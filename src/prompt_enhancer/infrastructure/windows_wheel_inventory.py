"""Offline wheel-plan construction for an explicit Windows CPython target."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import tomllib
from typing import Literal

from packaging.markers import Marker, InvalidMarker, Variable
from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version

from .desktop_dependency_export import DesktopDependencyExport, DesktopDependencyExportError

_MAX_LOCK_BYTES = 32 * 1024 * 1024
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
_REQ = re.compile(r"^([a-z0-9][a-z0-9-]*)==([^ ;]+)(?:\s*;\s*(.+?))?\s+(.+)$")
_MARKER_KEYS = frozenset({"implementation_name", "implementation_version", "os_name", "platform_machine", "platform_python_implementation", "python_full_version", "python_version", "sys_platform", "platform_system", "platform_release", "platform_version"})


class WindowsWheelInventoryError(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class WindowsWheelTarget:
    python_full_version: str
    architecture: Literal["amd64", "arm64"]
    implementation: Literal["cpython"] = "cpython"
    free_threaded: Literal[False] = False
    platform_release: str | None = None
    platform_version: str | None = None

    def __post_init__(self) -> None:
        if (not isinstance(self.python_full_version, str)
            or re.fullmatch(r"3\.(1[1-9]|[2-9][0-9])\.\d{1,3}", self.python_full_version) is None
            or self.architecture not in ("amd64", "arm64") or self.implementation != "cpython"
            or self.free_threaded is not False
            or any(value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 128) for value in (self.platform_release, self.platform_version))):
            raise ValueError("wheel target Python version is invalid")


@dataclass(frozen=True, slots=True)
class WindowsWheelArtifact:
    package: str; version: str; filename: str; sha256: str; size_bytes: int


@dataclass(frozen=True, slots=True)
class WindowsWheelInventory:
    target: WindowsWheelTarget
    artifacts: tuple[WindowsWheelArtifact, ...]
    export_fingerprint: str
    lockfile_sha256: str
    pyproject_sha256: str
    complete: Literal[True] = True


def _lock_bytes(path: Path, expected: str) -> dict[str, object]:
    """Read one immutable, ordinary lockfile without following unsafe paths."""
    absolute = _lexical_absolute(path)
    _ordinary_directory_ancestors(absolute.parent)
    try:
        before = absolute.lstat()
    except OSError as error:
        raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error
    if not _ordinary_file(before) or before.st_size > _MAX_LOCK_BYTES:
        raise WindowsWheelInventoryError("wheel inventory lock changed")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute, flags)
    except OSError as error:
        raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error
    try:
        opened = os.fstat(descriptor)
        if not _ordinary_file(opened) or not _same_snapshot(before, opened):
            raise WindowsWheelInventoryError("wheel inventory lock changed")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            data = stream.read(_MAX_LOCK_BYTES + 1)
            after_open = os.fstat(stream.fileno())
    except OSError as error:
        raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error
    finally:
        if descriptor != -1:
            os.close(descriptor)
    try:
        after = absolute.lstat()
    except OSError as error:
        raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error
    _ordinary_directory_ancestors(absolute.parent)
    if (len(data) > _MAX_LOCK_BYTES or not _ordinary_file(after)
        or not _same_snapshot(before, after_open) or not _same_snapshot(before, after)
        or hashlib.sha256(data).hexdigest() != expected):
        raise WindowsWheelInventoryError("wheel inventory lock changed")
    try: parsed = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error: raise WindowsWheelInventoryError("wheel inventory lock is invalid") from error
    if not isinstance(parsed, dict): raise WindowsWheelInventoryError("wheel inventory lock is invalid")
    return parsed


def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev == right.st_dev and left.st_ino == right.st_ino
            and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
            and left.st_nlink == right.st_nlink and left.st_size == right.st_size
            and left.st_mtime_ns == right.st_mtime_ns and left.st_ctime_ns == right.st_ctime_ns)


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)


def _ordinary_file(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and not _is_link_or_reparse(metadata) and metadata.st_nlink == 1


def _lexical_absolute(path: Path) -> Path:
    try:
        raw = os.fspath(path)
        if ".." in Path(raw).parts:
            raise ValueError("traversal")
        return Path(os.path.abspath(raw))
    except (OSError, TypeError, ValueError) as error:
        raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error


def _ordinary_directory_ancestors(path: Path) -> None:
    current = path
    while True:
        try:
            metadata = current.lstat()
        except OSError as error:
            raise WindowsWheelInventoryError("wheel inventory lock is unavailable") from error
        if not stat.S_ISDIR(metadata.st_mode) or _is_link_or_reparse(metadata):
            raise WindowsWheelInventoryError("wheel inventory lock is unavailable")
        if current.parent == current:
            return
        current = current.parent


def _target_tags(target: WindowsWheelTarget) -> tuple[Tag, ...]:
    major, minor, _micro = (int(item) for item in target.python_full_version.split("."))
    platform = f"win_{target.architecture}"
    interpreter = f"cp{major}{minor}"
    return tuple(cpython_tags((major, minor), abis=(interpreter,), platforms=(platform,))) + tuple(
        compatible_tags((major, minor), interpreter=interpreter, platforms=(platform,)))


def _marker_active(marker: str | None, target: WindowsWheelTarget) -> bool:
    if marker is None: return True
    try: parsed = Marker(marker)
    except InvalidMarker as error: raise WindowsWheelInventoryError("wheel inventory marker is invalid") from error
    def variables_of(value: object) -> set[str]:
        if isinstance(value, Variable):
            return {str(value.value)}
        if isinstance(value, (tuple, list)):
            return set().union(*(variables_of(item) for item in value))
        return set()
    variables = variables_of(parsed._markers)
    if not variables <= _MARKER_KEYS or (("platform_release" in variables and target.platform_release is None)
        or ("platform_version" in variables and target.platform_version is None)):
        raise WindowsWheelInventoryError("wheel inventory marker target is incomplete")
    major, minor, micro = target.python_full_version.split(".")
    environment = {
        "implementation_name": "cpython", "implementation_version": target.python_full_version,
        "os_name": "nt", "platform_machine": "AMD64" if target.architecture == "amd64" else "ARM64",
        "platform_python_implementation": "CPython", "python_full_version": target.python_full_version,
        "python_version": f"{major}.{minor}", "sys_platform": "win32",
        "platform_system": "Windows",
        "platform_release": target.platform_release or "", "platform_version": target.platform_version or "",
    }
    return parsed.evaluate(environment)


def _requirements(export: DesktopDependencyExport, target: WindowsWheelTarget) -> dict[str, tuple[str, frozenset[str]]]:
    chosen: dict[str, tuple[str, frozenset[str]]] = {}
    for line in export.requirements.splitlines():
        head, separator, tail = line.partition(" --hash=")
        if not separator: raise WindowsWheelInventoryError("wheel inventory export is invalid")
        try: requirement = Requirement(head)
        except InvalidRequirement as error: raise WindowsWheelInventoryError("wheel inventory export is invalid") from error
        if (requirement.url is not None or requirement.extras or len(requirement.specifier) != 1
            or next(iter(requirement.specifier)).operator != "=="):
            raise WindowsWheelInventoryError("wheel inventory export is invalid")
        version = next(iter(requirement.specifier)).version
        try:
            Version(version)
        except InvalidVersion as error:
            raise WindowsWheelInventoryError("wheel inventory export is invalid") from error
        name, marker = canonicalize_name(requirement.name), None if requirement.marker is None else str(requirement.marker)
        tail = "--hash=" + tail
        hashes = frozenset(_HASH.findall(tail))
        if not hashes or " ".join(f"--hash=sha256:{item}" for item in _HASH.findall(tail)) != tail:
            raise WindowsWheelInventoryError("wheel inventory export is invalid")
        if not _marker_active(marker, target): continue
        previous = chosen.get(name)
        current = (version, hashes)
        if previous is not None and previous != current:
            raise WindowsWheelInventoryError("wheel inventory conditional requirements conflict")
        chosen[name] = current
    if not chosen: raise WindowsWheelInventoryError("wheel inventory has no active requirements")
    return chosen


def _export_fingerprint(export: DesktopDependencyExport) -> str:
    return hashlib.sha256(export.requirements.encode("utf-8")).hexdigest()


def plan_windows_wheels(*, export: DesktopDependencyExport, lockfile: Path,
                        target: WindowsWheelTarget) -> WindowsWheelInventory:
    if not isinstance(export, DesktopDependencyExport): raise WindowsWheelInventoryError("wheel inventory export is invalid")
    try: target = WindowsWheelTarget(target.python_full_version, target.architecture, target.implementation, target.free_threaded, target.platform_release, target.platform_version)
    except Exception as error: raise WindowsWheelInventoryError("wheel inventory target is invalid") from error
    lock = _lock_bytes(lockfile, export.lockfile_sha256)
    requirements = _requirements(export, target); tags = _target_tags(target)
    rank = {tag: index for index, tag in enumerate(tags)}
    packages = lock.get("package")
    if not isinstance(packages, list): raise WindowsWheelInventoryError("wheel inventory lock is invalid")
    artifacts: list[WindowsWheelArtifact] = []
    for name, (version, hashes) in requirements.items():
        matches = [item for item in packages if isinstance(item, dict) and canonicalize_name(str(item.get("name", ""))) == name and str(item.get("version", "")) == version]
        if len(matches) != 1: raise WindowsWheelInventoryError(f"wheel inventory package unavailable:{name}")
        wheels = matches[0].get("wheels")
        if not isinstance(wheels, list): raise WindowsWheelInventoryError(f"wheel inventory wheel unavailable:{name}")
        choices: list[tuple[int, str, str, int]] = []
        for wheel in wheels:
            if not isinstance(wheel, dict): continue
            url, digest, size = wheel.get("url"), wheel.get("hash"), wheel.get("size")
            if not isinstance(url, str) or not isinstance(digest, str) or not isinstance(size, int) or isinstance(size, bool) or size < 1: continue
            filename = url.rsplit("/", 1)[-1]
            try: wheel_name, wheel_version, _build, wheel_tags = parse_wheel_filename(filename)
            except InvalidWheelFilename: continue
            sha = digest.removeprefix("sha256:")
            if (canonicalize_name(wheel_name) != name or str(wheel_version) != version
                or sha not in hashes or re.fullmatch(r"[0-9a-f]{64}", sha) is None): continue
            compatible = [rank[tag] for tag in wheel_tags if tag in rank]
            if compatible: choices.append((min(compatible), filename, sha, size))
        if not choices: raise WindowsWheelInventoryError(f"wheel inventory wheel unavailable:{name}")
        best = min(choices, key=lambda item: (item[0], item[1], item[2]))
        artifacts.append(WindowsWheelArtifact(name, version, best[1], best[2], best[3]))
    return WindowsWheelInventory(target, tuple(sorted(artifacts, key=lambda item: item.package)),
        _export_fingerprint(export), export.lockfile_sha256, export.pyproject_sha256)
