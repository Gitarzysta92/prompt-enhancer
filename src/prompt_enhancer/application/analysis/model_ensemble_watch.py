"""Durable opt-in scheduling for one continuously refreshed model ensemble.

The watch stores only pseudonymous identifiers, fingerprints, fixed reason
codes, progress counters, and timestamps.  Redacted text remains inside the
existing ephemeral ensemble execution boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
from threading import Event, Lock, Thread
from typing import Callable, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, SAFE_VERSION_PATTERN, StrictModel
from ..runtime_cancellation import RuntimeCooperativeStop
from .text_source import TEXT_ANALYSIS_PROVIDERS
from .model_ensemble import (
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    SessionModelEnsembleMetricReceipt,
    SessionModelEnsembleTypedMetricReceipt,
    SourceCoverageState,
)
from .session_model_ensemble import (
    MODEL_ENSEMBLE_CONFIRMATION,
    ModelEnsembleRuntimeCleanupError,
    SessionModelEnsembleError,
    SessionModelEnsembleOutcome,
    SessionModelEnsemblePersistenceAuthority,
)
from .probabilistic_metrics import (
    PROBABILISTIC_METRIC_PROJECTION_VERSION,
    SessionPredictiveMetricSummary,
)
from .metric_projection_v2 import MetricStateV2


MODEL_ENSEMBLE_WATCH_CONTRACT_VERSION = "model-ensemble-watch-v1"
MODEL_ENSEMBLE_WATCH_CONFIRMATION = "continuously_analyze_selected_redacted_session"
MODEL_ENSEMBLE_WATCH_POLL_SECONDS = 60
MODEL_ENSEMBLE_WATCH_LEASE_SECONDS = 5 * 60
MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL = 10
MODEL_ENSEMBLE_ATTEMPT_CONTRACT_VERSION = "model-ensemble-attempt-v1"
MODEL_ENSEMBLE_WATCH_MAX_FAILURE_STREAK = 6
MODEL_ENSEMBLE_WATCH_MAX_BACKOFF_SECONDS = 60 * 60
MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED = "watch_failure_streak_exhausted"
MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED = "watch_lease_recovered"
MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED = "redacted_content_consent_revoked"
_WORKER_START_FAILURE = "worker_start_failed"
_WORKER_STOP_IN_PROGRESS = "worker_stop_in_progress"
_WORKER_STOP_FAILURE = "worker_stop_failed"
_WORKER_STOP_TIMEOUT = "worker_stop_timeout"

# Failures that no amount of retrying can repair without a user action.  A
# watch that hits one of these is quarantined immediately instead of being
# hot-looped on the poll cadence.  Every other reason is retried under the
# bounded exponential backoff until the streak budget is exhausted.
MODEL_ENSEMBLE_WATCH_NONRETRYABLE_REASONS = frozenset(
    {
        "invalid_model_ensemble_request",
        "model_ensemble_confirmation_required",
        "redacted_content_consent_required",
        MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
        "session_not_in_safe_index",
        "provider_compatibility_blocked",
        "privacy_deleted",
        "model_ensemble_cleanup_unconfirmed",
    }
)


class ModelEnsembleWatchFailureClass(StrEnum):
    RETRYABLE = "retryable"
    NONRETRYABLE = "nonretryable"


def classify_watch_failure(reason_code: str) -> ModelEnsembleWatchFailureClass:
    """Map a fixed reason code to its durable retry class."""

    if reason_code in MODEL_ENSEMBLE_WATCH_NONRETRYABLE_REASONS:
        return ModelEnsembleWatchFailureClass.NONRETRYABLE
    return ModelEnsembleWatchFailureClass.RETRYABLE


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_id(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("watch identifier must be a local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("watch reason must be a fixed content-free code")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("watch timestamp must be UTC")
    return value


class ModelEnsembleWatchState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    IDLE = "idle"
    FAILED = "failed"
    DISABLED = "disabled"


class ModelEnsembleAttemptState(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelEnsembleStageState(StrEnum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ModelEnsembleAttemptRecord(StrictModel):
    """Content-free execution ledger for one exact watch generation."""

    attempt_id: str
    watch_id: str
    generation: int = Field(ge=1, le=1_000_000_000)
    state: ModelEnsembleAttemptState
    prior_head_run_id: str | None = None
    published_run_id: str | None = None
    progress_completed: int = Field(ge=0, le=32)
    progress_total: int = Field(ge=1, le=32)
    stage_count: int = Field(ge=0, le=32)
    warning_count: int = Field(ge=0, le=32)
    error_code: str | None = None
    requested_at: datetime
    started_at: datetime
    completed_at: datetime | None = None

    _ids = field_validator(
        "attempt_id", "watch_id", "prior_head_run_id", "published_run_id"
    )(lambda value: None if value is None else _safe_id(value))
    _reason = field_validator("error_code")(
        lambda value: None if value is None else _safe_code(value)
    )
    _times = field_validator("requested_at", "started_at", "completed_at")(
        lambda value: None if value is None else _utc(value)
    )

    @model_validator(mode="after")
    def validate_attempt(self) -> "ModelEnsembleAttemptRecord":
        terminal = self.state is not ModelEnsembleAttemptState.RUNNING
        if terminal != (self.completed_at is not None):
            raise ValueError("only terminal attempts have a completion timestamp")
        if self.progress_completed > self.progress_total:
            raise ValueError("attempt progress cannot exceed its total")
        if self.state in {
            ModelEnsembleAttemptState.COMPLETED,
            ModelEnsembleAttemptState.PARTIAL,
        } and self.published_run_id is None:
            raise ValueError("published attempts require an exact run binding")
        if self.state is ModelEnsembleAttemptState.COMPLETED and (
            self.warning_count != 0 or self.error_code is not None
        ):
            raise ValueError("completed attempts cannot contain warnings")
        if self.state is ModelEnsembleAttemptState.PARTIAL and self.warning_count < 1:
            raise ValueError("partial attempts require at least one warning")
        if self.state in {
            ModelEnsembleAttemptState.FAILED,
            ModelEnsembleAttemptState.CANCELLED,
        } and self.error_code is None:
            raise ValueError("failed or cancelled attempts require a fixed reason")
        if self.state is ModelEnsembleAttemptState.RUNNING and (
            self.published_run_id is not None
            or self.warning_count != 0
            or self.error_code is not None
        ):
            raise ValueError("running attempts cannot claim a result")
        return self


class ModelEnsembleAttemptStageReceipt(StrictModel):
    """One immutable, content-free stage result within an attempt."""

    attempt_id: str
    stage_ordinal: int = Field(ge=0, le=31)
    stage_key: str
    state: ModelEnsembleStageState
    model_key: str | None = None
    repository_id: str | None = None
    revision: str | None = None
    error_code: str | None = None
    device: Literal["cpu", "cuda", "mps"] | None = None
    quantization: Literal["none", "bitsandbytes_nf4"] = "none"
    inference_latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    peak_accelerator_memory_mb: float | None = Field(
        default=None, ge=0, le=16_384, allow_inf_nan=False
    )
    process_rss_mb: float | None = Field(
        default=None, ge=0, le=32_768, allow_inf_nan=False
    )
    evaluated_case_count: int | None = Field(default=None, ge=0, le=100_000)
    contributed_case_count: int | None = Field(default=None, ge=0, le=100_000)
    unloaded_after_stage: bool | None = None
    completed_at: datetime

    _attempt = field_validator("attempt_id")(_safe_id)
    _safe_values = field_validator("stage_key", "model_key", "revision")(
        lambda value: None if value is None else _safe_code(value)
    )
    _error = field_validator("error_code")(
        lambda value: None if value is None else _safe_code(value)
    )
    _time = field_validator("completed_at")(_utc)

    @field_validator("repository_id")
    @classmethod
    def validate_repository(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not 3 <= len(value) <= 192
            or "/" not in value
            or ".." in value
            or any(
                character
                not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/"
                for character in value
            )
        ):
            raise ValueError("stage repository identity is invalid")
        return value

    @model_validator(mode="after")
    def validate_stage(self) -> "ModelEnsembleAttemptStageReceipt":
        if self.state is ModelEnsembleStageState.COMPLETED:
            if self.error_code is not None:
                raise ValueError("completed stages cannot contain an error")
        elif self.error_code is None:
            raise ValueError("incomplete stages require a fixed error")
        if (
            self.evaluated_case_count is not None
            and self.contributed_case_count is not None
            and self.contributed_case_count > self.evaluated_case_count
        ):
            raise ValueError("stage contributions cannot exceed evaluated cases")
        return self


class ModelEnsembleCanonicalHead(StrictModel):
    """Lightweight head and active-attempt identity shared by all clients."""

    watch: "ModelEnsembleWatchRecord"
    head_run_id: str | None = None
    head_generation: int | None = Field(default=None, ge=1, le=1_000_000_000)
    latest_attempt: ModelEnsembleAttemptRecord | None = None
    stages: tuple[ModelEnsembleAttemptStageReceipt, ...] = Field(
        default=(), max_length=32
    )

    @model_validator(mode="after")
    def validate_head(self) -> "ModelEnsembleCanonicalHead":
        if (self.head_run_id is None) != (self.head_generation is None):
            raise ValueError("canonical head identity must be complete")
        if self.head_run_id != self.watch.latest_run_id:
            raise ValueError("canonical head must match the watch binding")
        if self.latest_attempt is not None:
            if (
                self.latest_attempt.watch_id != self.watch.watch_id
                or self.latest_attempt.generation != self.watch.generation
            ):
                raise ValueError("attempt is not bound to the canonical watch head")
            if self.latest_attempt.state in {
                ModelEnsembleAttemptState.COMPLETED,
                ModelEnsembleAttemptState.PARTIAL,
            } and self.latest_attempt.published_run_id != self.head_run_id:
                raise ValueError("published attempt does not match the canonical head")
            if self.latest_attempt.state is ModelEnsembleAttemptState.RUNNING:
                if self.stages or self.latest_attempt.stage_count != 0:
                    raise ValueError("running attempts cannot expose terminal stages")
            elif len(self.stages) != self.latest_attempt.stage_count:
                raise ValueError("terminal attempt stage graph is incomplete")
            if self.latest_attempt.warning_count != sum(
                stage.state is not ModelEnsembleStageState.COMPLETED
                for stage in self.stages
            ):
                raise ValueError("attempt warning count does not match its stages")
        if self.stages:
            if self.latest_attempt is None or any(
                stage.attempt_id != self.latest_attempt.attempt_id
                for stage in self.stages
            ):
                raise ValueError("attempt stages are not bound to the latest attempt")
            if tuple(stage.stage_ordinal for stage in self.stages) != tuple(
                range(len(self.stages))
            ):
                raise ValueError("attempt stages must use canonical ordinals")
        return self


class ModelEnsembleWatchFailurePolicy(StrictModel):
    """Bounded exponential backoff and quarantine budget for one watch.

    The policy contains no content and is applied inside the repository's
    writer transaction so that the persisted streak, the persisted next check
    time, and the quarantine flags can never disagree.
    """

    base_delay: timedelta = Field(default=timedelta(seconds=MODEL_ENSEMBLE_WATCH_POLL_SECONDS))
    max_delay: timedelta = Field(
        default=timedelta(seconds=MODEL_ENSEMBLE_WATCH_MAX_BACKOFF_SECONDS)
    )
    max_failure_streak: int = Field(
        default=MODEL_ENSEMBLE_WATCH_MAX_FAILURE_STREAK, ge=1, le=64
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "ModelEnsembleWatchFailurePolicy":
        if not timedelta(seconds=1) <= self.base_delay <= self.max_delay:
            raise ValueError("watch backoff base delay is outside the reviewed bound")
        if self.max_delay > timedelta(hours=24):
            raise ValueError("watch backoff ceiling is outside the reviewed bound")
        return self

    def next_delay(self, failure_streak: int) -> timedelta:
        """Delay before the retry that follows the given consecutive failure."""

        if not isinstance(failure_streak, int) or isinstance(failure_streak, bool):
            raise ValueError("failure streak must be an integer")
        if failure_streak < 1:
            raise ValueError("backoff requires at least one failure")
        exponent = min(failure_streak - 1, 30)
        return min(self.max_delay, self.base_delay * (2**exponent))

    def quarantines(self, failure_streak: int) -> bool:
        return failure_streak >= self.max_failure_streak


class ModelEnsembleWatchRecord(StrictModel):
    watch_id: str
    provider: Provider
    project_id: str
    session_id: str
    max_messages: int = Field(ge=1, le=100)
    state: ModelEnsembleWatchState
    generation: int = Field(ge=0)
    progress_completed: int = Field(ge=0, le=MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL)
    progress_total: int = Field(default=MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL)
    latest_run_id: str | None = None
    latest_input_fingerprint: str | None = None
    last_error_code: str | None = None
    next_check_at: datetime
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    failure_streak: int = Field(default=0, ge=0, le=64)
    quarantined_at: datetime | None = None
    quarantine_reason_code: str | None = None
    created_at: datetime
    updated_at: datetime

    _ids = field_validator("watch_id", "project_id", "session_id")(_safe_id)
    _optional_ids = field_validator(
        "latest_run_id",
        "latest_input_fingerprint",
        "lease_owner",
        "lease_token",
    )(lambda value: None if value is None else _safe_id(value))
    _reason = field_validator("last_error_code", "quarantine_reason_code")(
        lambda value: None if value is None else _safe_code(value)
    )
    _times = field_validator(
        "next_check_at",
        "lease_expires_at",
        "quarantined_at",
        "created_at",
        "updated_at",
    )(lambda value: None if value is None else _utc(value))

    @property
    def quarantined(self) -> bool:
        return self.quarantined_at is not None

    @model_validator(mode="after")
    def validate_state(self) -> "ModelEnsembleWatchRecord":
        leased = self.state is ModelEnsembleWatchState.RUNNING
        lease_complete = all(
            value is not None
            for value in (self.lease_owner, self.lease_token, self.lease_expires_at)
        )
        if leased != lease_complete:
            raise ValueError("only a running watch may hold a complete lease")
        if self.progress_completed > self.progress_total:
            raise ValueError("watch progress cannot exceed its total")
        if self.state is ModelEnsembleWatchState.IDLE and self.last_error_code is not None:
            raise ValueError("an idle watch cannot retain a failure code")
        if (self.quarantined_at is None) != (self.quarantine_reason_code is None):
            raise ValueError("watch quarantine identity must be complete")
        if self.quarantined_at is not None and self.state not in {
            ModelEnsembleWatchState.FAILED,
            ModelEnsembleWatchState.DISABLED,
        }:
            raise ValueError("only a failed or disabled watch may be quarantined")
        if self.state is ModelEnsembleWatchState.IDLE and self.failure_streak != 0:
            raise ValueError("an idle watch cannot retain a failure streak")
        return self


class ModelEnsembleWatchLease(StrictModel):
    watch_id: str
    owner: str
    token: str
    expires_at: datetime

    _ids = field_validator("watch_id", "owner", "token")(_safe_id)
    _time = field_validator("expires_at")(_utc)


class ModelEnsembleTrajectoryPoint(StrictModel):
    generation: int = Field(ge=1, le=1_000_000_000)
    run_id: str
    published_at: datetime
    completed_at: datetime
    max_messages: int = Field(ge=1, le=100)
    source_coverage_state: SourceCoverageState
    chunk_count: int = Field(ge=1, le=8)
    comparable_to_head: bool
    metrics: tuple[SessionModelEnsembleMetricReceipt, ...] = Field(
        min_length=1,
        max_length=20,
    )
    metric_projection_version: Literal[
        MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
    ] | None = None
    metric_projection_completed_at: datetime | None = None
    typed_metrics: tuple[SessionModelEnsembleTypedMetricReceipt, ...] = Field(
        default=(),
        max_length=20,
    )
    metric_states_v2: tuple[MetricStateV2, ...] = Field(
        default=(),
        max_length=20,
    )
    predictive_projection_version: Literal[
        PROBABILISTIC_METRIC_PROJECTION_VERSION
    ] | None = None
    predictive_metrics: tuple[SessionPredictiveMetricSummary, ...] = Field(
        default=(), max_length=20
    )

    _run = field_validator("run_id")(_safe_id)
    _times = field_validator("published_at", "completed_at")(_utc)

    @field_validator("metric_projection_completed_at")
    @classmethod
    def validate_projection_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_point(self) -> "ModelEnsembleTrajectoryPoint":
        if self.published_at < self.completed_at:
            raise ValueError("trajectory publication cannot precede completion")
        if len({item.metric_key for item in self.metrics}) != len(self.metrics):
            raise ValueError("trajectory metrics must be unique")
        if any(item.total_chunk_count > self.chunk_count for item in self.metrics):
            raise ValueError(
                "trajectory metric observations cannot exceed the physical chunk count"
            )
        projection_identity_complete = (
            self.metric_projection_version is not None
            and self.metric_projection_completed_at is not None
        )
        if bool(self.typed_metrics) != projection_identity_complete or (
            (self.metric_projection_version is None)
            != (self.metric_projection_completed_at is None)
        ):
            raise ValueError("trajectory typed projection identity is incomplete")
        if self.typed_metrics:
            typed_keys = tuple(item.metric_key for item in self.typed_metrics)
            committee_keys = tuple(item.metric_key for item in self.metrics)
            if len(set(typed_keys)) != len(typed_keys) or set(typed_keys) != set(
                committee_keys
            ):
                raise ValueError("trajectory typed projection metric set is incomplete")
        if self.metric_states_v2:
            v2_keys = tuple(item.metric_key for item in self.metric_states_v2)
            committee_keys = tuple(item.metric_key for item in self.metrics)
            if (
                len(self.metric_states_v2) != 20
                or len(set(v2_keys)) != len(v2_keys)
                or set(v2_keys) != set(committee_keys)
            ):
                raise ValueError("trajectory V2 metric state set is incomplete")
        if bool(self.predictive_metrics) != (
            self.predictive_projection_version is not None
        ):
            raise ValueError("trajectory predictive projection identity is incomplete")
        if self.predictive_metrics:
            predictive_keys = tuple(item.metric_key for item in self.predictive_metrics)
            committee_keys = tuple(item.metric_key for item in self.metrics)
            if len(set(predictive_keys)) != len(predictive_keys) or set(
                predictive_keys
            ) != set(committee_keys):
                raise ValueError("trajectory predictive metric set is incomplete")
        return self


class ModelEnsembleTrajectoryPage(StrictModel):
    watch_id: str
    head_run_id: str | None
    head_generation: int | None = Field(default=None, ge=1, le=1_000_000_000)
    points: tuple[ModelEnsembleTrajectoryPoint, ...] = Field(max_length=60)
    next_before_generation: int | None = Field(
        default=None,
        ge=1,
        le=1_000_000_000,
    )
    content_persisted: Literal[False] = False
    calibrated_as_truth: Literal[False] = False

    _watch = field_validator("watch_id")(_safe_id)
    _head = field_validator("head_run_id")(
        lambda value: None if value is None else _safe_id(value)
    )

    @model_validator(mode="after")
    def validate_page(self) -> "ModelEnsembleTrajectoryPage":
        if (self.head_run_id is None) != (self.head_generation is None):
            raise ValueError("trajectory head identity must be complete")
        generations = tuple(point.generation for point in self.points)
        if generations != tuple(sorted(generations, reverse=True)):
            raise ValueError("trajectory points must be newest first")
        if len(set(generations)) != len(generations):
            raise ValueError("trajectory generations must be unique")
        if self.head_generation is not None and any(
            generation > self.head_generation for generation in generations
        ):
            raise ValueError("trajectory points cannot be newer than the watch head")
        head_points = tuple(
            point for point in self.points if point.run_id == self.head_run_id
        )
        if head_points and (
            len(head_points) != 1
            or head_points[0].generation != self.head_generation
            or not head_points[0].comparable_to_head
            or self.points[0] != head_points[0]
        ):
            raise ValueError("trajectory head publication is inconsistent")
        if self.next_before_generation is not None and (
            not generations or self.next_before_generation != generations[-1]
        ):
            raise ValueError("trajectory cursor must identify the last returned point")
        return self


class ModelEnsembleWatchRepository(Protocol):
    def enable(
        self,
        *,
        watch_id: str,
        provider: Provider,
        project_id: str,
        session_id: str,
        max_messages: int = 100,
        now: datetime,
    ) -> ModelEnsembleWatchRecord: ...

    def disable(self, watch_id: str, *, now: datetime) -> ModelEnsembleWatchRecord: ...

    def get(self, watch_id: str) -> ModelEnsembleWatchRecord | None: ...

    def get_active(self) -> ModelEnsembleWatchRecord | None: ...

    def get_for_session(self, session_id: str) -> ModelEnsembleWatchRecord | None: ...

    def canonical_head(self, watch_id: str) -> ModelEnsembleCanonicalHead: ...

    def get_attempt(self, attempt_id: str) -> ModelEnsembleAttemptRecord | None: ...

    def get_attempt_stages(
        self, attempt_id: str
    ) -> tuple[ModelEnsembleAttemptStageReceipt, ...]: ...

    def get_attempt_snapshot(
        self, attempt_id: str
    ) -> tuple[
        ModelEnsembleAttemptRecord,
        tuple[ModelEnsembleAttemptStageReceipt, ...],
    ] | None: ...

    def list_attempts(
        self, watch_id: str, *, limit: int
    ) -> tuple[ModelEnsembleAttemptRecord, ...]: ...

    def request_refresh(
        self,
        watch_id: str,
        *,
        now: datetime,
    ) -> ModelEnsembleWatchRecord: ...

    def list_publications(
        self,
        watch_id: str,
        *,
        before_generation: int | None,
        limit: int,
    ) -> ModelEnsembleTrajectoryPage: ...

    def claim_due(
        self,
        *,
        owner: str,
        now: datetime,
        lease_duration: timedelta,
        policy: ModelEnsembleWatchFailurePolicy,
    ) -> tuple[ModelEnsembleWatchRecord, ModelEnsembleWatchLease] | None: ...

    def recover_orphaned_leases(
        self,
        *,
        owner: str,
        now: datetime,
        policy: ModelEnsembleWatchFailurePolicy,
    ) -> int: ...

    def quarantine_provider_watches(
        self,
        provider: Provider,
        *,
        now: datetime,
        reason_code: str,
    ) -> int: ...

    def quarantine_stopped_attempt(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        generation: int,
        now: datetime,
        reason_code: str,
    ) -> ModelEnsembleWatchRecord: ...

    def heartbeat(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        lease_duration: timedelta,
        progress_completed: int,
    ) -> tuple[ModelEnsembleWatchRecord, ModelEnsembleWatchLease]: ...

    def complete(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        next_check_at: datetime,
        outcome: SessionModelEnsembleOutcome,
    ) -> ModelEnsembleWatchRecord: ...

    def fail(
        self,
        lease: ModelEnsembleWatchLease,
        *,
        now: datetime,
        reason_code: str,
        failure_class: ModelEnsembleWatchFailureClass,
        policy: ModelEnsembleWatchFailurePolicy,
    ) -> ModelEnsembleWatchRecord: ...

    def cancel_attempt(
        self,
        watch_id: str,
        *,
        now: datetime,
        next_check_at: datetime,
        lease: ModelEnsembleWatchLease | None = None,
        reason_code: str = "analysis_cancelled",
    ) -> ModelEnsembleWatchRecord: ...


ProgressCallback = Callable[[int, int], None]


class ContinuousModelEnsembleCommand(Protocol):
    def require_watchable(self, *, provider: Provider, session_id: str) -> None: ...

    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        idempotency_key: str,
        max_messages: int = 100,
        progress_callback: ProgressCallback | None = None,
        reuse_latest: bool = True,
        prior_run_id: str | None = None,
    ) -> SessionModelEnsembleOutcome: ...


class ModelEnsembleWatchError(RuntimeError):
    code = "model_ensemble_watch_failed"


class ModelEnsembleWatchInputError(ModelEnsembleWatchError):
    code = "invalid_model_ensemble_watch_request"


class ModelEnsembleWatchNotFoundError(ModelEnsembleWatchError):
    code = "model_ensemble_watch_not_found"


class ModelEnsembleWatchConflictError(ModelEnsembleWatchError):
    code = "model_ensemble_watch_conflict"


class ModelEnsembleWatchStopped(RuntimeCooperativeStop):
    """Private cooperative signal used between serial expert stages."""


class ModelEnsembleWatchService:
    """Enable, inspect, and execute one durable continuous local watch."""

    def __init__(
        self,
        repository: ModelEnsembleWatchRepository,
        ensemble: ContinuousModelEnsembleCommand,
        *,
        clock: Callable[[], datetime] = _utc_now,
        poll_interval: timedelta = timedelta(seconds=MODEL_ENSEMBLE_WATCH_POLL_SECONDS),
        lease_duration: timedelta = timedelta(seconds=MODEL_ENSEMBLE_WATCH_LEASE_SECONDS),
        id_factory: Callable[[str], str] | None = None,
        failure_policy: ModelEnsembleWatchFailurePolicy | None = None,
    ) -> None:
        if not timedelta(seconds=5) <= poll_interval <= timedelta(minutes=15):
            raise ValueError("watch poll interval is outside the reviewed bound")
        if lease_duration < timedelta(minutes=5):
            raise ValueError("watch lease is too short for serial local inference")
        self._repository = repository
        self._ensemble = ensemble
        self._clock = clock
        self._poll_interval = poll_interval
        self._lease_duration = lease_duration
        self._failure_policy = failure_policy or ModelEnsembleWatchFailurePolicy(
            base_delay=poll_interval
        )
        self._id_factory = id_factory or (
            lambda value: hashlib.sha256(value.encode("ascii")).hexdigest()
        )
        self._owner = self._id_factory(
            f"{MODEL_ENSEMBLE_WATCH_CONTRACT_VERSION}:worker:{id(self)}"
        )
        self._cleanup_unconfirmed = Event()

    @property
    def cleanup_unconfirmed(self) -> bool:
        """Thread exit cannot prove that an uncertain model child was reaped."""

        return self._cleanup_unconfirmed.is_set()

    def enable(
        self,
        *,
        provider: Provider,
        project_id: str,
        session_id: str,
        max_messages: int = 100,
        confirmation: str,
    ) -> ModelEnsembleWatchRecord:
        if (
            provider not in TEXT_ANALYSIS_PROVIDERS
            or PSEUDONYM_PATTERN.fullmatch(project_id) is None
            or PSEUDONYM_PATTERN.fullmatch(session_id) is None
            or not isinstance(max_messages, int)
            or isinstance(max_messages, bool)
            or not 1 <= max_messages <= 100
            or confirmation != MODEL_ENSEMBLE_WATCH_CONFIRMATION
        ):
            raise ModelEnsembleWatchInputError()
        self._ensemble.require_watchable(provider=provider, session_id=session_id)
        watch_id = self._id_factory(
            ":".join(
                (
                    MODEL_ENSEMBLE_WATCH_CONTRACT_VERSION,
                    provider.value,
                    project_id,
                    session_id,
                )
            )
        )
        try:
            return self._repository.enable(
                watch_id=watch_id,
                provider=provider,
                project_id=project_id,
                session_id=session_id,
                max_messages=max_messages,
                now=self._clock(),
            )
        except ValueError:
            raise ModelEnsembleWatchConflictError() from None

    def disable(self, watch_id: str) -> ModelEnsembleWatchRecord:
        if PSEUDONYM_PATTERN.fullmatch(watch_id) is None:
            raise ModelEnsembleWatchInputError()
        try:
            return self._repository.disable(watch_id, now=self._clock())
        except ValueError:
            raise ModelEnsembleWatchNotFoundError() from None

    def get_active(self) -> ModelEnsembleWatchRecord | None:
        return self._repository.get_active()

    def canonical_head(self, watch_id: str | None = None) -> ModelEnsembleCanonicalHead:
        if watch_id is None:
            record = self._repository.get_active()
            if record is None:
                raise ModelEnsembleWatchNotFoundError()
            watch_id = record.watch_id
        elif PSEUDONYM_PATTERN.fullmatch(watch_id) is None:
            raise ModelEnsembleWatchInputError()
        try:
            return self._repository.canonical_head(watch_id)
        except ValueError:
            raise ModelEnsembleWatchNotFoundError() from None

    def canonical_head_for_session(
        self, session_id: str
    ) -> ModelEnsembleCanonicalHead:
        if PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise ModelEnsembleWatchInputError()
        record = self._repository.get_for_session(session_id)
        if record is None:
            raise ModelEnsembleWatchNotFoundError()
        try:
            return self._repository.canonical_head(record.watch_id)
        except ValueError:
            raise ModelEnsembleWatchNotFoundError() from None

    def attempt(self, attempt_id: str) -> ModelEnsembleAttemptRecord:
        if PSEUDONYM_PATTERN.fullmatch(attempt_id) is None:
            raise ModelEnsembleWatchInputError()
        attempt = self._repository.get_attempt(attempt_id)
        if attempt is None:
            raise ModelEnsembleWatchNotFoundError()
        return attempt

    def attempt_stages(
        self, attempt_id: str
    ) -> tuple[ModelEnsembleAttemptStageReceipt, ...]:
        self.attempt(attempt_id)
        return self._repository.get_attempt_stages(attempt_id)

    def attempt_snapshot(
        self, attempt_id: str
    ) -> tuple[
        ModelEnsembleAttemptRecord,
        tuple[ModelEnsembleAttemptStageReceipt, ...],
    ]:
        """Read one sealed attempt graph from a single repository snapshot."""

        if PSEUDONYM_PATTERN.fullmatch(attempt_id) is None:
            raise ModelEnsembleWatchInputError()
        snapshot = self._repository.get_attempt_snapshot(attempt_id)
        if snapshot is None:
            raise ModelEnsembleWatchNotFoundError()
        return snapshot

    def attempts(
        self, watch_id: str, *, limit: int = 12
    ) -> tuple[ModelEnsembleAttemptRecord, ...]:
        if (
            PSEUDONYM_PATTERN.fullmatch(watch_id) is None
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 60
        ):
            raise ModelEnsembleWatchInputError()
        if self._repository.get(watch_id) is None:
            raise ModelEnsembleWatchNotFoundError()
        return self._repository.list_attempts(watch_id, limit=limit)

    def cancel(self, watch_id: str) -> ModelEnsembleCanonicalHead:
        """Revoke the active lease while retaining the last valid publication."""

        if PSEUDONYM_PATTERN.fullmatch(watch_id) is None:
            raise ModelEnsembleWatchInputError()
        now = self._clock()
        try:
            self._repository.cancel_attempt(
                watch_id,
                now=now,
                next_check_at=now + self._poll_interval,
            )
            return self._repository.canonical_head(watch_id)
        except ValueError:
            raise ModelEnsembleWatchConflictError() from None

    def refresh(self, watch_id: str) -> ModelEnsembleWatchRecord:
        """Make a non-disabled watch immediately due without replacing its head."""

        if PSEUDONYM_PATTERN.fullmatch(watch_id) is None:
            raise ModelEnsembleWatchInputError()
        try:
            return self._repository.request_refresh(watch_id, now=self._clock())
        except ValueError:
            raise ModelEnsembleWatchNotFoundError() from None

    def trajectory(
        self,
        watch_id: str,
        *,
        before_generation: int | None = None,
        limit: int = 12,
    ) -> ModelEnsembleTrajectoryPage:
        if (
            PSEUDONYM_PATTERN.fullmatch(watch_id) is None
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 60
            or (
                before_generation is not None
                and (
                    not isinstance(before_generation, int)
                    or isinstance(before_generation, bool)
                    or not 1 <= before_generation <= 1_000_000_000
                )
            )
        ):
            raise ModelEnsembleWatchInputError()
        if self._repository.get(watch_id) is None:
            raise ModelEnsembleWatchNotFoundError()
        return self._repository.list_publications(
            watch_id,
            before_generation=before_generation,
            limit=limit,
        )

    @property
    def failure_policy(self) -> ModelEnsembleWatchFailurePolicy:
        return self._failure_policy

    def recover_orphaned_leases(self) -> int:
        """Recover expired leases without stealing work from another process.

        Each expired lease counts as one failure toward the durable
        backoff/quarantine budget so that a crash loop cannot restart local
        inference without bound.  Unexpired leases remain authoritative even
        when their owner differs from this process.
        """

        return self._repository.recover_orphaned_leases(
            owner=self._owner,
            now=self._clock(),
            policy=self._failure_policy,
        )

    def quarantine_for_provider(
        self,
        provider: Provider,
        *,
        reason_code: str = MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
    ) -> int:
        """Stop future analysis for a provider without deleting any result.

        Used when local-history consent is revoked.  The last sealed head is
        retained; erasing derived data stays a separate explicit user action.
        """

        if not isinstance(provider, Provider):
            raise ModelEnsembleWatchInputError()
        try:
            _safe_code(reason_code)
        except ValueError:
            raise ModelEnsembleWatchInputError() from None
        return self._repository.quarantine_provider_watches(
            provider,
            now=self._clock(),
            reason_code=reason_code,
        )

    def run_once(self, *, stop_requested: Callable[[], bool] = lambda: False) -> ModelEnsembleWatchRecord | None:
        if stop_requested():
            return None
        now = self._clock()
        claimed = self._repository.claim_due(
            owner=self._owner,
            now=now,
            lease_duration=self._lease_duration,
            policy=self._failure_policy,
        )
        if claimed is None:
            return None
        record, lease = claimed

        def guard_shutdown() -> None:
            if stop_requested():
                stopped_at = self._clock()
                try:
                    self._repository.cancel_attempt(
                        record.watch_id, now=stopped_at,
                        next_check_at=stopped_at + self._poll_interval,
                        lease=lease, reason_code="application_shutdown",
                    )
                except ValueError:
                    # A replaced/expired lease is not ours to cancel. Its
                    # publication or new attempt remains authoritative.
                    pass
                raise ModelEnsembleWatchStopped()

        def progress(completed: int, total: int) -> None:
            nonlocal record, lease
            guard_shutdown()
            if total != MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL:
                raise ValueError("watch progress total changed")
            operation_at = self._clock()
            record, lease = self._repository.heartbeat(
                lease,
                now=operation_at,
                lease_duration=self._lease_duration,
                progress_completed=completed,
            )
            if record.state is not ModelEnsembleWatchState.RUNNING:
                raise ModelEnsembleWatchStopped()

        def persistence_authority() -> SessionModelEnsemblePersistenceAuthority:
            guard_shutdown()
            return SessionModelEnsemblePersistenceAuthority(
                watch_id=record.watch_id,
                owner=lease.owner,
                token=lease.token,
                generation=record.generation,
                observed_at=self._clock(),
                prior_run_id=record.latest_run_id,
            )

        key = self._id_factory(
            f"{MODEL_ENSEMBLE_WATCH_CONTRACT_VERSION}:{record.watch_id}:{record.generation}"
        )
        try:
            guard_shutdown()
            if self.cleanup_unconfirmed:
                raise ModelEnsembleRuntimeCleanupError()
            outcome = self._ensemble.run(
                provider=record.provider,
                session_id=record.session_id,
                confirmation=MODEL_ENSEMBLE_CONFIRMATION,
                idempotency_key=key,
                max_messages=record.max_messages,
                progress_callback=progress,
                reuse_latest=True,
                prior_run_id=record.latest_run_id,
                persistence_authority=persistence_authority,
            )
            finished_at = self._clock()
            return self._repository.complete(
                lease,
                now=finished_at,
                next_check_at=finished_at + self._poll_interval,
                outcome=outcome,
            )
        except ModelEnsembleWatchStopped:
            current = self._repository.get(record.watch_id)
            return current
        except SessionModelEnsembleError as error:
            reason = error.code
            if reason == ModelEnsembleRuntimeCleanupError.code:
                self._cleanup_unconfirmed.set()
        except Exception:
            reason = "model_ensemble_watch_execution_failed"
        failed_at = self._clock()
        try:
            return self._repository.fail(
                lease,
                now=failed_at,
                reason_code=reason,
                failure_class=classify_watch_failure(reason),
                policy=self._failure_policy,
            )
        except ValueError:
            if reason == ModelEnsembleRuntimeCleanupError.code:
                try:
                    # Cancellation may already have sealed the attempt and
                    # released its lease. Retain the resource warning without
                    # rewriting that receipt or touching a replacement owner.
                    return self._repository.quarantine_stopped_attempt(
                        lease,
                        generation=record.generation,
                        now=failed_at,
                        reason_code=reason,
                    )
                except ValueError:
                    pass
            return self._repository.get(record.watch_id)


class ModelEnsembleWatchWorker:
    """One coalescing watch worker and therefore one global model/GPU lane."""

    def __init__(
        self,
        service: ModelEnsembleWatchService,
        *,
        wake_seconds: float = 5.0,
    ) -> None:
        if not 1 <= wake_seconds <= 60:
            raise ValueError("watch worker cadence is outside the reviewed bound")
        self._service = service
        self._wake_seconds = wake_seconds
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._service.cleanup_unconfirmed:
                raise RuntimeError(_WORKER_START_FAILURE)
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise RuntimeError(_WORKER_STOP_IN_PROGRESS)
                return
            self._thread = None
            start_failed = False
            try:
                self._stop.clear()
                thread = Thread(
                    target=self._run,
                    name="model-ensemble-watch-worker",
                    daemon=True,
                )
                thread.start()
            except Exception:
                self._stop.set()
                start_failed = True
            if start_failed:
                raise RuntimeError(_WORKER_START_FAILURE)
            self._thread = thread

    def is_alive(self) -> bool:
        """Return thread liveness without exposing watch details."""

        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def recover(self) -> int:
        """Run the durable startup recovery sweep once, swallowing detail text."""

        try:
            return self._service.recover_orphaned_leases()
        except Exception:
            # Exception text may carry private adapter details; the periodic
            # claim path recovers expired leases later regardless.
            return 0

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                if self._service.cleanup_unconfirmed:
                    raise RuntimeError(_WORKER_STOP_FAILURE)
                return
            self._stop.set()
            stop_failed = False
            timed_out = False
            try:
                thread.join(timeout=timeout)
                timed_out = thread.is_alive()
            except Exception:
                stop_failed = True
            if stop_failed:
                raise RuntimeError(_WORKER_STOP_FAILURE)
            if timed_out:
                raise RuntimeError(_WORKER_STOP_TIMEOUT)
            if self._thread is thread:
                self._thread = None
            if self._service.cleanup_unconfirmed:
                raise RuntimeError(_WORKER_STOP_FAILURE)

    def run_once(self) -> ModelEnsembleWatchRecord | None:
        return self._service.run_once(stop_requested=self._stop.is_set)

    def _run(self) -> None:
        self.recover()
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                # Exception text may carry private adapter details; retry later.
                pass
            self._stop.wait(self._wake_seconds)


__all__ = [
    "MODEL_ENSEMBLE_ATTEMPT_CONTRACT_VERSION",
    "MODEL_ENSEMBLE_WATCH_CONFIRMATION",
    "MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED",
    "MODEL_ENSEMBLE_WATCH_CONTRACT_VERSION",
    "MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED",
    "MODEL_ENSEMBLE_WATCH_MAX_BACKOFF_SECONDS",
    "MODEL_ENSEMBLE_WATCH_MAX_FAILURE_STREAK",
    "MODEL_ENSEMBLE_WATCH_NONRETRYABLE_REASONS",
    "MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL",
    "MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED",
    "ContinuousModelEnsembleCommand",
    "ModelEnsembleWatchFailureClass",
    "ModelEnsembleWatchFailurePolicy",
    "classify_watch_failure",
    "ModelEnsembleAttemptRecord",
    "ModelEnsembleAttemptStageReceipt",
    "ModelEnsembleAttemptState",
    "ModelEnsembleCanonicalHead",
    "ModelEnsembleStageState",
    "ModelEnsembleWatchConflictError",
    "ModelEnsembleWatchError",
    "ModelEnsembleWatchInputError",
    "ModelEnsembleWatchLease",
    "ModelEnsembleWatchNotFoundError",
    "ModelEnsembleWatchRecord",
    "ModelEnsembleWatchRepository",
    "ModelEnsembleWatchService",
    "ModelEnsembleWatchState",
    "ModelEnsembleWatchWorker",
    "ModelEnsembleTrajectoryPage",
    "ModelEnsembleTrajectoryPoint",
]
