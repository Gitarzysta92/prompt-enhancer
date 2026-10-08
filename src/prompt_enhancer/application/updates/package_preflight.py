"""Offline, non-installable MSIX package preflight contracts."""

from __future__ import annotations

from enum import StrEnum
import re

from pydantic import Field, field_validator, model_validator

from ...domain import StrictModel
from .contracts import UpdateVerification, UpdateVerificationState


_DOT_QUAD = re.compile(r"^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})$")
_ARCHITECTURES = frozenset({"x86", "x64", "arm", "arm64", "x86a64", "neutral"})


class MsixPreflightReason(StrEnum):
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    UNSUPPORTED_PACKAGE = "unsupported_package"
    PACKAGE_IO_FAILED = "package_io_failed"
    PACKAGE_CHANGED = "package_changed"
    RELEASE_BINDING_MISMATCH = "release_binding_mismatch"
    ARCHIVE_INVALID = "archive_invalid"
    MANIFEST_INVALID = "manifest_invalid"
    IDENTITY_MISMATCH = "identity_mismatch"
    SIGNATURE_INVALID = "signature_invalid"
    SIGNATURE_UNVERIFIABLE = "signature_unverifiable"
    SIGNER_MISMATCH = "signer_mismatch"


class MsixPreflightState(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"


class AuthenticatedReleaseArtifact(StrictModel):
    """Hash/size evidence created only from an accepted update verification."""

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=4 * 1024 * 1024 * 1024, strict=True)
    release_version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

    @classmethod
    def from_accepted(cls, verification: UpdateVerification) -> AuthenticatedReleaseArtifact:
        verification = UpdateVerification.model_validate(
            verification.model_dump(mode="python", warnings=False)
        )
        if verification.state is not UpdateVerificationState.ACCEPTED or verification.manifest is None:
            raise ValueError("release artifact requires an accepted signed update")
        return cls(
            sha256=verification.manifest.artifact_sha256,
            size_bytes=verification.manifest.artifact_size_bytes,
            release_version=verification.manifest.release_version,
        )


class MsixPackageExpectation(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z0-9.-]{3,50}$")
    publisher: str = Field(min_length=1, max_length=8192, strict=True)
    architecture: str = Field(min_length=1, max_length=8, strict=True)
    signer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("architecture")
    @classmethod
    def require_architecture(cls, value: str) -> str:
        if value not in _ARCHITECTURES:
            raise ValueError("MSIX architecture is unsupported")
        return value


class MsixPreflightResult(StrictModel):
    state: MsixPreflightState
    reason: MsixPreflightReason | None = None
    can_install: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> MsixPreflightResult:
        if self.can_install:
            raise ValueError("package installation is not connected")
        if self.state is MsixPreflightState.VERIFIED and self.reason is not None:
            raise ValueError("verified package cannot include a rejection")
        if self.state is MsixPreflightState.REJECTED and self.reason is None:
            raise ValueError("rejected package requires a reason")
        return self


def expected_msix_version(release_version: str) -> str:
    """Map accepted release X.Y.Z conservatively to the MSIX dot quad X.Y.Z.0."""

    parts = release_version.split(".")
    if len(parts) != 3 or any(not part.isdigit() or int(part) > 65535 for part in parts):
        raise ValueError("release version cannot map to an MSIX version")
    return f"{release_version}.0"


__all__ = (
    "AuthenticatedReleaseArtifact",
    "MsixPackageExpectation",
    "MsixPreflightReason",
    "MsixPreflightResult",
    "MsixPreflightState",
    "expected_msix_version",
)
