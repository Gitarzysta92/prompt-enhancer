"""Content-free contracts for renewable local analysis automation grants."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel


AUTOMATION_GRANT_CONTRACT_VERSION = "automation-grant-v1"
AUTOMATION_GRANT_LIFETIME = timedelta(days=30)
DEFAULT_AUTOMATION_NEWEST_SESSIONS = 20
DEFAULT_AUTOMATION_INTERVAL_SECONDS = 15 * 60
MAX_AUTOMATION_METRICS = 100
MAX_AUTOMATION_NEWEST_SESSIONS = 100


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("automation identifiers must be HMAC pseudonyms")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("automation codes must use safe identifier characters")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("automation timestamps must be UTC")
    return value


class AutomationRoute(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class AutomationGrantState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class AutomationResourcePolicy(StrictModel):
    route: AutomationRoute = Field(
        default=AutomationRoute.BALANCED,
        description="Persisted historical route; only balanced is currently executable.",
    )
    max_gpu_workers: Literal[1] = Field(
        default=1,
        description="Persisted GPU admission ceiling; current session-quality use is zero.",
    )
    max_cpu_workers: int = Field(
        default=1, ge=1, le=4,
        description="Persisted per-grant CPU admission ceiling; only one is currently reviewed.",
    )
    pause_on_battery: bool = Field(
        default=True,
        description="Admission intent only; it does not promise interruption of running work.",
    )
    maximum_session_seconds: int = Field(
        default=30 * 60, ge=60, le=4 * 60 * 60,
        description="Declared runtime budget; it does not imply a hard enforced deadline.",
    )


REVIEWED_AUTOMATION_RESOURCE_POLICY = AutomationResourcePolicy(
    route=AutomationRoute.BALANCED,
    max_gpu_workers=1,
    max_cpu_workers=1,
    pause_on_battery=True,
    maximum_session_seconds=30 * 60,
)


def is_reviewed_automation_resource_policy(
    policy: AutomationResourcePolicy,
) -> bool:
    """Return whether new work uses the only currently reviewed profile.

    The broad contract intentionally remains loadable so historical grants can
    be inspected.  Admission decisions must call this predicate explicitly.
    ``maximum_session_seconds`` is a declared runtime budget; this predicate
    does not claim that a hard execution deadline is currently enforced.
    """

    return policy == REVIEWED_AUTOMATION_RESOURCE_POLICY


class AutomationGrantScope(StrictModel):
    provider: Provider
    project_id: str
    metric_keys: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_AUTOMATION_METRICS,
    )
    newest_session_limit: int = Field(
        default=DEFAULT_AUTOMATION_NEWEST_SESSIONS,
        ge=1,
        le=MAX_AUTOMATION_NEWEST_SESSIONS,
    )
    check_interval_seconds: int = Field(
        default=DEFAULT_AUTOMATION_INTERVAL_SECONDS,
        ge=60,
        le=24 * 60 * 60,
    )
    resource_policy: AutomationResourcePolicy = Field(
        default_factory=AutomationResourcePolicy
    )
    local_only: Literal[True] = True
    remote_requires_fresh_approval: Literal[True] = True

    _safe_project = field_validator("project_id")(_pseudonym)

    @field_validator("metric_keys")
    @classmethod
    def canonical_metric_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(set(values)) != len(values):
            raise ValueError("automation metric keys must be unique and sorted")
        return tuple(_safe_version(value) for value in values)


class AutomationGrantDraft(StrictModel):
    grant_id: str
    scope: AutomationGrantScope
    created_at: datetime
    expires_at: datetime

    _safe_id = field_validator("grant_id")(_pseudonym)
    _utc_timestamps = field_validator("created_at", "expires_at")(_utc)

    @model_validator(mode="after")
    def exact_lifetime(self) -> AutomationGrantDraft:
        if self.expires_at - self.created_at != AUTOMATION_GRANT_LIFETIME:
            raise ValueError("automation grants require the fixed 30-day lifetime")
        return self


class AutomationGrantRecord(StrictModel):
    grant_id: str
    revision: int = Field(ge=1)
    scope: AutomationGrantScope
    state: AutomationGrantState
    created_at: datetime
    renewed_at: datetime
    expires_at: datetime
    next_check_at: datetime
    last_checked_at: datetime | None = None
    revoked_at: datetime | None = None
    last_error_code: str | None = None

    _safe_id = field_validator("grant_id")(_pseudonym)
    _utc_required = field_validator(
        "created_at", "renewed_at", "expires_at", "next_check_at"
    )(_utc)

    @field_validator("last_checked_at", "revoked_at")
    @classmethod
    def utc_optional(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @field_validator("last_error_code")
    @classmethod
    def safe_optional_code(cls, value: str | None) -> str | None:
        return None if value is None else _safe_version(value)

    @model_validator(mode="after")
    def coherent_state(self) -> AutomationGrantRecord:
        if self.expires_at - self.renewed_at != AUTOMATION_GRANT_LIFETIME:
            raise ValueError("renewal must establish a fresh 30-day lifetime")
        if self.renewed_at < self.created_at:
            raise ValueError("renewal cannot precede creation")
        if (self.state is AutomationGrantState.REVOKED) != (
            self.revoked_at is not None
        ):
            raise ValueError("revoked grants require a revocation timestamp")
        if self.state is not AutomationGrantState.REVOKED and self.revoked_at:
            raise ValueError("non-revoked grants cannot retain revocation state")
        return self

    def effective_state(self, now: datetime) -> AutomationGrantState:
        checked = _utc(now)
        if self.state is AutomationGrantState.REVOKED:
            return self.state
        if checked >= self.expires_at:
            return AutomationGrantState.EXPIRED
        return AutomationGrantState.ACTIVE

    def is_due(self, now: datetime) -> bool:
        checked = _utc(now)
        return (
            self.effective_state(checked) is AutomationGrantState.ACTIVE
            and checked >= self.next_check_at
        )


class AutomationSessionCandidate(StrictModel):
    provider: Provider
    project_id: str
    session_id: str
    input_fingerprint: str
    provenance_fingerprint: str
    provider_schema_version: str
    updated_at: datetime

    _safe_ids = field_validator(
        "project_id",
        "session_id",
        "input_fingerprint",
        "provenance_fingerprint",
    )(_pseudonym)
    _safe_schema = field_validator("provider_schema_version")(_safe_version)
    _utc_updated = field_validator("updated_at")(_utc)


class AutomationGrantRepository(Protocol):
    def create(self, draft: AutomationGrantDraft) -> AutomationGrantRecord: ...

    def get(self, grant_id: str) -> AutomationGrantRecord | None: ...

    def list_due(self, *, now: datetime, limit: int) -> tuple[AutomationGrantRecord, ...]: ...

    def list_for_provider(
        self,
        provider: Provider,
        *,
        active_only: bool,
    ) -> tuple[AutomationGrantRecord, ...]: ...

    def expire_due(self, *, now: datetime) -> int: ...

    def renew(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord: ...

    def revoke(self, grant_id: str, *, now: datetime) -> AutomationGrantRecord: ...

    def record_check(
        self,
        grant_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        error_code: str | None,
    ) -> AutomationGrantRecord: ...


class AutomationCandidateSource(Protocol):
    def newest_changed(
        self,
        scope: AutomationGrantScope,
        *,
        limit: int,
    ) -> tuple[AutomationSessionCandidate, ...]: ...


__all__ = [
    "AUTOMATION_GRANT_CONTRACT_VERSION",
    "AUTOMATION_GRANT_LIFETIME",
    "AutomationCandidateSource",
    "AutomationGrantDraft",
    "AutomationGrantRecord",
    "AutomationGrantRepository",
    "AutomationGrantScope",
    "AutomationGrantState",
    "AutomationResourcePolicy",
    "AutomationRoute",
    "AutomationSessionCandidate",
    "DEFAULT_AUTOMATION_INTERVAL_SECONDS",
    "DEFAULT_AUTOMATION_NEWEST_SESSIONS",
    "REVIEWED_AUTOMATION_RESOURCE_POLICY",
    "is_reviewed_automation_resource_policy",
]
