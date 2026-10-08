"""Closed-code failures for direct file-sharing operations."""

from __future__ import annotations

from .contracts import FileShareReasonCode


class FileShareError(RuntimeError):
    def __init__(self, reason: FileShareReasonCode) -> None:
        super().__init__(reason.value)
        self.reason = reason


class FileShareAuthorizationError(FileShareError):
    pass


class FileShareConflictError(FileShareError):
    pass


class FileShareCapabilityError(FileShareError):
    pass


__all__ = [
    "FileShareAuthorizationError",
    "FileShareCapabilityError",
    "FileShareConflictError",
    "FileShareError",
]
