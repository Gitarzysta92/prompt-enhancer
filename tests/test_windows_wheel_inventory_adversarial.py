from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.desktop_dependency_export import DesktopDependencyExport
from prompt_enhancer.infrastructure.windows_wheel_inventory import (
    WindowsWheelInventoryError,
    WindowsWheelTarget,
    plan_windows_wheels,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _inventory(tmp_path: Path, requirements: str, packages: str):
    lockfile = tmp_path / "uv.lock"
    lockfile.write_text(packages, encoding="utf-8")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='synthetic'\n", encoding="utf-8")
    export = DesktopDependencyExport(
        requirements=requirements,
        pyproject_sha256=hashlib.sha256(pyproject.read_bytes()).hexdigest(),
        lockfile_sha256=hashlib.sha256(lockfile.read_bytes()).hexdigest(),
    )
    return lockfile, export


def _package(name: str = "alpha", version: str = "1.0", *, filename: str | None = None, digest: str = HASH_A, size: int = 10) -> str:
    wheel = filename or f"{name}-{version}-py3-none-any.whl"
    return f'[[package]]\nname = "{name}"\nversion = "{version}"\nwheels = [{{ url = "https://example.invalid/{wheel}", hash = "sha256:{digest}", size = {size} }}]\n'


def _target(**changes: object) -> WindowsWheelTarget:
    values: dict[str, object] = {"python_full_version": "3.13.0", "architecture": "amd64"}
    values.update(changes)
    return WindowsWheelTarget(**values)  # type: ignore[arg-type]


def test_platform_system_windows_marker_is_active(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 ; platform_system == 'Windows' --hash=sha256:{HASH_A}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package())
    result = plan_windows_wheels(export=export, lockfile=lockfile, target=_target())
    assert result.complete is True and result.artifacts[0].filename == "alpha-1.0-py3-none-any.whl"


def test_reversed_platform_system_marker_is_active(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 ; 'Windows' == platform_system --hash=sha256:{HASH_A}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package())
    assert plan_windows_wheels(export=export, lockfile=lockfile, target=_target()).artifacts


def test_platform_release_marker_requires_target_value(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 ; '10' == platform_release --hash=sha256:{HASH_A}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package())
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


@pytest.mark.parametrize("changes", [
    {"architecture": "x86"},
    {"implementation": "pypy"},
    {"free_threaded": True},
])
def test_target_rejects_malformed_platform_identity(changes: dict[str, object]) -> None:
    with pytest.raises((ValueError, TypeError)):
        _target(**changes)


def test_incompatible_architecture_or_abi_is_rejected(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 --hash=sha256:{HASH_A}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package(filename="alpha-1.0-cp313-cp313-win_amd64.whl"))
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target(architecture="arm64"))
    lockfile, export = _inventory(tmp_path, requirements, _package(filename="alpha-1.0-cp312-cp312-win_amd64.whl"))
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_missing_active_package_and_hash_mismatch_are_rejected(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 --hash=sha256:{HASH_A}\nbeta==1.0 --hash=sha256:{HASH_B}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package())
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())
    requirements = f"alpha==1.0 --hash=sha256:{HASH_B}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package(digest=HASH_A))
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_wheel_filename_version_mismatch_is_rejected(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 --hash=sha256:{HASH_A}\n"
    lockfile, export = _inventory(tmp_path, requirements, _package(filename="alpha-2.0-py3-none-any.whl"))
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_active_conditional_versions_conflict(tmp_path: Path) -> None:
    requirements = (
        f"alpha==1.0 ; platform_system == 'Windows' --hash=sha256:{HASH_A}\n"
        f"alpha==2.0 ; sys_platform == 'win32' --hash=sha256:{HASH_B}\n"
    )
    lockfile, export = _inventory(tmp_path, requirements, _package())
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_selection_is_deterministic_and_prefers_target_tag(tmp_path: Path) -> None:
    requirements = f"alpha==1.0 --hash=sha256:{HASH_A} --hash=sha256:{HASH_B}\n"
    packages = ('[[package]]\nname = "alpha"\nversion = "1.0"\nwheels = ['
                f'{{ url = "https://example.invalid/alpha-1.0-py3-none-any.whl", hash = "sha256:{HASH_A}", size = 10 }},'
                f'{{ url = "https://example.invalid/alpha-1.0-cp313-cp313-win_amd64.whl", hash = "sha256:{HASH_B}", size = 10 }}]\n')
    lockfile, export = _inventory(tmp_path, requirements, packages)
    result = plan_windows_wheels(export=export, lockfile=lockfile, target=_target())
    assert result.artifacts[0].filename == "alpha-1.0-cp313-cp313-win_amd64.whl"


def test_malformed_lock_and_target_version_are_rejected(tmp_path: Path) -> None:
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", "not = [valid\n")
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())
    with pytest.raises(ValueError):
        _target(python_full_version="3.10.0")


@pytest.mark.parametrize("requirement", [
    f"alpha[extra]==1.0 --hash=sha256:{HASH_A}\n",
    f"alpha[extra]==1.0 ; sys_platform == 'linux' --hash=sha256:{HASH_A}\n",
    f"alpha==1.* --hash=sha256:{HASH_A}\n",
    f"alpha~=1.0 --hash=sha256:{HASH_A}\n",
])
def test_requirement_extras_and_wildcards_are_rejected(tmp_path: Path, requirement: str) -> None:
    lockfile, export = _inventory(tmp_path, requirement, _package())
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_lock_size_bound_is_inclusive_then_rejects_one_extra_byte(tmp_path: Path) -> None:
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", _package())
    prefix = _package().encode("utf-8")
    lockfile.write_bytes(prefix + b"#" * (32 * 1024 * 1024 - len(prefix)))
    export = DesktopDependencyExport(export.requirements, export.pyproject_sha256,
        hashlib.sha256(lockfile.read_bytes()).hexdigest())
    assert plan_windows_wheels(export=export, lockfile=lockfile, target=_target()).artifacts
    with lockfile.open("ab") as stream:
        stream.write(b"x")
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_symlinked_lock_or_parent_is_rejected(tmp_path: Path) -> None:
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", _package())
    target = tmp_path / "target.lock"
    target.write_text(_package(), encoding="utf-8")
    lockfile.unlink()
    try:
        lockfile.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {type(error).__name__}")
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", _package())
    lockfile.unlink()
    real_parent = tmp_path / "real-lock-parent"
    real_parent.mkdir()
    (real_parent / "uv.lock").write_text(_package(), encoding="utf-8")
    linked_parent = tmp_path / "linked-lock-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"directory symlink creation unavailable: {type(error).__name__}")
    linked_lock = linked_parent / "uv.lock"
    linked_export = DesktopDependencyExport(export.requirements, export.pyproject_sha256,
        hashlib.sha256((real_parent / "uv.lock").read_bytes()).hexdigest())
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=linked_export, lockfile=linked_lock, target=_target())


def test_lock_mutation_between_open_and_path_recheck_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    packages = _package()
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", packages)
    real_lstat = Path.lstat
    lock_checks = 0

    def mutate_after_open(path: Path):
        nonlocal lock_checks
        result = real_lstat(path)
        if path == lockfile:
            lock_checks += 1
            if lock_checks == 2:
                lockfile.write_text(packages.replace("size = 10", "size = 11"), encoding="utf-8")
                return real_lstat(path)
        return result

    monkeypatch.setattr(Path, "lstat", mutate_after_open)
    with pytest.raises(WindowsWheelInventoryError):
        plan_windows_wheels(export=export, lockfile=lockfile, target=_target())


def test_cli_emits_serializable_inventory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = Path(__file__).parents[1] / "scripts" / "plan_windows_wheels.py"
    spec = importlib.util.spec_from_file_location("synthetic_wheel_cli", path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    lockfile, export = _inventory(tmp_path, f"alpha==1.0 --hash=sha256:{HASH_A}\n", _package())
    monkeypatch.setattr(cli, "export_windows_desktop_requirements", lambda **_: export)
    assert cli.main(["--python-full-version", "3.13.0", "--architecture", "amd64", "--repository-root", str(tmp_path)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["complete"] is True and document["artifacts"][0]["package"] == "alpha"
