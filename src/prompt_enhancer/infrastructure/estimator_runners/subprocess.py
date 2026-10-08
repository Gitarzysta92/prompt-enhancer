"""Bounded, content-silent subprocess execution for estimator adapters.

The helpers in this module never render stdin, stdout, stderr, environment
values, or working-directory paths in exceptions or representations. Provider
adapters consume the captured bytes in memory and discard them before crossing
their public boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess as _subprocess
import threading
import time
from typing import BinaryIO, Mapping

from pydantic import Field

from ...application.owned_process import (
    OwnedProcess,
    process_tree_exited,
    start_owned_process,
    terminate_owned_process,
)
from ...domain import StrictModel


class RunnerLimits(StrictModel):
    """Hard resource bounds applied before and during every process run."""

    timeout_ms: int = Field(default=120_000, ge=10, le=3_600_000)
    stdin_bytes: int = Field(default=4 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    stdout_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    stderr_bytes: int = Field(default=256 * 1024, ge=1, le=4 * 1024 * 1024)
    workspace_bytes: int = Field(default=32 * 1024 * 1024, ge=4096, le=256 * 1024 * 1024)
    termination_grace_ms: int = Field(default=250, ge=0, le=2_000)


class SafeRunnerError(RuntimeError):
    """A content-free runner failure suitable for API/job error mapping."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r})"


class RunnerInputTooLarge(SafeRunnerError):
    pass


class RunnerOutputLimitExceeded(SafeRunnerError):
    pass


class RunnerTimedOut(SafeRunnerError):
    pass


class RunnerCancelled(SafeRunnerError):
    pass


class RunnerProcessFailed(SafeRunnerError):
    pass


class RunnerWorkspaceLimitExceeded(SafeRunnerError):
    pass


class RunnerExecutableUnavailable(SafeRunnerError):
    pass


@dataclass(frozen=True, slots=True)
class _ProcessCapture:
    return_code: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "CODEX_HOME",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)


def _minimal_environment(
    source: Mapping[str, str] | None = None,
    *,
    temporary_directory: Path | None = None,
) -> dict[str, str]:
    """Copy only runtime location variables; never copy credential variables."""

    base = os.environ if source is None else source
    result = {
        key: value
        for key, value in base.items()
        if key.upper() in _ENVIRONMENT_ALLOWLIST and "\x00" not in value
    }
    if temporary_directory is not None:
        temporary = os.fspath(temporary_directory)
        result["TEMP"] = temporary
        result["TMP"] = temporary
    result.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "NO_COLOR": "1",
        }
    )
    return result


def _validate_argv(argv: tuple[str, ...]) -> None:
    if not argv or any(not item or "\x00" in item for item in argv):
        raise RunnerExecutableUnavailable("runner_invalid_argv")


def _read_bounded(
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
            if len(chunk) > remaining:
                overflow.set()
                return
    except (OSError, ValueError):
        return


def _write_stdin(stream: BinaryIO, payload: bytes) -> None:
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            written = stream.write(view[offset : offset + 64 * 1024])
            if written is None:
                written = 0
            offset += written
            stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _start_owned_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> OwnedProcess:
    """Start one helper with atomic Windows descendant ownership."""

    return start_owned_process(
        argv,
        cwd=cwd,
        env=environment,
        pipe_stdin=True,
        capture_stdout=True,
        capture_stderr=True,
        maximum_active_processes=32,
    )


def _terminate_process_tree(
    process: OwnedProcess,
    *,
    environment: Mapping[str, str],
    grace_ms: int,
) -> bool:
    del environment
    return terminate_owned_process(
        process,
        graceful_timeout=grace_ms / 1000,
        forced_timeout=1.0,
    )


def _run_bounded_process(
    *,
    argv: tuple[str, ...],
    stdin_payload: bytes,
    cwd: Path,
    limits: RunnerLimits,
    cancellation: threading.Event | None = None,
    environment_source: Mapping[str, str] | None = None,
    temporary_directory: Path | None = None,
) -> _ProcessCapture:
    """Run one direct process with bounded pipes and process-tree cancellation."""

    _validate_argv(argv)
    if len(stdin_payload) > limits.stdin_bytes:
        raise RunnerInputTooLarge("runner_stdin_limit")
    if cancellation is not None and cancellation.is_set():
        raise RunnerCancelled("runner_cancelled")

    environment = _minimal_environment(
        environment_source,
        temporary_directory=temporary_directory,
    )
    try:
        process = _start_owned_process(
            argv,
            cwd=cwd,
            environment=environment,
        )
    except (FileNotFoundError, PermissionError, OSError) as error:
        raise RunnerExecutableUnavailable("runner_executable_unavailable") from error

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    stdout = bytearray()
    stderr = bytearray()
    stdout_overflow = threading.Event()
    stderr_overflow = threading.Event()
    threads = (
        threading.Thread(
            target=_read_bounded,
            kwargs={
                "stream": process.stdout,
                "limit": limits.stdout_bytes,
                "destination": stdout,
                "overflow": stdout_overflow,
            },
            daemon=True,
        ),
        threading.Thread(
            target=_read_bounded,
            kwargs={
                "stream": process.stderr,
                "limit": limits.stderr_bytes,
                "destination": stderr,
                "overflow": stderr_overflow,
            },
            daemon=True,
        ),
        threading.Thread(
            target=_write_stdin,
            args=(process.stdin, stdin_payload),
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + limits.timeout_ms / 1000
    terminal_reason: str | None = None
    while True:
        try:
            process_finished = process_tree_exited(process)
        except Exception:
            terminal_reason = "runner_cleanup_unconfirmed"
            break
        if process_finished:
            break
        if stdout_overflow.is_set():
            terminal_reason = "runner_stdout_limit"
            break
        if stderr_overflow.is_set():
            terminal_reason = "runner_stderr_limit"
            break
        if cancellation is not None and cancellation.is_set():
            terminal_reason = "runner_cancelled"
            break
        if time.monotonic() >= deadline:
            terminal_reason = "runner_timed_out"
            break
        time.sleep(0.005)

    if terminal_reason is not None:
        cleanup_confirmed = _terminate_process_tree(
            process,
            environment=environment,
            grace_ms=limits.termination_grace_ms,
        )
    else:
        cleanup_confirmed = True

    for thread in threads:
        thread.join(timeout=1)
    for pipe in (process.stdout, process.stderr):
        try:
            pipe.close()
        except (OSError, ValueError):
            pass
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=0.1)

    return_code: int | None = None
    try:
        observed_return_code = process.returncode
        if observed_return_code is not None:
            return_code = int(observed_return_code)
    except Exception:
        return_code = None

    close = getattr(process, "close", None)
    handles_closed = True
    if callable(close):
        try:
            handles_closed = bool(close(close_streams=False))
        except Exception:
            handles_closed = False

    if (
        not cleanup_confirmed
        or not handles_closed
        or any(thread.is_alive() for thread in threads)
        or return_code is None
    ):
        raise RunnerProcessFailed("runner_cleanup_unconfirmed")

    if terminal_reason is None and stdout_overflow.is_set():
        terminal_reason = "runner_stdout_limit"
    if terminal_reason is None and stderr_overflow.is_set():
        terminal_reason = "runner_stderr_limit"

    if terminal_reason == "runner_cancelled":
        raise RunnerCancelled(terminal_reason)
    if terminal_reason == "runner_timed_out":
        raise RunnerTimedOut(terminal_reason)
    if terminal_reason is not None:
        raise RunnerOutputLimitExceeded(terminal_reason)

    return _ProcessCapture(
        return_code=return_code,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
    )


def _workspace_size(root: Path) -> int:
    """Measure without following links; any link fails the workspace boundary."""

    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = tuple(os.scandir(directory))
        except OSError as error:
            raise RunnerWorkspaceLimitExceeded("runner_workspace_unreadable") from error
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise RunnerWorkspaceLimitExceeded("runner_workspace_link")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    raise RunnerWorkspaceLimitExceeded("runner_workspace_special_file")
            except OSError as error:
                raise RunnerWorkspaceLimitExceeded("runner_workspace_unreadable") from error
    return total


def _assert_workspace_bound(root: Path, limit: int) -> None:
    if _workspace_size(root) > limit:
        raise RunnerWorkspaceLimitExceeded("runner_workspace_limit")


__all__ = (
    "RunnerCancelled",
    "RunnerExecutableUnavailable",
    "RunnerInputTooLarge",
    "RunnerLimits",
    "RunnerOutputLimitExceeded",
    "RunnerProcessFailed",
    "RunnerTimedOut",
    "RunnerWorkspaceLimitExceeded",
    "SafeRunnerError",
)
