"""Owner-gated, content-free application update staging coordination."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
import hashlib
import secrets
from threading import Event, RLock, Thread
from typing import Protocol

from .contracts import (
    ApplicationUpdateReason,
    ApplicationUpdateState,
    ApplicationUpdateStatus,
    PackageReview,
    PackageReviewState,
    UpdateChannel,
    UpdateManifest,
    UpdateRejection,
    UpdateVerificationState,
)
from .ports import (
    ArtifactStagingError,
    ManifestSignatureVerifier,
    SignedUpdateManifestEnvelope,
    TrustedReplayLedger,
    UpdateArtifactSource,
    UpdateManifestSource,
    StagedPackageVerifier,
)
from .package_preflight import MsixPreflightResult, MsixPreflightState
from .verification import (
    authenticate_signed_update_manifest,
    verify_update_manifest,
)


class UpdateActionConflict(RuntimeError):
    """Content-free optimistic-concurrency or active-operation refusal."""


class UpdateStagingPort(Protocol):

    def stage(
        self,
        *,
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
        chunks: Iterable[bytes],
        cancelled: Callable[[], bool],
        on_progress: Callable[[int], None],
    ) -> None:
        ...


class ApplicationUpdateSurface(Protocol):

    def status(self) -> ApplicationUpdateStatus:
        ...

    def check(self, *, expected_revision: int,
              expected_instance_id: str) -> ApplicationUpdateStatus:
        ...

    def stage(self, *, expected_revision: int,
              expected_instance_id: str) -> ApplicationUpdateStatus:
        ...

    def cancel(self, *, expected_revision: int,
               expected_instance_id: str) -> ApplicationUpdateStatus:
        ...

    def retry(self, *, expected_revision: int,
              expected_instance_id: str) -> ApplicationUpdateStatus:
        ...

    def verify(self, *, expected_revision: int,
               expected_instance_id: str) -> ApplicationUpdateStatus:
        ...

    def shutdown(self) -> None:
        ...


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


class UnconfiguredApplicationUpdateSurface:
    """Default composition: no pinned trust, no egress, no staging."""

    def __init__(
        self,
        *,
        installed_version: str,
        channel: UpdateChannel = UpdateChannel.STABLE,
    ) -> None:
        self._status = ApplicationUpdateStatus(
            installed_version=installed_version,
            channel=channel,
            state=ApplicationUpdateState.UNCONFIGURED,
            instance_id=secrets.token_hex(16),
            revision=0,
            reason_code=ApplicationUpdateReason.RELEASE_FEED_UNCONFIGURED,
            can_check=False,
            can_stage=False,
            can_cancel=False,
            can_retry=False,
            can_apply=False,
            package_review=PackageReview(
                state=PackageReviewState.NOT_CONFIGURED),
        )

    def status(self) -> ApplicationUpdateStatus:
        return self._status

    def check(self, **_: object) -> ApplicationUpdateStatus:
        return self._status

    stage = check
    cancel = check
    retry = check
    verify = check

    def shutdown(self) -> None:
        return None


class ApplicationUpdateCoordinator:
    """A single, bounded staging worker.  It never installs or relaunches."""

    def __init__(
        self,
        *,
        installed_version: str,
        channel: UpdateChannel,
        source: UpdateManifestSource,
        verifier: ManifestSignatureVerifier,
        artifact_source: UpdateArtifactSource | None = None,
        staging_store: UpdateStagingPort | None = None,
        replay_ledger: TrustedReplayLedger | None = None,
        package_verifier: StagedPackageVerifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._installed_version, self._channel = installed_version, channel
        self._source, self._verifier = source, verifier
        self._artifact_source, self._staging_store = artifact_source, staging_store
        self._replay_ledger, self._clock = replay_ledger, clock
        self._package_verifier = package_verifier
        self._lock = RLock()
        self._active: str | None = None
        self._worker: Thread | None = None
        self._cancel = Event()
        self._closed = False
        self._instance_id, self._revision = secrets.token_hex(16), 0
        self._manifest: UpdateManifest | None = None
        self._envelope: SignedUpdateManifestEnvelope | None = None
        self._staged_manifest: UpdateManifest | None = None
        self._staged_envelope: SignedUpdateManifestEnvelope | None = None
        self._supersede_envelope: SignedUpdateManifestEnvelope | None = None
        self._highest_seen: tuple[tuple[int, int, int], str] | None = None
        self._replay_envelope: SignedUpdateManifestEnvelope | None = None
        self._retry_stage = False
        self._status = self._make(ApplicationUpdateState.READY_TO_CHECK,
                                  can_check=True)
        self._restore_replay_identity()
        if self._status.state is ApplicationUpdateState.FAILED:
            return
        self._restore_staged_candidate()

    @staticmethod
    def _identity(
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
    ) -> tuple[tuple[int, int, int], str]:
        return (_version_tuple(manifest.release_version),
                hashlib.sha256(envelope.raw_manifest).hexdigest())

    def _quarantine_replay(
        self,
        *,
        checked_at: datetime,
        verification: UpdateRejection | None = None,
    ) -> None:
        self._status = self._make(
            ApplicationUpdateState.FAILED,
            last_checked_at=checked_at,
            reason_code=ApplicationUpdateReason.MANIFEST_REJECTED
            if verification is not None else
            ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
            verification_code=verification,
            can_check=False,
            can_retry=False,
        )

    def _restore_replay_identity(self) -> None:
        """Load only historically authentic evidence; do not expose a release."""

        if self._replay_ledger is None:
            return
        checked_at = self._checked_at()
        try:
            envelope = self._replay_ledger.load()
        except Exception:
            self._quarantine_replay(checked_at=checked_at)
            return
        if envelope is None:
            return
        authenticated = authenticate_signed_update_manifest(
            envelope.raw_manifest,
            signature=envelope.signature,
            key_id=envelope.key_id,
            verifier=self._verifier,
        )
        if (authenticated.state is not UpdateVerificationState.ACCEPTED
                or authenticated.manifest is None):
            self._quarantine_replay(
                checked_at=checked_at,
                verification=authenticated.rejection
                or UpdateRejection.INVALID_SCHEMA,
            )
            return
        if authenticated.manifest.channel is not self._channel:
            self._quarantine_replay(
                checked_at=checked_at,
                verification=UpdateRejection.CHANNEL_MISMATCH,
            )
            return
        self._highest_seen = self._identity(authenticated.manifest, envelope)
        self._replay_envelope = envelope

    def _persist_new_high_water(
        self,
        *,
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
    ) -> bool:
        """CAS-persist an authenticated floor, including its exact re-check."""

        identity = self._identity(manifest, envelope)
        if self._highest_seen is not None:
            if identity[0] < self._highest_seen[0]:
                return False
            if identity[0] == self._highest_seen[0]:
                if identity[1] != self._highest_seen[1]:
                    return False
        if self._replay_ledger is not None:
            try:
                self._replay_ledger.persist_authenticated(
                    expected_envelope=self._replay_envelope,
                    envelope=envelope,
                )
            except Exception:
                return False
        self._highest_seen = identity
        self._replay_envelope = envelope
        return True

    def _restore_staged_candidate(self) -> None:
        """Re-authenticate durable stage evidence under current trust policy."""

        recover = getattr(self._staging_store, "recover_envelope", None)
        if recover is None:
            return
        checked_at = self._checked_at()
        try:
            envelope = recover()
        except ArtifactStagingError as error:
            self._status = self._make(
                ApplicationUpdateState.FAILED,
                last_checked_at=checked_at,
                reason_code=error.reason,
                can_check=False,
                can_retry=False,
            )
            return
        if envelope is None:
            return
        authenticated = authenticate_signed_update_manifest(
            envelope.raw_manifest,
            signature=envelope.signature,
            key_id=envelope.key_id,
            verifier=self._verifier,
        )
        if (authenticated.state is not UpdateVerificationState.ACCEPTED
                or authenticated.manifest is None
                or authenticated.manifest.channel is not self._channel):
            self._quarantine_replay(
                checked_at=checked_at,
                verification=authenticated.rejection
                or UpdateRejection.CHANNEL_MISMATCH,
            )
            return
        identity = self._identity(authenticated.manifest, envelope)
        if self._highest_seen is not None:
            if (identity[0] == self._highest_seen[0]
                    and identity[1] != self._highest_seen[1]):
                self._quarantine_replay(
                    checked_at=checked_at,
                    verification=UpdateRejection.RELEASE_IDENTITY_CONFLICT,
                )
                return
        if (self._highest_seen is None or identity[0] > self._highest_seen[0]):
            if not self._persist_new_high_water(
                    manifest=authenticated.manifest,
                    envelope=envelope):
                self._quarantine_replay(checked_at=checked_at)
                return
        verification = verify_update_manifest(
            envelope.raw_manifest,
            signature=envelope.signature,
            key_id=envelope.key_id,
            verifier=self._verifier,
            now=checked_at,
            installed_version=self._installed_version,
            channel=self._channel,
        )
        if verification.state is not UpdateVerificationState.ACCEPTED or verification.manifest is None:
            self._status = self._make(
                ApplicationUpdateState.FAILED,
                last_checked_at=checked_at,
                reason_code=ApplicationUpdateReason.
                ARTIFACT_VERIFICATION_FAILED,
                can_check=False,
                can_retry=False,
            )
            return
        self._manifest = verification.manifest
        self._envelope = envelope
        self._staged_manifest = verification.manifest
        self._staged_envelope = envelope
        self._status = self._make(
            ApplicationUpdateState.STAGED,
            available_version=verification.manifest.release_version,
            artifact_size_bytes=verification.manifest.artifact_size_bytes,
            downloaded_bytes=verification.manifest.artifact_size_bytes,
            last_checked_at=checked_at,
            can_check=True,
            can_verify=self._package_verifier is not None,
        )

    def _make(self,
              state: ApplicationUpdateState,
              *,
              available_version: str | None = None,
              artifact_size_bytes: int | None = None,
              downloaded_bytes: int | None = None,
              last_checked_at: datetime | None = None,
              reason_code: ApplicationUpdateReason | None = None,
              verification_code: UpdateRejection | None = None,
              can_check: bool = False,
              can_stage: bool = False,
              can_cancel: bool = False,
              can_retry: bool = False,
              can_verify: bool = False,
              package_review: PackageReview | None = None) -> ApplicationUpdateStatus:
        return ApplicationUpdateStatus(
            installed_version=self._installed_version,
            channel=self._channel,
            state=state,
            instance_id=self._instance_id,
            revision=self._revision,
            available_version=available_version,
            artifact_size_bytes=artifact_size_bytes,
            downloaded_bytes=downloaded_bytes,
            last_checked_at=last_checked_at,
            reason_code=reason_code,
            verification_code=verification_code,
            can_check=can_check,
            can_stage=can_stage,
            can_cancel=can_cancel,
            can_retry=can_retry,
            can_apply=False,
            can_verify=can_verify,
            package_review=package_review or PackageReview(
                state=(PackageReviewState.NOT_CHECKED if can_verify
                       else PackageReviewState.NOT_CONFIGURED)
                if state is ApplicationUpdateState.STAGED
                else (PackageReviewState.NOT_CONFIGURED
                      if state is ApplicationUpdateState.UNCONFIGURED
                      else PackageReviewState.NOT_STAGED)))

    def status(self) -> ApplicationUpdateStatus:
        with self._lock:
            return self._status

    def _publish(self,
                 status: ApplicationUpdateStatus,
                 *,
                 lifecycle: bool = True) -> ApplicationUpdateStatus:
        if lifecycle:
            self._revision += 1
            status = status.model_copy(update={"revision": self._revision})
        self._status = status
        return status

    def _assert_action(self, revision: int, instance_id: str) -> None:
        if self._closed or revision != self._revision or not secrets.compare_digest(
                instance_id, self._instance_id):
            raise UpdateActionConflict("update_action_refused")
        if self._active is not None:
            raise UpdateActionConflict("update_operation_active")

    def _checked_at(self) -> datetime:
        try:
            value = self._clock()
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value
        except Exception:
            return datetime.now(UTC)

    def _failed(
        self,
        *,
        checked_at: datetime,
        reason: ApplicationUpdateReason,
        verification: UpdateRejection | None = None,
        retry: bool = False,
        can_check: bool = True,
        manifest: UpdateManifest | None = None,
    ) -> ApplicationUpdateStatus:
        return self._publish(
            self._make(
                ApplicationUpdateState.FAILED,
                available_version=manifest.release_version
                if manifest else None,
                artifact_size_bytes=manifest.artifact_size_bytes
                if manifest else None,
                downloaded_bytes=0 if manifest else None,
                last_checked_at=checked_at,
                reason_code=reason,
                verification_code=verification,
                can_check=can_check,
                can_retry=retry,
            ))

    def check(
            self,
            *,
            expected_revision: int | None = None,
            expected_instance_id: str | None = None
    ) -> ApplicationUpdateStatus:
        with self._lock:
            if expected_revision is None and expected_instance_id is None:
                expected_revision, expected_instance_id = self._revision, self._instance_id
            self._assert_action(expected_revision, expected_instance_id)
            if not self._status.can_check:
                raise UpdateActionConflict("update_check_refused")
            self._active = "check"
            self._retry_stage = False
            self._publish(self._make(ApplicationUpdateState.CHECKING))
        checked_at = self._checked_at()
        try:
            envelope = self._source.fetch_manifest(channel=self._channel)
        except Exception:
            with self._lock:
                self._active = None
                if self._closed:
                    return self._failed(
                        checked_at=checked_at,
                        reason=ApplicationUpdateReason.
                        STAGING_CLEANUP_UNCONFIRMED,
                        retry=False,
                        can_check=False,
                    )
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.RELEASE_FEED_UNAVAILABLE,
                    retry=True)
        authenticated = authenticate_signed_update_manifest(
            envelope.raw_manifest,
            signature=envelope.signature,
            key_id=envelope.key_id,
            verifier=self._verifier,
        )
        verification = verify_update_manifest(
            envelope.raw_manifest,
            signature=envelope.signature,
            key_id=envelope.key_id,
            verifier=self._verifier,
            now=checked_at,
            installed_version=self._installed_version,
            channel=self._channel)
        with self._lock:
            self._active = None
            if self._closed:
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False,
                )
            if verification.state is UpdateVerificationState.REJECTED:
                if verification.rejection is UpdateRejection.CURRENT_VERSION:
                    current_manifest = authenticated.manifest
                    if (authenticated.state is not UpdateVerificationState.ACCEPTED
                            or current_manifest is None):
                        return self._failed(
                            checked_at=checked_at,
                            reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                            verification=authenticated.rejection
                            or UpdateRejection.INVALID_SCHEMA,
                        )
                    identity = self._identity(current_manifest, envelope)
                    if (self._highest_seen is not None
                            and identity[0] < self._highest_seen[0]):
                        return self._failed(
                            checked_at=checked_at,
                            reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                            verification=UpdateRejection.REPLAYED_RELEASE,
                        )
                    if (self._highest_seen is not None
                            and identity[0] == self._highest_seen[0]
                            and identity[1] != self._highest_seen[1]):
                        return self._failed(
                            checked_at=checked_at,
                            reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                            verification=UpdateRejection.RELEASE_IDENTITY_CONFLICT,
                        )
                    return self._publish(
                        self._make(ApplicationUpdateState.CURRENT,
                                   last_checked_at=checked_at,
                                   can_check=True))
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                    verification=verification.rejection)
            manifest = verification.manifest
            if manifest is None:
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                    verification=UpdateRejection.INVALID_SCHEMA)
            identity = self._identity(manifest, envelope)
            if self._highest_seen and (
                    identity[0] < self._highest_seen[0] or
                (identity[0] == self._highest_seen[0]
                 and identity[1] != self._highest_seen[1])):
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                    verification=UpdateRejection.REPLAYED_RELEASE
                    if identity[0] < self._highest_seen[0] else
                    UpdateRejection.RELEASE_IDENTITY_CONFLICT)
            if not self._persist_new_high_water(
                    manifest=manifest,
                    envelope=envelope):
                return self._failed(
                    checked_at=checked_at,
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False,
                )
            if (self._staged_manifest is not None
                    and self._staged_envelope is not None
                    and self._staged_manifest.release_version
                    == manifest.release_version
                    and self._staged_envelope.raw_manifest
                    == envelope.raw_manifest):
                self._manifest, self._envelope = manifest, envelope
                return self._publish(
                    self._make(
                        ApplicationUpdateState.STAGED,
                        available_version=manifest.release_version,
                        artifact_size_bytes=manifest.artifact_size_bytes,
                        downloaded_bytes=manifest.artifact_size_bytes,
                        last_checked_at=checked_at,
                        can_check=True,
                        can_verify=self._package_verifier is not None,
                    ))
            if self._staged_envelope is not None:
                self._supersede_envelope = self._staged_envelope
            self._manifest, self._envelope = manifest, envelope
            return self._publish(
                self._make(ApplicationUpdateState.AVAILABLE,
                           available_version=manifest.release_version,
                           artifact_size_bytes=manifest.artifact_size_bytes,
                           downloaded_bytes=0,
                           last_checked_at=checked_at,
                           can_check=True,
                           can_stage=self._artifact_source is not None
                           and self._staging_store is not None))

    def stage(self, *, expected_revision: int,
              expected_instance_id: str) -> ApplicationUpdateStatus:
        with self._lock:
            self._assert_action(expected_revision, expected_instance_id)
            if not self._status.can_stage:
                raise UpdateActionConflict("update_stage_refused")
            if self._status.state is not ApplicationUpdateState.AVAILABLE or self._manifest is None or self._envelope is None or self._artifact_source is None or self._staging_store is None:
                raise UpdateActionConflict("update_stage_refused")
            manifest, envelope = self._manifest, self._envelope
            verification = verify_update_manifest(
                envelope.raw_manifest,
                signature=envelope.signature,
                key_id=envelope.key_id,
                verifier=self._verifier,
                now=self._checked_at(),
                installed_version=self._installed_version,
                channel=self._channel)
            if verification.state is not UpdateVerificationState.ACCEPTED or verification.manifest != manifest:
                return self._failed(
                    checked_at=self._checked_at(),
                    reason=ApplicationUpdateReason.MANIFEST_REJECTED,
                    verification=verification.rejection
                    or UpdateRejection.INVALID_SCHEMA)
            # Re-CAS the exact evidence before downloading: another process
            # may have advanced or removed the durable floor since this owner
            # last checked the feed.
            if not self._persist_new_high_water(
                    manifest=manifest,
                    envelope=envelope):
                return self._failed(
                    checked_at=self._checked_at(),
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False,
                    manifest=manifest,
                )
            if self._supersede_envelope is not None:
                supersede = getattr(self._staging_store, "supersede_staged",
                                    None)
                if not callable(supersede):
                    return self._failed(
                        checked_at=self._checked_at(),
                        reason=ApplicationUpdateReason.
                        STAGING_CLEANUP_UNCONFIRMED,
                        retry=False,
                        can_check=False,
                        manifest=manifest,
                    )
                try:
                    supersede(expected_envelope=self._supersede_envelope)
                except ArtifactStagingError:
                    return self._failed(
                        checked_at=self._checked_at(),
                        reason=ApplicationUpdateReason.
                        STAGING_CLEANUP_UNCONFIRMED,
                        retry=False,
                        can_check=False,
                        manifest=manifest,
                    )
                self._supersede_envelope = None
                self._staged_manifest = None
                self._staged_envelope = None
            self._active = "stage"
            self._cancel.clear()
            snapshot = self._publish(
                self._make(ApplicationUpdateState.STAGING,
                           available_version=manifest.release_version,
                           artifact_size_bytes=manifest.artifact_size_bytes,
                           downloaded_bytes=0,
                           last_checked_at=self._status.last_checked_at,
                           can_cancel=True))
            self._worker = Thread(target=self._stage_worker,
                                  args=(manifest, envelope),
                                  daemon=False,
                                  name="application-update-staging")
            try:
                self._worker.start()
            except RuntimeError:
                self._active = None
                self._worker = None
                return self._failed(
                    checked_at=self._checked_at(),
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False,
                    manifest=manifest,
                )
            return snapshot

    def _stage_worker(
        self,
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
    ) -> None:
        chunks: object | None = None
        try:
            assert self._artifact_source is not None and self._staging_store is not None
            chunks = self._artifact_source.iter_artifact(
                channel=self._channel,
                release_version=manifest.release_version,
                artifact_sha256=manifest.artifact_sha256,
                artifact_size_bytes=manifest.artifact_size_bytes,
            )
            self._staging_store.stage(manifest=manifest,
                                      envelope=envelope,
                                      chunks=chunks,
                                      cancelled=self._cancel.is_set,
                                      on_progress=self._progress)
            stream = chunks
            chunks = None
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    raise ArtifactStagingError(
                        ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
                    ) from error
        except Exception as error:
            close = getattr(chunks, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    error = ArtifactStagingError(
                        ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
            reason = error.reason if isinstance(
                error, ArtifactStagingError
            ) else ApplicationUpdateReason.ARTIFACT_DOWNLOAD_FAILED
            with self._lock:
                self._active = None
                if self._closed:
                    reason = ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
                self._retry_stage = not self._closed and reason in {
                    ApplicationUpdateReason.ARTIFACT_DOWNLOAD_FAILED,
                    ApplicationUpdateReason.STAGING_INTERRUPTED,
                }
                self._failed(
                    checked_at=self._checked_at(),
                    reason=reason,
                    retry=self._retry_stage,
                    can_check=(not self._closed
                               and reason is not ApplicationUpdateReason.
                               STAGING_CLEANUP_UNCONFIRMED),
                    manifest=manifest,
                )
        else:
            with self._lock:
                if self._closed:
                    self._active = None
                    self._failed(checked_at=self._checked_at(),
                                 reason=ApplicationUpdateReason.
                                 STAGING_CLEANUP_UNCONFIRMED,
                                 retry=False,
                                 can_check=False)
                    return
                self._active = None
                self._staged_manifest = manifest
                self._staged_envelope = envelope
                self._publish(
                    self._make(
                        ApplicationUpdateState.STAGED,
                        available_version=manifest.release_version,
                        artifact_size_bytes=manifest.artifact_size_bytes,
                        downloaded_bytes=manifest.artifact_size_bytes,
                        last_checked_at=self._status.last_checked_at,
                        can_check=True,
                        can_verify=self._package_verifier is not None))

    def _progress(self, bytes_written: int) -> None:
        with self._lock:
            if self._status.state is ApplicationUpdateState.STAGING:
                self._status = self._status.model_copy(
                    update={"downloaded_bytes": bytes_written})

    def cancel(self, *, expected_revision: int,
               expected_instance_id: str) -> ApplicationUpdateStatus:
        with self._lock:
            if not self._status.can_cancel or expected_revision != self._revision or not secrets.compare_digest(
                    expected_instance_id,
                    self._instance_id) or self._active != "stage":
                raise UpdateActionConflict("update_cancel_refused")
            self._cancel.set()
            return self._publish(
                self._make(
                    ApplicationUpdateState.STAGING,
                    available_version=self._status.available_version,
                    artifact_size_bytes=self._status.artifact_size_bytes,
                    downloaded_bytes=self._status.downloaded_bytes,
                    last_checked_at=self._status.last_checked_at,
                    can_cancel=False))

    def retry(self, *, expected_revision: int,
              expected_instance_id: str) -> ApplicationUpdateStatus:
        with self._lock:
            self._assert_action(expected_revision, expected_instance_id)
            if self._status.state is not ApplicationUpdateState.FAILED or not self._status.can_retry:
                raise UpdateActionConflict("update_retry_refused")
            if self._retry_stage and self._manifest is not None and self._envelope is not None:
                available = self._publish(
                    self._make(
                        ApplicationUpdateState.AVAILABLE,
                        available_version=self._manifest.release_version,
                        artifact_size_bytes=self._manifest.artifact_size_bytes,
                        downloaded_bytes=0,
                        last_checked_at=self._status.last_checked_at,
                        can_check=True,
                        can_stage=True,
                    ))
                retry_stage = True
            else:
                available = self._publish(
                    self._make(ApplicationUpdateState.READY_TO_CHECK,
                               can_check=True))
                retry_stage = False
        if retry_stage:
            return self.stage(
                expected_revision=available.revision,
                expected_instance_id=available.instance_id,
            )
        return self.check(
            expected_revision=available.revision,
            expected_instance_id=available.instance_id,
        )

    def verify(self, *, expected_revision: int,
               expected_instance_id: str) -> ApplicationUpdateStatus:
        with self._lock:
            self._assert_action(expected_revision, expected_instance_id)
            if (self._status.state is not ApplicationUpdateState.STAGED
                    or self._package_verifier is None
                    or self._staged_manifest is None or self._staged_envelope is None):
                raise UpdateActionConflict("update_verify_refused")
            manifest, envelope = self._staged_manifest, self._staged_envelope
            self._active = "verify"
            snapshot = self._publish(self._make(
                ApplicationUpdateState.VERIFYING,
                available_version=manifest.release_version,
                artifact_size_bytes=manifest.artifact_size_bytes,
                downloaded_bytes=manifest.artifact_size_bytes,
                last_checked_at=self._status.last_checked_at,
                package_review=PackageReview(state=PackageReviewState.CHECKING)))
            self._worker = Thread(target=self._verify_worker, args=(manifest, envelope, snapshot.revision), daemon=False,
                                  name="application-update-review")
            try:
                self._worker.start()
            except RuntimeError:
                self._active = None
                self._worker = None
                return self._failed(checked_at=self._checked_at(),
                                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                                    retry=False, can_check=False, manifest=manifest)
            return snapshot

    def _verify_worker(self, manifest: UpdateManifest,
                       envelope: SignedUpdateManifestEnvelope,
                       operation_revision: int) -> None:
        checked_at = self._checked_at()
        review_reason: UpdateRejection | str | None = None
        try:
            verification = verify_update_manifest(
                envelope.raw_manifest, signature=envelope.signature, key_id=envelope.key_id,
                verifier=self._verifier, now=checked_at, installed_version=self._installed_version,
                channel=self._channel)
            if verification.state is not UpdateVerificationState.ACCEPTED or verification.manifest != manifest:
                review_reason = verification.rejection or UpdateRejection.INVALID_SCHEMA
                raise ValueError
            with self._lock:
                if (self._active != "verify" or self._revision != operation_revision
                        or not self._persist_new_high_water(manifest=manifest, envelope=envelope)):
                    raise ValueError
                verifier = self._package_verifier
            if verifier is None:
                raise ValueError
            result = MsixPreflightResult.model_validate(
                verifier.verify(manifest=manifest, envelope=envelope).model_dump(mode="python", warnings=False))
            completion = verify_update_manifest(
                envelope.raw_manifest, signature=envelope.signature, key_id=envelope.key_id,
                verifier=self._verifier, now=self._checked_at(), installed_version=self._installed_version,
                channel=self._channel)
            if completion.state is not UpdateVerificationState.ACCEPTED or completion.manifest != manifest:
                review_reason = completion.rejection or UpdateRejection.INVALID_SCHEMA
                result = None
            checked_at = self._checked_at()
        except Exception:
            result = None
        with self._lock:
            if (self._closed or self._revision != operation_revision or self._active != "verify"
                    or self._staged_manifest != manifest or self._staged_envelope != envelope):
                return
            if result is not None and not self._persist_new_high_water(manifest=manifest, envelope=envelope):
                result = None
                review_reason = "signature_unverifiable"
            self._active = None
            if result is not None and result.state is MsixPreflightState.VERIFIED:
                review = PackageReview(state=PackageReviewState.VERIFIED, checked_at=checked_at)
            else:
                reason = review_reason or getattr(result, "reason", None)
                review = PackageReview(state=PackageReviewState.REJECTED,
                                       reason_code=reason.value if hasattr(reason, "value") else reason or "signature_unverifiable",
                                       checked_at=checked_at)
            self._publish(self._make(ApplicationUpdateState.STAGED,
                                     available_version=manifest.release_version,
                                     artifact_size_bytes=manifest.artifact_size_bytes,
                                     downloaded_bytes=manifest.artifact_size_bytes,
                                     last_checked_at=self._status.last_checked_at,
                                     can_check=True,
                                     can_verify=self._package_verifier is not None,
                                     package_review=review))

    def shutdown(self) -> None:
        with self._lock:
            worker = self._worker
            self._cancel.set()
            self._closed = True
            active_metadata_check = self._active == "check"
            active_review = self._active == "verify"
            invalidate_review = self._status.package_review.state in {
                PackageReviewState.CHECKING,
                PackageReviewState.VERIFIED,
            }
            if active_metadata_check or active_review or invalidate_review:
                self._active = "shutdown_uncertain"
                self._failed(
                    checked_at=self._checked_at(),
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False,
                )
        # Metadata retrieval is synchronous and has no owned worker to join.
        # Preserve the explicit lifecycle signal rather than claiming cleanup
        # while an external source can still be executing.
        if active_metadata_check:
            raise RuntimeError("application update check did not terminate")
        if worker is not None:
            worker.join(timeout=5.0)
        if worker is not None and worker.is_alive():
            with self._lock:
                self._active = "shutdown_uncertain"
                self._failed(
                    checked_at=self._checked_at(),
                    reason=ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED,
                    retry=False,
                    can_check=False)
            raise RuntimeError("application update staging did not terminate")


__all__ = ("ApplicationUpdateCoordinator", "ApplicationUpdateSurface",
           "UnconfiguredApplicationUpdateSurface", "UpdateActionConflict")
