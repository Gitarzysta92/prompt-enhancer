"""Tenancy, device, credential, and audit contracts for the P3a control plane.

Every field in this module is drawn from a closed vocabulary, a pseudonymous
identifier, or a bounded number. That is a *minimized semantic surface*, not a
proof that nothing can be signalled through it: an authorized publisher still
controls which allowlisted keys it sends, what bounded values they carry, and
when it sends them, and those choices are a low-bandwidth covert channel that
no schema can remove. What the surface does guarantee is that no field carries
transcript text, prompts, snippets, rationales, model output, display names, or
free-form operator input, because no field accepts them.

Identifiers and audit rows are sensitive. They are pseudonymous, which is not
anonymous: an identifier that is stable across periods supports linkage, and an
audit trail describes real people's activity. Treat both as personal data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel


CONTROL_PLANE_CONTRACT_VERSION = "control-plane-v2"

MAX_TEAM_MEMBERSHIPS = 64
MAX_CLIENT_SCOPES = 8
MAX_VERIFICATION_MATERIAL_CHARACTERS = 512
MAX_SEAT_LIMIT = 10_000


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("control-plane identifiers must be HMAC pseudonyms")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    return None if value is None else _pseudonym(value)


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("control-plane codes must use safe identifier characters")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("control-plane timestamps must be UTC")
    if value.microsecond:
        raise ValueError("control-plane timestamps are whole seconds")
    return value


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


class DeploymentProfile(StrEnum):
    """Which adapter set is composed behind the control-plane ports."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class OrganizationRole(StrEnum):
    """Tenant-wide role. A role alone never grants access to private data."""

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"


MANAGERIAL_ROLES = frozenset(
    {OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MANAGER}
)
ADMINISTRATIVE_ROLES = frozenset(
    {OrganizationRole.OWNER, OrganizationRole.ADMIN}
)


class MembershipState(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class DeviceState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ApiClientState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class VisibilityScope(StrEnum):
    """Who may read a published snapshot. ``INDIVIDUAL`` is the safe default."""

    INDIVIDUAL = "individual"
    TEAM = "team"
    ORGANIZATION = "organization"


class ApiScope(StrEnum):
    """Capability granted to a tenant-scoped developer API client."""

    SNAPSHOTS_PUSH = "snapshots:push"
    SNAPSHOTS_PULL = "snapshots:pull"
    AGGREGATES_READ = "aggregates:read"
    AUDIT_READ = "audit:read"
    DELETION_REQUEST = "deletion:request"
    DIRECTORY_ADMINISTER = "directory:administer"


class ReasonCode(StrEnum):
    """Closed vocabulary for authorization and rejection reasons.

    An enumeration rather than a message keeps audit rows inside the minimized
    surface and makes it impossible to smuggle request text into evidence.
    """

    SELF_ACCESS = "self_access"
    TENANT_MEMBERSHIP = "tenant_membership"
    TEAM_VISIBILITY = "team_visibility"
    ORGANIZATION_VISIBILITY = "organization_visibility"
    MANAGER_GRANT = "manager_grant"
    ADMINISTRATIVE_ROLE = "administrative_role"
    DEFAULT_DENY = "default_deny"
    CROSS_TENANT = "cross_tenant"
    MEMBERSHIP_INACTIVE = "membership_inactive"
    DEVICE_INACTIVE = "device_inactive"
    DEVICE_NOT_BOUND = "device_not_bound"
    SCOPE_MISSING = "scope_missing"
    CLIENT_INACTIVE = "client_inactive"
    CREDENTIAL_REJECTED = "credential_rejected"
    SUBJECT_MISMATCH = "subject_mismatch"
    TEAM_MEMBERSHIP_REQUIRED = "team_membership_required"
    MANAGER_GRANT_REQUIRED = "manager_grant_required"
    INDIVIDUAL_VISIBILITY = "individual_visibility"
    SIGNATURE_INVALID = "signature_invalid"
    UNSUPPORTED_ALGORITHM = "unsupported_algorithm"
    KEY_MISMATCH = "key_mismatch"
    ENVELOPE_REPLAYED = "envelope_replayed"
    ENVELOPE_CONFLICT = "envelope_conflict"
    ENVELOPE_NOT_FRESH = "envelope_not_fresh"
    ENVELOPE_RESERVATION_EXPIRED = "envelope_reservation_expired"
    ENVELOPE_ID_UNREGISTERED = "envelope_id_unregistered"
    CURSOR_REGRESSION = "cursor_regression"
    CURSOR_NOT_OFFERED = "cursor_not_offered"
    SYNC_NOT_ENTITLED = "sync_not_entitled"
    ENTITLEMENT_MISSING = "entitlement_missing"


class AuditAction(StrEnum):
    """Closed vocabulary of auditable control-plane operations."""

    DEVICE_ENROLLED = "device_enrolled"
    DEVICE_REVOKED = "device_revoked"
    MEMBERSHIP_REVOKED = "membership_revoked"
    API_CLIENT_REVOKED = "api_client_revoked"
    SNAPSHOT_PUSHED = "snapshot_pushed"
    SNAPSHOT_REJECTED = "snapshot_rejected"
    ENVELOPE_IDENTIFIER_ISSUED = "envelope_identifier_issued"
    DELTA_PULLED = "delta_pulled"
    TEAM_AGGREGATE_READ = "team_aggregate_read"
    AUDIT_READ = "audit_read"
    MANAGER_ACCESS_USED = "manager_access_used"
    ACCESS_DENIED = "access_denied"
    SUBJECT_DATA_DELETED = "subject_data_deleted"
    MANAGER_GRANT_REVOKED = "manager_grant_revoked"


class AuditDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class Organization(StrictModel):
    """One tenant boundary. Display names are intentionally absent."""

    organization_id: str
    created_at: datetime

    _identifier = field_validator("organization_id")(_pseudonym)
    _created = field_validator("created_at")(_utc)


class Team(StrictModel):
    """A cohort inside one tenant. Display names are intentionally absent."""

    team_id: str
    organization_id: str
    created_at: datetime

    _identifiers = field_validator("team_id", "organization_id")(_pseudonym)
    _created = field_validator("created_at")(_utc)


class Membership(StrictModel):
    """A person's standing inside one tenant, with their team cohorts."""

    membership_id: str
    organization_id: str
    user_id: str
    role: OrganizationRole
    state: MembershipState
    team_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_TEAM_MEMBERSHIPS
    )
    created_at: datetime
    revoked_at: datetime | None = None

    _identifiers = field_validator(
        "membership_id", "organization_id", "user_id"
    )(_pseudonym)
    _created = field_validator("created_at")(_utc)
    _revoked = field_validator("revoked_at")(_optional_utc)

    @field_validator("team_ids")
    @classmethod
    def canonical_team_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("team identifiers must be unique and sorted")
        return tuple(_pseudonym(value) for value in values)

    @model_validator(mode="after")
    def coherent_revocation(self) -> Membership:
        if (self.state is MembershipState.REVOKED) != (self.revoked_at is not None):
            raise ValueError("revoked memberships require a revocation timestamp")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("revocation cannot precede creation")
        return self

    def is_active(self) -> bool:
        return self.state is MembershipState.ACTIVE

    def belongs_to_team(self, team_id: str) -> bool:
        return team_id in self.team_ids


class SignatureAlgorithm(StrEnum):
    """Envelope signature algorithms known to this contract version.

    ``ED25519`` is the production target and has no adapter in this slice, so
    the verifier registry fails closed on it. ``DEVELOPMENT_HMAC_SHA256`` uses
    symmetric material that both sides hold; it is sufficient to test tamper
    rejection and key binding locally, and it is not a public-key identity.
    """

    ED25519 = "ed25519"
    DEVELOPMENT_HMAC_SHA256 = "dev-hmac-sha256"


class DeviceVerificationKey(StrictModel):
    """Verification material held only by the store and the verifier.

    The material is a ``SecretStr`` so ordinary logging, exception rendering,
    and DTO serialization cannot reveal it. Public device records carry only the
    algorithm and the key fingerprint.
    """

    algorithm: SignatureAlgorithm
    key_fingerprint: str
    material: SecretStr = Field(repr=False)

    _fingerprint = field_validator("key_fingerprint")(_pseudonym)

    @field_validator("material")
    @classmethod
    def bounded_material(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or len(raw) > MAX_VERIFICATION_MATERIAL_CHARACTERS:
            raise ValueError("device verification material has an unexpected size")
        return value


class DeviceRegistration(StrictModel):
    """A request to bind one device key to one member of one tenant."""

    device_id: str
    organization_id: str
    user_id: str
    key: DeviceVerificationKey
    registered_at: datetime

    _identifiers = field_validator(
        "device_id", "organization_id", "user_id"
    )(_pseudonym)
    _registered = field_validator("registered_at")(_utc)


class Device(StrictModel):
    """Public device identity. It never carries verification material."""

    device_id: str
    organization_id: str
    user_id: str
    algorithm: SignatureAlgorithm
    key_fingerprint: str
    state: DeviceState
    registered_at: datetime
    revoked_at: datetime | None = None

    _identifiers = field_validator(
        "device_id", "organization_id", "user_id", "key_fingerprint"
    )(_pseudonym)
    _registered = field_validator("registered_at")(_utc)
    _revoked = field_validator("revoked_at")(_optional_utc)

    @model_validator(mode="after")
    def coherent_revocation(self) -> Device:
        if (self.state is DeviceState.REVOKED) != (self.revoked_at is not None):
            raise ValueError("revoked devices require a revocation timestamp")
        if self.revoked_at is not None and self.revoked_at < self.registered_at:
            raise ValueError("revocation cannot precede registration")
        return self

    def is_active(self) -> bool:
        return self.state is DeviceState.ACTIVE


class ApiClient(StrictModel):
    """A tenant-scoped developer client bound to one member and one device.

    The binding is the point. A credential for this client can act only as the
    member and device recorded here, so possessing it never lets a caller name
    somebody else. The credential secret itself is never modelled: only a
    verifier digest is stored, by the credential store.
    """

    client_id: str
    organization_id: str
    user_id: str
    device_id: str
    scopes: tuple[ApiScope, ...] = Field(min_length=1, max_length=MAX_CLIENT_SCOPES)
    state: ApiClientState
    created_at: datetime
    revoked_at: datetime | None = None

    _identifiers = field_validator(
        "client_id", "organization_id", "user_id", "device_id"
    )(_pseudonym)
    _created = field_validator("created_at")(_utc)
    _revoked = field_validator("revoked_at")(_optional_utc)

    @field_validator("scopes")
    @classmethod
    def canonical_scopes(cls, values: tuple[ApiScope, ...]) -> tuple[ApiScope, ...]:
        ordered = tuple(sorted(values, key=lambda scope: scope.value))
        if ordered != values or len(set(values)) != len(values):
            raise ValueError("client scopes must be unique and sorted")
        return values

    @model_validator(mode="after")
    def coherent_revocation(self) -> ApiClient:
        if (self.state is ApiClientState.REVOKED) != (self.revoked_at is not None):
            raise ValueError("revoked clients require a revocation timestamp")
        return self

    def is_active(self) -> bool:
        return self.state is ApiClientState.ACTIVE


class ManagerAccessGrant(StrictModel):
    """An explicit, expiring authorization for one manager to read one target.

    A grant names exactly one of a subject or a team, never both and never
    neither. Allowing both would make its blast radius ambiguous, and the
    ambiguity is precisely what an auditor needs to be able to state.
    """

    grant_id: str
    organization_id: str
    manager_user_id: str
    subject_user_id: str | None = None
    team_id: str | None = None
    granted_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    _identifiers = field_validator(
        "grant_id", "organization_id", "manager_user_id"
    )(_pseudonym)
    _optional_identifiers = field_validator("subject_user_id", "team_id")(
        _optional_pseudonym
    )
    _timestamps = field_validator("granted_at", "expires_at")(_utc)
    _revoked = field_validator("revoked_at")(_optional_utc)

    @model_validator(mode="after")
    def bounded_and_singly_targeted(self) -> ManagerAccessGrant:
        if self.expires_at <= self.granted_at:
            raise ValueError("manager grants must expire after they are granted")
        named = (self.subject_user_id is not None) + (self.team_id is not None)
        if named != 1:
            raise ValueError("manager grants name exactly one subject or team")
        if self.revoked_at is not None and self.revoked_at < self.granted_at:
            raise ValueError("grant revocation cannot precede grant creation")
        return self

    def is_active(self, now: datetime) -> bool:
        checked = _utc(now)
        if self.revoked_at is not None and checked >= self.revoked_at:
            return False
        return self.granted_at <= checked < self.expires_at

    def covers_subject(self, subject_user_id: str) -> bool:
        return self.subject_user_id == subject_user_id

    def covers_team(self, team_id: str | None) -> bool:
        return team_id is not None and self.team_id == team_id


class AuditEvent(StrictModel):
    """One immutable record of a control-plane decision.

    Audit rows are sensitive personal data: they describe who acted on whom and
    when. They are minimized, not anonymous.
    """

    audit_id: str
    organization_id: str
    sequence: int = Field(ge=1)
    recorded_at: datetime
    action: AuditAction
    decision: AuditDecision
    reason: ReasonCode
    actor_user_id: str | None = None
    actor_device_id: str | None = None
    actor_client_id: str | None = None
    subject_user_id: str | None = None
    team_id: str | None = None
    manager_grant_id: str | None = None

    _identifiers = field_validator("audit_id", "organization_id")(_pseudonym)
    _optional_identifiers = field_validator(
        "actor_user_id",
        "actor_device_id",
        "actor_client_id",
        "subject_user_id",
        "team_id",
        "manager_grant_id",
    )(_optional_pseudonym)
    _recorded = field_validator("recorded_at")(_utc)


class EntitlementTier(StrEnum):
    """Placeholder commercial tiers. No billing integration exists."""

    LOCAL_ONLY = "local_only"
    TEAM_PREVIEW = "team_preview"


class Entitlement(StrictModel):
    """What a tenant is currently permitted to do.

    ``remote_sync_enabled`` is the gate the service enforces for every
    publication and read, and it defaults to off. Turning it on is a deliberate
    per-tenant provisioning act; there is no global development bypass, so a
    tenant that nobody enabled synchronizes nothing.

    ``billing_enabled`` and ``remote_transport_available`` stay ``Literal[False]``
    because no billing integration and no off-machine transport exist at all. A
    ``None`` seat limit means unknown, not unlimited.
    """

    organization_id: str
    tier: EntitlementTier = EntitlementTier.LOCAL_ONLY
    seat_limit: int | None = Field(default=None, ge=1, le=MAX_SEAT_LIMIT)
    remote_sync_enabled: bool = False
    billing_enabled: Literal[False] = False
    remote_transport_available: Literal[False] = False
    evaluated_at: datetime

    _identifier = field_validator("organization_id")(_pseudonym)
    _evaluated = field_validator("evaluated_at")(_utc)


class ReadinessGap(StrEnum):
    """Exactly what is missing before this plane could serve a real team."""

    PRODUCTION_IDENTITY_PROVIDER_MISSING = "production_identity_provider_missing"
    PRODUCTION_SIGNATURE_ALGORITHM_MISSING = (
        "production_signature_algorithm_missing"
    )
    PRODUCTION_DATABASE_ADAPTER_MISSING = "production_database_adapter_missing"
    CREDENTIAL_LIFECYCLE_INCOMPLETE = "credential_lifecycle_incomplete"
    OUT_OF_BAND_PROVISIONING_ONLY = "out_of_band_provisioning_only"
    REMOTE_TRANSPORT_NOT_IMPLEMENTED = "remote_transport_not_implemented"
    BILLING_NOT_IMPLEMENTED = "billing_not_implemented"
    PRODUCER_PIPELINE_NOT_CONNECTED = "producer_pipeline_not_connected"
    DISCLOSURE_CONTROL_UNREVIEWED = "disclosure_control_unreviewed"
    DURABLE_RECIPIENT_DELIVERY_NOT_IMPLEMENTED = (
        "durable_recipient_delivery_not_implemented"
    )
    BACKUP_AND_REPLICA_ERASURE_NOT_IMPLEMENTED = (
        "backup_and_replica_erasure_not_implemented"
    )
    GOVERNANCE_REVIEW_PENDING = "governance_review_pending"


DEVELOPMENT_READINESS_GAPS: tuple[ReadinessGap, ...] = tuple(
    sorted(ReadinessGap, key=lambda gap: gap.value)
)


class ControlPlaneReadiness(StrictModel):
    """An explicit statement that this plane is not a finished product.

    ``production_ready`` is ``Literal[False]``. Making this plane production
    ready is a contract change with a new ADR, not a configuration value.
    """

    contract_version: str = CONTROL_PLANE_CONTRACT_VERSION
    profile: DeploymentProfile
    production_ready: Literal[False] = False
    remote_listening_enabled: Literal[False] = False
    delivery_guarantee: Literal["at_least_once_with_monotonic_ack"] = (
        "at_least_once_with_monotonic_ack"
    )
    gaps: tuple[ReadinessGap, ...] = Field(min_length=1)

    _version = field_validator("contract_version")(_safe_version)

    @field_validator("gaps")
    @classmethod
    def canonical_gaps(
        cls, values: tuple[ReadinessGap, ...]
    ) -> tuple[ReadinessGap, ...]:
        ordered = tuple(sorted(values, key=lambda gap: gap.value))
        if ordered != values or len(set(values)) != len(values):
            raise ValueError("readiness gaps must be unique and sorted")
        return values


__all__ = [
    "ADMINISTRATIVE_ROLES",
    "CONTROL_PLANE_CONTRACT_VERSION",
    "DEVELOPMENT_READINESS_GAPS",
    "MANAGERIAL_ROLES",
    "MAX_CLIENT_SCOPES",
    "MAX_SEAT_LIMIT",
    "MAX_TEAM_MEMBERSHIPS",
    "ApiClient",
    "ApiClientState",
    "ApiScope",
    "AuditAction",
    "AuditDecision",
    "AuditEvent",
    "ControlPlaneReadiness",
    "DeploymentProfile",
    "Device",
    "DeviceRegistration",
    "DeviceState",
    "DeviceVerificationKey",
    "Entitlement",
    "EntitlementTier",
    "ManagerAccessGrant",
    "Membership",
    "MembershipState",
    "Organization",
    "OrganizationRole",
    "ReadinessGap",
    "ReasonCode",
    "SignatureAlgorithm",
    "Team",
    "VisibilityScope",
]
