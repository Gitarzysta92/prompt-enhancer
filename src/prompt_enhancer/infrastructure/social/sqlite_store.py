"""Restart-safe, transactional SQLite adapters for the social ports.

One connection, one re-entrant lock and one ``BEGIN IMMEDIATE`` transaction per
service operation.  Any exception inside the transaction rolls back every write
made during that operation, including audit rows.  Only typed control-plane
metadata is persisted; the row serializers accept validated contracts and
refuse anything else.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import sqlite3
import threading
from types import TracebackType

from ...application.social.contracts import (
    SocialReadiness,
    durable_local_social_readiness,
    BlockRecord,
    ChannelMembership,
    Conversation,
    ConversationKind,
    ConversationReadState,
    DeviceKeyReference,
    DeviceState,
    E2eeEnvelopeMetadata,
    FriendRequest,
    FriendRequestState,
    Friendship,
    MessageDeletionTombstone,
    MessageOperation,
    MessageReaction,
    PeerDeletionAcknowledgement,
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
from .development import FailClosedMessageCrypto, RandomSocialIdentifierFactory
from .sqlite import (
    SOCIAL_DATABASE_FILENAME,
    SOCIAL_SCHEMA_VERSION,
    SocialSqliteDatabase,
)


def _ts(value: datetime) -> str:
    return value.isoformat()


def _ts_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _dt_or_none(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


class SqliteSocialConnection:
    """Shared connection plus the atomic per-operation transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.lock = threading.RLock()
        self._depth = 0

    def __enter__(self) -> None:
        self.lock.acquire()
        try:
            if self._depth == 0:
                self.connection.execute("BEGIN IMMEDIATE")
            self._depth += 1
        except Exception:
            self.lock.release()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            self._depth -= 1
            if self._depth == 0 and self.connection.in_transaction:
                self.connection.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.lock.release()
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.connection.execute(sql, params)

    def close(self) -> None:
        with self.lock:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            self.connection.close()


@dataclass(slots=True)
class SqliteSocialStore:
    """Implements the directory, graph, conversation, message, presence and audit ports."""

    db: SqliteSocialConnection

    # Provisioning (synthetic local bootstrap/tests only) ------------------
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
        with self.db:
            try:
                self.db.execute(
                    "INSERT INTO social_accounts VALUES (?, ?, ?, ?, ?)",
                    (
                        account.organization_id,
                        account.account_id,
                        account.state.value,
                        _ts(account.created_at),
                        _ts_or_none(account.deleted_at),
                    ),
                )
                self.db.execute(
                    "INSERT INTO social_organization_memberships VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        membership.organization_id,
                        membership.account_id,
                        membership.role.value,
                        membership.state.value,
                        _ts(membership.created_at),
                        _ts_or_none(membership.revoked_at),
                    ),
                )
                for device in devices:
                    self.db.execute(
                        "INSERT INTO social_devices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            device.organization_id,
                            device.device_id,
                            device.account_id,
                            device.state.value,
                            device.keys.signing_algorithm.value,
                            device.keys.agreement_algorithm.value,
                            device.keys.signing_key_version,
                            device.keys.agreement_key_version,
                            device.keys.signing_key_fingerprint,
                            device.keys.agreement_key_fingerprint,
                            _ts(device.enrolled_at),
                            _ts_or_none(device.revoked_at),
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("social account or device already provisioned") from error

    def provision_team(
        self, team: SocialTeam, memberships: tuple[SocialTeamMembership, ...]
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
        with self.db:
            try:
                self.db.execute(
                    "INSERT INTO social_teams VALUES (?, ?, ?, 1, 0, ?)",
                    (
                        team.organization_id,
                        team.team_id,
                        team.owner_account_id,
                        _ts(team.created_at),
                    ),
                )
                for membership in memberships:
                    self.db.execute(
                        "INSERT INTO social_team_memberships VALUES (?,?,?,?,?,?,?)",
                        (
                            membership.organization_id,
                            membership.team_id,
                            membership.account_id,
                            membership.role.value,
                            membership.state.value,
                            _ts(membership.created_at),
                            _ts_or_none(membership.revoked_at),
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("social team is unavailable or already provisioned") from error

    # Directory port ------------------------------------------------------
    def account(self, organization_id: str, account_id: str) -> SocialAccount | None:
        row = self.db.execute(
            "SELECT state, created_at, deleted_at FROM social_accounts "
            "WHERE organization_id = ? AND account_id = ?",
            (organization_id, account_id),
        ).fetchone()
        if row is None:
            return None
        return SocialAccount(
            organization_id=organization_id,
            account_id=account_id,
            state=SocialAccountState(row[0]),
            created_at=_dt(row[1]),
            deleted_at=_dt_or_none(row[2]),
        )

    def membership(
        self, organization_id: str, account_id: str
    ) -> SocialOrganizationMembership | None:
        row = self.db.execute(
            "SELECT role, state, created_at, revoked_at FROM social_organization_memberships "
            "WHERE organization_id = ? AND account_id = ?",
            (organization_id, account_id),
        ).fetchone()
        if row is None:
            return None
        return SocialOrganizationMembership(
            organization_id=organization_id,
            account_id=account_id,
            role=row[0],
            state=SocialMembershipState(row[1]),
            created_at=_dt(row[2]),
            revoked_at=_dt_or_none(row[3]),
        )

    def device(self, organization_id: str, device_id: str) -> SocialDevice | None:
        row = self.db.execute(
            "SELECT account_id, state, signing_key_version, agreement_key_version, "
            "signing_key_fingerprint, agreement_key_fingerprint, enrolled_at, revoked_at "
            "FROM social_devices WHERE organization_id = ? AND device_id = ?",
            (organization_id, device_id),
        ).fetchone()
        if row is None:
            return None
        return SocialDevice(
            organization_id=organization_id,
            account_id=row[0],
            device_id=device_id,
            state=DeviceState(row[1]),
            keys=DeviceKeyReference(
                signing_key_version=row[2],
                agreement_key_version=row[3],
                signing_key_fingerprint=row[4],
                agreement_key_fingerprint=row[5],
            ),
            enrolled_at=_dt(row[6]),
            revoked_at=_dt_or_none(row[7]),
        )

    def accounts_exist(self, organization_id: str, account_ids: tuple[str, ...]) -> bool:
        return all(self.account(organization_id, item) is not None for item in account_ids)

    def team(self, organization_id: str, team_id: str) -> SocialTeam | None:
        row = self.db.execute(
            "SELECT owner_account_id, created_at FROM social_teams "
            "WHERE organization_id = ? AND team_id = ?",
            (organization_id, team_id),
        ).fetchone()
        if row is None:
            return None
        return SocialTeam(
            organization_id=organization_id,
            team_id=team_id,
            owner_account_id=row[0],
            created_at=_dt(row[1]),
        )

    def team_membership(
        self, organization_id: str, team_id: str, account_id: str
    ) -> SocialTeamMembership | None:
        row = self.db.execute(
            "SELECT role, state, created_at, revoked_at FROM social_team_memberships "
            "WHERE organization_id = ? AND team_id = ? AND account_id = ?",
            (organization_id, team_id, account_id),
        ).fetchone()
        if row is None:
            return None
        return SocialTeamMembership(
            organization_id=organization_id,
            team_id=team_id,
            account_id=account_id,
            role=row[0],
            state=SocialMembershipState(row[1]),
            created_at=_dt(row[2]),
            revoked_at=_dt_or_none(row[3]),
        )

    def revoke_device(
        self, organization_id: str, device_id: str, *, now: datetime
    ) -> SocialDevice:
        with self.db:
            device = self.device(organization_id, device_id)
            if device is None:
                raise ValueError("social device unavailable")
            if device.state is DeviceState.REVOKED:
                return device
            self.db.execute(
                "UPDATE social_devices SET state = 'revoked', revoked_at = ? "
                "WHERE organization_id = ? AND device_id = ?",
                (_ts(now), organization_id, device_id),
            )
            revoked = self.device(organization_id, device_id)
            assert revoked is not None
            return revoked

    def delete_account(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> SocialAccount:
        with self.db:
            account = self.account(organization_id, account_id)
            if account is None:
                raise ValueError("social account unavailable")
            if account.state is SocialAccountState.DELETED:
                return account
            self.db.execute(
                "UPDATE social_accounts SET state = 'deleted', deleted_at = ? "
                "WHERE organization_id = ? AND account_id = ?",
                (_ts(now), organization_id, account_id),
            )
            self.db.execute(
                "UPDATE social_organization_memberships SET state = 'revoked', "
                "revoked_at = ? WHERE organization_id = ? AND account_id = ? "
                "AND state <> 'revoked'",
                (_ts(now), organization_id, account_id),
            )
            self.db.execute(
                "UPDATE social_devices SET state = 'revoked', revoked_at = ? "
                "WHERE organization_id = ? AND account_id = ? AND state <> 'revoked'",
                (_ts(now), organization_id, account_id),
            )
            deleted = self.account(organization_id, account_id)
            assert deleted is not None
            return deleted

    def save_deletion_receipt(self, receipt: SocialDeletionReceipt) -> SocialDeletionReceipt:
        with self.db:
            existing = self.deletion_receipt(receipt.organization_id, receipt.account_id)
            if existing is not None:
                if existing == receipt:
                    return existing
                raise ValueError("social deletion receipt conflict")
            account = self.account(receipt.organization_id, receipt.account_id)
            if account is None or account.state is not SocialAccountState.DELETED:
                raise ValueError("social deletion receipt requires a deleted account")
            if any(
                acknowledgement.organization_id != receipt.organization_id
                or acknowledgement.subject_account_id != receipt.account_id
                for acknowledgement in receipt.peer_device_acknowledgements
            ):
                raise ValueError("peer deletion acknowledgement is not bound")
            try:
                self.db.execute(
                    "INSERT INTO social_deletion_receipts VALUES (?,?,?,?,?,?,?,?,0,?,0,?)",
                    (
                        receipt.organization_id,
                        receipt.account_id,
                        receipt.receipt_id,
                        receipt.relationship_rows_removed,
                        receipt.message_metadata_rows_tombstoned,
                        receipt.conversation_membership_rows_removed,
                        receipt.reaction_and_read_rows_removed,
                        receipt.presence_rows_removed,
                        int(receipt.peer_deletion_requested),
                        _ts(receipt.completed_at),
                    ),
                )
                for acknowledgement in receipt.peer_device_acknowledgements:
                    self.db.execute(
                        "INSERT INTO social_peer_deletion_acknowledgements "
                        "VALUES (?,?,?,?,?,?)",
                        (
                            acknowledgement.organization_id,
                            acknowledgement.subject_account_id,
                            acknowledgement.peer_device_id,
                            acknowledgement.state.value,
                            _ts(acknowledgement.requested_at),
                            _ts_or_none(acknowledgement.acknowledged_at),
                        ),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("social deletion receipt violates schema constraints") from error
            return receipt

    def deletion_receipt(
        self, organization_id: str, account_id: str
    ) -> SocialDeletionReceipt | None:
        row = self.db.execute(
            "SELECT receipt_id, relationship_rows_removed, message_metadata_rows_tombstoned, "
            "conversation_membership_rows_removed, reaction_and_read_rows_removed, "
            "presence_rows_removed, peer_deletion_requested, completed_at "
            "FROM social_deletion_receipts WHERE organization_id = ? AND account_id = ?",
            (organization_id, account_id),
        ).fetchone()
        if row is None:
            return None
        acknowledgement_rows = self.db.execute(
            "SELECT peer_device_id, state, requested_at, acknowledged_at "
            "FROM social_peer_deletion_acknowledgements "
            "WHERE organization_id = ? AND subject_account_id = ? "
            "ORDER BY peer_device_id",
            (organization_id, account_id),
        ).fetchall()
        return SocialDeletionReceipt(
            organization_id=organization_id,
            account_id=account_id,
            receipt_id=row[0],
            relationship_rows_removed=row[1],
            message_metadata_rows_tombstoned=row[2],
            conversation_membership_rows_removed=row[3],
            reaction_and_read_rows_removed=row[4],
            presence_rows_removed=row[5],
            peer_deletion_requested=bool(row[6]),
            peer_device_acknowledgements=tuple(
                PeerDeletionAcknowledgement(
                    organization_id=organization_id,
                    subject_account_id=account_id,
                    peer_device_id=acknowledgement[0],
                    state=acknowledgement[1],
                    requested_at=_dt(acknowledgement[2]),
                    acknowledged_at=_dt_or_none(acknowledgement[3]),
                )
                for acknowledgement in acknowledgement_rows
            ),
            completed_at=_dt(row[7]),
        )

    # Social graph port ---------------------------------------------------
    def _friend_request_row(self, row: tuple[object, ...]) -> FriendRequest:
        return FriendRequest(
            organization_id=row[0],
            request_id=row[1],
            requester_account_id=row[2],
            recipient_account_id=row[3],
            state=FriendRequestState(row[4]),
            created_at=_dt(row[5]),
            expires_at=_dt(row[6]),
            decided_at=_dt_or_none(row[7]),
        )

    _REQUEST_COLUMNS = (
        "organization_id, request_id, requester_account_id, recipient_account_id, "
        "state, created_at, expires_at, decided_at"
    )

    def friend_request(self, organization_id: str, request_id: str) -> FriendRequest | None:
        row = self.db.execute(
            f"SELECT {self._REQUEST_COLUMNS} FROM social_friend_requests "
            "WHERE organization_id = ? AND request_id = ?",
            (organization_id, request_id),
        ).fetchone()
        return None if row is None else self._friend_request_row(row)

    def pending_between(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> FriendRequest | None:
        row = self.db.execute(
            f"SELECT {self._REQUEST_COLUMNS} FROM social_friend_requests "
            "WHERE organization_id = ? AND state = 'pending' AND ("
            "(requester_account_id = ? AND recipient_account_id = ?) OR "
            "(requester_account_id = ? AND recipient_account_id = ?)) "
            "ORDER BY created_at, request_id LIMIT 1",
            (
                organization_id,
                first_account_id,
                second_account_id,
                second_account_id,
                first_account_id,
            ),
        ).fetchone()
        return None if row is None else self._friend_request_row(row)

    def save_friend_request(self, request: FriendRequest) -> FriendRequest:
        with self.db:
            existing = self.friend_request(request.organization_id, request.request_id)
            if existing is not None and (
                existing.requester_account_id != request.requester_account_id
                or existing.recipient_account_id != request.recipient_account_id
                or existing.created_at != request.created_at
                or (
                    existing.state is not FriendRequestState.PENDING
                    and existing.state is not request.state
                )
            ):
                raise ValueError("friend request transition conflict")
            self.db.execute(
                "INSERT OR REPLACE INTO social_friend_requests VALUES (?,?,?,?,?,?,?,?)",
                (
                    request.organization_id,
                    request.request_id,
                    request.requester_account_id,
                    request.recipient_account_id,
                    request.state.value,
                    _ts(request.created_at),
                    _ts(request.expires_at),
                    _ts_or_none(request.decided_at),
                ),
            )
            return request

    def friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> Friendship | None:
        first, second = sorted((first_account_id, second_account_id))
        row = self.db.execute(
            "SELECT accepted_request_id, created_at FROM social_friendships "
            "WHERE organization_id = ? AND first_account_id = ? AND second_account_id = ?",
            (organization_id, first, second),
        ).fetchone()
        if row is None:
            return None
        return Friendship(
            organization_id=organization_id,
            first_account_id=first,
            second_account_id=second,
            accepted_request_id=row[0],
            created_at=_dt(row[1]),
        )

    def save_friendship(self, friendship: Friendship) -> Friendship:
        with self.db:
            existing = self.friendship(
                friendship.organization_id,
                friendship.first_account_id,
                friendship.second_account_id,
            )
            if existing is not None:
                if existing != friendship:
                    raise ValueError("friendship conflict")
                return friendship
            self.db.execute(
                "INSERT INTO social_friendships VALUES (?,?,?,?,?)",
                (
                    friendship.organization_id,
                    friendship.first_account_id,
                    friendship.second_account_id,
                    friendship.accepted_request_id,
                    _ts(friendship.created_at),
                ),
            )
            return friendship

    def remove_friendship(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool:
        first, second = sorted((first_account_id, second_account_id))
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM social_friendships WHERE organization_id = ? "
                "AND first_account_id = ? AND second_account_id = ?",
                (organization_id, first, second),
            )
            return cursor.rowcount > 0

    def block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> BlockRecord | None:
        row = self.db.execute(
            "SELECT created_at FROM social_blocks WHERE organization_id = ? "
            "AND blocker_account_id = ? AND blocked_account_id = ?",
            (organization_id, blocker_account_id, blocked_account_id),
        ).fetchone()
        if row is None:
            return None
        return BlockRecord(
            organization_id=organization_id,
            blocker_account_id=blocker_account_id,
            blocked_account_id=blocked_account_id,
            created_at=_dt(row[0]),
        )

    def either_blocked(
        self, organization_id: str, first_account_id: str, second_account_id: str
    ) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM social_blocks WHERE organization_id = ? AND ("
            "(blocker_account_id = ? AND blocked_account_id = ?) OR "
            "(blocker_account_id = ? AND blocked_account_id = ?)) LIMIT 1",
            (
                organization_id,
                first_account_id,
                second_account_id,
                second_account_id,
                first_account_id,
            ),
        ).fetchone()
        return row is not None

    def save_block(self, block: BlockRecord) -> BlockRecord:
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO social_blocks VALUES (?,?,?,?)",
                (
                    block.organization_id,
                    block.blocker_account_id,
                    block.blocked_account_id,
                    _ts(block.created_at),
                ),
            )
            stored = self.block(
                block.organization_id, block.blocker_account_id, block.blocked_account_id
            )
            assert stored is not None
            return stored

    def remove_block(
        self, organization_id: str, blocker_account_id: str, blocked_account_id: str
    ) -> bool:
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM social_blocks WHERE organization_id = ? "
                "AND blocker_account_id = ? AND blocked_account_id = ?",
                (organization_id, blocker_account_id, blocked_account_id),
            )
            return cursor.rowcount > 0

    def remove_account_relationships(self, organization_id: str, account_id: str) -> int:
        with self.db:
            count = 0
            count += self.db.execute(
                "DELETE FROM social_friend_requests WHERE organization_id = ? "
                "AND (requester_account_id = ? OR recipient_account_id = ?)",
                (organization_id, account_id, account_id),
            ).rowcount
            count += self.db.execute(
                "DELETE FROM social_friendships WHERE organization_id = ? "
                "AND (first_account_id = ? OR second_account_id = ?)",
                (organization_id, account_id, account_id),
            ).rowcount
            count += self.db.execute(
                "DELETE FROM social_blocks WHERE organization_id = ? "
                "AND (blocker_account_id = ? OR blocked_account_id = ?)",
                (organization_id, account_id, account_id),
            ).rowcount
            return count

    # Conversation port ---------------------------------------------------
    def channel(self, organization_id: str, channel_id: str) -> PrivateChannel | None:
        row = self.db.execute(
            "SELECT team_id, owner_account_id, created_at FROM social_private_channels "
            "WHERE organization_id = ? AND channel_id = ?",
            (organization_id, channel_id),
        ).fetchone()
        if row is None:
            return None
        return PrivateChannel(
            organization_id=organization_id,
            channel_id=channel_id,
            team_id=row[0],
            owner_account_id=row[1],
            created_at=_dt(row[2]),
        )

    def save_channel(self, channel: PrivateChannel) -> PrivateChannel:
        with self.db:
            existing = self.channel(channel.organization_id, channel.channel_id)
            if existing is not None:
                if existing != channel:
                    raise ValueError("private channel conflict")
                return channel
            self.db.execute(
                "INSERT INTO social_private_channels VALUES (?,?,?,?,1,0,?)",
                (
                    channel.organization_id,
                    channel.channel_id,
                    channel.team_id,
                    channel.owner_account_id,
                    _ts(channel.created_at),
                ),
            )
            return channel

    def _conversation_row(self, organization_id: str, row: tuple[object, ...]) -> Conversation:
        members = tuple(
            item[0]
            for item in self.db.execute(
                "SELECT account_id FROM social_conversation_members "
                "WHERE organization_id = ? AND conversation_id = ? ORDER BY account_id",
                (organization_id, row[0]),
            ).fetchall()
        )
        return Conversation(
            organization_id=organization_id,
            conversation_id=row[0],
            kind=ConversationKind(row[1]),
            member_account_ids=members,
            channel_id=row[2],
            current_key_version=row[3],
            created_at=_dt(row[4]),
        )

    _CONVERSATION_COLUMNS = (
        "conversation_id, kind, channel_id, current_key_version, created_at"
    )

    def conversation(self, organization_id: str, conversation_id: str) -> Conversation | None:
        with self.db.lock:
            row = self.db.execute(
                f"SELECT {self._CONVERSATION_COLUMNS} FROM social_conversations "
                "WHERE organization_id = ? AND conversation_id = ?",
                (organization_id, conversation_id),
            ).fetchone()
            return None if row is None else self._conversation_row(organization_id, row)

    def save_conversation(self, conversation: Conversation) -> Conversation:
        with self.db:
            existing = self.conversation(
                conversation.organization_id, conversation.conversation_id
            )
            if existing is not None and existing != conversation:
                if (
                    existing.kind is not conversation.kind
                    or existing.channel_id != conversation.channel_id
                    or existing.created_at != conversation.created_at
                    or existing.kind is ConversationKind.DIRECT
                    or conversation.current_key_version != existing.current_key_version + 1
                ):
                    raise ValueError("conversation conflict")
            if existing is None:
                try:
                    self.db.execute(
                        "INSERT INTO social_conversation_fences VALUES (?,?,?,NULL)",
                        (
                            conversation.organization_id,
                            conversation.conversation_id,
                            _ts(conversation.created_at),
                        ),
                    )
                    self.db.execute(
                        "INSERT INTO social_conversations VALUES (?,?,?,?,1,0,?,?)",
                        (
                            conversation.organization_id,
                            conversation.conversation_id,
                            conversation.kind.value,
                            conversation.channel_id,
                            conversation.current_key_version,
                            _ts(conversation.created_at),
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise ValueError("conversation is unavailable or replayed") from error
            else:
                self.db.execute(
                    "UPDATE social_conversations SET current_key_version = ? "
                    "WHERE organization_id = ? AND conversation_id = ?",
                    (
                        conversation.current_key_version,
                        conversation.organization_id,
                        conversation.conversation_id,
                    ),
                )
            self.db.execute(
                "DELETE FROM social_conversation_members WHERE organization_id = ? "
                "AND conversation_id = ?",
                (conversation.organization_id, conversation.conversation_id),
            )
            for member in conversation.member_account_ids:
                self.db.execute(
                    "INSERT INTO social_conversation_members VALUES (?,?,?)",
                    (conversation.organization_id, conversation.conversation_id, member),
                )
            return conversation

    def conversation_for_channel(
        self, organization_id: str, channel_id: str
    ) -> Conversation | None:
        with self.db.lock:
            row = self.db.execute(
                f"SELECT {self._CONVERSATION_COLUMNS} FROM social_conversations "
                "WHERE organization_id = ? AND channel_id = ?",
                (organization_id, channel_id),
            ).fetchone()
            return None if row is None else self._conversation_row(organization_id, row)

    def remove_conversation(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        now: datetime,
    ) -> bool:
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM social_conversations WHERE organization_id = ? "
                "AND conversation_id = ?",
                (organization_id, conversation_id),
            )
            if cursor.rowcount:
                self.db.execute(
                    "UPDATE social_conversation_fences SET closed_at = ? "
                    "WHERE organization_id = ? AND conversation_id = ? "
                    "AND closed_at IS NULL",
                    (_ts(now), organization_id, conversation_id),
                )
            return cursor.rowcount > 0

    def conversations_for_account(
        self, organization_id: str, account_id: str
    ) -> tuple[Conversation, ...]:
        with self.db.lock:
            rows = self.db.execute(
                f"SELECT {self._CONVERSATION_COLUMNS} FROM social_conversations "
                "WHERE organization_id = ? AND conversation_id IN ("
                "SELECT conversation_id FROM social_conversation_members "
                "WHERE organization_id = ? AND account_id = ?) ORDER BY conversation_id",
                (organization_id, organization_id, account_id),
            ).fetchall()
            return tuple(self._conversation_row(organization_id, row) for row in rows)

    def _channel_membership_row(self, row: tuple[object, ...]) -> ChannelMembership:
        return ChannelMembership(
            organization_id=row[0],
            channel_id=row[1],
            account_id=row[2],
            role=row[3],
            state=row[4],
            invited_by_account_id=row[5],
            created_at=_dt(row[6]),
            changed_at=_dt(row[7]),
        )

    def channel_membership(
        self, organization_id: str, channel_id: str, account_id: str
    ) -> ChannelMembership | None:
        row = self.db.execute(
            "SELECT * FROM social_channel_memberships WHERE organization_id = ? "
            "AND channel_id = ? AND account_id = ?",
            (organization_id, channel_id, account_id),
        ).fetchone()
        return None if row is None else self._channel_membership_row(row)

    def channel_memberships(
        self, organization_id: str, channel_id: str
    ) -> tuple[ChannelMembership, ...]:
        rows = self.db.execute(
            "SELECT * FROM social_channel_memberships WHERE organization_id = ? "
            "AND channel_id = ? ORDER BY account_id",
            (organization_id, channel_id),
        ).fetchall()
        return tuple(self._channel_membership_row(row) for row in rows)

    def save_channel_membership(self, membership: ChannelMembership) -> ChannelMembership:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO social_channel_memberships VALUES (?,?,?,?,?,?,?,?)",
                (
                    membership.organization_id,
                    membership.channel_id,
                    membership.account_id,
                    membership.role.value,
                    membership.state.value,
                    membership.invited_by_account_id,
                    _ts(membership.created_at),
                    _ts(membership.changed_at),
                ),
            )
            return membership

    def remove_account_memberships(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> int:
        with self.db:
            removed = self.db.execute(
                "DELETE FROM social_team_memberships WHERE organization_id = ? "
                "AND account_id = ?",
                (organization_id, account_id),
            ).rowcount
            removed += self.db.execute(
                "DELETE FROM social_channel_memberships WHERE organization_id = ? "
                "AND account_id = ?",
                (organization_id, account_id),
            ).rowcount
            for conversation in self.conversations_for_account(organization_id, account_id):
                removed += 1
                remaining = tuple(
                    member
                    for member in conversation.member_account_ids
                    if member != account_id
                )
                if conversation.kind is ConversationKind.DIRECT or len(remaining) < 2:
                    self.remove_conversation(
                        organization_id, conversation.conversation_id, now=now
                    )
                    continue
                self.save_conversation(
                    Conversation.model_validate(
                        {
                            **conversation.model_dump(mode="python"),
                            "member_account_ids": remaining,
                            "current_key_version": conversation.current_key_version + 1,
                        }
                    )
                )
            return removed

    # Message metadata port ----------------------------------------------
    _ENVELOPE_COLUMNS = (
        "organization_id, conversation_id, envelope_id, message_id, sender_account_id, "
        "sender_device_id, operation, revision, key_version, ciphertext_size, "
        "ciphertext_sha256, thread_root_message_id, created_at"
    )

    def _envelope_row(self, row: tuple[object, ...]) -> E2eeEnvelopeMetadata:
        return E2eeEnvelopeMetadata(
            organization_id=row[0],
            conversation_id=row[1],
            envelope_id=row[2],
            message_id=row[3],
            sender_account_id=row[4],
            sender_device_id=row[5],
            operation=MessageOperation(row[6]),
            revision=row[7],
            key_version=row[8],
            ciphertext_size=row[9],
            ciphertext_sha256=row[10],
            thread_root_message_id=row[11],
            created_at=_dt(row[12]),
        )

    def latest_message(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> E2eeEnvelopeMetadata | None:
        row = self.db.execute(
            f"SELECT {self._ENVELOPE_COLUMNS} FROM social_message_envelopes "
            "WHERE organization_id = ? AND conversation_id = ? AND message_id = ? "
            "ORDER BY revision DESC LIMIT 1",
            (organization_id, conversation_id, message_id),
        ).fetchone()
        return None if row is None else self._envelope_row(row)

    def has_message_tombstone(
        self, organization_id: str, conversation_id: str, message_id: str
    ) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM social_message_tombstones WHERE organization_id = ? "
            "AND conversation_id = ? AND message_id = ?",
            (organization_id, conversation_id, message_id),
        ).fetchone()
        return row is not None

    def envelope(self, organization_id: str, envelope_id: str) -> E2eeEnvelopeMetadata | None:
        row = self.db.execute(
            f"SELECT {self._ENVELOPE_COLUMNS} FROM social_message_envelopes "
            "WHERE organization_id = ? AND envelope_id = ?",
            (organization_id, envelope_id),
        ).fetchone()
        return None if row is None else self._envelope_row(row)

    def append_message_metadata(
        self, metadata: E2eeEnvelopeMetadata, *, accepted_at: datetime
    ) -> E2eeEnvelopeMetadata:
        with self.db:
            existing = self.envelope(metadata.organization_id, metadata.envelope_id)
            if existing is not None:
                if existing == metadata:
                    return existing
                raise ValueError("message envelope replay conflict")
            latest = self.latest_message(
                metadata.organization_id, metadata.conversation_id, metadata.message_id
            )
            expected_revision = 1 if latest is None else latest.revision + 1
            if metadata.revision != expected_revision or (
                latest is not None
                and (
                    latest.sender_account_id != metadata.sender_account_id
                    or latest.operation is MessageOperation.DELETE
                )
            ):
                raise ValueError("message revision regression")
            try:
                self.db.execute(
                    "INSERT INTO social_message_envelopes VALUES "
                    "(?,?,?,?,?,?,?,?,?,'xchacha20-poly1305',?,?,?,?,?)",
                    (
                        metadata.organization_id,
                        metadata.envelope_id,
                        metadata.conversation_id,
                        metadata.message_id,
                        metadata.sender_account_id,
                        metadata.sender_device_id,
                        metadata.operation.value,
                        metadata.revision,
                        metadata.key_version,
                        metadata.ciphertext_size,
                        metadata.ciphertext_sha256,
                        metadata.thread_root_message_id,
                        _ts(metadata.created_at),
                        _ts(accepted_at),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("message envelope violates schema constraints") from error
            if metadata.operation is MessageOperation.DELETE:
                self.db.execute(
                    "INSERT OR REPLACE INTO social_message_tombstones VALUES (?,?,?,?,?,0)",
                    (
                        metadata.organization_id,
                        metadata.conversation_id,
                        metadata.message_id,
                        metadata.sender_account_id,
                        _ts(accepted_at),
                    ),
                )
            return metadata

    def save_reaction(self, reaction: MessageReaction) -> MessageReaction:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO social_message_reactions VALUES (?,?,?,?,?,?,?)",
                (
                    reaction.organization_id,
                    reaction.conversation_id,
                    reaction.message_id,
                    reaction.actor_account_id,
                    reaction.reaction.value,
                    int(reaction.active),
                    _ts(reaction.changed_at),
                ),
            )
            return reaction

    def read_state(
        self, organization_id: str, conversation_id: str, account_id: str
    ) -> ConversationReadState | None:
        row = self.db.execute(
            "SELECT last_read_sequence, updated_at FROM social_conversation_read_states "
            "WHERE organization_id = ? AND conversation_id = ? AND account_id = ?",
            (organization_id, conversation_id, account_id),
        ).fetchone()
        if row is None:
            return None
        return ConversationReadState(
            organization_id=organization_id,
            conversation_id=conversation_id,
            account_id=account_id,
            last_read_sequence=row[0],
            updated_at=_dt(row[1]),
        )

    def save_read_state(self, state: ConversationReadState) -> ConversationReadState:
        with self.db:
            current = self.read_state(
                state.organization_id, state.conversation_id, state.account_id
            )
            if current is not None and state.last_read_sequence < current.last_read_sequence:
                raise ValueError("read state regression")
            self.db.execute(
                "INSERT OR REPLACE INTO social_conversation_read_states VALUES (?,?,?,?,?)",
                (
                    state.organization_id,
                    state.conversation_id,
                    state.account_id,
                    state.last_read_sequence,
                    _ts(state.updated_at),
                ),
            )
            return state

    def tombstone_account_messages(
        self, organization_id: str, account_id: str, *, now: datetime
    ) -> tuple[MessageDeletionTombstone, ...]:
        with self.db:
            rows = self.db.execute(
                "SELECT DISTINCT conversation_id, message_id FROM social_message_envelopes "
                "WHERE organization_id = ? AND sender_account_id = ? AND revision = 1 "
                "ORDER BY conversation_id, message_id",
                (organization_id, account_id),
            ).fetchall()
            tombstones: list[MessageDeletionTombstone] = []
            for conversation_id, message_id in rows:
                tombstone = MessageDeletionTombstone(
                    organization_id=organization_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    sender_account_id=account_id,
                    deleted_at=now,
                )
                self.db.execute(
                    "INSERT OR REPLACE INTO social_message_tombstones VALUES (?,?,?,?,?,0)",
                    (organization_id, conversation_id, message_id, account_id, _ts(now)),
                )
                # Every digest/size-bearing revision is erased; only the
                # content-free tombstone survives.
                self.db.execute(
                    "DELETE FROM social_message_envelopes WHERE organization_id = ? "
                    "AND conversation_id = ? AND message_id = ?",
                    (organization_id, conversation_id, message_id),
                )
                tombstones.append(tombstone)
            return tuple(tombstones)

    def remove_account_auxiliary_metadata(self, organization_id: str, account_id: str) -> int:
        with self.db:
            removed = self.db.execute(
                "DELETE FROM social_message_reactions WHERE organization_id = ? "
                "AND actor_account_id = ?",
                (organization_id, account_id),
            ).rowcount
            removed += self.db.execute(
                "DELETE FROM social_conversation_read_states WHERE organization_id = ? "
                "AND account_id = ?",
                (organization_id, account_id),
            ).rowcount
            return removed

    # Presence port -------------------------------------------------------
    def save_presence(self, presence: RelationshipPresence) -> RelationshipPresence:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO social_presence VALUES (?,?,?,?,?,?)",
                (
                    presence.organization_id,
                    presence.subject_account_id,
                    presence.audience_account_id,
                    presence.state.value,
                    _ts(presence.observed_at),
                    _ts(presence.expires_at),
                ),
            )
            return presence

    def presence(
        self,
        organization_id: str,
        subject_account_id: str,
        audience_account_id: str,
        *,
        now: datetime,
    ) -> RelationshipPresence | None:
        with self.db:
            row = self.db.execute(
                "SELECT state, observed_at, expires_at FROM social_presence "
                "WHERE organization_id = ? AND subject_account_id = ? AND audience_account_id = ?",
                (organization_id, subject_account_id, audience_account_id),
            ).fetchone()
            if row is None:
                return None
            presence = RelationshipPresence(
                organization_id=organization_id,
                subject_account_id=subject_account_id,
                audience_account_id=audience_account_id,
                state=row[0],
                observed_at=_dt(row[1]),
                expires_at=_dt(row[2]),
            )
            if presence.expires_at <= now:
                self.db.execute(
                    "DELETE FROM social_presence WHERE organization_id = ? "
                    "AND subject_account_id = ? AND audience_account_id = ?",
                    (organization_id, subject_account_id, audience_account_id),
                )
                return None
            return presence

    def remove_account_presence(self, organization_id: str, account_id: str) -> int:
        with self.db:
            return self.db.execute(
                "DELETE FROM social_presence WHERE organization_id = ? "
                "AND (subject_account_id = ? OR audience_account_id = ?)",
                (organization_id, account_id, account_id),
            ).rowcount

    # Audit port ----------------------------------------------------------
    def append(self, event: SocialAuditEvent) -> SocialAuditEvent:
        with self.db:
            self.db.execute(
                "INSERT INTO social_audit_events (organization_id, audit_id, "
                "actor_account_id, actor_device_id, target_account_id, action, "
                "decision, reason, occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    event.organization_id,
                    event.audit_id,
                    event.actor_account_id,
                    event.actor_device_id,
                    event.target_account_id,
                    event.action.value,
                    event.decision.value,
                    event.reason.value,
                    _ts(event.occurred_at),
                ),
            )
            return event

    def recent(self, organization_id: str, *, limit: int) -> tuple[SocialAuditEvent, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("social audit limit is invalid")
        rows = self.db.execute(
            "SELECT organization_id, audit_id, actor_account_id, actor_device_id, "
            "target_account_id, action, decision, reason, occurred_at "
            "FROM social_audit_events WHERE organization_id = ? "
            "ORDER BY sequence DESC LIMIT ?",
            (organization_id, limit),
        ).fetchall()
        return tuple(
            SocialAuditEvent(
                organization_id=row[0],
                audit_id=row[1],
                actor_account_id=row[2],
                actor_device_id=row[3],
                target_account_id=row[4],
                action=row[5],
                decision=row[6],
                reason=row[7],
                occurred_at=_dt(row[8]),
            )
            for row in rows
        )


@dataclass(frozen=True, slots=True)
class SqliteSocialFoundation:
    database: SocialSqliteDatabase
    db: SqliteSocialConnection
    store: SqliteSocialStore
    service: SocialService

    def close(self) -> None:
        self.db.close()

    def readiness(self, *, enabled: bool) -> SocialReadiness:
        """Return the honest ledger for this verified separated store.

        The dedicated ``social.sqlite3`` filename, the independent migration
        ledger at the current schema version and the absence of any attached
        analyzer database are re-checked here, so a caller cannot obtain the
        ``social_store_not_separated``-free ledger for a foreign or partially
        migrated file.  Every other production gap remains open.
        """

        if self.database.path.name != SOCIAL_DATABASE_FILENAME:
            raise ValueError("social readiness requires the dedicated social database")
        version_row = self.db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM social_schema_migrations"
        ).fetchone()
        if version_row is None or int(version_row[0]) != SOCIAL_SCHEMA_VERSION:
            raise ValueError("social readiness requires the current schema ledger")
        attached = tuple(
            str(row[1]) for row in self.db.execute("PRAGMA database_list").fetchall()
        )
        if any(name not in {"main", "temp"} for name in attached):
            raise ValueError("social database must not attach other databases")
        return durable_local_social_readiness(enabled=enabled)


def create_sqlite_social_foundation(
    database: SocialSqliteDatabase,
    clock: Callable[[], datetime],
) -> SqliteSocialFoundation:
    """Compose the durable local social service; crypto still fails closed."""

    db = SqliteSocialConnection(database.connect())
    store = SqliteSocialStore(db=db)
    service = SocialService(
        stores=SocialStores(
            transaction=db,
            directory=store,
            graph=store,
            conversations=store,
            messages=store,
            presence=store,
            audit=store,
        ),
        identifiers=RandomSocialIdentifierFactory(),
        crypto=FailClosedMessageCrypto(),
        clock=clock,
    )
    return SqliteSocialFoundation(database=database, db=db, store=store, service=service)


__all__ = [
    "SqliteSocialConnection",
    "SqliteSocialFoundation",
    "SqliteSocialStore",
    "create_sqlite_social_foundation",
]
