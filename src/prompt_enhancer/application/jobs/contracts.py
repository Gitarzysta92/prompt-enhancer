"""Content-free contracts for durable local analysis scheduling.

Jobs persist only pseudonymous targets, exact version identifiers, metric keys,
fingerprints, and execution state.  There is intentionally no field capable of
carrying a prompt, transcript, excerpt, model response, or provider credential.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    StrictModel,
)


ANALYSIS_JOB_CONTRACT_VERSION = "analysis-job-v1"
MAX_ANALYSIS_JOB_ATTEMPTS = 5
MAX_ANALYSIS_JOB_METRICS = 100
MAX_ANALYSIS_JOB_STAGES = 32
SESSION_QUALITY_PUBLICATION_BUDGET = timedelta(minutes=30)


class AnalysisJobKind(StrEnum):
    SESSION_QUALITY = "session_quality"
    SYNTHETIC_VALIDATION = "synthetic_validation"
    ESTIMATOR_EXECUTION = "estimator_execution"


class AnalysisJobState(StrEnum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    STAGE_N = "stage_n"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class AnalysisPublicationDeadlineFailure(StrEnum):
    """Reviewed, content-free reasons for a cooperative publication stop."""

    DEADLINE_EXCEEDED = "automation_publication_deadline_exceeded"
    CLOCK_REGRESSED = "automation_publication_clock_regressed"
    DEADLINE_MISSING = "automation_publication_deadline_missing"


class PowerSourceState(StrEnum):
    """Best-effort, content-free local power admission state."""

    EXTERNAL_POWER = "external_power"
    BATTERY = "battery"
    UNKNOWN = "unknown"


class PowerSourceReader(Protocol):
    def current(self) -> PowerSourceState: ...


ACTIVE_ANALYSIS_JOB_STATES = frozenset(
    {AnalysisJobState.PREPROCESSING, AnalysisJobState.STAGE_N}
)
TERMINAL_ANALYSIS_JOB_STATES = frozenset(
    {
        AnalysisJobState.COMPLETED,
        AnalysisJobState.PARTIAL,
        AnalysisJobState.FAILED,
        AnalysisJobState.CANCELLED,
        AnalysisJobState.SUPERSEDED,
    }
)


def _safe_id(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a pseudonymous identifier")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


class AnalysisJobIdentity(StrictModel):
    """Immutable scheduling identity used for deduplication."""

    kind: AnalysisJobKind
    provider: Provider
    project_id: str
    session_id: str
    input_fingerprint: str
    provenance_fingerprint: str
    metric_keys: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_ANALYSIS_JOB_METRICS,
    )
    estimator_plan_version: str
    redactor_version: str
    provider_schema_version: str
    automation_grant_id: str | None = None
    local_only: bool = True

    _safe_ids = field_validator(
        "project_id",
        "session_id",
        "input_fingerprint",
        "provenance_fingerprint",
    )(_safe_id)
    _safe_versions = field_validator(
        "estimator_plan_version",
        "redactor_version",
        "provider_schema_version",
    )(_safe_version)

    @field_validator("automation_grant_id")
    @classmethod
    def safe_optional_grant_id(cls, value: str | None) -> str | None:
        return None if value is None else _safe_id(value)

    @field_validator("metric_keys")
    @classmethod
    def metric_set_is_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(values))
        if values != normalized or len(set(values)) != len(values):
            raise ValueError("metric keys must be unique and sorted")
        return tuple(_safe_version(value) for value in values)

    @model_validator(mode="after")
    def remote_execution_is_not_a_queue_capability(self) -> AnalysisJobIdentity:
        if not self.local_only:
            raise ValueError("durable analysis jobs are local-only")
        return self


class AnalysisJobDraft(StrictModel):
    job_id: str
    dedupe_key: str
    identity: AnalysisJobIdentity
    max_attempts: int = Field(ge=1, le=MAX_ANALYSIS_JOB_ATTEMPTS)
    created_at: datetime

    _safe_ids = field_validator("job_id", "dedupe_key")(_safe_id)
    _utc_created = field_validator("created_at")(_utc)


class AnalysisJobRecord(StrictModel):
    job_id: str
    dedupe_key: str
    identity: AnalysisJobIdentity
    state: AnalysisJobState
    stage_number: int | None = Field(default=None, ge=1, le=MAX_ANALYSIS_JOB_STAGES)
    progress_completed: int = Field(ge=0, le=1_000_000)
    progress_total: int = Field(ge=1, le=1_000_000)
    attempt_count: int = Field(ge=0, le=MAX_ANALYSIS_JOB_ATTEMPTS)
    max_attempts: int = Field(ge=1, le=MAX_ANALYSIS_JOB_ATTEMPTS)
    available_at: datetime
    cancel_requested: bool
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    runtime_started_at: datetime | None = None
    publication_deadline_at: datetime | None = None
    publication_high_water_at: datetime | None = None
    last_error_code: str | None = None
    terminal_reason_code: str | None = None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None = None

    _safe_ids = field_validator("job_id", "dedupe_key")(_safe_id)
    _utc_timestamps = field_validator(
        "available_at", "created_at", "updated_at"
    )(_utc)

    @field_validator("lease_owner", "lease_token")
    @classmethod
    def safe_optional_ids(cls, value: str | None) -> str | None:
        return None if value is None else _safe_id(value)

    @field_validator(
        "lease_expires_at",
        "runtime_started_at",
        "publication_deadline_at",
        "publication_high_water_at",
        "terminal_at",
    )
    @classmethod
    def utc_optional_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @field_validator("last_error_code", "terminal_reason_code")
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_version(value)

    @model_validator(mode="after")
    def coherent_runtime_state(self) -> AnalysisJobRecord:
        leased = self.state in ACTIVE_ANALYSIS_JOB_STATES
        lease_values = (
            self.lease_owner,
            self.lease_token,
            self.lease_expires_at,
        )
        if leased != all(value is not None for value in lease_values):
            raise ValueError("active jobs require a complete lease")
        if not leased and any(value is not None for value in lease_values):
            raise ValueError("inactive jobs cannot retain a lease")
        if (self.state is AnalysisJobState.STAGE_N) != (
            self.stage_number is not None
        ):
            raise ValueError("only stage_n jobs carry a stage number")
        terminal = self.state in TERMINAL_ANALYSIS_JOB_STATES
        if terminal != (self.terminal_at is not None):
            raise ValueError("terminal jobs require a terminal timestamp")
        if terminal != (self.terminal_reason_code is not None):
            raise ValueError("terminal jobs require a reason code")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt count exceeds retry bound")
        if self.progress_completed > self.progress_total:
            raise ValueError("progress cannot exceed its total")
        publication_values = (
            self.runtime_started_at,
            self.publication_deadline_at,
            self.publication_high_water_at,
        )
        if any(value is not None for value in publication_values) and not all(
            value is not None for value in publication_values
        ):
            raise ValueError("publication deadline metadata must be complete")
        if all(value is not None for value in publication_values):
            started_at = self.runtime_started_at
            deadline_at = self.publication_deadline_at
            high_water_at = self.publication_high_water_at
            assert started_at is not None
            assert deadline_at is not None
            assert high_water_at is not None
            if (
                self.identity.kind is not AnalysisJobKind.SESSION_QUALITY
                or self.identity.automation_grant_id is None
            ):
                raise ValueError(
                    "publication deadlines are limited to automated session quality"
                )
            if self.attempt_count < 1:
                raise ValueError("publication deadlines require a first claim")
            if not started_at <= high_water_at < deadline_at:
                raise ValueError("publication deadline chronology is invalid")
            if deadline_at - started_at != SESSION_QUALITY_PUBLICATION_BUDGET:
                raise ValueError("publication deadline uses an unsupported budget")
        return self


class AnalysisJobEnqueueResult(StrictModel):
    job: AnalysisJobRecord
    created: bool


class AnalysisJobLease(StrictModel):
    job_id: str
    owner: str
    token: str
    expires_at: datetime

    _safe_ids = field_validator("job_id", "owner", "token")(_safe_id)
    _utc_expiry = field_validator("expires_at")(_utc)


class AnalysisJobRecoveryResult(StrictModel):
    requeued: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    failed: int = Field(ge=0)
    superseded: int = Field(ge=0)


class AnalysisJobCancellationBatchResult(StrictModel):
    cancelled: int = Field(ge=0)
    cancellation_requested: int = Field(ge=0)


class AnalysisJobPage(StrictModel):
    jobs: tuple[AnalysisJobRecord, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AnalysisJobRepository(Protocol):
    def enqueue(self, draft: AnalysisJobDraft) -> AnalysisJobEnqueueResult: ...

    def get(self, job_id: str) -> AnalysisJobRecord | None: ...

    def list(
        self,
        *,
        state: AnalysisJobState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AnalysisJobPage: ...

    def list_active(self, *, limit: int = 100) -> AnalysisJobPage: ...

    def get_latest_for_session(self, session_id: str) -> AnalysisJobRecord | None: ...

    def claim_next(
        self,
        *,
        owner: str,
        token: str,
        now: datetime,
        lease_duration: timedelta,
        power_source: PowerSourceState = PowerSourceState.UNKNOWN,
    ) -> AnalysisJobRecord | None: ...

    def recover_expired(self, *, now: datetime) -> AnalysisJobRecoveryResult: ...

    def renew(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> AnalysisJobRecord: ...

    def advance_stage(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        stage_number: int,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord: ...

    def check_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
    ) -> AnalysisJobRecord: ...

    def fail_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        failure: AnalysisPublicationDeadlineFailure,
    ) -> AnalysisJobRecord: ...

    def await_approval(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        reason_code: str,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord: ...

    def resume_after_approval(
        self,
        job_id: str,
        *,
        now: datetime,
    ) -> AnalysisJobRecord: ...

    def request_cancel(self, job_id: str, *, now: datetime) -> AnalysisJobRecord: ...

    def cancel_by_automation_grant(
        self,
        automation_grant_id: str,
        *,
        now: datetime,
    ) -> AnalysisJobCancellationBatchResult: ...

    def supersede(
        self,
        job_id: str,
        *,
        now: datetime,
        reason_code: str,
    ) -> AnalysisJobRecord: ...

    def finish(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        state: AnalysisJobState,
        reason_code: str,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord: ...

    def retry_or_fail(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        error_code: str,
        retryable: bool,
    ) -> AnalysisJobRecord: ...
