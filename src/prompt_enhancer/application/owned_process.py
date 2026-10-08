"""Cross-platform process ownership for bounded local helpers.

Windows children are admitted to a kill-on-close Job Object at creation, before
their first instruction can spawn a descendant. POSIX children receive a new
process group. This is a lifetime boundary, not a sandbox: callers must still
validate commands, minimize environments, bound I/O, and gate authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import BinaryIO, Protocol, Sequence

from .runtime_cancellation import RuntimeCleanupUnconfirmed


class OwnedProcess(Protocol):
    pid: int
    stdin: BinaryIO | None
    stdout: BinaryIO | None
    stderr: BinaryIO | None

    @property
    def returncode(self) -> int | None: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def tree_exited(self) -> bool: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def close(self, *, close_streams: bool = True) -> bool: ...

    def visible_window_detected(self) -> bool: ...


class OwnedProcessRunError(RuntimeError):
    """Content-free failure from a bounded owned helper process."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r})"


@dataclass(frozen=True, slots=True)
class OwnedProcessResult:
    returncode: int
    stdout: bytes = field(default=b"", repr=False)
    stderr: bytes = field(default=b"", repr=False)


class _PosixOwnedProcess:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        pipe_stdin: bool,
        capture_stdout: bool,
        capture_stderr: bool,
    ) -> None:
        self._process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if pipe_stdin else subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
            bufsize=0,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
        self.pid = self._process.pid
        self.stdin = self._process.stdin
        self.stdout = self._process.stdout
        self.stderr = self._process.stderr

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        code = self._process.wait(timeout=timeout)
        while not self.tree_exited():
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("owned-posix-process", timeout)
            time.sleep(0.01)
        return code

    def tree_exited(self) -> bool:
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def terminate(self) -> None:
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def kill(self) -> None:
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self, *, close_streams: bool = True) -> bool:
        closed = True
        if close_streams:
            for stream in (self.stdin, self.stdout, self.stderr):
                if stream is None:
                    continue
                try:
                    stream.close()
                except (OSError, ValueError):
                    closed = False
        return closed

    @staticmethod
    def visible_window_detected() -> bool:
        return False


def start_owned_process(
    argv: Sequence[str],
    *,
    cwd: str | Path | None,
    env: dict[str, str],
    pipe_stdin: bool = False,
    capture_stdout: bool = False,
    capture_stderr: bool = False,
    maximum_active_processes: int | None = None,
) -> OwnedProcess:
    """Start one direct child under an atomic descendant-lifetime boundary."""

    command = list(argv)
    if not command or any(
        not isinstance(value, str) or not value or "\0" in value
        for value in command
    ):
        raise ValueError("owned_process_arguments_invalid")
    working_directory = None if cwd is None else os.fspath(cwd)
    if os.name == "nt":
        from .local_command_windows import WindowsCommandJob

        return WindowsCommandJob(
            command,
            cwd=working_directory,
            env=env,
            pipe_stdin=pipe_stdin,
            capture_output=False,
            capture_stdout=capture_stdout,
            capture_stderr=capture_stderr,
            maximum_active_processes=maximum_active_processes,
        )
    return _PosixOwnedProcess(
        command,
        cwd=working_directory,
        env=env,
        pipe_stdin=pipe_stdin,
        capture_stdout=capture_stdout,
        capture_stderr=capture_stderr,
    )


def process_tree_exited(process: OwnedProcess) -> bool:
    """Return positive root-and-tree exit evidence, never root exit alone."""

    return process.poll() is not None and process.tree_exited()


def terminate_owned_process(
    process: OwnedProcess,
    *,
    graceful_timeout: float,
    forced_timeout: float = 1.0,
) -> bool:
    """Stop an exact owned tree and return whether cleanup was confirmed."""

    if graceful_timeout < 0 or forced_timeout < 0:
        raise ValueError("owned_process_timeout_invalid")
    try:
        if process_tree_exited(process):
            return True
    except Exception:
        return False
    try:
        process.terminate()
    except Exception:
        pass
    try:
        process.wait(timeout=max(graceful_timeout, 0.001))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        if process_tree_exited(process):
            return True
    except Exception:
        return False
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=max(forced_timeout, 0.001))
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        return process_tree_exited(process)
    except Exception:
        return False


def _read_bounded_stream(
    stream: BinaryIO,
    *,
    limit: int,
    destination: bytearray,
    overflow: threading.Event,
) -> None:
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            remaining = limit - len(destination)
            if remaining > 0:
                destination.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                overflow.set()
                return
    except (OSError, ValueError):
        return


def _write_process_input(stream: BinaryIO, payload: bytes) -> None:
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = stream.write(view[offset : offset + 64 * 1024])
            if written is None:
                written = 0
            if written <= 0:
                break
            offset += written
            stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def run_owned_process(
    argv: Sequence[str],
    *,
    cwd: str | Path | None,
    env: dict[str, str],
    stdin_payload: bytes = b"",
    stdout_limit: int = 0,
    stderr_limit: int = 0,
    timeout: float,
    maximum_active_processes: int | None = None,
    termination_grace: float = 0.25,
) -> OwnedProcessResult:
    """Run a hidden owned tree with bounded input, output, time, and cleanup."""

    if (
        not isinstance(stdin_payload, bytes)
        or isinstance(stdout_limit, bool)
        or not isinstance(stdout_limit, int)
        or stdout_limit < 0
        or isinstance(stderr_limit, bool)
        or not isinstance(stderr_limit, int)
        or stderr_limit < 0
        or isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < float(timeout) <= 3_600
        or isinstance(termination_grace, bool)
        or not isinstance(termination_grace, (int, float))
        or not 0 <= float(termination_grace) <= 10
    ):
        raise ValueError("owned_process_run_limits_invalid")

    try:
        process = start_owned_process(
            argv,
            cwd=cwd,
            env=env,
            pipe_stdin=bool(stdin_payload),
            capture_stdout=stdout_limit > 0,
            capture_stderr=stderr_limit > 0,
            maximum_active_processes=maximum_active_processes,
        )
    except (
        FileNotFoundError,
        PermissionError,
        OSError,
        RuntimeCleanupUnconfirmed,
        ValueError,
    ):
        raise OwnedProcessRunError("owned_process_unavailable") from None

    stdout = bytearray()
    stderr = bytearray()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()
    threads: list[threading.Thread] = []
    if process.stdout is not None:
        threads.append(
            threading.Thread(
                target=_read_bounded_stream,
                kwargs={
                    "stream": process.stdout,
                    "limit": stdout_limit,
                    "destination": stdout,
                    "overflow": stdout_overflow,
                },
                name="prompt-enhancer-owned-stdout",
                daemon=True,
            )
        )
    if process.stderr is not None:
        threads.append(
            threading.Thread(
                target=_read_bounded_stream,
                kwargs={
                    "stream": process.stderr,
                    "limit": stderr_limit,
                    "destination": stderr,
                    "overflow": stderr_overflow,
                },
                name="prompt-enhancer-owned-stderr",
                daemon=True,
            )
        )
    if process.stdin is not None:
        threads.append(
            threading.Thread(
                target=_write_process_input,
                args=(process.stdin, stdin_payload),
                name="prompt-enhancer-owned-stdin",
                daemon=True,
            )
        )
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + float(timeout)
    terminal_reason: str | None = None
    while True:
        try:
            if process_tree_exited(process):
                break
        except Exception:
            terminal_reason = "owned_process_cleanup_unconfirmed"
            break
        if stdout_overflow.is_set():
            terminal_reason = "owned_process_stdout_limit"
            break
        if stderr_overflow.is_set():
            terminal_reason = "owned_process_stderr_limit"
            break
        if time.monotonic() >= deadline:
            terminal_reason = "owned_process_timeout"
            break
        time.sleep(0.005)

    cleanup_confirmed = True
    if terminal_reason is not None:
        cleanup_confirmed = terminate_owned_process(
            process,
            graceful_timeout=float(termination_grace),
            forced_timeout=1.0,
        )

    for thread in threads:
        thread.join(timeout=1)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            cleanup_confirmed = False
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=0.1)

    returncode: int | None = None
    try:
        observed_returncode = process.returncode
        if observed_returncode is not None:
            returncode = int(observed_returncode)
    except Exception:
        returncode = None
    try:
        handles_closed = bool(process.close(close_streams=False))
    except Exception:
        handles_closed = False

    if terminal_reason is None and stdout_overflow.is_set():
        terminal_reason = "owned_process_stdout_limit"
    if terminal_reason is None and stderr_overflow.is_set():
        terminal_reason = "owned_process_stderr_limit"
    if (
        not cleanup_confirmed
        or not handles_closed
        or returncode is None
        or any(thread.is_alive() for thread in threads)
    ):
        terminal_reason = "owned_process_cleanup_unconfirmed"
    if terminal_reason is not None:
        raise OwnedProcessRunError(terminal_reason)
    return OwnedProcessResult(
        returncode=returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
    )


__all__ = (
    "OwnedProcess",
    "OwnedProcessResult",
    "OwnedProcessRunError",
    "process_tree_exited",
    "run_owned_process",
    "start_owned_process",
    "terminate_owned_process",
)
