"""Metadata stores and ephemeral direct-transfer boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..social.contracts import VerifiedSocialPrincipal
from .contracts import (
    ByteRange,
    DirectConnectivityAssessment,
    DirectTransferRequest,
    FileManifest,
    FileRecipientGrant,
    FileShareAuditEvent,
    LocalFileDescriptor,
    OwnerFileAvailability,
    TransferApproval,
    TransferRecord,
)


class FileManifestPort(Protocol):
    def manifest(self, organization_id: str, manifest_id: str) -> FileManifest | None: ...

    def save_manifest(self, manifest: FileManifest) -> FileManifest: ...

    def active_manifests_for_owner(
        self, organization_id: str, owner_account_id: str, *, now: datetime
    ) -> tuple[FileManifest, ...]: ...

    def revoke_manifest(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> bool: ...

    def is_manifest_revoked(self, organization_id: str, manifest_id: str) -> bool: ...


class FileGrantPort(Protocol):
    def grant(self, organization_id: str, grant_id: str) -> FileRecipientGrant | None: ...

    def grants_for_manifest(
        self, organization_id: str, manifest_id: str
    ) -> tuple[FileRecipientGrant, ...]: ...

    def save_grant(self, grant: FileRecipientGrant) -> FileRecipientGrant: ...

    def revoke_manifest_grants(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int: ...


class FileAvailabilityPort(Protocol):
    def save_availability(
        self, availability: OwnerFileAvailability
    ) -> OwnerFileAvailability: ...

    def availability(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> OwnerFileAvailability | None: ...


class FileTransferPort(Protocol):
    def transfer(self, organization_id: str, transfer_id: str) -> TransferRecord | None: ...

    def save_transfer(self, transfer: TransferRecord) -> TransferRecord: ...

    def active_transfers_for_owner(
        self, organization_id: str, owner_account_id: str
    ) -> tuple[TransferRecord, ...]: ...

    def approval(
        self, organization_id: str, transfer_id: str
    ) -> TransferApproval | None: ...

    def save_approval(self, approval: TransferApproval) -> TransferApproval: ...

    def revoke_manifest_transfers(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int: ...

    def revoke_grant_transfers(
        self, organization_id: str, grant_id: str, *, now: datetime
    ) -> int: ...


class FileShareAuditPort(Protocol):
    def append(self, event: FileShareAuditEvent) -> FileShareAuditEvent: ...


class FileShareIdentifierPort(Protocol):
    def issue(self, namespace: str) -> str: ...


class DirectSignalingPort(Protocol):
    """Ephemeral ICE/signaling boundary; candidate values are never returned."""

    @property
    def available(self) -> bool: ...

    @property
    def authenticated(self) -> bool: ...

    @property
    def relay_supported(self) -> bool: ...

    def negotiate_direct(
        self,
        owner: VerifiedSocialPrincipal,
        request: DirectTransferRequest,
        *,
        now: datetime,
    ) -> DirectConnectivityAssessment: ...


class QuarantinedLocalFilePort(Protocol):
    """Owner-local bytes; implementations must reject links/reparse traversal."""

    def stat_matches_manifest(
        self, descriptor: LocalFileDescriptor, manifest: FileManifest
    ) -> bool: ...

    def read_range(
        self, descriptor: LocalFileDescriptor, selected: ByteRange
    ) -> bytes: ...


class DirectByteTransportPort(Protocol):
    """Send an approved range directly to one authenticated peer."""

    @property
    def reviewed_encryption(self) -> bool: ...

    def send_range(
        self,
        request: DirectTransferRequest,
        selected: ByteRange,
        payload: bytes,
    ) -> int: ...


__all__ = [
    "DirectByteTransportPort",
    "DirectSignalingPort",
    "FileAvailabilityPort",
    "FileGrantPort",
    "FileManifestPort",
    "FileShareAuditPort",
    "FileShareIdentifierPort",
    "FileTransferPort",
    "QuarantinedLocalFilePort",
]
