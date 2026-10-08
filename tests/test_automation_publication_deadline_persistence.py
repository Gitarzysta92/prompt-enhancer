from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3
from threading import Barrier

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.text_baselines import (
    TEXT_METRIC_ALGORITHM_ID,
    TEXT_METRIC_ALGORITHM_VERSION,
    TEXT_METRIC_ENGINE_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    TEXT_METRIC_SCHEMA_VERSION,
)
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobService,
    AnalysisJobState,
    AnalysisPublicationDeadlineFailure,
    PowerSourceState,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisPublicationRejectedError,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricSignalStatus,
    SessionAnalysisSignalRecord,
)
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseError,
    DatabaseInvariantError,
    _MIGRATION_1,
)
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.analysis_jobs import (
    SqliteAnalysisJobRepository,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2048, 3, 4, 5, 6, tzinfo=UTC)
METRIC_KEY = "prompt.goal_definition"


def _digest(label: str) -> str:
    return hashlib.sha256(f"reserved-example:{label}".encode("ascii")).hexdigest()


def _epoch_us(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value - epoch
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


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


@dataclass(frozen=True)
class _AutomationFixture:
    database: Database
    job_repository: object
    run_repository: object
    grant_id: str
    job_id: str
    run_id: str
    lease: AnalysisJobLease
    authority: SessionAnalysisCompletionAuthority
    draft: SessionAnalysisRunDraft


def _result(*, computed_at: datetime) -> SessionAnalysisResultRecord:
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=METRIC_KEY,
            version=1,
            numeric_value=2 / 3,
            unit="ratio",
            source=MetricSource.DETERMINISTIC,
            observed_count=3,
            eligible_count=4,
            coverage=0.75,
            confidence=0.8,
        ),
        value_state=MetricValueState.KNOWN,
        direction=SessionMetricDirection.HIGHER_IS_BETTER,
        applicability=SessionMetricApplicability.APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=2,
        fraction_denominator=3,
        evidence=(
            SessionAnalysisEvidenceRecord(
                message_id=_digest("publication-evidence"),
                origin=SessionEvidenceOrigin.DIRECT,
            ),
        ),
        signals=(
            SessionAnalysisSignalRecord(
                code="goal.action",
                status=SessionMetricSignalStatus.DETECTED,
                count=1,
            ),
            SessionAnalysisSignalRecord(
                code="goal.outcome",
                status=SessionMetricSignalStatus.MISSING,
                count=0,
            ),
        ),
        explanation_code="synthetic_known",
        algorithm_id=TEXT_METRIC_ALGORITHM_ID,
        algorithm_version=TEXT_METRIC_ALGORITHM_VERSION,
        rubric_version="prompt-logic-rubric-v1",
        computed_at=computed_at,
    )


def _automation_fixture(
    tmp_path,
    *,
    bind_run: bool = True,
    claim: bool = True,
) -> _AutomationFixture:
    database = Database(tmp_path / "publication-deadline.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session = database.list_sessions(limit=1)[0]
    session_id = str(session["session_id"])
    project_id = str(session["project_id"])
    grant_id = _digest("publication-grant")
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=project_id,
                metric_keys=(METRIC_KEY,),
            ),
            created_at=NOW,
            expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        )
    )
    job_repository = database.analysis_job_repository()
    queued = AnalysisJobService(job_repository, clock=lambda: NOW).enqueue(
        AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.SYNTHETIC,
            project_id=project_id,
            session_id=session_id,
            input_fingerprint=_digest("publication-input"),
            provenance_fingerprint=_digest("publication-provenance"),
            metric_keys=(METRIC_KEY,),
            estimator_plan_version="synthetic-plan-v1",
            redactor_version="synthetic-redactor-v1",
            provider_schema_version="synthetic-schema-v1",
            automation_grant_id=grant_id,
        ),
        max_attempts=3,
    ).job
    run_id = _digest("publication-run")
    draft = SessionAnalysisRunDraft(
        run_id=run_id,
        session_id=session_id,
        request_fingerprint=_digest("publication-request"),
        input_fingerprint=_digest("publication-run-input"),
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=(METRIC_KEY,),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version="explicit-session-text-analysis-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-schema-v1",
        content_schema_version="redacted-message-v1",
        metric_engine_version=TEXT_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint=_digest("publication-model-plan"),
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        started_at=NOW,
    )
    if not claim:
        placeholder = AnalysisJobLease(
            job_id=queued.job_id,
            owner=_digest("unclaimed-owner"),
            token=_digest("unclaimed-token"),
            expires_at=NOW + timedelta(minutes=10),
        )
        placeholder_authority = SessionAnalysisCompletionAuthority(
            job_id=queued.job_id,
            automation_grant_id=grant_id,
            lease_owner=placeholder.owner,
            lease_token=placeholder.token,
        )
        return _AutomationFixture(
            database=database,
            job_repository=job_repository,
            run_repository=database.session_analysis_run_repository(),
            grant_id=grant_id,
            job_id=queued.job_id,
            run_id=run_id,
            lease=placeholder,
            authority=placeholder_authority,
            draft=draft,
        )
    claimed = job_repository.claim_next(
        owner=_digest("publication-owner"),
        token=_digest("publication-token"),
        now=NOW,
        lease_duration=timedelta(minutes=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == queued.job_id
    lease = _lease(claimed)
    authority = SessionAnalysisCompletionAuthority(
        job_id=claimed.job_id,
        automation_grant_id=grant_id,
        lease_owner=lease.owner,
        lease_token=lease.token,
    )
    run_repository = database.session_analysis_run_repository()
    if bind_run:
        run_repository.begin(draft, completion_authority=authority)
    return _AutomationFixture(
        database=database,
        job_repository=job_repository,
        run_repository=run_repository,
        grant_id=grant_id,
        job_id=claimed.job_id,
        run_id=run_id,
        lease=lease,
        authority=authority,
        draft=draft,
    )


def _renew_to_publication_cutoff(fixture: _AutomationFixture) -> AnalysisJobLease:
    repository = fixture.job_repository
    lease = fixture.lease
    for minutes in (9, 18, 27):
        checked = repository.check_publication_deadline(
            lease,
            now=NOW + timedelta(minutes=minutes),
        )
        assert checked.state in {
            AnalysisJobState.PREPROCESSING,
            AnalysisJobState.STAGE_N,
        }
        renewed = repository.renew(
            _lease(checked),
            now=NOW + timedelta(minutes=minutes),
            lease_duration=timedelta(minutes=10),
        )
        lease = _lease(renewed)
    return lease


def _counts(database: Database, run_id: str, job_id: str) -> dict[str, int]:
    with database._connection(readonly=True) as connection:
        return {
            "results": connection.execute(
                "SELECT COUNT(*) FROM session_analysis_results WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            "evidence": connection.execute(
                "SELECT COUNT(*) FROM session_analysis_result_evidence WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            "signals": connection.execute(
                "SELECT COUNT(*) FROM session_analysis_result_signals WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            "history": connection.execute(
                "SELECT COUNT(*) FROM temporal_completion_requests WHERE analysis_run_id=?",
                (run_id,),
            ).fetchone()[0],
            "publication": connection.execute(
                "SELECT COUNT(*) FROM automation_session_quality_publications WHERE job_id=?",
                (job_id,),
            ).fetchone()[0],
            "closure": connection.execute(
                """SELECT COUNT(*)
                   FROM automation_session_quality_publication_closures
                   WHERE job_id=?""",
                (job_id,),
            ).fetchone()[0],
            "authorization": connection.execute(
                "SELECT COUNT(*) FROM automation_publication_write_authorizations"
            ).fetchone()[0],
        }


def _raw_rejected(
    database: Database,
    statement: str,
    parameters: tuple[object, ...] = (),
    *,
    match: str | None = None,
) -> None:
    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        with pytest.raises(sqlite3.DatabaseError, match=match):
            connection.execute(statement, parameters)
        connection.rollback()
        connection.execute("PRAGMA trusted_schema=OFF")


@pytest.mark.parametrize("populated", (False, True))
def test_v24_to_v25_preserves_prior_checksums_and_existing_data(
    tmp_path,
    populated: bool,
) -> None:
    path = tmp_path / f"{'populated' if populated else 'fresh'}-v24.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 25)
    )
    checksums = tuple(
        hashlib.sha256(script.encode("utf-8")).hexdigest()
        for script in scripts
    )
    timestamp = _iso(NOW)
    job_id = _digest("v24-preserved-job")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,
                   checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            tuple(
                (version, checksum, timestamp)
                for version, checksum in enumerate(checksums, start=1)
            ),
        )
        if populated:
            installation_id = _digest("v24-installation")
            project_id = _digest("v24-project")
            session_id = _digest("v24-session")
            connection.execute(
                "INSERT INTO installations VALUES(?,?,?)",
                (installation_id, "synthetic", timestamp),
            )
            connection.execute(
                """INSERT INTO projects(
                       project_id,installation_id,provider,created_at
                   ) VALUES(?,?,?,?)""",
                (project_id, installation_id, "synthetic", timestamp),
            )
            connection.execute(
                """INSERT INTO sessions(
                       session_id,installation_id,project_id,provider,
                       provider_version,adapter_version,source_schema_version,
                       started_at,ended_at,terminal_state,events_complete,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,'completed',1,?,?)""",
                (
                    session_id,
                    installation_id,
                    project_id,
                    "synthetic",
                    "synthetic-provider-v1",
                    "synthetic-adapter-v1",
                    "synthetic-schema-v1",
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """INSERT INTO analysis_jobs(
                       job_id,dedupe_key,kind,provider,project_id,session_id,
                       input_fingerprint,provenance_fingerprint,
                       estimator_plan_version,redactor_version,
                       provider_schema_version,automation_grant_id,local_only,
                       state,stage_number,progress_completed,progress_total,
                       attempt_count,max_attempts,available_at,cancel_requested,
                       lease_owner,lease_token,lease_expires_at,last_error_code,
                       terminal_reason_code,created_at,updated_at,terminal_at
                   ) VALUES(?,?, 'session_quality','synthetic',?,?,?,?,?,?,?,NULL,
                       1,'queued',NULL,0,1,0,3,?,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL)""",
                (
                    job_id,
                    _digest("v24-dedupe"),
                    project_id,
                    session_id,
                    _digest("v24-input"),
                    _digest("v24-provenance"),
                    "synthetic-plan-v1",
                    "synthetic-redactor-v1",
                    "synthetic-schema-v1",
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO analysis_job_metrics VALUES(?,?,0)",
                (job_id, METRIC_KEY),
            )
        connection.execute("PRAGMA user_version=24")
        connection.commit()

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in rows) == tuple(range(1, 62))
        assert tuple(row[1] for row in rows[:24]) == checksums
        assert rows[24][1] == hashlib.sha256(
            migrations.MIGRATION_25.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_session_quality_publication_deadlines"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_session_quality_publications"
        ).fetchone()[0] == 0
        if populated:
            assert connection.execute(
                "SELECT kind,state FROM analysis_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone() == ("session_quality", "queued")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_first_claim_root_is_atomic_concurrent_and_permanent_across_retry(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path, claim=False)
    unauthorized_repository = SqliteAnalysisJobRepository(
        fixture.database._connection,
        fixture.database._ensure_initialized,
    )
    with pytest.raises(
        DatabaseInvariantError,
        match="automation publication write is not authorized",
    ):
        unauthorized_repository.claim_next(
            owner=_digest("unauthorized-owner"),
            token=_digest("unauthorized-token"),
            now=NOW,
            lease_duration=timedelta(minutes=10),
            power_source=PowerSourceState.EXTERNAL_POWER,
        )
    rolled_back = fixture.job_repository.get(fixture.job_id)
    assert rolled_back is not None
    assert rolled_back.state is AnalysisJobState.QUEUED
    assert rolled_back.attempt_count == 0
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_session_quality_publication_deadlines"
        ).fetchone()[0] == 0

    barrier = Barrier(2)

    def claim(repository, owner: str, token: str):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=5)
        return repository.claim_next(
            owner=owner,
            token=token,
            now=NOW,
            lease_duration=timedelta(minutes=10),
            power_source=PowerSourceState.EXTERNAL_POWER,
        )

    repositories = (
        fixture.database.analysis_job_repository(),
        fixture.database.analysis_job_repository(),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                claim,
                repositories[0],
                _digest("concurrent-owner-a"),
                _digest("concurrent-token-a"),
            ),
            executor.submit(
                claim,
                repositories[1],
                _digest("concurrent-owner-b"),
                _digest("concurrent-token-b"),
            ),
        )
        claims = tuple(future.result(timeout=10) for future in futures)
    winners = tuple(item for item in claims if item is not None)
    assert len(winners) == 1
    first = winners[0]
    assert first.runtime_started_at == NOW
    assert first.publication_deadline_at == NOW + timedelta(minutes=30)
    assert first.publication_high_water_at == NOW
    with fixture.database._connection(readonly=True) as connection:
        root = connection.execute(
            """SELECT first_claim_at_us,deadline_at_us,high_water_at_us,
                      grant_revision,analysis_run_id
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()
        assert root is not None
        assert tuple(root) == (
            _epoch_us(NOW),
            _epoch_us(NOW + timedelta(minutes=30)),
            _epoch_us(NOW),
            1,
            None,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0

    retried = fixture.job_repository.retry_or_fail(
        _lease(first),
        now=NOW + timedelta(minutes=1),
        error_code="synthetic_retry",
        retryable=True,
    )
    assert retried.state is AnalysisJobState.QUEUED
    restarted = Database(fixture.database.path).analysis_job_repository()
    second = restarted.claim_next(
        owner=_digest("retry-owner"),
        token=_digest("retry-token"),
        now=NOW + timedelta(minutes=1, seconds=6),
        lease_duration=timedelta(minutes=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert second is not None
    assert second.attempt_count == 2
    assert second.runtime_started_at == NOW
    assert second.publication_deadline_at == NOW + timedelta(minutes=30)


def test_strict_on_time_publication_at_deadline_minus_one_microsecond(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    lease = _renew_to_publication_cutoff(fixture)
    finished_at = NOW + timedelta(minutes=30) - timedelta(microseconds=1)
    fixture.run_repository.complete(
        fixture.run_id,
        (_result(computed_at=finished_at),),
        finished_at=finished_at,
        completion_authority=fixture.authority,
    )
    stored = fixture.run_repository.get(fixture.run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 1,
        "evidence": 1,
        "signals": 2,
        "history": 0,
        "publication": 1,
        "closure": 0,
        "authorization": 0,
    }
    with fixture.database._connection(readonly=True) as connection:
        receipt = connection.execute(
            """SELECT analysis_run_id,published_at_us,result_count
               FROM automation_session_quality_publications WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()
        assert receipt is not None
        assert tuple(receipt) == (fixture.run_id, _epoch_us(finished_at), 1)

    completed = Database(fixture.database.path).analysis_job_repository().finish(
        lease,
        now=NOW + timedelta(minutes=31),
        state=AnalysisJobState.FAILED,
        reason_code="synthetic_late_queue_finish",
        progress_completed=0,
        progress_total=1,
    )
    assert completed.state is AnalysisJobState.COMPLETED
    assert completed.terminal_reason_code == "local_analysis_completed"
    assert completed.terminal_at == finished_at


@pytest.mark.parametrize("microseconds_after_cutoff", (0, 1))
def test_equality_and_later_publication_fail_atomically_with_no_derived_rows(
    tmp_path,
    microseconds_after_cutoff: int,
) -> None:
    fixture = _automation_fixture(tmp_path)
    _renew_to_publication_cutoff(fixture)
    finished_at = NOW + timedelta(
        minutes=30,
        microseconds=microseconds_after_cutoff,
    )
    with pytest.raises(SessionAnalysisPublicationRejectedError) as raised:
        fixture.run_repository.complete(
            fixture.run_id,
            (_result(computed_at=finished_at),),
            finished_at=finished_at,
            completion_authority=fixture.authority,
        )
    assert raised.value.reason_code == "automation_publication_deadline_exceeded"
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 0,
        "evidence": 0,
        "signals": 0,
        "history": 0,
        "publication": 0,
        "closure": 1,
        "authorization": 0,
    }
    run = fixture.run_repository.get(fixture.run_id)
    job = fixture.job_repository.get(fixture.job_id)
    assert run is not None and run.status is AnalysisRunStatus.FAILED
    assert run.failure_code == "automation_publication_deadline_exceeded"
    assert job is not None and job.state is AnalysisJobState.FAILED
    assert job.terminal_reason_code == "automation_publication_deadline_exceeded"
    with fixture.database._connection(readonly=True) as connection:
        closure = connection.execute(
            """SELECT reason_code,observation_kind,observed_at_us,
                      effective_high_water_at_us
               FROM automation_session_quality_publication_closures
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()
        assert closure is not None
        assert tuple(closure) == (
            "automation_publication_deadline_exceeded",
            "wall_deadline_exceeded",
            _epoch_us(finished_at),
            _epoch_us(finished_at),
        )


def test_wall_clock_regression_closes_at_persisted_high_water_across_restart(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path, bind_run=False)
    advanced = fixture.job_repository.check_publication_deadline(
        fixture.lease,
        now=NOW + timedelta(minutes=5),
    )
    assert advanced.publication_high_water_at == NOW + timedelta(minutes=5)
    terminal = fixture.job_repository.check_publication_deadline(
        _lease(advanced),
        now=NOW + timedelta(minutes=4),
    )
    assert terminal.state is AnalysisJobState.FAILED
    assert terminal.terminal_reason_code == "automation_publication_clock_regressed"
    assert terminal.terminal_at == NOW + timedelta(minutes=5)
    reopened = Database(fixture.database.path).analysis_job_repository().get(
        fixture.job_id
    )
    assert reopened == terminal
    with fixture.database._connection(readonly=True) as connection:
        closure = connection.execute(
            """SELECT reason_code,observation_kind,observed_at_us,
                      effective_high_water_at_us
               FROM automation_session_quality_publication_closures
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()
        assert tuple(closure) == (
            "automation_publication_clock_regressed",
            "wall_clock_regressed",
            _epoch_us(NOW + timedelta(minutes=4)),
            _epoch_us(NOW + timedelta(minutes=5)),
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "finish",
        "retry_or_fail",
        "request_cancel",
        "cancel_by_grant",
        "supersede",
        "recover_expired",
        "claim_next",
        "check_deadline",
        "fail_deadline",
        "renew",
        "advance_stage",
    ),
)
def test_completed_publication_receipt_wins_every_queue_mutation_after_restart(
    tmp_path,
    mutation: str,
) -> None:
    fixture = _automation_fixture(tmp_path)
    published_at = NOW + timedelta(minutes=1)
    fixture.run_repository.complete(
        fixture.run_id,
        (_result(computed_at=published_at),),
        finished_at=published_at,
        completion_authority=fixture.authority,
    )
    repository = Database(fixture.database.path).analysis_job_repository()
    live_now = NOW + timedelta(minutes=2)
    expired_now = NOW + timedelta(minutes=11)
    if mutation == "finish":
        repository.finish(
            fixture.lease,
            now=expired_now,
            state=AnalysisJobState.FAILED,
            reason_code="synthetic_failure",
            progress_completed=0,
            progress_total=1,
        )
    elif mutation == "retry_or_fail":
        repository.retry_or_fail(
            fixture.lease,
            now=expired_now,
            error_code="synthetic_failure",
            retryable=True,
        )
    elif mutation == "request_cancel":
        repository.request_cancel(fixture.job_id, now=expired_now)
    elif mutation == "cancel_by_grant":
        repository.cancel_by_automation_grant(
            fixture.grant_id,
            now=expired_now,
        )
    elif mutation == "supersede":
        repository.supersede(
            fixture.job_id,
            now=expired_now,
            reason_code="input_changed",
        )
    elif mutation == "recover_expired":
        repository.recover_expired(now=expired_now)
    elif mutation == "claim_next":
        assert repository.claim_next(
            owner=_digest("post-publication-owner"),
            token=_digest("post-publication-token"),
            now=expired_now,
            lease_duration=timedelta(minutes=5),
            power_source=PowerSourceState.EXTERNAL_POWER,
        ) is None
    elif mutation == "check_deadline":
        repository.check_publication_deadline(fixture.lease, now=live_now)
    elif mutation == "fail_deadline":
        repository.fail_publication_deadline(
            fixture.lease,
            now=live_now,
            failure=AnalysisPublicationDeadlineFailure.DEADLINE_EXCEEDED,
        )
    elif mutation == "renew":
        repository.renew(
            fixture.lease,
            now=live_now,
            lease_duration=timedelta(minutes=5),
        )
    else:
        repository.advance_stage(
            fixture.lease,
            now=live_now,
            stage_number=2,
            progress_completed=0,
            progress_total=1,
        )

    completed = repository.get(fixture.job_id)
    assert completed is not None
    assert completed.state is AnalysisJobState.COMPLETED
    assert completed.terminal_reason_code == "local_analysis_completed"
    assert completed.terminal_at == published_at
    assert completed.cancel_requested is False
    assert completed.progress_completed == completed.progress_total
    counts = _counts(fixture.database, fixture.run_id, fixture.job_id)
    assert counts["publication"] == 1
    assert counts["closure"] == 0
    assert counts["authorization"] == 0


def test_legacy_attempted_automation_without_root_fails_before_reclaim(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path, claim=False)
    with fixture.database._connection() as connection:
        connection.execute(
            "UPDATE analysis_jobs SET attempt_count=1 WHERE job_id=?",
            (fixture.job_id,),
        )
        connection.commit()
    repository = Database(fixture.database.path).analysis_job_repository()
    assert repository.claim_next(
        owner=_digest("legacy-owner"),
        token=_digest("legacy-token"),
        now=NOW + timedelta(minutes=1),
        lease_duration=timedelta(minutes=5),
        power_source=PowerSourceState.EXTERNAL_POWER,
    ) is None
    terminal = repository.get(fixture.job_id)
    assert terminal is not None
    assert terminal.job_id == fixture.job_id
    assert terminal.state is AnalysisJobState.FAILED
    assert terminal.attempt_count == 1
    assert terminal.terminal_reason_code == "automation_publication_deadline_missing"
    assert terminal.runtime_started_at is None
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_session_quality_publication_deadlines"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0


def test_authority_for_a_different_run_cannot_mutate_either_run_or_queue(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    wrong_run_id = _digest("authority-wrong-run")
    wrong_draft = fixture.draft.model_copy(
        update={
            "run_id": wrong_run_id,
            "request_fingerprint": _digest("authority-wrong-request"),
        }
    )
    fixture.run_repository.begin(wrong_draft)
    observed_at = NOW + timedelta(minutes=1)
    with pytest.raises(
        DatabaseInvariantError,
        match="completion authority does not match the bound run",
    ):
        fixture.run_repository.complete(
            wrong_run_id,
            (_result(computed_at=observed_at),),
            finished_at=observed_at,
            completion_authority=fixture.authority,
        )

    bound_run = fixture.run_repository.get(fixture.run_id)
    wrong_run = fixture.run_repository.get(wrong_run_id)
    job = fixture.job_repository.get(fixture.job_id)
    assert bound_run is not None and bound_run.status is AnalysisRunStatus.RUNNING
    assert wrong_run is not None and wrong_run.status is AnalysisRunStatus.RUNNING
    assert fixture.run_repository.get_results(wrong_run_id) == ()
    assert job is not None and job.state is AnalysisJobState.PREPROCESSING
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 0,
        "evidence": 0,
        "signals": 0,
        "history": 0,
        "publication": 0,
        "closure": 0,
        "authorization": 0,
    }
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            """SELECT analysis_run_id
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()[0] == fixture.run_id
    assert not fixture.database._automation_publication_authorizations


def test_wrong_receipt_result_count_cannot_seal_completed_run(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    published_at = NOW + timedelta(minutes=1)
    operation_id, tag = (
        fixture.database._begin_automation_publication_authorization(
            fixture.job_id,
            "publish",
        )
    )
    try:
        with fixture.database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO automation_publication_write_authorizations VALUES(?,?,?,?)",
                (operation_id, fixture.job_id, "publish", tag),
            )
            connection.execute(
                """INSERT INTO automation_session_quality_publications(
                       job_id,analysis_run_id,published_at,published_at_us,
                       result_count
                   ) VALUES(?,?,?,?,?)""",
                (
                    fixture.job_id,
                    fixture.run_id,
                    _iso(published_at),
                    _epoch_us(published_at),
                    2,
                ),
            )
            with pytest.raises(
                sqlite3.DatabaseError,
                match="deadline rejected run",
            ):
                connection.execute(
                    """UPDATE session_analysis_runs
                       SET status='completed',finished_at=? WHERE run_id=?""",
                    (_iso(published_at), fixture.run_id),
                )
            connection.rollback()
            connection.execute("PRAGMA trusted_schema=OFF")
    finally:
        fixture.database._end_automation_publication_authorization(
            operation_id,
            fixture.job_id,
            "publish",
            tag,
        )

    run = fixture.run_repository.get(fixture.run_id)
    job = fixture.job_repository.get(fixture.job_id)
    assert run is not None and run.status is AnalysisRunStatus.RUNNING
    assert job is not None and job.state is AnalysisJobState.PREPROCESSING
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 0,
        "evidence": 0,
        "signals": 0,
        "history": 0,
        "publication": 0,
        "closure": 0,
        "authorization": 0,
    }
    assert not fixture.database._automation_publication_authorizations


def test_raw_publication_graph_writes_and_queue_transitions_require_live_hmac(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path, bind_run=False)
    fake_job_id = _digest("raw-fake-job")
    fake_run_id = _digest("raw-fake-run")
    deadline = NOW + timedelta(minutes=30)

    _raw_rejected(
        fixture.database,
        "INSERT INTO automation_publication_write_authorizations VALUES(?,?,?,?)",
        (
            _digest("forged-operation"),
            fixture.job_id,
            "root",
            _digest("forged-tag"),
        ),
        match="authorization is invalid",
    )
    _raw_rejected(
        fixture.database,
        """INSERT INTO automation_session_quality_publication_deadlines
           SELECT ?,automation_grant_id,grant_revision,first_claim_at,
                  first_claim_at_us,deadline_at_us,deadline_at,high_water_at_us,
                  high_water_at,analysis_run_id
           FROM automation_session_quality_publication_deadlines WHERE job_id=?""",
        (fake_job_id, fixture.job_id),
        match="root is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """UPDATE automation_session_quality_publication_deadlines
           SET high_water_at_us=high_water_at_us+1 WHERE job_id=?""",
        (fixture.job_id,),
        match="mutation is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """UPDATE automation_session_quality_publication_deadlines
           SET analysis_run_id=? WHERE job_id=?""",
        (fake_run_id, fixture.job_id),
        match="mutation is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """INSERT INTO automation_session_quality_publication_closures(
               job_id,reason_code,observation_kind,observed_at_us,
               effective_high_water_at_us
           ) VALUES(?,?,?,?,?)""",
        (
            fixture.job_id,
            "automation_publication_deadline_exceeded",
            "wall_deadline_exceeded",
            _epoch_us(deadline),
            _epoch_us(deadline),
        ),
        match="closure is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """UPDATE analysis_jobs SET state='completed',stage_number=NULL,
               progress_completed=progress_total,lease_owner=NULL,lease_token=NULL,
               lease_expires_at=NULL,terminal_reason_code='local_analysis_completed',
               terminal_at=?,updated_at=? WHERE job_id=?""",
        (_iso(NOW + timedelta(minutes=1)), _iso(NOW + timedelta(minutes=1)), fixture.job_id),
        match="terminal transition is invalid",
    )

    fixture.run_repository.begin(
        fixture.draft,
        completion_authority=fixture.authority,
    )
    published_at = NOW + timedelta(minutes=1)
    _raw_rejected(
        fixture.database,
        """INSERT INTO automation_session_quality_publications(
               job_id,analysis_run_id,published_at,published_at_us,result_count
           ) VALUES(?,?,?,?,?)""",
        (
            fixture.job_id,
            fixture.run_id,
            _iso(published_at),
            _epoch_us(published_at),
            1,
        ),
        match="receipt is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """INSERT INTO session_analysis_results(
               run_id,key,version,metric_schema_version,value_state,numeric_value,
               unit,source,direction,applicability,aggregation_method,
               fraction_numerator,fraction_denominator,observed_count,
               eligible_count,coverage,confidence,evidence_data_tier,
               explanation_code,error_code,algorithm_id,algorithm_version,
               model_id,model_revision,model_license,tokenizer_id,prompt_version,
               rubric_version,computed_at
           ) VALUES(?,?,1,2,'known',0.5,'ratio','deterministic',
               'higher_is_better','applicable','ratio_of_sums',1,2,1,1,1.0,
               NULL,'redacted_content','synthetic_known',NULL,?,?,NULL,NULL,NULL,
               NULL,NULL,'prompt-logic-rubric-v1',?)""",
        (
            fixture.run_id,
            METRIC_KEY,
            TEXT_METRIC_ALGORITHM_ID,
            TEXT_METRIC_ALGORITHM_VERSION,
            _iso(published_at),
        ),
        match="deadline rejected result",
    )
    _raw_rejected(
        fixture.database,
        """UPDATE session_analysis_runs SET status='completed',finished_at=?
           WHERE run_id=?""",
        (_iso(published_at), fixture.run_id),
        match="deadline rejected run",
    )
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 0,
        "evidence": 0,
        "signals": 0,
        "history": 0,
        "publication": 0,
        "closure": 0,
        "authorization": 0,
    }

    fixture.run_repository.complete(
        fixture.run_id,
        (_result(computed_at=published_at),),
        finished_at=published_at,
        completion_authority=fixture.authority,
    )
    _raw_rejected(
        fixture.database,
        """UPDATE automation_session_quality_publications
           SET result_count=2 WHERE job_id=?""",
        (fixture.job_id,),
        match="receipt is immutable",
    )
    _raw_rejected(
        fixture.database,
        "DELETE FROM automation_session_quality_publications WHERE job_id=?",
        (fixture.job_id,),
        match="privacy deletion is not authorized",
    )
    _raw_rejected(
        fixture.database,
        "DELETE FROM automation_session_quality_publication_deadlines WHERE job_id=?",
        (fixture.job_id,),
        match="privacy deletion is not authorized",
    )
    _raw_rejected(
        fixture.database,
        """UPDATE analysis_jobs SET cancel_requested=1,
               last_error_code='cancellation_requested',updated_at=? WHERE job_id=?""",
        (_iso(NOW + timedelta(minutes=2)), fixture.job_id),
        match="completed automation publication must win",
    )
    assert _counts(fixture.database, fixture.run_id, fixture.job_id)[
        "publication"
    ] == 1


def test_closure_and_deadline_root_are_immutable_without_privacy_authority(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    lease = _renew_to_publication_cutoff(fixture)
    terminal = fixture.job_repository.check_publication_deadline(
        lease,
        now=NOW + timedelta(minutes=30),
    )
    assert terminal.state is AnalysisJobState.FAILED
    assert terminal.terminal_reason_code == "automation_publication_deadline_exceeded"
    _raw_rejected(
        fixture.database,
        """UPDATE automation_session_quality_publication_closures
           SET observation_kind='monotonic_deadline_exceeded' WHERE job_id=?""",
        (fixture.job_id,),
        match="closure is immutable",
    )
    _raw_rejected(
        fixture.database,
        "DELETE FROM automation_session_quality_publication_closures WHERE job_id=?",
        (fixture.job_id,),
        match="privacy deletion is not authorized",
    )
    _raw_rejected(
        fixture.database,
        "DELETE FROM automation_session_quality_publication_deadlines WHERE job_id=?",
        (fixture.job_id,),
        match="privacy deletion is not authorized",
    )
    counts = _counts(fixture.database, fixture.run_id, fixture.job_id)
    assert counts["closure"] == 1
    assert counts["authorization"] == 0


def test_publication_transaction_rollback_removes_receipt_and_hmac_capability(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    finished_at = NOW + timedelta(minutes=1)
    invalid_result = _result(computed_at=finished_at + timedelta(seconds=1))
    with pytest.raises(
        DatabaseInvariantError,
        match="result timestamp is outside the analysis window",
    ):
        fixture.run_repository.complete(
            fixture.run_id,
            (invalid_result,),
            finished_at=finished_at,
            completion_authority=fixture.authority,
        )
    assert _counts(fixture.database, fixture.run_id, fixture.job_id) == {
        "results": 0,
        "evidence": 0,
        "signals": 0,
        "history": 0,
        "publication": 0,
        "closure": 0,
        "authorization": 0,
    }
    assert not fixture.database._automation_publication_authorizations
    run = fixture.run_repository.get(fixture.run_id)
    job = fixture.job_repository.get(fixture.job_id)
    assert run is not None and run.status is AnalysisRunStatus.RUNNING
    assert job is not None and job.state is AnalysisJobState.PREPROCESSING

    fixture.run_repository.complete(
        fixture.run_id,
        (_result(computed_at=finished_at),),
        finished_at=finished_at,
        completion_authority=fixture.authority,
    )
    assert _counts(fixture.database, fixture.run_id, fixture.job_id)[
        "publication"
    ] == 1


@pytest.mark.parametrize("sealed_kind", ("publication", "closure"))
def test_run_privacy_deletion_removes_publication_root_receipt_or_closure(
    tmp_path,
    sealed_kind: str,
) -> None:
    fixture = _automation_fixture(tmp_path)
    if sealed_kind == "publication":
        published_at = NOW + timedelta(minutes=1)
        fixture.run_repository.complete(
            fixture.run_id,
            (_result(computed_at=published_at),),
            finished_at=published_at,
            completion_authority=fixture.authority,
        )
    else:
        lease = _renew_to_publication_cutoff(fixture)
        fixture.job_repository.check_publication_deadline(
            lease,
            now=NOW + timedelta(minutes=30),
        )
    before = _counts(fixture.database, fixture.run_id, fixture.job_id)
    assert before[sealed_kind] == 1

    assert fixture.run_repository.delete_for_privacy(fixture.run_id) is True

    assert fixture.run_repository.get(fixture.run_id) is None
    with fixture.database._connection(readonly=True) as connection:
        for table in (
            "automation_session_quality_publication_deadlines",
            "automation_session_quality_publications",
            "automation_session_quality_publication_closures",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE job_id=?",  # noqa: S608
                (fixture.job_id,),
            ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not fixture.database._automation_publication_authorizations


def test_privacy_deletion_rollback_restores_graph_and_cleans_authority(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    published_at = NOW + timedelta(minutes=1)
    fixture.run_repository.complete(
        fixture.run_id,
        (_result(computed_at=published_at),),
        finished_at=published_at,
        completion_authority=fixture.authority,
    )
    with fixture.database._connection() as connection:
        connection.execute(
            f"""CREATE TRIGGER synthetic_privacy_rollback_probe
                BEFORE DELETE ON session_analysis_runs
                WHEN OLD.run_id='{fixture.run_id}'
                BEGIN SELECT RAISE(ABORT,'synthetic privacy rollback'); END;"""
        )
        connection.commit()

    with pytest.raises(DatabaseError, match="local database operation failed"):
        fixture.run_repository.delete_for_privacy(fixture.run_id)

    retained = _counts(fixture.database, fixture.run_id, fixture.job_id)
    assert retained["publication"] == 1
    assert retained["results"] == 1
    assert retained["authorization"] == 0
    assert fixture.run_repository.get(fixture.run_id) is not None
    assert not fixture.database._automation_publication_authorizations
    with fixture.database._connection() as connection:
        connection.execute("DROP TRIGGER synthetic_privacy_rollback_probe")
        connection.commit()
    assert fixture.run_repository.delete_for_privacy(fixture.run_id) is True
    assert fixture.run_repository.get(fixture.run_id) is None


@pytest.mark.parametrize(
    ("bypass", "recursive_triggers"),
    (
        ("job_delete", False),
        ("job_self_replace", False),
        ("job_self_replace", True),
        ("job_dedupe_replace", False),
        ("session_delete", False),
        ("project_delete", False),
    ),
)
def test_publication_root_survives_direct_replace_and_parent_delete_bypasses(
    tmp_path,
    bypass: str,
    recursive_triggers: bool,
) -> None:
    fixture = _automation_fixture(tmp_path)
    job = fixture.job_repository.get(fixture.job_id)
    assert job is not None
    replacement_job_id = _digest("publication-replacement-job")
    with fixture.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute(
            f"PRAGMA recursive_triggers={'ON' if recursive_triggers else 'OFF'}"
        )
        with pytest.raises(sqlite3.DatabaseError):
            if bypass == "job_delete":
                connection.execute(
                    "DELETE FROM analysis_jobs WHERE job_id=?",
                    (fixture.job_id,),
                )
            elif bypass == "job_self_replace":
                connection.execute(
                    """INSERT OR REPLACE INTO analysis_jobs
                       SELECT * FROM analysis_jobs WHERE job_id=?""",
                    (fixture.job_id,),
                )
            elif bypass == "job_dedupe_replace":
                columns = tuple(
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(analysis_jobs)"
                    ).fetchall()
                )
                selected = ("?",) + columns[1:]
                connection.execute(
                    f"""INSERT OR REPLACE INTO analysis_jobs({','.join(columns)})
                        SELECT {','.join(selected)} FROM analysis_jobs
                        WHERE job_id=?""",  # noqa: S608 - schema-owned names
                    (replacement_job_id, fixture.job_id),
                )
            elif bypass == "session_delete":
                connection.execute(
                    "DELETE FROM sessions WHERE session_id=?",
                    (fixture.draft.session_id,),
                )
            else:
                connection.execute(
                    "DELETE FROM projects WHERE project_id=?",
                    (job.identity.project_id,),
                )
        connection.rollback()
        connection.execute("PRAGMA trusted_schema=OFF")

    retained_job = fixture.job_repository.get(fixture.job_id)
    retained_run = fixture.run_repository.get(fixture.run_id)
    assert retained_job == job
    assert fixture.job_repository.get(replacement_job_id) is None
    assert retained_run is not None
    assert retained_run.status is AnalysisRunStatus.RUNNING
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_id=?",
            (fixture.draft.session_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM projects WHERE project_id=?",
            (job.identity.project_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            """SELECT analysis_run_id
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()[0] == fixture.run_id
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert fixture.database.automation_grant_repository().get(
        fixture.grant_id
    ) is not None

    cutoff = NOW + timedelta(minutes=30)
    with pytest.raises(DatabaseError, match="local database operation failed"):
        fixture.run_repository.complete(
            fixture.run_id,
            (_result(computed_at=cutoff),),
            finished_at=cutoff,
        )
    assert fixture.run_repository.get_results(fixture.run_id) == ()
    after_late_attempt = fixture.run_repository.get(fixture.run_id)
    assert after_late_attempt is not None
    assert after_late_attempt.status is AnalysisRunStatus.RUNNING
    assert fixture.job_repository.get(fixture.job_id) == retained_job
    counts = _counts(fixture.database, fixture.run_id, fixture.job_id)
    assert counts["publication"] == 0
    assert counts["closure"] == 0
    assert counts["authorization"] == 0
    assert not fixture.database._automation_publication_authorizations


def test_run_privacy_releases_root_before_independent_job_deletion(
    tmp_path,
) -> None:
    fixture = _automation_fixture(tmp_path)
    assert fixture.run_repository.delete_for_privacy(fixture.run_id) is True
    assert fixture.run_repository.get(fixture.run_id) is None
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            """SELECT COUNT(*)
               FROM automation_session_quality_publication_deadlines
               WHERE job_id=?""",
            (fixture.job_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0
    assert not fixture.database._automation_publication_authorizations

    with fixture.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        assert connection.execute(
            "DELETE FROM analysis_jobs WHERE job_id=?",
            (fixture.job_id,),
        ).rowcount == 1
        connection.commit()
        connection.execute("PRAGMA trusted_schema=OFF")
    assert fixture.job_repository.get(fixture.job_id) is None
    with pytest.raises(
        DatabaseInvariantError,
        match="run is missing or already terminal",
    ):
        fixture.run_repository.complete(
            fixture.run_id,
            (_result(computed_at=NOW + timedelta(minutes=1)),),
            finished_at=NOW + timedelta(minutes=1),
        )
    with fixture.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_publication_write_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
