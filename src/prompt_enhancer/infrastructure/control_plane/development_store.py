"""In-memory development adapters for the control-plane ports.

This adapter exists so the domain rules can be exercised end to end without a
server, a schema migration, or a network. Two properties are load-bearing:

- every collection is keyed by ``(organization_id, ...)``, so a lookup with the
  wrong tenant simply finds nothing — the in-memory analogue of the row-level
  security policies the production PostgreSQL adapter will carry;
- all stores in one adapter set share a single re-entrant lock, so a use case
  wrapped in :class:`DevelopmentTransaction` is indivisible with respect to the
  other threads FastAPI runs endpoints on.

It is not a database. There is no durability, no crash recovery, no isolation
level beyond the one lock, and no encryption. Nothing in this module may become
a production storage path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import hmac
import secrets
import threading
from types import TracebackType

from pydantic import SecretStr

from ...application.control_plane import (
    ApiClient,
    ApiClientState,
    AuditEvent,
    ConsumedEnvelope,
    DeletionReason,
    Device,
    DeviceRegistration,
    DeviceState,
    DeviceVerificationKey,
    Entitlement,
    EnvelopeReservation,
    ManagerAccessGrant,
    MAX_OUTSTANDING_ENVELOPE_RESERVATIONS,
    Membership,
    MembershipState,
    Organization,
    ReportingBucket,
    SnapshotRecord,
    SuppressionReason,
    SyncAudience,
    SyncCheckpoint,
    SyncItem,
    SyncItemKind,
    Team,
    TeamAggregate,
    Tombstone,
    VerifiedIdentity,
)
from ...application.control_plane.identity import (
    MAX_CREDENTIAL_CHARACTERS,
    MIN_CREDENTIAL_CHARACTERS,
)
from ...application.persistence.errors import PersistenceConflictError
from ...domain import SAFE_VERSION_PATTERN


CREDENTIAL_DIGEST_DOMAIN = b"prompt-enhancer/control-plane-credential/v1"


def credential_digest(credential: SecretStr) -> str:
    """Digest a presented credential for lookup.

    The store keeps only this digest, so a dump of development state does not
    hand over usable credentials. Credentials are high-entropy random strings,
    which is why a plain domain-separated hash is adequate here and why this is
    still not an acceptable production credential store.
    """

    raw = credential.get_secret_value()
    if not MIN_CREDENTIAL_CHARACTERS <= len(raw) <= MAX_CREDENTIAL_CHARACTERS:
        raise ValueError("credentials have an unexpected size")
    return hashlib.sha256(
        CREDENTIAL_DIGEST_DOMAIN + b"\x00" + raw.encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class RandomIdentifierFactory:
    """Issue unguessable, installation-local control-plane identifiers.

    Identifiers are random rather than derived so that no identifier reveals
    what it names, and so a caller cannot precompute another tenant's keys.
    """

    def issue(self, namespace: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(namespace) is None:
            raise ValueError("identifier namespace must be a safe identifier")
        return secrets.token_hex(32)


@dataclass(frozen=True, slots=True)
class DevelopmentTransaction:
    """One re-entrant lock shared by every store in an adapter set."""

    lock: threading.RLock

    def __enter__(self) -> None:
        self.lock.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        self.lock.release()
        return None


@dataclass(slots=True)
class DevelopmentDirectoryStore:
    """Organizations, teams, memberships, and roles held in memory."""

    lock: threading.RLock
    organizations: dict[str, Organization] = field(default_factory=dict)
    teams: dict[tuple[str, str], Team] = field(default_factory=dict)
    memberships: dict[tuple[str, str], Membership] = field(default_factory=dict)

    def organization(self, organization_id: str) -> Organization | None:
        with self.lock:
            return self.organizations.get(organization_id)

    def team(self, organization_id: str, team_id: str) -> Team | None:
        with self.lock:
            return self.teams.get((organization_id, team_id))

    def membership(self, organization_id: str, user_id: str) -> Membership | None:
        with self.lock:
            return self.memberships.get((organization_id, user_id))

    def team_memberships(
        self, organization_id: str, team_id: str
    ) -> tuple[Membership, ...]:
        with self.lock:
            return tuple(
                membership
                for (scope, _), membership in sorted(self.memberships.items())
                if scope == organization_id and membership.belongs_to_team(team_id)
            )

    def revoke_membership(
        self, organization_id: str, user_id: str, *, now: datetime
    ) -> Membership:
        with self.lock:
            membership = self.memberships.get((organization_id, user_id))
            if membership is None:
                raise PersistenceConflictError("membership does not exist")
            if membership.state is MembershipState.REVOKED:
                return membership
            revoked = membership.model_copy(
                update={"state": MembershipState.REVOKED, "revoked_at": now}
            )
            self.memberships[(organization_id, user_id)] = revoked
            return revoked


@dataclass(slots=True)
class DevelopmentDeviceStore:
    """Device identities and their verification material held in memory."""

    lock: threading.RLock
    devices: dict[tuple[str, str], Device] = field(default_factory=dict)
    keys: dict[tuple[str, str], DeviceVerificationKey] = field(default_factory=dict)

    def register(self, registration: DeviceRegistration) -> Device:
        with self.lock:
            scope = (registration.organization_id, registration.device_id)
            if scope in self.devices:
                raise PersistenceConflictError("device identifier already exists")
            device = Device(
                device_id=registration.device_id,
                organization_id=registration.organization_id,
                user_id=registration.user_id,
                algorithm=registration.key.algorithm,
                key_fingerprint=registration.key.key_fingerprint,
                state=DeviceState.ACTIVE,
                registered_at=registration.registered_at,
            )
            self.devices[scope] = device
            self.keys[scope] = registration.key
            return device

    def device(self, organization_id: str, device_id: str) -> Device | None:
        with self.lock:
            return self.devices.get((organization_id, device_id))

    def verification_key(
        self, organization_id: str, device_id: str
    ) -> DeviceVerificationKey | None:
        with self.lock:
            device = self.devices.get((organization_id, device_id))
            if device is None or not device.is_active():
                return None
            return self.keys.get((organization_id, device_id))

    def revoke(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> Device:
        with self.lock:
            scope = (organization_id, device_id)
            device = self.devices.get(scope)
            if device is None:
                raise PersistenceConflictError("device does not exist")
            if device.state is DeviceState.REVOKED:
                return device
            revoked = device.model_copy(
                update={"state": DeviceState.REVOKED, "revoked_at": now}
            )
            self.devices[scope] = revoked
            # Revocation destroys the material as well as the flag, so a later
            # verification cannot succeed even if a state check is ever missed.
            self.keys.pop(scope, None)
            return revoked

    def devices_for_user(
        self, organization_id: str, user_id: str
    ) -> tuple[Device, ...]:
        with self.lock:
            return tuple(
                device
                for (scope, _), device in sorted(self.devices.items())
                if scope == organization_id and device.user_id == user_id
            )


@dataclass(slots=True)
class DevelopmentSnapshotStore:
    """The per-tenant ordered log, plus the fence that outlives deletion."""

    lock: threading.RLock
    identifiers: RandomIdentifierFactory = field(
        default_factory=RandomIdentifierFactory
    )
    log: dict[str, list[SyncItem]] = field(default_factory=dict)
    heads: dict[str, int] = field(default_factory=dict)
    consumed: dict[tuple[str, str], ConsumedEnvelope] = field(default_factory=dict)
    reservations: dict[tuple[str, str], EnvelopeReservation] = field(
        default_factory=dict
    )
    deletion_epochs: dict[tuple[str, str], datetime] = field(default_factory=dict)
    deletion_generations: dict[tuple[str, str], int] = field(default_factory=dict)

    def next_sequence(self, organization_id: str) -> int:
        with self.lock:
            return self.heads.get(organization_id, 0) + 1

    def reserve_envelope(self, reservation: EnvelopeReservation) -> None:
        with self.lock:
            expired_or_consumed = tuple(
                key
                for key, current in self.reservations.items()
                if current.expires_at <= reservation.issued_at
                or key in self.consumed
            )
            for key in expired_or_consumed:
                self.reservations.pop(key, None)
            outstanding = sum(
                current.organization_id == reservation.organization_id
                and current.subject_user_id == reservation.subject_user_id
                and current.client_id == reservation.client_id
                and current.device_id == reservation.device_id
                for current in self.reservations.values()
            )
            if outstanding >= MAX_OUTSTANDING_ENVELOPE_RESERVATIONS:
                raise PersistenceConflictError(
                    "one producer may hold only one envelope reservation"
                )
            scope = (reservation.organization_id, reservation.envelope_id)
            if scope in self.reservations or scope in self.consumed:
                raise PersistenceConflictError("envelope identifier already exists")
            self.reservations[scope] = reservation

    def envelope_reservation(
        self, organization_id: str, envelope_id: str
    ) -> EnvelopeReservation | None:
        with self.lock:
            return self.reservations.get((organization_id, envelope_id))

    def active_envelope_reservation(
        self,
        organization_id: str,
        subject_user_id: str,
        client_id: str,
        device_id: str,
        *,
        now: datetime,
    ) -> EnvelopeReservation | None:
        with self.lock:
            for scope, reservation in tuple(self.reservations.items()):
                if scope in self.consumed or reservation.expires_at <= now:
                    self.reservations.pop(scope, None)
                    continue
                if (
                    reservation.organization_id == organization_id
                    and reservation.subject_user_id == subject_user_id
                    and reservation.client_id == client_id
                    and reservation.device_id == device_id
                ):
                    return reservation
            return None

    def invalidate_subject_reservations(
        self, organization_id: str, subject_user_id: str
    ) -> int:
        with self.lock:
            doomed = tuple(
                scope
                for scope, reservation in self.reservations.items()
                if reservation.organization_id == organization_id
                and reservation.subject_user_id == subject_user_id
            )
            for scope in doomed:
                self.reservations.pop(scope, None)
            return len(doomed)

    def _append(self, organization_id: str, item: SyncItem) -> None:
        expected = self.heads.get(organization_id, 0) + 1
        if item.sequence != expected:
            raise PersistenceConflictError("sequence numbers must be contiguous")
        self.log.setdefault(organization_id, []).append(item)
        self.heads[organization_id] = item.sequence

    def append_snapshot(self, record: SnapshotRecord) -> SnapshotRecord:
        with self.lock:
            organization_id = record.organization_id
            envelope_id = record.envelope.envelope_id
            reservation = self.reservations.get((organization_id, envelope_id))
            if reservation is None:
                raise PersistenceConflictError("envelope identifier was not reserved")
            if (
                reservation.subject_user_id != record.subject_user_id
                or reservation.device_id != record.device_id
            ):
                raise PersistenceConflictError("envelope reservation binding mismatch")
            current_epoch = self.deletion_generations.get(
                (organization_id, record.subject_user_id), 0
            )
            if reservation.subject_epoch != current_epoch:
                raise PersistenceConflictError("envelope reservation epoch is stale")
            if record.envelope.issued_at < reservation.issued_at:
                raise PersistenceConflictError(
                    "envelope predates its server reservation"
                )
            if record.accepted_at >= reservation.expires_at:
                raise PersistenceConflictError("envelope reservation expired")
            if (organization_id, envelope_id) in self.consumed:
                raise PersistenceConflictError("envelope identifier already consumed")
            self._append(
                organization_id,
                SyncItem(
                    kind=SyncItemKind.SNAPSHOT,
                    sequence=record.sequence,
                    audience=SyncAudience(
                        organization_id=record.organization_id,
                        subject_user_id=record.subject_user_id,
                        team_id=record.team_id,
                        visibility=record.visibility,
                    ),
                    snapshot=record,
                ),
            )
            # The fence entry and the row are written together. A caller that
            # observes the row always observes the fence that protects it.
            self.consumed[(organization_id, envelope_id)] = ConsumedEnvelope(
                organization_id=organization_id,
                envelope_id=envelope_id,
                snapshot_id=record.snapshot_id,
                subject_user_id=record.subject_user_id,
                client_id=reservation.client_id,
                device_id=record.device_id,
                content_digest=record.content_digest,
                first_sequence=record.sequence,
                consumed_at=record.accepted_at,
            )
            self.reservations.pop((organization_id, envelope_id), None)
            return record

    def consumed_envelope(
        self, organization_id: str, envelope_id: str
    ) -> ConsumedEnvelope | None:
        with self.lock:
            return self.consumed.get((organization_id, envelope_id))

    def subject_deletion_epoch(
        self, organization_id: str, subject_user_id: str
    ) -> datetime | None:
        with self.lock:
            return self.deletion_epochs.get((organization_id, subject_user_id))

    def subject_deletion_generation(
        self, organization_id: str, subject_user_id: str
    ) -> int:
        with self.lock:
            return self.deletion_generations.get(
                (organization_id, subject_user_id), 0
            )

    def snapshot_by_envelope(
        self, organization_id: str, envelope_id: str
    ) -> SnapshotRecord | None:
        with self.lock:
            for item in self.log.get(organization_id, ()):
                record = item.snapshot
                if record is not None and record.envelope.envelope_id == envelope_id:
                    return record
            return None

    def read_since(
        self, organization_id: str, *, sequence: int, limit: int
    ) -> tuple[SyncItem, ...]:
        with self.lock:
            entries = [
                item
                for item in self.log.get(organization_id, ())
                if item.sequence > sequence
            ]
            return tuple(entries[:limit])

    def snapshots_for_team(
        self, organization_id: str, team_id: str, *, period: ReportingBucket
    ) -> tuple[SnapshotRecord, ...]:
        with self.lock:
            selected: list[SnapshotRecord] = []
            for item in self.log.get(organization_id, ()):
                record = item.snapshot
                if record is None or record.team_id != team_id:
                    continue
                if record.period != period:
                    continue
                selected.append(record)
            return tuple(selected)

    def delete_subject(
        self,
        organization_id: str,
        subject_user_id: str,
        *,
        reason: DeletionReason,
        now: datetime,
    ) -> tuple[Tombstone, ...]:
        with self.lock:
            # The epoch is recorded even when nothing was published, so an
            # envelope signed before the request cannot arrive afterwards.
            epoch_key = (organization_id, subject_user_id)
            previous = self.deletion_epochs.get((organization_id, subject_user_id))
            if previous is None or now > previous:
                self.deletion_epochs[epoch_key] = now
            self.deletion_generations[epoch_key] = (
                self.deletion_generations.get(epoch_key, 0) + 1
            )
            self.invalidate_subject_reservations(
                organization_id, subject_user_id
            )

            entries = self.log.get(organization_id, [])
            removed = [
                item.snapshot
                for item in entries
                if item.snapshot is not None
                and item.snapshot.subject_user_id == subject_user_id
            ]
            if not removed:
                return ()
            self.log[organization_id] = [
                item
                for item in entries
                if item.snapshot is None
                or item.snapshot.subject_user_id != subject_user_id
            ]
            tombstones: list[Tombstone] = []
            for record in removed:
                envelope_id = record.envelope.envelope_id
                fence = self.consumed.get((organization_id, envelope_id))
                if fence is not None:
                    self.consumed[(organization_id, envelope_id)] = fence.model_copy(
                        update={"deleted": True}
                    )
                # Identity-bearing reservation metadata is no longer needed;
                # the opaque consumed fence alone prevents resurrection.
                self.reservations.pop((organization_id, envelope_id), None)
                tombstone = Tombstone(
                    tombstone_id=self.identifiers.issue("tombstone"),
                    target_snapshot_id=record.snapshot_id,
                    recorded_at=now,
                )
                sequence = self.heads.get(organization_id, 0) + 1
                self._append(
                    organization_id,
                    SyncItem(
                        kind=SyncItemKind.TOMBSTONE,
                        sequence=sequence,
                        audience=SyncAudience(
                            organization_id=record.organization_id,
                            subject_user_id=record.subject_user_id,
                            team_id=record.team_id,
                            visibility=record.visibility,
                        ),
                        tombstone=tombstone,
                    ),
                )
                tombstones.append(tombstone)
            return tuple(tombstones)


@dataclass(slots=True)
class DevelopmentCursorStore:
    """Atomic acknowledgement state keyed by tenant, client, and device."""

    lock: threading.RLock
    checkpoints: dict[tuple[str, str, str], SyncCheckpoint] = field(
        default_factory=dict
    )

    def checkpoint(
        self, organization_id: str, client_id: str, device_id: str
    ) -> SyncCheckpoint:
        with self.lock:
            key = (organization_id, client_id, device_id)
            return self.checkpoints.get(key) or SyncCheckpoint(
                organization_id=organization_id,
                client_id=client_id,
                device_id=device_id,
            )

    def acknowledge(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> SyncCheckpoint:
        with self.lock:
            current = self.checkpoint(organization_id, client_id, device_id)
            if sequence < current.acknowledged_sequence:
                raise PersistenceConflictError("cursor acknowledgements are monotonic")
            if sequence > current.offered_sequence:
                raise PersistenceConflictError("cursor was not offered")
            updated = current.model_copy(
                update={"acknowledged_sequence": sequence}
            )
            self.checkpoints[(organization_id, client_id, device_id)] = updated
            return updated

    def offer(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> SyncCheckpoint:
        with self.lock:
            current = self.checkpoint(organization_id, client_id, device_id)
            updated = current.model_copy(
                update={"offered_sequence": max(current.offered_sequence, sequence)}
            )
            self.checkpoints[(organization_id, client_id, device_id)] = updated
            return updated


@dataclass(slots=True)
class DevelopmentRecipientDeliveryStore:
    """Recipient-local contiguous streams and opaque delivery receipts."""

    lock: threading.RLock
    identifiers: RandomIdentifierFactory = field(
        default_factory=RandomIdentifierFactory
    )
    source_positions: dict[tuple[str, str, str], int] = field(default_factory=dict)
    streams: dict[tuple[str, str, str], list[SyncItem]] = field(
        default_factory=dict
    )
    heads: dict[tuple[str, str, str], int] = field(default_factory=dict)
    delivery_sources: dict[tuple[str, str, str, int], str] = field(
        default_factory=dict
    )
    delivered: dict[
        tuple[str, str],
        dict[tuple[str, str, str], tuple[str, SyncAudience]],
    ] = field(default_factory=dict)

    @staticmethod
    def _key(
        organization_id: str, client_id: str, device_id: str
    ) -> tuple[str, str, str]:
        return (organization_id, client_id, device_id)

    def source_position(
        self, organization_id: str, client_id: str, device_id: str
    ) -> int:
        with self.lock:
            return self.source_positions.get(
                self._key(organization_id, client_id, device_id), 0
            )

    def advance_source(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
    ) -> None:
        with self.lock:
            key = self._key(organization_id, client_id, device_id)
            current = self.source_positions.get(key, 0)
            if sequence < current:
                raise PersistenceConflictError("source position cannot move backward")
            self.source_positions[key] = sequence

    def read(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        *,
        sequence: int,
        limit: int,
    ) -> tuple[SyncItem, ...]:
        with self.lock:
            key = self._key(organization_id, client_id, device_id)
            selected = (
                item for item in self.streams.get(key, ()) if item.sequence > sequence
            )
            return tuple(list(selected)[:limit])

    def enqueue_snapshot(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        record: SnapshotRecord,
    ) -> SyncItem:
        with self.lock:
            key = self._key(organization_id, client_id, device_id)
            sequence = self.heads.get(key, 0) + 1
            recipient_snapshot_id = self.identifiers.issue("delivery-snapshot")
            delivered_record = record.model_copy(
                update={"snapshot_id": recipient_snapshot_id}
            )
            audience = SyncAudience(
                organization_id=record.organization_id,
                subject_user_id=record.subject_user_id,
                team_id=record.team_id,
                visibility=record.visibility,
            )
            item = SyncItem(
                kind=SyncItemKind.SNAPSHOT,
                sequence=sequence,
                audience=audience,
                snapshot=delivered_record,
            )
            self.streams.setdefault(key, []).append(item)
            self.heads[key] = sequence
            self.delivery_sources[(*key, sequence)] = record.snapshot_id
            return item

    def mark_delivered(
        self,
        organization_id: str,
        client_id: str,
        device_id: str,
        items: tuple[SyncItem, ...],
    ) -> None:
        with self.lock:
            recipient = self._key(organization_id, client_id, device_id)
            for item in items:
                if item.snapshot is None:
                    continue
                server_snapshot_id = self.delivery_sources.get(
                    (*recipient, item.sequence)
                )
                if server_snapshot_id is None:
                    continue
                self.delivered.setdefault(
                    (organization_id, server_snapshot_id), {}
                )[recipient] = (item.snapshot.snapshot_id, item.audience)

    def enqueue_tombstones(
        self, organization_id: str, tombstones: tuple[Tombstone, ...]
    ) -> int:
        with self.lock:
            enqueued = 0
            for internal in tombstones:
                recipients = self.delivered.pop(
                    (organization_id, internal.target_snapshot_id), {}
                )
                for recipient, (recipient_snapshot_id, audience) in recipients.items():
                    # Erasure must not leave the full delivered snapshot in the
                    # retry stream. Replace any older local offer with an opaque
                    # marker at the same position, then also append a fresh
                    # marker. The fresh position closes the race where a client
                    # acknowledges the old offer while deletion is committed.
                    stream = self.streams.get(recipient, [])
                    for index, prior in enumerate(stream):
                        source_key = (*recipient, prior.sequence)
                        if (
                            prior.snapshot is None
                            or self.delivery_sources.get(source_key)
                            != internal.target_snapshot_id
                        ):
                            continue
                        retry_marker = Tombstone(
                            tombstone_id=self.identifiers.issue(
                                "delivery-tombstone"
                            ),
                            target_snapshot_id=prior.snapshot.snapshot_id,
                            recorded_at=internal.recorded_at,
                        )
                        stream[index] = SyncItem(
                            kind=SyncItemKind.TOMBSTONE,
                            sequence=prior.sequence,
                            audience=audience,
                            tombstone=retry_marker,
                        )
                        self.delivery_sources.pop(source_key, None)
                    sequence = self.heads.get(recipient, 0) + 1
                    marker = Tombstone(
                        tombstone_id=self.identifiers.issue("delivery-tombstone"),
                        target_snapshot_id=recipient_snapshot_id,
                        recorded_at=internal.recorded_at,
                    )
                    item = SyncItem(
                        kind=SyncItemKind.TOMBSTONE,
                        sequence=sequence,
                        audience=audience,
                        tombstone=marker,
                    )
                    self.streams.setdefault(recipient, []).append(item)
                    self.heads[recipient] = sequence
                    enqueued += 1
            return enqueued

@dataclass(slots=True)
class DevelopmentAggregateReleaseStore:
    """First publishable result wins for each fixed team bucket."""

    lock: threading.RLock
    releases: dict[tuple[str, str, str, str], TeamAggregate] = field(
        default_factory=dict
    )

    @staticmethod
    def _key(
        organization_id: str, team_id: str, period: ReportingBucket
    ) -> tuple[str, str, str, str]:
        return (organization_id, team_id, period.kind.value, period.key)

    def release(
        self, organization_id: str, team_id: str, period: ReportingBucket
    ) -> TeamAggregate | None:
        with self.lock:
            return self.releases.get(self._key(organization_id, team_id, period))

    def publish_once(self, aggregate: TeamAggregate) -> TeamAggregate:
        if aggregate.suppressed:
            raise PersistenceConflictError("suppressed aggregates are not releases")
        with self.lock:
            key = self._key(
                aggregate.organization_id, aggregate.team_id, aggregate.period
            )
            existing = self.releases.get(key)
            if existing is not None:
                return existing
            self.releases[key] = aggregate
            return aggregate

    def invalidate_organization(self, organization_id: str) -> None:
        """Erase released values and permanently suppress affected buckets."""

        with self.lock:
            for key, aggregate in tuple(self.releases.items()):
                if key[0] != organization_id:
                    continue
                self.releases[key] = TeamAggregate(
                    organization_id=aggregate.organization_id,
                    team_id=aggregate.team_id,
                    period=aggregate.period,
                    minimum_cohort_size=aggregate.minimum_cohort_size,
                    suppressed=True,
                    suppression_reason=SuppressionReason.PRIVACY_DELETION,
                )


@dataclass(slots=True)
class DevelopmentManagerGrantStore:
    lock: threading.RLock
    grants: dict[str, list[ManagerAccessGrant]] = field(default_factory=dict)

    def grants_for_manager(
        self, organization_id: str, manager_user_id: str
    ) -> tuple[ManagerAccessGrant, ...]:
        with self.lock:
            return tuple(
                grant
                for grant in self.grants.get(organization_id, ())
                if grant.manager_user_id == manager_user_id
            )

    def grant(
        self, organization_id: str, grant_id: str
    ) -> ManagerAccessGrant | None:
        with self.lock:
            return next(
                (
                    grant
                    for grant in self.grants.get(organization_id, ())
                    if grant.grant_id == grant_id
                ),
                None,
            )

    def revoke(
        self, organization_id: str, grant_id: str, *, now: datetime
    ) -> ManagerAccessGrant:
        with self.lock:
            grants = self.grants.get(organization_id, [])
            for index, grant in enumerate(grants):
                if grant.grant_id != grant_id:
                    continue
                if grant.revoked_at is not None:
                    return grant
                revoked = grant.model_copy(update={"revoked_at": now})
                grants[index] = revoked
                return revoked
            raise PersistenceConflictError("manager grant does not exist")


@dataclass(slots=True)
class DevelopmentApiClientStore:
    lock: threading.RLock
    clients: dict[tuple[str, str], ApiClient] = field(default_factory=dict)

    def client(self, organization_id: str, client_id: str) -> ApiClient | None:
        with self.lock:
            return self.clients.get((organization_id, client_id))

    def revoke(
        self, organization_id: str, client_id: str, *, now: datetime
    ) -> ApiClient:
        with self.lock:
            scope = (organization_id, client_id)
            client = self.clients.get(scope)
            if client is None:
                raise PersistenceConflictError("client does not exist")
            if client.state is ApiClientState.REVOKED:
                return client
            revoked = client.model_copy(
                update={"state": ApiClientState.REVOKED, "revoked_at": now}
            )
            self.clients[scope] = revoked
            return revoked

    def clients_for_user(
        self, organization_id: str, user_id: str
    ) -> tuple[ApiClient, ...]:
        with self.lock:
            return tuple(
                client
                for (scope, _), client in sorted(self.clients.items())
                if scope == organization_id and client.user_id == user_id
            )


@dataclass(slots=True)
class DevelopmentCredentialStore:
    """Digest-keyed credential lookup for the development resolver."""

    lock: threading.RLock
    identities: dict[str, VerifiedIdentity] = field(default_factory=dict)
    revoked_digests: set[str] = field(default_factory=set)

    def bind(self, digest: str, identity: VerifiedIdentity) -> None:
        with self.lock:
            if digest in self.identities or digest in self.revoked_digests:
                raise PersistenceConflictError("credential already bound")
            self.identities[digest] = identity

    def identity_for(self, digest: str) -> VerifiedIdentity | None:
        with self.lock:
            # Compare against every stored digest so lookup position is not
            # exposed through an early return. This is still only a
            # development credential store, not a hardened authenticator.
            matched: VerifiedIdentity | None = None
            for stored, identity in self.identities.items():
                if hmac.compare_digest(stored, digest):
                    matched = None if stored in self.revoked_digests else identity
            return matched

    def revoke_client(
        self, organization_id: str, client_id: str, *, now: datetime
    ) -> int:
        del now
        with self.lock:
            revoked = 0
            for digest, identity in self.identities.items():
                if (
                    identity.organization_id == organization_id
                    and identity.client_id == client_id
                    and digest not in self.revoked_digests
                ):
                    self.revoked_digests.add(digest)
                    revoked += 1
            return revoked


@dataclass(slots=True)
class DevelopmentAuditStore:
    lock: threading.RLock
    events: dict[str, list[AuditEvent]] = field(default_factory=dict)

    def next_sequence(self, organization_id: str) -> int:
        with self.lock:
            return len(self.events.get(organization_id, ())) + 1

    def append(self, event: AuditEvent) -> AuditEvent:
        with self.lock:
            entries = self.events.setdefault(event.organization_id, [])
            if event.sequence != len(entries) + 1:
                raise PersistenceConflictError(
                    "audit sequence numbers must be contiguous"
                )
            entries.append(event)
            return event

    def read(self, organization_id: str, *, limit: int) -> tuple[AuditEvent, ...]:
        with self.lock:
            entries = self.events.get(organization_id, ())
            return tuple(entries[-limit:])


@dataclass(slots=True)
class DevelopmentEntitlementStore:
    lock: threading.RLock
    entitlements: dict[str, Entitlement] = field(default_factory=dict)

    def entitlement(self, organization_id: str) -> Entitlement | None:
        with self.lock:
            return self.entitlements.get(organization_id)


__all__ = [
    "CREDENTIAL_DIGEST_DOMAIN",
    "DevelopmentApiClientStore",
    "DevelopmentAggregateReleaseStore",
    "DevelopmentAuditStore",
    "DevelopmentCredentialStore",
    "DevelopmentCursorStore",
    "DevelopmentDeviceStore",
    "DevelopmentDirectoryStore",
    "DevelopmentEntitlementStore",
    "DevelopmentManagerGrantStore",
    "DevelopmentRecipientDeliveryStore",
    "DevelopmentSnapshotStore",
    "DevelopmentTransaction",
    "RandomIdentifierFactory",
    "credential_digest",
]
