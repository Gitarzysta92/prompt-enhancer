"""Restart, rollback, tamper and revocation tests for the SQLite file store.

Every identity here is a reserved synthetic value.  The direct-signaling stub
lives only in this test module; the composed foundation still fails closed and
no signaling, STUN/TURN or byte transport exists in the adapters.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import inspect
from pathlib import Path
import sqlite3

import pytest

from prompt_enhancer.application.file_sharing import (
    ByteRange,
    FileGrantState,
    FileShareAuditAction,
    FileShareAuditEvent,
    FileShareAuthorizationError,
    FileShareConflictError,
    FileShareReasonCode,
    OwnerFileAvailability,
    PeerAvailabilityState,
    TransferApproval,
    TransferFailureReason,
    TransferIntegrityEvidence,
    TransferRecord,
    TransferState,
)
from prompt_enhancer.infrastructure import file_sharing as file_sharing_infrastructure
from prompt_enhancer.infrastructure.file_sharing import (
    FailClosedDirectSignaling,
    create_sqlite_file_sharing_foundation,
)
from prompt_enhancer.infrastructure.file_sharing import sqlite as file_sqlite_module
from prompt_enhancer.infrastructure.social import (
    SocialSqliteDatabase,
    SqliteFileShareStore,
    create_sqlite_social_foundation,
)
from prompt_enhancer.infrastructure.social import sqlite_file_store as store_module
from prompt_enhancer.infrastructure.social.sqlite_schema import FORBIDDEN_COLUMN_NAMES

from test_direct_file_sharing_service import (
    MANIFEST,
    SyntheticDirectSignaling,
    chunks,
    manifest,
)
from test_social_service import (
    ALICE,
    ALICE_DEVICE,
    BOB,
    BOB_DEVICE,
    Clock,
    NOW,
    ORG,
    OTHER_ORG,
    provision,
)

CANARIES = (
    b"canary-file-name.txt",
    b"canary-file-plaintext-bytes",
    b"203.0.113.7",
    b"candidate:",
    b"/home/example-user/",
)
FILE_TABLES = (
    "social_file_manifests",
    "social_file_manifest_chunks",
    "social_file_grants",
    "social_file_availability",
    "social_file_transfers",
    "social_file_transfer_ranges",
    "social_file_transfer_approvals",
    "social_file_audit_events",
)


def open_foundations(tmp_path: Path, clock: Clock, *, signaling=None):
    social = create_sqlite_social_foundation(SocialSqliteDatabase.under(tmp_path), clock)
    files = create_sqlite_file_sharing_foundation(social, clock)
    service = files.service
    if signaling is not None:
        service = replace(service, signaling=signaling)
    return social, files, service


def bootstrap(tmp_path: Path, clock: Clock, *, signaling=None):
    social, files, service = open_foundations(tmp_path, clock, signaling=signaling)
    alice = provision(social.store, ALICE, ALICE_DEVICE)
    bob = provision(social.store, BOB, BOB_DEVICE)
    request = social.service.request_friend(
        alice, BOB, expires_at=NOW + timedelta(days=1)
    )
    social.service.decide_friend_request(bob, request.request_id, accept=True)
    return social, files, service, alice, bob


def consented_grant(service, alice, bob):
    service.register_manifest(alice, manifest())
    offered = service.offer(alice, MANIFEST, BOB, expires_at=NOW + timedelta(hours=4))
    return service.decide_grant(bob, offered.grant_id, consent=True)


def availability(*, expires_in=timedelta(minutes=1)) -> OwnerFileAvailability:
    return OwnerFileAvailability(
        organization_id=ORG,
        manifest_id=MANIFEST,
        owner_account_id=ALICE,
        owner_device_id=ALICE_DEVICE,
        state=PeerAvailabilityState.ONLINE,
        observed_at=NOW,
        expires_at=NOW + expires_in,
    )


def evidence(transfer_id: str) -> TransferIntegrityEvidence:
    return TransferIntegrityEvidence(
        transfer_id=transfer_id,
        manifest_id=MANIFEST,
        received_bytes=manifest().byte_size,
        whole_file_sha256=manifest().whole_file_sha256,
        chunk_sha256=tuple(chunk.sha256 for chunk in chunks()),
        verified_at=NOW,
    )


def raw_rows(path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def raw_execute(path: Path, sql: str, params: tuple = ()) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(sql, params)
        connection.commit()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Lifecycle across restarts


def test_metadata_lifecycle_survives_restarts_and_persists_ranges_and_approval(
    tmp_path: Path,
) -> None:
    clock = Clock()
    social, _, service, alice, bob = bootstrap(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    social.close()

    social, files, service = open_foundations(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    ranges = (
        ByteRange(start=0, end_exclusive=10),
        ByteRange(start=10, end_exclusive=65_536),
        ByteRange(start=65_536, end_exclusive=manifest().byte_size),
    )
    transfer = service.request_transfer(
        bob, grant.grant_id, ranges=ranges, expires_at=NOW + timedelta(hours=1)
    )
    assert transfer.state is TransferState.WAITING_OWNER_APPROVAL
    ready = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert ready.state is TransferState.DIRECT_READY
    social.close()

    social, files, service = open_foundations(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    reloaded = files.store.transfer(ORG, transfer.request.transfer_id)
    assert reloaded == ready
    assert reloaded.request.ranges == ranges
    approval = files.store.approval(ORG, transfer.request.transfer_id)
    assert approval is not None
    assert (
        approval.manifest_id,
        approval.owner_account_id,
        approval.owner_device_id,
        approval.approved_at,
    ) == (MANIFEST, ALICE, ALICE_DEVICE, ready.owner_approved_at)
    assert files.store.manifest(ORG, MANIFEST) == manifest()
    completed = service.complete_transfer(bob, evidence(transfer.request.transfer_id))
    assert completed.state is TransferState.COMPLETED
    assert completed.remote_recall_guaranteed is False
    social.close()

    social, files, _ = open_foundations(tmp_path, clock)
    persisted = files.store.transfer(ORG, transfer.request.transfer_id)
    assert persisted == completed
    actions = [event.action for event in files.store.recent_audit(ORG, limit=100)]
    assert FileShareAuditAction.TRANSFER_COMPLETED in actions
    assert FileShareAuditAction.MANIFEST_REGISTERED in actions
    # Audit rows are content-free: only identifiers, an action and a timestamp.
    assert set(FileShareAuditEvent.model_fields) == {
        "organization_id",
        "audit_id",
        "actor_account_id",
        "actor_device_id",
        "manifest_id",
        "transfer_id",
        "action",
        "occurred_at",
    }
    # Cross-tenant reads see nothing.
    assert files.store.transfer(OTHER_ORG, transfer.request.transfer_id) is None
    assert files.store.manifest(OTHER_ORG, MANIFEST) is None
    assert files.store.grant(OTHER_ORG, grant.grant_id) is None
    assert files.store.approval(OTHER_ORG, transfer.request.transfer_id) is None
    assert files.store.recent_audit(OTHER_ORG, limit=10) == ()
    social.close()


def test_composed_foundation_signaling_fails_closed_without_relay(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(tmp_path, clock)
    assert isinstance(files.service.signaling, FailClosedDirectSignaling)
    assert files.service.signaling.available is False
    assert files.service.signaling.relay_supported is False
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    failed = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert failed.state is TransferState.FAILED
    assert failed.failure_reason is TransferFailureReason.SIGNALING_UNAVAILABLE
    social.close()
    social, files, _ = open_foundations(tmp_path, clock)
    assert files.store.transfer(ORG, transfer.request.transfer_id) == failed
    social.close()


# ---------------------------------------------------------------------------
# Revocation


def test_manifest_revocation_is_atomic_and_survives_reopen(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    done = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    service.approve_and_negotiate(alice, done.request.transfer_id)
    completed = service.complete_transfer(bob, evidence(done.request.transfer_id))
    assert completed.state is TransferState.COMPLETED
    pending = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    receipt = service.revoke_manifest(alice, MANIFEST)
    assert receipt.revoked_grants == 1
    assert receipt.cancelled_active_transfers == 1
    assert receipt.already_received_bytes_recalled is False
    social.close()

    social, files, service = open_foundations(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    assert files.store.is_manifest_revoked(ORG, MANIFEST) is True
    assert files.store.availability(ORG, MANIFEST, now=NOW) is None
    assert raw_rows(
        social.database.path,
        "SELECT count(*) FROM social_file_availability WHERE manifest_id = ?",
        (MANIFEST,),
    ) == [(0,)]
    revoked_grant = files.store.grant(ORG, grant.grant_id)
    assert revoked_grant.state is FileGrantState.REVOKED
    assert revoked_grant.explicit_recipient_consent is False
    revoked_transfer = files.store.transfer(ORG, pending.request.transfer_id)
    assert revoked_transfer.state is TransferState.REVOKED
    # Completed bytes are never recalled or rewritten.
    still_completed = files.store.transfer(ORG, done.request.transfer_id)
    assert still_completed.state is TransferState.COMPLETED
    assert still_completed.received_bytes == manifest().byte_size
    assert files.store.active_manifests_for_owner(ORG, ALICE, now=NOW) == ()
    with pytest.raises(FileShareAuthorizationError) as denied:
        service.publish_availability(alice, availability())
    assert denied.value.reason is FileShareReasonCode.MANIFEST_UNAVAILABLE
    with pytest.raises(FileShareAuthorizationError):
        service.request_transfer(
            bob,
            grant.grant_id,
            ranges=(ByteRange(start=0, end_exclusive=1),),
            expires_at=NOW + timedelta(hours=1),
        )
    # A revoked, terminal transfer cannot be resurrected by any adapter write.
    with pytest.raises(ValueError):
        files.store.save_transfer(
            TransferRecord.model_validate(
                {
                    **revoked_transfer.model_dump(mode="python"),
                    "state": TransferState.WAITING_OWNER_APPROVAL,
                }
            )
        )
    # The store also refuses availability for a revoked manifest directly.
    with pytest.raises(ValueError):
        files.store.save_availability(availability())
    social.close()


def test_grant_revocation_revokes_incomplete_transfers_atomically(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(tmp_path, clock)
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    revoked = service.revoke_grant(alice, grant.grant_id)
    assert revoked.state is FileGrantState.REVOKED
    social.close()
    social, files, _ = open_foundations(tmp_path, clock)
    assert files.store.transfer(ORG, transfer.request.transfer_id).state is (
        TransferState.REVOKED
    )
    assert files.store.active_transfers_for_owner(ORG, ALICE) == ()
    social.close()


def test_revoked_requester_device_never_reaches_direct_ready_after_reopen(
    tmp_path: Path,
) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=1),),
        expires_at=NOW + timedelta(hours=1),
    )
    social.store.revoke_device(ORG, BOB_DEVICE, now=NOW)
    social.close()
    social, files, service = open_foundations(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    # The revoked requester device is rejected before any signaling runs, and
    # the persisted transfer never advances past owner approval.
    with pytest.raises(FileShareConflictError) as conflict:
        service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert conflict.value.reason is FileShareReasonCode.STATE_CONFLICT
    stored = files.store.transfer(ORG, transfer.request.transfer_id)
    assert stored.state is TransferState.WAITING_OWNER_APPROVAL
    assert stored.owner_approved_at is None
    assert files.store.approval(ORG, transfer.request.transfer_id) is None
    with pytest.raises(FileShareAuthorizationError) as denied:
        service.complete_transfer(bob, evidence(transfer.request.transfer_id))
    assert denied.value.reason is FileShareReasonCode.DEVICE_INACTIVE
    social.close()


def test_block_precedes_grant_and_matches_unknown_recipient(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(tmp_path, clock)
    service.register_manifest(alice, manifest())
    social.service.block_account(bob, ALICE)
    with pytest.raises(FileShareAuthorizationError) as blocked:
        service.offer(alice, MANIFEST, BOB, expires_at=NOW + timedelta(hours=1))
    with pytest.raises(FileShareAuthorizationError) as unknown:
        service.offer(
            alice, MANIFEST, "soc_" + "8" * 64, expires_at=NOW + timedelta(hours=1)
        )
    assert blocked.value.reason is unknown.value.reason
    assert blocked.value.reason is FileShareReasonCode.BLOCKED_OR_UNAVAILABLE
    assert files.store.grants_for_manifest(ORG, MANIFEST) == ()
    social.close()


# ---------------------------------------------------------------------------
# Immutability, transitions and binding checks


def test_manifest_is_immutable_idempotent_and_tamper_evident(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, _ = bootstrap(tmp_path, clock)
    service.register_manifest(alice, manifest())
    assert service.register_manifest(alice, manifest()) == manifest()
    assert files.store.save_manifest(manifest()) == manifest()
    changed = manifest().model_copy(update={"whole_file_sha256": "9" * 64})
    with pytest.raises(FileShareConflictError) as replayed:
        service.register_manifest(alice, changed)
    assert replayed.value.reason is FileShareReasonCode.REQUEST_REPLAYED
    with pytest.raises(ValueError):
        files.store.save_manifest(changed)
    # An owner device from another tenant/account cannot anchor a manifest.
    foreign = manifest().model_copy(
        update={"manifest_id": "shr_" + "2" * 64, "owner_device_id": BOB_DEVICE}
    )
    with pytest.raises(ValueError):
        files.store.save_manifest(foreign)
    assert files.store.manifest(ORG, "shr_" + "2" * 64) is None
    social.close()

    raw_execute(
        social.database.path,
        "UPDATE social_file_manifest_chunks SET sha256 = ? "
        "WHERE manifest_id = ? AND chunk_index = 1",
        ("f" * 64, MANIFEST),
    )
    social, files, _ = open_foundations(tmp_path, clock)
    with pytest.raises(ValueError):
        files.store.manifest(ORG, MANIFEST)
    social.close()


def test_transfer_transitions_and_approval_binding_fail_closed(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    store: SqliteFileShareStore = files.store

    def moved(record: TransferRecord, **updates) -> TransferRecord:
        return TransferRecord.model_validate(
            {**record.model_dump(mode="python"), **updates}
        )

    # Pre-approval state cannot skip to a post-approval state.
    with pytest.raises(ValueError):
        store.save_transfer(
            moved(transfer, state=TransferState.DIRECT_READY, owner_approved_at=NOW)
        )
    # Approval must be bound to the transfer's manifest, owner and device.
    with pytest.raises(ValueError):
        store.save_approval(
            TransferApproval(
                organization_id=ORG,
                transfer_id=transfer.request.transfer_id,
                manifest_id=MANIFEST,
                owner_account_id=BOB,
                owner_device_id=BOB_DEVICE,
                approved_at=NOW,
            )
        )
    with pytest.raises(ValueError):
        store.save_approval(
            TransferApproval(
                organization_id=ORG,
                transfer_id="shr_" + "3" * 64,
                manifest_id=MANIFEST,
                owner_account_id=ALICE,
                owner_device_id=ALICE_DEVICE,
                approved_at=NOW,
            )
        )
    ready = service.approve_and_negotiate(alice, transfer.request.transfer_id)
    assert ready.state is TransferState.DIRECT_READY
    approval = store.approval(ORG, transfer.request.transfer_id)
    assert store.save_approval(approval) == approval
    with pytest.raises(ValueError):
        store.save_approval(approval.model_copy(update={"approved_at": NOW + timedelta(seconds=5)}))
    # Immutable request identity.
    with pytest.raises(ValueError):
        store.save_transfer(
            moved(
                ready,
                request={
                    **ready.request.model_dump(mode="python"),
                    "ranges": (ByteRange(start=0, end_exclusive=1),),
                },
            )
        )
    # Received bytes never regress and approval time is immutable.
    transferring = store.save_transfer(
        moved(ready, state=TransferState.TRANSFERRING, received_bytes=100)
    )
    with pytest.raises(ValueError):
        store.save_transfer(moved(transferring, received_bytes=50))
    with pytest.raises(ValueError):
        store.save_transfer(
            moved(transferring, owner_approved_at=NOW + timedelta(seconds=1), changed_at=NOW + timedelta(seconds=1))
        )
    completed = service.complete_transfer(bob, evidence(transfer.request.transfer_id))
    assert completed.state is TransferState.COMPLETED
    for terminal_target in (
        TransferState.TRANSFERRING,
        TransferState.CANCELLED,
        TransferState.REVOKED,
    ):
        with pytest.raises(ValueError):
            store.save_transfer(
                moved(
                    completed,
                    state=terminal_target,
                    completed_whole_file_sha256=None,
                )
            )
    assert store.revoke_manifest_transfers(ORG, MANIFEST, now=NOW) == 0
    assert store.transfer(ORG, transfer.request.transfer_id) == completed
    social.close()


def test_grant_transitions_and_ordering_match_development_adapter(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(tmp_path, clock)
    service.register_manifest(alice, manifest())
    offered = service.offer(alice, MANIFEST, BOB, expires_at=NOW + timedelta(hours=4))
    store: SqliteFileShareStore = files.store
    with pytest.raises(ValueError):
        store.save_grant(offered.model_copy(update={"recipient_account_id": ALICE, "owner_account_id": BOB}))
    with pytest.raises(ValueError):
        store.save_grant(offered.model_copy(update={"manifest_id": "shr_" + "4" * 64}))
    declined = service.decide_grant(bob, offered.grant_id, consent=False)
    assert declined.state is FileGrantState.DECLINED
    with pytest.raises(ValueError):
        store.save_grant(
            declined.model_copy(
                update={
                    "state": FileGrantState.CONSENTED,
                    "explicit_recipient_consent": True,
                }
            )
        )
    with pytest.raises(FileShareConflictError):
        service.decide_grant(bob, offered.grant_id, consent=True)
    # A grant for a manifest that lives in another tenant is refused.
    with pytest.raises(ValueError):
        store.save_grant(
            offered.model_copy(
                update={"organization_id": OTHER_ORG, "grant_id": "shr_" + "5" * 64}
            )
        )
    assert store.grants_for_manifest(OTHER_ORG, MANIFEST) == ()
    ordered = store.grants_for_manifest(ORG, MANIFEST)
    assert [item.grant_id for item in ordered] == sorted(item.grant_id for item in ordered)
    social.close()


def test_availability_expires_and_deletes_atomically(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, _ = bootstrap(tmp_path, clock)
    service.register_manifest(alice, manifest())
    service.publish_availability(alice, availability(expires_in=timedelta(seconds=30)))
    assert files.store.availability(ORG, MANIFEST, now=NOW) is not None
    assert files.store.availability(OTHER_ORG, MANIFEST, now=NOW) is None
    later = NOW + timedelta(seconds=30)
    assert files.store.availability(ORG, MANIFEST, now=later) is None
    assert raw_rows(
        social.database.path, "SELECT count(*) FROM social_file_availability"
    ) == [(0,)]
    with pytest.raises(ValueError):
        files.store.save_availability(
            availability().model_copy(update={"owner_device_id": BOB_DEVICE})
        )
    social.close()


# ---------------------------------------------------------------------------
# Rollback, replay and database constraints


def test_failed_audit_rolls_back_manifest_registration(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, _ = bootstrap(tmp_path, clock)

    class FailingAudit:
        def append(self, event):
            raise sqlite3.OperationalError("synthetic disk failure")

    failing = replace(service, stores=replace(service.stores, audit=FailingAudit()))
    with pytest.raises(sqlite3.OperationalError):
        failing.register_manifest(alice, manifest())
    assert social.db.connection.in_transaction is False
    assert files.store.manifest(ORG, MANIFEST) is None
    assert raw_rows(
        social.database.path, "SELECT count(*) FROM social_file_manifest_chunks"
    ) == [(0,)]
    social.close()


def test_audit_replay_and_unbound_rows_are_rejected(tmp_path: Path) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(tmp_path, clock)
    grant = consented_grant(service, alice, bob)
    event = files.store.recent_audit(ORG, limit=1)[0]
    with pytest.raises(ValueError):
        files.store.append(event)
    with pytest.raises(ValueError):
        files.store.append(event.model_copy(update={"organization_id": OTHER_ORG}))
    social.close()

    path = social.database.path
    # A transfer row for a grant that lives in another tenant fails on the
    # composite foreign key even when the adapter is bypassed.
    with pytest.raises(sqlite3.IntegrityError):
        raw_execute(
            path,
            "INSERT INTO social_file_transfers VALUES "
            "(?,?,?,?,?,?,?,?,'waiting_owner_approval',NULL,NULL,?,0,NULL,0,0,0)",
            (
                OTHER_ORG,
                "shr_" + "6" * 64,
                MANIFEST,
                grant.grant_id,
                BOB,
                BOB_DEVICE,
                "2047-03-08T12:00:00+00:00",
                "2047-03-08T13:00:00+00:00",
                "2047-03-08T12:00:00+00:00",
            ),
        )
    # Relay and cloud fallback flags cannot be flipped in storage.
    with pytest.raises(sqlite3.IntegrityError):
        raw_execute(
            path,
            "INSERT INTO social_file_transfers VALUES "
            "(?,?,?,?,?,?,?,?,'waiting_owner_approval',NULL,NULL,?,0,NULL,1,0,0)",
            (
                ORG,
                "shr_" + "6" * 64,
                MANIFEST,
                grant.grant_id,
                BOB,
                BOB_DEVICE,
                "2047-03-08T12:00:00+00:00",
                "2047-03-08T13:00:00+00:00",
                "2047-03-08T12:00:00+00:00",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        raw_execute(
            path,
            "UPDATE social_file_manifests SET stores_file_name = 1 WHERE manifest_id = ?",
            (MANIFEST,),
        )
    # Store-level binding: transfer request for the wrong grant/manifest pair.
    social, files, _ = open_foundations(tmp_path, clock)
    with pytest.raises(ValueError):
        files.store.save_transfer(
            TransferRecord.model_validate(
                {
                    "request": {
                        "organization_id": ORG,
                        "transfer_id": "shr_" + "6" * 64,
                        "manifest_id": "shr_" + "2" * 64,
                        "grant_id": grant.grant_id,
                        "requester_account_id": BOB,
                        "requester_device_id": BOB_DEVICE,
                        "ranges": (ByteRange(start=0, end_exclusive=1),),
                        "created_at": NOW,
                        "expires_at": NOW + timedelta(hours=1),
                    },
                    "state": TransferState.WAITING_OWNER_APPROVAL,
                    "changed_at": NOW,
                    "received_bytes": 0,
                }
            )
        )
    social.close()


# ---------------------------------------------------------------------------
# Privacy canaries and transport absence


def test_file_tables_have_no_content_columns_and_database_has_no_canaries(
    tmp_path: Path,
) -> None:
    clock = Clock()
    social, files, service, alice, bob = bootstrap(
        tmp_path, clock, signaling=SyntheticDirectSignaling()
    )
    grant = consented_grant(service, alice, bob)
    service.publish_availability(alice, availability())
    transfer = service.request_transfer(
        bob,
        grant.grant_id,
        ranges=(ByteRange(start=0, end_exclusive=manifest().byte_size),),
        expires_at=NOW + timedelta(hours=1),
    )
    service.approve_and_negotiate(alice, transfer.request.transfer_id)
    service.complete_transfer(bob, evidence(transfer.request.transfer_id))
    social.close()
    path = social.database.path
    connection = sqlite3.connect(path)
    try:
        for table in FILE_TABLES:
            info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            assert info, table
            columns = {row[1] for row in info}
            assert columns.isdisjoint(FORBIDDEN_COLUMN_NAMES), table
            assert all(row[2].upper() != "BLOB" for row in info), table
            for token in ("name", "path", "content", "bytes", "candidate", "ip"):
                # ``stores_file_name``/``stores_file_path`` are always-zero
                # negative flags and ``*_bytes`` columns are INTEGER sizes;
                # neither is a text/blob storage column.
                assert not any(
                    (row[1] == token or row[1].endswith("_" + token))
                    and not row[1].startswith("stores_")
                    and row[2].upper() != "INTEGER"
                    for row in info
                ), (table, token)
        # TransferIntegrityEvidence has no table and no evidence-only column.
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert not any("evidence" in name or "chunk_sha256" in name for name in tables)
        columns = {
            row[1]
            for table in tables
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        assert "verified_at" not in columns and "chunk_sha256" not in columns
    finally:
        connection.close()
    payload = path.read_bytes()
    for wal in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if wal.exists():
            payload += wal.read_bytes()
    for canary in CANARIES:
        assert canary not in payload


def test_no_direct_transport_or_network_implementation_was_added() -> None:
    sources = (
        inspect.getsource(store_module),
        inspect.getsource(file_sqlite_module),
    )
    for source in sources:
        for forbidden in (
            "import socket",
            "import asyncio",
            "import ssl",
            "http.server",
            "urllib",
            "aiortc",
            "stun",
            "turn:",
            "ice_candidate",
            "DirectByteTransportPort",
            "TransferIntegrityEvidence(",
            "send_range",
            "listen(",
            "bind(",
        ):
            assert forbidden not in source, forbidden
    # No transport adapter is exported by the file-sharing infrastructure.
    exported = set(file_sharing_infrastructure.__all__)
    assert not any("Transport" in name or "Signaling" in name and name != "FailClosedDirectSignaling" for name in exported)
    assert not any(
        hasattr(getattr(file_sharing_infrastructure, name), "send_range")
        for name in exported
    )
