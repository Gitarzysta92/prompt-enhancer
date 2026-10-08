"""Adversarial policy and lifecycle tests for the social development service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.social import (
    DeviceKeyReference,
    DeviceState,
    E2eeEnvelopeMetadata,
    FriendRequestState,
    MessageOperation,
    MessageReaction,
    MessageReactionCode,
    PresenceState,
    RelationshipPresence,
    SocialAccount,
    SocialAccountState,
    SocialAuthorizationError,
    SocialConflictError,
    SocialCryptoUnavailableError,
    SocialDevice,
    SocialMembershipState,
    SocialOrganizationMembership,
    SocialOrganizationRole,
    SocialReasonCode,
    SocialTeam,
    SocialTeamMembership,
    SocialTeamRole,
    SocialService,
    VerifiedSocialPrincipal,
)
from prompt_enhancer.infrastructure.social import (
    FailClosedMessageCrypto,
    create_development_social_foundation,
)


ORG = "soc_" + "a" * 64
OTHER_ORG = "soc_" + "9" * 64
ALICE = "soc_" + "b" * 64
BOB = "soc_" + "c" * 64
UNKNOWN = "soc_" + "8" * 64
CHARLIE = "soc_" + "6" * 64
ALICE_DEVICE = "soc_" + "d" * 64
BOB_DEVICE = "soc_" + "e" * 64
CHARLIE_DEVICE = "soc_" + "5" * 64
NOW = datetime(2047, 3, 8, 12, tzinfo=UTC)


@dataclass
class Clock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


@dataclass(frozen=True)
class SyntheticVerifiedCrypto:
    production_ready: bool = False
    forward_secrecy: bool = False
    valid: bool = True

    def verify_authenticated_envelope(self, principal: object, metadata: object) -> bool:
        return self.valid


def key_reference(seed: str) -> DeviceKeyReference:
    return DeviceKeyReference(
        signing_key_version=1,
        agreement_key_version=1,
        signing_key_fingerprint=seed * 64,
        agreement_key_fingerprint=("f" if seed != "f" else "0") * 64,
    )


def provision(
    state: object,
    account_id: str,
    device_id: str,
    *,
    organization_id: str = ORG,
) -> VerifiedSocialPrincipal:
    account = SocialAccount(
        organization_id=organization_id,
        account_id=account_id,
        state=SocialAccountState.ACTIVE,
        created_at=NOW,
    )
    membership = SocialOrganizationMembership(
        organization_id=organization_id,
        account_id=account_id,
        role=SocialOrganizationRole.MEMBER,
        state=SocialMembershipState.ACTIVE,
        created_at=NOW,
    )
    device = SocialDevice(
        organization_id=organization_id,
        account_id=account_id,
        device_id=device_id,
        state=DeviceState.ACTIVE,
        keys=key_reference(device_id[-1]),
        enrolled_at=NOW,
    )
    state.provision_account(account, membership, (device,))
    return VerifiedSocialPrincipal(
        organization_id=organization_id,
        account_id=account_id,
        device_id=device_id,
        authenticated_at=NOW,
    )


def setup() -> tuple[Clock, object, SocialService, VerifiedSocialPrincipal, VerifiedSocialPrincipal]:
    clock = Clock()
    foundation = create_development_social_foundation(clock)
    alice = provision(foundation.state, ALICE, ALICE_DEVICE)
    bob = provision(foundation.state, BOB, BOB_DEVICE)
    service = SocialService(
        stores=foundation.service.stores,
        identifiers=foundation.service.identifiers,
        crypto=SyntheticVerifiedCrypto(),
        clock=clock,
    )
    return clock, foundation.state, service, alice, bob


def befriend(
    service: SocialService,
    alice: VerifiedSocialPrincipal,
    bob: VerifiedSocialPrincipal,
) -> None:
    request = service.request_friend(
        alice, bob.account_id, expires_at=NOW + timedelta(days=2)
    )
    accepted = service.decide_friend_request(bob, request.request_id, accept=True)
    assert accepted.state is FriendRequestState.ACCEPTED


def message(
    conversation_id: str,
    sender: VerifiedSocialPrincipal,
    *,
    envelope_seed: str = "1",
    message_seed: str = "2",
    operation: MessageOperation = MessageOperation.CREATE,
    revision: int = 1,
    key_version: int = 1,
    thread_root_message_id: str | None = None,
    created_at: datetime = NOW,
) -> E2eeEnvelopeMetadata:
    return E2eeEnvelopeMetadata(
        organization_id=sender.organization_id,
        conversation_id=conversation_id,
        envelope_id="soc_" + envelope_seed * 64,
        message_id="soc_" + message_seed * 64,
        sender_account_id=sender.account_id,
        sender_device_id=sender.device_id,
        operation=operation,
        revision=revision,
        key_version=key_version,
        ciphertext_size=128,
        ciphertext_sha256="7" * 64,
        thread_root_message_id=thread_root_message_id,
        created_at=created_at,
    )


def test_friend_request_accept_replay_remove_and_block_lifecycle() -> None:
    _, state, service, alice, bob = setup()
    request = service.request_friend(
        alice, BOB, expires_at=NOW + timedelta(days=1)
    )
    assert service.request_friend(
        alice, BOB, expires_at=NOW + timedelta(hours=2)
    ) == request
    accepted = service.decide_friend_request(bob, request.request_id, accept=True)
    assert service.decide_friend_request(bob, request.request_id, accept=True) == accepted
    assert state.friendship(ORG, ALICE, BOB) is not None
    assert service.remove_friend(alice, BOB) is True
    assert state.friendship(ORG, ALICE, BOB) is None

    block = service.block_account(alice, BOB)
    assert service.block_account(alice, BOB) == block
    assert state.either_blocked(ORG, ALICE, BOB)
    assert service.unblock_account(alice, BOB) is True
    assert service.unblock_account(alice, BOB) is False


def test_blocked_and_unknown_targets_have_same_observable_failure() -> None:
    _, _, service, alice, bob = setup()
    service.block_account(bob, ALICE)
    observed: list[tuple[type[Exception], SocialReasonCode]] = []
    for target in (BOB, UNKNOWN):
        with pytest.raises(SocialAuthorizationError) as captured:
            service.request_friend(
                alice, target, expires_at=NOW + timedelta(hours=1)
            )
        observed.append((type(captured.value), captured.value.reason))
    assert observed == [
        (SocialAuthorizationError, SocialReasonCode.RELATIONSHIP_UNAVAILABLE),
        (SocialAuthorizationError, SocialReasonCode.RELATIONSHIP_UNAVAILABLE),
    ]


def test_block_wins_accept_race_and_removes_pending_relationship() -> None:
    _, _, service, alice, bob = setup()
    request = service.request_friend(
        alice, BOB, expires_at=NOW + timedelta(hours=1)
    )
    service.block_account(alice, BOB)
    with pytest.raises(SocialAuthorizationError) as captured:
        service.decide_friend_request(bob, request.request_id, accept=True)
    assert captured.value.reason is SocialReasonCode.RELATIONSHIP_UNAVAILABLE


def test_revoked_device_denies_every_operation_before_read() -> None:
    _, state, service, alice, bob = setup()
    state.revoke_device(ORG, ALICE_DEVICE, now=NOW)
    with pytest.raises(SocialAuthorizationError) as captured:
        service.request_friend(alice, BOB, expires_at=NOW + timedelta(hours=1))
    assert captured.value.reason is SocialReasonCode.DEVICE_INACTIVE
    with pytest.raises(SocialAuthorizationError) as captured:
        service.read_presence(alice, BOB)
    assert captured.value.reason is SocialReasonCode.DEVICE_INACTIVE


def test_message_revisions_threads_reads_reactions_and_stale_keys() -> None:
    _, _, service, alice, bob = setup()
    befriend(service, alice, bob)
    conversation = service.create_direct_conversation(alice, BOB)
    created = message(conversation.conversation_id, alice)
    assert service.record_message_metadata(alice, created) == created
    assert service.record_message_metadata(alice, created) == created

    with pytest.raises(SocialConflictError) as captured:
        service.record_message_metadata(
            alice,
            message(
                conversation.conversation_id,
                alice,
                envelope_seed="3",
                message_seed="4",
                key_version=2,
            ),
        )
    assert captured.value.reason is SocialReasonCode.STALE_KEY_VERSION

    edit = message(
        conversation.conversation_id,
        alice,
        envelope_seed="5",
        operation=MessageOperation.EDIT,
        revision=2,
    )
    assert service.record_message_metadata(alice, edit) == edit
    reaction = MessageReaction(
        organization_id=ORG,
        conversation_id=conversation.conversation_id,
        message_id=created.message_id,
        actor_account_id=BOB,
        reaction=MessageReactionCode.ACKNOWLEDGED,
        active=True,
        changed_at=NOW,
    )
    assert service.react(bob, reaction) == reaction
    read = service.mark_read(bob, conversation.conversation_id, through_sequence=4)
    assert read.last_read_sequence == 4
    assert service.mark_read(bob, conversation.conversation_id, through_sequence=4) == read
    with pytest.raises(SocialConflictError):
        service.mark_read(bob, conversation.conversation_id, through_sequence=3)

    deleted = message(
        conversation.conversation_id,
        alice,
        envelope_seed="6",
        operation=MessageOperation.DELETE,
        revision=3,
    )
    service.record_message_metadata(alice, deleted)
    with pytest.raises(SocialAuthorizationError):
        service.react(bob, reaction)


def test_only_original_author_can_mutate_message_and_audit_uses_acceptance_time() -> None:
    clock, state, service, alice, bob = setup()
    befriend(service, alice, bob)
    conversation = service.create_direct_conversation(alice, BOB)
    created = message(conversation.conversation_id, alice)
    service.record_message_metadata(alice, created)

    forged_edit = message(
        conversation.conversation_id,
        bob,
        envelope_seed="3",
        operation=MessageOperation.EDIT,
        revision=2,
    )
    with pytest.raises(SocialConflictError) as captured:
        service.record_message_metadata(bob, forged_edit)
    assert captured.value.reason is SocialReasonCode.REVISION_CONFLICT
    assert state.latest_message(ORG, conversation.conversation_id, created.message_id) == created

    clock.value = NOW + timedelta(minutes=2)
    accepted_edit = message(
        conversation.conversation_id,
        alice,
        envelope_seed="4",
        operation=MessageOperation.EDIT,
        revision=2,
        created_at=NOW,
    )
    service.record_message_metadata(alice, accepted_edit)
    assert state.audits[-1].occurred_at == clock.value

    clock.value = NOW + timedelta(minutes=3)
    accepted_delete = message(
        conversation.conversation_id,
        alice,
        envelope_seed="5",
        operation=MessageOperation.DELETE,
        revision=3,
        created_at=NOW,
    )
    service.record_message_metadata(alice, accepted_delete)
    tombstone = state.message_tombstones[
        (ORG, conversation.conversation_id, created.message_id)
    ]
    assert tombstone.deleted_at == clock.value


def test_reaction_timestamp_outside_server_window_is_rejected() -> None:
    _, _, service, alice, bob = setup()
    befriend(service, alice, bob)
    conversation = service.create_direct_conversation(alice, BOB)
    created = message(conversation.conversation_id, alice)
    service.record_message_metadata(alice, created)
    with pytest.raises(SocialConflictError) as captured:
        service.react(
            bob,
            MessageReaction(
                organization_id=ORG,
                conversation_id=conversation.conversation_id,
                message_id=created.message_id,
                actor_account_id=BOB,
                reaction=MessageReactionCode.ACKNOWLEDGED,
                active=True,
                changed_at=NOW - timedelta(minutes=10),
            ),
        )
    assert captured.value.reason is SocialReasonCode.TIMESTAMP_OUT_OF_WINDOW


def test_unfriend_immediately_closes_direct_conversation_capability() -> None:
    _, _, service, alice, bob = setup()
    befriend(service, alice, bob)
    conversation = service.create_direct_conversation(alice, BOB)
    service.remove_friend(alice, BOB)
    with pytest.raises(SocialAuthorizationError) as captured:
        service.record_message_metadata(
            bob, message(conversation.conversation_id, bob)
        )
    assert captured.value.reason is SocialReasonCode.CONVERSATION_ACCESS_DENIED
    with pytest.raises(SocialAuthorizationError):
        service.mark_read(bob, conversation.conversation_id, through_sequence=0)


def test_crypto_port_is_fail_closed_and_cross_tenant_sender_is_rejected() -> None:
    clock, _, service, alice, bob = setup()
    befriend(service, alice, bob)
    conversation = service.create_direct_conversation(alice, BOB)
    fail_closed = SocialService(
        stores=service.stores,
        identifiers=service.identifiers,
        crypto=FailClosedMessageCrypto(),
        clock=clock,
    )
    with pytest.raises(SocialCryptoUnavailableError) as captured:
        fail_closed.record_message_metadata(
            alice, message(conversation.conversation_id, alice)
        )
    assert captured.value.reason is SocialReasonCode.CRYPTO_ADAPTER_UNAVAILABLE

    forged = message(conversation.conversation_id, alice).model_copy(
        update={"organization_id": OTHER_ORG}
    )
    with pytest.raises(SocialAuthorizationError):
        service.record_message_metadata(alice, forged)


def test_presence_requires_friendship_expires_and_account_deletion_is_honest() -> None:
    clock, state, service, alice, bob = setup()
    befriend(service, alice, bob)
    presence = RelationshipPresence(
        organization_id=ORG,
        subject_account_id=ALICE,
        audience_account_id=BOB,
        state=PresenceState.AVAILABLE,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
    )
    service.publish_presence(alice, presence)
    assert service.read_presence(bob, ALICE) == presence
    clock.value = NOW + timedelta(minutes=3)
    assert service.read_presence(bob, ALICE) is None

    receipt = service.delete_account_metadata(alice)
    assert receipt.local_account_content_erased is True
    assert receipt.local_metadata_erased is False
    assert receipt.retains_account_tombstone is True
    assert receipt.retains_device_revocation_fences is True
    assert receipt.retains_security_audit_events is True
    assert receipt.remote_plaintext_recall_guaranteed is False
    assert state.account(ORG, ALICE).state is SocialAccountState.DELETED
    assert state.device(ORG, ALICE_DEVICE) is None
    assert (ORG, ALICE_DEVICE) in state.revoked_device_ids


def test_account_deletion_never_tombstones_or_erases_peer_authored_metadata() -> None:
    _, state, service, alice, bob = setup()
    charlie = provision(state, CHARLIE, CHARLIE_DEVICE)
    channel = service.create_private_channel(alice)
    service.invite_channel_member(alice, channel.channel_id, BOB)
    service.decide_channel_invite(bob, channel.channel_id, accept=True)
    service.invite_channel_member(alice, channel.channel_id, CHARLIE)
    _, conversation = service.decide_channel_invite(
        charlie, channel.channel_id, accept=True
    )
    assert conversation is not None

    peer_message = message(
        conversation.conversation_id,
        bob,
        envelope_seed="3",
        message_seed="4",
        key_version=conversation.current_key_version,
    )
    own_message = message(
        conversation.conversation_id,
        alice,
        envelope_seed="5",
        message_seed="6",
        key_version=conversation.current_key_version,
    )
    service.record_message_metadata(bob, peer_message)
    service.record_message_metadata(alice, own_message)
    service.mark_read(bob, conversation.conversation_id, through_sequence=1)
    service.react(
        bob,
        MessageReaction(
            organization_id=ORG,
            conversation_id=conversation.conversation_id,
            message_id=peer_message.message_id,
            actor_account_id=BOB,
            reaction=MessageReactionCode.ACKNOWLEDGED,
            active=True,
            changed_at=NOW,
        ),
    )

    service.delete_account_metadata(alice)

    assert state.latest_message(
        ORG, conversation.conversation_id, peer_message.message_id
    ) == peer_message
    assert state.latest_message(
        ORG, conversation.conversation_id, own_message.message_id
    ) is None
    assert state.message_tombstones[
        (ORG, conversation.conversation_id, own_message.message_id)
    ].sender_account_id == ALICE
    assert (
        ORG,
        conversation.conversation_id,
        peer_message.message_id,
        BOB,
        MessageReactionCode.ACKNOWLEDGED.value,
    ) in state.reactions
    assert (ORG, conversation.conversation_id, BOB) in state.read_states
    surviving = state.conversation(ORG, conversation.conversation_id)
    assert surviving is not None
    assert surviving.member_account_ids == tuple(sorted((BOB, CHARLIE)))
    assert surviving.current_key_version == conversation.current_key_version + 1
    with pytest.raises(SocialConflictError) as captured:
        service.record_message_metadata(
            bob,
            message(
                surviving.conversation_id,
                bob,
                envelope_seed="7",
                message_seed="6",
                key_version=surviving.current_key_version,
            ),
        )
    assert captured.value.reason is SocialReasonCode.REVISION_CONFLICT


def test_private_group_invites_are_finite_and_membership_changes_rotate_keys() -> None:
    _, state, service, alice, bob = setup()
    charlie = provision(state, CHARLIE, CHARLIE_DEVICE)
    channel = service.create_private_channel(alice)
    invite = service.invite_channel_member(alice, channel.channel_id, BOB)
    assert invite.state.value == "invited"
    accepted, conversation = service.decide_channel_invite(
        bob, channel.channel_id, accept=True
    )
    assert accepted.state.value == "active"
    assert conversation is not None
    assert conversation.current_key_version == 1
    assert conversation.member_account_ids == tuple(sorted((ALICE, BOB)))

    service.invite_channel_member(alice, channel.channel_id, CHARLIE)
    _, expanded = service.decide_channel_invite(
        charlie, channel.channel_id, accept=True
    )
    assert expanded is not None
    assert expanded.current_key_version == 2
    assert expanded.member_account_ids == tuple(sorted((ALICE, BOB, CHARLIE)))

    removed, rotated = service.remove_channel_member(
        alice, channel.channel_id, BOB
    )
    assert removed.state.value == "removed"
    assert rotated is not None
    assert rotated.current_key_version == 3
    assert BOB not in rotated.member_account_ids
    with pytest.raises(SocialAuthorizationError):
        service.record_message_metadata(
            bob,
            message(
                rotated.conversation_id,
                bob,
                envelope_seed="9",
                message_seed="a",
                key_version=3,
            ),
        )


def test_team_bound_private_channel_rejects_nonmember_before_invite() -> None:
    _, state, service, alice, bob = setup()
    team_id = "soc_" + "4" * 64
    state.provision_team(
        SocialTeam(
            organization_id=ORG,
            team_id=team_id,
            owner_account_id=ALICE,
            created_at=NOW,
        ),
        (
            SocialTeamMembership(
                organization_id=ORG,
                team_id=team_id,
                account_id=ALICE,
                role=SocialTeamRole.LEAD,
                state=SocialMembershipState.ACTIVE,
                created_at=NOW,
            ),
        ),
    )
    channel = service.create_private_channel(alice, team_id=team_id)
    with pytest.raises(SocialAuthorizationError) as captured:
        service.invite_channel_member(alice, channel.channel_id, BOB)
    assert captured.value.reason is SocialReasonCode.MEMBERSHIP_REQUIRED


def test_team_membership_revocation_invalidates_an_outstanding_channel_invite() -> None:
    _, state, service, alice, bob = setup()
    team_id = "soc_" + "4" * 64
    bob_team_membership = SocialTeamMembership(
        organization_id=ORG,
        team_id=team_id,
        account_id=BOB,
        role=SocialTeamRole.MEMBER,
        state=SocialMembershipState.ACTIVE,
        created_at=NOW,
    )
    state.provision_team(
        SocialTeam(
            organization_id=ORG,
            team_id=team_id,
            owner_account_id=ALICE,
            created_at=NOW,
        ),
        (
            SocialTeamMembership(
                organization_id=ORG,
                team_id=team_id,
                account_id=ALICE,
                role=SocialTeamRole.LEAD,
                state=SocialMembershipState.ACTIVE,
                created_at=NOW,
            ),
            bob_team_membership,
        ),
    )
    channel = service.create_private_channel(alice, team_id=team_id)
    service.invite_channel_member(alice, channel.channel_id, BOB)
    state.team_memberships[(ORG, team_id, BOB)] = SocialTeamMembership.model_validate(
        {
            **bob_team_membership.model_dump(mode="python"),
            "state": SocialMembershipState.REVOKED,
            "revoked_at": NOW,
        }
    )
    with pytest.raises(SocialAuthorizationError) as captured:
        service.decide_channel_invite(bob, channel.channel_id, accept=True)
    assert captured.value.reason is SocialReasonCode.MEMBERSHIP_REQUIRED


def test_blocked_pair_freezes_group_delivery_even_for_another_member() -> None:
    _, state, service, alice, bob = setup()
    charlie = provision(state, CHARLIE, CHARLIE_DEVICE)
    channel = service.create_private_channel(alice)
    service.invite_channel_member(alice, channel.channel_id, BOB)
    service.decide_channel_invite(bob, channel.channel_id, accept=True)
    service.invite_channel_member(alice, channel.channel_id, CHARLIE)
    _, conversation = service.decide_channel_invite(
        charlie, channel.channel_id, accept=True
    )
    assert conversation is not None
    service.block_account(alice, BOB)
    with pytest.raises(SocialAuthorizationError) as captured:
        service.record_message_metadata(
            charlie,
            message(
                conversation.conversation_id,
                charlie,
                envelope_seed="9",
                message_seed="a",
                key_version=conversation.current_key_version,
            ),
        )
    assert captured.value.reason is SocialReasonCode.CONVERSATION_ACCESS_DENIED
