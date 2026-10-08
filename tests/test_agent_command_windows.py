"""Windows atomic ownership failures, using only a finite sleeping child."""

from __future__ import annotations

import ctypes
import subprocess
import sys

import pytest

from prompt_enhancer.application import local_command_windows as windows
from prompt_enhancer.application.local_command_process import minimal_environment
from prompt_enhancer.application.runtime_cancellation import RuntimeCleanupUnconfirmed


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object contract")


@pytest.mark.parametrize("fault", ["job-attribute", "create-refused", "thread-close", "attribute-release"])
def test_native_admission_and_setup_failure_never_leave_an_unowned_child(tmp_path, monkeypatch, fault):
    native = windows._kernel()

    class ControlledKernel:
        job = process = thread = None
        created = 0
        root_exited = False
        tree_exited = False
        closed = set()
        active_limit = None
        application_name = None
        creation_flags = None

        def __getattr__(self, name):
            return getattr(native, name)

        def CreateJobObjectW(self, *args):
            self.job = native.CreateJobObjectW(*args)
            return self.job

        def SetInformationJobObject(self, *args):
            if args[1] == 9:
                limits = ctypes.cast(
                    args[2],
                    ctypes.POINTER(windows._ExtendedLimits),
                ).contents
                self.active_limit = (
                    int(limits.BasicLimitInformation.LimitFlags),
                    int(limits.BasicLimitInformation.ActiveProcessLimit),
                )
            return native.SetInformationJobObject(*args)

        def UpdateProcThreadAttribute(self, *args):
            if fault == "job-attribute" and args[2] == 0x2000D:
                return 0
            return native.UpdateProcThreadAttribute(*args)

        def CreateProcessW(self, *args):
            self.created += 1
            self.application_name = args[0]
            self.creation_flags = int(args[5])
            if fault == "create-refused":
                return 0
            result = native.CreateProcessW(*args)
            if result:
                info = ctypes.cast(args[-1], ctypes.POINTER(windows._ProcessInfo)).contents
                self.process, self.thread = info.hProcess, info.hThread
            return result

        def CloseHandle(self, handle):
            result = native.CloseHandle(handle)
            if result:
                self.closed.add(handle)
            if fault == "thread-close" and handle == self.thread:
                raise OSError("EXAMPLE_PRIVATE_RELEASE_CANARY")
            return result

        def DeleteProcThreadAttributeList(self, *args):
            native.DeleteProcThreadAttributeList(*args)
            if fault == "attribute-release":
                raise OSError("EXAMPLE_PRIVATE_RELEASE_CANARY")

        def WaitForSingleObject(self, *args):
            result = native.WaitForSingleObject(*args)
            if args[0] == self.process and result == 0:
                self.root_exited = True
            return result

        def QueryInformationJobObject(self, *args):
            result = native.QueryInformationJobObject(*args)
            if result:
                accounting = ctypes.cast(args[2], ctypes.POINTER(windows._Accounting)).contents
                self.tree_exited = accounting.ActiveProcesses == 0
            return result

    controlled = ControlledKernel()
    monkeypatch.setattr(windows, "_kernel", lambda: controlled)
    try:
        expected = OSError if fault in {"job-attribute", "create-refused"} else RuntimeCleanupUnconfirmed
        with pytest.raises(expected) as failed:
            windows.WindowsCommandJob(
                [sys.executable, "-I", "-c", "import time; time.sleep(5)"],
                cwd=str(tmp_path),
                env=minimal_environment(),
                maximum_active_processes=16,
            )
        assert "EXAMPLE_PRIVATE_RELEASE_CANARY" not in str(failed.value)
        assert controlled.job in controlled.closed
        assert controlled.created == (0 if fault == "job-attribute" else 1)
        assert controlled.active_limit is not None
        assert controlled.active_limit[0] & 0x00000008
        assert controlled.active_limit[0] & 0x00002000
        assert not controlled.active_limit[0] & 0x00000800
        assert not controlled.active_limit[0] & 0x00001000
        assert controlled.active_limit[1] == 16
        if controlled.created:
            assert controlled.application_name == sys.executable
            assert controlled.creation_flags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            assert not controlled.creation_flags & getattr(
                subprocess,
                "CREATE_BREAKAWAY_FROM_JOB",
                0x01000000,
            )
        if controlled.process:
            assert controlled.root_exited and controlled.tree_exited
            assert controlled.process in controlled.closed
    finally:
        # Even an intentionally reproduced failure cannot leave the test child.
        # Only exact handles created above are used; no process-name/PID scan.
        if controlled.job and controlled.job not in controlled.closed:
            native.TerminateJobObject(controlled.job, 1)
        if controlled.process and controlled.process not in controlled.closed:
            native.WaitForSingleObject(controlled.process, 3000)
        for handle in (controlled.thread, controlled.process, controlled.job):
            if handle and handle not in controlled.closed:
                native.CloseHandle(handle)


@pytest.mark.parametrize("value", [0, 257, True])
def test_invalid_windows_job_process_budget_starts_no_child(
    tmp_path,
    monkeypatch,
    value,
):
    native = windows._kernel()

    class CountingKernel:
        created = 0

        def __getattr__(self, name):
            return getattr(native, name)

        def CreateProcessW(self, *args):
            self.created += 1
            return native.CreateProcessW(*args)

    controlled = CountingKernel()
    monkeypatch.setattr(windows, "_kernel", lambda: controlled)
    with pytest.raises(ValueError, match="command_process_limit_invalid"):
        windows.WindowsCommandJob(
            [sys.executable, "-I", "-c", "raise SystemExit(0)"],
            cwd=str(tmp_path),
            env=minimal_environment(),
            maximum_active_processes=value,
        )
    assert controlled.created == 0
