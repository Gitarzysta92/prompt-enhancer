from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.jobs import (
    AnalysisJobCooperativeStop,
    AnalysisJobExecutionContext,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobRecord,
    AnalysisJobState,
    AnalysisJobWorker,
    AnalysisPublicationDeadlineFailure,
)
from prompt_enhancer.domain import Provider


STARTED_AT = datetime(2052, 6, 7, 8, 9, tzinfo=UTC)


class MutableWallClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SequenceWallClock:
    def __init__(self, *values: datetime | Exception) -> None:
        self.values = list(values)

    def __call__(self) -> datetime:
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class MutableMonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _active_job(*, high_water: datetime = STARTED_AT) -> AnalysisJobRecord:
    return AnalysisJobRecord(
        job_id="1" * 64,
        dedupe_key="2" * 64,
        identity=AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.SYNTHETIC,
            project_id="3" * 64,
            session_id="4" * 64,
            input_fingerprint="5" * 64,
            provenance_fingerprint="6" * 64,
            metric_keys=("prompt.context_sufficiency",),
            estimator_plan_version="synthetic-plan-v1",
            redactor_version="synthetic-redactor-v1",
            provider_schema_version="synthetic-schema-v1",
            automation_grant_id="7" * 64,
        ),
        state=AnalysisJobState.PREPROCESSING,
        progress_completed=0,
        progress_total=1,
        attempt_count=1,
        max_attempts=3,
        available_at=STARTED_AT,
        cancel_requested=False,
        lease_owner="8" * 64,
        lease_token="9" * 64,
        lease_expires_at=STARTED_AT + timedelta(minutes=5),
        runtime_started_at=STARTED_AT,
        publication_deadline_at=STARTED_AT + timedelta(minutes=30),
        publication_high_water_at=high_water,
        created_at=STARTED_AT - timedelta(minutes=1),
        updated_at=STARTED_AT,
    )


def _lease(job: AnalysisJobRecord) -> AnalysisJobLease:
    assert job.lease_owner is not None
    assert job.lease_token is not None
    assert job.lease_expires_at is not None
    return AnalysisJobLease(
        job_id=job.job_id,
        owner=job.lease_owner,
        token=job.lease_token,
        expires_at=job.lease_expires_at,
    )


class PublicationRepository:
    def __init__(self, job: AnalysisJobRecord) -> None:
        self.job = job
        self.checked_at: list[datetime] = []
        self.failures: list[AnalysisPublicationDeadlineFailure] = []
        self.renewed_at: list[datetime] = []
        self.advanced_at: list[datetime] = []
        self.retried_at: list[datetime] = []

    def get(self, job_id: str) -> AnalysisJobRecord | None:
        assert job_id == self.job.job_id
        return self.job

    def check_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
    ) -> AnalysisJobRecord:
        assert lease.job_id == self.job.job_id
        self.checked_at.append(now)
        return self.job

    def fail_publication_deadline(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        failure: AnalysisPublicationDeadlineFailure,
    ) -> AnalysisJobRecord:
        assert lease.job_id == self.job.job_id
        self.failures.append(failure)
        self.job = self.job.model_copy(
            update={
                "state": AnalysisJobState.FAILED,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "terminal_reason_code": failure.value,
                "terminal_at": now,
                "updated_at": now,
            }
        )
        return self.job

    def renew(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> AnalysisJobRecord:
        assert lease.job_id == self.job.job_id
        self.renewed_at.append(now)
        self.job = self.job.model_copy(
            update={
                "lease_expires_at": now + lease_duration,
                "updated_at": now,
            }
        )
        return self.job

    def advance_stage(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        stage_number: int,
        progress_completed: int,
        progress_total: int,
    ) -> AnalysisJobRecord:
        assert lease.job_id == self.job.job_id
        self.advanced_at.append(now)
        self.job = self.job.model_copy(
            update={
                "state": AnalysisJobState.STAGE_N,
                "stage_number": stage_number,
                "progress_completed": progress_completed,
                "progress_total": progress_total,
                "updated_at": now,
            }
        )
        return self.job

    def retry_or_fail(
        self,
        lease: AnalysisJobLease,
        *,
        now: datetime,
        error_code: str,
        retryable: bool,
    ) -> AnalysisJobRecord:
        del error_code, retryable
        assert lease.job_id == self.job.job_id
        self.retried_at.append(now)
        return self.job


def _context(
    repository: PublicationRepository,
    wall: MutableWallClock | SequenceWallClock,
    monotonic: MutableMonotonicClock,
) -> AnalysisJobExecutionContext:
    return AnalysisJobExecutionContext(
        repository,  # type: ignore[arg-type]
        repository.job,
        _lease(repository.job),
        clock=wall,
        monotonic_clock=monotonic,
        lease_duration=timedelta(minutes=5),
        authorization_check=lambda _job: True,
        fingerprint_resolver=lambda job: (
            job.identity.input_fingerprint,
            job.identity.provenance_fingerprint,
        ),
        execution_stop_callback=lambda _job, _state, _reason: None,
    )


def test_monotonic_deadline_equality_closes_without_faking_wall_time() -> None:
    wall = MutableWallClock(STARTED_AT)
    monotonic = MutableMonotonicClock(100.0)
    repository = PublicationRepository(_active_job())
    context = _context(repository, wall, monotonic)

    wall.value += timedelta(seconds=1)
    monotonic.value = 1_900.0
    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        context.publication_checkpoint()

    assert raised.value.reason_code == "automation_publication_deadline_exceeded"
    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED
    ]
    assert repository.job.terminal_at == STARTED_AT + timedelta(seconds=1)


def test_persisted_high_water_never_lengthens_rebased_monotonic_cutoff() -> None:
    high_water = STARTED_AT + timedelta(minutes=10)
    wall = MutableWallClock(STARTED_AT + timedelta(seconds=1))
    monotonic = MutableMonotonicClock(50.0)
    repository = PublicationRepository(_active_job(high_water=high_water))
    context = _context(repository, wall, monotonic)

    monotonic.value = 1_250.0
    with pytest.raises(AnalysisJobCooperativeStop):
        context.publication_checkpoint()

    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED
    ]


def test_monotonic_regression_uses_fixed_clock_failure() -> None:
    wall = MutableWallClock(STARTED_AT)
    monotonic = MutableMonotonicClock(100.0)
    repository = PublicationRepository(_active_job())
    context = _context(repository, wall, monotonic)

    monotonic.value = 99.0
    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        context.publication_checkpoint()

    assert raised.value.reason_code == "automation_publication_clock_regressed"
    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
    ]


def test_committed_publication_disables_later_cooperative_relabeling() -> None:
    wall = MutableWallClock(STARTED_AT)
    monotonic = MutableMonotonicClock(100.0)
    repository = PublicationRepository(_active_job())
    context = _context(repository, wall, monotonic)

    context.mark_publication_committed()
    wall.value += timedelta(hours=1)
    monotonic.value += 3_600

    assert context.heartbeat() == repository.job
    assert repository.checked_at == []
    assert repository.failures == []


@pytest.mark.parametrize("invalid", (float("nan"), float("inf"), -float("inf")))
def test_invalid_monotonic_clock_fails_closed_during_context_creation(
    invalid: float,
) -> None:
    wall = MutableWallClock(STARTED_AT)
    monotonic = MutableMonotonicClock(invalid)
    repository = PublicationRepository(_active_job())

    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        _context(repository, wall, monotonic)

    assert raised.value.reason_code == "automation_publication_clock_regressed"
    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
    ]


def test_guarded_stage_reuses_one_wall_observation_then_fails_next_read() -> None:
    observed_at = STARTED_AT + timedelta(seconds=1)
    wall = SequenceWallClock(
        STARTED_AT,
        observed_at,
        RuntimeError("synthetic clock unavailable"),
    )
    monotonic = MutableMonotonicClock(100.0)
    repository = PublicationRepository(_active_job())
    context = _context(repository, wall, monotonic)

    staged = context.enter_stage(
        2,
        progress_completed=0,
        progress_total=1,
    )

    assert staged.state is AnalysisJobState.STAGE_N
    assert repository.checked_at == [observed_at]
    assert repository.renewed_at == [observed_at]
    assert repository.advanced_at == [observed_at]
    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        context.heartbeat()
    assert raised.value.reason_code == "automation_publication_clock_regressed"
    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
    ]


def test_invalid_stop_clock_closes_before_execution_ledger_callback() -> None:
    wall = SequenceWallClock(
        STARTED_AT,
        RuntimeError("synthetic clock unavailable"),
    )
    monotonic = MutableMonotonicClock(100.0)
    job = _active_job().model_copy(
        update={
            "cancel_requested": True,
            "last_error_code": "cancellation_requested",
        }
    )
    repository = PublicationRepository(job)
    stopped: list[str] = []
    context = AnalysisJobExecutionContext(
        repository,  # type: ignore[arg-type]
        repository.job,
        _lease(repository.job),
        clock=wall,
        monotonic_clock=monotonic,
        lease_duration=timedelta(minutes=5),
        authorization_check=lambda _job: True,
        fingerprint_resolver=lambda current: (
            current.identity.input_fingerprint,
            current.identity.provenance_fingerprint,
        ),
        execution_stop_callback=(
            lambda _job, _state, reason: stopped.append(reason)
        ),
    )

    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        context.heartbeat()

    assert raised.value.reason_code == "automation_publication_clock_regressed"
    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
    ]
    assert stopped == []


def test_worker_retry_checks_deadline_clock_before_queue_retry() -> None:
    wall = SequenceWallClock(
        STARTED_AT,
        RuntimeError("synthetic clock unavailable"),
    )
    monotonic = MutableMonotonicClock(100.0)
    repository = PublicationRepository(_active_job())
    context = _context(repository, wall, monotonic)
    worker = AnalysisJobWorker(
        repository,  # type: ignore[arg-type]
        {},
        clock=wall,
        monotonic_clock=monotonic,
        worker_id="b" * 64,
    )

    worker._retry_safely(  # type: ignore[attr-defined]
        context.lease,
        "synthetic_handler_failure",
        True,
        context=context,
    )

    assert repository.failures == [
        AnalysisPublicationDeadlineFailure.CLOCK_REGRESSED
    ]
    assert repository.retried_at == []
