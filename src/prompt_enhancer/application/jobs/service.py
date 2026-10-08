"""Use cases and local worker seam for durable analysis jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import hashlib
import json
import math
import secrets
from threading import Event, Lock, Thread
from time import monotonic
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ...database import DatabaseInvariantError
from ...domain import SAFE_VERSION_PATTERN, Provider, StrictModel
from .contracts import (
    ANALYSIS_JOB_CONTRACT_VERSION,
    TERMINAL_ANALYSIS_JOB_STATES,
    AnalysisJobCancellationBatchResult,
    AnalysisJobDraft,
    AnalysisJobEnqueueResult,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobPage,
    AnalysisPublicationDeadlineFailure,
    AnalysisJobRecord,
    AnalysisJobRepository,
    AnalysisJobState,
    PowerSourceReader,
    PowerSourceState,
)


DEFAULT_ANALYSIS_JOB_LEASE = timedelta(seconds=30)
DEFAULT_ANALYSIS_JOB_POLL_SECONDS = 1.0
_WORKER_START_FAILURE = "worker_start_failed"
_WORKER_STOP_IN_PROGRESS = "worker_stop_in_progress"
_WORKER_STOP_FAILURE = "worker_stop_failed"
_WORKER_STOP_TIMEOUT = "worker_stop_timeout"


class AnalysisJobServiceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AnalysisJobNotFoundError(AnalysisJobServiceError):
    def __init__(self) -> None:
        super().__init__("analysis_job_not_found")


class AnalysisJobConflictError(AnalysisJobServiceError):
    def __init__(self) -> None:
        super().__init__("analysis_job_conflict")


class AnalysisJobExecutionError(RuntimeError):
    """Handler error that exposes only a reviewed content-free code."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        if SAFE_VERSION_PATTERN.fullmatch(code) is None:
            raise ValueError("execution error code must be content-free")
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class AnalysisJobCooperativeStop(RuntimeError):
    """A queue transition already persisted at a cooperative boundary."""

    def __init__(self, reason_code: str) -> None:
        if SAFE_VERSION_PATTERN.fullmatch(reason_code) is None:
            raise ValueError("cooperative stop code must be content-free")
        self.reason_code = reason_code
        super().__init__(reason_code)


class AnalysisJobExecutionResult(StrictModel):
    state: AnalysisJobState
    reason_code: str
    progress_completed: int = Field(ge=0, le=1_000_000)
    progress_total: int = Field(ge=1, le=1_000_000)

    @field_validator("reason_code")
    @classmethod
    def safe_reason_code(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("execution result reason must be content-free")
        return value

    @model_validator(mode="after")
    def closed_result_state(self) -> AnalysisJobExecutionResult:
        if self.state not in {
            AnalysisJobState.AWAITING_APPROVAL,
            AnalysisJobState.COMPLETED,
            AnalysisJobState.PARTIAL,
            AnalysisJobState.FAILED,
            AnalysisJobState.CANCELLED,
            AnalysisJobState.SUPERSEDED,
        }:
            raise ValueError("handler returned an unsupported queue state")
        if self.progress_completed > self.progress_total:
            raise ValueError("execution progress cannot exceed its total")
        if (
            self.state is AnalysisJobState.COMPLETED
            and self.progress_completed != self.progress_total
        ):
            raise ValueError("completed execution must report complete progress")
        return self


class AnalysisJobHandler(Protocol):
    def __call__(
        self,
        job: AnalysisJobRecord,
        context: AnalysisJobExecutionContext,
    ) -> AnalysisJobExecutionResult: ...


Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]
AuthorizationCheck = Callable[[AnalysisJobRecord], bool]
FingerprintResolver = Callable[[AnalysisJobRecord], tuple[str, str] | None]
ExecutionStopCallback = Callable[[AnalysisJobRecord, AnalysisJobState, str], None]
ExecutionRecoveryCallback = Callable[[datetime], None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _identity_digest(identity: AnalysisJobIdentity, max_attempts: int) -> str:
    canonical = json.dumps(
        {
            "contract_version": ANALYSIS_JOB_CONTRACT_VERSION,
            "identity": identity.model_dump(mode="json"),
            "max_attempts": max_attempts,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _job_id(dedupe_key: str) -> str:
    return hashlib.sha256(
        f"{ANALYSIS_JOB_CONTRACT_VERSION}:{dedupe_key}".encode("ascii")
    ).hexdigest()


class AnalysisJobService:
    """Content-free enqueue/query/cancel boundary used by HTTP and automation."""

    def __init__(
        self,
        repository: AnalysisJobRepository,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def enqueue(
        self,
        identity: AnalysisJobIdentity,
        *,
        max_attempts: int = 3,
    ) -> AnalysisJobEnqueueResult:
        if identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise AnalysisJobConflictError()
        if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
            raise ValueError("max attempts must be between one and five")
        dedupe_key = _identity_digest(identity, max_attempts)
        job_id = _job_id(dedupe_key)
        existing = self._repository.get(job_id)
        if existing is not None:
            if (
                existing.dedupe_key != dedupe_key
                or existing.identity != identity
                or existing.max_attempts != max_attempts
            ):
                raise AnalysisJobConflictError()
            return AnalysisJobEnqueueResult(job=existing, created=False)
        try:
            return self._repository.enqueue(
                AnalysisJobDraft(
                    job_id=job_id,
                    dedupe_key=dedupe_key,
                    identity=identity,
                    max_attempts=max_attempts,
                    created_at=self._clock(),
                )
            )
        except DatabaseInvariantError:
            # A concurrent identical enqueue may have won after the first read.
            concurrent = self._repository.get(job_id)
            if (
                concurrent is not None
                and concurrent.dedupe_key == dedupe_key
                and concurrent.identity == identity
                and concurrent.max_attempts == max_attempts
            ):
                return AnalysisJobEnqueueResult(job=concurrent, created=False)
            raise AnalysisJobConflictError() from None

    def get(self, job_id: str) -> AnalysisJobRecord:
        try:
            job = self._repository.get(job_id)
        except ValueError:
            raise AnalysisJobNotFoundError() from None
        if job is None:
            raise AnalysisJobNotFoundError()
        return job

    def list(
        self,
        *,
        state: AnalysisJobState | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AnalysisJobPage:
        return self._repository.list(state=state, limit=limit, offset=offset)

    def list_active(self, *, limit: int = 100) -> AnalysisJobPage:
        return self._repository.list_active(limit=limit)

    def latest_for_session(self, session_id: str) -> AnalysisJobRecord | None:
        try:
            return self._repository.get_latest_for_session(session_id)
        except ValueError:
            raise AnalysisJobNotFoundError() from None

    def cancel(self, job_id: str) -> AnalysisJobRecord:
        job = self.get(job_id)
        if job.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise AnalysisJobConflictError()
        try:
            return self._repository.request_cancel(job_id, now=self._clock())
        except DatabaseInvariantError:
            raise AnalysisJobConflictError() from None

    def resume_after_approval(self, job_id: str) -> AnalysisJobRecord:
        job = self.get(job_id)
        if job.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise AnalysisJobConflictError()
        try:
            return self._repository.resume_after_approval(
                job_id,
                now=self._clock(),
            )
        except DatabaseInvariantError:
            raise AnalysisJobConflictError() from None

    def revoke_automation_grant(
        self,
        automation_grant_id: str,
    ) -> AnalysisJobCancellationBatchResult:
        try:
            return self._repository.cancel_by_automation_grant(
                automation_grant_id,
                now=self._clock(),
            )
        except ValueError:
            raise AnalysisJobNotFoundError() from None
        except DatabaseInvariantError:
            raise AnalysisJobConflictError() from None

    def supersede_if_changed(
        self,
        job_id: str,
        *,
        input_fingerprint: str,
        provenance_fingerprint: str,
    ) -> AnalysisJobRecord:
        job = self.get(job_id)
        if job.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise AnalysisJobConflictError()
        if job.state in TERMINAL_ANALYSIS_JOB_STATES:
            return job
        reason: str | None = None
        if input_fingerprint != job.identity.input_fingerprint:
            reason = "input_changed"
        elif provenance_fingerprint != job.identity.provenance_fingerprint:
            reason = "provenance_changed"
        if reason is None:
            return job
        try:
            return self._repository.supersede(
                job_id,
                now=self._clock(),
                reason_code=reason,
            )
        except DatabaseInvariantError:
            raise AnalysisJobConflictError() from None


class AnalysisJobExecutionContext:
    """Lease-bound handler controls; values are all content-free."""

    def __init__(
        self,
        repository: AnalysisJobRepository,
        job: AnalysisJobRecord,
        lease: AnalysisJobLease,
        *,
        clock: Clock,
        monotonic_clock: MonotonicClock,
        lease_duration: timedelta,
        authorization_check: AuthorizationCheck,
        fingerprint_resolver: FingerprintResolver,
        execution_stop_callback: ExecutionStopCallback,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self._repository = repository
        self._job = job
        self._lease = lease
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._lease_duration = lease_duration
        self._authorization_check = authorization_check
        self._fingerprint_resolver = fingerprint_resolver
        self._execution_stop_callback = execution_stop_callback
        self._stop_requested = stop_requested
        self._lock = Lock()
        self._publication_committed = False
        self._publication_monotonic_cutoff: float | None = None
        self._last_monotonic: float | None = None
        self._last_validated_wall_at: datetime | None = None
        self._initialize_publication_clock()

    @property
    def job(self) -> AnalysisJobRecord:
        return self._job

    @property
    def lease(self) -> AnalysisJobLease:
        return self._lease

    @property
    def publication_committed(self) -> bool:
        return self._publication_committed

    def _read_monotonic(self) -> float:
        observed = self._monotonic_clock()
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not math.isfinite(observed)
        ):
            raise ValueError("monotonic clock returned an invalid value")
        return float(observed)

    def _clock_failure_timestamp(self) -> datetime:
        return (
            self._job.publication_high_water_at
            or self._job.runtime_started_at
            or self._job.updated_at
        )

    def _read_wall_clock(self) -> datetime:
        try:
            observed = self._clock()
        except Exception:
            self._fail_publication_deadline(
                AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED,
                now=self._clock_failure_timestamp(),
            )
            raise AssertionError("cooperative clock closure must stop execution")
        if (
            not isinstance(observed, datetime)
            or observed.tzinfo is None
            or observed.utcoffset() != timedelta(0)
        ):
            self._fail_publication_deadline(
                AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED,
                now=self._clock_failure_timestamp(),
            )
            raise AssertionError("cooperative clock closure must stop execution")
        self._last_validated_wall_at = observed
        return observed

    def _repository_timestamp_locked(self) -> datetime:
        if self._job.publication_deadline_at is None:
            return self._clock()
        if self._last_validated_wall_at is None:
            return self._read_wall_clock()
        return self._last_validated_wall_at

    def _initialize_publication_clock(self) -> None:
        deadline_job = (
            self._job.identity.kind is AnalysisJobKind.SESSION_QUALITY
            and self._job.identity.automation_grant_id is not None
        )
        if self._job.publication_deadline_at is None:
            if deadline_job and self._job.attempt_count > 0:
                self._fail_publication_deadline(
                    AnalysisPublicationDeadlineFailure.DEADLINE_MISSING,
                    now=self._read_wall_clock(),
                )
            return
        wall_now = self._read_wall_clock()
        try:
            observed = self._read_monotonic()
        except Exception:
            self._fail_publication_deadline(
                AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED,
                now=wall_now,
            )
            raise AssertionError("cooperative clock closure must stop execution")
        anchor = max(
            wall_now,
            self._job.publication_high_water_at or wall_now,
        )
        remaining = (
            self._job.publication_deadline_at - anchor
        ).total_seconds()
        self._last_monotonic = observed
        self._publication_monotonic_cutoff = observed + max(remaining, 0.0)

    def _fail_publication_deadline(
        self,
        failure: AnalysisPublicationDeadlineFailure,
        *,
        now: datetime,
    ) -> None:
        closed = self._repository.fail_publication_deadline(
            self._lease,
            now=now,
            failure=failure,
        )
        self._raise_cooperative_stop(closed)

    def _raise_cooperative_stop(self, job: AnalysisJobRecord) -> None:
        self._job = job
        if job.state is AnalysisJobState.COMPLETED:
            self._publication_committed = True
        reason = (
            job.terminal_reason_code
            or job.last_error_code
            or "cooperative_execution_stopped"
        )
        raise AnalysisJobCooperativeStop(reason)

    def _check_publication_deadline_locked(self) -> AnalysisJobRecord:
        if self._publication_committed:
            return self._job
        if self._job.publication_deadline_at is None:
            return self._job
        wall_now = self._read_wall_clock()
        try:
            observed = self._read_monotonic()
        except Exception:
            self._fail_publication_deadline(
                AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED,
                now=wall_now,
            )
            raise AssertionError("cooperative clock closure must stop execution")
        last_monotonic = self._last_monotonic
        cutoff = self._publication_monotonic_cutoff
        failure: AnalysisPublicationDeadlineFailure | None = None
        if last_monotonic is not None and observed < last_monotonic:
            failure = AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
        elif cutoff is not None and observed >= cutoff:
            failure = AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED
        if failure is None:
            checked = self._repository.check_publication_deadline(
                self._lease,
                now=wall_now,
            )
        else:
            self._fail_publication_deadline(failure, now=wall_now)
            raise AssertionError("cooperative deadline closure must stop execution")
        self._last_monotonic = observed
        self._job = checked
        if checked.state in TERMINAL_ANALYSIS_JOB_STATES:
            self._raise_cooperative_stop(checked)
        return checked

    def publication_checkpoint(self) -> AnalysisJobRecord:
        """Deny late publication without attempting to preempt blocking work."""

        with self._lock:
            persisted = self._repository.get(self._job.job_id)
            if persisted is None:
                raise AnalysisJobCooperativeStop("analysis_job_missing")
            self._job = persisted
            if persisted.state in TERMINAL_ANALYSIS_JOB_STATES:
                self._raise_cooperative_stop(persisted)
            if not self._publication_committed and self._stop_requested():
                raise AnalysisJobExecutionError("application_shutdown", retryable=True)
            return self._check_publication_deadline_locked()

    def mark_publication_committed(self) -> None:
        """Record that the repository atomically accepted the exact result set."""

        with self._lock:
            self._publication_committed = True

    def repository_timestamp(self) -> datetime:
        """Return one checked timestamp for the next queue write.

        Once publication commits, the last pre-publication observation is kept
        so queue convergence cannot be undone by a later clock failure.
        """

        with self._lock:
            if (
                not self._publication_committed
                and self._job.publication_deadline_at is not None
            ):
                self._check_publication_deadline_locked()
            return self._repository_timestamp_locked()

    def _stop(
        self,
        state: AnalysisJobState,
        reason_code: str,
    ) -> None:
        operation_at = (
            self._read_wall_clock()
            if self._job.publication_deadline_at is not None
            else self._clock()
        )
        # Persist the execution ledger first.  If that append fails, the queue
        # remains leased and can be reconciled without a false terminal state.
        self._execution_stop_callback(self._job, state, reason_code)
        self._job = self._repository.finish(
            self._lease,
            now=operation_at,
            state=state,
            reason_code=reason_code,
            progress_completed=self._job.progress_completed,
            progress_total=self._job.progress_total,
        )
        raise AnalysisJobCooperativeStop(reason_code)

    def _guard_and_renew_locked(self) -> AnalysisJobRecord:
        persisted = self._repository.get(self._job.job_id)
        if persisted is None:
            raise AnalysisJobCooperativeStop("analysis_job_missing")
        self._job = persisted
        if self._publication_committed:
            return persisted
        if self._stop_requested():
            # Preserve the reviewed retry/attempt budget. A stopped attempt is
            # not published as a successful or failed model measurement.
            raise AnalysisJobExecutionError("application_shutdown", retryable=True)
        if persisted.cancel_requested:
            reason = persisted.last_error_code or "cancellation_requested"
            terminal = (
                AnalysisJobState.SUPERSEDED
                if reason in {"input_changed", "provenance_changed"}
                else AnalysisJobState.CANCELLED
            )
            self._stop(terminal, reason)
        if not self._authorization_check(persisted):
            self._stop(AnalysisJobState.CANCELLED, "authorization_revoked")
        current = self._fingerprint_resolver(persisted)
        if current is None:
            self._stop(AnalysisJobState.FAILED, "identity_check_unavailable")
        current_input, current_provenance = current
        if current_input != persisted.identity.input_fingerprint:
            self._stop(AnalysisJobState.SUPERSEDED, "input_changed")
        if current_provenance != persisted.identity.provenance_fingerprint:
            self._stop(AnalysisJobState.SUPERSEDED, "provenance_changed")
        self._check_publication_deadline_locked()
        operation_at = self._repository_timestamp_locked()
        renewed = self._repository.renew(
            self._lease,
            now=operation_at,
            lease_duration=self._lease_duration,
        )
        self._job = renewed
        if renewed.lease_expires_at is None:
            raise AnalysisJobCooperativeStop("analysis_job_lease_lost")
        self._lease = AnalysisJobLease(
            job_id=renewed.job_id,
            owner=renewed.lease_owner,
            token=renewed.lease_token,
            expires_at=renewed.lease_expires_at,
        )
        return renewed

    def heartbeat(self) -> AnalysisJobRecord:
        with self._lock:
            if self._publication_committed:
                return self._job
            return self._guard_and_renew_locked()

    def enter_stage(
        self,
        stage_number: int,
        *,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord:
        with self._lock:
            if self._publication_committed:
                return self._job
            self._guard_and_renew_locked()
            self._job = self._repository.advance_stage(
                self._lease,
                now=self._repository_timestamp_locked(),
                stage_number=stage_number,
                progress_completed=progress_completed,
                progress_total=progress_total,
            )
            return self._job


class AnalysisJobWorker:
    """One bounded local worker; handlers must be explicitly reviewed/injected."""

    def __init__(
        self,
        repository: AnalysisJobRepository,
        handlers: Mapping[tuple[AnalysisJobKind, Provider], AnalysisJobHandler],
        *,
        authorization_check: AuthorizationCheck = lambda _job: False,
        fingerprint_resolver: FingerprintResolver = lambda _job: None,
        execution_stop_callback: ExecutionStopCallback = (
            lambda _job, _state, _reason: None
        ),
        execution_recovery_callback: ExecutionRecoveryCallback = lambda _now: None,
        power_source: PowerSourceReader | None = None,
        clock: Clock = _utc_now,
        monotonic_clock: MonotonicClock = monotonic,
        lease_duration: timedelta = DEFAULT_ANALYSIS_JOB_LEASE,
        poll_seconds: float = DEFAULT_ANALYSIS_JOB_POLL_SECONDS,
        worker_id: str | None = None,
    ) -> None:
        if not 0.05 <= poll_seconds <= 60:
            raise ValueError("worker poll interval is outside the reviewed bound")
        self._repository = repository
        self._handlers = dict(handlers)
        self._authorization_check = authorization_check
        self._fingerprint_resolver = fingerprint_resolver
        self._execution_stop_callback = execution_stop_callback
        self._execution_recovery_callback = execution_recovery_callback
        self._power_source = power_source
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._lease_duration = lease_duration
        self._poll_seconds = poll_seconds
        self._worker_id = worker_id or secrets.token_hex(32)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise RuntimeError(_WORKER_STOP_IN_PROGRESS)
                return
            self._thread = None
            start_failed = False
            try:
                now = self._clock()
                self._execution_recovery_callback(now)
                self._repository.recover_expired(now=now)
                self._stop_event.clear()
                thread = Thread(
                    target=self._run,
                    name="analysis-job-worker",
                    daemon=True,
                )
                thread.start()
            except Exception:
                self._stop_event.set()
                start_failed = True
            if start_failed:
                raise RuntimeError(_WORKER_START_FAILURE)
            self._thread = thread

    def is_alive(self) -> bool:
        """Return thread liveness without exposing work or failure details."""

        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_event.set()
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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                # Repository and recovery failures may carry private details.
                # Keep the worker alive and retry only after the reviewed poll
                # interval without logging or retaining the exception.
                self._stop_event.wait(self._poll_seconds)
                continue
            if not worked:
                self._stop_event.wait(self._poll_seconds)

    def run_once(self) -> bool:
        if self._stop_event.is_set():
            return False
        now = self._clock()
        self._execution_recovery_callback(now)
        token = secrets.token_hex(32)
        power_source = self._current_power_source()
        job = self._repository.claim_next(
            owner=self._worker_id,
            token=token,
            now=now,
            lease_duration=self._lease_duration,
            power_source=power_source,
        )
        if job is None:
            return False
        if job.lease_expires_at is None or job.lease_owner is None or job.lease_token is None:
            return True
        lease = AnalysisJobLease(
            job_id=job.job_id,
            owner=job.lease_owner,
            token=job.lease_token,
            expires_at=job.lease_expires_at,
        )
        handler = self._handlers.get((job.identity.kind, job.identity.provider))
        if handler is None:
            self._retry_safely(
                lease, "execution_handler_unavailable", retryable=False
            )
            return True
        context: AnalysisJobExecutionContext | None = None
        try:
            context = AnalysisJobExecutionContext(
                self._repository,
                job,
                lease,
                clock=self._clock,
                monotonic_clock=self._monotonic_clock,
                lease_duration=self._lease_duration,
                authorization_check=self._authorization_check,
                fingerprint_resolver=self._fingerprint_resolver,
                execution_stop_callback=self._execution_stop_callback,
                stop_requested=self._stop_event.is_set,
            )
            context.enter_stage(1, progress_completed=0, progress_total=1)
            result = handler(context.job, context)
            context.heartbeat()
            operation_at = context.repository_timestamp()
            if result.state is AnalysisJobState.AWAITING_APPROVAL:
                self._repository.await_approval(
                    context.lease,
                    now=operation_at,
                    reason_code=result.reason_code,
                    progress_completed=result.progress_completed,
                    progress_total=result.progress_total,
                )
            else:
                self._execution_stop_callback(
                    context.job, result.state, result.reason_code
                )
                self._repository.finish(
                    context.lease,
                    now=operation_at,
                    state=result.state,
                    reason_code=result.reason_code,
                    progress_completed=result.progress_completed,
                    progress_total=result.progress_total,
                )
        except AnalysisJobCooperativeStop:
            pass
        except AnalysisJobExecutionError as error:
            self._retry_safely(
                context.lease if context is not None else lease,
                error.code,
                error.retryable,
                context=context,
            )
        except Exception:
            self._retry_safely(
                context.lease if context is not None else lease,
                "execution_handler_failed",
                True,
                context=context,
            )
        return True

    def _current_power_source(self) -> PowerSourceState:
        if self._power_source is None:
            return PowerSourceState.UNKNOWN
        try:
            state = self._power_source.current()
        except Exception:
            return PowerSourceState.UNKNOWN
        return state if isinstance(state, PowerSourceState) else PowerSourceState.UNKNOWN

    def _retry_safely(
        self,
        lease: AnalysisJobLease,
        error_code: str,
        retryable: bool,
        *,
        context: AnalysisJobExecutionContext | None = None,
    ) -> None:
        try:
            operation_at = (
                context.repository_timestamp()
                if context is not None
                else self._clock()
            )
            current = self._repository.get(lease.job_id)
            if current is None:
                return
            terminal_state: AnalysisJobState | None = None
            terminal_reason = error_code
            if current.cancel_requested:
                terminal_reason = (
                    current.last_error_code or "cancellation_requested"
                )
                terminal_state = (
                    AnalysisJobState.SUPERSEDED
                    if terminal_reason in {"input_changed", "provenance_changed"}
                    else AnalysisJobState.CANCELLED
                )
            elif not retryable or current.attempt_count >= current.max_attempts:
                terminal_state = AnalysisJobState.FAILED
            if terminal_state is not None:
                self._execution_stop_callback(
                    current, terminal_state, terminal_reason
                )
            self._repository.retry_or_fail(
                lease,
                now=operation_at,
                error_code=error_code,
                retryable=retryable,
            )
        except AnalysisJobCooperativeStop:
            return
        except DatabaseInvariantError:
            # The lease was already recovered or terminal; never expose handler data.
            return
