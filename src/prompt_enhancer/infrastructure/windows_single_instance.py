"""Bounded Windows single-instance ownership for native application windows.

The mutex name and window title are fixed application constants.  No path,
account, workspace, model, prompt, session, process identifier, or exception
text is retained or rendered by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import sys
import time
from typing import Any, Callable


ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


class WindowsSingleInstanceError(RuntimeError):
    """Raised without retaining native API diagnostics or machine details."""


@dataclass(slots=True)
class WindowsInstanceLease:
    """One process-held named mutex handle with idempotent release."""

    _handle: Any
    _close_handle: Callable[[Any], object]
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            closed = bool(self._close_handle(self._handle))
        except Exception:
            closed = False
        self._handle = None
        if not closed:
            raise WindowsSingleInstanceError("single_instance_release_failed") from None


def _kernel32() -> Any:
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    library.CreateMutexW.restype = wintypes.HANDLE
    library.CloseHandle.argtypes = [wintypes.HANDLE]
    library.CloseHandle.restype = wintypes.BOOL
    return library


def _user32() -> Any:
    library = ctypes.WinDLL("user32", use_last_error=True)
    library.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    library.FindWindowW.restype = wintypes.HWND
    library.IsIconic.argtypes = [wintypes.HWND]
    library.IsIconic.restype = wintypes.BOOL
    library.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    library.ShowWindow.restype = wintypes.BOOL
    library.SetForegroundWindow.argtypes = [wintypes.HWND]
    library.SetForegroundWindow.restype = wintypes.BOOL
    return library


def acquire_windows_instance(
    name: str,
    *,
    kernel: Any | None = None,
    get_last_error: Callable[[], int] | None = None,
    set_last_error: Callable[[int], None] | None = None,
) -> WindowsInstanceLease | None:
    """Acquire ``name`` or return ``None`` when another process owns it.

    Returning ``None`` is an ordinary duplicate-launch result, not an error.
    The duplicate handle is closed before returning so repeated clicks cannot
    accumulate native resources.
    """

    if sys.platform != "win32":
        raise WindowsSingleInstanceError("single_instance_platform_unsupported")
    if not name.startswith("Local\\PromptEnhancer.") or not 1 <= len(name) <= 120:
        raise WindowsSingleInstanceError("single_instance_name_invalid")
    api = kernel or _kernel32()
    last_error = get_last_error or getattr(ctypes, "get_last_error", lambda: 0)
    reset_last_error = set_last_error or getattr(ctypes, "set_last_error", lambda _value: None)
    try:
        reset_last_error(0)
        handle = api.CreateMutexW(None, False, name)
        error_code = int(last_error())
    except Exception:
        raise WindowsSingleInstanceError("single_instance_acquire_failed") from None
    if not handle:
        raise WindowsSingleInstanceError("single_instance_acquire_failed") from None
    if error_code == ERROR_ALREADY_EXISTS:
        try:
            closed = bool(api.CloseHandle(handle))
        except Exception:
            closed = False
        if not closed:
            raise WindowsSingleInstanceError("single_instance_release_failed") from None
        return None
    return WindowsInstanceLease(handle, api.CloseHandle)


def focus_existing_window(
    title: str,
    *,
    timeout_seconds: float = 2.0,
    poll_seconds: float = 0.05,
    user: Any | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Restore and focus one exact-title window within a bounded wait.

    A duplicate launch can race the primary window's creation.  This short
    wait lets a normal second click focus that primary without ever creating a
    second backend or WebView.  Failure to focus is reported only as ``False``;
    it must not trigger a fallback launch.
    """

    if sys.platform != "win32" or not title or len(title) > 160:
        return False
    if timeout_seconds < 0 or timeout_seconds > 5 or poll_seconds <= 0:
        return False
    try:
        api = user or _user32()
    except Exception:
        return False
    deadline = monotonic() + timeout_seconds
    while True:
        try:
            window = api.FindWindowW(None, title)
        except Exception:
            return False
        if window:
            try:
                if api.IsIconic(window):
                    api.ShowWindow(window, SW_RESTORE)
                return bool(api.SetForegroundWindow(window))
            except Exception:
                return False
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(poll_seconds, remaining))


__all__ = [
    "WindowsInstanceLease",
    "WindowsSingleInstanceError",
    "acquire_windows_instance",
    "focus_existing_window",
]
