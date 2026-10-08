"""Recipient-scoped, acknowledged delta synchronization.

The development contract is honestly **at least once**. Each authenticated
client/device pair has its own contiguous sequence space and monotonic
acknowledgement checkpoint. A hidden tenant-source position may advance past
rows the recipient cannot read, but those rows never allocate a public
sequence or create a visible gap.

Authorization is evaluated before a snapshot enters a recipient stream. Once
the snapshot is actually offered, a delivery ledger remembers only the source
and recipient's opaque handle. Deletion uses that ledger, rather than current
authorization, to enqueue an opaque tombstone for every prior recipient. Thus
grant expiry or revocation cannot strand a copy that was previously delivered.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .contracts import VisibilityScope
from .envelopes import SnapshotEnvelope
from .periods import ReportingBucket


MAX_DELTA_PAGE_ITEMS = 100
DEFAULT_DELTA_PAGE_ITEMS = 50
MAX_OUTSTANDING_ENVELOPE_RESERVATIONS = 1
ENVELOPE_RESERVATION_TTL = timedelta(minutes=5)


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("synchronization identifiers must be HMAC pseudonyms")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    return None if value is None else _pseudonym(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("synchronization timestamps must be UTC")
    if value.microsecond:
        raise ValueError("synchronization timestamps are whole seconds")
    return value


class DeletionReason(StrEnum):
    SUBJECT_REQUEST = "subject_request"
    MEMBERSHIP_REVOKED = "membership_revoked"
    DEVICE_REVOKED = "device_revoked"
    ADMINISTRATIVE_DELETION = "administrative_deletion"


class SnapshotRecord(StrictModel):
    """One envelope stamped with identity from the verified credential."""

    snapshot_id: str
    organization_id: str
    subject_user_id: str
    device_id: str
    # Tenant-source ordering is internal. Delta clients receive a contiguous,
    # recipient-local sequence on ``SyncItem`` instead.
    sequence: int = Field(ge=1, exclude=True, repr=False)
    accepted_at: datetime
    content_digest: str
    envelope: SnapshotEnvelope

    _identifiers = field_validator(
        "snapshot_id",
        "organization_id",
        "subject_user_id",
        "device_id",
        "content_digest",
    )(_pseudonym)
    _accepted = field_validator("accepted_at")(_utc)

    @property
    def team_id(self) -> str | None:
        return self.envelope.team_id

    @property
    def visibility(self) -> VisibilityScope:
        return self.envelope.visibility

    @property
    def period(self) -> ReportingBucket:
        return self.envelope.period


class Tombstone(StrictModel):
    """The public, opaque instruction to forget one server snapshot handle."""

    tombstone_id: str
    target_snapshot_id: str
    recorded_at: datetime

    _identifiers = field_validator("tombstone_id", "target_snapshot_id")(_pseudonym)
    _recorded = field_validator("recorded_at")(_utc)


class SyncAudience(StrictModel):
    """Internal authorization metadata that is never part of a delta payload."""

    organization_id: str
    subject_user_id: str
    visibility: VisibilityScope
    team_id: str | None = None

    _identifiers = field_validator("organization_id", "subject_user_id")(_pseudonym)
    _optional_identifiers = field_validator("team_id")(_optional_pseudonym)

    @model_validator(mode="after")
    def team_audience_names_its_team(self) -> SyncAudience:
        if self.visibility is VisibilityScope.TEAM and self.team_id is None:
            raise ValueError("a team audience must name its team")
        return self


class EnvelopeReservation(StrictModel):
    """A server-issued envelope identifier bound to one authenticated producer."""

    envelope_id: str
    organization_id: str
    subject_user_id: str
    client_id: str
    device_id: str
    subject_epoch: int = Field(ge=0)
    issued_at: datetime
    expires_at: datetime

    _identifiers = field_validator(
        "envelope_id", "organization_id", "subject_user_id", "client_id", "device_id"
    )(_pseudonym)
    _issued = field_validator("issued_at")(_utc)
    _expires = field_validator("expires_at")(_utc)

    @model_validator(mode="after")
    def bounded_lifetime(self) -> EnvelopeReservation:
        if self.expires_at <= self.issued_at:
            raise ValueError("an envelope reservation must expire after issuance")
        if self.expires_at - self.issued_at > ENVELOPE_RESERVATION_TTL:
            raise ValueError("an envelope reservation exceeds the maximum lifetime")
        return self

    def is_active(self, now: datetime) -> bool:
        return self.issued_at <= _utc(now) < self.expires_at


class EnvelopeIdentifier(StrictModel):
    """The only caller-visible part of an envelope reservation."""

    envelope_id: str

    _identifier = field_validator("envelope_id")(_pseudonym)


class ConsumedEnvelope(StrictModel):
    """An immutable record that one envelope identifier was already accepted.

    The fence outlives the snapshot. Deleting a subject's data removes the
    snapshot but keeps this row, so a device that still holds the signed
    envelope cannot re-publish it and undo the deletion.
    """

    organization_id: str
    envelope_id: str
    snapshot_id: str
    subject_user_id: str
    client_id: str
    device_id: str
    content_digest: str
    first_sequence: int = Field(ge=1)
    consumed_at: datetime
    deleted: bool = False

    _identifiers = field_validator(
        "organization_id",
        "envelope_id",
        "snapshot_id",
        "subject_user_id",
        "client_id",
        "device_id",
        "content_digest",
    )(_pseudonym)
    _consumed = field_validator("consumed_at")(_utc)


class SyncItemKind(StrEnum):
    SNAPSHOT = "snapshot"
    TOMBSTONE = "tombstone"


class SyncItem(StrictModel):
    """Exactly one payload at a recipient-local sequence position."""

    kind: SyncItemKind
    sequence: int = Field(ge=1)
    # The audience is required to authorize both snapshots and tombstones but
    # excluded from every serialized response. Snapshot payloads contain their
    # own visible metadata; tombstones deliberately do not.
    audience: SyncAudience = Field(exclude=True, repr=False)
    snapshot: SnapshotRecord | None = None
    tombstone: Tombstone | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> SyncItem:
        payloads = (self.snapshot, self.tombstone)
        if sum(payload is not None for payload in payloads) != 1:
            raise ValueError("a sync item carries exactly one payload")
        if self.kind is SyncItemKind.SNAPSHOT and self.snapshot is None:
            raise ValueError("snapshot items must carry a snapshot")
        if self.kind is SyncItemKind.TOMBSTONE and self.tombstone is None:
            raise ValueError("tombstone items must carry a tombstone")
        if self.snapshot is not None:
            expected = SyncAudience(
                organization_id=self.snapshot.organization_id,
                subject_user_id=self.snapshot.subject_user_id,
                team_id=self.snapshot.team_id,
                visibility=self.snapshot.visibility,
            )
            if self.audience != expected:
                raise ValueError("snapshot audience must match its envelope")
        return self

    @property
    def _payload(self) -> SnapshotRecord | Tombstone:
        payload = self.snapshot if self.snapshot is not None else self.tombstone
        if payload is None:
            raise ValueError("a sync item always carries one payload")
        return payload

    @property
    def subject_user_id(self) -> str:
        return self.audience.subject_user_id

    @property
    def team_id(self) -> str | None:
        return self.audience.team_id

    @property
    def visibility(self) -> VisibilityScope:
        return self.audience.visibility

    @property
    def organization_id(self) -> str:
        return self.audience.organization_id


class SyncCursor(StrictModel):
    """A sequence boundary returned by the server."""

    sequence: int = Field(default=0, ge=0)


class SyncCheckpoint(StrictModel):
    """Server state bound to one authenticated client and device."""

    organization_id: str
    client_id: str
    device_id: str
    acknowledged_sequence: int = Field(default=0, ge=0)
    offered_sequence: int = Field(default=0, ge=0)

    _identifiers = field_validator("organization_id", "client_id", "device_id")(
        _pseudonym
    )

    @model_validator(mode="after")
    def acknowledged_was_offered(self) -> SyncCheckpoint:
        if self.acknowledged_sequence > self.offered_sequence:
            raise ValueError("an acknowledged sequence must have been offered")
        return self


class DeltaPage(StrictModel):
    """One ordered page of changes plus the cursor that resumes after it.

    ``next_cursor`` is the last contiguous recipient-local item offered. Hidden
    source rows that the caller may not read do not affect it.
    """

    organization_id: str
    items: tuple[SyncItem, ...] = Field(max_length=MAX_DELTA_PAGE_ITEMS)
    acknowledged_cursor: SyncCursor
    next_cursor: SyncCursor
    has_more: bool

    _identifier = field_validator("organization_id")(_pseudonym)

    @model_validator(mode="after")
    def strictly_increasing_within_tenant(self) -> DeltaPage:
        previous = self.acknowledged_cursor.sequence
        for item in self.items:
            if item.sequence != previous + 1:
                raise ValueError("recipient delta pages must be contiguous")
            previous = item.sequence
            if item.organization_id != self.organization_id:
                raise ValueError("a delta page cannot mix tenants")
        if self.next_cursor.sequence < self.acknowledged_cursor.sequence:
            raise ValueError("the offered cursor cannot precede the acknowledgement")
        if self.items and self.next_cursor.sequence < previous:
            raise ValueError("the next cursor cannot precede delivered items")
        return self


class PushReceipt(StrictModel):
    """The result of one push without exposing the tenant-source position."""

    envelope_id: str
    snapshot_id: str
    content_digest: str
    duplicate: bool

    _identifiers = field_validator("envelope_id", "snapshot_id", "content_digest")(
        _pseudonym
    )


class DeletionReceipt(StrictModel):
    """A minimized acknowledgement of subject erasure."""

    organization_id: str
    subject_user_id: str
    deleted_snapshot_count: int = Field(ge=0)

    _identifiers = field_validator("organization_id", "subject_user_id")(_pseudonym)


__all__ = [
    "DEFAULT_DELTA_PAGE_ITEMS",
    "ENVELOPE_RESERVATION_TTL",
    "MAX_DELTA_PAGE_ITEMS",
    "MAX_OUTSTANDING_ENVELOPE_RESERVATIONS",
    "ConsumedEnvelope",
    "DeletionReason",
    "DeletionReceipt",
    "DeltaPage",
    "EnvelopeIdentifier",
    "EnvelopeReservation",
    "PushReceipt",
    "SnapshotRecord",
    "SyncAudience",
    "SyncCheckpoint",
    "SyncCursor",
    "SyncItem",
    "SyncItemKind",
    "Tombstone",
]
