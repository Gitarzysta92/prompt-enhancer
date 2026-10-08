"""Private, bounded logical npm-lock to installed physical-root bindings.

Package metadata hardlinks are permitted. No package code is executed or read;
these bindings do not prove that installed file contents match npm tarballs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from .application_wheel_preparation import _assert_link_free_ancestors, ApplicationWheelPreparationError
from .frontend_module_inventory import _json, _path

_MAX_METADATA = 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_MAX_MAPPING = 2 * 1024 * 1024
_MAX_PACKAGES = 4096


class FrontendPackageBindingError(ValueError):
    pass


def _require(condition):
    if not condition:
        raise FrontendPackageBindingError("frontend package binding invalid")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _snapshot(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, getattr(info, "st_birthtime_ns", None), getattr(info, "st_file_attributes", 0))


def _ordinary(info, directory=False):
    return (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) and not (
        stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400)


def _cross(path_info, fd_info):
    # Same-API snapshots below retain raw ctime. Cross-API Windows ctime can
    # describe different timestamps, so use creation time when both expose it.
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns")
    if not path_info.st_ino or not fd_info.st_ino or any(getattr(path_info, f) != getattr(fd_info, f) for f in fields):
        return False
    left, right = getattr(path_info, "st_birthtime_ns", None), getattr(fd_info, "st_birthtime_ns", None)
    if os.name == "nt" and left is not None and right is not None:
        return left == right
    return path_info.st_ctime_ns == fd_info.st_ctime_ns


def _metadata(path, budget):
    _assert_link_free_ancestors(path)
    before = path.lstat()
    _require(_ordinary(before) and before.st_nlink >= 1 and 0 < before.st_size <= min(_MAX_METADATA, budget))
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(_ordinary(opened) and _cross(before, opened))
        raw = stream.read(before.st_size + 1)
        _require(_snapshot(opened) == _snapshot(os.fstat(stream.fileno())))
    _assert_link_free_ancestors(path)
    _require(_snapshot(before) == _snapshot(path.lstat()) and len(raw) == before.st_size)
    return raw


def _resolve(root, logical):
    target = root.joinpath(*PurePosixPath(logical).parts)
    unresolved = target.resolve(strict=False)
    _require(unresolved != root / "node_modules" and unresolved.is_relative_to(root / "node_modules"))
    try:
        physical = target.resolve(strict=True)
    except FileNotFoundError:
        return None
    _require(physical != root / "node_modules" and physical.is_relative_to(root / "node_modules"))
    _assert_link_free_ancestors(physical / "package.json")
    _require(_ordinary(physical.lstat(), directory=True))
    return physical


@dataclass(frozen=True)
class _Entry:
    logical: str
    physical: Path | None
    directory_snapshot: tuple | None
    metadata_sha256: str | None
    metadata_size: int | None


@dataclass(frozen=True)
class FrontendPackageBindings:
    root: Path
    lock_sha256: str
    lock_bytes: bytes
    entries: tuple[_Entry, ...]
    logical_digest: str

    @property
    def available_keys(self):
        return frozenset(entry.logical for entry in self.entries if entry.physical is not None)

    @property
    def missing_count(self):
        return sum(entry.physical is None for entry in self.entries)

    def mapping_bytes(self):
        # Absolute roots exist only in the private work directory, not in the
        # logical digest, graph, published dashboard, or user-facing receipt.
        payload = {"contract": "frontend-package-physical-bindings.v1", "entries": [
            {"lock_key": entry.logical, "physical_root": entry.physical.as_posix() if entry.physical else None}
            for entry in self.entries], "package_lock_sha256": self.lock_sha256}
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        _require(len(raw) <= _MAX_MAPPING)
        return raw

    def verify(self):
        current = collect_frontend_package_bindings(self.root, self.lock_bytes)
        _require(current.entries == self.entries and current.logical_digest == self.logical_digest)

    def write_mapping(self, path):
        _assert_link_free_ancestors(path)
        raw = self.mapping_bytes()
        with path.open("xb") as stream:
            stream.write(raw)
        return _digest(raw)

    def verify_mapping(self, path):
        # Mapping is generated here, so byte equality also proves closed schema.
        from .application_wheel_preparation import _read
        _require(_read(path, maximum=_MAX_MAPPING) == self.mapping_bytes())


def collect_frontend_package_bindings(frontend_root: Path, lock_bytes: bytes) -> FrontendPackageBindings:
    try:
        _require(frontend_root.is_absolute())
        _require(_ordinary(frontend_root.lstat(), directory=True))
        _assert_link_free_ancestors(frontend_root / "node_modules" / "package.json")
        root = frontend_root.resolve(strict=True)
        _assert_link_free_ancestors(root / "node_modules" / "package.json")
        _require(_ordinary((root / "node_modules").lstat(), directory=True))
        lock = _json(lock_bytes)
        _require(type(lock.get("lockfileVersion")) is int and lock["lockfileVersion"] == 3)
        packages = lock.get("packages")
        _require(isinstance(packages, dict) and 1 <= len(packages) <= _MAX_PACKAGES + 1)
        entries, logical_records, seen, total = [], [], set(), 0
        for logical, expected in sorted(packages.items()):
            if logical == "": continue
            _path(logical)
            _require(logical.startswith("node_modules/") and isinstance(expected, dict))
            physical = _resolve(root, logical)
            if physical is None:
                entries.append(_Entry(logical, None, None, None, None))
                logical_records.append({"lock_key": logical, "present": False})
                continue
            normalized = os.path.normcase(os.fspath(physical))
            _require(normalized not in seen)
            seen.add(normalized)
            before = _snapshot(physical.lstat())
            raw = _metadata(physical / "package.json", _MAX_TOTAL - total)
            total += len(raw)
            _require(before == _snapshot(physical.lstat()))
            metadata = _json(raw)
            name = logical.rsplit("node_modules/", 1)[1]
            _require(metadata.get("name") == name and metadata.get("version") == expected.get("version")
                     and isinstance(metadata.get("version"), str))
            entries.append(_Entry(logical, physical, before, _digest(raw), len(raw)))
            logical_records.append({"lock_key": logical, "present": True, "package_json_sha256": _digest(raw),
                                    "package_json_size_bytes": len(raw)})
        _require(bool(entries))
        digest = _digest(json.dumps(logical_records, sort_keys=True, separators=(",", ":")).encode())
        return FrontendPackageBindings(root, _digest(lock_bytes), lock_bytes, tuple(entries), digest)
    except (OSError, RuntimeError, ValueError, ApplicationWheelPreparationError):
        raise FrontendPackageBindingError("frontend package binding invalid") from None
