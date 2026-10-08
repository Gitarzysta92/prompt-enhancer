"""Transactional, default-deny social graph and message-metadata use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .contracts import (
    BlockRecord,
    ChannelMembership,
    ChannelMembershipState,
    ChannelRole,
    Conversation,
    ConversationKind,
    ConversationReadState,
    DeviceState,
    E2eeEnvelopeMetadata,
    FriendRequest,
    FriendRequestState,
    Friendship,
    MessageOperation,
    MessageReaction,
    MAX_CLIENT_CLOCK_SKEW,
    PrivateChannel,
    RelationshipPresence,
    SocialAccountState,
    SocialAuditAction,
    SocialAuditDecision,
    SocialAuditEvent,
    SocialDeletionReceipt,
    SocialMembershipState,
    SocialReasonCode,
    VerifiedSocialPrincipal,
)
from .errors import (
    SocialAuthorizationError,
    SocialConflictError,
    SocialCryptoUnavailableError,
)
from .ports import (
    ConversationPort,
    LocalMessageCryptoPort,
    MessageMetadataPort,
    PresencePort,
    SocialAuditPort,
    SocialDirectoryPort,
    SocialGraphPort,
    SocialIdentifierPort,
    SocialTransaction,
)


@dataclass(frozen=True, slots=True)
class SocialStores:
    transaction: SocialTransaction
    directory: SocialDirectoryPort
    graph: SocialGraphPort
    conversations: ConversationPort
    messages: MessageMetadataPort
    presence: PresencePort
    audit: SocialAuditPort


@dataclass(frozen=True, slots=True)
class SocialService:
    """Operate on minimized social metadata without handling message bytes."""

    stores: SocialStores
    identifiers: SocialIdentifierPort
    crypto: LocalMessageCryptoPort
    clock: Callable[[], datetime]

    def _principal(self, caller: VerifiedSocialPrincipal) -> None:
        account = self.stores.directory.account(
            caller.organization_id, caller.account_id
        )
        membership = self.stores.directory.membership(
            caller.organization_id, caller.account_id
        )
        device = self.stores.directory.device(
            caller.organization_id, caller.device_id
        )
        if (
            account is None
            or account.state is not SocialAccountState.ACTIVE
            or membership is None
            or membership.state is not SocialMembershipState.ACTIVE
        ):
            raise SocialAuthorizationError(SocialReasonCode.PRINCIPAL_INACTIVE)
        if (
            device is None
            or device.state is not DeviceState.ACTIVE
            or device.account_id != caller.account_id
        ):
            raise SocialAuthorizationError(SocialReasonCode.DEVICE_INACTIVE)

    def _relationship_target(
        self, caller: VerifiedSocialPrincipal, target_account_id: str
    ) -> None:
        """Apply block policy before target existence to resist enumeration."""

        if self.stores.graph.either_blocked(
            caller.organization_id, caller.account_id, target_account_id
        ):
            raise SocialAuthorizationError(
                SocialReasonCode.RELATIONSHIP_UNAVAILABLE
            )
        target = self.stores.directory.account(
            caller.organization_id, target_account_id
        )
        membership = self.stores.directory.membership(
            caller.organization_id, target_account_id
        )
        if (
            target is None
            or target.state is not SocialAccountState.ACTIVE
            or membership is None
            or membership.state is not SocialMembershipState.ACTIVE
        ):
            # Deliberately identical to the block answer.
            raise SocialAuthorizationError(
                SocialReasonCode.RELATIONSHIP_UNAVAILABLE
            )

    def _audit(
        self,
        caller: VerifiedSocialPrincipal,
        action: SocialAuditAction,
        *,
        target_account_id: str | None = None,
        decision: SocialAuditDecision = SocialAuditDecision.ALLOW,
        reason: SocialReasonCode = SocialReasonCode.ALLOWED,
        now: datetime | None = None,
    ) -> SocialAuditEvent:
        event = SocialAuditEvent(
            organization_id=caller.organization_id,
            audit_id=self.identifiers.issue("social-audit"),
            actor_account_id=caller.account_id,
            actor_device_id=caller.device_id,
            target_account_id=target_account_id,
            action=action,
            decision=decision,
            reason=reason,
            occurred_at=now or self.clock(),
        )
        return self.stores.audit.append(event)

    def request_friend(
        self,
        caller: VerifiedSocialPrincipal,
        target_account_id: str,
        *,
        expires_at: datetime,
    ) -> FriendRequest:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._relationship_target(caller, target_account_id)
            if caller.account_id == target_account_id:
                raise SocialAuthorizationError(
                    SocialReasonCode.RELATIONSHIP_UNAVAILABLE
                )
            if self.stores.graph.friendship(
                caller.organization_id, caller.account_id, target_account_id
            ) is not None:
                raise SocialConflictError(SocialReasonCode.REQUEST_STATE_CONFLICT)
            pending = self.stores.graph.pending_between(
                caller.organization_id, caller.account_id, target_account_id
            )
            if pending is not None:
                # A repeated command observes the original pending request. It
                # never creates a second notification or timing channel.
                return pending
            request = FriendRequest(
                organization_id=caller.organization_id,
                request_id=self.identifiers.issue("friend-request"),
                requester_account_id=caller.account_id,
                recipient_account_id=target_account_id,
                state=FriendRequestState.PENDING,
                created_at=now,
                expires_at=expires_at,
            )
            stored = self.stores.graph.save_friend_request(request)
            self._audit(
                caller,
                SocialAuditAction.FRIEND_REQUESTED,
                target_account_id=target_account_id,
                now=now,
            )
            return stored

    def decide_friend_request(
        self,
        caller: VerifiedSocialPrincipal,
        request_id: str,
        *,
        accept: bool,
    ) -> FriendRequest:
        now = self.clock()
        action = (
            SocialAuditAction.FRIEND_REQUEST_ACCEPTED
            if accept
            else SocialAuditAction.FRIEND_REQUEST_DECLINED
        )
        target: str | None = None
        with self.stores.transaction:
            self._principal(caller)
            request = self.stores.graph.friend_request(
                caller.organization_id, request_id
            )
            if request is None or request.recipient_account_id != caller.account_id:
                raise SocialAuthorizationError(
                    SocialReasonCode.RELATIONSHIP_UNAVAILABLE
                )
            target = request.requester_account_id
            self._relationship_target(caller, target)
            desired = (
                FriendRequestState.ACCEPTED
                if accept
                else FriendRequestState.DECLINED
            )
            if request.state is desired:
                return request
            if request.state is not FriendRequestState.PENDING:
                raise SocialConflictError(SocialReasonCode.REQUEST_STATE_CONFLICT)
            if request.expires_at <= now:
                expired = FriendRequest.model_validate(
                    {
                        **request.model_dump(mode="python"),
                        "state": FriendRequestState.EXPIRED,
                        "decided_at": now,
                    }
                )
                self.stores.graph.save_friend_request(expired)
                raise SocialConflictError(SocialReasonCode.REQUEST_STATE_CONFLICT)
            decided = FriendRequest.model_validate(
                {
                    **request.model_dump(mode="python"),
                    "state": desired,
                    "decided_at": now,
                }
            )
            self.stores.graph.save_friend_request(decided)
            if accept:
                first, second = sorted(
                    (request.requester_account_id, request.recipient_account_id)
                )
                self.stores.graph.save_friendship(
                    Friendship(
                        organization_id=caller.organization_id,
                        first_account_id=first,
                        second_account_id=second,
                        accepted_request_id=request.request_id,
                        created_at=now,
                    )
                )
            self._audit(caller, action, target_account_id=target, now=now)
            return decided

    def cancel_friend_request(
        self, caller: VerifiedSocialPrincipal, request_id: str
    ) -> FriendRequest:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            request = self.stores.graph.friend_request(
                caller.organization_id, request_id
            )
            if request is None or request.requester_account_id != caller.account_id:
                raise SocialAuthorizationError(
                    SocialReasonCode.RELATIONSHIP_UNAVAILABLE
                )
            # Do the block check before exposing whether the pending state still
            # exists. Both answers are the same closed reason.
            self._relationship_target(caller, request.recipient_account_id)
            if request.state is FriendRequestState.CANCELLED:
                return request
            if request.state is not FriendRequestState.PENDING:
                raise SocialConflictError(SocialReasonCode.REQUEST_STATE_CONFLICT)
            cancelled = FriendRequest.model_validate(
                {
                    **request.model_dump(mode="python"),
                    "state": FriendRequestState.CANCELLED,
                    "decided_at": now,
                }
            )
            self.stores.graph.save_friend_request(cancelled)
            self._audit(
                caller,
                SocialAuditAction.FRIEND_REQUEST_CANCELLED,
                target_account_id=request.recipient_account_id,
                now=now,
            )
            return cancelled

    def remove_friend(
        self, caller: VerifiedSocialPrincipal, target_account_id: str
    ) -> bool:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._relationship_target(caller, target_account_id)
            removed = self.stores.graph.remove_friendship(
                caller.organization_id, caller.account_id, target_account_id
            )
            if not removed:
                raise SocialAuthorizationError(
                    SocialReasonCode.RELATIONSHIP_UNAVAILABLE
                )
            self._audit(
                caller,
                SocialAuditAction.FRIEND_REMOVED,
                target_account_id=target_account_id,
                now=now,
            )
            return True

    def block_account(
        self, caller: VerifiedSocialPrincipal, target_account_id: str
    ) -> BlockRecord:
        """Block atomically removes friendship and pending relationship state."""

        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            existing = self.stores.graph.block(
                caller.organization_id, caller.account_id, target_account_id
            )
            if existing is not None:
                return existing
            # A caller may block an identifier it already knows without learning
            # whether that identifier currently names an account.
            block = self.stores.graph.save_block(
                BlockRecord(
                    organization_id=caller.organization_id,
                    blocker_account_id=caller.account_id,
                    blocked_account_id=target_account_id,
                    created_at=now,
                )
            )
            self.stores.graph.remove_friendship(
                caller.organization_id, caller.account_id, target_account_id
            )
            pending = self.stores.graph.pending_between(
                caller.organization_id, caller.account_id, target_account_id
            )
            if pending is not None:
                self.stores.graph.save_friend_request(
                    FriendRequest.model_validate(
                        {
                            **pending.model_dump(mode="python"),
                            "state": FriendRequestState.CANCELLED,
                            "decided_at": now,
                        }
                    )
                )
            self._audit(
                caller,
                SocialAuditAction.ACCOUNT_BLOCKED,
                target_account_id=target_account_id,
                now=now,
            )
            return block

    def unblock_account(
        self, caller: VerifiedSocialPrincipal, target_account_id: str
    ) -> bool:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            removed = self.stores.graph.remove_block(
                caller.organization_id, caller.account_id, target_account_id
            )
            if removed:
                self._audit(
                    caller,
                    SocialAuditAction.ACCOUNT_UNBLOCKED,
                    target_account_id=target_account_id,
                    now=now,
                )
            return removed

    def create_direct_conversation(
        self, caller: VerifiedSocialPrincipal, friend_account_id: str
    ) -> Conversation:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._relationship_target(caller, friend_account_id)
            if self.stores.graph.friendship(
                caller.organization_id, caller.account_id, friend_account_id
            ) is None:
                raise SocialAuthorizationError(
                    SocialReasonCode.RELATIONSHIP_UNAVAILABLE
                )
            members = tuple(sorted((caller.account_id, friend_account_id)))
            for existing in self.stores.conversations.conversations_for_account(
                caller.organization_id, caller.account_id
            ):
                if (
                    existing.kind is ConversationKind.DIRECT
                    and existing.member_account_ids == members
                ):
                    return existing
            return self.stores.conversations.save_conversation(
                Conversation(
                    organization_id=caller.organization_id,
                    conversation_id=self.identifiers.issue("conversation"),
                    kind=ConversationKind.DIRECT,
                    member_account_ids=members,
                    current_key_version=1,
                    created_at=now,
                )
            )

    def create_private_channel(
        self,
        caller: VerifiedSocialPrincipal,
        *,
        team_id: str | None = None,
    ) -> PrivateChannel:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            if team_id is not None:
                membership = self.stores.directory.team_membership(
                    caller.organization_id, team_id, caller.account_id
                )
                if (
                    self.stores.directory.team(caller.organization_id, team_id)
                    is None
                    or membership is None
                    or membership.state is not SocialMembershipState.ACTIVE
                ):
                    raise SocialAuthorizationError(
                        SocialReasonCode.MEMBERSHIP_REQUIRED
                    )
            channel = self.stores.conversations.save_channel(
                PrivateChannel(
                    organization_id=caller.organization_id,
                    channel_id=self.identifiers.issue("private-channel"),
                    team_id=team_id,
                    owner_account_id=caller.account_id,
                    created_at=now,
                )
            )
            self.stores.conversations.save_channel_membership(
                ChannelMembership(
                    organization_id=caller.organization_id,
                    channel_id=channel.channel_id,
                    account_id=caller.account_id,
                    role=ChannelRole.OWNER,
                    state=ChannelMembershipState.ACTIVE,
                    invited_by_account_id=caller.account_id,
                    created_at=now,
                    changed_at=now,
                )
            )
            self._audit(
                caller,
                SocialAuditAction.CHANNEL_MEMBERSHIP_CHANGED,
                now=now,
            )
            return channel

    def _channel_actor(
        self, caller: VerifiedSocialPrincipal, channel_id: str
    ) -> tuple[PrivateChannel, ChannelMembership]:
        channel = self.stores.conversations.channel(
            caller.organization_id, channel_id
        )
        membership = self.stores.conversations.channel_membership(
            caller.organization_id, channel_id, caller.account_id
        )
        if (
            channel is None
            or membership is None
            or membership.state is not ChannelMembershipState.ACTIVE
        ):
            raise SocialAuthorizationError(
                SocialReasonCode.CONVERSATION_ACCESS_DENIED
            )
        return channel, membership

    def invite_channel_member(
        self,
        caller: VerifiedSocialPrincipal,
        channel_id: str,
        target_account_id: str,
    ) -> ChannelMembership:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            channel, actor = self._channel_actor(caller, channel_id)
            if actor.role not in {ChannelRole.OWNER, ChannelRole.MODERATOR}:
                raise SocialAuthorizationError(SocialReasonCode.MEMBERSHIP_REQUIRED)
            self._relationship_target(caller, target_account_id)
            if channel.team_id is not None:
                team_membership = self.stores.directory.team_membership(
                    caller.organization_id, channel.team_id, target_account_id
                )
                if (
                    team_membership is None
                    or team_membership.state is not SocialMembershipState.ACTIVE
                ):
                    raise SocialAuthorizationError(
                        SocialReasonCode.MEMBERSHIP_REQUIRED
                    )
            existing = self.stores.conversations.channel_membership(
                caller.organization_id, channel_id, target_account_id
            )
            if existing is not None and existing.state in {
                ChannelMembershipState.INVITED,
                ChannelMembershipState.ACTIVE,
            }:
                return existing
            invited = ChannelMembership(
                organization_id=caller.organization_id,
                channel_id=channel_id,
                account_id=target_account_id,
                role=ChannelRole.MEMBER,
                state=ChannelMembershipState.INVITED,
                invited_by_account_id=caller.account_id,
                created_at=now,
                changed_at=now,
            )
            stored = self.stores.conversations.save_channel_membership(invited)
            self._audit(
                caller,
                SocialAuditAction.CHANNEL_MEMBERSHIP_CHANGED,
                target_account_id=target_account_id,
                now=now,
            )
            return stored

    def decide_channel_invite(
        self,
        caller: VerifiedSocialPrincipal,
        channel_id: str,
        *,
        accept: bool,
    ) -> tuple[ChannelMembership, Conversation | None]:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            channel = self.stores.conversations.channel(
                caller.organization_id, channel_id
            )
            membership = self.stores.conversations.channel_membership(
                caller.organization_id, channel_id, caller.account_id
            )
            if (
                channel is None
                or membership is None
                or membership.state is not ChannelMembershipState.INVITED
            ):
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
            if self.stores.graph.either_blocked(
                caller.organization_id,
                caller.account_id,
                channel.owner_account_id,
            ):
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
            if accept and channel.team_id is not None:
                team_membership = self.stores.directory.team_membership(
                    caller.organization_id, channel.team_id, caller.account_id
                )
                if (
                    team_membership is None
                    or team_membership.state is not SocialMembershipState.ACTIVE
                ):
                    raise SocialAuthorizationError(
                        SocialReasonCode.MEMBERSHIP_REQUIRED
                    )
            decided = ChannelMembership.model_validate(
                {
                    **membership.model_dump(mode="python"),
                    "state": (
                        ChannelMembershipState.ACTIVE
                        if accept
                        else ChannelMembershipState.LEFT
                    ),
                    "changed_at": now,
                }
            )
            self.stores.conversations.save_channel_membership(decided)
            conversation = self._rebuild_group_conversation(
                caller.organization_id, channel_id, now=now
            )
            self._audit(
                caller,
                SocialAuditAction.CHANNEL_MEMBERSHIP_CHANGED,
                now=now,
            )
            return decided, conversation

    def remove_channel_member(
        self,
        caller: VerifiedSocialPrincipal,
        channel_id: str,
        target_account_id: str,
    ) -> tuple[ChannelMembership, Conversation | None]:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            _, actor = self._channel_actor(caller, channel_id)
            target = self.stores.conversations.channel_membership(
                caller.organization_id, channel_id, target_account_id
            )
            if (
                actor.role not in {ChannelRole.OWNER, ChannelRole.MODERATOR}
                or target is None
                or target.state is not ChannelMembershipState.ACTIVE
                or target.role is ChannelRole.OWNER
                or (
                    actor.role is ChannelRole.MODERATOR
                    and target.role is ChannelRole.MODERATOR
                )
            ):
                raise SocialAuthorizationError(SocialReasonCode.MEMBERSHIP_REQUIRED)
            removed = ChannelMembership.model_validate(
                {
                    **target.model_dump(mode="python"),
                    "state": ChannelMembershipState.REMOVED,
                    "changed_at": now,
                }
            )
            self.stores.conversations.save_channel_membership(removed)
            conversation = self._rebuild_group_conversation(
                caller.organization_id, channel_id, now=now
            )
            self._audit(
                caller,
                SocialAuditAction.CHANNEL_MEMBERSHIP_CHANGED,
                target_account_id=target_account_id,
                now=now,
            )
            return removed, conversation

    def leave_channel(
        self, caller: VerifiedSocialPrincipal, channel_id: str
    ) -> tuple[ChannelMembership, Conversation | None]:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            _, membership = self._channel_actor(caller, channel_id)
            if membership.role is ChannelRole.OWNER:
                raise SocialConflictError(SocialReasonCode.REQUEST_STATE_CONFLICT)
            left = ChannelMembership.model_validate(
                {
                    **membership.model_dump(mode="python"),
                    "state": ChannelMembershipState.LEFT,
                    "changed_at": now,
                }
            )
            self.stores.conversations.save_channel_membership(left)
            conversation = self._rebuild_group_conversation(
                caller.organization_id, channel_id, now=now
            )
            self._audit(
                caller,
                SocialAuditAction.CHANNEL_MEMBERSHIP_CHANGED,
                now=now,
            )
            return left, conversation

    def _rebuild_group_conversation(
        self, organization_id: str, channel_id: str, *, now: datetime
    ) -> Conversation | None:
        active_members = tuple(
            sorted(
                membership.account_id
                for membership in self.stores.conversations.channel_memberships(
                    organization_id, channel_id
                )
                if membership.state is ChannelMembershipState.ACTIVE
            )
        )
        existing = self.stores.conversations.conversation_for_channel(
            organization_id, channel_id
        )
        if len(active_members) < 2:
            if existing is not None:
                self.stores.conversations.remove_conversation(
                    organization_id, existing.conversation_id, now=now
                )
            return None
        if existing is None:
            return self.stores.conversations.save_conversation(
                Conversation(
                    organization_id=organization_id,
                    conversation_id=self.identifiers.issue("conversation"),
                    kind=ConversationKind.PRIVATE_GROUP,
                    member_account_ids=active_members,
                    channel_id=channel_id,
                    current_key_version=1,
                    created_at=now,
                )
            )
        if existing.member_account_ids == active_members:
            return existing
        rotated = Conversation.model_validate(
            {
                **existing.model_dump(mode="python"),
                "member_account_ids": active_members,
                "current_key_version": existing.current_key_version + 1,
            }
        )
        return self.stores.conversations.save_conversation(rotated)

    def _conversation_for_member(
        self, caller: VerifiedSocialPrincipal, conversation_id: str
    ) -> Conversation:
        conversation = self.stores.conversations.conversation(
            caller.organization_id, conversation_id
        )
        if conversation is None or caller.account_id not in conversation.member_account_ids:
            raise SocialAuthorizationError(
                SocialReasonCode.CONVERSATION_ACCESS_DENIED
            )
        if conversation.kind is ConversationKind.DIRECT:
            peer_account_id = next(
                account_id
                for account_id in conversation.member_account_ids
                if account_id != caller.account_id
            )
            if self.stores.graph.friendship(
                caller.organization_id, caller.account_id, peer_account_id
            ) is None:
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
        # Once the membership list is available, blocks override the content
        # operation. The same generic conversation denial avoids revealing who
        # blocked whom.
        for index, first in enumerate(conversation.member_account_ids):
            for second in conversation.member_account_ids[index + 1 :]:
                if self.stores.graph.either_blocked(
                    caller.organization_id, first, second
                ):
                    raise SocialAuthorizationError(
                        SocialReasonCode.CONVERSATION_ACCESS_DENIED
                    )
        return conversation

    def record_message_metadata(
        self,
        caller: VerifiedSocialPrincipal,
        metadata: E2eeEnvelopeMetadata,
    ) -> E2eeEnvelopeMetadata:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            if (
                metadata.organization_id != caller.organization_id
                or metadata.sender_account_id != caller.account_id
                or metadata.sender_device_id != caller.device_id
            ):
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
            if abs(now - metadata.created_at) > MAX_CLIENT_CLOCK_SKEW:
                raise SocialConflictError(
                    SocialReasonCode.TIMESTAMP_OUT_OF_WINDOW
                )
            conversation = self._conversation_for_member(
                caller, metadata.conversation_id
            )
            if metadata.key_version != conversation.current_key_version:
                raise SocialConflictError(SocialReasonCode.STALE_KEY_VERSION)
            existing_envelope = self.stores.messages.envelope(
                caller.organization_id, metadata.envelope_id
            )
            if existing_envelope is not None:
                if existing_envelope == metadata:
                    return existing_envelope
                raise SocialConflictError(SocialReasonCode.REQUEST_REPLAYED)
            latest = self.stores.messages.latest_message(
                caller.organization_id,
                metadata.conversation_id,
                metadata.message_id,
            )
            if metadata.operation is MessageOperation.CREATE:
                if latest is not None or self.stores.messages.has_message_tombstone(
                    caller.organization_id,
                    metadata.conversation_id,
                    metadata.message_id,
                ):
                    raise SocialConflictError(SocialReasonCode.REVISION_CONFLICT)
            else:
                if (
                    latest is None
                    or latest.operation is MessageOperation.DELETE
                    or metadata.revision != latest.revision + 1
                    or metadata.sender_account_id != latest.sender_account_id
                ):
                    raise SocialConflictError(SocialReasonCode.REVISION_CONFLICT)
            if metadata.thread_root_message_id is not None:
                root = self.stores.messages.latest_message(
                    caller.organization_id,
                    metadata.conversation_id,
                    metadata.thread_root_message_id,
                )
                if root is None or root.operation is MessageOperation.DELETE:
                    raise SocialConflictError(SocialReasonCode.REVISION_CONFLICT)
            try:
                verified = self.crypto.verify_authenticated_envelope(caller, metadata)
            except NotImplementedError as error:
                raise SocialCryptoUnavailableError(
                    SocialReasonCode.CRYPTO_ADAPTER_UNAVAILABLE
                ) from error
            if not verified:
                raise SocialAuthorizationError(
                    SocialReasonCode.ENVELOPE_VERIFICATION_FAILED
                )
            stored = self.stores.messages.append_message_metadata(
                metadata, accepted_at=now
            )
            self._audit(
                caller,
                SocialAuditAction.MESSAGE_TOMBSTONED
                if metadata.operation is MessageOperation.DELETE
                else SocialAuditAction.MESSAGE_METADATA_ACCEPTED,
                now=now,
            )
            return stored

    def react(
        self, caller: VerifiedSocialPrincipal, reaction: MessageReaction
    ) -> MessageReaction:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            if (
                reaction.organization_id != caller.organization_id
                or reaction.actor_account_id != caller.account_id
            ):
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
            if abs(now - reaction.changed_at) > MAX_CLIENT_CLOCK_SKEW:
                raise SocialConflictError(
                    SocialReasonCode.TIMESTAMP_OUT_OF_WINDOW
                )
            self._conversation_for_member(caller, reaction.conversation_id)
            message = self.stores.messages.latest_message(
                caller.organization_id,
                reaction.conversation_id,
                reaction.message_id,
            )
            if message is None or message.operation is MessageOperation.DELETE:
                raise SocialAuthorizationError(
                    SocialReasonCode.CONVERSATION_ACCESS_DENIED
                )
            return self.stores.messages.save_reaction(reaction)

    def mark_read(
        self,
        caller: VerifiedSocialPrincipal,
        conversation_id: str,
        *,
        through_sequence: int,
    ) -> ConversationReadState:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._conversation_for_member(caller, conversation_id)
            current = self.stores.messages.read_state(
                caller.organization_id, conversation_id, caller.account_id
            )
            if current is not None and through_sequence < current.last_read_sequence:
                raise SocialConflictError(SocialReasonCode.REVISION_CONFLICT)
            if current is not None and through_sequence == current.last_read_sequence:
                return current
            return self.stores.messages.save_read_state(
                ConversationReadState(
                    organization_id=caller.organization_id,
                    conversation_id=conversation_id,
                    account_id=caller.account_id,
                    last_read_sequence=through_sequence,
                    updated_at=now,
                )
            )

    def publish_presence(
        self,
        caller: VerifiedSocialPrincipal,
        presence: RelationshipPresence,
    ) -> RelationshipPresence:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            if (
                presence.organization_id != caller.organization_id
                or presence.subject_account_id != caller.account_id
            ):
                raise SocialAuthorizationError(
                    SocialReasonCode.PRESENCE_NOT_CONSENTED
                )
            if (
                abs(now - presence.observed_at) > MAX_CLIENT_CLOCK_SKEW
                or presence.expires_at <= now
            ):
                raise SocialConflictError(
                    SocialReasonCode.TIMESTAMP_OUT_OF_WINDOW
                )
            self._relationship_target(caller, presence.audience_account_id)
            if self.stores.graph.friendship(
                caller.organization_id,
                caller.account_id,
                presence.audience_account_id,
            ) is None:
                raise SocialAuthorizationError(
                    SocialReasonCode.PRESENCE_NOT_CONSENTED
                )
            stored = self.stores.presence.save_presence(presence)
            self._audit(
                caller,
                SocialAuditAction.PRESENCE_PUBLISHED,
                target_account_id=presence.audience_account_id,
                now=now,
            )
            return stored

    def read_presence(
        self,
        caller: VerifiedSocialPrincipal,
        subject_account_id: str,
    ) -> RelationshipPresence | None:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            self._relationship_target(caller, subject_account_id)
            if self.stores.graph.friendship(
                caller.organization_id, caller.account_id, subject_account_id
            ) is None:
                raise SocialAuthorizationError(
                    SocialReasonCode.PRESENCE_NOT_CONSENTED
                )
            return self.stores.presence.presence(
                caller.organization_id,
                subject_account_id,
                caller.account_id,
                now=now,
            )

    def delete_account_metadata(
        self, caller: VerifiedSocialPrincipal
    ) -> SocialDeletionReceipt:
        now = self.clock()
        with self.stores.transaction:
            self._principal(caller)
            relationship_rows = self.stores.graph.remove_account_relationships(
                caller.organization_id, caller.account_id
            )
            message_tombstones = self.stores.messages.tombstone_account_messages(
                caller.organization_id, caller.account_id, now=now
            )
            auxiliary_rows = self.stores.messages.remove_account_auxiliary_metadata(
                caller.organization_id, caller.account_id
            )
            conversation_rows = self.stores.conversations.remove_account_memberships(
                caller.organization_id, caller.account_id, now=now
            )
            presence_rows = self.stores.presence.remove_account_presence(
                caller.organization_id, caller.account_id
            )
            self.stores.directory.delete_account(
                caller.organization_id, caller.account_id, now=now
            )
            receipt = SocialDeletionReceipt(
                organization_id=caller.organization_id,
                account_id=caller.account_id,
                receipt_id=self.identifiers.issue("social-deletion"),
                relationship_rows_removed=relationship_rows,
                message_metadata_rows_tombstoned=len(message_tombstones),
                conversation_membership_rows_removed=conversation_rows,
                reaction_and_read_rows_removed=auxiliary_rows,
                presence_rows_removed=presence_rows,
                completed_at=now,
            )
            # The honest receipt is durable evidence: it records what was
            # erased and what is retained, never a remote recall claim.
            self.stores.directory.save_deletion_receipt(receipt)
            self._audit(
                caller,
                SocialAuditAction.ACCOUNT_METADATA_DELETED,
                now=now,
            )
            return receipt


__all__ = ["SocialService", "SocialStores"]
