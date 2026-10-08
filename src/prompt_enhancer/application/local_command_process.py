"""Bounded command pipes and cancellation scoped to the owning Agent turn."""

from __future__ import annotations

import locale
import math
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, BinaryIO

from .local_agent_limits import DEFAULT_COMMAND_SECONDS, MAX_COMMAND_SECONDS, MAX_TOOL_RESULT_CHARS
from .runtime_cancellation import (
    RuntimeCleanupUnconfirmed, RuntimeCooperativeStop, current_runtime_cancellation,
)


COMMAND_POLL_SECONDS = 0.025
COMMAND_CLEANUP_SECONDS = 2.0
_READ_BYTES = 16 * 1024
_TAIL_BYTES = MAX_TOOL_RESULT_CHARS * 4
_ENV_KEEP = frozenset({
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "LANG", "LC_ALL",
    "TERM", "SHELL", "USERNAME", "USER", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
    "PYTHONIOENCODING", "VIRTUAL_ENV", "NVM_DIR", "JAVA_HOME", "CARGO_HOME", "GOPATH",
})


def minimal_environment() -> dict[str, str]:
    """Approved commands inherit reviewed locations, not app/provider secrets."""

    environment = {key: value for key, value in os.environ.items() if key.upper() in _ENV_KEEP}
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUTF8", "1")
    return environment


class CommandCancelled(RuntimeCooperativeStop):
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        super().__init__("tool_cancelled")
        self.stdout, self.stderr = stdout, stderr


class CommandResult(subprocess.CompletedProcess[str]):
    def __init__(self, argv: list[str], code: int, stdout: str, stderr: str, *, truncated: bool) -> None:
        super().__init__(argv, code, stdout, stderr)
        self.output_truncated = truncated


class _OutputTail:
    """Only a bounded raw tail is retained while the child is running."""

    def __init__(self, stream: BinaryIO, encoding: str, errors: str) -> None:
        self.stream, self.encoding, self.errors = stream, encoding, errors
        self.data = bytearray()
        self.truncated = False
        self.failed = False

    def drain(self) -> None:
        try:
            while chunk := self.stream.read(_READ_BYTES):
                self.data.extend(chunk)
                if len(self.data) > _TAIL_BYTES:
                    del self.data[:-_TAIL_BYTES]
                    self.truncated = True
        except Exception:
            self.failed = True
        finally:
            try:
                self.stream.close()
            except OSError:
                self.failed = True

    def text(self) -> str:
        value = self.data.decode(self.encoding, errors=self.errors).replace("\r\n", "\n").replace("\r", "\n")
        if len(value) > MAX_TOOL_RESULT_CHARS:
            self.truncated = True
            value = value[-MAX_TOOL_RESULT_CHARS:]
        return value


class _PosixCommandGroup:
    def __init__(self, argv: list[str], *, cwd: str | None, env: dict[str, str]) -> None:
        self._process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        self.pid, self.stdout, self.stderr = self._process.pid, self._process.stdout, self._process.stderr

    def poll(self) -> int | None:
        return self._process.poll()

    def tree_exited(self) -> bool:
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def terminate(self) -> None:
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def close(self, *, close_streams: bool = True) -> bool:
        closed = True
        if close_streams:
            for stream in (self.stdout, self.stderr):
                try:
                    stream.close()
                except OSError:
                    closed = False
        return closed


def _start_process(argv: list[str], *, cwd: str | None, env: dict[str, str]):
    if sys.platform == "win32":
        from .local_command_windows import WindowsCommandJob

        return WindowsCommandJob(argv, cwd=cwd, env=env)
    return _PosixCommandGroup(argv, cwd=cwd, env=env)


def _cleanup(process: Any, threads: list[threading.Thread], *, terminate: bool) -> bool:
    """Reap the owned process group and pipe workers before claiming cleanup."""

    deadline = time.monotonic() + COMMAND_CLEANUP_SECONDS
    confirmed = False
    if terminate:
        try:
            process.terminate()
        except Exception:
            pass  # Positive exit/accounting evidence below remains mandatory.
    while True:
        try:
            confirmed = process.poll() is not None and process.tree_exited()
        except Exception:
            break
        if confirmed or time.monotonic() >= deadline:
            break
        time.sleep(COMMAND_POLL_SECONDS)
    joined = True
    for thread in threads:
        try:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
            joined = not thread.is_alive() and joined
        except Exception:
            joined = False
    try:
        closed = process.close(close_streams=joined)
    except Exception:
        closed = False
    return confirmed and joined and closed


def run_with_tree_kill(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run an approved, noninteractive command with bounded I/O and ownership.

    The historical import name is retained. A root shell exiting is not enough:
    descendants and pipe workers must finish too. Stop/timeout terminate only
    this command's owned group; uncertainty supersedes every apparent success.
    """

    timeout = kwargs.pop("timeout", DEFAULT_COMMAND_SECONDS)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 0 < timeout <= MAX_COMMAND_SECONDS):
        raise ValueError("command_timeout_invalid")
    cwd = kwargs.pop("cwd", None)
    env = kwargs.pop("env", None)
    encoding = kwargs.pop("encoding", None) or locale.getpreferredencoding(False)
    errors = kwargs.pop("errors", "replace")
    stdin = kwargs.pop("stdin", subprocess.DEVNULL)
    text_mode = kwargs.pop("text", True)
    capture = kwargs.pop("capture_output", True)
    if kwargs or stdin != subprocess.DEVNULL or text_mode is not True or capture is not True:
        raise ValueError("command_process_options_invalid")
    if not argv or any(not isinstance(value, str) or "\0" in value for value in argv):
        raise ValueError("command_arguments_invalid")
    cancellation = current_runtime_cancellation()
    if cancellation is not None and cancellation.is_set():
        raise CommandCancelled()
    deadline = time.monotonic() + timeout
    process = _start_process(argv, cwd=cwd, env=minimal_environment() if env is None else env)
    tails = [_OutputTail(stream, encoding, errors) for stream in (process.stdout, process.stderr)]
    threads: list[threading.Thread] = []
    failure: BaseException | None = None
    result = None
    try:
        for index, tail in enumerate(tails):
            thread = threading.Thread(target=tail.drain, name=f"agent-command-pipe-{index}", daemon=True)
            thread.start()
            threads.append(thread)
        while True:
            if cancellation is not None and cancellation.is_set():
                raise CommandCancelled()
            if any(tail.failed for tail in tails):
                raise OSError("command_output_unavailable")
            code = process.poll()
            if code is not None and process.tree_exited() and all(not thread.is_alive() for thread in threads):
                break
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("approved_command", timeout)
            time.sleep(COMMAND_POLL_SECONDS)
        if cancellation is not None and cancellation.is_set():
            raise CommandCancelled()
        stdout, stderr = (tail.text() for tail in tails)
        result = CommandResult(argv, code, stdout, stderr, truncated=any(tail.truncated for tail in tails))
    except BaseException as error:
        failure = error
    finally:
        confirmed = _cleanup(process, threads, terminate=result is None)
    if not confirmed:
        raise RuntimeCleanupUnconfirmed("command_cleanup_unconfirmed") from None
    if isinstance(failure, CommandCancelled):
        raise CommandCancelled(*(tail.text() for tail in tails)) from None
    if isinstance(failure, subprocess.TimeoutExpired):
        failure.output, failure.stderr = (tail.text() for tail in tails)
    if failure is not None:
        raise failure
    assert result is not None
    return result
