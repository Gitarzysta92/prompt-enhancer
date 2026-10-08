"""Storage and boundary ports for the control plane.

The ports are split by aggregate rather than exposed as one wide store, so a
production PostgreSQL adapter can implement them table by table behind row
level security while the development adapter stays in memory. No port accepts
SQL, a filesystem path, or free text, and every method is tenant-scoped: the
organization identifier is a required argument, never an implicit ambient
value. That is what lets an adapter enforce isolation and what makes a
cross-tenant read a type-level mistake rather than a forgotten filter.

Adapters are responsible for atomicity. :class:`TransactionBoundary` marks the
region a use case needs to be indivisible; the in-memory adapter satisfies it
with one re-entrant lock, and a database adapter satisfies it with a
transaction.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol

from .contracts import (
    ApiClient,
    AuditEvent,
    Device,
    DeviceRegistration,
    DeviceVerificationKey,
    Entitlement,
    ManagerAccessGrant,
    Membership,
    Organization,
    SignatureAlgorithm,
    Team,
)
from .envelopes import SignatureVerifier
from .aggregation import TeamAggregate
from .periods import ReportingBucket
from .sync import (
    ConsumedEnvelope,
    DeletionReason,
    EnvelopeReservation,
    SnapshotRecord,
    SyncCheckpoint,
    SyncItem,
    Tombstone,
)


class TransactionBoundary(Protocol):
    """A re-entrant, indivisible region across every store in one adapter set."""

    def __enter__(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class DirectoryStore(Protocol):
    """Organizations, teams, memberships, and roles."""

    def organization(self, organization_id: str) -> Organization | None: ...

    def team(self, organization_id: str, team_id: str) -> Team | None: ...

    def membership(
        self, organization_id: str, user_id: str
    ) -> Membership | None: ...

    def team_memberships(
        self, organization_id: str, team_id: str
    ) -> tuple[Membership, ...]: ...

    def revoke_membership(
        self, organization_id: str, user_id: str, *, now: datetime
    ) -> Membership: ...


class DeviceStore(Protocol):
    """Device identities and their verification material."""

    def register(self, registration: DeviceRegistration) -> Device: ...

    def device(self, organization_id: str, device_id: str) -> Device | None: ...

    def verification_key(
        self, organization_id: str, device_id: str
    ) -> DeviceVerificationKey | None: ...

    def revoke(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> Device: ...

    def devices_for_user(
        self, organization_id: str, user_id: str
    ) -> tuple[Device, ...]: ...


class SnapshotStore(Protocol):
    """The internal tenant-source log and deletion/replay fences.

    ``append_snapshot`` must record the consumed-envelope fence entry in the
    same indivisible step as the row, and ``delete_subject`` must keep the fence
    while removing the rows. That pairing is what stops a deleted envelope from
    being republished by a device that still holds the signed bytes.
    """

    def append_snapshot(self, record: SnapshotRecord) -> SnapshotRecord: ...

    def reserve_envelope(self, reservation: EnvelopeReservation) -> None: ...

    def envelope_reservation(
        self, organization_id: str, envelope_id: str
    ) -> EnvelopeReservation | None: ...

    def active_envelope_reservation(
        self,
        organization_id: str,
        subject_user_id: str,
        client_id: str,
        device_id: str,
        *,
        now: datetime,
    ) -> EnvelopeReservation | None: ...

    def invalidate_subject_reservations(
        self, organization_id: str, subject_user_id: str
    ) -> int: ...

    def next_sequence(self, organization_id: str) -> int: ...

    def consumed_envelope(
        self, organization_id: str, envelope_id: str
    ) -> ConsumedEnvelope | None: ...

    def subject_deletion_epoch(
        self, organization_id: str, subject_user_id: str
    ) -> datetime | None: ...

    def subject_deletion_generation(
        self, organization_id: str, subject_user_id: str
    ) -> int: ...

    def snapshot_by_envelope(
        self, organization_id: str, envelope_id: str
    ) -> SnapshotRecord | None: ...

    def read_since(
        self, organization_id: str, *, sequence: int, limit: int
    ) -> tuple[SyncItem, ...]: ...

    def snapshots_for_team(
        self, organization_id: str, team_id: str, *, period: ReportingBucket
    ) -> tuple[SnapshotRecord, ...]: ...

    def delete_subject(
        self,
        organization_id: str,
        subject_user_id: str,
        *,
        reason: DeletionReason,
        now: datetime,
    ) -> tuple[Tombstone, ...]: ...


class ManagerGrantStore(Protocol):
    """Explicit, expiring manager access grants."""

    def grants_for_manager(
        self, organization_id: str, manager_user_id: str
    ) -> tuple[ManagerAccessGrant, ...]: ...

    def grant(
        self, organization_id: str, grant_id: str
    ) -> ManagerAccessGrant | None: ...

    def revoke(
        self, organization_id: str, grant_id: str, *, now: datetime
    ) -> ManagerAccessGrant: ...


class CursorStore(Protocol):
    """Monotonic delivery acknowledgement per tenant/client/device."""

    def checkpoint(
        self, organization_id: str, client_id: str, device_id: str
    ) -> SyncCheckpoint: ...

    def acknowledge(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> SyncCheckpoint: ...

    def offer(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> SyncCheckpoint: ...


class RecipientDeliveryStore(Protocol):
    """Contiguous recipient-local streams plus the opaque delivery ledger."""

    def source_position(
        self, organization_id: str, client_id: str, device_id: str
    ) -> int: ...

    def advance_source(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> None: ...

    def read(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
        limit: int,
    ) -> tuple[SyncItem, ...]: ...

    def enqueue_snapshot(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        record: SnapshotRecord,
    ) -> SyncItem: ...

    def mark_delivered(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        items: tuple[SyncItem, ...],
    ) -> None: ...

    def enqueue_tombstones(
        self, organization_id: str, tombstones: tuple[Tombstone, ...]
    ) -> int: ...

class AggregateReleaseStore(Protocol):
    """Immutable first release for a team and fixed reporting bucket."""

    def release(
        self, organization_id: str, team_id: str, period: ReportingBucket
    ) -> TeamAggregate | None: ...

    def publish_once(self, aggregate: TeamAggregate) -> TeamAggregate: ...

    def invalidate_organization(self, organization_id: str) -> None: ...


class ApiClientStore(Protocol):
    """Tenant-scoped developer clients, their scopes, and their revocation."""

    def client(self, organization_id: str, client_id: str) -> ApiClient | None: ...

    def revoke(
        self, organization_id: str, client_id: str, *, now: datetime
    ) -> ApiClient: ...

    def clients_for_user(
        self, organization_id: str, user_id: str
    ) -> tuple[ApiClient, ...]: ...


class CredentialRevocationStore(Protocol):
    """Revoke every presented credential bound to one API client."""

    def revoke_client(
        self, organization_id: str, client_id: str, *, now: datetime
    ) -> int: ...


class AuditStore(Protocol):
    """Append-only audit evidence. Its rows are sensitive personal data."""

    def append(self, event: AuditEvent) -> AuditEvent: ...

    def next_sequence(self, organization_id: str) -> int: ...

    def read(
        self, organization_id: str, *, limit: int
    ) -> tuple[AuditEvent, ...]: ...


class EntitlementStore(Protocol):
    """Per-tenant entitlement lookup. Absence means no synchronization."""

    def entitlement(self, organization_id: str) -> Entitlement | None: ...


class IdentifierFactory(Protocol):
    """Issues opaque control-plane identifiers.

    Identifiers are issued by the plane, never accepted from a caller, so a
    client cannot choose an identifier that collides with another tenant's.
    """

    def issue(self, namespace: str) -> str: ...


class SignatureVerifierRegistry(Protocol):
    """Resolves the verifier for one algorithm, or nothing at all.

    Returning ``None`` for an unregistered algorithm is what makes the plane
    fail closed on production algorithms that have no reviewed adapter yet.
    """

    def verifier(
        self, algorithm: SignatureAlgorithm
    ) -> SignatureVerifier | None: ...


__all__ = [
    "ApiClientStore",
    "AggregateReleaseStore",
    "AuditStore",
    "CursorStore",
    "CredentialRevocationStore",
    "DeviceStore",
    "DirectoryStore",
    "EntitlementStore",
    "IdentifierFactory",
    "ManagerGrantStore",
    "RecipientDeliveryStore",
    "SignatureVerifierRegistry",
    "SnapshotStore",
    "TransactionBoundary",
]
