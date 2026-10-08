"""Signature verification port.  There is intentionally no fetcher port implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Protocol

from .contracts import ApplicationUpdateReason, UpdateChannel, UpdateManifest
from .package_preflight import MsixPreflightResult

_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SignatureState(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN_KEY = "unknown_key"


class ManifestSignatureVerifier(Protocol):

    def verify(self, *, payload: bytes, signature: bytes,
               key_id: str) -> SignatureState:
        ...


@dataclass(frozen=True, slots=True)
class SignedUpdateManifestEnvelope:
    raw_manifest: bytes = field(repr=False)
    signature: bytes = field(repr=False)
    key_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.raw_manifest, bytes) or not isinstance(
                self.signature, bytes):
            raise TypeError("signed update envelope requires bytes")
        if _KEY_ID.fullmatch(self.key_id) is None:
            raise ValueError("signed update key identity is invalid")


class UpdateManifestSource(Protocol):

    def fetch_manifest(self, *,
                       channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        ...


class UpdateArtifactSource(Protocol):
    """Streams an already pinned artifact URL for an explicitly chosen release."""

    def iter_artifact(
        self,
        *,
        channel: UpdateChannel,
        release_version: str,
        artifact_sha256: str,
        artifact_size_bytes: int,
    ) -> object:
        ...


class StagedPackageVerifier(Protocol):
    """Read-only verification of the exact staged signed-envelope candidate."""

    def verify(self, *, manifest: UpdateManifest,
               envelope: SignedUpdateManifestEnvelope) -> MsixPreflightResult:
        ...


class TrustedReplayLedger(Protocol):
    """Durable signed-envelope evidence used only after re-authentication.

    Implementations retain no derived version, hash, endpoint, or owner data.
    Callers must authenticate an envelope under their active trust policy before
    persisting it and again after loading it.
    """

    def load(self) -> SignedUpdateManifestEnvelope | None:
        ...

    def persist_authenticated(
            self,
            *,
            expected_envelope: SignedUpdateManifestEnvelope | None,
            envelope: SignedUpdateManifestEnvelope,
    ) -> None:
        """Compare-and-swap an exact loaded envelope under a process guard."""
        ...


class ArtifactStagingError(RuntimeError):
    """Typed, content-free staging result consumed by the coordinator."""

    def __init__(self, reason: ApplicationUpdateReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


class ArtifactStagingCancelled(ArtifactStagingError):

    def __init__(self) -> None:
        super().__init__(ApplicationUpdateReason.STAGING_INTERRUPTED)
