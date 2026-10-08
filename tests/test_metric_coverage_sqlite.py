from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    COACHING_METRIC_RUBRIC_VERSION,
)
from prompt_enhancer.application.analysis.metric_coverage import (
    MetricCoverageProjectNotFoundError,
    MetricCoverageScope,
    MetricCoverageSelection,
)
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
)
from prompt_enhancer.application.persistence import (
    MetricValueState,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
    SafeSession,
    SessionState,
)
from prompt_enhancer.infrastructure.sqlite.metric_coverage import (
    SqliteMetricCoverageRepository,
)


NOW = datetime(2047, 6, 7, 8, 9, tzinfo=UTC)
INSTALLATION_ID = "1" * 64
PROJECT_ID = "2" * 64
METRIC = next(
    item
    for item in COACHING_METRIC_DEFINITIONS
    if item.key == "prompt.context_sufficiency"
)


def _session(ordinal: int) -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id=INSTALLATION_ID,
        project_id=PROJECT_ID,
        session_id=f"{100 + ordinal:064x}",
        provider_version="0.144.5",
        adapter_version="codex-app-server-v1",
        source_schema_version="codex-consumed-schema-v1",
        started_at=NOW - timedelta(hours=ordinal + 2),
        ended_at=NOW - timedelta(hours=ordinal + 1),
        terminal_state=SessionState.COMPLETED,
        events_complete=True,
    )


def _draft(session: SafeSession, ordinal: int) -> SessionAnalysisRunDraft:
    return SessionAnalysisRunDraft(
        run_id=f"{1000 + ordinal:064x}",
        session_id=session.session_id,
        request_fingerprint=f"{2000 + ordinal:064x}",
        input_fingerprint=f"{3000 + ordinal:064x}",
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=(METRIC.key,),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_policy_version="synthetic-consent-v1",
        provider=Provider.CODEX,
        provider_version=session.provider_version,
        adapter_version=session.adapter_version,
        source_schema_version=session.source_schema_version,
        content_schema_version="redacted-message-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint=f"{4000 + ordinal:064x}",
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        started_at=NOW - timedelta(minutes=10 - ordinal),
    )


def _result(
    state: MetricValueState = MetricValueState.KNOWN,
    *,
    version: int | None = None,
    metric_schema_version: int = 2,
) -> SessionAnalysisResultRecord:
    known = state is MetricValueState.KNOWN
    not_applicable = state is MetricValueState.NOT_APPLICABLE
    execution_error = state is MetricValueState.EXECUTION_ERROR
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=METRIC.key,
            version=METRIC.version if version is None else version,
            numeric_value=0.5 if known else None,
            unit=METRIC.unit,
            source=MetricSource.DETERMINISTIC,
            observed_count=1 if known else 0,
            eligible_count=2,
            coverage=0.5 if known else 0.0,
        ),
        value_state=state,
        direction=SessionMetricDirection(METRIC.direction.value),
        applicability=(
            SessionMetricApplicability.NOT_APPLICABLE
            if not_applicable
            else SessionMetricApplicability.APPLICABLE
        ),
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=metric_schema_version,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=1 if known else None,
        fraction_denominator=2 if known else None,
        explanation_code=f"synthetic_{state.value}",
        error_code="synthetic_execution_error" if execution_error else None,
        algorithm_id=COACHING_METRIC_ALGORITHM_ID,
        algorithm_version=COACHING_METRIC_ALGORITHM_VERSION,
        rubric_version=COACHING_METRIC_RUBRIC_VERSION,
        computed_at=NOW - timedelta(minutes=5),
    )


def _repository(database: Database) -> SqliteMetricCoverageRepository:
    return SqliteMetricCoverageRepository(
        database._connection, database._ensure_initialized
    )


def test_empty_local_index_is_exact_but_provider_history_remains_out_of_scope(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )

    assert snapshot.indexed_project_count == 0
    assert snapshot.indexed_session_count == 0
    assert snapshot.latest_profile_runs.never_run == 0
    assert len(snapshot.metrics) == 20
    assert all(item.latest_completed_run_count == 0 for item in snapshot.metrics)


def test_latest_profile_selection_results_and_automation_are_counted_exactly(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    sessions = tuple(_session(ordinal) for ordinal in range(4))
    for session in sessions:
        database.persist_session(session, ())
    runs = database.session_analysis_run_repository()

    completed = _draft(sessions[0], 0)
    running = _draft(sessions[1], 1)
    failed = _draft(sessions[2], 2)
    runs.begin(completed)
    runs.complete(
        completed.run_id,
        (_result(),),
        finished_at=NOW - timedelta(minutes=4),
    )
    runs.begin(running)
    runs.begin(failed)
    runs.fail(
        failed.run_id,
        finished_at=NOW - timedelta(minutes=2),
        failure_code="synthetic_failure",
    )

    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id="a" * 64,
            scope=AutomationGrantScope(
                provider=Provider.CODEX,
                project_id=PROJECT_ID,
                metric_keys=(METRIC.key,),
            ),
            created_at=NOW - timedelta(days=1),
            expires_at=(NOW - timedelta(days=1)) + AUTOMATION_GRANT_LIFETIME,
        )
    )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    by_key = {item.metric_key: item for item in snapshot.metrics}
    measured = by_key[METRIC.key]
    omitted = next(
        item
        for item in snapshot.metrics
        if item.metric_key != METRIC.key
    )

    assert snapshot.indexed_project_count == 1
    assert snapshot.indexed_session_count == 4
    assert snapshot.latest_profile_runs.model_dump() == {
        "completed": 1,
        "running": 1,
        "failed": 1,
        "never_run": 1,
    }
    assert snapshot.latest_completed_snapshot_count == 1
    assert measured.selected_run_count == 1
    assert measured.completed_selected_run_count == 1
    assert measured.contract_compatible_result_states.known == 1
    assert measured.contract_incompatible_result_count == 0
    assert measured.expected_result_absent_count == 0
    assert measured.compatible_provenance_cohort_count == 1
    assert omitted.selected_run_count == 0
    assert omitted.not_selected_run_count == 1
    assert snapshot.effective_automation_grant_count == 1
    assert snapshot.effective_automation_project_count == 1
    assert measured.effective_automation_selected_project_count == 1
    assert omitted.effective_automation_selected_project_count == 0


def test_project_scope_requires_an_exact_provider_project(tmp_path) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    database.persist_session(_session(0), ())
    repository = _repository(database)

    project = repository.snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.ONE_PROJECT,
            project_id=PROJECT_ID,
        ),
        generated_at=NOW,
    )
    assert project.scope is MetricCoverageScope.ONE_PROJECT
    assert project.indexed_project_count == 1
    assert project.indexed_session_count == 1

    with pytest.raises(MetricCoverageProjectNotFoundError):
        repository.snapshot(
            MetricCoverageSelection(
                provider=Provider.CODEX,
                scope=MetricCoverageScope.ONE_PROJECT,
                project_id="f" * 64,
            ),
            generated_at=NOW,
        )


def test_expired_grant_boundary_is_not_reported_as_effective(tmp_path) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    database.persist_session(_session(0), ())
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id="b" * 64,
            scope=AutomationGrantScope(
                provider=Provider.CODEX,
                project_id=PROJECT_ID,
                metric_keys=(METRIC.key,),
            ),
            created_at=NOW - AUTOMATION_GRANT_LIFETIME,
            expires_at=NOW,
        )
    )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    assert snapshot.effective_automation_grant_count == 0
    assert snapshot.effective_automation_project_count == 0
    assert all(
        item.effective_automation_selected_project_count == 0
        for item in snapshot.metrics
    )


def test_all_persisted_value_states_and_wrong_definition_version_stay_distinct(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    runs = database.session_analysis_run_repository()
    states = tuple(MetricValueState)
    for ordinal, state in enumerate(states):
        session = _session(ordinal)
        database.persist_session(session, ())
        draft = _draft(session, ordinal)
        runs.begin(draft)
        runs.complete(
            draft.run_id,
            (_result(state),),
            finished_at=NOW - timedelta(minutes=1),
        )

    wrong_session = _session(len(states))
    database.persist_session(wrong_session, ())
    with database._connection() as connection:
        connection.execute(
            """
            INSERT INTO metric_definitions(
                key, version, dimension, display_name, description, unit,
                source, algorithm_version, definition_checksum
            ) VALUES (?, 1, ?, ?, ?, ?, 'deterministic', ?, ?)
            """,
            (
                METRIC.key,
                METRIC.dimension,
                METRIC.display_name,
                "Reserved synthetic prior definition for coverage integrity.",
                METRIC.unit,
                COACHING_METRIC_ALGORITHM_VERSION,
                "e" * 64,
            ),
        )
        connection.commit()
    wrong_draft = _draft(wrong_session, len(states))
    runs.begin(wrong_draft)
    runs.complete(
        wrong_draft.run_id,
        (_result(version=1),),
        finished_at=NOW - timedelta(seconds=30),
    )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    measured = next(
        item for item in snapshot.metrics if item.metric_key == METRIC.key
    )

    assert measured.completed_selected_run_count == len(states) + 1
    assert measured.contract_compatible_result_states.model_dump() == {
        "known": 1,
        "unknown": 1,
        "not_applicable": 1,
        "abstained": 1,
        "execution_error": 1,
    }
    assert measured.contract_incompatible_result_count == 1
    assert measured.expected_result_absent_count == 0
    assert measured.compatible_provenance_cohort_count == 1


def test_newer_failed_attempt_does_not_erase_older_completed_snapshot(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    session = _session(0)
    database.persist_session(session, ())
    runs = database.session_analysis_run_repository()
    completed = _draft(session, 0)
    newer_failed = _draft(session, 1)
    runs.begin(completed)
    runs.complete(
        completed.run_id,
        (_result(),),
        finished_at=NOW - timedelta(minutes=5),
    )
    runs.begin(newer_failed)
    runs.fail(
        newer_failed.run_id,
        finished_at=NOW - timedelta(minutes=1),
        failure_code="synthetic_retry_failed",
    )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    measured = next(
        item for item in snapshot.metrics if item.metric_key == METRIC.key
    )

    assert snapshot.latest_profile_runs.model_dump() == {
        "completed": 0,
        "running": 0,
        "failed": 1,
        "never_run": 0,
    }
    assert snapshot.latest_completed_snapshot_count == 1
    assert measured.latest_completed_run_count == 1
    assert measured.selected_run_count == 1
    assert measured.contract_compatible_result_states.known == 1


def test_current_definition_with_wrong_metric_schema_is_contract_incompatible(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    runs = database.session_analysis_run_repository()
    compatible_session = _session(0)
    incompatible_session = _session(1)
    for ordinal, session in enumerate((compatible_session, incompatible_session)):
        database.persist_session(session, ())
        draft = _draft(session, ordinal)
        runs.begin(draft)
        runs.complete(
            draft.run_id,
            (
                _result(
                    metric_schema_version=2 if ordinal == 0 else 3,
                ),
            ),
            finished_at=NOW - timedelta(minutes=1),
        )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    measured = next(
        item for item in snapshot.metrics if item.metric_key == METRIC.key
    )

    assert measured.completed_selected_run_count == 2
    assert measured.contract_compatible_result_states.model_dump() == {
        "known": 1,
        "unknown": 0,
        "not_applicable": 0,
        "abstained": 0,
        "execution_error": 0,
    }
    assert measured.contract_incompatible_result_count == 1
    assert measured.expected_result_absent_count == 0
    assert (
        measured.contract_compatible_result_states.total
        + measured.contract_incompatible_result_count
        + measured.expected_result_absent_count
        == measured.completed_selected_run_count
    )


def test_contract_valid_results_preserve_distinct_provenance_cohorts(
    tmp_path,
) -> None:
    database = Database(tmp_path / "coverage.sqlite3")
    database.initialize()
    runs = database.session_analysis_run_repository()
    for ordinal, provider_version in enumerate(("0.144.5", "0.145.0")):
        session = _session(ordinal).model_copy(
            update={"provider_version": provider_version}
        )
        database.persist_session(session, ())
        draft = _draft(session, ordinal)
        runs.begin(draft)
        runs.complete(
            draft.run_id,
            (_result(),),
            finished_at=NOW - timedelta(minutes=1),
        )

    snapshot = _repository(database).snapshot(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        ),
        generated_at=NOW,
    )
    measured = next(
        item for item in snapshot.metrics if item.metric_key == METRIC.key
    )

    assert measured.completed_selected_run_count == 2
    assert measured.contract_compatible_result_states.known == 2
    assert measured.contract_incompatible_result_count == 0
    assert measured.expected_result_absent_count == 0
    assert measured.compatible_provenance_cohort_count == 2
