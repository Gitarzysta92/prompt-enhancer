"""Default-deny orchestration for direct, consented, owner-hosted transfers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hmac

from ..social.contracts import (
    DeviceState,
    SocialAccountState,
    MAX_CLIENT_CLOCK_SKEW,
    SocialMembershipState,
    VerifiedSocialPrincipal,
)
from ..social.ports import SocialDirectoryPort, SocialGraphPort, SocialTransaction
from .contracts import (
    ByteRange,
    DirectConnectivityState,
    DirectTransferRequest,
    FileGrantState,
    FileManifest,
    FileRecipientGrant,
    FileRevocationReceipt,
    FileShareAuditAction,
    FileShareAuditEvent,
    FileShareQuota,
    FileShareReasonCode,
    OwnerFileAvailability,
    PeerAvailabilityState,
    TransferApproval,
    TransferFailureReason,
    TransferIntegrityEvidence,
    TransferRecord,
    TransferState,
    TERMINAL_TRANSFER_STATES,
)
from .errors import (
    FileShareAuthorizationError,
    FileShareCapabilityError,
    FileShareConflictError,
)
from .ports import (
    DirectSignalingPort,
    FileAvailabilityPort,
    FileGrantPort,
    FileManifestPort,
    FileShareAuditPort,
    FileShareIdentifierPort,
    FileTransferPort,
)


@dataclass(frozen=True, slots=True)
class FileSharingStores:
    transaction: SocialTransaction
    directory: SocialDirectoryPort
    graph: SocialGraphPort
    manifests: FileManifestPort
    grants: FileGrantPort
    availability: FileAvailabilityPort
    transfers: FileTransferPort
    audit: FileShareAuditPort


@dataclass(frozen=True, slots=True)
class DirectFileSharingService:
    stores: FileSharingStores
    identifiers: FileShareIdentifierPort
    signaling: DirectSignalingPort
    quota: FileShareQuota
    clock: Callable[[], datetime]

    def _principal(self, caller: VerifiedSocialPrincipal) -> None:
        account = self.stores.directory.account(
            caller.organization_id, caller.account_id
        )
        membership = self.stores.directory.membership(
            caller.organization_id, caller.account_id
        )
        device = self.stores.directory.device(
            caller.organization_id, caller.device_id
        )
        if (
            account is None
            or account.state is not SocialAccountState.ACTIVE
            or membership is None
            or membership.state is not SocialMembershipState.ACTIVE
        ):
            raise FileShareAuthorizationError(
                FileShareReasonCode.PRINCIPAL_INACTIVE
            )
        if (
            device is None
            or device.state is not DeviceState.ACTIVE
            or device.account_id != caller.account_id
        ):
            raise FileShareAuthorizationError(FileShareReasonCode.DEVICE_INACTIVE)

    def _recipient_available(
        self, caller: VerifiedSocialPrincipal, recipient_account_id: str
    ) -> None:
        # Block state wins before existence, membership, friendship or role and
        # intentionally returns the same observable reason as an unknown ID.
        if self.stores.graph.either_blocked(
            caller.organization_id, caller.account_id, recipient_account_id
        ):
            raise FileShareAuthorizationError(
                FileShareReasonCode.BLOCKED_OR_UNAVAILABLE
            )
        account = self.stores.directory.account(
            caller.organization_id, recipient_account_id
        )
        membership = self.stores.directory.membership(
            caller.organization_id, recipient_account_id
        )
        friendship = self.stores.graph.friendship(
            caller.organization_id, caller.account_id, recipient_account_id
        )
        if (
            account is None
            or account.state is not SocialAccountState.ACTIVE
            or membership is None
            or membership.state is not SocialMembershipState.ACTIVE
            or friendship is None
        ):
            raise FileShareAuthorizationError(
                FileShareReasonCode.BLOCKED_OR_UNAVAILABLE
            )

    def _requester_device_active(self, transfer: TransferRecord) -> bool:
        device = self.stores.directory.device(
            transfer.request.organization_id,
            transfer.request.requester_device_id,
        )
        return (
            device is not None
            and device.state is DeviceState.ACTIVE
            and device.account_id == transfer.request.requester_account_id
        )

    def _manifest_owner_device_active(self, manifest: FileManifest) -> bool:
        device = self.stores.directory.device(
            manifest.organization_id,
            manifest.owner_device_id,
        )
        return (
            device is not None
            and device.state is DeviceState.ACTIVE
            and device.account_id == manifest.owner_account_id
        )

    def _audit(
        self,
        caller: VerifiedSocialPrincipal,
        action: FileShareAuditAction,
        *,
        manifest_id: str | None = None,
        transfer_id: str | None = None,
        now: datetime | None = None,
    ) -> FileShareAuditEvent:
        event = FileShareAuditEvent(
            organization_id=caller.organization_id,
            audit_id=self.identifiers.issue("file-audit"),
            actor_account_id=caller.account_id,
            actor_device_id=caller.device_id,
            manifest_id=manifest_id,
            transfer_id=transfer_id,
            action=action,
            occurred_at=now or self.clock(),
        )
        return self.stores.audit.append(event)

    def register_manifest(
        self, caller: VerifiedSocialPrincipal, manifest: FileManifest
    ) -> FileManifest:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            if (
                manifest.organization_id != caller.organization_id
                or manifest.owner_account_id != caller.account_id
                or manifest.owner_device_id != caller.device_id
            ):
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            existing = self.stores.manifests.manifest(
                caller.organization_id, manifest.manifest_id
            )
            if existing is not None:
                if existing == manifest:
                    return existing
                raise FileShareConflictError(FileShareReasonCode.REQUEST_REPLAYED)
            if manifest.byte_size > self.quota.max_bytes_per_manifest:
                raise FileShareConflictError(FileShareReasonCode.QUOTA_EXCEEDED)
            if abs(now - manifest.created_at) > MAX_CLIENT_CLOCK_SKEW:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            active = self.stores.manifests.active_manifests_for_owner(
                caller.organization_id, caller.account_id, now=now
            )
            if len(active) >= self.quota.max_active_manifests_per_owner:
                raise FileShareConflictError(FileShareReasonCode.QUOTA_EXCEEDED)
            stored = self.stores.manifests.save_manifest(manifest)
            self._audit(
                caller,
                FileShareAuditAction.MANIFEST_REGISTERED,
                manifest_id=manifest.manifest_id,
                now=now,
            )
            return stored

    def offer(
        self,
        caller: VerifiedSocialPrincipal,
        manifest_id: str,
        recipient_account_id: str,
        *,
        expires_at: datetime,
    ) -> FileRecipientGrant:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._recipient_available(caller, recipient_account_id)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, manifest_id
            )
            if (
                manifest is None
                or manifest.owner_account_id != caller.account_id
                or manifest.owner_device_id != caller.device_id
                or manifest.expires_at <= now
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, manifest_id
                )
            ):
                raise FileShareAuthorizationError(
                    FileShareReasonCode.MANIFEST_UNAVAILABLE
                )
            existing_grants = self.stores.grants.grants_for_manifest(
                caller.organization_id, manifest_id
            )
            for existing in existing_grants:
                if (
                    existing.recipient_account_id == recipient_account_id
                    and existing.state
                    in {FileGrantState.OFFERED, FileGrantState.CONSENTED}
                    and existing.expires_at > now
                ):
                    return existing
            active_grants = tuple(
                existing
                for existing in existing_grants
                if existing.state in {FileGrantState.OFFERED, FileGrantState.CONSENTED}
                and existing.expires_at > now
            )
            if len(active_grants) >= self.quota.max_recipients_per_manifest:
                raise FileShareConflictError(FileShareReasonCode.QUOTA_EXCEEDED)
            effective_expiry = min(expires_at, manifest.expires_at)
            if effective_expiry <= now:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            grant = FileRecipientGrant(
                organization_id=caller.organization_id,
                grant_id=self.identifiers.issue("file-grant"),
                manifest_id=manifest_id,
                owner_account_id=caller.account_id,
                recipient_account_id=recipient_account_id,
                state=FileGrantState.OFFERED,
                offered_at=now,
                expires_at=effective_expiry,
            )
            stored = self.stores.grants.save_grant(grant)
            self._audit(
                caller,
                FileShareAuditAction.GRANT_OFFERED,
                manifest_id=manifest_id,
                now=now,
            )
            return stored

    def decide_grant(
        self,
        caller: VerifiedSocialPrincipal,
        grant_id: str,
        *,
        consent: bool,
    ) -> FileRecipientGrant:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            grant = self.stores.grants.grant(caller.organization_id, grant_id)
            if grant is None or grant.recipient_account_id != caller.account_id:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.GRANT_UNAVAILABLE
                )
            # Anti-enumeration block check precedes manifest lookup/state detail.
            self._recipient_available(caller, grant.owner_account_id)
            desired = FileGrantState.CONSENTED if consent else FileGrantState.DECLINED
            if grant.state is desired:
                return grant
            if grant.state is not FileGrantState.OFFERED or grant.expires_at <= now:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            decided = FileRecipientGrant.model_validate(
                {
                    **grant.model_dump(mode="python"),
                    "state": desired,
                    "decided_at": now,
                    "explicit_recipient_consent": consent,
                }
            )
            stored = self.stores.grants.save_grant(decided)
            self._audit(
                caller,
                FileShareAuditAction.GRANT_CONSENTED
                if consent
                else FileShareAuditAction.GRANT_DECLINED,
                manifest_id=grant.manifest_id,
                now=now,
            )
            return stored

    def revoke_grant(
        self, caller: VerifiedSocialPrincipal, grant_id: str
    ) -> FileRecipientGrant:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            grant = self.stores.grants.grant(caller.organization_id, grant_id)
            if grant is None or grant.owner_account_id != caller.account_id:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.GRANT_UNAVAILABLE
                )
            if grant.state is FileGrantState.REVOKED:
                return grant
            if grant.state in {FileGrantState.DECLINED, FileGrantState.EXPIRED}:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            revoked = FileRecipientGrant.model_validate(
                {
                    **grant.model_dump(mode="python"),
                    "state": FileGrantState.REVOKED,
                    "revoked_at": now,
                    # Consent history remains evident in decided_at, while the
                    # active consent capability is removed.
                    "explicit_recipient_consent": False,
                }
            )
            stored = self.stores.grants.save_grant(revoked)
            self.stores.transfers.revoke_grant_transfers(
                caller.organization_id, grant_id, now=now
            )
            self._audit(
                caller,
                FileShareAuditAction.GRANT_REVOKED,
                manifest_id=grant.manifest_id,
                now=now,
            )
            return stored

    def publish_availability(
        self,
        caller: VerifiedSocialPrincipal,
        availability: OwnerFileAvailability,
    ) -> OwnerFileAvailability:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, availability.manifest_id
            )
            if (
                availability.organization_id != caller.organization_id
                or availability.owner_account_id != caller.account_id
                or availability.owner_device_id != caller.device_id
                or manifest is None
                or manifest.owner_account_id != caller.account_id
                or manifest.owner_device_id != caller.device_id
                or manifest.expires_at <= now
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, availability.manifest_id
                )
                or abs(now - availability.observed_at) > MAX_CLIENT_CLOCK_SKEW
                or availability.expires_at <= now
            ):
                raise FileShareAuthorizationError(
                    FileShareReasonCode.MANIFEST_UNAVAILABLE
                )
            return self.stores.availability.save_availability(availability)

    def request_transfer(
        self,
        caller: VerifiedSocialPrincipal,
        grant_id: str,
        *,
        ranges: tuple[ByteRange, ...],
        expires_at: datetime,
    ) -> TransferRecord:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            grant = self.stores.grants.grant(caller.organization_id, grant_id)
            if grant is None or grant.recipient_account_id != caller.account_id:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.GRANT_UNAVAILABLE
                )
            self._recipient_available(caller, grant.owner_account_id)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, grant.manifest_id
            )
            if (
                grant.state is not FileGrantState.CONSENTED
                or not grant.explicit_recipient_consent
                or grant.expires_at <= now
            ):
                raise FileShareAuthorizationError(FileShareReasonCode.CONSENT_REQUIRED)
            if (
                manifest is None
                or manifest.expires_at <= now
                or not self._manifest_owner_device_active(manifest)
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, grant.manifest_id
                )
            ):
                raise FileShareAuthorizationError(
                    FileShareReasonCode.MANIFEST_UNAVAILABLE
                )
            if not ranges:
                raise FileShareConflictError(FileShareReasonCode.INVALID_RANGE)
            for selected in ranges:
                if selected.end_exclusive > manifest.byte_size:
                    raise FileShareConflictError(FileShareReasonCode.INVALID_RANGE)
            active = self.stores.transfers.active_transfers_for_owner(
                caller.organization_id, manifest.owner_account_id
            )
            if len(active) >= self.quota.max_concurrent_transfers_per_owner:
                raise FileShareConflictError(FileShareReasonCode.QUOTA_EXCEEDED)
            effective_expiry = min(
                expires_at, grant.expires_at, manifest.expires_at
            )
            if effective_expiry <= now:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            request = DirectTransferRequest(
                organization_id=caller.organization_id,
                transfer_id=self.identifiers.issue("file-transfer"),
                manifest_id=manifest.manifest_id,
                grant_id=grant.grant_id,
                requester_account_id=caller.account_id,
                requester_device_id=caller.device_id,
                ranges=ranges,
                created_at=now,
                expires_at=effective_expiry,
            )
            availability = self.stores.availability.availability(
                caller.organization_id, manifest.manifest_id, now=now
            )
            if availability is None or availability.state is PeerAvailabilityState.OFFLINE:
                record = TransferRecord(
                    request=request,
                    state=TransferState.FAILED,
                    failure_reason=TransferFailureReason.OWNER_OFFLINE,
                    changed_at=now,
                    received_bytes=0,
                )
            else:
                record = TransferRecord(
                    request=request,
                    state=TransferState.WAITING_OWNER_APPROVAL,
                    changed_at=now,
                    received_bytes=0,
                )
            stored = self.stores.transfers.save_transfer(record)
            self._audit(
                caller,
                FileShareAuditAction.TRANSFER_REQUESTED,
                manifest_id=manifest.manifest_id,
                transfer_id=request.transfer_id,
                now=now,
            )
            return stored

    def approve_and_negotiate(
        self,
        caller: VerifiedSocialPrincipal,
        transfer_id: str,
    ) -> TransferRecord:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            transfer = self.stores.transfers.transfer(
                caller.organization_id, transfer_id
            )
            if transfer is None:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.GRANT_UNAVAILABLE
                )
            manifest = self.stores.manifests.manifest(
                caller.organization_id, transfer.request.manifest_id
            )
            grant = self.stores.grants.grant(
                caller.organization_id, transfer.request.grant_id
            )
            if (
                manifest is None
                or manifest.owner_account_id != caller.account_id
                or manifest.owner_device_id != caller.device_id
                or grant is None
            ):
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            self._recipient_available(caller, grant.recipient_account_id)
            if (
                transfer.state is not TransferState.WAITING_OWNER_APPROVAL
                or transfer.request.expires_at <= now
                or grant.state is not FileGrantState.CONSENTED
                or not self._requester_device_active(transfer)
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, manifest.manifest_id
                )
            ):
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            approval = TransferApproval(
                organization_id=caller.organization_id,
                transfer_id=transfer_id,
                manifest_id=manifest.manifest_id,
                owner_account_id=caller.account_id,
                owner_device_id=caller.device_id,
                approved_at=now,
            )
            self.stores.transfers.save_approval(approval)
            negotiating = TransferRecord.model_validate(
                {
                    **transfer.model_dump(mode="python"),
                    "state": TransferState.NEGOTIATING_DIRECT,
                    "owner_approved_at": now,
                    "changed_at": now,
                }
            )
            self.stores.transfers.save_transfer(negotiating)
            self._audit(
                caller,
                FileShareAuditAction.TRANSFER_APPROVED,
                manifest_id=manifest.manifest_id,
                transfer_id=transfer_id,
                now=now,
            )

        # Candidate exchange is an external operation and must never run while
        # the metadata transaction/lock is held. Revocation may race it; the
        # second transaction below revalidates every capability.
        assessment = None
        if (
            self.signaling.available
            and self.signaling.authenticated
            and not self.signaling.relay_supported
        ):
            try:
                assessment = self.signaling.negotiate_direct(
                    caller, transfer.request, now=now
                )
            except Exception:
                # Adapter details may contain network addresses. Collapse them
                # into a content-free capability result.
                assessment = None

        finished_at = self.clock()
        with self.stores.transaction:
            current = self.stores.transfers.transfer(
                caller.organization_id, transfer_id
            )
            if current is None:
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            if current.state in TERMINAL_TRANSFER_STATES:
                return current
            if current.state is not TransferState.NEGOTIATING_DIRECT:
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            current_manifest = self.stores.manifests.manifest(
                caller.organization_id, current.request.manifest_id
            )
            current_grant = self.stores.grants.grant(
                caller.organization_id, current.request.grant_id
            )
            revoked_during_negotiation = False
            try:
                self._principal(caller)
                if current_grant is not None:
                    self._recipient_available(
                        caller, current_grant.recipient_account_id
                    )
            except FileShareAuthorizationError:
                revoked_during_negotiation = True
            if (
                revoked_during_negotiation
                or current_manifest is None
                or current_grant is None
                or current_grant.state is not FileGrantState.CONSENTED
                or not self._requester_device_active(current)
                or current.request.expires_at <= finished_at
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, current.request.manifest_id
                )
            ):
                failure_reason = TransferFailureReason.REVOKED_BEFORE_COMPLETION
            elif (
                assessment is None
                or assessment.transfer_id != transfer_id
                or not assessment.authenticated_signaling
            ):
                failure_reason = TransferFailureReason.SIGNALING_UNAVAILABLE
            elif assessment.state is DirectConnectivityState.UNAVAILABLE:
                failure_reason = assessment.reason or TransferFailureReason.UNREACHABLE_NO_RELAY
            else:
                failure_reason = None

            if failure_reason is not None:
                failed = TransferRecord.model_validate(
                    {
                        **current.model_dump(mode="python"),
                        "state": TransferState.FAILED,
                        "failure_reason": failure_reason,
                        "changed_at": finished_at,
                    }
                )
                stored = self.stores.transfers.save_transfer(failed)
                self._audit(
                    caller,
                    FileShareAuditAction.DIRECT_NEGOTIATION_FAILED,
                    manifest_id=current.request.manifest_id,
                    transfer_id=transfer_id,
                    now=finished_at,
                )
                return stored
            ready = TransferRecord.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "state": TransferState.DIRECT_READY,
                    "changed_at": finished_at,
                }
            )
            return self.stores.transfers.save_transfer(ready)

    def complete_transfer(
        self,
        caller: VerifiedSocialPrincipal,
        evidence: TransferIntegrityEvidence,
    ) -> TransferRecord:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            transfer = self.stores.transfers.transfer(
                caller.organization_id, evidence.transfer_id
            )
            if (
                transfer is None
                or transfer.request.requester_account_id != caller.account_id
                or transfer.request.requester_device_id != caller.device_id
                or transfer.request.manifest_id != evidence.manifest_id
            ):
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            grant = self.stores.grants.grant(
                caller.organization_id, transfer.request.grant_id
            )
            if grant is None:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.GRANT_UNAVAILABLE
                )
            self._recipient_available(caller, grant.owner_account_id)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, evidence.manifest_id
            )
            if (
                manifest is None
                or transfer.state
                not in {
                    TransferState.DIRECT_READY,
                    TransferState.TRANSFERRING,
                    TransferState.VERIFYING,
                }
                or grant.state is not FileGrantState.CONSENTED
                or self.stores.manifests.is_manifest_revoked(
                    caller.organization_id, evidence.manifest_id
                )
            ):
                raise FileShareConflictError(FileShareReasonCode.STATE_CONFLICT)
            if (
                transfer.request.expires_at <= now
                or grant.expires_at <= now
                or manifest.expires_at <= now
            ):
                expired = TransferRecord.model_validate(
                    {
                        **transfer.model_dump(mode="python"),
                        "state": TransferState.FAILED,
                        "failure_reason": TransferFailureReason.EXPIRED,
                        "changed_at": now,
                        "received_bytes": evidence.received_bytes,
                    }
                )
                return self.stores.transfers.save_transfer(expired)
            if not self._manifest_owner_device_active(manifest):
                failed = TransferRecord.model_validate(
                    {
                        **transfer.model_dump(mode="python"),
                        "state": TransferState.FAILED,
                        "failure_reason": (
                            TransferFailureReason.REVOKED_BEFORE_COMPLETION
                        ),
                        "changed_at": now,
                        "received_bytes": evidence.received_bytes,
                    }
                )
                return self.stores.transfers.save_transfer(failed)
            exact_chunks = tuple(chunk.sha256 for chunk in manifest.chunks)
            integrity_ok = (
                evidence.received_bytes == manifest.byte_size
                and hmac.compare_digest(
                    evidence.whole_file_sha256, manifest.whole_file_sha256
                )
                and len(evidence.chunk_sha256) == len(exact_chunks)
                and all(
                    hmac.compare_digest(received, expected)
                    for received, expected in zip(
                        evidence.chunk_sha256, exact_chunks, strict=True
                    )
                )
            )
            if not integrity_ok:
                failed = TransferRecord.model_validate(
                    {
                        **transfer.model_dump(mode="python"),
                        "state": TransferState.FAILED,
                        "failure_reason": TransferFailureReason.INTEGRITY_FAILED,
                        "changed_at": now,
                        "received_bytes": evidence.received_bytes,
                    }
                )
                return self.stores.transfers.save_transfer(failed)
            completed = TransferRecord.model_validate(
                {
                    **transfer.model_dump(mode="python"),
                    "state": TransferState.COMPLETED,
                    "failure_reason": None,
                    "changed_at": now,
                    "received_bytes": evidence.received_bytes,
                    "completed_whole_file_sha256": evidence.whole_file_sha256,
                }
            )
            stored = self.stores.transfers.save_transfer(completed)
            self._audit(
                caller,
                FileShareAuditAction.TRANSFER_COMPLETED,
                manifest_id=manifest.manifest_id,
                transfer_id=transfer.request.transfer_id,
                now=now,
            )
            return stored

    def cancel_transfer(
        self, caller: VerifiedSocialPrincipal, transfer_id: str
    ) -> TransferRecord:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            transfer = self.stores.transfers.transfer(
                caller.organization_id, transfer_id
            )
            if transfer is None:
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, transfer.request.manifest_id
            )
            if manifest is None or caller.account_id not in {
                manifest.owner_account_id,
                transfer.request.requester_account_id,
            }:
                raise FileShareAuthorizationError(FileShareReasonCode.DEFAULT_DENY)
            other = (
                transfer.request.requester_account_id
                if caller.account_id == manifest.owner_account_id
                else manifest.owner_account_id
            )
            if self.stores.graph.either_blocked(
                caller.organization_id, caller.account_id, other
            ):
                raise FileShareAuthorizationError(
                    FileShareReasonCode.BLOCKED_OR_UNAVAILABLE
                )
            if transfer.state in TERMINAL_TRANSFER_STATES:
                return transfer
            cancelled = TransferRecord.model_validate(
                {
                    **transfer.model_dump(mode="python"),
                    "state": TransferState.CANCELLED,
                    "changed_at": now,
                }
            )
            stored = self.stores.transfers.save_transfer(cancelled)
            self._audit(
                caller,
                FileShareAuditAction.TRANSFER_CANCELLED,
                manifest_id=manifest.manifest_id,
                transfer_id=transfer_id,
                now=now,
            )
            return stored

    def revoke_manifest(
        self, caller: VerifiedSocialPrincipal, manifest_id: str
    ) -> FileRevocationReceipt:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            manifest = self.stores.manifests.manifest(
                caller.organization_id, manifest_id
            )
            if manifest is None or manifest.owner_account_id != caller.account_id:
                raise FileShareAuthorizationError(
                    FileShareReasonCode.MANIFEST_UNAVAILABLE
                )
            self.stores.manifests.revoke_manifest(
                caller.organization_id, manifest_id, now=now
            )
            revoked_grants = self.stores.grants.revoke_manifest_grants(
                caller.organization_id, manifest_id, now=now
            )
            cancelled = self.stores.transfers.revoke_manifest_transfers(
                caller.organization_id, manifest_id, now=now
            )
            receipt = FileRevocationReceipt(
                organization_id=caller.organization_id,
                manifest_id=manifest_id,
                receipt_id=self.identifiers.issue("file-revocation"),
                revoked_grants=revoked_grants,
                cancelled_active_transfers=cancelled,
                completed_at=now,
            )
            self._audit(
                caller,
                FileShareAuditAction.MANIFEST_REVOKED,
                manifest_id=manifest_id,
                now=now,
            )
            return receipt


__all__ = ["DirectFileSharingService", "FileSharingStores"]
