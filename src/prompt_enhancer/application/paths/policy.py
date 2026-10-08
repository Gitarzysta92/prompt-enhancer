"""Fail-closed, content-free policy contracts for private local paths.

The application layer deliberately does not claim that POSIX mode bits protect
a directory on Windows.  Platform adapters report one of three states and may
only return ``hardened`` after a platform-appropriate check succeeds.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePath, PureWindowsPath
from typing import Protocol

from pydantic import ConfigDict, Field, model_validator

from ...domain import StrictModel


MAX_PRIVATE_PATH_COMPONENTS = 64
MAX_PRIVATE_PATH_CHARACTERS = 1_024


class PathInspectionState(StrEnum):
    SAFE = "safe"
    REPARSE_OR_SYMLINK = "reparse_or_symlink"
    UNVERIFIABLE = "unverifiable"


class HardeningState(StrEnum):
    HARDENED = "hardened"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


class PathRejection(StrEnum):
    ALTERNATE_DATA_STREAM = "alternate_data_stream"
    DRIVE_RELATIVE = "drive_relative"
    EXTENDED_OR_UNC_PATH = "extended_or_unc_path"
    INSPECTION_FAILED = "inspection_failed"
    INVALID_COMPONENT = "invalid_component"
    OUTSIDE_PRIVATE_ROOT = "outside_private_root"
    PATH_NOT_CREATED = "path_not_created"
    PATH_TOO_DEEP = "path_too_deep"
    PATH_TOO_LONG = "path_too_long"
    PERMISSIONS_UNVERIFIED = "permissions_unverified"
    REPARSE_OR_SYMLINK = "reparse_or_symlink"
    RESERVED_DEVICE_NAME = "reserved_device_name"
    TRAILING_DOT_OR_SPACE = "trailing_dot_or_space"
    TRAVERSAL_COMPONENT = "traversal_component"
    WINDOWS_DACL_UNAVAILABLE = "windows_dacl_unavailable"


class PathInspection(StrictModel):
    state: PathInspectionState
    rejection: PathRejection | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> PathInspection:
        if self.state is PathInspectionState.SAFE and self.rejection is not None:
            raise ValueError("safe path inspection cannot include a rejection")
        if self.state is not PathInspectionState.SAFE and self.rejection is None:
            raise ValueError("unsafe path inspection requires a rejection")
        return self


class HardeningReport(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: HardeningState
    reason: PathRejection | None = None
    existing_components_checked: int = Field(default=0, ge=0, le=MAX_PRIVATE_PATH_COMPONENTS + 8)

    @model_validator(mode="after")
    def validate_reason(self) -> HardeningReport:
        if self.state is HardeningState.HARDENED and self.reason is not None:
            raise ValueError("hardened path cannot include a rejection")
        if self.state is not HardeningState.HARDENED and self.reason is None:
            raise ValueError("non-hardened path requires a reason")
        return self


class PrivatePathHardener(Protocol):
    """Port implemented by an OS-specific, fail-closed path adapter."""

    def inspect(self, path: PurePath) -> HardeningReport: ...


class PrivateUpdateStagingRootPreparer(Protocol):
    """Creates only the fixed private update-staging child when supported."""

    def prepare_private_update_staging_root(self, path: PurePath) -> HardeningReport: ...


_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
    | {f"COM{index}" for index in ("¹", "²", "³")}
    | {f"LPT{index}" for index in ("¹", "²", "³")}
)


def validate_private_relative_parts(parts: tuple[str, ...]) -> PathRejection | None:
    """Validate portable relative components without touching the filesystem."""

    if len(parts) > MAX_PRIVATE_PATH_COMPONENTS:
        return PathRejection.PATH_TOO_DEEP
    if sum(len(part) + 1 for part in parts) > MAX_PRIVATE_PATH_CHARACTERS:
        return PathRejection.PATH_TOO_LONG
    for part in parts:
        if part in {"", ".", ".."}:
            return PathRejection.TRAVERSAL_COMPONENT
        if "\x00" in part or "/" in part or "\\" in part:
            return PathRejection.INVALID_COMPONENT
        if part.endswith((".", " ")):
            return PathRejection.TRAILING_DOT_OR_SPACE
        if ":" in part:
            return PathRejection.ALTERNATE_DATA_STREAM
        stem = part.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            return PathRejection.RESERVED_DEVICE_NAME
    return None


def classify_windows_path_text(value: str) -> PathRejection | None:
    """Reject ambiguous Windows path forms before a platform adapter sees them."""

    normalized = value.replace("/", "\\")
    if normalized.startswith(("\\\\", "\\\\?\\", "\\??\\")):
        return PathRejection.EXTENDED_OR_UNC_PATH
    parsed = PureWindowsPath(normalized)
    if parsed.drive and not parsed.root:
        return PathRejection.DRIVE_RELATIVE
    return None
