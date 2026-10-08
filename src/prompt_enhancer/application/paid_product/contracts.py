"""Closed contracts for the optional paid-product development boundary.

The local analyzer does not depend on these contracts.  Persistent identifiers
are keyed pseudonyms, version-like fields use a restricted alphabet, and no
model in this module has a place for profile data, transcript text, prompts,
provider credentials, payment-card data, or free-form audit messages.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_METRIC_TEXT_PATTERN, SAFE_VERSION_PATTERN, StrictModel


PAID_PRODUCT_CONTRACT_VERSION = "paid-product-v1"
MAX_JOB_METRICS = 20
MAX_RESULT_METRICS = 20
MAX_APPROVED_PAYLOAD_BYTES = 500_000
MAX_MONEY_MICRO_UNITS = 1_000_000_000_000


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("paid-product identifiers must be keyed pseudonyms")
    return value


def _safe(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("paid-product codes must use safe identifier characters")
    return value


def _metric_key(value: str) -> str:
    if SAFE_METRIC_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("metric keys must use the reviewed metric-key alphabet")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("paid-product timestamps must be UTC")
    if value.microsecond:
        raise ValueError("paid-product timestamps are whole seconds")
    return value


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


class ProductDeploymentProfile(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class TenantJobDestination(StrEnum):
    """Only commercial APIs are valid production destinations.

    ``SYNTHETIC_TEST`` exists so the development service can exercise the full
    state machine without network access.  Composition rejects it outside the
    development profile.  Personal/local CLIs are intentionally unrepresentable.
    """

    OFFICIAL_OPENAI_API = "official_openai_api"
    OFFICIAL_ANTHROPIC_API = "official_anthropic_api"
    SYNTHETIC_TEST = "synthetic_test"


PRODUCTION_JOB_DESTINATIONS = frozenset(
    {
        TenantJobDestination.OFFICIAL_OPENAI_API,
        TenantJobDestination.OFFICIAL_ANTHROPIC_API,
    }
)


class RetentionClass(StrEnum):
    ZERO_DATA_RETENTION = "zero_data_retention"
    PROVIDER_STANDARD = "provider_standard"
    SYNTHETIC_EPHEMERAL = "synthetic_ephemeral"


class PaidScope(StrEnum):
    JOBS_SUBMIT = "jobs:submit"
    JOBS_READ = "jobs:read"
    JOBS_CANCEL = "jobs:cancel"
    BILLING_READ = "billing:read"
    BILLING_ADMINISTER = "billing:administer"


class EntitlementFeature(StrEnum):
    TEAM_SYNC = "team_sync"
    HOSTED_DEEP_ANALYSIS = "hosted_deep_analysis"


class EntitlementDeltaKind(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class WebhookDisposition(StrEnum):
    APPLIED = "applied"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class SpendHoldState(StrEnum):
    HELD = "held"
    SETTLED = "settled"
    RELEASED = "released"
    COST_UNKNOWN = "cost_unknown"


class ApprovalState(StrEnum):
    AVAILABLE = "available"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class DeepJobState(StrEnum):
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COST_UNKNOWN = "cost_unknown"


class PaidReasonCode(StrEnum):
    DEFAULT_DENY = "default_deny"
    CROSS_TENANT = "cross_tenant"
    PRINCIPAL_INACTIVE = "principal_inactive"
    SCOPE_MISSING = "scope_missing"
    ENTITLEMENT_MISSING = "entitlement_missing"
    DESTINATION_UNAVAILABLE = "destination_unavailable"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_MISMATCH = "approval_mismatch"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REPLAYED = "approval_replayed"
    SPEND_LIMIT_EXCEEDED = "spend_limit_exceeded"
    WEBHOOK_SIGNATURE_INVALID = "webhook_signature_invalid"
    WEBHOOK_STALE = "webhook_stale"
    WEBHOOK_CONFLICT = "webhook_conflict"
    OIDC_ASSERTION_INVALID = "oidc_assertion_invalid"
    OIDC_NONCE_REPLAYED = "oidc_nonce_replayed"
    PROVIDER_FAILED = "provider_failed"
    RESULT_INVALID = "result_invalid"
    COST_UNKNOWN = "cost_unknown"


class Account(StrictModel):
    account_id: str
    created_at: datetime
    disabled_at: datetime | None = None

    _ids = field_validator("account_id")(_pseudonym)
    _created = field_validator("created_at")(_utc)
    _disabled = field_validator("disabled_at")(_optional_utc)

    @model_validator(mode="after")
    def coherent_disable(self) -> Account:
        if self.disabled_at is not None and self.disabled_at < self.created_at:
            raise ValueError("account disablement cannot precede creation")
        return self


class AccountIdentityBinding(StrictModel):
    account_id: str
    issuer_id: str
    subject_pseudonym: str
    created_at: datetime

    _ids = field_validator("account_id", "subject_pseudonym")(_pseudonym)
    _issuer = field_validator("issuer_id")(_safe)
    _created = field_validator("created_at")(_utc)


class TenantAccountBinding(StrictModel):
    organization_id: str
    account_id: str
    user_id: str
    created_at: datetime

    _ids = field_validator("organization_id", "account_id", "user_id")(_pseudonym)
    _created = field_validator("created_at")(_utc)


class VerifiedOidcAssertion(StrictModel):
    """Ephemeral result from a registered verifier; never a persistence row."""

    issuer_id: str
    audience: str
    raw_subject: SecretStr
    nonce_id: str
    issued_at: datetime
    expires_at: datetime

    _codes = field_validator("issuer_id", "audience")(_safe)
    _nonce = field_validator("nonce_id")(_pseudonym)
    _issued = field_validator("issued_at")(_utc)
    _expires = field_validator("expires_at")(_utc)

    @model_validator(mode="after")
    def coherent_interval(self) -> VerifiedOidcAssertion:
        if self.expires_at <= self.issued_at:
            raise ValueError("OIDC assertion expiry must follow issuance")
        if len(self.raw_subject.get_secret_value()) not in range(1, 257):
            raise ValueError("OIDC subject length is out of bounds")
        return self


class PaidPrincipal(StrictModel):
    organization_id: str
    user_id: str
    account_id: str
    client_id: str
    device_id: str
    scopes: tuple[PaidScope, ...] = Field(max_length=8)
    verified_at: datetime
    expires_at: datetime
    active: bool

    _ids = field_validator(
        "organization_id", "user_id", "account_id", "client_id", "device_id"
    )(_pseudonym)
    _verified = field_validator("verified_at")(_utc)
    _expires = field_validator("expires_at")(_utc)

    @field_validator("scopes")
    @classmethod
    def canonical_scopes(cls, values: tuple[PaidScope, ...]) -> tuple[PaidScope, ...]:
        if values != tuple(sorted(set(values), key=str)):
            raise ValueError("paid scopes must be unique and sorted")
        return values

    @model_validator(mode="after")
    def coherent_expiry(self) -> PaidPrincipal:
        if self.expires_at <= self.verified_at:
            raise ValueError("principal expiry must follow verification")
        return self


class EntitlementLedgerEntry(StrictModel):
    entry_id: str
    organization_id: str
    provider_event_id: str
    provider_event_digest: str
    ledger_sequence: int = Field(ge=1)
    feature: EntitlementFeature
    kind: EntitlementDeltaKind
    effective_at: datetime
    expires_at: datetime | None = None
    recorded_at: datetime

    _ids = field_validator("entry_id", "organization_id", "provider_event_id")(_pseudonym)
    _digest = field_validator("provider_event_digest")(_pseudonym)
    _effective = field_validator("effective_at", "recorded_at")(_utc)
    _expires = field_validator("expires_at")(_optional_utc)

    @model_validator(mode="after")
    def coherent_expiry(self) -> EntitlementLedgerEntry:
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("entitlement expiry must follow its effective time")
        return self


class EntitlementProjection(StrictModel):
    organization_id: str
    feature: EntitlementFeature
    enabled: bool
    effective_at: datetime | None
    expires_at: datetime | None
    projected_at: datetime

    _org = field_validator("organization_id")(_pseudonym)
    _effective = field_validator("effective_at", "expires_at")(_optional_utc)
    _projected = field_validator("projected_at")(_utc)


class SignedBillingWebhook(StrictModel):
    provider_event_id: str
    provider_event_digest: str
    organization_id: str
    entry_id: str
    feature: EntitlementFeature
    kind: EntitlementDeltaKind
    effective_at: datetime
    expires_at: datetime | None = None
    delivered_at: datetime
    signature: SecretStr

    _ids = field_validator("provider_event_id", "organization_id", "entry_id")(_pseudonym)
    _digest = field_validator("provider_event_digest")(_pseudonym)
    _times = field_validator("effective_at", "delivered_at")(_utc)
    _expires = field_validator("expires_at")(_optional_utc)


class SpendPolicy(StrictModel):
    organization_id: str
    user_id: str
    user_limit_micro: int = Field(ge=1, le=MAX_MONEY_MICRO_UNITS)
    currency: Literal["usd_micro"] = "usd_micro"

    _ids = field_validator("organization_id", "user_id")(_pseudonym)


class OrganizationSpendPolicy(StrictModel):
    organization_id: str
    organization_limit_micro: int = Field(ge=1, le=MAX_MONEY_MICRO_UNITS)
    currency: Literal["usd_micro"] = "usd_micro"

    _id = field_validator("organization_id")(_pseudonym)


class SpendHold(StrictModel):
    hold_id: str
    organization_id: str
    user_id: str
    job_id: str
    amount_micro: int = Field(ge=1, le=MAX_MONEY_MICRO_UNITS)
    state: SpendHoldState
    created_at: datetime
    settled_amount_micro: int | None = Field(default=None, ge=0, le=MAX_MONEY_MICRO_UNITS)
    settled_at: datetime | None = None

    _ids = field_validator("hold_id", "organization_id", "user_id", "job_id")(_pseudonym)
    _created = field_validator("created_at")(_utc)
    _settled = field_validator("settled_at")(_optional_utc)

    @model_validator(mode="after")
    def coherent_state(self) -> SpendHold:
        terminal = self.state in {SpendHoldState.SETTLED, SpendHoldState.RELEASED}
        if terminal != (self.settled_at is not None):
            raise ValueError("terminal spend holds require a settlement time")
        if self.state is SpendHoldState.SETTLED and self.settled_amount_micro is None:
            raise ValueError("settled holds require an actual amount")
        if self.state is not SpendHoldState.SETTLED and self.settled_amount_micro is not None:
            raise ValueError("only settled holds carry an actual amount")
        return self


class RemoteAnalysisApproval(StrictModel):
    approval_id: str
    organization_id: str
    user_id: str
    provider: TenantJobDestination
    model_id: str
    window_fingerprint: str
    payload_pseudonym: str
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=MAX_JOB_METRICS)
    redactor_version: str
    retention_class: RetentionClass
    approved_payload_bytes: int = Field(ge=1, le=MAX_APPROVED_PAYLOAD_BYTES)
    max_cost_micro: int = Field(ge=1, le=MAX_MONEY_MICRO_UNITS)
    state: ApprovalState
    approved_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    _ids = field_validator("approval_id", "organization_id", "user_id")(_pseudonym)
    _codes = field_validator("model_id", "redactor_version")(_safe)
    _window = field_validator("window_fingerprint", "payload_pseudonym")(_pseudonym)
    _approved = field_validator("approved_at")(_utc)
    _expires = field_validator("expires_at")(_utc)
    _consumed = field_validator("consumed_at")(_optional_utc)

    @field_validator("metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_metric_key(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("approved metric keys must be unique and sorted")
        return checked

    @model_validator(mode="after")
    def coherent_state(self) -> RemoteAnalysisApproval:
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiry must follow approval")
        consumed = self.state is ApprovalState.CONSUMED
        if consumed != (self.consumed_at is not None):
            raise ValueError("consumed approvals require a consumed timestamp")
        if (
            self.provider is TenantJobDestination.SYNTHETIC_TEST
        ) != (self.retention_class is RetentionClass.SYNTHETIC_EPHEMERAL):
            raise ValueError("synthetic retention is limited to the synthetic destination")
        return self


class DeepAnalysisRequest(StrictModel):
    job_id: str
    organization_id: str
    user_id: str
    approval_id: str
    hold_id: str
    destination: TenantJobDestination
    model_id: str
    window_fingerprint: str
    payload_pseudonym: str
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=MAX_JOB_METRICS)
    redactor_version: str
    retention_class: RetentionClass
    payload_bytes: int = Field(ge=1, le=MAX_APPROVED_PAYLOAD_BYTES)
    estimated_cost_micro: int = Field(ge=1, le=MAX_MONEY_MICRO_UNITS)
    requested_at: datetime

    _ids = field_validator(
        "job_id", "organization_id", "user_id", "approval_id", "hold_id"
    )(_pseudonym)
    _codes = field_validator("model_id", "redactor_version")(_safe)
    _window = field_validator("window_fingerprint", "payload_pseudonym")(_pseudonym)
    _requested = field_validator("requested_at")(_utc)

    @field_validator("metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_metric_key(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("requested metric keys must be unique and sorted")
        return checked

    @model_validator(mode="after")
    def coherent_retention(self) -> DeepAnalysisRequest:
        if (
            self.destination is TenantJobDestination.SYNTHETIC_TEST
        ) != (self.retention_class is RetentionClass.SYNTHETIC_EPHEMERAL):
            raise ValueError("synthetic retention is limited to the synthetic destination")
        return self


class MetricJudgment(StrictModel):
    metric_key: str
    value: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)

    _metric = field_validator("metric_key")(_metric_key)


class ProviderResult(StrictModel):
    provider_receipt_id: str
    destination: TenantJobDestination
    model_id: str
    judgments: tuple[MetricJudgment, ...] = Field(max_length=MAX_RESULT_METRICS)
    actual_cost_micro: int | None = Field(default=None, ge=0, le=MAX_MONEY_MICRO_UNITS)
    completed_at: datetime

    _receipt = field_validator("provider_receipt_id")(_pseudonym)
    _model = field_validator("model_id")(_safe)
    _completed = field_validator("completed_at")(_utc)

    @field_validator("judgments")
    @classmethod
    def canonical_judgments(cls, values: tuple[MetricJudgment, ...]) -> tuple[MetricJudgment, ...]:
        keys = tuple(item.metric_key for item in values)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("provider judgments must be unique and sorted")
        return values


class DeepAnalysisJob(StrictModel):
    job_id: str
    organization_id: str
    user_id: str
    destination: TenantJobDestination
    model_id: str
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=MAX_JOB_METRICS)
    state: DeepJobState
    requested_at: datetime
    completed_at: datetime | None = None
    provider_receipt_id: str | None = None
    judgments: tuple[MetricJudgment, ...] = Field(
        default=(), max_length=MAX_RESULT_METRICS
    )
    reason: PaidReasonCode | None = None

    _ids = field_validator("job_id", "organization_id", "user_id")(_pseudonym)
    _model = field_validator("model_id")(_safe)
    _completed = field_validator("completed_at")(_optional_utc)

    @field_validator("provider_receipt_id")
    @classmethod
    def optional_receipt(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_metric_key(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("job metric keys must be unique and sorted")
        return checked

    @field_validator("judgments")
    @classmethod
    def canonical_judgments(
        cls, values: tuple[MetricJudgment, ...]
    ) -> tuple[MetricJudgment, ...]:
        keys = tuple(value.metric_key for value in values)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("job judgments must be unique and sorted")
        return values

    @model_validator(mode="after")
    def coherent_state(self) -> DeepAnalysisJob:
        if self.state is DeepJobState.QUEUED:
            if (
                self.completed_at is not None
                or self.provider_receipt_id is not None
                or self.judgments
                or self.reason is not None
            ):
                raise ValueError("queued jobs cannot carry terminal output")
            return self
        if self.completed_at is None:
            raise ValueError("terminal jobs require a completion timestamp")
        if self.state is DeepJobState.COMPLETED:
            if (
                self.provider_receipt_id is None
                or tuple(item.metric_key for item in self.judgments)
                != self.metric_keys
                or self.reason is not None
            ):
                raise ValueError("completed jobs require exact reviewed judgments")
        elif self.reason is None:
            raise ValueError("non-complete terminal jobs require a fixed reason")
        return self


class PaidAuditAction(StrEnum):
    SIGN_IN = "sign_in"
    WEBHOOK_APPLIED = "webhook_applied"
    WEBHOOK_REPLAYED = "webhook_replayed"
    SPEND_HELD = "spend_held"
    SPEND_SETTLED = "spend_settled"
    SPEND_COST_UNKNOWN = "spend_cost_unknown"
    APPROVAL_CONSUMED = "approval_consumed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    ACCESS_DENIED = "access_denied"


class PaidAuditEvent(StrictModel):
    event_id: str
    organization_id: str
    actor_user_id: str | None = None
    action: PaidAuditAction
    allowed: bool
    reason: PaidReasonCode | None = None
    occurred_at: datetime

    _ids = field_validator("event_id", "organization_id")(_pseudonym)
    _occurred = field_validator("occurred_at")(_utc)

    @field_validator("actor_user_id")
    @classmethod
    def optional_actor(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)


class ProductReadiness(StrictModel):
    contract_version: Literal["paid-product-v1"] = PAID_PRODUCT_CONTRACT_VERSION
    production_ready: Literal[False] = False
    remote_transport_enabled: Literal[False] = False
    real_identity_provider_registered: Literal[False] = False
    real_billing_provider_registered: Literal[False] = False
    real_llm_provider_registered: Literal[False] = False
    durable_store_registered: Literal[False] = False
    backup_verified: Literal[False] = False
    retention_approved: Literal[False] = False
    monitoring_configured: Literal[False] = False
    gaps: tuple[str, ...]

    @field_validator("gaps")
    @classmethod
    def canonical_gaps(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_safe(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("readiness gaps must be unique and sorted")
        return checked


DEVELOPMENT_PRODUCT_READINESS = ProductReadiness(
    gaps=tuple(
        sorted(
            {
                "backup_unverified",
                "crash_reconciler_unmounted",
                "durable_store_missing",
                "erasure_policy_missing",
                "local_receipt_tamper_seal_missing",
                "monitoring_missing",
                "production_billing_missing",
                "production_identity_missing",
                "production_provider_missing",
                "remote_transport_disabled",
                "retention_approval_missing",
            }
        )
    )
)


__all__ = [
    "Account",
    "AccountIdentityBinding",
    "ApprovalState",
    "DEVELOPMENT_PRODUCT_READINESS",
    "DeepAnalysisJob",
    "DeepAnalysisRequest",
    "DeepJobState",
    "EntitlementDeltaKind",
    "EntitlementFeature",
    "EntitlementLedgerEntry",
    "EntitlementProjection",
    "MetricJudgment",
    "OrganizationSpendPolicy",
    "PAID_PRODUCT_CONTRACT_VERSION",
    "PRODUCTION_JOB_DESTINATIONS",
    "PaidAuditAction",
    "PaidAuditEvent",
    "PaidPrincipal",
    "PaidReasonCode",
    "PaidScope",
    "ProductDeploymentProfile",
    "ProductReadiness",
    "ProviderResult",
    "RemoteAnalysisApproval",
    "RetentionClass",
    "SignedBillingWebhook",
    "SpendHold",
    "SpendHoldState",
    "SpendPolicy",
    "TenantAccountBinding",
    "TenantJobDestination",
    "VerifiedOidcAssertion",
    "WebhookDisposition",
]
