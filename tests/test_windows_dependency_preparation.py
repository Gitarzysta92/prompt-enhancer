"""Synthetic tests for source-build/registry dependency preparation reporting."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.desktop_dependency_export import DesktopDependencyExport
from prompt_enhancer.infrastructure import proxy_tools_wheel_preparation as wheel_builder
import prompt_enhancer.infrastructure.windows_dependency_preparation as preparation
from prompt_enhancer.infrastructure.windows_dependency_preparation import (
    WindowsDependencyPreparationError,
    prepare_windows_dependencies,
    report_json,
)
from prompt_enhancer.infrastructure.windows_wheel_inventory import (
    WindowsWheelArtifact, WindowsWheelInventory, WindowsWheelTarget,
)


def _inventory(*, export: DesktopDependencyExport, lockfile: Path,
               target: WindowsWheelTarget) -> WindowsWheelInventory:
    del lockfile
    assert "proxy-tools" not in export.requirements
    return WindowsWheelInventory(target, (WindowsWheelArtifact(
        "registry-package", "1.0", "registry_package-1.0-py3-none-any.whl", "a" * 64, 10),),
        "c" * 64, export.lockfile_sha256, export.pyproject_sha256)


def _export() -> DesktopDependencyExport:
    return DesktopDependencyExport(
        "registry-package==1.0 --hash=sha256:" + "a" * 64 + "\n"
        + "proxy-tools==0.1.0 --hash=sha256:ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010\n",
                                   "b" * 64, "c" * 64)


def _allow_reviewed_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preparation, "_lock_bytes", lambda path, digest: {"package": [{
        "name": "proxy-tools", "version": "0.1.0",
        "sdist": {"hash": "sha256:ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010", "size": 2978},
    }]})


def test_report_keeps_registry_admission_separate_from_source_requirement(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_reviewed_lock(monkeypatch)
    report = prepare_windows_dependencies(
        export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
        planner=_inventory)
    assert [item.package for item in report.registry_wheels] == ["registry-package"]
    assert report.source_build_requirements[0].package == "proxy-tools"
    assert report.prepared_source_wheels == ()
    assert report.unresolved_blockers == ("proxy_tools_source_build_required",)
    assert report.complete is False and report.release_accepted is False
    assert json.loads(report_json(report))["complete"] is False


def _record_digest(value: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=").decode()


def _reviewed_wheel(module: bytes) -> bytes:
    files = {
        "proxy_tools/__init__.py": module,
        "proxy_tools-0.1.0.dist-info/METADATA": b"Metadata-Version: 2.4\nName: proxy-tools\nVersion: 0.1.0\nLicense: MIT\n",
        "proxy_tools-0.1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "proxy_tools-0.1.0.dist-info/top_level.txt": b"proxy_tools\n",
    }
    record_name = "proxy_tools-0.1.0.dist-info/RECORD"
    rows = [[name, _record_digest(data), str(len(data))] for name, data in files.items()]
    rows.append([record_name, "", ""])
    files[record_name] = "\n".join(",".join(row) for row in rows).encode() + b"\n"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


def test_prepared_source_wheel_requires_existing_builder_provenance(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = b"synthetic reviewed proxy module\n"
    _allow_reviewed_lock(monkeypatch)
    monkeypatch.setattr(wheel_builder, "_SOURCE_MEMBERS", {
        "proxy_tools/__init__.py": (len(module), hashlib.sha256(module).hexdigest())
    })
    payload = _reviewed_wheel(module)
    wheel = tmp_path / "proxy_tools-0.1.0-py3-none-any.whl"
    wheel.write_bytes(payload)
    provenance = {
        "filename": wheel.name, "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
        "python_sha256": "d" * 64, "python_size_bytes": 1, "python_version": "3.13.0",
        "source_date_epoch": "1399328544", "source_sha256": "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010",
        "source_size_bytes": 2978, "setuptools_sha256": "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
        "setuptools_size_bytes": 818216, "setuptools_version": "84.0.0",
        "license_discrepancy_review_required": True, "network_isolation_not_proven": True,
        "python_runtime_dependencies_not_pinned": True,
    }
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    report = prepare_windows_dependencies(
        export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
        proxy_tools_wheel=wheel, proxy_tools_provenance=provenance_path, planner=_inventory)
    assert report.prepared_source_wheels[0].sha256 == provenance["sha256"]
    assert "proxy_tools_source_build_required" not in report.unresolved_blockers
    assert report.complete is False and report.release_accepted is False
    provenance["sha256"] = "0" * 64
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(WindowsDependencyPreparationError):
        prepare_windows_dependencies(
            export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
            proxy_tools_wheel=wheel, proxy_tools_provenance=provenance_path, planner=_inventory)


def test_proxy_wheel_and_provenance_must_arrive_together(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_reviewed_lock(monkeypatch)
    with pytest.raises(WindowsDependencyPreparationError):
        prepare_windows_dependencies(
            export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
            proxy_tools_wheel=tmp_path / "wheel", planner=_inventory)


@pytest.mark.parametrize("requirement", [
    "proxy-tools==0.2.0 --hash=sha256:" + "b" * 64 + "\n",
    "proxy-tools==0.1.0 --hash=sha256:" + "c" * 64 + "\n",
])
def test_source_projection_rejects_unreviewed_active_requirement(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requirement: str) -> None:
    _allow_reviewed_lock(monkeypatch)
    export = DesktopDependencyExport(requirement, "b" * 64, "c" * 64)
    with pytest.raises(WindowsDependencyPreparationError):
        prepare_windows_dependencies(
            export=export, lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
            planner=_inventory)


def test_source_projection_rejects_wrong_locked_sdist(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_reviewed_lock(monkeypatch)
    monkeypatch.setattr(preparation, "_lock_bytes", lambda path, digest: {"package": [{
        "name": "proxy-tools", "version": "0.1.0",
        "sdist": {"hash": "sha256:" + "0" * 64, "size": 2978},
    }]})
    with pytest.raises(WindowsDependencyPreparationError):
        prepare_windows_dependencies(
            export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
            planner=_inventory)


def test_builder_receipt_rejects_duplicate_json_member(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_reviewed_lock(monkeypatch)
    wheel = tmp_path / "proxy_tools-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"not consumed: duplicate receipt must fail first")
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"filename":"first","filename":"second"}', encoding="utf-8")
    with pytest.raises(WindowsDependencyPreparationError):
        prepare_windows_dependencies(
            export=_export(), lockfile=tmp_path / "lock", target=WindowsWheelTarget("3.13.0", "amd64"),
            proxy_tools_wheel=wheel, proxy_tools_provenance=receipt, planner=_inventory)


def test_provenance_reader_binds_bytes_to_the_opened_file_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewed = tmp_path / "reviewed-provenance.json"
    substitute = tmp_path / "substitute-provenance.json"
    reviewed.write_bytes(b"reviewed")
    substitute.write_bytes(b"attacker")
    real_open = Path.open

    def redirected_open(path: Path, *args: object, **kwargs: object) -> object:
        return real_open(substitute if path == reviewed else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", redirected_open)
    with pytest.raises(WindowsDependencyPreparationError):
        preparation._ordinary_bytes(reviewed, 32)
