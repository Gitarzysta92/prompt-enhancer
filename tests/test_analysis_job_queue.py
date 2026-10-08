from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event
import time

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobExecutionResult,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobService,
    AnalysisJobState,
    AnalysisJobWorker,
    PowerSourceState,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database, SCHEMA_VERSION
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_analysis_job_token_1234567890"
NOW = datetime(2046, 1, 2, 3, 4, tzinfo=UTC)
PRIVATE_CANARY = "SYNTHETIC-PRIVATE-JOB-CONTENT-CANARY"


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: float) -> None:
        self.value += timedelta(**values)


def _database(tmp_path) -> tuple[Database, dict[str, object]]:
    database = Database(tmp_path / "queue.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session = database.list_sessions(limit=1)[0]
    return database, session


def _identity(
    session: dict[str, object],
    *,
    input_fingerprint: str = "a" * 64,
    provenance_fingerprint: str = "b" * 64,
    automation_grant_id: str | None = None,
    metric_keys: tuple[str, ...] = (
        "prompt.checkability_cue_coverage",
        "prompt.goal_cue_coverage",
    ),
) -> AnalysisJobIdentity:
    return AnalysisJobIdentity(
        kind=AnalysisJobKind.SESSION_QUALITY,
        provider=Provider.SYNTHETIC,
        project_id=str(session["project_id"]),
        session_id=str(session["session_id"]),
        input_fingerprint=input_fingerprint,
        provenance_fingerprint=provenance_fingerprint,
        metric_keys=metric_keys,
        estimator_plan_version="synthetic-plan-v1",
        redactor_version="synthetic-redactor-v1",
        provider_schema_version="synthetic-schema-v1",
        automation_grant_id=automation_grant_id,
        local_only=True,
    )


def _lease(job) -> AnalysisJobLease:  # type: ignore[no-untyped-def]
    assert job.lease_owner is not None
    assert job.lease_token is not None
    assert job.lease_expires_at is not None
    return AnalysisJobLease(
        job_id=job.job_id,
        owner=job.lease_owner,
        token=job.lease_token,
        expires_at=job.lease_expires_at,
    )


@pytest.mark.parametrize("boundary", ("heartbeat", "publication_checkpoint"))
def test_worker_shutdown_requeues_cooperative_work_before_publication(tmp_path, boundary) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    clock = MutableClock()
    queued = AnalysisJobService(repository, clock=clock).enqueue(_identity(session)).job
    entered, release = Event(), Event()

    def handler(_job, context):
        entered.set()
        while not release.wait(0.01):
            getattr(context, boundary)()
        return AnalysisJobExecutionResult(state=AnalysisJobState.COMPLETED, reason_code="example_completed", progress_completed=1, progress_total=1)

    worker = AnalysisJobWorker(
        repository, {(AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): handler},
        authorization_check=lambda _job: True,
        fingerprint_resolver=lambda job: (job.identity.input_fingerprint, job.identity.provenance_fingerprint),
        clock=clock, poll_seconds=0.05,
    )
    try:
        worker.start()
        assert entered.wait(2)
        worker.stop(timeout=2)
        stopped = repository.get(queued.job_id)
        assert stopped.state is AnalysisJobState.QUEUED
        assert stopped.last_error_code == "application_shutdown"
        assert stopped.terminal_at is None
        assert stopped.lease_owner is None
        assert stopped.progress_completed == 0
        assert worker.run_once() is False
    finally:
        release.set()
        worker.stop(timeout=2)


def test_schema_and_enqueue_are_durable_content_free_and_idempotent(tmp_path) -> None:
    database, session = _database(tmp_path)
    clock = MutableClock()
    service = AnalysisJobService(database.analysis_job_repository(), clock=clock)
    identity = _identity(session)

    first = service.enqueue(identity, max_attempts=3)
    clock.advance(seconds=1)
    duplicate = service.enqueue(identity, max_attempts=3)
    changed = service.enqueue(
        _identity(session, input_fingerprint="c" * 64),
        max_attempts=3,
    )

    assert SCHEMA_VERSION == 61
    assert first.created is True
    assert duplicate.created is False
    assert duplicate.job == first.job
    assert changed.job.job_id != first.job.job_id
    reopened = Database(database.path)
    reopened.initialize()
    persisted = reopened.analysis_job_repository().get(first.job.job_id)
    assert persisted == first.job
    assert persisted.identity.metric_keys == tuple(sorted(identity.metric_keys))
    assert PRIVATE_CANARY.encode() not in database.path.read_bytes()


def test_metric_scope_is_immutable_persisted_and_part_of_queue_identity(
    tmp_path,
) -> None:
    database, session = _database(tmp_path)
    service = AnalysisJobService(database.analysis_job_repository())
    one_metric = ("prompt.goal_cue_coverage",)
    several_metrics = (
        "logic.requirement_action_traceability",
        "prompt.checkability_cue_coverage",
        "prompt.goal_cue_coverage",
    )

    one = service.enqueue(_identity(session, metric_keys=one_metric)).job
    several = service.enqueue(
        _identity(session, metric_keys=several_metrics)
    ).job

    assert one.job_id != several.job_id
    assert one.dedupe_key != several.dedupe_key
    reopened = Database(database.path)
    reopened.initialize()
    persisted_one = reopened.analysis_job_repository().get(one.job_id)
    persisted_several = reopened.analysis_job_repository().get(several.job_id)
    assert persisted_one is not None
    assert persisted_several is not None
    assert persisted_one.identity.metric_keys == one_metric
    assert persisted_several.identity.metric_keys == several_metrics


def test_lease_heartbeat_restart_recovery_backoff_and_progress(tmp_path) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    clock = MutableClock()
    job = AnalysisJobService(repository, clock=clock).enqueue(
        _identity(session),
        max_attempts=2,
    ).job

    claimed = repository.claim_next(
        owner="1" * 64,
        token="2" * 64,
        now=clock(),
        lease_duration=timedelta(seconds=10),
    )
    assert claimed is not None
    assert claimed.state is AnalysisJobState.PREPROCESSING
    assert claimed.attempt_count == 1
    assert repository.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=clock(),
        lease_duration=timedelta(seconds=10),
    ) is None
    clock.advance(seconds=5)
    renewed = repository.renew(
        _lease(claimed),
        now=clock(),
        lease_duration=timedelta(seconds=10),
    )
    staged = repository.advance_stage(
        _lease(renewed),
        now=clock(),
        stage_number=2,
        progress_completed=1,
        progress_total=3,
    )
    assert staged.state is AnalysisJobState.STAGE_N
    assert staged.stage_number == 2
    assert (staged.progress_completed, staged.progress_total) == (1, 3)

    # A fresh repository simulates process restart after the renewed lease expires.
    clock.advance(seconds=11)
    restarted = Database(database.path).analysis_job_repository()
    recovery = restarted.recover_expired(now=clock())
    assert recovery.requeued == 1
    assert restarted.get(job.job_id).state is AnalysisJobState.QUEUED
    assert restarted.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=clock(),
        lease_duration=timedelta(seconds=10),
    ) is None
    clock.advance(seconds=5)
    retried = restarted.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=clock(),
        lease_duration=timedelta(seconds=10),
    )
    assert retried is not None
    assert retried.attempt_count == 2
    failed = restarted.retry_or_fail(
        _lease(retried),
        now=clock(),
        error_code="synthetic_failure",
        retryable=True,
    )
    assert failed.state is AnalysisJobState.FAILED
    assert failed.terminal_reason_code == "synthetic_failure"


def test_cancellation_grant_revocation_and_supersession_are_cooperative(tmp_path) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    clock = MutableClock()
    service = AnalysisJobService(repository, clock=clock)
    grant_id = "9" * 64
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=str(session["project_id"]),
                metric_keys=tuple(sorted(_identity(session).metric_keys)),
            ),
            created_at=clock(),
            expires_at=clock() + AUTOMATION_GRANT_LIFETIME,
        )
    )
    first = service.enqueue(
        _identity(session, automation_grant_id=grant_id),
    ).job
    second = service.enqueue(
        _identity(
            session,
            input_fingerprint="c" * 64,
            automation_grant_id=grant_id,
        ),
    ).job
    claimed = repository.claim_next(
        owner="1" * 64,
        token="2" * 64,
        now=clock(),
        lease_duration=timedelta(seconds=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    active = claimed
    queued = next(job for job in (first, second) if job.job_id != active.job_id)

    revoked = service.revoke_automation_grant(grant_id)
    assert revoked.cancelled == 1
    assert revoked.cancellation_requested == 1
    assert repository.get(queued.job_id).state is AnalysisJobState.CANCELLED
    terminal = repository.finish(
        _lease(repository.get(active.job_id)),
        now=clock(),
        state=AnalysisJobState.COMPLETED,
        reason_code="completed",
        progress_completed=1,
        progress_total=1,
    )
    assert terminal.state is AnalysisJobState.CANCELLED
    assert terminal.terminal_reason_code == "automation_grant_revoked"

    pending = service.enqueue(
        _identity(session, input_fingerprint="d" * 64),
    ).job
    superseded = service.supersede_if_changed(
        pending.job_id,
        input_fingerprint="e" * 64,
        provenance_fingerprint=pending.identity.provenance_fingerprint,
    )
    assert superseded.state is AnalysisJobState.SUPERSEDED
    assert superseded.terminal_reason_code == "input_changed"


def test_worker_runs_reviewed_synthetic_handler_and_detects_change(tmp_path) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    clock = MutableClock()
    service = AnalysisJobService(repository, clock=clock)
    completed_job = service.enqueue(_identity(session)).job

    def success(_job, context):  # type: ignore[no-untyped-def]
        context.enter_stage(2, progress_completed=1, progress_total=2)
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.COMPLETED,
            reason_code="synthetic_completed",
            progress_completed=2,
            progress_total=2,
        )

    exact = lambda job: (  # noqa: E731
        job.identity.input_fingerprint,
        job.identity.provenance_fingerprint,
    )
    worker = AnalysisJobWorker(
        repository,
        {(AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): success},
        authorization_check=lambda _job: True,
        fingerprint_resolver=exact,
        clock=clock,
        lease_duration=timedelta(seconds=10),
        worker_id="1" * 64,
    )
    assert worker.run_once() is True
    completed = repository.get(completed_job.job_id)
    assert completed.state is AnalysisJobState.COMPLETED
    assert completed.stage_number is None
    assert completed.progress_completed == 2

    changed_job = service.enqueue(
        _identity(session, input_fingerprint="c" * 64)
    ).job

    def change_during_run(job, context):  # type: ignore[no-untyped-def]
        service.supersede_if_changed(
            job.job_id,
            input_fingerprint="d" * 64,
            provenance_fingerprint=job.identity.provenance_fingerprint,
        )
        context.heartbeat()
        raise AssertionError("superseded work must stop before returning")

    changed_worker = AnalysisJobWorker(
        repository,
        {(AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): change_during_run},
        authorization_check=lambda _job: True,
        fingerprint_resolver=exact,
        clock=clock,
        lease_duration=timedelta(seconds=10),
        worker_id="2" * 64,
    )
    assert changed_worker.run_once() is True
    changed = repository.get(changed_job.job_id)
    assert changed.state is AnalysisJobState.SUPERSEDED
    assert changed.terminal_reason_code == "input_changed"


def test_worker_fails_closed_without_handler_and_can_wait_for_fresh_approval(
    tmp_path,
) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    service = AnalysisJobService(repository)
    unavailable = service.enqueue(_identity(session), max_attempts=1).job
    fail_closed = AnalysisJobWorker(
        repository,
        {},
        worker_id="1" * 64,
    )
    assert fail_closed.run_once() is True
    failed = repository.get(unavailable.job_id)
    assert failed.state is AnalysisJobState.FAILED
    assert failed.terminal_reason_code == "execution_handler_unavailable"

    approval_job = service.enqueue(
        _identity(session, input_fingerprint="c" * 64)
    ).job

    def approval_required(_job, _context):  # type: ignore[no-untyped-def]
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.AWAITING_APPROVAL,
            reason_code="fresh_approval_required",
            progress_completed=1,
            progress_total=2,
        )

    worker = AnalysisJobWorker(
        repository,
        {(AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): approval_required},
        authorization_check=lambda _job: True,
        fingerprint_resolver=lambda job: (
            job.identity.input_fingerprint,
            job.identity.provenance_fingerprint,
        ),
        lease_duration=timedelta(seconds=5),
        worker_id="2" * 64,
    )
    assert worker.run_once() is True
    waiting = repository.get(approval_job.job_id)
    assert waiting.state is AnalysisJobState.AWAITING_APPROVAL
    assert waiting.lease_owner is None
    assert waiting.progress_completed == 1
    assert waiting.last_error_code == "fresh_approval_required"
    resumed = service.resume_after_approval(waiting.job_id)
    assert resumed.state is AnalysisJobState.QUEUED
    assert resumed.last_error_code is None


def _http_payload(session: dict[str, object]) -> dict[str, object]:
    return {
        "kind": "session_quality",
        "provider": "synthetic",
        "project_id": session["project_id"],
        "session_id": session["session_id"],
        "input_fingerprint": "a" * 64,
        "provenance_fingerprint": "b" * 64,
        "metric_keys": [
            "prompt.goal_cue_coverage",
            "prompt.checkability_cue_coverage",
        ],
        "estimator_plan_version": "synthetic-plan-v1",
        "redactor_version": "synthetic-redactor-v1",
        "provider_schema_version": "synthetic-schema-v1",
        "max_attempts": 3,
    }


def test_http_queue_is_authenticated_strict_and_content_free(tmp_path, caplog) -> None:
    database, session = _database(tmp_path)
    service = AnalysisJobService(database.analysis_job_repository())
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=service,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    payload = _http_payload(session)

    with client:
        unauthorized = client.post("/v1/analysis-jobs", json=payload)
        private = dict(payload)
        private["transcript"] = PRIVATE_CANARY
        rejected = client.post(
            "/v1/analysis-jobs",
            json=private,
            headers={API_TOKEN_HEADER: TOKEN},
        )
        created = client.post(
            "/v1/analysis-jobs",
            json=payload,
            headers={API_TOKEN_HEADER: TOKEN},
        )
        duplicate = client.post(
            "/v1/analysis-jobs",
            json=payload,
            headers={API_TOKEN_HEADER: TOKEN},
        )
        job_id = created.json()["job"]["job_id"]
        fetched = client.get(
            f"/v1/analysis-jobs/{job_id}",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        latest = client.get(
            f"/v1/sessions/{session['session_id']}/analysis-jobs/latest",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        cancelled = client.post(
            f"/v1/analysis-jobs/{job_id}/cancellation",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert unauthorized.status_code == 401
    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "request validation failed"}
    assert PRIVATE_CANARY not in rejected.text
    assert created.status_code == 202 and created.json()["created"] is True
    assert created.headers["cache-control"] == "no-store, private"
    assert created.headers["pragma"] == "no-cache"
    assert duplicate.status_code == 202 and duplicate.json()["created"] is False
    assert fetched.status_code == 200 and fetched.json()["state"] == "queued"
    assert {
        "dedupe_key",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
    }.isdisjoint(fetched.json())
    assert latest.status_code == 200 and latest.json()["job_id"] == job_id
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert PRIVATE_CANARY not in caplog.text
    assert PRIVATE_CANARY.encode() not in database.path.read_bytes()


def test_fastapi_lifespan_starts_and_stops_local_worker(tmp_path) -> None:
    database, session = _database(tmp_path)
    repository = database.analysis_job_repository()
    service = AnalysisJobService(repository)

    def success(_job, _context):  # type: ignore[no-untyped-def]
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.COMPLETED,
            reason_code="synthetic_completed",
            progress_completed=1,
            progress_total=1,
        )

    worker = AnalysisJobWorker(
        repository,
        {(AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): success},
        authorization_check=lambda _job: True,
        fingerprint_resolver=lambda job: (
            job.identity.input_fingerprint,
            job.identity.provenance_fingerprint,
        ),
        lease_duration=timedelta(seconds=5),
        poll_seconds=0.05,
        worker_id="7" * 64,
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=service,
        analysis_job_worker=worker,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/v1/analysis-jobs",
            json=_http_payload(session),
            headers={API_TOKEN_HEADER: TOKEN},
        )
        job_id = created.json()["job"]["job_id"]
        state = "queued"
        for _ in range(100):
            response = client.get(
                f"/v1/analysis-jobs/{job_id}",
                headers={API_TOKEN_HEADER: TOKEN},
            )
            state = response.json()["state"]
            if state == "completed":
                break
            time.sleep(0.01)
    assert state == "completed"
