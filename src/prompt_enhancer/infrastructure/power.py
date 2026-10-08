"""Read-only, dependency-free local power-source detection."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys

from ..application.jobs import PowerSourceState


class _WindowsSystemPowerStatus(ctypes.Structure):
    _fields_ = (
        ("ac_line_status", ctypes.c_ubyte),
        ("battery_flag", ctypes.c_ubyte),
        ("battery_life_percent", ctypes.c_ubyte),
        ("system_status_flag", ctypes.c_ubyte),
        ("battery_life_time", ctypes.c_ulong),
        ("battery_full_life_time", ctypes.c_ulong),
    )


class LocalPowerSourceReader:
    """Best-effort detector that returns UNKNOWN on every unsupported/error path.

    The adapter only reads operating-system power status.  It has no network,
    provider, transcript, or credential access and does not mutate power state.
    """

    def current(self) -> PowerSourceState:
        try:
            if sys.platform == "win32":
                return self._windows_current()
            if sys.platform.startswith("linux"):
                return self._linux_current(Path("/sys/class/power_supply"))
        except Exception:
            return PowerSourceState.UNKNOWN
        return PowerSourceState.UNKNOWN

    @staticmethod
    def _windows_current() -> PowerSourceState:
        status = _WindowsSystemPowerStatus()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_status = kernel32.GetSystemPowerStatus
        get_status.argtypes = (ctypes.POINTER(_WindowsSystemPowerStatus),)
        get_status.restype = ctypes.c_int
        if get_status(ctypes.byref(status)) == 0:
            return PowerSourceState.UNKNOWN
        if status.ac_line_status == 1:
            return PowerSourceState.EXTERNAL_POWER
        if status.ac_line_status == 0:
            return PowerSourceState.BATTERY
        return PowerSourceState.UNKNOWN

    @staticmethod
    def _linux_current(root: Path) -> PowerSourceState:
        if not root.is_dir():
            return PowerSourceState.UNKNOWN
        battery_statuses: list[str] = []
        for supply in root.iterdir():
            supply_type = (supply / "type").read_text(
                encoding="utf-8", errors="strict"
            ).strip().lower()
            if supply_type == "battery":
                status_path = supply / "status"
                if status_path.is_file():
                    battery_statuses.append(
                        status_path.read_text(
                            encoding="utf-8", errors="strict"
                        ).strip().lower()
                    )
                continue
            online_path = supply / "online"
            if online_path.is_file() and online_path.read_text(
                encoding="utf-8", errors="strict"
            ).strip() == "1":
                return PowerSourceState.EXTERNAL_POWER
        if any(status in {"charging", "full"} for status in battery_statuses):
            return PowerSourceState.EXTERNAL_POWER
        if any(status == "discharging" for status in battery_statuses):
            return PowerSourceState.BATTERY
        return PowerSourceState.UNKNOWN


__all__ = ["LocalPowerSourceReader"]
