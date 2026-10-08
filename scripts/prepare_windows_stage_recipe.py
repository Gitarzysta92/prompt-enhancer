"""Review explicit Windows stage inputs and prepare a pinned runtime offline.

Wheel acquisition and release staging deliberately remain separate commands.
This recipe has no network, install, signing, or wheel-staging mode.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import sys

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from packaging.requirements import Requirement  # noqa: E402
from packaging.utils import canonicalize_name  # noqa: E402

from prompt_enhancer.application.paths.policy import classify_windows_path_text  # noqa: E402
from prompt_enhancer.infrastructure.desktop_dependency_export import (  # noqa: E402
    DesktopDependencyExport,
    export_windows_desktop_requirements,
)
from prompt_enhancer.infrastructure.windows_dependency_preparation import (  # noqa: E402
    prepare_windows_dependencies,
    report_json,
)
from prompt_enhancer.infrastructure.windows_python_runtime import (  # noqa: E402
    prepare_windows_python_runtime,
)
from prompt_enhancer.infrastructure.windows_wheel_inventory import (  # noqa: E402
    WindowsWheelTarget,
    plan_windows_wheels,
)

_MAX_RUNTIME_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RuntimePin:
    archive: Path
    version: str
    sha256: str
    size_bytes: int


def _local_absolute_path(value: Path, label: str) -> Path:
    if not isinstance(value, Path):
        raise ValueError(f"{label} is invalid")
    text = os.fspath(value)
    if (not value.is_absolute()
            or ".." in PurePath(text).parts
            or ".." in PureWindowsPath(text).parts
            or classify_windows_path_text(text) is not None):
        raise ValueError(f"{label} is invalid")
    return value


def runtime_pin(
    archive: Path | None,
    version: str | None,
    sha256: str | None,
    size_bytes: int | None,
) -> RuntimePin:
    values = (archive, version, sha256, size_bytes)
    if any(value is None for value in values):
        raise ValueError("runtime pin must be complete")
    assert archive is not None and version is not None and sha256 is not None and size_bytes is not None
    archive = _local_absolute_path(archive, "runtime archive")
    if (not isinstance(version, str) or re.fullmatch(r"3\.13\.[0-9]{1,3}", version) is None
            or not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
            or isinstance(size_bytes, bool) or not isinstance(size_bytes, int)
            or not 0 < size_bytes <= _MAX_RUNTIME_BYTES):
        raise ValueError("runtime pin is invalid")
    return RuntimePin(archive, version, sha256, size_bytes)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns, getattr(value, "st_file_attributes", 0),
    )


def bytes_(path: Path, maximum: int = _MAX_RUNTIME_BYTES) -> bytes:
    """Read one ordinary local file while binding the complete file identity."""
    path = _local_absolute_path(path, "runtime archive")
    current = path.parent
    try:
        while True:
            metadata = current.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & 0x400):
                raise ValueError("runtime archive is unsafe")
            if current.parent == current:
                break
            current = current.parent
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode)
                or getattr(before, "st_file_attributes", 0) & 0x400
                or before.st_nlink != 1 or not 0 < before.st_size <= maximum):
            raise ValueError("runtime archive is unsafe")
        chunks = bytearray()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _identity(opened) != _identity(before):
                raise ValueError("runtime archive changed")
            while chunk := stream.read(min(64 * 1024, maximum + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > maximum:
                    raise ValueError("runtime archive is unsafe")
        after = path.lstat()
    except OSError as error:
        raise ValueError("runtime archive is unavailable") from error
    if _identity(after) != _identity(before) or len(chunks) != before.st_size:
        raise ValueError("runtime archive changed")
    return bytes(chunks)


def verify_runtime_pin(pin: RuntimePin) -> RuntimePin:
    if not isinstance(pin, RuntimePin):
        raise ValueError("runtime pin is invalid")
    checked = runtime_pin(pin.archive, pin.version, pin.sha256, pin.size_bytes)
    archive = bytes_(checked.archive)
    if len(archive) != checked.size_bytes or hashlib.sha256(archive).hexdigest() != checked.sha256:
        raise SystemExit("runtime identity mismatch")
    return checked


def _registry_export(export: DesktopDependencyExport, registry_packages: set[str]) -> DesktopDependencyExport:
    lines: list[str] = []
    for line in export.requirements.splitlines():
        requirement = Requirement(line.split(" --hash=", 1)[0])
        if canonicalize_name(requirement.name) in registry_packages:
            lines.append(line)
    if not lines:
        raise ValueError("registry dependency review is empty")
    return DesktopDependencyExport(
        requirements="\n".join(lines) + "\n",
        pyproject_sha256=export.pyproject_sha256,
        lockfile_sha256=export.lockfile_sha256,
    )


def plan(
    runtime_version: str,
    *,
    repository_root: Path,
    proxy_tools_wheel: Path,
    proxy_tools_provenance: Path,
) -> tuple[WindowsWheelTarget, object, object]:
    repository_root = _local_absolute_path(repository_root, "repository root")
    proxy_tools_wheel = _local_absolute_path(proxy_tools_wheel, "proxy tools wheel")
    proxy_tools_provenance = _local_absolute_path(proxy_tools_provenance, "proxy tools provenance")
    target = WindowsWheelTarget(runtime_version, "amd64")
    export = export_windows_desktop_requirements(repository_root=repository_root)
    lockfile = repository_root / "uv.lock"
    report = prepare_windows_dependencies(
        export=export,
        lockfile=lockfile,
        target=target,
        proxy_tools_wheel=proxy_tools_wheel,
        proxy_tools_provenance=proxy_tools_provenance,
    )
    registry_export = _registry_export(export, {item.package for item in report.registry_wheels})
    inventory = plan_windows_wheels(export=registry_export, lockfile=lockfile, target=target)
    return target, report, inventory


def prepare_runtime(pin: RuntimePin, destination: Path) -> object:
    pin = verify_runtime_pin(pin)
    destination = _local_absolute_path(destination, "runtime destination")
    return prepare_windows_python_runtime(
        archive=pin.archive,
        expected_version=pin.version,
        expected_architecture="amd64",
        expected_sha256=pin.sha256,
        expected_size_bytes=pin.size_bytes,
        destination=destination,
    )


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.exit(2, "windows_stage_recipe_invalid\n")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Review explicit local Windows stage inputs offline.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--review", action="store_true")
    mode.add_argument("--prepare-runtime", metavar="DESTINATION", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--proxy-tools-wheel", type=Path)
    parser.add_argument("--proxy-tools-provenance", type=Path)
    parser.add_argument("--runtime-archive", type=Path)
    parser.add_argument("--runtime-version")
    parser.add_argument("--runtime-sha256")
    parser.add_argument("--runtime-size-bytes", type=int)
    arguments = parser.parse_args(argv)
    try:
        pin = runtime_pin(
            arguments.runtime_archive,
            arguments.runtime_version,
            arguments.runtime_sha256,
            arguments.runtime_size_bytes,
        )
        if arguments.prepare_runtime is not None:
            prepare_runtime(pin, arguments.prepare_runtime)
            return 0
        if any(value is None for value in (
            arguments.repository_root,
            arguments.proxy_tools_wheel,
            arguments.proxy_tools_provenance,
        )):
            raise ValueError("review inputs must be complete")
        pin = verify_runtime_pin(pin)
        _target, report, inventory = plan(
            pin.version,
            repository_root=arguments.repository_root,
            proxy_tools_wheel=arguments.proxy_tools_wheel,
            proxy_tools_provenance=arguments.proxy_tools_provenance,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("windows stage recipe failed") from None
    print(json.dumps({
        "lockfile_sha256": report.lockfile_sha256,
        "network_used": False,
        "pyproject_sha256": report.pyproject_sha256,
        "registry_wheels": len(inventory.artifacts),
        "runtime_sha256": pin.sha256,
        "runtime_size_bytes": pin.size_bytes,
        "runtime_version": pin.version,
        "source_report_sha256": hashlib.sha256(report_json(report).encode("utf-8")).hexdigest(),
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
