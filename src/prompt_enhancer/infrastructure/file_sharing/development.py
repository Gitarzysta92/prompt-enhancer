"""Volatile metadata adapters for the direct file-sharing development slice."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import secrets
import threading

from ...application.file_sharing.contracts import (
    DirectConnectivityAssessment,
    DirectConnectivityState,
    DirectTransferRequest,
    FileGrantState,
    FileManifest,
    FileRecipientGrant,
    FileShareAuditEvent,
    FileShareQuota,
    OwnerFileAvailability,
    TransferApproval,
    TransferFailureReason,
    TransferRecord,
    TransferState,
    TERMINAL_TRANSFER_STATES,
)
from ...application.file_sharing.service import (
    DirectFileSharingService,
    FileSharingStores,
)
from ...application.social.contracts import VerifiedSocialPrincipal
from ..social.development import (
    DevelopmentSocialFoundation,
    DevelopmentSocialTransaction,
)


@dataclass(frozen=True, slots=True)
class RandomFileShareIdentifierFactory:
    def issue(self, namespace: str) -> str:
        if not namespace or len(namespace) > 64 or not namespace.replace("-", "").isalnum():
            raise ValueError("file-sharing identifier namespace is invalid")
        return f"shr_{secrets.token_hex(32)}"


_ALLOWED_TRANSFER_TRANSITIONS = frozenset(
    {
        (TransferState.WAITING_OWNER_APPROVAL, TransferState.NEGOTIATING_DIRECT),
        (TransferState.NEGOTIATING_DIRECT, TransferState.DIRECT_READY),
        (TransferState.NEGOTIATING_DIRECT, TransferState.FAILED),
        (TransferState.DIRECT_READY, TransferState.TRANSFERRING),
        (TransferState.DIRECT_READY, TransferState.VERIFYING),
        (TransferState.DIRECT_READY, TransferState.COMPLETED),
        (TransferState.TRANSFERRING, TransferState.VERIFYING),
        (TransferState.TRANSFERRING, TransferState.COMPLETED),
        (TransferState.VERIFYING, TransferState.COMPLETED),
        (TransferState.DIRECT_READY, TransferState.FAILED),
        (TransferState.TRANSFERRING, TransferState.FAILED),
        (TransferState.VERIFYING, TransferState.FAILED),
    }
)

_ALLOWED_GRANT_TRANSITIONS = frozenset(
    {
        (FileGrantState.OFFERED, FileGrantState.CONSENTED),
        (FileGrantState.OFFERED, FileGrantState.DECLINED),
        (FileGrantState.OFFERED, FileGrantState.REVOKED),
        (FileGrantState.OFFERED, FileGrantState.EXPIRED),
        (FileGrantState.CONSENTED, FileGrantState.REVOKED),
        (FileGrantState.CONSENTED, FileGrantState.EXPIRED),
    }
)


@dataclass(slots=True)
class DevelopmentFileSharingState:
    lock: threading.RLock
    manifests: dict[tuple[str, str], FileManifest] = field(default_factory=dict)
    revoked_manifests: dict[tuple[str, str], datetime] = field(default_factory=dict)
    grants: dict[tuple[str, str], FileRecipientGrant] = field(default_factory=dict)
    availabilities: dict[tuple[str, str], OwnerFileAvailability] = field(
        default_factory=dict
    )
    transfers: dict[tuple[str, str], TransferRecord] = field(default_factory=dict)
    approvals: dict[tuple[str, str], TransferApproval] = field(default_factory=dict)
    audits: list[FileShareAuditEvent] = field(default_factory=list)

    # Manifest port ------------------------------------------------------
    def manifest(self, organization_id: str, manifest_id: str) -> FileManifest | None:
        with self.lock:
            return self.manifests.get((organization_id, manifest_id))

    def save_manifest(self, manifest: FileManifest) -> FileManifest:
        with self.lock:
            key = (manifest.organization_id, manifest.manifest_id)
            existing = self.manifests.get(key)
            if existing is not None and existing != manifest:
                raise ValueError("immutable file manifest conflict")
            self.manifests[key] = manifest
            return manifest

    def active_manifests_for_owner(
        self, organization_id: str, owner_account_id: str, *, now: datetime
    ) -> tuple[FileManifest, ...]:
        with self.lock:
            return tuple(
                manifest
                for (tenant, identifier), manifest in sorted(self.manifests.items())
                if tenant == organization_id
                and manifest.owner_account_id == owner_account_id
                and manifest.expires_at > now
                and (tenant, identifier) not in self.revoked_manifests
            )

    def revoke_manifest(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> bool:
        with self.lock:
            key = (organization_id, manifest_id)
            if key not in self.manifests:
                return False
            if key in self.revoked_manifests:
                return False
            self.revoked_manifests[key] = now
            self.availabilities.pop(key, None)
            return True

    def is_manifest_revoked(self, organization_id: str, manifest_id: str) -> bool:
        with self.lock:
            return (organization_id, manifest_id) in self.revoked_manifests

    # Grant port ---------------------------------------------------------
    def grant(self, organization_id: str, grant_id: str) -> FileRecipientGrant | None:
        with self.lock:
            return self.grants.get((organization_id, grant_id))

    def grants_for_manifest(
        self, organization_id: str, manifest_id: str
    ) -> tuple[FileRecipientGrant, ...]:
        with self.lock:
            return tuple(
                grant
                for (tenant, _), grant in sorted(self.grants.items())
                if tenant == organization_id and grant.manifest_id == manifest_id
            )

    def save_grant(self, grant: FileRecipientGrant) -> FileRecipientGrant:
        with self.lock:
            key = (grant.organization_id, grant.grant_id)
            existing = self.grants.get(key)
            if existing is not None and existing != grant:
                if (
                    existing.manifest_id != grant.manifest_id
                    or existing.owner_account_id != grant.owner_account_id
                    or existing.recipient_account_id != grant.recipient_account_id
                    or (existing.state, grant.state) not in _ALLOWED_GRANT_TRANSITIONS
                ):
                    raise ValueError("invalid file grant transition")
            self.grants[key] = grant
            return grant

    def revoke_manifest_grants(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int:
        with self.lock:
            changed = 0
            for key, grant in tuple(self.grants.items()):
                if (
                    key[0] != organization_id
                    or grant.manifest_id != manifest_id
                    or grant.state
                    in {
                        FileGrantState.REVOKED,
                        FileGrantState.DECLINED,
                        FileGrantState.EXPIRED,
                    }
                ):
                    continue
                self.grants[key] = FileRecipientGrant.model_validate(
                    {
                        **grant.model_dump(mode="python"),
                        "state": FileGrantState.REVOKED,
                        "revoked_at": now,
                        "explicit_recipient_consent": False,
                    }
                )
                changed += 1
            return changed

    # Availability port --------------------------------------------------
    def save_availability(
        self, availability: OwnerFileAvailability
    ) -> OwnerFileAvailability:
        with self.lock:
            self.availabilities[
                (availability.organization_id, availability.manifest_id)
            ] = availability
            return availability

    def availability(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> OwnerFileAvailability | None:
        with self.lock:
            key = (organization_id, manifest_id)
            availability = self.availabilities.get(key)
            if availability is None:
                return None
            if availability.expires_at <= now or key in self.revoked_manifests:
                self.availabilities.pop(key, None)
                return None
            return availability

    # Transfer port ------------------------------------------------------
    def transfer(self, organization_id: str, transfer_id: str) -> TransferRecord | None:
        with self.lock:
            return self.transfers.get((organization_id, transfer_id))

    def save_transfer(self, transfer: TransferRecord) -> TransferRecord:
        with self.lock:
            key = (transfer.request.organization_id, transfer.request.transfer_id)
            existing = self.transfers.get(key)
            if existing is not None and existing != transfer:
                if existing.request != transfer.request:
                    raise ValueError("immutable file transfer request conflict")
                if existing.state in TERMINAL_TRANSFER_STATES:
                    raise ValueError("terminal file transfer cannot transition")
                transition = (existing.state, transfer.state)
                if (
                    transition not in _ALLOWED_TRANSFER_TRANSITIONS
                    and transfer.state
                    not in {TransferState.CANCELLED, TransferState.REVOKED}
                ):
                    raise ValueError("invalid file transfer state transition")
            self.transfers[key] = transfer
            return transfer

    def active_transfers_for_owner(
        self, organization_id: str, owner_account_id: str
    ) -> tuple[TransferRecord, ...]:
        with self.lock:
            active: list[TransferRecord] = []
            for (tenant, _), transfer in self.transfers.items():
                if tenant != organization_id or transfer.state in TERMINAL_TRANSFER_STATES:
                    continue
                manifest = self.manifests.get(
                    (organization_id, transfer.request.manifest_id)
                )
                if manifest is not None and manifest.owner_account_id == owner_account_id:
                    active.append(transfer)
            return tuple(sorted(active, key=lambda item: item.request.transfer_id))

    def approval(
        self, organization_id: str, transfer_id: str
    ) -> TransferApproval | None:
        with self.lock:
            return self.approvals.get((organization_id, transfer_id))

    def save_approval(self, approval: TransferApproval) -> TransferApproval:
        with self.lock:
            key = (approval.organization_id, approval.transfer_id)
            if key not in self.transfers:
                raise ValueError("file transfer approval is not bound")
            existing = self.approvals.get(key)
            if existing is not None and existing != approval:
                raise ValueError("file transfer approval conflict")
            self.approvals[key] = approval
            return approval

    def revoke_manifest_transfers(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int:
        with self.lock:
            changed = 0
            for key, transfer in tuple(self.transfers.items()):
                if (
                    key[0] != organization_id
                    or transfer.request.manifest_id != manifest_id
                    or transfer.state in TERMINAL_TRANSFER_STATES
                ):
                    continue
                self.transfers[key] = TransferRecord.model_validate(
                    {
                        **transfer.model_dump(mode="python"),
                        "state": TransferState.REVOKED,
                        "changed_at": now,
                    }
                )
                changed += 1
            return changed

    def revoke_grant_transfers(
        self, organization_id: str, grant_id: str, *, now: datetime
    ) -> int:
        with self.lock:
            changed = 0
            for key, transfer in tuple(self.transfers.items()):
                if (
                    key[0] != organization_id
                    or transfer.request.grant_id != grant_id
                    or transfer.state in TERMINAL_TRANSFER_STATES
                ):
                    continue
                self.transfers[key] = TransferRecord.model_validate(
                    {
                        **transfer.model_dump(mode="python"),
                        "state": TransferState.REVOKED,
                        "changed_at": now,
                    }
                )
                changed += 1
            return changed

    # Audit port ---------------------------------------------------------
    def append(self, event: FileShareAuditEvent) -> FileShareAuditEvent:
        with self.lock:
            self.audits.append(event)
            return event


@dataclass(frozen=True, slots=True)
class FailClosedDirectSignaling:
    """No server, ICE candidate exchange, STUN or TURN is composed."""

    available: bool = False
    authenticated: bool = False
    relay_supported: bool = False

    def negotiate_direct(
        self,
        owner: VerifiedSocialPrincipal,
        request: DirectTransferRequest,
        *,
        now: datetime,
    ) -> DirectConnectivityAssessment:
        return DirectConnectivityAssessment(
            transfer_id=request.transfer_id,
            state=DirectConnectivityState.UNAVAILABLE,
            reason=TransferFailureReason.SIGNALING_UNAVAILABLE,
            authenticated_signaling=False,
            assessed_at=now,
        )


@dataclass(frozen=True, slots=True)
class DevelopmentFileSharingFoundation:
    state: DevelopmentFileSharingState
    service: DirectFileSharingService


def create_development_file_sharing_foundation(
    social: DevelopmentSocialFoundation,
    clock: Callable[[], datetime],
    *,
    quota: FileShareQuota | None = None,
) -> DevelopmentFileSharingFoundation:
    state = DevelopmentFileSharingState(lock=social.state.lock)
    service = DirectFileSharingService(
        stores=FileSharingStores(
            transaction=DevelopmentSocialTransaction(social.state.lock),
            directory=social.state,
            graph=social.state,
            manifests=state,
            grants=state,
            availability=state,
            transfers=state,
            audit=state,
        ),
        identifiers=RandomFileShareIdentifierFactory(),
        signaling=FailClosedDirectSignaling(),
        quota=quota or FileShareQuota(),
        clock=clock,
    )
    return DevelopmentFileSharingFoundation(state=state, service=service)


__all__ = [
    "DevelopmentFileSharingFoundation",
    "DevelopmentFileSharingState",
    "FailClosedDirectSignaling",
    "RandomFileShareIdentifierFactory",
    "create_development_file_sharing_foundation",
]
