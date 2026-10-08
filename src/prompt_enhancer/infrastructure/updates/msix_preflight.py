"""Read-only MSIX preflight; it has no installation or update authority."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import struct
from typing import Protocol
from xml.etree import ElementTree
import zipfile

from ...application.paths.policy import classify_windows_path_text
from ...application.paths.policy import validate_private_relative_parts
from ...application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
    MsixPreflightReason,
    MsixPreflightResult,
    MsixPreflightState,
    expected_msix_version,
)
from .staging import FileUpdateStagingStore, UpdateStagingError


_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_CENTRAL_DIRECTORY_BYTES = 8 * 1024 * 1024
_MAX_MANIFEST_BYTES = 256 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_APPX_MANIFEST = "appxmanifest.xml"
_APPX_NAMESPACE = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
_XML_DECLARATION = re.compile(r"^\s*<\?xml\s+[^?]*\?>", re.IGNORECASE)
_XML_ENCODING = re.compile(r"\bencoding\s*=\s*(['\"])([^'\"]+)\1", re.IGNORECASE)


class PackageSigner(Protocol):
    """Verifies the same already-open package file without trust retrieval."""

    def verify(self, *, path: Path, descriptor: int) -> str | None:
        """Return only the authenticated signer leaf DER SHA-256, or None."""


class PackageSignerUnavailable(RuntimeError):
    """Offline native verification could not establish signature evidence."""


class MsixPackagePreflight:
    """Offline preflight callable by release tooling; never installs a package."""

    def __init__(self, *, signer: PackageSigner) -> None:
        self._signer = signer

    def verify(
        self,
        *,
        package_path: Path,
        artifact: AuthenticatedReleaseArtifact,
        expectation: MsixPackageExpectation,
    ) -> MsixPreflightResult:
        return self._verify(
            package_path=package_path,
            artifact=artifact,
            expectation=expectation,
            allow_owned_staged=False,
        )

    def verify_staged(
        self,
        *,
        staged_package: FileUpdateStagingStore,
        artifact: AuthenticatedReleaseArtifact,
        expectation: MsixPackageExpectation,
    ) -> MsixPreflightResult:
        """Preflight only the fixed leaf supplied by the private staging store.

        The ordinary release-tool entry point remains ``.msix``-only.  This
        internal seam exists because renaming an authenticated staged artifact
        merely to satisfy a filename suffix would itself weaken the evidence.
        """

        try:
            if not isinstance(staged_package, FileUpdateStagingStore):
                return _rejected(MsixPreflightReason.PACKAGE_IO_FAILED)
            package_path = staged_package.staged_package_path()
        except (AttributeError, OSError, TypeError, ValueError,
                UpdateStagingError):
            return _rejected(MsixPreflightReason.PACKAGE_IO_FAILED)
        return self._verify(
            package_path=package_path,
            artifact=artifact,
            expectation=expectation,
            allow_owned_staged=True,
        )

    def _verify(
        self,
        *,
        package_path: Path,
        artifact: AuthenticatedReleaseArtifact,
        expectation: MsixPackageExpectation,
        allow_owned_staged: bool,
    ) -> MsixPreflightResult:
        try:
            artifact = AuthenticatedReleaseArtifact.model_validate(
                artifact.model_dump(mode="python", warnings=False)
            )
            expectation = MsixPackageExpectation.model_validate(
                expectation.model_dump(mode="python", warnings=False)
            )
        except (AttributeError, TypeError, ValueError):
            return _rejected(MsixPreflightReason.RELEASE_BINDING_MISMATCH)
        if not _safe_package_path(package_path, allow_owned_staged=allow_owned_staged):
            return _rejected(MsixPreflightReason.PACKAGE_IO_FAILED)
        try:
            path_snapshot = _path_components(package_path)
            descriptor = _open_readonly(package_path)
        except OSError:
            return _rejected(MsixPreflightReason.PACKAGE_IO_FAILED)
        try:
            before = os.fstat(descriptor)
            if (
                not _ordinary_file(before)
                or _leaf_snapshot(before) != path_snapshot[0]
            ):
                return _rejected(MsixPreflightReason.PACKAGE_CHANGED)
            if before.st_size != artifact.size_bytes:
                return _rejected(MsixPreflightReason.RELEASE_BINDING_MISMATCH)
            if not _bounded_zip_central_directory(descriptor, size=artifact.size_bytes):
                return _rejected(MsixPreflightReason.UNSUPPORTED_PACKAGE)
            digest = _hash_descriptor(descriptor, expected_size=artifact.size_bytes)
            if digest != artifact.sha256:
                return _rejected(MsixPreflightReason.RELEASE_BINDING_MISMATCH)
            identity_reason = _verify_identity(descriptor, artifact, expectation)
            if identity_reason is not None:
                return _rejected(identity_reason)
            try:
                signer_hash = self._signer.verify(path=package_path, descriptor=descriptor)
            except Exception:
                return _rejected(MsixPreflightReason.SIGNATURE_UNVERIFIABLE)
            if signer_hash is None:
                return _rejected(MsixPreflightReason.SIGNATURE_INVALID)
            if signer_hash != expectation.signer_sha256:
                return _rejected(MsixPreflightReason.SIGNER_MISMATCH)
            after = os.fstat(descriptor)
            if (
                not _same_file(before, after)
                or path_snapshot != _path_components(package_path)
                or _hash_descriptor(descriptor, expected_size=artifact.size_bytes)
                != digest
                or not _same_file(after, os.fstat(descriptor))
                or path_snapshot != _path_components(package_path)
            ):
                return _rejected(MsixPreflightReason.PACKAGE_CHANGED)
            descriptor_to_close = descriptor
            descriptor = -1
            try:
                os.close(descriptor_to_close)
            except OSError:
                return _rejected(MsixPreflightReason.PACKAGE_CHANGED)
            return MsixPreflightResult(state=MsixPreflightState.VERIFIED)
        except (
            OSError,
            ValueError,
            RuntimeError,
            NotImplementedError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ):
            return _rejected(MsixPreflightReason.ARCHIVE_INVALID)
        finally:
            try:
                if descriptor != -1:
                    os.close(descriptor)
            except OSError:
                pass


def _rejected(reason: MsixPreflightReason) -> MsixPreflightResult:
    return MsixPreflightResult(state=MsixPreflightState.REJECTED, reason=reason)


def _safe_package_path(path: PurePath, *, allow_owned_staged: bool = False) -> bool:
    try:
        raw = os.fspath(path)
    except (OSError, TypeError, ValueError):
        return False
    if (".." in PurePath(raw).parts or ".." in PureWindowsPath(raw).parts
            or classify_windows_path_text(raw) is not None):
        return False
    candidate = Path(raw)
    parts = tuple(part for part in candidate.parts if part not in {candidate.anchor, ""})
    if (validate_private_relative_parts(parts) is not None
            or any(ord(char) <= 31 or 127 <= ord(char) <= 159 for char in raw)
            or any(char in '<>"|?*' for char in raw)):
        return False
    suffix = candidate.suffix.lower()
    return candidate.is_absolute() and (
        suffix == ".msix" or (allow_owned_staged and candidate.name == "artifact.staged")
    )


def _path_components(path: Path) -> tuple[tuple[int, ...], ...]:
    """Bind the leaf contents and parent identities without directory churn."""

    snapshots: list[tuple[int, ...]] = []
    current = path
    while True:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_file_attributes", 0) & 0x400
        ):
            raise OSError("package path is a link")
        if current == path:
            snapshots.append(_leaf_snapshot(metadata))
        else:
            snapshots.append(
                (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode))
            )
        if current.parent == current:
            return tuple(snapshots)
        current = current.parent


def _leaf_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_nlink,
        stat.S_IFMT(metadata.st_mode),
    )


def _open_readonly(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def _ordinary_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and metadata.st_nlink == 1
        and not bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
    )


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        first.st_size,
        first.st_mtime_ns,
        first.st_ctime_ns,
        first.st_nlink,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_size,
        second.st_mtime_ns,
        second.st_ctime_ns,
        second.st_nlink,
    )


def _hash_descriptor(descriptor: int, *, expected_size: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest, total = hashlib.sha256(), 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, expected_size - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > expected_size:
            raise ValueError("package exceeded expected size")
        digest.update(chunk)
    if total != expected_size:
        raise ValueError("package size changed")
    return digest.hexdigest()


def _bounded_zip_central_directory(descriptor: int, *, size: int) -> bool:
    if size < 22:
        return False
    window = min(size, 65_557)
    os.lseek(descriptor, size - window, os.SEEK_SET)
    tail = _read_exact(descriptor, window)
    marker = tail.rfind(b"PK\x05\x06")
    if marker < 0 or marker + 22 > len(tail):
        return False
    fields = struct.unpack_from("<4s4H2LH", tail, marker)
    disk, central_disk, disk_entries, entries = fields[1:5]
    central_size, central_offset, comment_size = fields[5:8]
    if marker + 22 + comment_size != len(tail):
        return False
    if (disk != 0 or central_disk != 0 or disk_entries != entries
            or entries == 0xFFFF or central_size == 0xFFFFFFFF
            or central_offset == 0xFFFFFFFF):
        return False
    eocd_offset = size - window + marker
    if (
        entries > _MAX_ARCHIVE_ENTRIES
        or central_size > _MAX_CENTRAL_DIRECTORY_BYTES
        or central_offset + central_size != eocd_offset
    ):
        return False
    if eocd_offset >= 20:
        os.lseek(descriptor, eocd_offset - 20, os.SEEK_SET)
        if _read_exact(descriptor, 20).startswith(b"PK\x06\x07"):
            return False
    os.lseek(descriptor, central_offset, os.SEEK_SET)
    central_directory = _read_exact(descriptor, central_size)
    return _valid_central_directory(
        central_directory,
        expected_entries=entries,
        central_offset=central_offset,
    )


def _read_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            raise ValueError("archive changed during bounded read")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _valid_central_directory(
    value: bytes,
    *,
    expected_entries: int,
    central_offset: int,
) -> bool:
    """Require exact, non-ZIP64 central records before ``ZipFile`` parses them."""

    position = 0
    entries = 0
    while position < len(value):
        if position + 46 > len(value) or value[position:position + 4] != b"PK\x01\x02":
            return False
        fields = struct.unpack_from("<4s6H3L5H2L", value, position)
        compressed_size, uncompressed_size = fields[8:10]
        name_size, extra_size, comment_size, disk_start = fields[10:14]
        local_offset = fields[16]
        record_size = 46 + name_size + extra_size + comment_size
        if (
            position + record_size > len(value)
            or disk_start != 0
            or compressed_size == 0xFFFFFFFF
            or uncompressed_size == 0xFFFFFFFF
            or local_offset == 0xFFFFFFFF
            or local_offset >= central_offset
            or _contains_zip64_extra(value[position + 46 + name_size:position + 46 + name_size + extra_size])
        ):
            return False
        position += record_size
        entries += 1
    return position == len(value) and entries == expected_entries


def _contains_zip64_extra(value: bytes) -> bool:
    position = 0
    while position < len(value):
        if position + 4 > len(value):
            return True
        header_id, length = struct.unpack_from("<HH", value, position)
        position += 4
        if position + length > len(value) or header_id == 0x0001:
            return True
        position += length
    return False


def _verify_identity(
    descriptor: int,
    artifact: AuthenticatedReleaseArtifact,
    expectation: MsixPackageExpectation,
) -> MsixPreflightReason | None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(os.dup(descriptor), "rb") as stream:
        with zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ARCHIVE_ENTRIES:
                return MsixPreflightReason.UNSUPPORTED_PACKAGE
            if any(_unsafe_member(entry) for entry in infos) or _archive_tree_conflicts(infos):
                return MsixPreflightReason.ARCHIVE_INVALID
            names = [info.filename.casefold() for info in infos]
            if names.count(_APPX_MANIFEST) != 1 or len(names) != len(set(names)):
                return MsixPreflightReason.ARCHIVE_INVALID
            info = next(entry for entry in infos if entry.filename.casefold() == _APPX_MANIFEST)
            if info.file_size <= 0 or info.file_size > _MAX_MANIFEST_BYTES or info.is_dir():
                return MsixPreflightReason.ARCHIVE_INVALID
            with archive.open(info) as manifest_stream:
                raw = manifest_stream.read(_MAX_MANIFEST_BYTES + 1)
    if (
        len(raw) != info.file_size
        or len(raw) > _MAX_MANIFEST_BYTES
        or b"<!" in raw
        or b"\x00" in raw
    ):
        return MsixPreflightReason.MANIFEST_INVALID
    try:
        decoded = raw.decode("utf-8", errors="strict")
        if "\x00" in decoded:
            return MsixPreflightReason.MANIFEST_INVALID
        declaration = _XML_DECLARATION.match(decoded)
        if declaration is not None:
            declared_encoding = _XML_ENCODING.search(declaration.group(0))
            if (
                declared_encoding is not None
                and declared_encoding.group(2).casefold() not in {"utf-8", "utf8"}
            ):
                return MsixPreflightReason.MANIFEST_INVALID
        root = ElementTree.fromstring(decoded)
    except (UnicodeDecodeError, ElementTree.ParseError):
        return MsixPreflightReason.MANIFEST_INVALID
    identities = [element for element in root if element.tag == f"{{{_APPX_NAMESPACE}}}Identity"]
    if root.tag != f"{{{_APPX_NAMESPACE}}}Package" or len(identities) != 1:
        return MsixPreflightReason.MANIFEST_INVALID
    identity = identities[0]
    if (identity.get("Name") != expectation.name
            or identity.get("Publisher") != expectation.publisher
            or identity.get("ProcessorArchitecture") != expectation.architecture
            or identity.get("Version") != expected_msix_version(artifact.release_version)):
        return MsixPreflightReason.IDENTITY_MISMATCH
    return None


def _unsafe_member(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    mode = info.external_attr >> 16
    original = getattr(info, "orig_filename", name)
    if (original != name or not name or name.startswith(("/", "\\"))
            or "\\" in name or stat.S_ISLNK(mode) or info.flag_bits & 1):
        return True
    normalized = name[:-1] if info.is_dir() else name
    parts = tuple(normalized.split("/"))
    if not normalized or any(ord(char) <= 31 or 127 <= ord(char) <= 159 for char in normalized):
        return True
    return (validate_private_relative_parts(parts) is not None
            or any(char in '<>"|?*' for char in normalized)
            or info.file_size > _MAX_MEMBER_BYTES)


def _archive_tree_conflicts(infos: list[zipfile.ZipInfo]) -> bool:
    paths: dict[tuple[str, ...], bool] = {}
    for info in infos:
        normalized = info.filename[:-1] if info.is_dir() else info.filename
        path = tuple(part.casefold() for part in normalized.split("/"))
        previous = paths.get(path)
        if previous is not None and previous != info.is_dir():
            return True
        paths[path] = info.is_dir()
    for path, directory in paths.items():
        if not directory and any(
            not paths[prefix]
            for prefix in (path[:index] for index in range(1, len(path)))
            if prefix in paths
        ):
            return True
    return False


__all__ = ("MsixPackagePreflight", "PackageSigner")
