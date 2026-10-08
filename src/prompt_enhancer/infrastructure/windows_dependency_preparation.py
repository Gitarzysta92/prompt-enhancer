"""Offline dependency preparation report for a Windows desktop target.

Registry wheels are selected only by :mod:`windows_wheel_inventory`.  The one
reviewed ``proxy-tools`` source build is intentionally outside that registry
admission path and must carry builder provenance before it can be reported as
prepared.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from .desktop_dependency_export import DesktopDependencyExport
from .proxy_tools_wheel_preparation import (
    _MAX_WHEEL_BYTES,
    _SOURCE_SHA,
    _SOURCE_SIZE,
    _SOURCE_DATE_EPOCH,
    _SETUPTOOLS_SHA,
    _SETUPTOOLS_SIZE,
    _SETUPTOOLS_VERSION,
    _validate_built_wheel,
)
from .windows_wheel_inventory import (
    WindowsWheelArtifact,
    WindowsWheelInventory,
    WindowsWheelInventoryError,
    WindowsWheelTarget,
    _lock_bytes,
    _requirements,
    plan_windows_wheels,
)


_MAX_PROVENANCE_BYTES = 16 * 1024
_REQUIRED_PROVENANCE_KEYS = frozenset({
    "filename", "license_discrepancy_review_required", "network_isolation_not_proven",
    "python_runtime_dependencies_not_pinned", "python_sha256", "python_size_bytes",
    "python_version", "setuptools_sha256", "setuptools_size_bytes", "setuptools_version",
    "sha256", "size_bytes", "source_date_epoch", "source_sha256", "source_size_bytes",
})


class WindowsDependencyPreparationError(RuntimeError):
    """Content-free failure while preparing an offline dependency report."""


@dataclass(frozen=True, slots=True)
class SourceBuildRequirement:
    package: str
    version: str
    source_sha256: str
    source_size_bytes: int
    setuptools_sha256: str
    setuptools_size_bytes: int
    setuptools_version: str


@dataclass(frozen=True, slots=True)
class PreparedSourceWheel:
    package: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    python_sha256: str
    python_size_bytes: int
    python_version: str
    license_discrepancy_review_required: bool
    network_isolation_not_proven: bool
    python_runtime_dependencies_not_pinned: bool


@dataclass(frozen=True, slots=True)
class WindowsDependencyPreparationReport:
    target: WindowsWheelTarget
    registry_wheels: tuple[WindowsWheelArtifact, ...]
    source_build_requirements: tuple[SourceBuildRequirement, ...]
    prepared_source_wheels: tuple[PreparedSourceWheel, ...]
    pyproject_sha256: str
    lockfile_sha256: str
    export_fingerprint: str
    registry_export_fingerprint: str
    unresolved_blockers: tuple[str, ...]
    complete: bool = False
    release_accepted: bool = False


def _ordinary_bytes(path: Path, maximum_size: int) -> bytes:
    current = path.parent
    while True:
        try:
            parent_metadata = current.lstat()
        except OSError as error:
            raise WindowsDependencyPreparationError("dependency preparation input is unavailable") from error
        if (not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode)
                or getattr(parent_metadata, "st_file_attributes", 0) & 0x400):
            raise WindowsDependencyPreparationError("dependency preparation input is unsafe")
        if current.parent == current:
            break
        current = current.parent
    try:
        before = path.lstat()
    except OSError as error:
        raise WindowsDependencyPreparationError("dependency preparation input is unavailable") from error
    if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or before.st_nlink != 1 or not 0 < before.st_size <= maximum_size):
        raise WindowsDependencyPreparationError("dependency preparation input is unsafe")
    try:
        chunks = bytearray()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                      value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                                      getattr(value, "st_file_attributes", 0))
            opened_identity = lambda value: (
                value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode), value.st_nlink,
                value.st_size, value.st_mtime_ns, value.st_ctime_ns,
                getattr(value, "st_file_attributes", 0),
            )
            if opened_identity(opened) != opened_identity(before):
                raise WindowsDependencyPreparationError("dependency preparation input changed")
            while chunk := stream.read(min(64 * 1024, maximum_size + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > maximum_size:
                    raise WindowsDependencyPreparationError("dependency preparation input is unsafe")
        data = bytes(chunks)
        after = path.lstat()
    except OSError as error:
        raise WindowsDependencyPreparationError("dependency preparation input is unavailable") from error
    if identity(before) != identity(after) or len(data) != before.st_size:
        raise WindowsDependencyPreparationError("dependency preparation input changed")
    return data


def _provenance(path: Path) -> dict[str, object]:
    data = _ordinary_bytes(path, _MAX_PROVENANCE_BYTES)
    try:
        def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate")
                result[key] = item
            return result
        value = json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid") from error
    if not isinstance(value, dict) or set(value) != _REQUIRED_PROVENANCE_KEYS:
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    return value


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    return value


def _prepared_proxy_tools_wheel(wheel_path: Path, provenance_path: Path) -> PreparedSourceWheel:
    provenance = _provenance(provenance_path)
    required_fixed_values = {
        "source_sha256": _SOURCE_SHA,
        "source_size_bytes": _SOURCE_SIZE,
        "setuptools_sha256": _SETUPTOOLS_SHA,
        "setuptools_size_bytes": _SETUPTOOLS_SIZE,
        "setuptools_version": _SETUPTOOLS_VERSION,
    }
    if any(provenance[key] != value for key, value in required_fixed_values.items()):
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    flag_names = (
        "license_discrepancy_review_required", "network_isolation_not_proven",
        "python_runtime_dependencies_not_pinned",
    )
    if any(provenance[name] is not True for name in flag_names):
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    filename = _string(provenance["filename"])
    python_sha256 = _string(provenance["python_sha256"])
    python_size = _positive_integer(provenance["python_size_bytes"])
    python_version = _string(provenance["python_version"])
    if (provenance["source_date_epoch"] != _SOURCE_DATE_EPOCH
            or re.fullmatch(r"[0-9a-f]{64}", python_sha256) is None
            or re.fullmatch(r"3\.(1[1-9]|[2-9][0-9])\.\d{1,3}", python_version) is None):
        raise WindowsDependencyPreparationError("dependency preparation provenance is invalid")
    wheel_bytes = _ordinary_bytes(wheel_path, _MAX_WHEEL_BYTES)
    if wheel_path.name != filename:
        raise WindowsDependencyPreparationError("dependency preparation wheel does not match provenance")
    validated = _validate_built_wheel(wheel_bytes, filename, python_sha256, python_size, python_version)
    if (validated.sha256 != _string(provenance["sha256"])
            or validated.size_bytes != _positive_integer(provenance["size_bytes"])):
        raise WindowsDependencyPreparationError("dependency preparation wheel does not match provenance")
    return PreparedSourceWheel(
        package="proxy-tools", version="0.1.0", filename=filename,
        sha256=validated.sha256, size_bytes=validated.size_bytes,
        python_sha256=python_sha256, python_size_bytes=python_size,
        python_version=python_version,
        license_discrepancy_review_required=True,
        network_isolation_not_proven=True,
        python_runtime_dependencies_not_pinned=True,
    )


def _registry_only_export(export: DesktopDependencyExport, lockfile: Path,
                          target: WindowsWheelTarget) -> tuple[DesktopDependencyExport, bool]:
    """Project the reviewed source-only package out before registry admission."""
    try:
        active = _requirements(export, target)
        proxy_requirement = active.get("proxy-tools")
        if proxy_requirement is not None:
            if proxy_requirement[0] != "0.1.0" or _SOURCE_SHA not in proxy_requirement[1]:
                raise ValueError("review mismatch")
            lock = _lock_bytes(lockfile, export.lockfile_sha256)
            matches = [package for package in lock.get("package", []) if isinstance(package, dict)
                       and canonicalize_name(str(package.get("name", ""))) == "proxy-tools"
                       and str(package.get("version", "")) == "0.1.0"]
            if len(matches) != 1 or not isinstance(matches[0].get("sdist"), dict):
                raise ValueError("source unavailable")
            source = matches[0]["sdist"]
            if source.get("hash") != f"sha256:{_SOURCE_SHA}" or source.get("size") != _SOURCE_SIZE:
                raise ValueError("source mismatch")
        lines = []
        for line in export.requirements.splitlines():
            requirement = Requirement(line.split(" --hash=", 1)[0])
            if canonicalize_name(requirement.name) != "proxy-tools":
                lines.append(line)
    except Exception as error:
        raise WindowsDependencyPreparationError("dependency preparation export is invalid") from error
    return DesktopDependencyExport(
        requirements="\n".join(lines) + ("\n" if lines else ""),
        pyproject_sha256=export.pyproject_sha256,
        lockfile_sha256=export.lockfile_sha256,
    ), "proxy-tools" in active


def prepare_windows_dependencies(
    *,
    export: DesktopDependencyExport,
    lockfile: Path,
    target: WindowsWheelTarget,
    proxy_tools_wheel: Path | None = None,
    proxy_tools_provenance: Path | None = None,
    planner: Callable[..., WindowsWheelInventory] = plan_windows_wheels,
) -> WindowsDependencyPreparationReport:
    """Classify lock-selected registry wheels and the reviewed source build.

    This function never downloads, builds, installs, or stages any dependency.
    """
    registry_export, proxy_tools_active = _registry_only_export(export, lockfile, target)
    try:
        inventory = planner(export=registry_export, lockfile=lockfile, target=target)
    except WindowsWheelInventoryError as error:
        raise WindowsDependencyPreparationError("dependency preparation registry plan failed") from error
    if not isinstance(inventory, WindowsWheelInventory) or inventory.complete is not True:
        raise WindowsDependencyPreparationError("dependency preparation registry plan failed")
    requirements: tuple[SourceBuildRequirement, ...] = ()
    if proxy_tools_active:
        requirements = (SourceBuildRequirement(
            package="proxy-tools", version="0.1.0", source_sha256=_SOURCE_SHA,
            source_size_bytes=_SOURCE_SIZE, setuptools_sha256=_SETUPTOOLS_SHA,
            setuptools_size_bytes=_SETUPTOOLS_SIZE, setuptools_version=_SETUPTOOLS_VERSION,
        ),)
    prepared: tuple[PreparedSourceWheel, ...] = ()
    blockers = ["proxy_tools_source_build_required"] if proxy_tools_active else []
    if (proxy_tools_wheel is None) != (proxy_tools_provenance is None):
        raise WindowsDependencyPreparationError("dependency preparation provenance is incomplete")
    if proxy_tools_wheel is not None and proxy_tools_provenance is not None:
        if not proxy_tools_active:
            raise WindowsDependencyPreparationError("dependency preparation source wheel is not required")
        prepared_wheel = _prepared_proxy_tools_wheel(Path(proxy_tools_wheel), Path(proxy_tools_provenance))
        prepared = (prepared_wheel,)
        blockers.remove("proxy_tools_source_build_required")
        blockers.extend((
            "proxy_tools_license_discrepancy_review_required",
            "proxy_tools_network_isolation_not_proven",
            "proxy_tools_python_runtime_dependencies_not_pinned",
        ))
    return WindowsDependencyPreparationReport(
        target=inventory.target, registry_wheels=inventory.artifacts,
        source_build_requirements=requirements, prepared_source_wheels=prepared,
        pyproject_sha256=inventory.pyproject_sha256, lockfile_sha256=inventory.lockfile_sha256,
        export_fingerprint=hashlib.sha256(export.requirements.encode("utf-8")).hexdigest(),
        registry_export_fingerprint=inventory.export_fingerprint,
        unresolved_blockers=tuple(blockers), complete=False, release_accepted=False,
    )


def report_json(report: WindowsDependencyPreparationReport) -> str:
    """Render the explicit, content-free planning report for the CLI."""
    return json.dumps(asdict(report), sort_keys=True, separators=(",", ":"))


__all__ = (
    "PreparedSourceWheel", "SourceBuildRequirement", "WindowsDependencyPreparationError",
    "WindowsDependencyPreparationReport", "prepare_windows_dependencies", "report_json",
)
