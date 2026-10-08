from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3

import pytest

from prompt_enhancer.application.estimators.runtime_persistence import (
    EstimatorRuntimeState,
    EstimatorRuntimeStateReceipt,
)
from prompt_enhancer.application.jobs import AnalysisJobState, PowerSourceState
from prompt_enhancer.database import Database, SCHEMA_VERSION, _MIGRATION_1
from prompt_enhancer.infrastructure.sqlite import migrations

from test_estimator_runtime_persistence import _automation_runtime_setup, digest


BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _queue_with_terminal_runtime(
    tmp_path,
    *,
    label: str,
    state: EstimatorRuntimeState,
    reason_code: str,
):  # type: ignore[no-untyped-def]
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label=label)
    )
    snapshot = repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest(f"{label}-owner"),
        token=digest(f"{label}-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    assert claimed.job_id == launch.authorization.job_id

    created = snapshot.states[-1]
    running = EstimatorRuntimeStateReceipt(
        state_receipt_id=digest(f"{label}-running-state"),
        execution_id=launch.authorization.execution_id,
        sequence=created.sequence + 1,
        previous_state_receipt_fingerprint=created.canonical_fingerprint,
        state=EstimatorRuntimeState.RUNNING,
        reason_code="runtime_worker_started",
        recorded_at=clock(),
    )
    repository.append_state(running)
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest(f"{label}-{state.value}-state"),
            execution_id=launch.authorization.execution_id,
            sequence=running.sequence + 1,
            previous_state_receipt_fingerprint=running.canonical_fingerprint,
            state=state,
            reason_code=reason_code,
            recorded_at=clock(),
        )
    )

    # Reproduce the durable half of a real failure interleaving: the runtime
    # terminal append committed, then queue completion failed and retry put the
    # still non-terminal queue row back into QUEUED.
    with database._connection() as connection:
        connection.execute(
            """
            UPDATE analysis_jobs SET state='queued',stage_number=NULL,
                available_at=?,lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,last_error_code='execution_handler_failed',
                terminal_reason_code=NULL,terminal_at=NULL,updated_at=?
            WHERE job_id=? AND state IN ('preprocessing','stage_n')
            """,
            (
                clock().isoformat(timespec="microseconds"),
                clock().isoformat(timespec="microseconds"),
                launch.authorization.job_id,
            ),
        )
        connection.commit()
    return database, clock, repository, launch


@pytest.mark.parametrize(
    ("runtime_state", "reason_code"),
    (
        (EstimatorRuntimeState.PARTIAL, "local_model_runtime_not_enabled"),
        (EstimatorRuntimeState.FAILED, "execution_handler_failed"),
    ),
)
def test_queued_estimator_can_mirror_exact_latest_runtime_terminal_receipt(
    tmp_path,
    runtime_state: EstimatorRuntimeState,
    reason_code: str,
) -> None:
    database, clock, repository, launch = _queue_with_terminal_runtime(
        tmp_path,
        label=f"exact-{runtime_state.value}",
        state=runtime_state,
        reason_code=reason_code,
    )
    timestamp = clock().isoformat(timespec="microseconds")
    with database._connection() as connection:
        updated = connection.execute(
            """
            UPDATE analysis_jobs SET state=?,terminal_reason_code=?,
                terminal_at=?,updated_at=?
            WHERE job_id=? AND state='queued'
            """,
            (
                runtime_state.value,
                reason_code,
                timestamp,
                timestamp,
                launch.authorization.job_id,
            ),
        )
        assert updated.rowcount == 1
        connection.commit()

    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState(runtime_state.value)
    assert snapshot.job.terminal_reason_code == reason_code
    assert snapshot.states[-1].state is runtime_state
    assert snapshot.states[-1].reason_code == reason_code


@pytest.mark.parametrize(
    ("requested_state", "requested_reason"),
    (
        ("partial", "different_reason"),
        ("failed", "local_model_runtime_not_enabled"),
    ),
)
def test_queued_estimator_transition_rejects_nonmatching_terminal_receipt(
    tmp_path,
    requested_state: str,
    requested_reason: str,
) -> None:
    database, clock, repository, launch = _queue_with_terminal_runtime(
        tmp_path,
        label=f"mismatch-{requested_state}-{requested_reason}",
        state=EstimatorRuntimeState.PARTIAL,
        reason_code="local_model_runtime_not_enabled",
    )
    timestamp = clock().isoformat(timespec="microseconds")
    with database._connection() as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """
                UPDATE analysis_jobs SET state=?,terminal_reason_code=?,
                    terminal_at=?,updated_at=?
                WHERE job_id=? AND state='queued'
                """,
                (
                    requested_state,
                    requested_reason,
                    timestamp,
                    timestamp,
                    launch.authorization.job_id,
                ),
            )
        connection.rollback()

    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.QUEUED
    assert snapshot.states[-1].state is EstimatorRuntimeState.PARTIAL


@pytest.mark.parametrize("requested_state", ("partial", "failed"))
def test_created_runtime_and_non_estimator_cannot_use_reconciliation_transition(
    tmp_path,
    requested_state: str,
) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(
            tmp_path,
            label=f"closed-{requested_state}",
        )
    )
    repository.launch(launch)
    timestamp = clock().isoformat(timespec="microseconds")
    with database._connection() as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """
                UPDATE analysis_jobs SET state=?,terminal_reason_code=?,
                    terminal_at=?,updated_at=?
                WHERE job_id=? AND state='queued'
                """,
                (
                    requested_state,
                    "runtime_receipt_absent",
                    timestamp,
                    timestamp,
                    launch.authorization.job_id,
                ),
            )
        connection.rollback()

        manual_job_id = digest(f"manual-{requested_state}-job")
        connection.execute(
            """
            INSERT INTO analysis_jobs(
                job_id,dedupe_key,kind,provider,project_id,session_id,
                input_fingerprint,provenance_fingerprint,
                estimator_plan_version,redactor_version,
                provider_schema_version,automation_grant_id,local_only,state,
                stage_number,progress_completed,progress_total,attempt_count,
                max_attempts,available_at,cancel_requested,lease_owner,
                lease_token,lease_expires_at,last_error_code,
                terminal_reason_code,created_at,updated_at,terminal_at
            ) VALUES (?,?, 'session_quality',?,?,?,?,?,?,?, ?,NULL,1,'queued',
                      NULL,0,1,0,3,?,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL)
            """,
            (
                manual_job_id,
                digest(f"manual-{requested_state}-dedupe"),
                launch.authorization.provider.value,
                launch.authorization.project_id,
                launch.authorization.session_id,
                digest(f"manual-{requested_state}-input"),
                digest(f"manual-{requested_state}-provenance"),
                "synthetic-plan-v1",
                "synthetic-redactor-v1",
                launch.authorization.provider_schema_version,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO analysis_job_metrics VALUES (?,?,0)",
            (manual_job_id, launch.authorization.packet_bindings[0].metric_key),
        )
        connection.commit()

    with database._connection() as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """
                UPDATE analysis_jobs SET state=?,terminal_reason_code=?,
                    terminal_at=?,updated_at=? WHERE job_id=?
                """,
                (
                    requested_state,
                    "runtime_receipt_absent",
                    timestamp,
                    timestamp,
                    manual_job_id,
                ),
            )
        connection.rollback()
        assert connection.execute(
            "SELECT state FROM analysis_jobs WHERE job_id=?", (manual_job_id,)
        ).fetchone()[0] == "queued"


def test_unbound_estimator_cannot_use_reconciliation_transition(tmp_path) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label="unbound")
    )
    repository.launch(launch)
    timestamp = clock().isoformat(timespec="microseconds")
    unbound_job_id = digest("unbound-estimator-job")
    with database._connection() as connection:
        with repository._authorized(
            connection,
            launch.authorization.authorization_id,
            launch.authorization.execution_id,
            unbound_job_id,
        ):
            connection.execute(
                """
                INSERT INTO analysis_jobs(
                    job_id,dedupe_key,kind,provider,project_id,session_id,
                    input_fingerprint,provenance_fingerprint,
                    estimator_plan_version,redactor_version,
                    provider_schema_version,automation_grant_id,local_only,state,
                    stage_number,progress_completed,progress_total,attempt_count,
                    max_attempts,available_at,cancel_requested,lease_owner,
                    lease_token,lease_expires_at,last_error_code,
                    terminal_reason_code,created_at,updated_at,terminal_at
                ) VALUES (?,?, 'estimator_execution',?,?,?,?,?,?,?, ?,?,1,'queued',
                          NULL,0,1,0,3,?,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL)
                """,
                (
                    unbound_job_id,
                    digest("unbound-estimator-dedupe"),
                    launch.authorization.provider.value,
                    launch.authorization.project_id,
                    launch.authorization.session_id,
                    digest("unbound-estimator-input"),
                    digest("unbound-estimator-provenance"),
                    launch.authorization.plan_fingerprint,
                    launch.authorization.redactor_version,
                    launch.authorization.provider_schema_version,
                    launch.authorization.automation_grant_id,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
        connection.commit()

    with database._connection() as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """
                UPDATE analysis_jobs SET state='failed',
                    terminal_reason_code='runtime_receipt_absent',
                    terminal_at=?,updated_at=? WHERE job_id=?
                """,
                (timestamp, timestamp, unbound_job_id),
            )
        connection.rollback()
        assert connection.execute(
            "SELECT state FROM analysis_jobs WHERE job_id=?", (unbound_job_id,)
        ).fetchone()[0] == "queued"


def test_populated_v23_upgrades_to_v24_with_prior_checksums_unchanged(
    tmp_path,
) -> None:
    path = tmp_path / "populated-v23.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 24)
    )
    checksums = tuple(
        hashlib.sha256(script.encode("utf-8")).hexdigest() for script in scripts
    )
    timestamp = BASE.isoformat(timespec="microseconds")
    installation_id = digest("v23-installation")
    project_id = digest("v23-project")
    session_id = digest("v23-session")
    job_id = digest("v23-job")

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?,?)",
            tuple(
                (version, checksum, timestamp)
                for version, checksum in enumerate(checksums, start=1)
            ),
        )
        connection.execute(
            "INSERT INTO installations VALUES (?,?,?)",
            (installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO projects(
                project_id,installation_id,provider,created_at
            ) VALUES (?,?,?,?)
            """,
            (project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id,installation_id,project_id,provider,
                provider_version,adapter_version,source_schema_version,
                started_at,ended_at,terminal_state,events_complete,
                created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
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
                "completed",
                1,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO analysis_jobs(
                job_id,dedupe_key,kind,provider,project_id,session_id,
                input_fingerprint,provenance_fingerprint,
                estimator_plan_version,redactor_version,
                provider_schema_version,automation_grant_id,local_only,state,
                stage_number,progress_completed,progress_total,attempt_count,
                max_attempts,available_at,cancel_requested,lease_owner,
                lease_token,lease_expires_at,last_error_code,
                terminal_reason_code,created_at,updated_at,terminal_at
            ) VALUES (?,?, 'session_quality','synthetic',?,?,?,?,?,?,?,NULL,1,
                      'queued',NULL,0,1,0,3,?,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL)
            """,
            (
                job_id,
                digest("v23-dedupe"),
                project_id,
                session_id,
                digest("v23-input"),
                digest("v23-provenance"),
                "synthetic-plan-v1",
                "synthetic-redactor-v1",
                "synthetic-schema-v1",
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO analysis_job_metrics VALUES (?,?,0)",
            (job_id, "prompt.goal_cue_coverage"),
        )
        connection.execute("PRAGMA user_version=23")
        connection.commit()

    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in rows) == tuple(range(1, 62))
        assert tuple(row[1] for row in rows[:23]) == checksums
        assert rows[23][1] == hashlib.sha256(
            migrations.MIGRATION_24.encode("utf-8")
        ).hexdigest()
        assert rows[24][1] == hashlib.sha256(
            migrations.MIGRATION_25.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            "SELECT kind,state FROM analysis_jobs WHERE job_id=?", (job_id,)
        ).fetchone() == ("session_quality", "queued")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
