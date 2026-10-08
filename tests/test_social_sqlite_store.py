"""Durability, rollback and attack tests for the SQLite social adapter."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sqlite3
import threading

import pytest

from prompt_enhancer.application.social import (
    E2eeEnvelopeMetadata,
    MessageOperation,
    PeerDeletionAcknowledgement,
    PeerDeletionState,
    SocialAuthorizationError,
    SocialConflictError,
    SocialDeletionReceipt,
    SocialReasonCode,
    SocialService,
)
from prompt_enhancer.infrastructure.social import (
    SOCIAL_SCHEMA_VERSION,
    SocialSqliteDatabase,
    create_sqlite_social_foundation,
)
from prompt_enhancer.infrastructure.social.sqlite_schema import (
    FORBIDDEN_COLUMN_NAMES,
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
    SyntheticVerifiedCrypto,
    provision,
)

CANARY = "canary-message-plaintext-body-do-not-persist"


def open_foundation(tmp_path: Path, clock: Clock):
    return create_sqlite_social_foundation(SocialSqliteDatabase.under(tmp_path), clock)


def befriend(service: SocialService, alice, bob):
    request = service.request_friend(
        alice, bob.account_id, expires_at=NOW + timedelta(days=1)
    )
    service.decide_friend_request(bob, request.request_id, accept=True)


def test_ledger_reaches_current_head_and_schema_has_no_content_or_path_columns(
    tmp_path: Path,
) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    foundation.close()
    connection = sqlite3.connect(foundation.database.path)
    try:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM social_schema_migrations ORDER BY version"
            )
        ]
        assert versions == list(range(1, SOCIAL_SCHEMA_VERSION + 1))
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        assert "social_accounts" in tables and "social_file_transfers" in tables
        assert not any(name in {"sessions", "events", "metrics"} for name in tables)
        columns = {
            row[1]
            for table in tables
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        assert columns.isdisjoint(FORBIDDEN_COLUMN_NAMES)
        for table in tables:
            assert not any(
                "BLOB" == row[2].upper()
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            )
    finally:
        connection.close()


def test_friendship_survives_restart_and_block_beats_grant(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    bob = provision(foundation.store, BOB, BOB_DEVICE)
    befriend(foundation.service, alice, bob)
    foundation.close()

    reopened = open_foundation(tmp_path, clock)
    conversation = reopened.service.create_direct_conversation(alice, BOB)
    assert conversation.member_account_ids == tuple(sorted((ALICE, BOB)))
    reopened.service.block_account(bob, ALICE)
    with pytest.raises(SocialAuthorizationError) as denied:
        reopened.service.create_direct_conversation(alice, BOB)
    assert denied.value.reason is SocialReasonCode.RELATIONSHIP_UNAVAILABLE
    # A blocked and an unknown target look identical.
    with pytest.raises(SocialAuthorizationError) as unknown:
        reopened.service.request_friend(
            alice, "soc_" + "7" * 64, expires_at=NOW + timedelta(days=1)
        )
    assert unknown.value.reason is denied.value.reason
    reopened.close()


def test_partial_write_rolls_back_when_audit_fails(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    provision(foundation.store, BOB, BOB_DEVICE)
    class FailingAudit:
        def append(self, event):
            raise sqlite3.OperationalError("synthetic disk failure")

        def recent(self, organization_id, *, limit):
            return ()

    from dataclasses import replace

    failing_service = replace(
        foundation.service,
        stores=replace(foundation.service.stores, audit=FailingAudit()),
    )
    with pytest.raises(sqlite3.OperationalError):
        failing_service.request_friend(
            alice, BOB, expires_at=NOW + timedelta(days=1)
        )
    assert foundation.store.pending_between(ORG, ALICE, BOB) is None
    assert foundation.db.connection.in_transaction is False
    foundation.close()


def test_begin_contention_releases_process_lock(tmp_path: Path) -> None:
    foundation = open_foundation(tmp_path, Clock())
    foundation.db.connection.execute("PRAGMA busy_timeout = 1")
    blocker = sqlite3.connect(foundation.database.path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError):
            with foundation.db:
                pass

        acquired: list[bool] = []

        def probe_lock() -> None:
            locked = foundation.db.lock.acquire(timeout=0.5)
            acquired.append(locked)
            if locked:
                foundation.db.lock.release()

        thread = threading.Thread(target=probe_lock)
        thread.start()
        thread.join(timeout=1)
        assert acquired == [True]
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    with foundation.db:
        assert foundation.db.connection.in_transaction is True
    foundation.close()


def test_tenant_isolation_and_revoked_device_denies_after_restart(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    provision(foundation.store, BOB, BOB_DEVICE, organization_id=OTHER_ORG)
    with pytest.raises(SocialAuthorizationError):
        foundation.service.request_friend(
            alice, BOB, expires_at=NOW + timedelta(days=1)
        )
    foundation.store.revoke_device(ORG, ALICE_DEVICE, now=NOW)
    foundation.close()
    reopened = open_foundation(tmp_path, clock)
    with pytest.raises(SocialAuthorizationError) as denied:
        reopened.service.read_presence(alice, BOB)
    assert denied.value.reason is SocialReasonCode.DEVICE_INACTIVE
    with pytest.raises(ValueError):
        provision(reopened.store, ALICE, ALICE_DEVICE)
    reopened.close()


def test_message_metadata_replay_regression_and_no_content_column(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    bob = provision(foundation.store, BOB, BOB_DEVICE)
    befriend(foundation.service, alice, bob)
    conversation = foundation.service.create_direct_conversation(alice, BOB)
    service = SocialService(
        stores=foundation.service.stores,
        identifiers=foundation.service.identifiers,
        crypto=SyntheticVerifiedCrypto(),
        clock=clock,
    )
    envelope = E2eeEnvelopeMetadata(
        organization_id=ORG,
        conversation_id=conversation.conversation_id,
        envelope_id="soc_" + "1" * 64,
        message_id="soc_" + "2" * 64,
        sender_account_id=ALICE,
        sender_device_id=ALICE_DEVICE,
        operation=MessageOperation.CREATE,
        revision=1,
        key_version=1,
        ciphertext_size=42,
        ciphertext_sha256="3" * 64,
        created_at=NOW,
    )
    assert service.record_message_metadata(alice, envelope) == envelope
    assert service.record_message_metadata(alice, envelope) == envelope
    replay = envelope.model_copy(update={"ciphertext_size": 43})
    with pytest.raises(SocialConflictError) as conflict:
        service.record_message_metadata(alice, replay)
    assert conflict.value.reason is SocialReasonCode.REQUEST_REPLAYED
    stale_edit = envelope.model_copy(
        update={
            "envelope_id": "soc_" + "4" * 64,
            "operation": MessageOperation.EDIT,
            "revision": 3,
        }
    )
    with pytest.raises(SocialConflictError):
        service.record_message_metadata(alice, stale_edit)
    with pytest.raises(ValueError):
        foundation.store.append_message_metadata(stale_edit, accepted_at=NOW)
    service.mark_read(alice, conversation.conversation_id, through_sequence=5)
    with pytest.raises(SocialConflictError):
        service.mark_read(alice, conversation.conversation_id, through_sequence=4)
    foundation.close()
    assert CANARY.encode() not in foundation.database.path.read_bytes()


def test_account_deletion_persists_honest_receipt_and_tombstones(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    bob = provision(foundation.store, BOB, BOB_DEVICE)
    befriend(foundation.service, alice, bob)
    receipt = foundation.service.delete_account_metadata(alice)
    foundation.close()
    reopened = open_foundation(tmp_path, clock)
    stored = reopened.store.deletion_receipt(ORG, ALICE)
    assert stored == receipt
    assert stored.local_metadata_erased is False
    assert stored.remote_plaintext_recall_guaranteed is False
    assert reopened.store.friendship(ORG, ALICE, BOB) is None
    assert reopened.store.device(ORG, ALICE_DEVICE).state.value == "revoked"
    with pytest.raises(SocialAuthorizationError):
        reopened.service.request_friend(
            alice, BOB, expires_at=NOW + timedelta(days=1)
        )
    reopened.close()


def test_deletion_receipt_round_trips_peer_device_acknowledgements(
    tmp_path: Path,
) -> None:
    foundation = open_foundation(tmp_path, Clock())
    provision(foundation.store, ALICE, ALICE_DEVICE)
    provision(foundation.store, BOB, BOB_DEVICE)
    foundation.store.delete_account(ORG, ALICE, now=NOW)
    acknowledgement = PeerDeletionAcknowledgement(
        organization_id=ORG,
        subject_account_id=ALICE,
        peer_device_id=BOB_DEVICE,
        state=PeerDeletionState.ACKNOWLEDGED,
        requested_at=NOW,
        acknowledged_at=NOW,
    )
    receipt = SocialDeletionReceipt(
        organization_id=ORG,
        account_id=ALICE,
        receipt_id="soc_" + "6" * 64,
        relationship_rows_removed=0,
        message_metadata_rows_tombstoned=0,
        conversation_membership_rows_removed=0,
        reaction_and_read_rows_removed=0,
        presence_rows_removed=0,
        peer_deletion_requested=True,
        peer_device_acknowledgements=(acknowledgement,),
        completed_at=NOW,
    )
    assert foundation.store.save_deletion_receipt(receipt) == receipt
    assert foundation.store.save_deletion_receipt(receipt) == receipt
    with pytest.raises(ValueError, match="conflict"):
        foundation.store.save_deletion_receipt(
            receipt.model_copy(update={"receipt_id": "soc_" + "7" * 64})
        )
    foundation.close()

    reopened = open_foundation(tmp_path, Clock())
    assert reopened.store.deletion_receipt(ORG, ALICE) == receipt
    reopened.close()


def test_account_deletion_closes_direct_conversation_but_retains_peer_metadata(
    tmp_path: Path,
) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    bob = provision(foundation.store, BOB, BOB_DEVICE)
    befriend(foundation.service, alice, bob)
    conversation = foundation.service.create_direct_conversation(alice, BOB)
    service = SocialService(
        stores=foundation.service.stores,
        identifiers=foundation.service.identifiers,
        crypto=SyntheticVerifiedCrypto(),
        clock=clock,
    )
    peer_envelope = E2eeEnvelopeMetadata(
        organization_id=ORG,
        conversation_id=conversation.conversation_id,
        envelope_id="soc_" + "8" * 64,
        message_id="soc_" + "9" * 64,
        sender_account_id=BOB,
        sender_device_id=BOB_DEVICE,
        operation=MessageOperation.CREATE,
        revision=1,
        key_version=1,
        ciphertext_size=64,
        ciphertext_sha256="a" * 64,
        created_at=NOW,
    )
    service.record_message_metadata(bob, peer_envelope)

    receipt = foundation.service.delete_account_metadata(alice)
    assert receipt.local_metadata_erased is False
    assert foundation.store.conversation(ORG, conversation.conversation_id) is None
    assert (
        foundation.store.latest_message(
            ORG, conversation.conversation_id, peer_envelope.message_id
        )
        == peer_envelope
    )
    foundation.close()

    reopened = open_foundation(tmp_path, clock)
    assert reopened.store.deletion_receipt(ORG, ALICE) == receipt
    assert reopened.store.conversation(ORG, conversation.conversation_id) is None
    assert (
        reopened.store.latest_message(
            ORG, conversation.conversation_id, peer_envelope.message_id
        )
        == peer_envelope
    )
    late_envelope = peer_envelope.model_copy(
        update={
            "envelope_id": "soc_" + "e" * 64,
            "message_id": "soc_" + "f" * 64,
        }
    )
    with pytest.raises(ValueError, match="schema constraints"):
        reopened.store.append_message_metadata(late_envelope, accepted_at=NOW)
    fence = reopened.db.connection.execute(
        "SELECT closed_at FROM social_conversation_fences "
        "WHERE organization_id = ? AND conversation_id = ?",
        (ORG, conversation.conversation_id),
    ).fetchone()
    assert fence is not None and fence[0] == NOW.isoformat()
    reopened.close()


def test_group_shrink_closes_capability_without_erasing_peer_envelope(
    tmp_path: Path,
) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    alice = provision(foundation.store, ALICE, ALICE_DEVICE)
    bob = provision(foundation.store, BOB, BOB_DEVICE)
    channel = foundation.service.create_private_channel(alice)
    foundation.service.invite_channel_member(alice, channel.channel_id, BOB)
    _, conversation = foundation.service.decide_channel_invite(
        bob, channel.channel_id, accept=True
    )
    assert conversation is not None
    service = SocialService(
        stores=foundation.service.stores,
        identifiers=foundation.service.identifiers,
        crypto=SyntheticVerifiedCrypto(),
        clock=clock,
    )
    peer_envelope = E2eeEnvelopeMetadata(
        organization_id=ORG,
        conversation_id=conversation.conversation_id,
        envelope_id="soc_" + "b" * 64,
        message_id="soc_" + "c" * 64,
        sender_account_id=BOB,
        sender_device_id=BOB_DEVICE,
        operation=MessageOperation.CREATE,
        revision=1,
        key_version=conversation.current_key_version,
        ciphertext_size=64,
        ciphertext_sha256="d" * 64,
        created_at=NOW,
    )
    service.record_message_metadata(bob, peer_envelope)

    _, active_conversation = foundation.service.leave_channel(bob, channel.channel_id)
    assert active_conversation is None
    assert foundation.store.conversation_for_channel(ORG, channel.channel_id) is None
    assert (
        foundation.store.latest_message(
            ORG, conversation.conversation_id, peer_envelope.message_id
        )
        == peer_envelope
    )
    foundation.close()

    reopened = open_foundation(tmp_path, clock)
    assert reopened.store.conversation_for_channel(ORG, channel.channel_id) is None
    assert (
        reopened.store.latest_message(
            ORG, conversation.conversation_id, peer_envelope.message_id
        )
        == peer_envelope
    )
    reopened.close()


def test_schema_constraints_reject_public_channels_and_foreign_ids(tmp_path: Path) -> None:
    clock = Clock()
    foundation = open_foundation(tmp_path, clock)
    connection = foundation.db.connection
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO social_private_channels VALUES (?,?,NULL,?,1,1,?)",
            (ORG, "soc_" + "5" * 64, ALICE, NOW.isoformat()),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO social_devices VALUES (?,?,?,'active','ed25519','x25519',1,1,?,?,?,NULL)",
            (ORG, ALICE_DEVICE, ALICE, "a" * 64, "b" * 64, NOW.isoformat()),
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO social_blocks VALUES (?,?,?,?)",
            (ORG, "user-123", "user-456", NOW.isoformat()),
        )
    foundation.close()
