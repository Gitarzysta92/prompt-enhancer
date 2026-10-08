"""Prepare a supplied CPython Windows embeddable ZIP without executing it.

The embeddable package is intentionally kept isolated: this module copies its
``._pth`` file byte-for-byte and rejects an enabled ``import site`` line.  It
does not install Python, consult the registry, download anything, or establish
that native DLL dependencies/execution are accepted on the target machine.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_MEMBERS = 512
_REPARSE = 0x400
_RESERVED = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                       *(f"lpt{i}" for i in range(1, 10))})
_MACHINE = {"amd64": 0x8664, "arm64": 0xAA64}


class WindowsPythonRuntimeError(RuntimeError):
    """Content-free failure for embeddable-runtime preparation."""


@dataclass(frozen=True, slots=True)
class WindowsPythonRuntimeFile:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedWindowsPythonRuntime:
    declared_python_version: str
    architecture: str
    archive_sha256: str
    archive_size_bytes: int
    files: tuple[WindowsPythonRuntimeFile, ...]
    native_dll_dependencies_unresolved: bool = True
    runtime_execution_unproven: bool = True
    complete: bool = False


def _fail(message: str, error: Exception | None = None) -> None:
    if error is None:
        raise WindowsPythonRuntimeError(message)
    raise WindowsPythonRuntimeError(message) from error


def _ordinary_file(path: Path, maximum_size: int) -> os.stat_result:
    try:
        value = path.lstat()
    except OSError as error:
        _fail("windows Python runtime input is unavailable", error)
    if (not stat.S_ISREG(value.st_mode) or stat.S_ISLNK(value.st_mode)
            or getattr(value, "st_file_attributes", 0) & _REPARSE
            or value.st_nlink != 1 or not 0 < value.st_size <= maximum_size):
        _fail("windows Python runtime input is unsafe")
    return value


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_mode, left.st_nlink, left.st_size,
            left.st_mtime_ns, left.st_ctime_ns, getattr(left, "st_file_attributes", 0)) == (
        right.st_dev, right.st_ino, right.st_mode, right.st_nlink, right.st_size,
        right.st_mtime_ns, right.st_ctime_ns, getattr(right, "st_file_attributes", 0))


def _read_verified(path: Path, size: int, digest: str) -> bytes:
    before = _ordinary_file(path, _MAX_ARCHIVE_BYTES)
    if before.st_size != size:
        _fail("windows Python runtime input does not match review")
    try:
        chunks = bytearray()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not _same_file(before, opened):
                _fail("windows Python runtime input does not match review")
            while chunk := stream.read(min(64 * 1024, _MAX_ARCHIVE_BYTES + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > _MAX_ARCHIVE_BYTES:
                    _fail("windows Python runtime input does not match review")
            data = bytes(chunks)
    except OSError as error:
        _fail("windows Python runtime input is unavailable", error)
    if (not _same_file(before, _ordinary_file(path, _MAX_ARCHIVE_BYTES))
            or len(data) != size or hashlib.sha256(data).hexdigest() != digest):
        _fail("windows Python runtime input does not match review")
    return data


def _safe_parts(name: str) -> tuple[str, ...]:
    raw_parts = name.split("/")
    if any(part == "" for part in raw_parts):
        _fail("windows Python runtime archive layout is invalid")
    value = PurePosixPath(name)
    parts = value.parts
    if (not name or value.is_absolute() or "\\" in name or any(
            part in {"", ".", ".."} or ":" in part or part != part.rstrip(". ")
            or part.rstrip(". ").split(".", 1)[0].casefold() in _RESERVED for part in parts)):
        _fail("windows Python runtime archive layout is invalid")
    return parts


def _machine(data: bytes) -> int:
    if len(data) < 64 or data[:2] != b"MZ":
        _fail("windows Python runtime PE is invalid")
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if offset > 1024 * 1024 or len(data) < offset + 6 or data[offset:offset + 4] != b"PE\0\0":
        _fail("windows Python runtime PE is invalid")
    return int.from_bytes(data[offset + 4:offset + 6], "little")


def _validate_pth(data: bytes) -> None:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        _fail("windows Python runtime path configuration is invalid", error)
    active = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if active != ["python313.zip", "."]:
        _fail("windows Python runtime path configuration is not isolated")


def _extract(archive_bytes: bytes, destination: Path, version: str, architecture: str) -> tuple[WindowsPythonRuntimeFile, ...]:
    major, minor, _micro = version.split(".")
    stem = f"python{major}{minor}"
    required = {"python.exe", "pythonw.exe", f"{stem}.dll", "python3.dll", f"{stem}.zip", f"{stem}._pth", "LICENSE.txt", "vcruntime140.dll", "vcruntime140_1.dll"}
    files: list[WindowsPythonRuntimeFile] = []
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= _MAX_MEMBERS or sum(item.file_size for item in infos) > _MAX_TOTAL_BYTES:
                raise ValueError("bounds")
            names: set[str] = set()
            folded: set[str] = set()
            for info in infos:
                parts = _safe_parts(info.filename)
                if (info.is_dir() or info.filename in names or info.filename.casefold() in folded
                        or stat.S_ISLNK(info.external_attr >> 16) or info.file_size > _MAX_MEMBER_BYTES):
                    raise ValueError("member")
                names.add(info.filename); folded.add(info.filename.casefold())
                target = destination.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(); written = 0
                with archive.open(info) as source, target.open("xb") as output:
                    for chunk in iter(lambda: source.read(64 * 1024), b""):
                        written += len(chunk)
                        if written > info.file_size or written > _MAX_MEMBER_BYTES:
                            raise ValueError("member size")
                        digest.update(chunk); output.write(chunk)
                if written != info.file_size:
                    raise ValueError("member size")
                files.append(WindowsPythonRuntimeFile(info.filename, written, digest.hexdigest()))
                if info.filename == f"{stem}._pth":
                    _validate_pth(target.read_bytes())
                if info.filename.casefold().endswith((".exe", ".dll", ".pyd")):
                    if _machine(target.read_bytes()) != _MACHINE[architecture]:
                        raise ValueError("architecture")
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        _fail("windows Python runtime archive is invalid", error)
    if not required <= {item.relative_path for item in files}:
        _fail("windows Python runtime archive is incomplete")
    return tuple(sorted(files, key=lambda item: item.relative_path.casefold()))


def prepare_windows_python_runtime(*, archive: Path, expected_version: str,
                                   expected_architecture: str, expected_sha256: str,
                                   expected_size_bytes: int, destination: Path) -> PreparedWindowsPythonRuntime:
    """Verify and extract one pinned official embeddable runtime ZIP offline."""
    if (re.fullmatch(r"3\.13\.\d{1,3}", expected_version) is None
            or expected_architecture not in _MACHINE or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
            or isinstance(expected_size_bytes, bool) or not isinstance(expected_size_bytes, int)
            or not 0 < expected_size_bytes <= _MAX_ARCHIVE_BYTES):
        _fail("windows Python runtime identity is invalid")
    data = _read_verified(Path(archive), expected_size_bytes, expected_sha256)
    output = Path(destination).absolute()
    ancestor = output.parent
    while True:
        try: metadata = ancestor.lstat()
        except OSError as error: _fail("windows Python runtime destination is unavailable", error)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & _REPARSE:
            _fail("windows Python runtime destination is unavailable")
        if ancestor.parent == ancestor: break
        ancestor = ancestor.parent
    if ".." in Path(destination).parts or output.exists() or output.is_symlink():
        _fail("windows Python runtime destination is unavailable")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".python-runtime-incomplete-", dir=output.parent))
    try:
        files = _extract(data, temporary, expected_version, expected_architecture)
        if output.exists():
            _fail("windows Python runtime destination is unavailable")
        os.rename(temporary, output)
    except Exception:
        # Every archive member was checked as a regular, non-link file before
        # extraction. The fresh direct child is therefore safe task-owned cleanup.
        try:
            if temporary.exists() and temporary.parent == output.parent and not temporary.is_symlink():
                root_metadata = temporary.lstat()
                if getattr(root_metadata, "st_file_attributes", 0) & _REPARSE:
                    _fail("windows Python runtime cleanup unconfirmed")
                for current, directories, files_in_tree in os.walk(temporary, topdown=True, followlinks=False):
                    for name in [*directories, *files_in_tree]:
                        item = Path(current) / name; metadata = item.lstat()
                        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & _REPARSE:
                            _fail("windows Python runtime cleanup unconfirmed")
                shutil.rmtree(temporary)
        except OSError as error:
            _fail("windows Python runtime cleanup unconfirmed", error)
        raise
    return PreparedWindowsPythonRuntime(expected_version, expected_architecture,
                                        expected_sha256, expected_size_bytes, files)


__all__ = ("PreparedWindowsPythonRuntime", "WindowsPythonRuntimeError",
           "WindowsPythonRuntimeFile", "prepare_windows_python_runtime")
