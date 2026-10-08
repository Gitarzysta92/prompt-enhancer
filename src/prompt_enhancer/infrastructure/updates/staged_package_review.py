"""Read-only review of the one private staged MSIX candidate."""

from __future__ import annotations

from ...application.updates.contracts import UpdateManifest
from ...application.updates.package_preflight import (
    AuthenticatedReleaseArtifact,
    MsixPackageExpectation,
    MsixPreflightReason,
    MsixPreflightResult,
    MsixPreflightState,
)
from ...application.updates.ports import SignedUpdateManifestEnvelope
from .msix_preflight import MsixPackagePreflight
from .staging import FileUpdateStagingStore, UpdateStagingError


class StagedPackageReview:
    """Verify only the exact, accounted-for ``artifact.staged`` candidate.

    The coordinator authenticates the envelope with its active trust policy.
    This adapter deliberately does not cache a positive outcome: it recovers
    and binds the on-disk candidate before and after each native preflight.
    """

    def __init__(
        self,
        *,
        staging_store: FileUpdateStagingStore,
        preflight: MsixPackagePreflight,
        expectation: MsixPackageExpectation,
    ) -> None:
        if not isinstance(staging_store, FileUpdateStagingStore):
            raise TypeError("staged review requires the private file staging store")
        self._staging_store = staging_store
        self._preflight = preflight
        # Revalidate even model-copy/construct inputs at this composition edge.
        self._expectation = MsixPackageExpectation.model_validate(
            expectation.model_dump(mode="python", warnings=False))

    def verify(
        self,
        *,
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
    ) -> MsixPreflightResult:
        try:
            candidate_manifest = UpdateManifest.model_validate(
                manifest.model_dump(mode="python", warnings=False))
            candidate_envelope = SignedUpdateManifestEnvelope(
                raw_manifest=envelope.raw_manifest,
                signature=envelope.signature,
                key_id=envelope.key_id,
            )
            recovered = self._staging_store.recover_envelope()
            if (recovered is None or recovered != candidate_envelope
                    or UpdateManifest.model_validate_json(recovered.raw_manifest)
                    != candidate_manifest):
                return _changed()
            artifact = AuthenticatedReleaseArtifact(
                sha256=candidate_manifest.artifact_sha256,
                size_bytes=candidate_manifest.artifact_size_bytes,
                release_version=candidate_manifest.release_version,
            )
        except (AttributeError, TypeError, ValueError, UpdateStagingError):
            return _changed()

        result = self._preflight.verify_staged(
            staged_package=self._staging_store,
            artifact=artifact,
            expectation=self._expectation,
        )
        try:
            recovered_after = self._staging_store.recover_envelope()
            if (recovered_after is None or recovered_after != candidate_envelope
                    or UpdateManifest.model_validate_json(recovered_after.raw_manifest)
                    != candidate_manifest):
                return _changed()
        except (TypeError, ValueError, UpdateStagingError):
            return _changed()
        return result


def _changed() -> MsixPreflightResult:
    return MsixPreflightResult(
        state=MsixPreflightState.REJECTED,
        reason=MsixPreflightReason.PACKAGE_CHANGED,
    )


__all__ = ("StagedPackageReview",)
