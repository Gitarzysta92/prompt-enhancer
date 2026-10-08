"""Single-process development adapters for the private social contracts.

The adapter is intentionally volatile and content-free.  It proves transaction
and policy behavior but is not a server, an identity provider, a durable sync
engine, or an E2EE implementation.  Every collection is tenant scoped and all
operations share one re-entrant lock.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import secrets
import threading
from types import TracebackType

from ...application.social.contracts import (
    BlockRecord,
    ChannelMembership,
    Conversation,
    ConversationKind,
    ConversationReadState,
    DeviceState,
    E2eeEnvelopeMetadata,
    FriendRequest,
    FriendRequestState,
    Friendship,
    MessageDeletionTombstone,
    MessageOperation,
    MessageReaction,
    PrivateChannel,
    RelationshipPresence,
    SocialAccount,
    SocialAccountState,
    SocialAuditEvent,
    SocialDeletionReceipt,
    SocialDevice,
    SocialMembershipState,
    SocialOrganizationMembership,
    SocialTeam,
    SocialTeamMembership,
)
from ...application.social.service import SocialService, SocialStores


@dataclass(frozen=True, slots=True)
class DevelopmentSocialTransaction:
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


@dataclass(frozen=True, slots=True)
class RandomSocialIdentifierFactory:
    def issue(self, namespace: str) -> str:
        # Namespace deliberately affects no externally visible identifier; it
        # is present only to prevent callers from requesting an untyped ID.
        if not namespace or len(namespace) > 64 or not namespace.replace("-", "").isalnum():
            raise ValueError("social identifier namespace is invalid")
        return f"soc_{secrets.token_hex(32)}"


@dataclass(slots=True)
class DevelopmentSocialState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    accounts: dict[tuple[str, str], SocialAccount] = field(default_factory=dict)
    memberships: dict[tuple[str, str], SocialOrganizationMembership] = field(
        default_factory=dict
    )
    teams: dict[tuple[str, str], SocialTeam] = field(default_factory=dict)
    team_memberships: dict[tuple[str, str, str], SocialTeamMembership] = field(
        default_factory=dict
    )
    devices: dict[tuple[str, str], SocialDevice] = field(default_factory=dict)
    revoked_device_ids: set[tuple[str, str]] = field(default_factory=set)
    requests: dict[tuple[str, str], FriendRequest] = field(default_factory=dict)
    friendships: dict[tuple[str, str, str], Friendship] = field(default_factory=dict)
    blocks: dict[tuple[str, str, str], BlockRecord] = field(default_factory=dict)
    conversations: dict[tuple[str, str], Conversation] = field(default_factory=dict)
    channels: dict[tuple[str, str], PrivateChannel] = field(default_factory=dict)
    channel_membership_records: dict[tuple[str, str, str], ChannelMembership] = field(
        default_factory=dict
    )
    envelopes: dict[tuple[str, str], E2eeEnvelopeMetadata] = field(
        default_factory=dict
    )
    message_history: dict[
        tuple[str, str, str], list[E2eeEnvelopeMetadata]
    ] = field(default_factory=dict)
    message_tombstones: dict[
        tuple[str, str, str], MessageDeletionTombstone
    ] = field(default_factory=dict)
    reactions: dict[tuple[str, str, str, str, str], MessageReaction] = field(
        default_factory=dict
    )
    read_states: dict[tuple[str, str, str], ConversationReadState] = field(
        default_factory=dict
    )
    presences: dict[tuple[str, str, str], RelationshipPresence] = field(
        default_factory=dict
    )
    audits: list[SocialAuditEvent] = field(default_factory=list)
    deletion_receipts: dict[tuple[str, str], SocialDeletionReceipt] = field(
        default_factory=dict
    )

    # Out-of-band development provisioning. No credential or remote endpoint is
    # created, and callers must supply already validated synthetic contracts.
    def provision_account(
        self,
        account: SocialAccount,
        membership: SocialOrganizationMembership,
        devices: tuple[SocialDevice, ...],
    ) -> None:
        if (
            membership.organization_id != account.organization_id
            or membership.account_id != account.account_id
            or any(
                device.organization_id != account.organization_id
                or device.account_id != account.account_id
                for device in devices
            )
        ):
            raise ValueError("social provisioning records are not bound")
        with self.lock:
            account_key = (account.organization_id, account.account_id)
            if account_key in self.accounts:
                raise ValueError("social account already provisioned")
            device_keys = tuple(
                (device.organization_id, device.device_id) for device in devices
            )
            if len(device_keys) != len(set(device_keys)) or any(
                key in self.devices or key in self.revoked_device_ids
                for key in device_keys
            ):
                raise ValueError("social device already provisioned")
            self.accounts[account_key] = account
            self.memberships[account_key] = membership
            for device in devices:
                key = (device.organization_id, device.device_id)
                self.devices[key] = device

    def provision_team(
        self,
        team: SocialTeam,
        memberships: tuple[SocialTeamMembership, ...],
    ) -> None:
        if any(
            membership.organization_id != team.organization_id
            or membership.team_id != team.team_id
            for membership in memberships
        ):
            raise ValueError("social team memberships are not bound")
        if not any(
            membership.account_id == team.owner_account_id
            and membership.state is SocialMembershipState.ACTIVE
            for membership in memberships
        ):
            raise ValueError("social team owner requires active membership")
        with self.lock:
            key = (team.organization_id, team.team_id)
            if key in self.teams:
                raise ValueError("social team already provisioned")
            if any(
                (team.organization_id, membership.account_id) not in self.accounts
                for membership in memberships
            ):
                raise ValueError("social team member is unavailable")
            self.teams[key] = team
            for membership in memberships:
                self.team_memberships[
                    (
                        membership.organization_id,
                        membership.team_id,
                        membership.account_id,
                    )
                ] = membership

    # Directory port -----------------------------------------------------
    def account(self, organization_id: str, account_id: str) -> SocialAccount | None:
        with self.lock:
            return self.accounts.get((organization_id, account_id))

    def membership(
        self, organization_id: str, account_id: str
    ) -> SocialOrganizationMembership | None:
        with self.lock:
            return self.memberships.get((organization_id, account_id))

    def device(self, organization_id: str, device_id: str) -> SocialDevice | None:
        with self.lock:
            return self.devices.get((organization_id, device_id))

    def accounts_exist(self, organization_id: str, account_ids: tuple[str, ...]) -> bool:
        with self.lock:
            return all((organization_id, account_id) in self.accounts for account_id in account_ids)

    def team(self, organization_id: str, team_id: str) -> SocialTeam | None:
        with self.lock:
            return self.teams.get((organization_id, team_id))

    def team_membership(
        self, organization_id: str, team_id: str, account_id: str
    ) -> SocialTeamMembership | None:
        with self.lock:
            return self.team_memberships.get(
                (organization_id, team_id, account_id)
            )

    def revoke_device(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> SocialDevice:
        with self.lock:
            key = (organization_id, device_id)
            device = self.devices.get(key)
            if device is None:
                raise ValueError("social device unavailable")
            revoked = SocialDevice.model_validate(
                {
                    **device.model_dump(mode="python"),
                    "state": DeviceState.REVOKED,
                    "revoked_at": now,
                }
            )
            del self.devices[key]
            self.revoked_device_ids.add(key)
            return revoked

    def delete_account(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> SocialAccount:
        with self.lock:
            key = (organization_id, account_id)
            account = self.accounts.get(key)
            if account is None:
                raise ValueError("social account unavailable")
            if account.state is SocialAccountState.DELETED:
                return account
            deleted = SocialAccount.model_validate(
                {
                    **account.model_dump(mode="python"),
                    "state": SocialAccountState.DELETED,
                    "deleted_at": now,
                }
            )
            self.accounts[key] = deleted
            membership = self.memberships.get(key)
            if membership is not None:
                self.memberships[key] = SocialOrganizationMembership.model_validate(
                    {
                        **membership.model_dump(mode="python"),
                        "state": SocialMembershipState.REVOKED,
                        "revoked_at": now,
                    }
                )
            for device_key, device in tuple(self.devices.items()):
                if device_key[0] == organization_id and device.account_id == account_id:
                    del self.devices[device_key]
                    self.revoked_device_ids.add(device_key)
            return deleted

    def save_deletion_receipt(
        self, receipt: SocialDeletionReceipt
    ) -> SocialDeletionReceipt:
        with self.lock:
            key = (receipt.organization_id, receipt.account_id)
            if key in self.deletion_receipts:
                raise ValueError("social deletion receipt already recorded")
            self.deletion_receipts[key] = receipt
            return receipt

    def deletion_receipt(
        self, organization_id: str, account_id: str
    ) -> SocialDeletionReceipt | None:
        with self.lock:
            return self.deletion_receipts.get((organization_id, account_id))

    # Social graph port --------------------------------------------------
    def friend_request(
        self, organization_id: str, request_id: str
    ) -> FriendRequest | None:
        with self.lock:
            return self.requests.get((organization_id, request_id))

    def pending_between(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> FriendRequest | None:
        with self.lock:
            matches = tuple(
                request
                for (tenant, _), request in self.requests.items()
                if tenant == organization_id
                and request.state is FriendRequestState.PENDING
                and {
                    request.requester_account_id,
                    request.recipient_account_id,
                }
                == {first_account_id, second_account_id}
            )
            return min(matches, key=lambda item: item.created_at) if matches else None

    def save_friend_request(self, request: FriendRequest) -> FriendRequest:
        with self.lock:
            self.requests[(request.organization_id, request.request_id)] = request
            return request

    @staticmethod
    def _pair(
        organization_id: str, first_account_id: str, second_account_id: str
    ) -> tuple[str, str, str]:
        first, second = sorted((first_account_id, second_account_id))
        return organization_id, first, second

    def friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> Friendship | None:
        with self.lock:
            return self.friendships.get(
                self._pair(organization_id, first_account_id, second_account_id)
            )

    def save_friendship(self, friendship: Friendship) -> Friendship:
        with self.lock:
            key = (
                friendship.organization_id,
                friendship.first_account_id,
                friendship.second_account_id,
            )
            existing = self.friendships.get(key)
            if existing is not None and existing != friendship:
                raise ValueError("friendship conflict")
            self.friendships[key] = friendship
            return friendship

    def remove_friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool:
        with self.lock:
            key = self._pair(organization_id, first_account_id, second_account_id)
            return self.friendships.pop(key, None) is not None

    def block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> BlockRecord | None:
        with self.lock:
            return self.blocks.get(
                (organization_id, blocker_account_id, blocked_account_id)
            )

    def either_blocked(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool:
        with self.lock:
            return (
                organization_id,
                first_account_id,
                second_account_id,
            ) in self.blocks or (
                organization_id,
                second_account_id,
                first_account_id,
            ) in self.blocks

    def save_block(self, block: BlockRecord) -> BlockRecord:
        with self.lock:
            self.blocks[
                (
                    block.organization_id,
                    block.blocker_account_id,
                    block.blocked_account_id,
                )
            ] = block
            return block

    def remove_block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> bool:
        with self.lock:
            return self.blocks.pop(
                (organization_id, blocker_account_id, blocked_account_id), None
            ) is not None

    def remove_account_relationships(
        self, organization_id: str, account_id: str
    ) -> int:
        with self.lock:
            count = 0
            for collection in (self.requests, self.friendships, self.blocks):
                for key, record in tuple(collection.items()):
                    if key[0] != organization_id:
                        continue
                    values = record.model_dump(mode="python")
                    if account_id in values.values():
                        del collection[key]
                        count += 1
            return count

    # Conversation port --------------------------------------------------
    def channel(
        self, organization_id: str, channel_id: str
    ) -> PrivateChannel | None:
        with self.lock:
            return self.channels.get((organization_id, channel_id))

    def save_channel(self, channel: PrivateChannel) -> PrivateChannel:
        with self.lock:
            key = (channel.organization_id, channel.channel_id)
            existing = self.channels.get(key)
            if existing is not None and existing != channel:
                raise ValueError("private channel conflict")
            self.channels[key] = channel
            return channel

    def conversation(
        self, organization_id: str, conversation_id: str
    ) -> Conversation | None:
        with self.lock:
            return self.conversations.get((organization_id, conversation_id))

    def save_conversation(self, conversation: Conversation) -> Conversation:
        with self.lock:
            key = (conversation.organization_id, conversation.conversation_id)
            existing = self.conversations.get(key)
            if existing is not None and existing != conversation:
                if (
                    existing.kind is not conversation.kind
                    or existing.channel_id != conversation.channel_id
                    or existing.created_at != conversation.created_at
                    or existing.kind is ConversationKind.DIRECT
                    or conversation.current_key_version
                    != existing.current_key_version + 1
                ):
                    raise ValueError("conversation conflict")
            self.conversations[key] = conversation
            return conversation

    def conversation_for_channel(
        self, organization_id: str, channel_id: str
    ) -> Conversation | None:
        with self.lock:
            for (tenant, _), conversation in self.conversations.items():
                if tenant == organization_id and conversation.channel_id == channel_id:
                    return conversation
            return None

    def remove_conversation(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        now: datetime,
    ) -> bool:
        with self.lock:
            return self.conversations.pop(
                (organization_id, conversation_id), None
            ) is not None

    def conversations_for_account(
        self, organization_id: str, account_id: str
    ) -> tuple[Conversation, ...]:
        with self.lock:
            return tuple(
                conversation
                for (tenant, _), conversation in sorted(self.conversations.items())
                if tenant == organization_id
                and account_id in conversation.member_account_ids
            )

    def channel_membership(
        self, organization_id: str, channel_id: str, account_id: str
    ) -> ChannelMembership | None:
        with self.lock:
            return self.channel_membership_records.get(
                (organization_id, channel_id, account_id)
            )

    def channel_memberships(
        self, organization_id: str, channel_id: str
    ) -> tuple[ChannelMembership, ...]:
        with self.lock:
            return tuple(
                membership
                for (tenant, selected_channel, _), membership in sorted(
                    self.channel_membership_records.items()
                )
                if tenant == organization_id and selected_channel == channel_id
            )

    def save_channel_membership(
        self, membership: ChannelMembership
    ) -> ChannelMembership:
        with self.lock:
            self.channel_membership_records[
                (
                    membership.organization_id,
                    membership.channel_id,
                    membership.account_id,
                )
            ] = membership
            return membership

    def remove_account_memberships(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> int:
        with self.lock:
            removed = 0
            for key in tuple(self.team_memberships):
                if key[0] == organization_id and key[2] == account_id:
                    del self.team_memberships[key]
                    removed += 1
            for key in tuple(self.channel_membership_records):
                if key[0] == organization_id and key[2] == account_id:
                    del self.channel_membership_records[key]
                    removed += 1
            for key, conversation in tuple(self.conversations.items()):
                if (
                    key[0] != organization_id
                    or account_id not in conversation.member_account_ids
                ):
                    continue
                removed += 1
                remaining_members = tuple(
                    member
                    for member in conversation.member_account_ids
                    if member != account_id
                )
                if (
                    conversation.kind is ConversationKind.DIRECT
                    or len(remaining_members) < 2
                ):
                    del self.conversations[key]
                    continue
                self.conversations[key] = Conversation.model_validate(
                    {
                        **conversation.model_dump(mode="python"),
                        "member_account_ids": remaining_members,
                        "current_key_version": conversation.current_key_version + 1,
                    }
                )
            return removed

    # Message metadata port ---------------------------------------------
    def latest_message(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> E2eeEnvelopeMetadata | None:
        with self.lock:
            history = self.message_history.get(
                (organization_id, conversation_id, message_id), []
            )
            return history[-1] if history else None

    def has_message_tombstone(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> bool:
        with self.lock:
            return (
                organization_id,
                conversation_id,
                message_id,
            ) in self.message_tombstones

    def envelope(
        self, organization_id: str, envelope_id: str
    ) -> E2eeEnvelopeMetadata | None:
        with self.lock:
            return self.envelopes.get((organization_id, envelope_id))

    def append_message_metadata(
        self, metadata: E2eeEnvelopeMetadata, *, accepted_at: datetime
    ) -> E2eeEnvelopeMetadata:
        with self.lock:
            envelope_key = (metadata.organization_id, metadata.envelope_id)
            existing = self.envelopes.get(envelope_key)
            if existing is not None:
                if existing == metadata:
                    return existing
                raise ValueError("message envelope replay conflict")
            self.envelopes[envelope_key] = metadata
            message_key = (
                metadata.organization_id,
                metadata.conversation_id,
                metadata.message_id,
            )
            self.message_history.setdefault(message_key, []).append(metadata)
            if metadata.operation is MessageOperation.DELETE:
                self.message_tombstones[message_key] = MessageDeletionTombstone(
                    organization_id=metadata.organization_id,
                    conversation_id=metadata.conversation_id,
                    message_id=metadata.message_id,
                    sender_account_id=metadata.sender_account_id,
                    deleted_at=accepted_at,
                )
            return metadata

    def save_reaction(self, reaction: MessageReaction) -> MessageReaction:
        with self.lock:
            key = (
                reaction.organization_id,
                reaction.conversation_id,
                reaction.message_id,
                reaction.actor_account_id,
                reaction.reaction.value,
            )
            self.reactions[key] = reaction
            return reaction

    def read_state(
        self, organization_id: str, conversation_id: str, account_id: str
    ) -> ConversationReadState | None:
        with self.lock:
            return self.read_states.get(
                (organization_id, conversation_id, account_id)
            )

    def save_read_state(
        self, state: ConversationReadState
    ) -> ConversationReadState:
        with self.lock:
            self.read_states[
                (state.organization_id, state.conversation_id, state.account_id)
            ] = state
            return state

    def tombstone_account_messages(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> tuple[MessageDeletionTombstone, ...]:
        with self.lock:
            tombstones: list[MessageDeletionTombstone] = []
            for key, history in tuple(self.message_history.items()):
                if key[0] != organization_id or not history:
                    continue
                if history[0].sender_account_id != account_id:
                    continue
                tombstone = MessageDeletionTombstone(
                    organization_id=organization_id,
                    conversation_id=key[1],
                    message_id=key[2],
                    sender_account_id=history[0].sender_account_id,
                    deleted_at=now,
                )
                self.message_tombstones[key] = tombstone
                # Remove every ciphertext digest/size-bearing revision. The
                # content-free tombstone alone survives local deletion.
                for envelope in history:
                    self.envelopes.pop(
                        (organization_id, envelope.envelope_id), None
                    )
                del self.message_history[key]
                tombstones.append(tombstone)
            return tuple(tombstones)

    def remove_account_auxiliary_metadata(
        self, organization_id: str, account_id: str
    ) -> int:
        with self.lock:
            removed = 0
            for collection in (self.reactions, self.read_states):
                for key in tuple(collection):
                    if key[0] != organization_id:
                        continue
                    actor_or_account = key[3] if len(key) > 3 else key[2]
                    if actor_or_account == account_id:
                        del collection[key]
                        removed += 1
            return removed

    # Presence port ------------------------------------------------------
    def save_presence(self, presence: RelationshipPresence) -> RelationshipPresence:
        with self.lock:
            self.presences[
                (
                    presence.organization_id,
                    presence.subject_account_id,
                    presence.audience_account_id,
                )
            ] = presence
            return presence

    def presence(
        self,
        organization_id: str,
        subject_account_id: str,
        audience_account_id: str,
        *,
        now: datetime,
    ) -> RelationshipPresence | None:
        with self.lock:
            key = (organization_id, subject_account_id, audience_account_id)
            presence = self.presences.get(key)
            if presence is None:
                return None
            if presence.expires_at <= now:
                self.presences.pop(key, None)
                return None
            return presence

    def remove_account_presence(self, organization_id: str, account_id: str) -> int:
        with self.lock:
            keys = tuple(
                key
                for key in self.presences
                if key[0] == organization_id and account_id in key[1:]
            )
            for key in keys:
                del self.presences[key]
            return len(keys)

    # Audit port ---------------------------------------------------------
    def append(self, event: SocialAuditEvent) -> SocialAuditEvent:
        with self.lock:
            self.audits.append(event)
            return event

    def recent(
        self, organization_id: str, *, limit: int
    ) -> tuple[SocialAuditEvent, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("social audit limit is invalid")
        with self.lock:
            return tuple(
                event
                for event in reversed(self.audits)
                if event.organization_id == organization_id
            )[:limit]


@dataclass(frozen=True, slots=True)
class FailClosedMessageCrypto:
    """Default adapter: it cannot encrypt, decrypt, sign or verify anything."""

    production_ready: bool = False
    forward_secrecy: bool = False

    def verify_authenticated_envelope(
        self, principal: object, metadata: object
    ) -> bool:
        raise NotImplementedError("reviewed E2EE adapter is unavailable")


@dataclass(frozen=True, slots=True)
class DevelopmentSocialFoundation:
    state: DevelopmentSocialState
    service: SocialService


def create_development_social_foundation(
    clock: Callable[[], datetime],
) -> DevelopmentSocialFoundation:
    state = DevelopmentSocialState()
    transaction = DevelopmentSocialTransaction(state.lock)
    identifiers = RandomSocialIdentifierFactory()
    service = SocialService(
        stores=SocialStores(
            transaction=transaction,
            directory=state,
            graph=state,
            conversations=state,
            messages=state,
            presence=state,
            audit=state,
        ),
        identifiers=identifiers,
        crypto=FailClosedMessageCrypto(),
        clock=clock,
    )
    return DevelopmentSocialFoundation(state=state, service=service)


__all__ = [
    "DevelopmentSocialFoundation",
    "DevelopmentSocialState",
    "DevelopmentSocialTransaction",
    "FailClosedMessageCrypto",
    "RandomSocialIdentifierFactory",
    "create_development_social_foundation",
]
