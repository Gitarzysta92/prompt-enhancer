"""Contracts for consented, owner-hosted, direct-only file transfers.

The control-plane surface stores integrity and authorization metadata only.
File bytes, network candidates, credentials, private keys, absolute paths and
file names are absent.  A safe basename exists only in the owner-local
``LocalFileDescriptor`` consumed by a local access port; it must never be sent
to or persisted by the control plane.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...domain import StrictModel
from ..social.contracts import SOCIAL_ID_PATTERN, social_id, utc_seconds
from .integrity import compute_merkle_root


FILE_SHARING_CONTRACT_VERSION = "direct-file-sharing-v1"
SHARE_ID_PATTERN = re.compile(r"^shr_[a-f0-9]{64}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
SAFE_BASENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,239}$")

MIN_CHUNK_BYTES = 64 * 1024
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024 * 1024
MAX_CHUNKS = 16_384
MAX_RECIPIENTS_PER_SHARE = 64
MAX_RANGES_PER_REQUEST = 1_024
MAX_AVAILABILITY_LIFETIME = timedelta(minutes=2)
MAX_TRANSFER_LIFETIME = timedelta(hours=24)
MAX_MANIFEST_LIFETIME = timedelta(days=30)

_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def share_id(value: str) -> str:
    if SHARE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("file-sharing identifiers must be opaque shr_ identifiers")
    return value


def optional_share_id(value: str | None) -> str | None:
    return None if value is None else share_id(value)


def sha256_digest(value: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("integrity digests must be lowercase SHA-256 hex")
    return value


def safe_local_basename(value: str) -> str:
    """Accept one portable basename and reject every path-like spelling."""

    if SAFE_BASENAME_PATTERN.fullmatch(value) is None:
        raise ValueError("local file name contains unsafe characters")
    if value in {".", ".."} or value.endswith((".", " ")):
        raise ValueError("local file name is not canonical")
    if any(character in value for character in ("/", "\\", ":", "\x00")):
        raise ValueError("local file name must not contain path syntax")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("local file name contains control characters")
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise ValueError("local file name is reserved by the operating system")
    return value


class FileContentKind(StrEnum):
    ARCHIVE = "archive"
    AUDIO = "audio"
    DOCUMENT = "document"
    IMAGE = "image"
    OTHER = "other"
    SOURCE_BUNDLE = "source_bundle"
    VIDEO = "video"


class ChunkDigest(StrictModel):
    index: int = Field(ge=0, lt=MAX_CHUNKS)
    offset: int = Field(ge=0, le=MAX_FILE_BYTES)
    size: int = Field(ge=1, le=MAX_CHUNK_BYTES)
    sha256: str

    _digest = field_validator("sha256")(sha256_digest)


class FileManifest(StrictModel):
    """Immutable, content-free integrity manifest for one selected file."""

    manifest_id: str
    organization_id: str
    owner_account_id: str
    owner_device_id: str
    content_kind: FileContentKind
    byte_size: int = Field(ge=1, le=MAX_FILE_BYTES)
    chunk_size: int = Field(ge=MIN_CHUNK_BYTES, le=MAX_CHUNK_BYTES)
    whole_file_sha256: str
    merkle_root_sha256: str
    chunks: tuple[ChunkDigest, ...] = Field(min_length=1, max_length=MAX_CHUNKS)
    created_at: datetime
    expires_at: datetime
    manifest_version: Literal[1] = 1
    immutable: Literal[True] = True
    stores_file_name: Literal[False] = False
    stores_file_path: Literal[False] = False

    _manifest = field_validator("manifest_id")(share_id)
    _social_ids = field_validator(
        "organization_id", "owner_account_id", "owner_device_id"
    )(social_id)
    _digests = field_validator("whole_file_sha256", "merkle_root_sha256")(
        sha256_digest
    )
    _times = field_validator("created_at", "expires_at")(utc_seconds)

    @model_validator(mode="after")
    def complete_chunk_coverage(self) -> FileManifest:
        if self.expires_at <= self.created_at:
            raise ValueError("file manifest expiry must follow creation")
        if self.expires_at - self.created_at > MAX_MANIFEST_LIFETIME:
            raise ValueError("file manifest lifetime exceeds the retention bound")
        expected_count = (self.byte_size + self.chunk_size - 1) // self.chunk_size
        if len(self.chunks) != expected_count:
            raise ValueError("file manifest does not cover the declared size")
        for index, chunk in enumerate(self.chunks):
            expected_offset = index * self.chunk_size
            remaining = self.byte_size - expected_offset
            expected_size = min(self.chunk_size, remaining)
            if (
                chunk.index != index
                or chunk.offset != expected_offset
                or chunk.size != expected_size
            ):
                raise ValueError("file manifest chunks are not canonical and contiguous")
        if compute_merkle_root(self.chunks) != self.merkle_root_sha256:
            raise ValueError("file manifest Merkle root does not match its chunks")
        return self


class LocalFileDescriptor(StrictModel):
    """Owner-local quarantine reference; never a control-plane record."""

    local_file_id: str
    manifest_id: str
    safe_basename: str
    quarantine_root_id: str
    symlink_or_reparse_checked: Literal[True]

    _ids = field_validator("local_file_id", "manifest_id", "quarantine_root_id")(
        share_id
    )
    _name = field_validator("safe_basename")(safe_local_basename)


class FileGrantState(StrEnum):
    OFFERED = "offered"
    CONSENTED = "consented"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class FileRecipientGrant(StrictModel):
    organization_id: str
    grant_id: str
    manifest_id: str
    owner_account_id: str
    recipient_account_id: str
    state: FileGrantState
    offered_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None
    revoked_at: datetime | None = None
    explicit_recipient_consent: bool = False

    _social_ids = field_validator(
        "organization_id", "owner_account_id", "recipient_account_id"
    )(social_id)
    _share_ids = field_validator("grant_id", "manifest_id")(share_id)
    _times = field_validator("offered_at", "expires_at")(utc_seconds)

    @field_validator("decided_at", "revoked_at")
    @classmethod
    def optional_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else utc_seconds(value)

    @model_validator(mode="after")
    def valid_lifecycle(self) -> FileRecipientGrant:
        if self.owner_account_id == self.recipient_account_id:
            raise ValueError("file share recipient must differ from owner")
        if self.expires_at <= self.offered_at:
            raise ValueError("file grant expiry must follow offer")
        if self.decided_at is not None and not (
            self.offered_at <= self.decided_at <= self.expires_at
        ):
            raise ValueError("file grant decision is outside its lifetime")
        if self.revoked_at is not None and self.revoked_at < self.offered_at:
            raise ValueError("file grant revocation predates offer")
        if self.state is FileGrantState.CONSENTED:
            if not self.explicit_recipient_consent or self.decided_at is None:
                raise ValueError("consented file grant requires explicit consent")
        elif self.explicit_recipient_consent:
            raise ValueError("only a consented file grant may carry consent")
        if self.state is FileGrantState.REVOKED:
            if self.revoked_at is None:
                raise ValueError("revoked file grant requires a timestamp")
        elif self.revoked_at is not None:
            raise ValueError("only revoked file grants carry a revocation timestamp")
        if self.state in {FileGrantState.DECLINED, FileGrantState.EXPIRED}:
            if self.decided_at is None:
                raise ValueError("terminal file grant requires a decision timestamp")
        return self


class PeerAvailabilityState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class OwnerFileAvailability(StrictModel):
    organization_id: str
    manifest_id: str
    owner_account_id: str
    owner_device_id: str
    state: PeerAvailabilityState
    observed_at: datetime
    expires_at: datetime
    direct_only: Literal[True] = True

    _social_ids = field_validator(
        "organization_id", "owner_account_id", "owner_device_id"
    )(social_id)
    _manifest = field_validator("manifest_id")(share_id)
    _times = field_validator("observed_at", "expires_at")(utc_seconds)

    @model_validator(mode="after")
    def short_lived(self) -> OwnerFileAvailability:
        if not self.observed_at < self.expires_at:
            raise ValueError("availability expiry must follow observation")
        if self.expires_at - self.observed_at > MAX_AVAILABILITY_LIFETIME:
            raise ValueError("availability assertion lives too long")
        return self


class ByteRange(StrictModel):
    start: int = Field(ge=0, le=MAX_FILE_BYTES)
    end_exclusive: int = Field(ge=1, le=MAX_FILE_BYTES)

    @model_validator(mode="after")
    def ordered(self) -> ByteRange:
        if self.end_exclusive <= self.start:
            raise ValueError("byte range end must follow start")
        return self


class TransferState(StrEnum):
    QUEUED_ON_SENDER = "queued_on_sender"
    WAITING_RECIPIENT_CONSENT = "waiting_recipient_consent"
    WAITING_OWNER_APPROVAL = "waiting_owner_approval"
    NEGOTIATING_DIRECT = "negotiating_direct"
    DIRECT_READY = "direct_ready"
    TRANSFERRING = "transferring"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVOKED = "revoked"


class TransferFailureReason(StrEnum):
    DIRECT_PATH_UNAVAILABLE = "direct_path_unavailable"
    EXPIRED = "expired"
    INTEGRITY_FAILED = "integrity_failed"
    INVALID_RANGE = "invalid_range"
    MANIFEST_REVOKED = "manifest_revoked"
    OWNER_OFFLINE = "owner_offline"
    RECIPIENT_OFFLINE = "recipient_offline"
    OWNER_APPROVAL_MISSING = "owner_approval_missing"
    QUOTA_EXCEEDED = "quota_exceeded"
    RECIPIENT_CONSENT_MISSING = "recipient_consent_missing"
    SENDER_QUEUE_EXPIRING = "sender_queue_expiring"
    SIGNALING_UNAVAILABLE = "signaling_unavailable"
    SYMMETRIC_NAT_OR_CGNAT = "symmetric_nat_or_cgnat"
    UNREACHABLE_NO_RELAY = "unreachable_no_relay"
    REVOKED_BEFORE_COMPLETION = "revoked_before_completion"
    MANIFEST_INVALID = "manifest_invalid"
    QUARANTINE_REJECTED_PATH = "quarantine_rejected_path"


TERMINAL_TRANSFER_STATES = frozenset(
    {
        TransferState.COMPLETED,
        TransferState.FAILED,
        TransferState.CANCELLED,
        TransferState.REVOKED,
    }
)


class DirectTransferRequest(StrictModel):
    organization_id: str
    transfer_id: str
    manifest_id: str
    grant_id: str
    requester_account_id: str
    requester_device_id: str
    ranges: tuple[ByteRange, ...] = Field(
        min_length=1, max_length=MAX_RANGES_PER_REQUEST
    )
    created_at: datetime
    expires_at: datetime
    relay_allowed: Literal[False] = False
    cloud_byte_fallback_allowed: Literal[False] = False

    _social_ids = field_validator(
        "organization_id", "requester_account_id", "requester_device_id"
    )(social_id)
    _share_ids = field_validator("transfer_id", "manifest_id", "grant_id")(
        share_id
    )
    _times = field_validator("created_at", "expires_at")(utc_seconds)

    @model_validator(mode="after")
    def canonical_ranges(self) -> DirectTransferRequest:
        if not self.created_at < self.expires_at:
            raise ValueError("transfer expiry must follow creation")
        if self.expires_at - self.created_at > MAX_TRANSFER_LIFETIME:
            raise ValueError("transfer request lives too long")
        prior_end = 0
        for index, selected in enumerate(self.ranges):
            if index and selected.start < prior_end:
                raise ValueError("transfer ranges must be sorted and non-overlapping")
            prior_end = selected.end_exclusive
        return self


class DirectConnectivityState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class DirectConnectivityAssessment(StrictModel):
    transfer_id: str
    state: DirectConnectivityState
    reason: TransferFailureReason | None = None
    authenticated_signaling: bool
    relay_used: Literal[False] = False
    candidate_data_persisted: Literal[False] = False
    assessed_at: datetime

    _transfer = field_validator("transfer_id")(share_id)
    _assessed = field_validator("assessed_at")(utc_seconds)

    @model_validator(mode="after")
    def state_has_reason(self) -> DirectConnectivityAssessment:
        if (self.state is DirectConnectivityState.UNAVAILABLE) != (
            self.reason is not None
        ):
            raise ValueError("unavailable direct connectivity requires one reason")
        return self


class TransferApproval(StrictModel):
    organization_id: str
    transfer_id: str
    manifest_id: str
    owner_account_id: str
    owner_device_id: str
    approved_at: datetime
    explicit_per_transfer_approval: Literal[True] = True

    _share_ids = field_validator("transfer_id", "manifest_id")(share_id)
    _social_ids = field_validator(
        "organization_id", "owner_account_id", "owner_device_id"
    )(social_id)
    _approved = field_validator("approved_at")(utc_seconds)


class TransferRecord(StrictModel):
    request: DirectTransferRequest
    state: TransferState
    failure_reason: TransferFailureReason | None = None
    owner_approved_at: datetime | None = None
    changed_at: datetime
    received_bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    completed_whole_file_sha256: str | None = None
    remote_recall_guaranteed: Literal[False] = False

    _changed = field_validator("changed_at")(utc_seconds)

    @field_validator("owner_approved_at")
    @classmethod
    def optional_approval_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else utc_seconds(value)

    @field_validator("completed_whole_file_sha256")
    @classmethod
    def optional_digest(cls, value: str | None) -> str | None:
        return None if value is None else sha256_digest(value)

    @model_validator(mode="after")
    def valid_terminal_state(self) -> TransferRecord:
        approved_states = {
            TransferState.NEGOTIATING_DIRECT,
            TransferState.DIRECT_READY,
            TransferState.TRANSFERRING,
            TransferState.VERIFYING,
            TransferState.COMPLETED,
        }
        preapproval_states = {
            TransferState.QUEUED_ON_SENDER,
            TransferState.WAITING_RECIPIENT_CONSENT,
            TransferState.WAITING_OWNER_APPROVAL,
        }
        if self.state in approved_states and self.owner_approved_at is None:
            raise ValueError("post-approval transfer state requires owner approval")
        if self.state in preapproval_states and self.owner_approved_at is not None:
            raise ValueError("pre-approval transfer state cannot carry owner approval")
        if self.owner_approved_at is not None and not (
            self.request.created_at <= self.owner_approved_at <= self.changed_at
        ):
            raise ValueError("transfer approval timestamp is outside its lifecycle")
        if self.changed_at < self.request.created_at:
            raise ValueError("transfer state change predates its request")
        if self.state is TransferState.FAILED:
            if self.failure_reason is None:
                raise ValueError("failed transfer requires a reason")
        elif self.failure_reason is not None:
            raise ValueError("only failed transfer carries a failure reason")
        if self.state is TransferState.COMPLETED:
            if self.completed_whole_file_sha256 is None:
                raise ValueError("completed transfer requires whole-file verification")
        elif self.completed_whole_file_sha256 is not None:
            raise ValueError("only completed transfer carries a final digest")
        return self


class TransferIntegrityEvidence(StrictModel):
    """Recipient-local verification result; it contains no file bytes."""

    transfer_id: str
    manifest_id: str
    received_bytes: int = Field(ge=1, le=MAX_FILE_BYTES)
    whole_file_sha256: str
    chunk_sha256: tuple[str, ...] = Field(min_length=1, max_length=MAX_CHUNKS)
    verified_at: datetime

    _share_ids = field_validator("transfer_id", "manifest_id")(share_id)
    _whole = field_validator("whole_file_sha256")(sha256_digest)
    _verified = field_validator("verified_at")(utc_seconds)

    @field_validator("chunk_sha256")
    @classmethod
    def valid_chunk_digests(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            sha256_digest(item)
        return value


class FileShareReasonCode(StrEnum):
    ALLOWED = "allowed"
    DEFAULT_DENY = "default_deny"
    PRINCIPAL_INACTIVE = "principal_inactive"
    DEVICE_INACTIVE = "device_inactive"
    BLOCKED_OR_UNAVAILABLE = "blocked_or_unavailable"
    MANIFEST_UNAVAILABLE = "manifest_unavailable"
    GRANT_UNAVAILABLE = "grant_unavailable"
    CONSENT_REQUIRED = "consent_required"
    OWNER_APPROVAL_REQUIRED = "owner_approval_required"
    STATE_CONFLICT = "state_conflict"
    REQUEST_REPLAYED = "request_replayed"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_RANGE = "invalid_range"
    INTEGRITY_FAILED = "integrity_failed"
    DIRECT_CONNECTIVITY_UNAVAILABLE = "direct_connectivity_unavailable"
    LOCAL_FILE_ACCESS_UNAVAILABLE = "local_file_access_unavailable"


class FileShareQuota(StrictModel):
    max_active_manifests_per_owner: int = Field(default=128, ge=1, le=10_000)
    max_recipients_per_manifest: int = Field(
        default=MAX_RECIPIENTS_PER_SHARE,
        ge=1,
        le=MAX_RECIPIENTS_PER_SHARE,
    )
    max_concurrent_transfers_per_owner: int = Field(default=4, ge=1, le=64)
    max_bytes_per_manifest: int = Field(
        default=32 * 1024 * 1024 * 1024, ge=1, le=MAX_FILE_BYTES
    )


class FileShareAuditAction(StrEnum):
    MANIFEST_REGISTERED = "manifest_registered"
    GRANT_OFFERED = "grant_offered"
    GRANT_CONSENTED = "grant_consented"
    GRANT_DECLINED = "grant_declined"
    GRANT_REVOKED = "grant_revoked"
    TRANSFER_REQUESTED = "transfer_requested"
    TRANSFER_APPROVED = "transfer_approved"
    DIRECT_NEGOTIATION_FAILED = "direct_negotiation_failed"
    TRANSFER_COMPLETED = "transfer_completed"
    TRANSFER_CANCELLED = "transfer_cancelled"
    MANIFEST_REVOKED = "manifest_revoked"
    ACCESS_DENIED = "access_denied"


class FileShareAuditEvent(StrictModel):
    organization_id: str
    audit_id: str
    actor_account_id: str
    actor_device_id: str
    manifest_id: str | None = None
    transfer_id: str | None = None
    action: FileShareAuditAction
    occurred_at: datetime

    _social_ids = field_validator(
        "organization_id", "actor_account_id", "actor_device_id"
    )(social_id)
    _audit = field_validator("audit_id")(share_id)
    _optional_ids = field_validator("manifest_id", "transfer_id")(
        optional_share_id
    )
    _occurred = field_validator("occurred_at")(utc_seconds)


class FileRevocationReceipt(StrictModel):
    organization_id: str
    manifest_id: str
    receipt_id: str
    revoked_grants: int = Field(ge=0)
    cancelled_active_transfers: int = Field(ge=0)
    owner_will_no_longer_serve_bytes: Literal[True] = True
    already_received_bytes_recalled: Literal[False] = False
    completed_at: datetime

    _organization = field_validator("organization_id")(social_id)
    _share_ids = field_validator("manifest_id", "receipt_id")(share_id)
    _completed = field_validator("completed_at")(utc_seconds)


class FileSharingReadinessGap(StrEnum):
    AUTHENTICATED_SIGNALING_UNAVAILABLE = "authenticated_signaling_unavailable"
    DIRECT_CONNECTIVITY_UNVERIFIED = "direct_connectivity_unverified"
    SYMMETRIC_NAT_AND_CGNAT_UNSUPPORTED = "symmetric_nat_and_cgnat_unsupported"
    TURN_RELAY_ABSENT = "turn_relay_absent"
    REVIEWED_TRANSPORT_ENCRYPTION_UNAVAILABLE = (
        "reviewed_transport_encryption_unavailable"
    )
    DURABLE_TRANSFER_RESUME_UNAVAILABLE = "durable_transfer_resume_unavailable"
    MALWARE_SCANNING_UNAVAILABLE = "malware_scanning_unavailable"
    LEGAL_CONTROLLER_UNDETERMINED = "legal_controller_undetermined"
    RETENTION_POLICY_UNAPPROVED = "retention_policy_unapproved"
    METADATA_VISIBLE_TO_CONTROL_PLANE = "metadata_visible_to_control_plane"


DEVELOPMENT_FILE_SHARING_GAPS = tuple(
    sorted(FileSharingReadinessGap, key=lambda item: item.value)
)


class FileSharingReadiness(StrictModel):
    contract_version: Literal["direct-file-sharing-v1"] = FILE_SHARING_CONTRACT_VERSION
    enabled: bool
    production_ready: Literal[False] = False
    direct_only: Literal[True] = True
    relay_allowed: Literal[False] = False
    cloud_file_byte_storage: Literal[False] = False
    offline_recipient_queue_location: Literal["sender_device_only"] = (
        "sender_device_only"
    )
    remote_recall_guaranteed: Literal[False] = False
    central_file_name_storage: Literal[False] = False
    central_file_path_storage: Literal[False] = False
    local_history_deleted_on_entitlement_lapse: Literal[False] = False
    received_files_deleted_on_entitlement_lapse: Literal[False] = False
    local_export_requires_active_entitlement: Literal[False] = False
    capability_state: Literal["contract_only"] = "contract_only"
    gaps: tuple[FileSharingReadinessGap, ...] = DEVELOPMENT_FILE_SHARING_GAPS

    @model_validator(mode="after")
    def canonical_gaps(self) -> FileSharingReadiness:
        if self.gaps != tuple(sorted(set(self.gaps), key=lambda item: item.value)):
            raise ValueError("file-sharing readiness gaps must be unique and sorted")
        return self


__all__ = [
    "DEVELOPMENT_FILE_SHARING_GAPS",
    "FILE_SHARING_CONTRACT_VERSION",
    "MAX_CHUNKS",
    "MAX_FILE_BYTES",
    "MAX_RANGES_PER_REQUEST",
    "MAX_RECIPIENTS_PER_SHARE",
    "SHARE_ID_PATTERN",
    "ByteRange",
    "ChunkDigest",
    "DirectConnectivityAssessment",
    "DirectConnectivityState",
    "DirectTransferRequest",
    "FileContentKind",
    "FileGrantState",
    "FileManifest",
    "FileRecipientGrant",
    "FileRevocationReceipt",
    "FileShareAuditAction",
    "FileShareAuditEvent",
    "FileShareQuota",
    "FileShareReasonCode",
    "FileSharingReadiness",
    "FileSharingReadinessGap",
    "LocalFileDescriptor",
    "OwnerFileAvailability",
    "PeerAvailabilityState",
    "TransferApproval",
    "TransferFailureReason",
    "TransferRecord",
    "TransferIntegrityEvidence",
    "TransferState",
    "safe_local_basename",
    "sha256_digest",
    "share_id",
]
