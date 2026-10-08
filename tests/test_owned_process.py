"""Synthetic proof for the shared local helper process-lifetime boundary."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from prompt_enhancer.application import owned_process
from prompt_enhancer.application.owned_process import (
    OwnedProcessRunError,
    process_tree_exited,
    run_owned_process,
    start_owned_process,
    terminate_owned_process,
)


def _environment() -> dict[str, str]:
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    return {key: value for key, value in os.environ.items() if key.upper() in keep}


def _process_running(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return (
            bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
            and code.value == 259
        )
    finally:
        kernel.CloseHandle(handle)


def test_invalid_command_is_rejected_before_process_creation() -> None:
    with pytest.raises(ValueError, match="^owned_process_arguments_invalid$"):
        start_owned_process([], cwd=None, env={})
    with pytest.raises(ValueError, match="^owned_process_arguments_invalid$"):
        start_owned_process(["example\0command"], cwd=None, env={})


def test_owned_process_captures_only_requested_streams(tmp_path: Path) -> None:
    process = start_owned_process(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; print('synthetic-output'); print('discarded', file=sys.stderr)",
        ],
        cwd=tmp_path,
        env=_environment(),
        capture_stdout=True,
        capture_stderr=False,
        maximum_active_processes=4,
    )
    try:
        assert process.stdout is not None
        assert process.stderr is None
        output = process.stdout.read()
        assert process.wait(timeout=3) == 0
        assert output.strip() == b"synthetic-output"
        assert process_tree_exited(process)
    finally:
        terminate_owned_process(process, graceful_timeout=0.1)
        assert process.close()


def test_bounded_owned_run_round_trips_stdin_without_stderr(tmp_path: Path) -> None:
    result = run_owned_process(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import sys; payload=sys.stdin.buffer.read(); "
                "sys.stdout.buffer.write(payload.upper()); "
                "sys.stderr.buffer.write(b'discarded')"
            ),
        ],
        cwd=tmp_path,
        env=_environment(),
        stdin_payload=b"synthetic-input",
        stdout_limit=128,
        timeout=3,
        maximum_active_processes=4,
    )

    assert result.returncode == 0
    assert result.stdout == b"SYNTHETIC-INPUT"
    assert result.stderr == b""


def test_bounded_owned_run_stops_on_output_overflow(tmp_path: Path) -> None:
    with pytest.raises(
        OwnedProcessRunError, match="^owned_process_stdout_limit$"
    ):
        run_owned_process(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys,time; sys.stdout.write('x'*65536); sys.stdout.flush(); time.sleep(5)",
            ],
            cwd=tmp_path,
            env=_environment(),
            stdout_limit=32,
            timeout=3,
            maximum_active_processes=4,
        )


def test_repeated_bounded_runs_leave_no_roots_or_visible_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_ids: list[int] = []
    visible_windows: list[bool] = []
    original = owned_process.start_owned_process

    def capture_start(*args: object, **kwargs: object):
        process = original(*args, **kwargs)
        process_ids.append(process.pid)
        visible_windows.append(process.visible_window_detected())
        return process

    monkeypatch.setattr(owned_process, "start_owned_process", capture_start)
    for index in range(12):
        result = owned_process.run_owned_process(
            [
                sys.executable,
                "-I",
                "-c",
                f"import time; time.sleep(0.01); print('synthetic-{index}')",
            ],
            cwd=tmp_path,
            env=_environment(),
            stdout_limit=128,
            timeout=3,
            maximum_active_processes=4,
        )
        assert result.returncode == 0

    assert len(process_ids) == 12
    assert visible_windows == [False] * 12
    assert all(not _process_running(pid) for pid in process_ids)


def test_owned_process_termination_reaps_a_descendant_tree(tmp_path: Path) -> None:
    marker = tmp_path / "synthetic-descendant-survived"
    descendant = (
        "import pathlib,time; time.sleep(1); "
        f"pathlib.Path({str(marker)!r}).write_text('unexpected','utf-8')"
    )
    root = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
        "time.sleep(5)"
    )
    process = start_owned_process(
        [sys.executable, "-I", "-c", root],
        cwd=tmp_path,
        env=_environment(),
        maximum_active_processes=4,
    )
    try:
        assert terminate_owned_process(
            process,
            graceful_timeout=0.2,
            forced_timeout=1.0,
        )
        assert process_tree_exited(process)
    finally:
        process.close()
    time.sleep(1.2)
    assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows hidden Job contract")
def test_windows_owned_process_has_no_visible_window_and_no_breakaway(
    tmp_path: Path,
) -> None:
    process = start_owned_process(
        [sys.executable, "-I", "-c", "import time; time.sleep(0.2)"],
        cwd=tmp_path,
        env=_environment(),
        maximum_active_processes=4,
    )
    try:
        assert process.visible_window_detected() is False
        assert process.wait(timeout=3) == 0
        assert process_tree_exited(process)
    finally:
        terminate_owned_process(process, graceful_timeout=0.1)
        process.close()
