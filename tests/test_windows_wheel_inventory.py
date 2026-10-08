from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.desktop_dependency_export import DesktopDependencyExport
from prompt_enhancer.infrastructure.windows_wheel_inventory import (
    WindowsWheelInventoryError, WindowsWheelTarget, plan_windows_wheels,
)

HASH = "a" * 64


def _export(lock: Path, requirements: str) -> DesktopDependencyExport:
    return DesktopDependencyExport(requirements, "b" * 64, hashlib.sha256(lock.read_bytes()).hexdigest())


def _lock(path: Path, *, filename: str = "package-1.0-cp313-cp313-win_amd64.whl", digest: str = HASH) -> None:
    path.write_text(
        "version = 1\n[[package]]\nname = 'package'\nversion = '1.0'\nwheels = [{ url = 'https://example.invalid/" + filename + "', hash = 'sha256:" + digest + "', size = 10 }]\n",
        encoding="utf-8",
    )


def test_inventory_selects_explicit_target_wheel_and_orders_content_only(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"; _lock(lock)
    value = plan_windows_wheels(export=_export(lock, f"package==1.0 --hash=sha256:{HASH}\n"), lockfile=lock,
        target=WindowsWheelTarget("3.13.0", "amd64"))
    assert value.complete and value.artifacts[0].filename.endswith("win_amd64.whl")
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=_export(lock, f"package==1.0 --hash=sha256:{HASH}\n"), lockfile=lock,
            target=WindowsWheelTarget("3.11.0", "amd64"))


@pytest.mark.parametrize("requirements", [
    f"package==1.0 ; sys_platform == 'win32' --hash=sha256:{HASH}\n",
    f"package==1.0 ; sys_platform == 'linux' --hash=sha256:{HASH}\n",
    f"package==1.0 ; platform_release == '10' --hash=sha256:{HASH}\n",
])
def test_inventory_evaluates_markers_only_against_explicit_target(tmp_path: Path, requirements: str) -> None:
    lock = tmp_path / "uv.lock"; _lock(lock)
    target = WindowsWheelTarget("3.13.0", "amd64")
    if "linux" in requirements or "platform_release" in requirements:
        with pytest.raises(WindowsWheelInventoryError): plan_windows_wheels(export=_export(lock, requirements), lockfile=lock, target=target)
    else:
        assert plan_windows_wheels(export=_export(lock, requirements), lockfile=lock, target=target).artifacts


def test_inventory_rejects_hash_arch_version_and_lock_mutation(tmp_path: Path) -> None:
    lock = tmp_path / "uv.lock"; _lock(lock, digest="c" * 64)
    export = _export(lock, f"package==1.0 --hash=sha256:{HASH}\n")
    with pytest.raises(WindowsWheelInventoryError): plan_windows_wheels(export=export, lockfile=lock, target=WindowsWheelTarget("3.13.0", "amd64"))
    _lock(lock, filename="package-1.0-cp313-cp313-win_arm64.whl")
    with pytest.raises(WindowsWheelInventoryError): plan_windows_wheels(export=_export(lock, f"package==1.0 --hash=sha256:{HASH}\n"), lockfile=lock, target=WindowsWheelTarget("3.13.0", "amd64"))
    lock.write_text("changed", encoding="utf-8")
    with pytest.raises(WindowsWheelInventoryError): plan_windows_wheels(export=export, lockfile=lock, target=WindowsWheelTarget("3.13.0", "amd64"))
