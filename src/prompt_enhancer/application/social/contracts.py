"""Content-free contracts for the invite-only social development foundation.

The social namespace is deliberately independent from analyzer and team-metric
identifiers.  Every durable identifier starts with ``soc_`` and is random; an
analytics HMAC pseudonym therefore cannot be used as a social join key.  These
records contain relationship and delivery metadata, which is still personal
data even though message plaintext and ciphertext are absent.

This module does not implement authentication or encryption.  Device public-key
references and encrypted-envelope metadata are safe interfaces for reviewed
adapters.  Private keys, message bodies, ciphertext bytes, filesystem paths,
display names, and free-form audit text are structurally absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...domain import SAFE_VERSION_PATTERN, StrictModel


SOCIAL_CONTRACT_VERSION = "social-foundation-v1"
SOCIAL_ID_PATTERN = re.compile(r"^soc_[a-f0-9]{64}$")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")

MAX_GROUP_MEMBERS = 64
MAX_CHANNEL_MEMBERSHIPS = 256
MAX_REACTION_ACTORS = 10_000
MAX_CIPHERTEXT_BYTES = 16 * 1024 * 1024
MAX_FRIEND_REQUEST_LIFETIME = timedelta(days=30)
MAX_PRESENCE_LIFETIME = timedelta(minutes=5)
MAX_CLIENT_CLOCK_SKEW = timedelta(minutes=5)


def social_id(value: str) -> str:
    if SOCIAL_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("social identifiers must be opaque soc_ identifiers")
    return value


def optional_social_id(value: str | None) -> str | None:
    return None if value is None else social_id(value)


def digest(value: str) -> str:
    if DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError("digests must be lowercase SHA-256 hex")
    return value


def safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("version identifiers contain unsafe characters")
    return value


def utc_seconds(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("social timestamps must be UTC")
    if value.microsecond:
        raise ValueError("social timestamps must be whole seconds")
    return value


def optional_utc_seconds(value: datetime | None) -> datetime | None:
    return None if value is None else utc_seconds(value)


class SocialDeploymentProfile(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class SocialReadinessGap(StrEnum):
    """Closed, user-displayable reasons this is not a production messenger."""

    IDENTITY_PROVIDER_UNAVAILABLE = "identity_provider_unavailable"
    DEVICE_PROOF_OF_POSSESSION_UNAVAILABLE = (
        "device_proof_of_possession_unavailable"
    )
    REVIEWED_E2EE_ADAPTER_UNAVAILABLE = "reviewed_e2ee_adapter_unavailable"
    FORWARD_SECRECY_UNAVAILABLE = "forward_secrecy_unavailable"
    AUTHENTICATED_SIGNALING_UNAVAILABLE = "authenticated_signaling_unavailable"
    DIRECT_CONNECTIVITY_UNVERIFIED = "direct_connectivity_unverified"
    DURABLE_MULTI_DEVICE_SYNC_UNAVAILABLE = "durable_multi_device_sync_unavailable"
    BACKUP_RECOVERY_UNAVAILABLE = "backup_recovery_unavailable"
    ABUSE_REPORTING_UNAVAILABLE = "abuse_reporting_unavailable"
    SOCIAL_STORE_NOT_SEPARATED = "social_store_not_separated"
    LEGAL_CONTROLLER_UNDETERMINED = "legal_controller_undetermined"
    RETENTION_POLICY_UNAPPROVED = "retention_policy_unapproved"
    METADATA_VISIBLE_TO_CONTROL_PLANE = "metadata_visible_to_control_plane"
    DPIA_REVIEW_REQUIRED_BEFORE_WORKPLACE_USE = (
        "dpia_review_required_before_workplace_use"
    )


DEVELOPMENT_SOCIAL_GAPS = tuple(sorted(SocialReadinessGap, key=lambda item: item.value))


class CapabilityState(StrEnum):
    CONTRACT_ONLY = "contract_only"
    DEVELOPMENT_ONLY = "development_only"
    UNAVAILABLE = "unavailable"


class SocialCapability(StrictModel):
    capability: Literal[
        "social_graph",
        "private_channels",
        "message_metadata",
        "coarse_presence",
        "e2ee",
        "multi_device_sync",
        "export",
        "deletion",
    ]
    state: CapabilityState


class SocialReadiness(StrictModel):
    contract_version: Literal["social-foundation-v1"] = SOCIAL_CONTRACT_VERSION
    deployment_profile: Literal[SocialDeploymentProfile.DEVELOPMENT] = (
        SocialDeploymentProfile.DEVELOPMENT
    )
    enabled: bool
    production_ready: Literal[False] = False
    invite_only: Literal[True] = True
    public_discovery: Literal[False] = False
    analyzer_join_keys: Literal[False] = False
    persists_message_plaintext: Literal[False] = False
    persists_message_ciphertext: Literal[False] = False
    presence_derived_from_analyzer_activity: Literal[False] = False
    local_history_deleted_on_entitlement_lapse: Literal[False] = False
    local_export_requires_active_entitlement: Literal[False] = False
    capabilities: tuple[SocialCapability, ...]
    gaps: tuple[SocialReadinessGap, ...] = DEVELOPMENT_SOCIAL_GAPS

    @model_validator(mode="after")
    def canonical_collections(self) -> SocialReadiness:
        capability_names = tuple(item.capability for item in self.capabilities)
        if capability_names != tuple(sorted(capability_names)):
            raise ValueError("social capabilities must be sorted")
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("social capabilities must be unique")
        if self.gaps != tuple(sorted(set(self.gaps), key=lambda item: item.value)):
            raise ValueError("social readiness gaps must be unique and sorted")
        return self


class SocialAccountState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class SocialOrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MODERATOR = "moderator"
    MEMBER = "member"


class SocialMembershipState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class SocialAccount(StrictModel):
    organization_id: str
    account_id: str
    state: SocialAccountState
    created_at: datetime
    deleted_at: datetime | None = None

    _ids = field_validator("organization_id", "account_id")(social_id)
    _created = field_validator("created_at")(utc_seconds)
    _deleted = field_validator("deleted_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def deletion_matches_state(self) -> SocialAccount:
        if (self.state is SocialAccountState.DELETED) != (self.deleted_at is not None):
            raise ValueError("deleted accounts require exactly one deletion timestamp")
        if self.deleted_at is not None and self.deleted_at < self.created_at:
            raise ValueError("account deletion predates creation")
        return self


class SocialOrganizationMembership(StrictModel):
    organization_id: str
    account_id: str
    role: SocialOrganizationRole
    state: SocialMembershipState
    created_at: datetime
    revoked_at: datetime | None = None

    _ids = field_validator("organization_id", "account_id")(social_id)
    _created = field_validator("created_at")(utc_seconds)
    _revoked = field_validator("revoked_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def revocation_matches_state(self) -> SocialOrganizationMembership:
        if (self.state is SocialMembershipState.REVOKED) != (
            self.revoked_at is not None
        ):
            raise ValueError("revoked membership requires exactly one timestamp")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("membership revocation predates creation")
        return self


class DeviceState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class SigningAlgorithm(StrEnum):
    ED25519 = "ed25519"


class AgreementAlgorithm(StrEnum):
    X25519 = "x25519"


class AeadAlgorithm(StrEnum):
    XCHACHA20_POLY1305 = "xchacha20-poly1305"


class DeviceKeyReference(StrictModel):
    """Public key identifiers only; key bytes live behind a reviewed port."""

    signing_algorithm: Literal[SigningAlgorithm.ED25519] = SigningAlgorithm.ED25519
    agreement_algorithm: Literal[AgreementAlgorithm.X25519] = (
        AgreementAlgorithm.X25519
    )
    signing_key_version: int = Field(ge=1, le=2_147_483_647)
    agreement_key_version: int = Field(ge=1, le=2_147_483_647)
    signing_key_fingerprint: str
    agreement_key_fingerprint: str

    _digests = field_validator(
        "signing_key_fingerprint", "agreement_key_fingerprint"
    )(digest)


class SocialDevice(StrictModel):
    organization_id: str
    account_id: str
    device_id: str
    state: DeviceState
    keys: DeviceKeyReference
    enrolled_at: datetime
    revoked_at: datetime | None = None

    _ids = field_validator("organization_id", "account_id", "device_id")(social_id)
    _enrolled = field_validator("enrolled_at")(utc_seconds)
    _revoked = field_validator("revoked_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def revocation_matches_state(self) -> SocialDevice:
        if (self.state is DeviceState.REVOKED) != (self.revoked_at is not None):
            raise ValueError("revoked device requires exactly one timestamp")
        if self.revoked_at is not None and self.revoked_at < self.enrolled_at:
            raise ValueError("device revocation predates enrollment")
        return self


class VerifiedSocialPrincipal(StrictModel):
    """Resolved out of band; no public request may construct this identity."""

    organization_id: str
    account_id: str
    device_id: str
    authenticated_at: datetime

    _ids = field_validator("organization_id", "account_id", "device_id")(social_id)
    _authenticated = field_validator("authenticated_at")(utc_seconds)


class FriendRequestState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_FRIEND_REQUEST_STATES = frozenset(
    {
        FriendRequestState.ACCEPTED,
        FriendRequestState.DECLINED,
        FriendRequestState.CANCELLED,
        FriendRequestState.EXPIRED,
    }
)


class FriendRequest(StrictModel):
    organization_id: str
    request_id: str
    requester_account_id: str
    recipient_account_id: str
    state: FriendRequestState
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None

    _ids = field_validator(
        "organization_id",
        "request_id",
        "requester_account_id",
        "recipient_account_id",
    )(social_id)
    _created = field_validator("created_at")(utc_seconds)
    _expires = field_validator("expires_at")(utc_seconds)
    _decided = field_validator("decided_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def valid_lifecycle(self) -> FriendRequest:
        if self.requester_account_id == self.recipient_account_id:
            raise ValueError("an account cannot friend itself")
        if not self.created_at < self.expires_at:
            raise ValueError("friend request expiry must follow creation")
        if self.expires_at - self.created_at > MAX_FRIEND_REQUEST_LIFETIME:
            raise ValueError("friend request lifetime exceeds the maximum")
        terminal = self.state in TERMINAL_FRIEND_REQUEST_STATES
        if terminal != (self.decided_at is not None):
            raise ValueError("terminal friend request requires a decision timestamp")
        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("friend request decision predates creation")
        return self


class Friendship(StrictModel):
    organization_id: str
    first_account_id: str
    second_account_id: str
    accepted_request_id: str
    created_at: datetime

    _ids = field_validator(
        "organization_id",
        "first_account_id",
        "second_account_id",
        "accepted_request_id",
    )(social_id)
    _created = field_validator("created_at")(utc_seconds)

    @model_validator(mode="after")
    def canonical_pair(self) -> Friendship:
        if self.first_account_id >= self.second_account_id:
            raise ValueError("friendship accounts must be unique and sorted")
        return self


class BlockRecord(StrictModel):
    organization_id: str
    blocker_account_id: str
    blocked_account_id: str
    created_at: datetime

    _ids = field_validator(
        "organization_id", "blocker_account_id", "blocked_account_id"
    )(social_id)
    _created = field_validator("created_at")(utc_seconds)

    @model_validator(mode="after")
    def not_self(self) -> BlockRecord:
        if self.blocker_account_id == self.blocked_account_id:
            raise ValueError("an account cannot block itself")
        return self


class ChannelRole(StrEnum):
    OWNER = "owner"
    MODERATOR = "moderator"
    MEMBER = "member"


class ChannelMembershipState(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class SocialTeamRole(StrEnum):
    LEAD = "lead"
    MEMBER = "member"


class SocialTeam(StrictModel):
    organization_id: str
    team_id: str
    owner_account_id: str
    invitation_only: Literal[True] = True
    discoverable: Literal[False] = False
    created_at: datetime

    _ids = field_validator("organization_id", "team_id", "owner_account_id")(
        social_id
    )
    _created = field_validator("created_at")(utc_seconds)


class SocialTeamMembership(StrictModel):
    organization_id: str
    team_id: str
    account_id: str
    role: SocialTeamRole
    state: SocialMembershipState
    created_at: datetime
    revoked_at: datetime | None = None

    _ids = field_validator("organization_id", "team_id", "account_id")(
        social_id
    )
    _created = field_validator("created_at")(utc_seconds)
    _revoked = field_validator("revoked_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def revocation_matches_state(self) -> SocialTeamMembership:
        if (self.state is SocialMembershipState.REVOKED) != (
            self.revoked_at is not None
        ):
            raise ValueError("revoked team membership requires a timestamp")
        return self


class PrivateChannel(StrictModel):
    organization_id: str
    channel_id: str
    team_id: str | None = None
    owner_account_id: str
    invitation_only: Literal[True] = True
    discoverable: Literal[False] = False
    created_at: datetime

    _required_ids = field_validator(
        "organization_id", "channel_id", "owner_account_id"
    )(social_id)
    _team = field_validator("team_id")(optional_social_id)
    _created = field_validator("created_at")(utc_seconds)


class ChannelMembership(StrictModel):
    organization_id: str
    channel_id: str
    account_id: str
    role: ChannelRole
    state: ChannelMembershipState
    invited_by_account_id: str
    created_at: datetime
    changed_at: datetime

    _ids = field_validator(
        "organization_id",
        "channel_id",
        "account_id",
        "invited_by_account_id",
    )(social_id)
    _times = field_validator("created_at", "changed_at")(utc_seconds)

    @model_validator(mode="after")
    def ordered_times(self) -> ChannelMembership:
        if self.changed_at < self.created_at:
            raise ValueError("channel membership change predates creation")
        return self


class ConversationKind(StrEnum):
    DIRECT = "direct"
    PRIVATE_GROUP = "private_group"


class Conversation(StrictModel):
    organization_id: str
    conversation_id: str
    kind: ConversationKind
    member_account_ids: tuple[str, ...] = Field(
        min_length=2, max_length=MAX_GROUP_MEMBERS
    )
    channel_id: str | None = None
    invitation_only: Literal[True] = True
    discoverable: Literal[False] = False
    current_key_version: int = Field(ge=1, le=2_147_483_647)
    created_at: datetime

    _ids = field_validator("organization_id", "conversation_id")(social_id)
    _channel = field_validator("channel_id")(optional_social_id)
    _created = field_validator("created_at")(utc_seconds)

    @field_validator("member_account_ids")
    @classmethod
    def canonical_members(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for member in value:
            social_id(member)
        if value != tuple(sorted(set(value))):
            raise ValueError("conversation members must be unique and sorted")
        return value

    @model_validator(mode="after")
    def valid_kind(self) -> Conversation:
        if self.kind is ConversationKind.DIRECT:
            if len(self.member_account_ids) != 2 or self.channel_id is not None:
                raise ValueError("direct conversations have exactly two members")
        elif self.channel_id is None:
            raise ValueError("private group conversations require a channel")
        return self


class MessageOperation(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"


class E2eeEnvelopeMetadata(StrictModel):
    """Server-visible metadata for an encrypted message; bytes are absent."""

    organization_id: str
    conversation_id: str
    envelope_id: str
    message_id: str
    sender_account_id: str
    sender_device_id: str
    operation: MessageOperation
    revision: int = Field(ge=1, le=2_147_483_647)
    key_version: int = Field(ge=1, le=2_147_483_647)
    aead_algorithm: Literal[AeadAlgorithm.XCHACHA20_POLY1305] = (
        AeadAlgorithm.XCHACHA20_POLY1305
    )
    ciphertext_size: int = Field(ge=1, le=MAX_CIPHERTEXT_BYTES)
    ciphertext_sha256: str
    thread_root_message_id: str | None = None
    created_at: datetime

    _ids = field_validator(
        "organization_id",
        "conversation_id",
        "envelope_id",
        "message_id",
        "sender_account_id",
        "sender_device_id",
    )(social_id)
    _root = field_validator("thread_root_message_id")(optional_social_id)
    _digest = field_validator("ciphertext_sha256")(digest)
    _created = field_validator("created_at")(utc_seconds)

    @model_validator(mode="after")
    def valid_revision(self) -> E2eeEnvelopeMetadata:
        if self.operation is MessageOperation.CREATE and self.revision != 1:
            raise ValueError("new messages start at revision one")
        if self.operation is not MessageOperation.CREATE and self.revision <= 1:
            raise ValueError("mutations require a later revision")
        return self


class MessageReactionCode(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    APPROVED = "approved"
    HEART = "heart"
    LAUGH = "laugh"
    THUMBS_DOWN = "thumbs_down"
    THUMBS_UP = "thumbs_up"


class MessageReaction(StrictModel):
    organization_id: str
    conversation_id: str
    message_id: str
    actor_account_id: str
    reaction: MessageReactionCode
    active: bool
    changed_at: datetime

    _ids = field_validator(
        "organization_id", "conversation_id", "message_id", "actor_account_id"
    )(social_id)
    _changed = field_validator("changed_at")(utc_seconds)


class MessageDeletionTombstone(StrictModel):
    """Content-free local deletion marker; it is not proof of remote recall."""

    organization_id: str
    conversation_id: str
    message_id: str
    sender_account_id: str
    deleted_at: datetime
    remote_plaintext_recall_guaranteed: Literal[False] = False

    _ids = field_validator(
        "organization_id", "conversation_id", "message_id", "sender_account_id"
    )(social_id)
    _deleted = field_validator("deleted_at")(utc_seconds)


class ConversationReadState(StrictModel):
    organization_id: str
    conversation_id: str
    account_id: str
    last_read_sequence: int = Field(ge=0)
    updated_at: datetime

    _ids = field_validator("organization_id", "conversation_id", "account_id")(
        social_id
    )
    _updated = field_validator("updated_at")(utc_seconds)


class PresenceState(StrEnum):
    AVAILABLE = "available"
    AWAY = "away"
    OFFLINE = "offline"


class RelationshipPresence(StrictModel):
    """Explicit, coarse and expiring; never inferred from analyzer activity."""

    organization_id: str
    subject_account_id: str
    audience_account_id: str
    state: PresenceState
    opted_in: Literal[True] = True
    observed_at: datetime
    expires_at: datetime

    _ids = field_validator(
        "organization_id", "subject_account_id", "audience_account_id"
    )(social_id)
    _times = field_validator("observed_at", "expires_at")(utc_seconds)

    @model_validator(mode="after")
    def short_lived(self) -> RelationshipPresence:
        if self.subject_account_id == self.audience_account_id:
            raise ValueError("presence audience must be another account")
        if not self.observed_at < self.expires_at:
            raise ValueError("presence expiry must follow observation")
        if self.expires_at - self.observed_at > MAX_PRESENCE_LIFETIME:
            raise ValueError("presence lifetime exceeds the coarse presence maximum")
        return self


class SocialAuditAction(StrEnum):
    FRIEND_REQUESTED = "friend_requested"
    FRIEND_REQUEST_ACCEPTED = "friend_request_accepted"
    FRIEND_REQUEST_DECLINED = "friend_request_declined"
    FRIEND_REQUEST_CANCELLED = "friend_request_cancelled"
    FRIEND_REMOVED = "friend_removed"
    ACCOUNT_BLOCKED = "account_blocked"
    ACCOUNT_UNBLOCKED = "account_unblocked"
    CHANNEL_MEMBERSHIP_CHANGED = "channel_membership_changed"
    MESSAGE_METADATA_ACCEPTED = "message_metadata_accepted"
    MESSAGE_TOMBSTONED = "message_tombstoned"
    PRESENCE_PUBLISHED = "presence_published"
    DEVICE_REVOKED = "device_revoked"
    ACCOUNT_METADATA_DELETED = "account_metadata_deleted"
    ACCESS_DENIED = "access_denied"


class SocialReasonCode(StrEnum):
    ALLOWED = "allowed"
    DEFAULT_DENY = "default_deny"
    PRINCIPAL_INACTIVE = "principal_inactive"
    DEVICE_INACTIVE = "device_inactive"
    RELATIONSHIP_UNAVAILABLE = "relationship_unavailable"
    REQUEST_STATE_CONFLICT = "request_state_conflict"
    REQUEST_REPLAYED = "request_replayed"
    MEMBERSHIP_REQUIRED = "membership_required"
    MEMBERSHIP_REVOKED = "membership_revoked"
    CONVERSATION_ACCESS_DENIED = "conversation_access_denied"
    STALE_KEY_VERSION = "stale_key_version"
    CRYPTO_ADAPTER_UNAVAILABLE = "crypto_adapter_unavailable"
    ENVELOPE_VERIFICATION_FAILED = "envelope_verification_failed"
    REVISION_CONFLICT = "revision_conflict"
    PRESENCE_NOT_CONSENTED = "presence_not_consented"
    TIMESTAMP_OUT_OF_WINDOW = "timestamp_out_of_window"


class SocialAuditDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class SocialAuditEvent(StrictModel):
    organization_id: str
    audit_id: str
    actor_account_id: str
    actor_device_id: str
    target_account_id: str | None = None
    action: SocialAuditAction
    decision: SocialAuditDecision
    reason: SocialReasonCode
    occurred_at: datetime

    _ids = field_validator(
        "organization_id", "audit_id", "actor_account_id", "actor_device_id"
    )(social_id)
    _target = field_validator("target_account_id")(optional_social_id)
    _occurred = field_validator("occurred_at")(utc_seconds)


class PeerDeletionState(StrEnum):
    REQUESTED = "requested"
    ACKNOWLEDGED = "acknowledged"
    EXPIRED = "expired"


class PeerDeletionAcknowledgement(StrictModel):
    """Per-device request evidence, never a claim that plaintext was recalled."""

    organization_id: str
    subject_account_id: str
    peer_device_id: str
    state: PeerDeletionState
    requested_at: datetime
    acknowledged_at: datetime | None = None
    plaintext_recall_guaranteed: Literal[False] = False

    _ids = field_validator(
        "organization_id", "subject_account_id", "peer_device_id"
    )(social_id)
    _requested = field_validator("requested_at")(utc_seconds)
    _acknowledged = field_validator("acknowledged_at")(optional_utc_seconds)

    @model_validator(mode="after")
    def acknowledgement_matches_state(self) -> PeerDeletionAcknowledgement:
        acknowledged = self.state is PeerDeletionState.ACKNOWLEDGED
        if acknowledged != (self.acknowledged_at is not None):
            raise ValueError("peer deletion acknowledgement state is inconsistent")
        if self.acknowledged_at is not None and self.acknowledged_at < self.requested_at:
            raise ValueError("peer deletion acknowledgement predates request")
        return self


class SocialDeletionReceipt(StrictModel):
    organization_id: str
    account_id: str
    receipt_id: str
    relationship_rows_removed: int = Field(ge=0)
    message_metadata_rows_tombstoned: int = Field(ge=0)
    conversation_membership_rows_removed: int = Field(ge=0)
    reaction_and_read_rows_removed: int = Field(ge=0)
    presence_rows_removed: int = Field(ge=0)
    local_account_content_erased: Literal[True] = True
    local_metadata_erased: Literal[False] = False
    retains_account_tombstone: Literal[True] = True
    retains_device_revocation_fences: Literal[True] = True
    retains_security_audit_events: Literal[True] = True
    peer_deletion_requested: bool = False
    peer_device_acknowledgements: tuple[PeerDeletionAcknowledgement, ...] = Field(
        default=(), max_length=256
    )
    remote_plaintext_recall_guaranteed: Literal[False] = False
    completed_at: datetime

    _ids = field_validator("organization_id", "account_id", "receipt_id")(
        social_id
    )
    _completed = field_validator("completed_at")(utc_seconds)


DURABLE_LOCAL_SOCIAL_GAPS = tuple(
    gap
    for gap in DEVELOPMENT_SOCIAL_GAPS
    if gap is not SocialReadinessGap.SOCIAL_STORE_NOT_SEPARATED
)


def durable_local_social_readiness(*, enabled: bool) -> SocialReadiness:
    """Ledger for an explicitly composed, verified separated ``social.sqlite3``.

    The only gap a durable local store closes is ``social_store_not_separated``.
    Identity, device proof, reviewed E2EE and forward secrecy, signaling and
    direct connectivity, multi-device sync, backup/recovery, abuse handling and
    governance gaps stay open, so ``production_ready`` remains ``False`` and no
    message encryption or direct transfer is claimed.  A disabled ledger is
    indistinguishable from the in-memory disabled ledger.
    """

    if not enabled:
        return development_social_readiness(enabled=False)
    base = development_social_readiness(enabled=True)
    return SocialReadiness(
        enabled=True,
        capabilities=base.capabilities,
        gaps=DURABLE_LOCAL_SOCIAL_GAPS,
    )


def development_social_readiness(*, enabled: bool) -> SocialReadiness:
    """Return the exact, production-honest capability ledger."""

    states = {
        "coarse_presence": CapabilityState.DEVELOPMENT_ONLY,
        "deletion": CapabilityState.DEVELOPMENT_ONLY,
        "e2ee": CapabilityState.UNAVAILABLE,
        "export": CapabilityState.CONTRACT_ONLY,
        "message_metadata": CapabilityState.DEVELOPMENT_ONLY,
        "multi_device_sync": CapabilityState.UNAVAILABLE,
        "private_channels": CapabilityState.DEVELOPMENT_ONLY,
        "social_graph": CapabilityState.DEVELOPMENT_ONLY,
    }
    if not enabled:
        states = {key: CapabilityState.UNAVAILABLE for key in states}
    return SocialReadiness(
        enabled=enabled,
        capabilities=tuple(
            SocialCapability(capability=key, state=states[key])  # type: ignore[arg-type]
            for key in sorted(states)
        ),
    )


__all__ = [
    "DEVELOPMENT_SOCIAL_GAPS",
    "DURABLE_LOCAL_SOCIAL_GAPS",
    "DIGEST_PATTERN",
    "MAX_CIPHERTEXT_BYTES",
    "MAX_FRIEND_REQUEST_LIFETIME",
    "MAX_GROUP_MEMBERS",
    "MAX_CLIENT_CLOCK_SKEW",
    "MAX_PRESENCE_LIFETIME",
    "SOCIAL_CONTRACT_VERSION",
    "SOCIAL_ID_PATTERN",
    "AeadAlgorithm",
    "AgreementAlgorithm",
    "BlockRecord",
    "CapabilityState",
    "ChannelMembership",
    "ChannelMembershipState",
    "ChannelRole",
    "Conversation",
    "ConversationKind",
    "ConversationReadState",
    "DeviceKeyReference",
    "DeviceState",
    "E2eeEnvelopeMetadata",
    "FriendRequest",
    "FriendRequestState",
    "Friendship",
    "MessageOperation",
    "MessageDeletionTombstone",
    "MessageReaction",
    "MessageReactionCode",
    "PeerDeletionAcknowledgement",
    "PeerDeletionState",
    "PresenceState",
    "PrivateChannel",
    "RelationshipPresence",
    "SigningAlgorithm",
    "SocialAccount",
    "SocialAccountState",
    "SocialAuditAction",
    "SocialAuditDecision",
    "SocialAuditEvent",
    "SocialCapability",
    "SocialDeletionReceipt",
    "SocialDeploymentProfile",
    "SocialDevice",
    "SocialMembershipState",
    "SocialOrganizationMembership",
    "SocialOrganizationRole",
    "SocialReadiness",
    "SocialReadinessGap",
    "SocialReasonCode",
    "SocialTeam",
    "SocialTeamMembership",
    "SocialTeamRole",
    "VerifiedSocialPrincipal",
    "development_social_readiness",
    "digest",
    "durable_local_social_readiness",
    "optional_social_id",
    "safe_version",
    "social_id",
    "utc_seconds",
]
