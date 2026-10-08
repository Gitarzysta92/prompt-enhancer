"""Contract and privacy tests for the invite-only social foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.social import (
    AeadAlgorithm,
    Conversation,
    ConversationKind,
    DeviceKeyReference,
    DeviceState,
    E2eeEnvelopeMetadata,
    FriendRequest,
    FriendRequestState,
    MessageOperation,
    PeerDeletionAcknowledgement,
    PeerDeletionState,
    PresenceState,
    RelationshipPresence,
    SocialDeletionReceipt,
    SocialDevice,
    SocialReadinessGap,
    development_social_readiness,
)


NOW = datetime(2047, 3, 8, 12, tzinfo=UTC)
ORG = "soc_" + "a" * 64
ALICE = "soc_" + "b" * 64
BOB = "soc_" + "c" * 64
DEVICE = "soc_" + "d" * 64
CONVERSATION = "soc_" + "e" * 64
ENVELOPE = "soc_" + "f" * 64
MESSAGE = "soc_" + "1" * 64
REQUEST = "soc_" + "2" * 64
CONTENT_CANARY = "SYNTHETIC private message canary: never persist this"


def key_reference() -> DeviceKeyReference:
    return DeviceKeyReference(
        signing_key_version=1,
        agreement_key_version=1,
        signing_key_fingerprint="3" * 64,
        agreement_key_fingerprint="4" * 64,
    )


def test_social_namespace_cannot_reuse_analyzer_pseudonyms() -> None:
    with pytest.raises(ValidationError):
        SocialDevice(
            organization_id="a" * 64,
            account_id=ALICE,
            device_id=DEVICE,
            state=DeviceState.ACTIVE,
            keys=key_reference(),
            enrolled_at=NOW,
        )
    with pytest.raises(ValidationError):
        SocialDevice(
            organization_id=ORG,
            account_id=CONTENT_CANARY,
            device_id=DEVICE,
            state=DeviceState.ACTIVE,
            keys=key_reference(),
            enrolled_at=NOW,
        )


def test_friend_request_lifecycle_is_finite_and_closed() -> None:
    pending = FriendRequest(
        organization_id=ORG,
        request_id=REQUEST,
        requester_account_id=ALICE,
        recipient_account_id=BOB,
        state=FriendRequestState.PENDING,
        created_at=NOW,
        expires_at=NOW + timedelta(days=7),
    )
    assert pending.decided_at is None

    with pytest.raises(ValidationError):
        FriendRequest(
            **pending.model_dump(exclude={"expires_at"}),
            expires_at=NOW + timedelta(days=31),
        )
    with pytest.raises(ValidationError):
        FriendRequest(
            **pending.model_dump(exclude={"state"}),
            state=FriendRequestState.ACCEPTED,
        )
    with pytest.raises(ValidationError):
        FriendRequest(
            **pending.model_dump(exclude={"recipient_account_id"}),
            recipient_account_id=ALICE,
        )


def test_private_conversations_are_finite_invite_only_and_not_discoverable() -> None:
    direct = Conversation(
        organization_id=ORG,
        conversation_id=CONVERSATION,
        kind=ConversationKind.DIRECT,
        member_account_ids=(ALICE, BOB),
        current_key_version=1,
        created_at=NOW,
    )
    assert direct.invitation_only is True
    assert direct.discoverable is False
    with pytest.raises(ValidationError):
        Conversation(
            **direct.model_dump(exclude={"discoverable"}), discoverable=True
        )
    with pytest.raises(ValidationError):
        Conversation(
            **direct.model_dump(exclude={"member_account_ids"}),
            member_account_ids=(BOB, ALICE),
        )
    with pytest.raises(ValidationError):
        Conversation(
            **direct.model_dump(exclude={"member_account_ids"}),
            member_account_ids=(ALICE, BOB, "soc_" + "5" * 64),
        )


def test_e2ee_persistent_contract_has_metadata_but_no_message_bytes() -> None:
    metadata = E2eeEnvelopeMetadata(
        organization_id=ORG,
        conversation_id=CONVERSATION,
        envelope_id=ENVELOPE,
        message_id=MESSAGE,
        sender_account_id=ALICE,
        sender_device_id=DEVICE,
        operation=MessageOperation.CREATE,
        revision=1,
        key_version=1,
        aead_algorithm=AeadAlgorithm.XCHACHA20_POLY1305,
        ciphertext_size=512,
        ciphertext_sha256="6" * 64,
        created_at=NOW,
    )
    field_names = set(E2eeEnvelopeMetadata.model_fields)
    assert not field_names.intersection(
        {"body", "text", "plaintext", "ciphertext", "content", "prompt"}
    )
    assert CONTENT_CANARY not in metadata.model_dump_json()
    for forbidden in ("body", "text", "plaintext", "ciphertext", "content"):
        with pytest.raises(ValidationError):
            E2eeEnvelopeMetadata(
                **metadata.model_dump(), **{forbidden: CONTENT_CANARY}
            )

    with pytest.raises(ValidationError):
        E2eeEnvelopeMetadata(
            **metadata.model_dump(exclude={"revision", "operation"}),
            revision=2,
            operation=MessageOperation.CREATE,
        )


def test_presence_is_explicit_per_relationship_coarse_and_short_lived() -> None:
    presence = RelationshipPresence(
        organization_id=ORG,
        subject_account_id=ALICE,
        audience_account_id=BOB,
        state=PresenceState.AVAILABLE,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )
    assert presence.opted_in is True
    with pytest.raises(ValidationError):
        RelationshipPresence(
            **presence.model_dump(exclude={"expires_at"}),
            expires_at=NOW + timedelta(minutes=6),
        )
    with pytest.raises(ValidationError):
        RelationshipPresence(
            **presence.model_dump(exclude={"opted_in"}), opted_in=False
        )


def test_readiness_and_deletion_are_production_honest() -> None:
    readiness = development_social_readiness(enabled=True)
    assert readiness.production_ready is False
    assert readiness.invite_only is True
    assert readiness.public_discovery is False
    assert readiness.analyzer_join_keys is False
    assert readiness.persists_message_plaintext is False
    assert readiness.persists_message_ciphertext is False
    assert readiness.presence_derived_from_analyzer_activity is False
    assert readiness.local_history_deleted_on_entitlement_lapse is False
    assert readiness.local_export_requires_active_entitlement is False
    assert SocialReadinessGap.FORWARD_SECRECY_UNAVAILABLE in readiness.gaps
    assert SocialReadinessGap.ABUSE_REPORTING_UNAVAILABLE in readiness.gaps
    assert SocialReadinessGap.SOCIAL_STORE_NOT_SEPARATED in readiness.gaps
    assert SocialReadinessGap.METADATA_VISIBLE_TO_CONTROL_PLANE in readiness.gaps
    assert SocialReadinessGap.LEGAL_CONTROLLER_UNDETERMINED in readiness.gaps

    acknowledgement = PeerDeletionAcknowledgement(
        organization_id=ORG,
        subject_account_id=ALICE,
        peer_device_id=DEVICE,
        state=PeerDeletionState.ACKNOWLEDGED,
        requested_at=NOW,
        acknowledged_at=NOW + timedelta(seconds=2),
    )
    receipt = SocialDeletionReceipt(
        organization_id=ORG,
        account_id=ALICE,
        receipt_id="soc_" + "7" * 64,
        relationship_rows_removed=2,
        message_metadata_rows_tombstoned=3,
        conversation_membership_rows_removed=1,
        reaction_and_read_rows_removed=2,
        presence_rows_removed=1,
        peer_deletion_requested=True,
        peer_device_acknowledgements=(acknowledgement,),
        completed_at=NOW,
    )
    assert receipt.local_account_content_erased is True
    assert receipt.local_metadata_erased is False
    assert receipt.retains_account_tombstone is True
    assert receipt.retains_device_revocation_fences is True
    assert receipt.retains_security_audit_events is True
    assert receipt.peer_deletion_requested is True
    assert receipt.peer_device_acknowledgements[0].plaintext_recall_guaranteed is False
    assert receipt.remote_plaintext_recall_guaranteed is False


def test_whole_second_utc_timestamps_are_mandatory() -> None:
    with pytest.raises(ValidationError):
        RelationshipPresence(
            organization_id=ORG,
            subject_account_id=ALICE,
            audience_account_id=BOB,
            state=PresenceState.AWAY,
            observed_at=NOW.replace(tzinfo=None),
            expires_at=NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValidationError):
        RelationshipPresence(
            organization_id=ORG,
            subject_account_id=ALICE,
            audience_account_id=BOB,
            state=PresenceState.AWAY,
            observed_at=NOW.replace(microsecond=1),
            expires_at=NOW + timedelta(minutes=1),
        )
