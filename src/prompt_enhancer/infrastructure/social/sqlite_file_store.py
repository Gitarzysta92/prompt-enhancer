"""Restart-safe SQLite adapters for the direct file-sharing metadata ports.

The store shares ``SqliteSocialConnection`` (one connection, one re-entrant
lock, one ``BEGIN IMMEDIATE`` transaction per service operation) with the
social store, so a file-sharing operation, its social checks and its audit rows
commit or roll back together.  Only integrity/authorization metadata exists in
the schema-v2 file tables: identifiers, states, digests, sizes, offsets and
timestamps.  File bytes, names, paths, ICE candidates, addresses and
``TransferIntegrityEvidence`` are never written.  No signaling, STUN, TURN,
byte transport or network listener is implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from ...application.file_sharing.contracts import (
    ByteRange,
    ChunkDigest,
    DirectTransferRequest,
    FileGrantState,
    FileManifest,
    FileRecipientGrant,
    FileShareAuditEvent,
    OwnerFileAvailability,
    TransferApproval,
    TransferRecord,
    TransferState,
    TERMINAL_TRANSFER_STATES,
)
from .sqlite_store import SqliteSocialConnection, _dt, _dt_or_none, _ts, _ts_or_none


# The transition matrices mirror the development adapter exactly.
ALLOWED_TRANSFER_TRANSITIONS = frozenset(
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

ALLOWED_GRANT_TRANSITIONS = frozenset(
    {
        (FileGrantState.OFFERED, FileGrantState.CONSENTED),
        (FileGrantState.OFFERED, FileGrantState.DECLINED),
        (FileGrantState.OFFERED, FileGrantState.REVOKED),
        (FileGrantState.OFFERED, FileGrantState.EXPIRED),
        (FileGrantState.CONSENTED, FileGrantState.REVOKED),
        (FileGrantState.CONSENTED, FileGrantState.EXPIRED),
    }
)

_TERMINAL_STATE_VALUES = tuple(sorted(state.value for state in TERMINAL_TRANSFER_STATES))
_TERMINAL_PLACEHOLDERS = ", ".join("?" for _ in _TERMINAL_STATE_VALUES)


@dataclass(slots=True)
class SqliteFileShareStore:
    """Implements the manifest, grant, availability, transfer and audit ports."""

    db: SqliteSocialConnection

    # Internal binding checks ---------------------------------------------
    def _device_account(self, organization_id: str, device_id: str) -> str | None:
        row = self.db.execute(
            "SELECT account_id FROM social_devices "
            "WHERE organization_id = ? AND device_id = ?",
            (organization_id, device_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def _manifest_owner(
        self, organization_id: str, manifest_id: str
    ) -> tuple[str, str, bool] | None:
        row = self.db.execute(
            "SELECT owner_account_id, owner_device_id, revoked_at IS NOT NULL "
            "FROM social_file_manifests WHERE organization_id = ? AND manifest_id = ?",
            (organization_id, manifest_id),
        ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]), bool(row[2]))

    # Manifest port -------------------------------------------------------
    def _chunks(self, organization_id: str, manifest_id: str) -> tuple[ChunkDigest, ...]:
        rows = self.db.execute(
            "SELECT chunk_index, chunk_offset, chunk_bytes, sha256 "
            "FROM social_file_manifest_chunks "
            "WHERE organization_id = ? AND manifest_id = ? ORDER BY chunk_index",
            (organization_id, manifest_id),
        ).fetchall()
        return tuple(
            ChunkDigest(index=row[0], offset=row[1], size=row[2], sha256=row[3])
            for row in rows
        )

    def _manifest_row(self, row: tuple[object, ...]) -> FileManifest:
        organization_id, manifest_id = str(row[0]), str(row[1])
        return FileManifest(
            manifest_id=manifest_id,
            organization_id=organization_id,
            owner_account_id=row[2],
            owner_device_id=row[3],
            content_kind=row[4],
            byte_size=row[5],
            chunk_size=row[6],
            whole_file_sha256=row[7],
            merkle_root_sha256=row[8],
            chunks=self._chunks(organization_id, manifest_id),
            created_at=_dt(row[9]),
            expires_at=_dt(row[10]),
        )

    _MANIFEST_COLUMNS = (
        "organization_id, manifest_id, owner_account_id, owner_device_id, "
        "content_kind, byte_size, chunk_size, whole_file_sha256, "
        "merkle_root_sha256, created_at, expires_at"
    )

    def manifest(self, organization_id: str, manifest_id: str) -> FileManifest | None:
        with self.db.lock:
            row = self.db.execute(
                f"SELECT {self._MANIFEST_COLUMNS} FROM social_file_manifests "
                "WHERE organization_id = ? AND manifest_id = ?",
                (organization_id, manifest_id),
            ).fetchone()
            if row is None:
                return None
            # Reconstruction re-validates chunk canonicality and the Merkle
            # root, so a tampered chunk row fails closed instead of loading.
            return self._manifest_row(row)

    def save_manifest(self, manifest: FileManifest) -> FileManifest:
        with self.db:
            existing = self.manifest(manifest.organization_id, manifest.manifest_id)
            if existing is not None:
                if existing == manifest:
                    return existing
                raise ValueError("immutable file manifest conflict")
            owner_account = self._device_account(
                manifest.organization_id, manifest.owner_device_id
            )
            if owner_account is None or owner_account != manifest.owner_account_id:
                raise ValueError("file manifest owner device is not bound to its owner")
            try:
                self.db.execute(
                    "INSERT INTO social_file_manifests VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,NULL,0,0)",
                    (
                        manifest.organization_id,
                        manifest.manifest_id,
                        manifest.owner_account_id,
                        manifest.owner_device_id,
                        manifest.content_kind.value,
                        manifest.byte_size,
                        manifest.chunk_size,
                        manifest.whole_file_sha256,
                        manifest.merkle_root_sha256,
                        _ts(manifest.created_at),
                        _ts(manifest.expires_at),
                    ),
                )
                for chunk in manifest.chunks:
                    self.db.execute(
                        "INSERT INTO social_file_manifest_chunks VALUES (?,?,?,?,?,?)",
                        (
                            manifest.organization_id,
                            manifest.manifest_id,
                            chunk.index,
                            chunk.offset,
                            chunk.size,
                            chunk.sha256,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("file manifest rows are not bound or replayed") from error
            return manifest

    def active_manifests_for_owner(
        self, organization_id: str, owner_account_id: str, *, now: datetime
    ) -> tuple[FileManifest, ...]:
        with self.db.lock:
            rows = self.db.execute(
                f"SELECT {self._MANIFEST_COLUMNS} FROM social_file_manifests "
                "WHERE organization_id = ? AND owner_account_id = ? "
                "AND revoked_at IS NULL AND expires_at > ? ORDER BY manifest_id",
                (organization_id, owner_account_id, _ts(now)),
            ).fetchall()
            return tuple(self._manifest_row(row) for row in rows)

    def revoke_manifest(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> bool:
        with self.db:
            changed = self.db.execute(
                "UPDATE social_file_manifests SET revoked_at = ? "
                "WHERE organization_id = ? AND manifest_id = ? AND revoked_at IS NULL",
                (_ts(now), organization_id, manifest_id),
            ).rowcount
            if changed == 0:
                return False
            self.db.execute(
                "DELETE FROM social_file_availability "
                "WHERE organization_id = ? AND manifest_id = ?",
                (organization_id, manifest_id),
            )
            return True

    def is_manifest_revoked(self, organization_id: str, manifest_id: str) -> bool:
        owner = self._manifest_owner(organization_id, manifest_id)
        return owner is not None and owner[2]

    # Grant port ----------------------------------------------------------
    _GRANT_COLUMNS = (
        "organization_id, grant_id, manifest_id, owner_account_id, "
        "recipient_account_id, state, offered_at, expires_at, decided_at, "
        "revoked_at, explicit_recipient_consent"
    )

    def _grant_row(self, row: tuple[object, ...]) -> FileRecipientGrant:
        return FileRecipientGrant(
            organization_id=row[0],
            grant_id=row[1],
            manifest_id=row[2],
            owner_account_id=row[3],
            recipient_account_id=row[4],
            state=FileGrantState(row[5]),
            offered_at=_dt(row[6]),
            expires_at=_dt(row[7]),
            decided_at=_dt_or_none(row[8]),
            revoked_at=_dt_or_none(row[9]),
            explicit_recipient_consent=bool(row[10]),
        )

    def grant(self, organization_id: str, grant_id: str) -> FileRecipientGrant | None:
        row = self.db.execute(
            f"SELECT {self._GRANT_COLUMNS} FROM social_file_grants "
            "WHERE organization_id = ? AND grant_id = ?",
            (organization_id, grant_id),
        ).fetchone()
        return None if row is None else self._grant_row(row)

    def grants_for_manifest(
        self, organization_id: str, manifest_id: str
    ) -> tuple[FileRecipientGrant, ...]:
        rows = self.db.execute(
            f"SELECT {self._GRANT_COLUMNS} FROM social_file_grants "
            "WHERE organization_id = ? AND manifest_id = ? ORDER BY grant_id",
            (organization_id, manifest_id),
        ).fetchall()
        return tuple(self._grant_row(row) for row in rows)

    def save_grant(self, grant: FileRecipientGrant) -> FileRecipientGrant:
        with self.db:
            existing = self.grant(grant.organization_id, grant.grant_id)
            if existing is not None:
                if existing == grant:
                    return existing
                if (
                    existing.manifest_id != grant.manifest_id
                    or existing.owner_account_id != grant.owner_account_id
                    or existing.recipient_account_id != grant.recipient_account_id
                    or existing.offered_at != grant.offered_at
                    or (existing.state, grant.state) not in ALLOWED_GRANT_TRANSITIONS
                ):
                    raise ValueError("invalid file grant transition")
                self.db.execute(
                    "UPDATE social_file_grants SET state = ?, expires_at = ?, "
                    "decided_at = ?, revoked_at = ?, explicit_recipient_consent = ? "
                    "WHERE organization_id = ? AND grant_id = ?",
                    (
                        grant.state.value,
                        _ts(grant.expires_at),
                        _ts_or_none(grant.decided_at),
                        _ts_or_none(grant.revoked_at),
                        int(grant.explicit_recipient_consent),
                        grant.organization_id,
                        grant.grant_id,
                    ),
                )
                return grant
            owner = self._manifest_owner(grant.organization_id, grant.manifest_id)
            if owner is None or owner[0] != grant.owner_account_id:
                raise ValueError("file grant is not bound to its manifest owner")
            try:
                self.db.execute(
                    "INSERT INTO social_file_grants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        grant.organization_id,
                        grant.grant_id,
                        grant.manifest_id,
                        grant.owner_account_id,
                        grant.recipient_account_id,
                        grant.state.value,
                        _ts(grant.offered_at),
                        _ts(grant.expires_at),
                        _ts_or_none(grant.decided_at),
                        _ts_or_none(grant.revoked_at),
                        int(grant.explicit_recipient_consent),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("file grant rows are not bound or replayed") from error
            return grant

    def revoke_manifest_grants(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int:
        with self.db:
            return self.db.execute(
                "UPDATE social_file_grants SET state = 'revoked', revoked_at = ?, "
                "explicit_recipient_consent = 0 "
                "WHERE organization_id = ? AND manifest_id = ? "
                "AND state IN ('offered', 'consented')",
                (_ts(now), organization_id, manifest_id),
            ).rowcount

    # Availability port ---------------------------------------------------
    def save_availability(
        self, availability: OwnerFileAvailability
    ) -> OwnerFileAvailability:
        with self.db:
            owner = self._manifest_owner(
                availability.organization_id, availability.manifest_id
            )
            if (
                owner is None
                or owner[2]
                or owner[0] != availability.owner_account_id
                or owner[1] != availability.owner_device_id
            ):
                raise ValueError("file availability is not bound to a live manifest owner")
            self.db.execute(
                "INSERT OR REPLACE INTO social_file_availability VALUES (?,?,?,?,?,?,?,1)",
                (
                    availability.organization_id,
                    availability.manifest_id,
                    availability.owner_account_id,
                    availability.owner_device_id,
                    availability.state.value,
                    _ts(availability.observed_at),
                    _ts(availability.expires_at),
                ),
            )
            return availability

    def availability(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> OwnerFileAvailability | None:
        with self.db:
            row = self.db.execute(
                "SELECT owner_account_id, owner_device_id, state, observed_at, expires_at "
                "FROM social_file_availability WHERE organization_id = ? AND manifest_id = ?",
                (organization_id, manifest_id),
            ).fetchone()
            if row is None:
                return None
            availability = OwnerFileAvailability(
                organization_id=organization_id,
                manifest_id=manifest_id,
                owner_account_id=row[0],
                owner_device_id=row[1],
                state=row[2],
                observed_at=_dt(row[3]),
                expires_at=_dt(row[4]),
            )
            if availability.expires_at <= now or self.is_manifest_revoked(
                organization_id, manifest_id
            ):
                self.db.execute(
                    "DELETE FROM social_file_availability "
                    "WHERE organization_id = ? AND manifest_id = ?",
                    (organization_id, manifest_id),
                )
                return None
            return availability

    # Transfer port -------------------------------------------------------
    _TRANSFER_COLUMNS = (
        "organization_id, transfer_id, manifest_id, grant_id, requester_account_id, "
        "requester_device_id, created_at, expires_at, state, failure_reason, "
        "owner_approved_at, changed_at, received_bytes, completed_whole_file_sha256"
    )

    _TRANSFER_COLUMNS_T = ", ".join(
        "t." + column.strip() for column in _TRANSFER_COLUMNS.split(",")
    )

    def _ranges(self, organization_id: str, transfer_id: str) -> tuple[ByteRange, ...]:
        rows = self.db.execute(
            "SELECT range_start, range_end_exclusive FROM social_file_transfer_ranges "
            "WHERE organization_id = ? AND transfer_id = ? ORDER BY range_index",
            (organization_id, transfer_id),
        ).fetchall()
        return tuple(ByteRange(start=row[0], end_exclusive=row[1]) for row in rows)

    def _transfer_row(self, row: tuple[object, ...]) -> TransferRecord:
        organization_id, transfer_id = str(row[0]), str(row[1])
        request = DirectTransferRequest(
            organization_id=organization_id,
            transfer_id=transfer_id,
            manifest_id=row[2],
            grant_id=row[3],
            requester_account_id=row[4],
            requester_device_id=row[5],
            ranges=self._ranges(organization_id, transfer_id),
            created_at=_dt(row[6]),
            expires_at=_dt(row[7]),
        )
        return TransferRecord(
            request=request,
            state=TransferState(row[8]),
            failure_reason=row[9],
            owner_approved_at=_dt_or_none(row[10]),
            changed_at=_dt(row[11]),
            received_bytes=row[12],
            completed_whole_file_sha256=row[13],
        )

    def transfer(self, organization_id: str, transfer_id: str) -> TransferRecord | None:
        with self.db.lock:
            row = self.db.execute(
                f"SELECT {self._TRANSFER_COLUMNS} FROM social_file_transfers "
                "WHERE organization_id = ? AND transfer_id = ?",
                (organization_id, transfer_id),
            ).fetchone()
            return None if row is None else self._transfer_row(row)

    def save_transfer(self, transfer: TransferRecord) -> TransferRecord:
        request = transfer.request
        with self.db:
            existing = self.transfer(request.organization_id, request.transfer_id)
            if existing is not None:
                if existing == transfer:
                    return existing
                if existing.request != request:
                    raise ValueError("immutable file transfer request conflict")
                if existing.state in TERMINAL_TRANSFER_STATES:
                    raise ValueError("terminal file transfer cannot transition")
                transition = (existing.state, transfer.state)
                if (
                    transition not in ALLOWED_TRANSFER_TRANSITIONS
                    and transfer.state
                    not in {TransferState.CANCELLED, TransferState.REVOKED}
                ):
                    raise ValueError("invalid file transfer state transition")
                if (
                    existing.owner_approved_at is not None
                    and transfer.owner_approved_at != existing.owner_approved_at
                ):
                    raise ValueError("file transfer approval time is immutable")
                if transfer.received_bytes < existing.received_bytes:
                    raise ValueError("received bytes cannot be recalled")
                self.db.execute(
                    "UPDATE social_file_transfers SET state = ?, failure_reason = ?, "
                    "owner_approved_at = ?, changed_at = ?, received_bytes = ?, "
                    "completed_whole_file_sha256 = ? "
                    "WHERE organization_id = ? AND transfer_id = ?",
                    (
                        transfer.state.value,
                        None if transfer.failure_reason is None else transfer.failure_reason.value,
                        _ts_or_none(transfer.owner_approved_at),
                        _ts(transfer.changed_at),
                        transfer.received_bytes,
                        transfer.completed_whole_file_sha256,
                        request.organization_id,
                        request.transfer_id,
                    ),
                )
                return transfer
            grant = self.grant(request.organization_id, request.grant_id)
            if (
                grant is None
                or grant.manifest_id != request.manifest_id
                or grant.recipient_account_id != request.requester_account_id
            ):
                raise ValueError("file transfer is not bound to its grant")
            requester = self._device_account(
                request.organization_id, request.requester_device_id
            )
            if requester is None or requester != request.requester_account_id:
                raise ValueError("file transfer requester device is not bound")
            try:
                self.db.execute(
                    "INSERT INTO social_file_transfers VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0)",
                    (
                        request.organization_id,
                        request.transfer_id,
                        request.manifest_id,
                        request.grant_id,
                        request.requester_account_id,
                        request.requester_device_id,
                        _ts(request.created_at),
                        _ts(request.expires_at),
                        transfer.state.value,
                        None if transfer.failure_reason is None else transfer.failure_reason.value,
                        _ts_or_none(transfer.owner_approved_at),
                        _ts(transfer.changed_at),
                        transfer.received_bytes,
                        transfer.completed_whole_file_sha256,
                    ),
                )
                for index, selected in enumerate(request.ranges):
                    self.db.execute(
                        "INSERT INTO social_file_transfer_ranges VALUES (?,?,?,?,?)",
                        (
                            request.organization_id,
                            request.transfer_id,
                            index,
                            selected.start,
                            selected.end_exclusive,
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("file transfer rows are not bound or replayed") from error
            return transfer

    def active_transfers_for_owner(
        self, organization_id: str, owner_account_id: str
    ) -> tuple[TransferRecord, ...]:
        with self.db.lock:
            rows = self.db.execute(
                f"SELECT {self._TRANSFER_COLUMNS_T} FROM social_file_transfers AS t "
                "JOIN social_file_manifests AS m "
                "ON m.organization_id = t.organization_id AND m.manifest_id = t.manifest_id "
                "WHERE t.organization_id = ? AND m.owner_account_id = ? "
                f"AND t.state NOT IN ({_TERMINAL_PLACEHOLDERS}) ORDER BY t.transfer_id",
                (organization_id, owner_account_id, *_TERMINAL_STATE_VALUES),
            ).fetchall()
            return tuple(self._transfer_row(row) for row in rows)

    def approval(
        self, organization_id: str, transfer_id: str
    ) -> TransferApproval | None:
        row = self.db.execute(
            "SELECT manifest_id, owner_account_id, owner_device_id, approved_at "
            "FROM social_file_transfer_approvals "
            "WHERE organization_id = ? AND transfer_id = ?",
            (organization_id, transfer_id),
        ).fetchone()
        if row is None:
            return None
        return TransferApproval(
            organization_id=organization_id,
            transfer_id=transfer_id,
            manifest_id=row[0],
            owner_account_id=row[1],
            owner_device_id=row[2],
            approved_at=_dt(row[3]),
        )

    def save_approval(self, approval: TransferApproval) -> TransferApproval:
        with self.db:
            transfer = self.transfer(approval.organization_id, approval.transfer_id)
            if transfer is None or transfer.request.manifest_id != approval.manifest_id:
                raise ValueError("file transfer approval is not bound")
            owner = self._manifest_owner(approval.organization_id, approval.manifest_id)
            if (
                owner is None
                or owner[0] != approval.owner_account_id
                or owner[1] != approval.owner_device_id
            ):
                raise ValueError("file transfer approval is not bound to the manifest owner")
            existing = self.approval(approval.organization_id, approval.transfer_id)
            if existing is not None:
                if existing == approval:
                    return existing
                raise ValueError("file transfer approval conflict")
            try:
                self.db.execute(
                    "INSERT INTO social_file_transfer_approvals VALUES (?,?,?,?,?,?)",
                    (
                        approval.organization_id,
                        approval.transfer_id,
                        approval.manifest_id,
                        approval.owner_account_id,
                        approval.owner_device_id,
                        _ts(approval.approved_at),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("file transfer approval is not bound") from error
            return approval

    def _revoke_transfers_where(
        self, column: str, organization_id: str, identifier: str, now: datetime
    ) -> int:
        with self.db:
            return self.db.execute(
                "UPDATE social_file_transfers SET state = 'revoked', changed_at = ? "
                f"WHERE organization_id = ? AND {column} = ? "
                f"AND state NOT IN ({_TERMINAL_PLACEHOLDERS})",
                (_ts(now), organization_id, identifier, *_TERMINAL_STATE_VALUES),
            ).rowcount

    def revoke_manifest_transfers(
        self, organization_id: str, manifest_id: str, *, now: datetime
    ) -> int:
        return self._revoke_transfers_where("manifest_id", organization_id, manifest_id, now)

    def revoke_grant_transfers(
        self, organization_id: str, grant_id: str, *, now: datetime
    ) -> int:
        return self._revoke_transfers_where("grant_id", organization_id, grant_id, now)

    # Audit port ----------------------------------------------------------
    def append(self, event: FileShareAuditEvent) -> FileShareAuditEvent:
        with self.db:
            # Audit identifiers are server-issued and globally unique; the same
            # identifier under another tenant is a replay, not a new event.
            replayed = self.db.execute(
                "SELECT 1 FROM social_file_audit_events WHERE audit_id = ?",
                (event.audit_id,),
            ).fetchone()
            if replayed is not None:
                raise ValueError("file audit event replayed")
            try:
                self.db.execute(
                    "INSERT INTO social_file_audit_events (organization_id, audit_id, "
                    "actor_account_id, actor_device_id, manifest_id, transfer_id, "
                    "action, occurred_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        event.organization_id,
                        event.audit_id,
                        event.actor_account_id,
                        event.actor_device_id,
                        event.manifest_id,
                        event.transfer_id,
                        event.action.value,
                        _ts(event.occurred_at),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("file audit event replayed") from error
            return event

    def recent_audit(
        self, organization_id: str, *, limit: int
    ) -> tuple[FileShareAuditEvent, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("file audit limit is invalid")
        rows = self.db.execute(
            "SELECT organization_id, audit_id, actor_account_id, actor_device_id, "
            "manifest_id, transfer_id, action, occurred_at "
            "FROM social_file_audit_events WHERE organization_id = ? "
            "ORDER BY sequence DESC LIMIT ?",
            (organization_id, limit),
        ).fetchall()
        return tuple(
            FileShareAuditEvent(
                organization_id=row[0],
                audit_id=row[1],
                actor_account_id=row[2],
                actor_device_id=row[3],
                manifest_id=row[4],
                transfer_id=row[5],
                action=row[6],
                occurred_at=_dt(row[7]),
            )
            for row in rows
        )


__all__ = [
    "ALLOWED_GRANT_TRANSITIONS",
    "ALLOWED_TRANSFER_TRANSITIONS",
    "SqliteFileShareStore",
]
