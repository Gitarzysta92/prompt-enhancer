"""Owned Windows command jobs using documented, atomic process admission.

Windows 10+ PROC_THREAD_ATTRIBUTE_JOB_LIST assigns ownership before execution.
Only the three stdio handles are inherited. No breakaway permission is added.
This controls ordinary descendant lifetime, not a security sandbox or external
services that an approved command might ask to perform work on its behalf.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
import shutil
import subprocess
import time
from typing import BinaryIO

from .runtime_cancellation import RuntimeCleanupUnconfirmed, RuntimeCooperativeStop, current_runtime_cancellation


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


_MAX_TRACKED_JOB_PROCESSES = 256


class _ProcessIdList(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wintypes.DWORD),
        ("NumberOfProcessIdsInList", wintypes.DWORD),
        ("ProcessIdList", ctypes.c_size_t * _MAX_TRACKED_JOB_PROCESSES),
    ]


@lru_cache(maxsize=1)
def _kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "InitializeProcThreadAttributeList": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "UpdateProcThreadAttribute": ([ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
        "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo)], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = arguments, result
    return api


@lru_cache(maxsize=1)
def _user():
    api = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    api.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    api.EnumWindows.restype = wintypes.BOOL
    api.IsWindowVisible.argtypes = (wintypes.HWND,)
    api.IsWindowVisible.restype = wintypes.BOOL
    api.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    return api, callback_type


def _require(success: object) -> None:
    if not success:
        raise OSError("command_process_control_failed")


def _resolved_executable(argv0: str, *, cwd: str | None, env: dict[str, str]) -> str:
    """Resolve the program before passing an explicit CreateProcess image path."""

    if not argv0 or "\0" in argv0:
        raise OSError("command_executable_invalid")
    has_directory = bool(os.path.dirname(argv0))
    if has_directory:
        candidate = argv0 if os.path.isabs(argv0) else os.path.join(cwd or os.getcwd(), argv0)
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            return candidate
        resolved = shutil.which(candidate, path=env.get("PATH"))
    else:
        resolved = shutil.which(argv0, path=env.get("PATH"))
    if resolved is None:
        raise OSError("command_executable_unavailable")
    return os.path.abspath(resolved)


class WindowsCommandJob:
    """One immutable job handle owns the root and its normal descendants."""

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str | None,
        env: dict[str, str],
        pipe_stdin: bool = False,
        capture_output: bool = True,
        capture_stdout: bool | None = None,
        capture_stderr: bool | None = None,
        maximum_active_processes: int | None = None,
    ) -> None:
        import msvcrt

        self.stdin: BinaryIO | None = None
        self.stdout: BinaryIO | None = None
        self.stderr: BinaryIO | None = None
        self.pid = 0
        self._returncode: int | None = None
        self._process = None
        self._job = None
        self._api = api = _kernel()
        descriptors: list[int] = []
        attributes = None
        initialized = False
        info = _ProcessInfo()
        problem: BaseException | None = None
        setup_cleanup_failed = False
        try:
            self._job = api.CreateJobObjectW(None, None)
            _require(self._job)
            limits = _ExtendedLimits()
            if (
                maximum_active_processes is not None
                and (
                    isinstance(maximum_active_processes, bool)
                    or not 1 <= maximum_active_processes <= _MAX_TRACKED_JOB_PROCESSES
                )
            ):
                raise ValueError("command_process_limit_invalid")
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if maximum_active_processes is not None:
                limits.BasicLimitInformation.LimitFlags |= 0x00000008  # ACTIVE_PROCESS
                limits.BasicLimitInformation.ActiveProcessLimit = maximum_active_processes
            _require(api.SetInformationJobObject(self._job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))

            stdout_captured = capture_output if capture_stdout is None else capture_stdout
            stderr_captured = capture_output if capture_stderr is None else capture_stderr
            if not isinstance(stdout_captured, bool) or not isinstance(stderr_captured, bool):
                raise ValueError("command_process_capture_invalid")

            output_readers: list[int | None] = []
            output_fds: list[int] = []
            for captured in (stdout_captured, stderr_captured):
                if captured:
                    reader, writer = os.pipe()
                    descriptors.extend((reader, writer))
                    output_readers.append(reader)
                    output_fds.append(writer)
                else:
                    writer = os.open(
                        os.devnull,
                        os.O_WRONLY | getattr(os, "O_BINARY", 0),
                    )
                    descriptors.append(writer)
                    output_readers.append(None)
                    output_fds.append(writer)
            if pipe_stdin:
                input_fd, input_writer = os.pipe()
                descriptors.extend((input_fd, input_writer))
            else:
                input_fd = os.open(os.devnull, os.O_RDONLY | getattr(os, "O_BINARY", 0))
                input_writer = None
                descriptors.append(input_fd)
            inherited = (wintypes.HANDLE * 3)(*(
                msvcrt.get_osfhandle(fd) for fd in (input_fd, *output_fds)
            ))
            for handle in inherited:
                os.set_handle_inheritable(handle, True)
            jobs = (wintypes.HANDLE * 1)(self._job)

            size = ctypes.c_size_t()
            api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            _require(size.value)
            attributes = ctypes.create_string_buffer(size.value)
            _require(api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)))
            initialized = True
            for key, values in ((0x20002, inherited), (0x2000D, jobs)):
                _require(api.UpdateProcThreadAttribute(attributes, 0, key,
                    ctypes.byref(values), ctypes.sizeof(values), None, None))

            startup = _StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x101  # USESTDHANDLES | USESHOWWINDOW
            startup.StartupInfo.wShowWindow = 0  # SW_HIDE
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = inherited
            startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
            executable = _resolved_executable(argv[0], cwd=cwd, env=env)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment = ctypes.create_unicode_buffer(
                "\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda item: item[0].upper())) + "\0\0"
            )
            if output_readers[0] is not None:
                self.stdout = os.fdopen(output_readers[0], "rb", buffering=0)
                descriptors.remove(output_readers[0])
            if output_readers[1] is not None:
                self.stderr = os.fdopen(output_readers[1], "rb", buffering=0)
                descriptors.remove(output_readers[1])
            if input_writer is not None:
                self.stdin = os.fdopen(input_writer, "wb", buffering=0)
                descriptors.remove(input_writer)
            cancellation = current_runtime_cancellation()
            if cancellation is not None and cancellation.is_set():
                raise RuntimeCooperativeStop("tool_cancelled")
            # Atomic job admission is mandatory. Never fall back to an
            # unowned child if the host cannot apply these attributes.
            _require(api.CreateProcessW(executable, command, None, None, True,
                0x08080400,  # NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | UNICODE_ENVIRONMENT
                environment, cwd, ctypes.byref(startup), ctypes.byref(info)))
            self._process, self.pid = info.hProcess, int(info.dwProcessId)
        except BaseException as error:
            problem = error
        finally:
            if info.hThread:
                try:
                    setup_cleanup_failed = not bool(api.CloseHandle(info.hThread))
                except Exception:
                    setup_cleanup_failed = True
            if initialized:
                try:
                    api.DeleteProcThreadAttributeList(attributes)
                except Exception:
                    setup_cleanup_failed = True
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except Exception:
                    setup_cleanup_failed = True
        if problem is not None or setup_cleanup_failed:
            confirmed = not bool(self._process)
            if self._process:
                deadline = time.monotonic() + 2
                try:
                    self.terminate()
                except Exception:
                    pass
                while time.monotonic() < deadline:
                    try:
                        confirmed = self.poll() is not None and self.tree_exited()
                    except Exception:
                        break
                    if confirmed:
                        break
                    time.sleep(0.025)
            closed = self.close()
            if not confirmed or not closed or setup_cleanup_failed:
                raise RuntimeCleanupUnconfirmed("command_cleanup_unconfirmed") from None
            assert problem is not None
            raise problem

    def poll(self) -> int | None:
        if not self._process:
            return self._returncode
        wait = self._api.WaitForSingleObject(self._process, 0)
        if wait == 258:  # WAIT_TIMEOUT
            return None
        _require(wait == 0)
        code = wintypes.DWORD()
        _require(self._api.GetExitCodeProcess(self._process, ctypes.byref(code)))
        self._returncode = int(code.value)
        return self._returncode

    @property
    def returncode(self) -> int | None:
        """Expose the Popen-compatible status used by bounded helper runners."""

        return self.poll()

    def tree_exited(self) -> bool:
        accounting = _Accounting()
        _require(self._api.QueryInformationJobObject(self._job, 1,
            ctypes.byref(accounting), ctypes.sizeof(accounting), None))
        return accounting.ActiveProcesses == 0

    def active_process_ids(self) -> tuple[int, ...]:
        processes = _ProcessIdList()
        _require(self._api.QueryInformationJobObject(
            self._job,
            3,  # JobObjectBasicProcessIdList
            ctypes.byref(processes),
            ctypes.sizeof(processes),
            None,
        ))
        assigned = int(processes.NumberOfAssignedProcesses)
        listed = int(processes.NumberOfProcessIdsInList)
        if assigned != listed or listed > _MAX_TRACKED_JOB_PROCESSES:
            raise OSError("command_process_inventory_unavailable")
        return tuple(int(processes.ProcessIdList[index]) for index in range(listed))

    def visible_window_detected(self) -> bool:
        """Return whether this exact job currently owns a visible top-level window."""

        process_ids = frozenset(self.active_process_ids())
        if not process_ids:
            return False
        user, callback_type = _user()
        found = False

        @callback_type
        def inspect(window: int, _parameter: int) -> bool:
            nonlocal found
            if not user.IsWindowVisible(window):
                return True
            process_id = wintypes.DWORD()
            if user.GetWindowThreadProcessId(window, ctypes.byref(process_id)):
                if int(process_id.value) in process_ids:
                    found = True
                    return False
            return True

        completed = bool(user.EnumWindows(inspect, 0))
        if not completed and not found:
            raise OSError("command_window_inventory_unavailable")
        return found

    def terminate(self) -> None:
        _require(self._api.TerminateJobObject(self._job, 1))

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll()
            if code is not None and self.tree_exited():
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("owned-windows-job", timeout)
            time.sleep(0.025)

    def close(self, *, close_streams: bool = True) -> bool:
        closed = True
        if close_streams:
            for stream in (self.stdin, self.stdout, self.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        closed = False
        for name in ("_process", "_job"):
            handle = getattr(self, name)
            if handle:
                try:
                    closed = bool(self._api.CloseHandle(handle)) and closed
                except Exception:
                    closed = False
                setattr(self, name, None)
        return closed
