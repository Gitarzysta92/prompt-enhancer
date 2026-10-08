"""Narrow storage, identity and cryptography ports for private social use cases.

Every persistent method is scoped by a social organization identifier.  The
ports accept metadata contracts only; there is no method that can persist a
message body, ciphertext buffer, analyzer identifier, display name, network
address, credential or private key.
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol

from .contracts import (
    BlockRecord,
    ChannelMembership,
    Conversation,
    ConversationReadState,
    E2eeEnvelopeMetadata,
    FriendRequest,
    Friendship,
    MessageDeletionTombstone,
    MessageReaction,
    PrivateChannel,
    RelationshipPresence,
    SocialAccount,
    SocialAuditEvent,
    SocialDeletionReceipt,
    SocialDevice,
    SocialOrganizationMembership,
    SocialTeam,
    SocialTeamMembership,
    VerifiedSocialPrincipal,
)


class SocialTransaction(Protocol):
    def __enter__(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class SocialDirectoryPort(Protocol):
    def account(self, organization_id: str, account_id: str) -> SocialAccount | None: ...

    def membership(
        self, organization_id: str, account_id: str
    ) -> SocialOrganizationMembership | None: ...

    def device(self, organization_id: str, device_id: str) -> SocialDevice | None: ...

    def accounts_exist(self, organization_id: str, account_ids: tuple[str, ...]) -> bool: ...

    def team(self, organization_id: str, team_id: str) -> SocialTeam | None: ...

    def team_membership(
        self, organization_id: str, team_id: str, account_id: str
    ) -> SocialTeamMembership | None: ...

    def revoke_device(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> SocialDevice: ...

    def delete_account(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> SocialAccount: ...

    def save_deletion_receipt(
        self, receipt: SocialDeletionReceipt
    ) -> SocialDeletionReceipt: ...

    def deletion_receipt(
        self, organization_id: str, account_id: str
    ) -> SocialDeletionReceipt | None: ...


class SocialGraphPort(Protocol):
    def friend_request(
        self, organization_id: str, request_id: str
    ) -> FriendRequest | None: ...

    def pending_between(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> FriendRequest | None: ...

    def save_friend_request(self, request: FriendRequest) -> FriendRequest: ...

    def friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> Friendship | None: ...

    def save_friendship(self, friendship: Friendship) -> Friendship: ...

    def remove_friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool: ...

    def block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> BlockRecord | None: ...

    def either_blocked(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool: ...

    def save_block(self, block: BlockRecord) -> BlockRecord: ...

    def remove_block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> bool: ...

    def remove_account_relationships(
        self, organization_id: str, account_id: str
    ) -> int: ...


class ConversationPort(Protocol):
    def channel(
        self, organization_id: str, channel_id: str
    ) -> PrivateChannel | None: ...

    def save_channel(self, channel: PrivateChannel) -> PrivateChannel: ...

    def conversation(
        self, organization_id: str, conversation_id: str
    ) -> Conversation | None: ...

    def save_conversation(self, conversation: Conversation) -> Conversation: ...

    def conversation_for_channel(
        self, organization_id: str, channel_id: str
    ) -> Conversation | None: ...

    def remove_conversation(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        now: datetime,
    ) -> bool: ...

    def conversations_for_account(
        self, organization_id: str, account_id: str
    ) -> tuple[Conversation, ...]: ...

    def channel_membership(
        self, organization_id: str, channel_id: str, account_id: str
    ) -> ChannelMembership | None: ...

    def channel_memberships(
        self, organization_id: str, channel_id: str
    ) -> tuple[ChannelMembership, ...]: ...

    def save_channel_membership(
        self, membership: ChannelMembership
    ) -> ChannelMembership: ...

    def remove_account_memberships(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> int: ...


class MessageMetadataPort(Protocol):
    def latest_message(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> E2eeEnvelopeMetadata | None: ...

    def has_message_tombstone(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> bool: ...

    def envelope(
        self, organization_id: str, envelope_id: str
    ) -> E2eeEnvelopeMetadata | None: ...

    def append_message_metadata(
        self, metadata: E2eeEnvelopeMetadata, *, accepted_at: datetime
    ) -> E2eeEnvelopeMetadata: ...

    def save_reaction(self, reaction: MessageReaction) -> MessageReaction: ...

    def read_state(
        self, organization_id: str, conversation_id: str, account_id: str
    ) -> ConversationReadState | None: ...

    def save_read_state(
        self, state: ConversationReadState
    ) -> ConversationReadState: ...

    def tombstone_account_messages(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> tuple[MessageDeletionTombstone, ...]: ...

    def remove_account_auxiliary_metadata(
        self, organization_id: str, account_id: str
    ) -> int: ...


class PresencePort(Protocol):
    def save_presence(self, presence: RelationshipPresence) -> RelationshipPresence: ...

    def presence(
        self,
        organization_id: str,
        subject_account_id: str,
        audience_account_id: str,
        *,
        now: datetime,
    ) -> RelationshipPresence | None: ...

    def remove_account_presence(self, organization_id: str, account_id: str) -> int: ...


class SocialAuditPort(Protocol):
    def append(self, event: SocialAuditEvent) -> SocialAuditEvent: ...

    def recent(
        self, organization_id: str, *, limit: int
    ) -> tuple[SocialAuditEvent, ...]: ...


class SocialIdentifierPort(Protocol):
    def issue(self, namespace: str) -> str: ...


class SocialPrincipalResolver(Protocol):
    """Production implementation must authenticate a device out of band."""

    def resolve(self, opaque_credential: str) -> VerifiedSocialPrincipal | None: ...


class LocalMessageCryptoPort(Protocol):
    """Ephemeral local E2EE boundary; persistent adapters never see bytes.

    A production implementation must use a reviewed library for Ed25519,
    X25519 and AEAD and must define an independently reviewed forward-secrecy
    protocol.  This application foundation provides no implementation.
    """

    @property
    def production_ready(self) -> bool: ...

    @property
    def forward_secrecy(self) -> bool: ...

    def verify_authenticated_envelope(
        self, principal: VerifiedSocialPrincipal, metadata: E2eeEnvelopeMetadata
    ) -> bool: ...


__all__ = [
    "ConversationPort",
    "LocalMessageCryptoPort",
    "MessageMetadataPort",
    "PresencePort",
    "SocialAuditPort",
    "SocialDirectoryPort",
    "SocialGraphPort",
    "SocialIdentifierPort",
    "SocialPrincipalResolver",
    "SocialTransaction",
]
