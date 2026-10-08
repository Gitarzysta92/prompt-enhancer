"""Owner-local, read-only access to explicitly quarantined files.

Nothing in this adapter is reachable from HTTP.  It holds paths only in memory,
accepts a single portable basename, rechecks symlink/reparse state on each open,
uses bounded range reads, and never writes or deletes a file.  Integrity is
checked against the immutable manifest before registration and is checked again
by the recipient before a transfer can complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import stat
import threading

from ...application.file_sharing.contracts import (
    ByteRange,
    FileManifest,
    FileShareReasonCode,
    LocalFileDescriptor,
    MAX_CHUNK_BYTES,
    safe_local_basename,
)
from ...config import lexical_absolute_path, path_has_symlink_component


class QuarantineAccessError(RuntimeError):
    """Sanitized local rejection with no path or filename in its message."""

    def __init__(self, reason: FileShareReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(slots=True)
class QuarantinedLocalFileReader:
    root: Path
    quarantine_root_id: str
    lock: threading.RLock = field(default_factory=threading.RLock)
    _registrations: dict[str, tuple[LocalFileDescriptor, FileManifest]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.root = lexical_absolute_path(self.root)
        if (
            not self.root.is_dir()
            or path_has_symlink_component(self.root)
            or self.root.name in {"", ".", ".."}
        ):
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        # Validate the opaque root identifier through the local descriptor.
        LocalFileDescriptor(
            local_file_id="shr_" + "0" * 64,
            manifest_id="shr_" + "1" * 64,
            safe_basename="validation.bin",
            quarantine_root_id=self.quarantine_root_id,
            symlink_or_reparse_checked=True,
        )

    def _candidate(self, safe_basename: str) -> Path:
        try:
            name = safe_local_basename(safe_basename)
        except ValueError as error:
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            ) from error
        if path_has_symlink_component(self.root):
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        candidate = lexical_absolute_path(self.root / name)
        if candidate.parent != self.root:
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        try:
            metadata = candidate.lstat()
        except OSError as error:
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            ) from error
        is_reparse = bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or is_reparse
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or path_has_symlink_component(candidate)
        ):
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        return candidate

    def _open_readonly(self, descriptor: LocalFileDescriptor) -> tuple[int, FileManifest]:
        with self.lock:
            registration = self._registrations.get(descriptor.local_file_id)
            if registration is None or registration[0] != descriptor:
                raise QuarantineAccessError(
                    FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
                )
            manifest = registration[1]
        candidate = self._candidate(descriptor.safe_basename)
        before = candidate.lstat()
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor_number: int | None = None
        try:
            descriptor_number = os.open(candidate, flags)
            opened = os.fstat(descriptor_number)
            after = candidate.lstat()
        except OSError as error:
            if descriptor_number is not None:
                os.close(descriptor_number)
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            ) from error
        stable_identity = (
            before.st_dev,
            before.st_ino,
            after.st_dev,
            after.st_ino,
            opened.st_dev,
            opened.st_ino,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != manifest.byte_size
            or stable_identity[0:2] != stable_identity[2:4]
            or stable_identity[2:4] != stable_identity[4:6]
            or stat.S_ISLNK(after.st_mode)
            or bool(getattr(after, "st_file_attributes", 0) & 0x400)
        ):
            os.close(descriptor_number)
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        return descriptor_number, manifest

    @staticmethod
    def _read_exact(handle: int, length: int) -> bytes:
        remaining = length
        pieces: list[bytes] = []
        while remaining:
            piece = os.read(handle, remaining)
            if not piece:
                break
            pieces.append(piece)
            remaining -= len(piece)
        return b"".join(pieces)

    def register(
        self,
        *,
        local_file_id: str,
        safe_basename: str,
        manifest: FileManifest,
    ) -> LocalFileDescriptor:
        self._candidate(safe_basename)
        descriptor = LocalFileDescriptor(
            local_file_id=local_file_id,
            manifest_id=manifest.manifest_id,
            safe_basename=safe_basename,
            quarantine_root_id=self.quarantine_root_id,
            symlink_or_reparse_checked=True,
        )
        with self.lock:
            existing = self._registrations.get(local_file_id)
            if existing is not None and existing != (descriptor, manifest):
                raise QuarantineAccessError(
                    FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
                )
            self._registrations[local_file_id] = (descriptor, manifest)
        if not self.stat_matches_manifest(descriptor, manifest):
            with self.lock:
                self._registrations.pop(local_file_id, None)
            raise QuarantineAccessError(FileShareReasonCode.INTEGRITY_FAILED)
        return descriptor

    def stat_matches_manifest(
        self, descriptor: LocalFileDescriptor, manifest: FileManifest
    ) -> bool:
        if descriptor.manifest_id != manifest.manifest_id:
            return False
        try:
            handle, registered = self._open_readonly(descriptor)
        except QuarantineAccessError:
            return False
        if registered != manifest:
            os.close(handle)
            return False
        whole = hashlib.sha256()
        try:
            for expected in manifest.chunks:
                payload = self._read_exact(handle, expected.size)
                if len(payload) != expected.size:
                    return False
                whole.update(payload)
                if hashlib.sha256(payload).hexdigest() != expected.sha256:
                    return False
            if os.read(handle, 1):
                return False
            return whole.hexdigest() == manifest.whole_file_sha256
        finally:
            os.close(handle)

    def read_range(
        self, descriptor: LocalFileDescriptor, selected: ByteRange
    ) -> bytes:
        length = selected.end_exclusive - selected.start
        if length > MAX_CHUNK_BYTES:
            raise QuarantineAccessError(
                FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
            )
        handle, manifest = self._open_readonly(descriptor)
        try:
            if selected.end_exclusive > manifest.byte_size:
                raise QuarantineAccessError(
                    FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
                )
            os.lseek(handle, selected.start, os.SEEK_SET)
            payload = self._read_exact(handle, length)
            if len(payload) != length:
                raise QuarantineAccessError(
                    FileShareReasonCode.LOCAL_FILE_ACCESS_UNAVAILABLE
                )
            return payload
        finally:
            os.close(handle)

    def unregister(self, local_file_id: str) -> bool:
        """Forget the local mapping without modifying the selected file."""

        with self.lock:
            return self._registrations.pop(local_file_id, None) is not None


__all__ = ["QuarantineAccessError", "QuarantinedLocalFileReader"]
