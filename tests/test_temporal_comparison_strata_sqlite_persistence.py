from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.history.coaching_identity import (
    COACHING_TEMPORAL_PROFILE_KEY,
    COACHING_TEMPORAL_PROFILE_VERSION,
)
from prompt_enhancer.application.history.comparison_strata import (
    _AutomationComparisonLeaseAuthorityV1,
)
from prompt_enhancer.application.history.contracts import (
    AnalysisInputReceiptV2,
    TemporalWindowKind,
    TemporalWindowSpec,
)
from prompt_enhancer.application.history.persistence import (
    SyntheticTemporalCompletionRequestV1,
)
from prompt_enhancer.application.persistence import (
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    DecisionAction,
    DecisionRevisionLink,
    DecisionRevisionRole,
    SessionAnalysisRunDraft,
    SessionMetricScopeState,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from prompt_enhancer.database import (
    Database,
    DatabaseInvariantError,
    SCHEMA_VERSION,
    _MIGRATION_1,
)
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.temporal_history import (
    ANALYSIS_RUN_BRIDGE_VERSION,
    analysis_run_bridge_fingerprint,
)
from prompt_enhancer.privacy import Pseudonymizer
from tests.test_temporal_history_sqlite_persistence import (
    BASE,
    _completion_fixture,
    _id,
)


def _comparison_ready_context(tmp_path: Path) -> SimpleNamespace:
    context = _completion_fixture(tmp_path, bind_publication=False)
    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    context.database.configure_local_artifact_id_factory(identifiers)
    # The synthetic v21 fixture predates the comparison requirement that the
    # stored session source schema equal the job's provider-schema authority.
    with context.database._connection() as connection:
        connection.execute(
            "UPDATE sessions SET source_schema_version=? WHERE session_id=?",
            ("synthetic-provider-schema-v1", context.session_id),
        )
        connection.commit()
    context.__dict__.update(identifiers=identifiers)
    return context


def _comparison_preparation(tmp_path: Path) -> SimpleNamespace:
    context = _comparison_ready_context(tmp_path)
    identifiers = context.identifiers
    comparison = context.database.temporal_comparison_stratum_repository()
    prepared_at = BASE + timedelta(minutes=2, seconds=20)
    comparison._clock = lambda: prepared_at
    authority = _AutomationComparisonLeaseAuthorityV1(
        job_id=context.authority.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=context.authority.lease_owner,
        lease_token=context.authority.lease_token,
    )
    prepared = comparison.prepare_automation_stratum(
        context.scope.prepared_scope_id,
        authority=authority,
    )
    context.__dict__.update(
        identifiers=identifiers,
        comparison=comparison,
        comparison_authority=authority,
        comparison_prepared_at=prepared_at,
        prepared=prepared,
    )
    return context


def _append_reviewed_task(context: SimpleNamespace, role: str) -> TaskRevisionRecord:
    revision = TaskRevisionRecord(
        task_id=_id(f"comparison-task-{role}"),
        revision=1,
        project_id=context.project_id,
        task_type="bug_fix",
        lifecycle_state="confirmed",
        session_ids=(context.session_id,),
        input_fingerprint=_id(f"comparison-task-input-{role}"),
        created_at=BASE + timedelta(minutes=2, seconds=15),
    )
    context.database.task_repository().append_revision(revision)
    return revision


def _comparison_completion(tmp_path: Path) -> SimpleNamespace:
    context = _comparison_preparation(tmp_path)
    prepared = context.prepared
    finished_at = BASE + timedelta(minutes=3)
    request_fingerprint = _id("comparison-run-request")
    input_fingerprint = _id("comparison-run-input")
    analysis_window_fingerprint = _id("comparison-window")
    model_plan_fingerprint = _id("comparison-model-plan")
    run_fingerprint = analysis_run_bridge_fingerprint(
        request_fingerprint=request_fingerprint,
        input_fingerprint=input_fingerprint,
        analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
        analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=(context.metric_key,),
        provider="synthetic",
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-provider-schema-v1",
        content_schema_version="synthetic-content-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint=model_plan_fingerprint,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        analysis_window_fingerprint=analysis_window_fingerprint,
    )
    input_values = context.request.analysis_input.model_dump(mode="python")
    input_values.update(
        input_receipt_id=_id("comparison-input-receipt"),
        analysis_run_id=prepared.expected_analysis_run_id,
        analysis_run_fingerprint=run_fingerprint,
        analysis_run_fingerprint_version=ANALYSIS_RUN_BRIDGE_VERSION,
        analysis_run_request_fingerprint=request_fingerprint,
        analysis_window_fingerprint=analysis_window_fingerprint,
        provider_schema_version="synthetic-provider-schema-v1",
        source_schema_version="synthetic-provider-schema-v1",
        model_plan_fingerprint=model_plan_fingerprint,
        analysis_run_completed_at=finished_at,
        captured_at=finished_at,
    )
    analysis_input = AnalysisInputReceiptV2.model_validate(input_values)
    temporal_request = SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("comparison-completion-request"),
        prepared_scope=context.scope,
        analysis_input=analysis_input,
        analysis_run_id=prepared.expected_analysis_run_id,
    )
    runs = context.database.session_analysis_run_repository()
    assert runs._temporal_history_repository is not None
    assert runs._temporal_comparison_repository is not None
    runs._temporal_history_repository._clock = lambda: BASE + timedelta(minutes=4)
    runs._temporal_comparison_repository._clock = (
        lambda: BASE + timedelta(minutes=4, seconds=1)
    )
    runs.begin(
        SessionAnalysisRunDraft(
            run_id=prepared.expected_analysis_run_id,
            session_id=context.session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=input_fingerprint,
            analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
            analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
            metric_pack_key=COACHING_METRIC_PACK_KEY,
            metric_pack_version=COACHING_METRIC_PACK_VERSION,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=(context.metric_key,),
            data_tier=DataTier.REDACTED_CONTENT,
            consent_policy_version="synthetic-consent-v1",
            provider=Provider.SYNTHETIC,
            provider_version="synthetic-provider-v1",
            adapter_version="synthetic-adapter-v1",
            source_schema_version="synthetic-provider-schema-v1",
            content_schema_version="synthetic-content-v1",
            metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
            redactor_version="synthetic-redactor-v1",
            model_plan_fingerprint=model_plan_fingerprint,
            schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
            started_at=BASE + timedelta(minutes=2, seconds=30),
        ),
        completion_authority=context.authority,
    )
    result = context.result.model_copy(update={"computed_at": finished_at})
    context.__dict__.update(
        runs=runs,
        finished_at=finished_at,
        result=result,
        temporal_request=temporal_request,
    )
    return context


def test_v22_schema_is_zero_backfill_normalized_and_transient(tmp_path) -> None:
    path = tmp_path / "synthetic-v21.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 22)
    )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,
                   checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL)"""
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            (
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    BASE.isoformat(timespec="microseconds"),
                )
                for version, script in enumerate(scripts, start=1)
            ),
        )
        connection.execute("PRAGMA user_version=21")
        connection.commit()
    database = Database(path)
    database.initialize()
    assert SCHEMA_VERSION == 61
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        tables = tuple(
            str(row["name"])
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'comparison_%'
                   ORDER BY name"""
            )
        )
        assert tables
        for table in tables:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            assert all(str(column["type"]).upper() != "BLOB" for column in columns)
            assert not {"json", "payload", "content", "prompt", "path", "uri"} & {
                str(column["name"]).lower() for column in columns
            }
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        for transient in (
            "comparison_prepare_append_authorizations",
            "comparison_seal_append_authorizations",
        ):
            assert connection.execute(
                f"PRAGMA foreign_key_list({transient})"
            ).fetchall() == []


def test_prepare_is_keyed_exact_idempotent_and_concurrent(tmp_path) -> None:
    context = _comparison_preparation(tmp_path)
    prepared = context.prepared
    assert prepared.expected_analysis_run_id == context.identifiers.session_analysis_run_id(
        f"automation-{prepared.analysis_job.job_id}",
        Provider.SYNTHETIC,
        context.session_id,
        COACHING_METRIC_PACK_KEY,
        COACHING_METRIC_PACK_VERSION,
    )
    assert context.comparison.get_prepared_stratum(prepared.prepared_stratum_id) == prepared
    context.comparison._clock = lambda: BASE + timedelta(days=1)

    def replay() -> object:
        return context.comparison.prepare_automation_stratum(
            context.scope.prepared_scope_id,
            authority=context.comparison_authority,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = tuple(executor.map(lambda _: replay(), range(8)))
    assert all(item == prepared for item in receipts)
    with context.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_prepared_stratum_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_prepare_append_authorizations"
        ).fetchone()[0] == 0


def test_task_query_is_latest_before_membership_and_max_plus_one(tmp_path) -> None:
    context = _comparison_ready_context(tmp_path)
    target = context.database.get_session(context.session_id)
    assert target is not None
    other_session_id = _id("comparison-other-session")
    context.database.persist_session(
        target.model_copy(update={"session_id": other_session_id}),
        (),
    )
    cutoff = BASE + timedelta(minutes=2, seconds=20)
    tasks = context.database.task_repository()
    first_task_id = _id("comparison-membership-before-latest")
    tasks.append_revision(
        TaskRevisionRecord(
            task_id=first_task_id,
            revision=1,
            project_id=context.project_id,
            task_type="bug_fix",
            lifecycle_state="confirmed",
            session_ids=(context.session_id,),
            input_fingerprint=_id("comparison-task-a1"),
            created_at=cutoff - timedelta(seconds=3),
        )
    )
    tasks.append_revision(
        TaskRevisionRecord(
            task_id=first_task_id,
            revision=2,
            project_id=context.project_id,
            task_type="bug_fix",
            lifecycle_state="confirmed",
            session_ids=(other_session_id,),
            input_fingerprint=_id("comparison-task-a2"),
            created_at=cutoff - timedelta(seconds=2),
        )
    )
    second_task_id = _id("comparison-post-cutoff-latest")
    tasks.append_revision(
        TaskRevisionRecord(
            task_id=second_task_id,
            revision=1,
            project_id=context.project_id,
            task_type="bug_fix",
            lifecycle_state="confirmed",
            session_ids=(context.session_id,),
            input_fingerprint=_id("comparison-task-b1"),
            created_at=cutoff - timedelta(seconds=1),
        )
    )
    tasks.append_revision(
        TaskRevisionRecord(
            task_id=second_task_id,
            revision=2,
            project_id=context.project_id,
            task_type="bug_fix",
            lifecycle_state="confirmed",
            session_ids=(context.session_id,),
            input_fingerprint=_id("comparison-task-b2"),
            created_at=cutoff + timedelta(seconds=1),
        )
    )
    comparison = context.database.temporal_comparison_stratum_repository()
    comparison._clock = lambda: cutoff
    authority = _AutomationComparisonLeaseAuthorityV1(
        job_id=context.authority.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=context.authority.lease_owner,
        lease_token=context.authority.lease_token,
    )
    prepared = comparison.prepare_automation_stratum(
        context.scope.prepared_scope_id,
        authority=authority,
    )
    assert tuple(
        (item.task_id, item.revision)
        for item in prepared.dimensions.task_manifest.current_revisions
    ) == ((second_task_id, 1),)

    overflow_dir = tmp_path / "overflow"
    overflow_dir.mkdir()
    overflow = _comparison_ready_context(overflow_dir)
    overflow_tasks = overflow.database.task_repository()
    for index in range(101):
        overflow_tasks.append_revision(
            TaskRevisionRecord(
                task_id=hashlib.sha256(
                    f"synthetic-comparison-overflow:{index}".encode("ascii")
                ).hexdigest(),
                revision=1,
                project_id=overflow.project_id,
                task_type="bug_fix",
                lifecycle_state="confirmed",
                session_ids=(overflow.session_id,),
                input_fingerprint=hashlib.sha256(
                    f"synthetic-comparison-input:{index}".encode("ascii")
                ).hexdigest(),
                created_at=cutoff - timedelta(seconds=1),
            )
        )
    overflow_repository = (
        overflow.database.temporal_comparison_stratum_repository()
    )
    overflow_repository._clock = lambda: cutoff
    with pytest.raises(DatabaseInvariantError):
        overflow_repository.prepare_automation_stratum(
            overflow.scope.prepared_scope_id,
            authority=_AutomationComparisonLeaseAuthorityV1(
                job_id=overflow.authority.job_id,
                automation_grant_id=overflow.grant_id,
                lease_owner=overflow.authority.lease_owner,
                lease_token=overflow.authority.lease_token,
            ),
        )
    assert overflow_repository.get_prepared_stratum_for_job(
        overflow.authority.job_id
    ) is None


def test_completion_seals_atomically_replays_and_privacy_deletes(tmp_path) -> None:
    context = _comparison_completion(tmp_path)
    batch = context.runs.complete(
        context.prepared.expected_analysis_run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.temporal_request,
    )
    assert batch is not None
    sealed = context.comparison.get_sealed_stratum_for_run(
        context.prepared.expected_analysis_run_id
    )
    assert sealed is not None
    assert sealed.sealed_batch == batch
    assert len(sealed.ordered_authority_fingerprints) == 12
    # Replay is a read-equivalent check and does not consult current lease time.
    context.comparison._clock = lambda: BASE + timedelta(days=40)
    assert context.runs.complete(
        context.prepared.expected_analysis_run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.temporal_request,
    ) == batch
    assert context.comparison.seal_automation_stratum(
        context.prepared.prepared_stratum_id,
        batch.sealed_batch_id,
        authority=context.comparison_authority,
    ) == sealed
    assert context.runs.delete_for_privacy(
        context.prepared.expected_analysis_run_id
    ) is True
    with context.database._connection(readonly=True) as connection:
        for table in (
            "comparison_prepared_stratum_roots",
            "comparison_prepared_task_projections",
            "comparison_prepared_graph_commitments",
            "comparison_automation_revalidations",
            "comparison_seal_authority_commitments",
            "comparison_sealed_stratum_roots",
            "comparison_prepare_append_authorizations",
            "comparison_seal_append_authorizations",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_prepared_only_privacy_deletion_removes_the_entire_graph(tmp_path) -> None:
    context = _comparison_preparation(tmp_path)
    assert context.runs.delete_for_privacy(
        context.prepared.expected_analysis_run_id
    ) is True
    assert context.comparison.get_prepared_stratum(
        context.prepared.prepared_stratum_id
    ) is None
    with context.database._connection(readonly=True) as connection:
        for table in (
            "comparison_prepared_stratum_roots",
            "comparison_prepared_task_projections",
            "comparison_prepared_graph_commitments",
            "comparison_prepare_append_authorizations",
            "temporal_run_delete_authorizations",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_running_expected_run_replace_recursive_off_preserves_graph(tmp_path) -> None:
    context = _comparison_completion(tmp_path)
    run_id = context.prepared.expected_analysis_run_id
    with context.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("PRAGMA recursive_triggers=OFF")
        before = (
            connection.execute(
                "SELECT COUNT(*) FROM session_analysis_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM session_analysis_run_metrics WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            connection.execute(
                """SELECT COUNT(*) FROM comparison_prepared_stratum_roots
                   WHERE expected_analysis_run_id=?""",
                (run_id,),
            ).fetchone()[0],
        )
        assert before == (1, 1, 1)
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """INSERT OR REPLACE INTO session_analysis_runs
                   SELECT * FROM session_analysis_runs WHERE run_id=?""",
                (run_id,),
            )
        connection.rollback()
        after = (
            connection.execute(
                "SELECT COUNT(*) FROM session_analysis_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            connection.execute(
                "SELECT COUNT(*) FROM session_analysis_run_metrics WHERE run_id=?",
                (run_id,),
            ).fetchone()[0],
            connection.execute(
                """SELECT COUNT(*) FROM comparison_prepared_stratum_roots
                   WHERE expected_analysis_run_id=?""",
                (run_id,),
            ).fetchone()[0],
        )
        assert after == before


def test_raw_terminal_mutation_replace_and_late_public_seal_fail_closed(
    tmp_path,
) -> None:
    context = _comparison_completion(tmp_path)
    with context.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """UPDATE session_analysis_runs
                   SET status='completed',finished_at=? WHERE run_id=?""",
                (
                    context.finished_at.isoformat(timespec="microseconds"),
                    context.prepared.expected_analysis_run_id,
                ),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """INSERT OR REPLACE INTO comparison_prepared_stratum_roots
                   SELECT * FROM comparison_prepared_stratum_roots
                   WHERE prepared_stratum_id=?""",
                (context.prepared.prepared_stratum_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """UPDATE comparison_prepared_stratum_roots
                   SET contract_version=contract_version
                   WHERE prepared_stratum_id=?""",
                (context.prepared.prepared_stratum_id,),
            )
        connection.rollback()
    with pytest.raises(DatabaseInvariantError):
        context.comparison.seal_automation_stratum(
            context.prepared.prepared_stratum_id,
            _id("nonexistent-sealed-batch"),
            authority=context.comparison_authority,
        )


def _assert_failed_completion_left_only_preparation(context: SimpleNamespace) -> None:
    with context.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT status FROM session_analysis_runs WHERE run_id=?",
            (context.prepared.expected_analysis_run_id,),
        ).fetchone()[0] == "running"
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_results WHERE run_id=?",
            (context.prepared.expected_analysis_run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_completion_requests WHERE analysis_run_id=?",
            (context.prepared.expected_analysis_run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_prepared_stratum_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_sealed_stratum_roots"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_seal_append_authorizations"
        ).fetchone()[0] == 0
    assert context.database._comparison_seal_authorizations == set()


def test_seal_faults_before_and_after_terminal_update_roll_back(tmp_path) -> None:
    terminal_dir = tmp_path / "terminal-fault"
    terminal_dir.mkdir()
    terminal = _comparison_completion(terminal_dir)
    run_id = terminal.prepared.expected_analysis_run_id
    with terminal.database._connection() as connection:
        connection.execute(
            f"""CREATE TRIGGER synthetic_comparison_terminal_fault
                BEFORE UPDATE OF status ON session_analysis_runs
                WHEN NEW.run_id='{run_id}' AND NEW.status='completed'
                BEGIN SELECT RAISE(ABORT,'synthetic terminal fault'); END"""
        )
        connection.commit()
    with pytest.raises(Exception):
        terminal.runs.complete(
            run_id,
            (terminal.result,),
            finished_at=terminal.finished_at,
            completion_authority=terminal.authority,
            temporal_completion_request=terminal.temporal_request,
        )
    _assert_failed_completion_left_only_preparation(terminal)
    with terminal.database._connection() as connection:
        connection.execute("DROP TRIGGER synthetic_comparison_terminal_fault")
        connection.commit()
    assert terminal.runs.complete(
        run_id,
        (terminal.result,),
        finished_at=terminal.finished_at,
        completion_authority=terminal.authority,
        temporal_completion_request=terminal.temporal_request,
    ) is not None

    commit_dir = tmp_path / "root-fault"
    commit_dir.mkdir()
    commit = _comparison_completion(commit_dir)
    comparison = commit.runs._temporal_comparison_repository
    assert comparison is not None
    exact_commit = comparison._commit_completion_seal_locked

    def fail_after_terminal(*_args: object, **_kwargs: object) -> None:
        raise DatabaseInvariantError("synthetic root fault")

    comparison._commit_completion_seal_locked = fail_after_terminal  # type: ignore[method-assign]
    with pytest.raises(DatabaseInvariantError):
        commit.runs.complete(
            commit.prepared.expected_analysis_run_id,
            (commit.result,),
            finished_at=commit.finished_at,
            completion_authority=commit.authority,
            temporal_completion_request=commit.temporal_request,
        )
    _assert_failed_completion_left_only_preparation(commit)
    comparison._commit_completion_seal_locked = exact_commit  # type: ignore[method-assign]
    assert commit.runs.complete(
        commit.prepared.expected_analysis_run_id,
        (commit.result,),
        finished_at=commit.finished_at,
        completion_authority=commit.authority,
        temporal_completion_request=commit.temporal_request,
    ) is not None


def test_transient_authorization_cannot_be_reused_for_altered_lineage(
    tmp_path,
) -> None:
    database = Database(tmp_path / "synthetic-authorization.sqlite3")
    database.initialize()
    values = tuple(_id(f"prepare-auth-{index}") for index in range(8))
    operation_id, tag = database._begin_comparison_prepare_authorization(*values)
    authorization_fingerprint = values[-1]
    try:
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                """INSERT INTO comparison_prepare_append_authorizations
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, *values, tag),
            )
            connection.execute(
                """DELETE FROM comparison_prepare_append_authorizations
                   WHERE operation_id=?""",
                (operation_id,),
            )
            altered = list(values)
            altered[3] = _id("altered-prepared-stratum")
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute(
                    """INSERT INTO comparison_prepare_append_authorizations
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (operation_id, *altered, tag),
                )
            connection.rollback()
    finally:
        database._end_comparison_prepare_authorization(
            operation_id,
            authorization_fingerprint,
            tag,
        )
    assert database._comparison_prepare_authorizations == set()


def test_raw_child_writes_and_deletes_fail_with_recursive_triggers_off(
    tmp_path,
) -> None:
    context = _comparison_preparation(tmp_path)
    prepared_id = context.prepared.prepared_stratum_id
    run_id = context.prepared.expected_analysis_run_id
    with context.database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("PRAGMA recursive_triggers=OFF")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """INSERT INTO comparison_prepared_graph_commitments(
                       prepared_stratum_id,operation_id,
                       expected_analysis_run_id,ordinal,fingerprint)
                   VALUES(?,?,?,?,?)""",
                (prepared_id, _id("raw-operation"), run_id, 111, _id("raw-child")),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """DELETE FROM comparison_prepared_graph_commitments
                   WHERE prepared_stratum_id=? AND ordinal=0""",
                (prepared_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                """INSERT OR REPLACE INTO comparison_prepared_graph_commitments
                   SELECT * FROM comparison_prepared_graph_commitments
                   WHERE prepared_stratum_id=? AND ordinal=0""",
                (prepared_id,),
            )
        connection.rollback()


def test_task_privacy_deletes_prepared_graph_and_absent_retry_checkpoints(
    tmp_path,
) -> None:
    context = _comparison_ready_context(tmp_path)
    revision = _append_reviewed_task(context, "prepared-privacy")
    comparison = context.database.temporal_comparison_stratum_repository()
    comparison._clock = lambda: BASE + timedelta(minutes=2, seconds=20)
    authority = _AutomationComparisonLeaseAuthorityV1(
        job_id=context.authority.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=context.authority.lease_owner,
        lease_token=context.authority.lease_token,
    )
    prepared = comparison.prepare_automation_stratum(
        context.scope.prepared_scope_id,
        authority=authority,
    )
    assert prepared.dimensions.task_manifest.current_revisions[0].task_id == revision.task_id
    tasks = context.database.task_repository()
    assert tasks.delete_task_for_privacy(revision.task_id) is True
    assert tasks.delete_task_for_privacy(revision.task_id) is False
    assert comparison.get_prepared_stratum(prepared.prepared_stratum_id) is None
    assert context.database.get_session(context.session_id) is not None
    with context.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM comparison_task_delete_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[1:] == (0, 0)
    assert context.database._comparison_task_delete_authorizations == set()


def test_task_privacy_deletes_sealed_graph_but_preserves_run_and_temporal(
    tmp_path,
) -> None:
    context = _comparison_ready_context(tmp_path)
    revision = _append_reviewed_task(context, "sealed-privacy")
    # Reuse the completion builder after inserting the reviewed task by
    # performing its remaining steps against this exact context.
    comparison = context.database.temporal_comparison_stratum_repository()
    comparison._clock = lambda: BASE + timedelta(minutes=2, seconds=20)
    authority = _AutomationComparisonLeaseAuthorityV1(
        job_id=context.authority.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=context.authority.lease_owner,
        lease_token=context.authority.lease_token,
    )
    prepared = comparison.prepare_automation_stratum(
        context.scope.prepared_scope_id,
        authority=authority,
    )
    # Complete this exact prepared graph with synthetic run inputs.
    finished_at = BASE + timedelta(minutes=3)
    request_fingerprint = _id("sealed-task-run-request")
    input_fingerprint = _id("sealed-task-run-input")
    window = _id("sealed-task-window")
    model_plan = _id("sealed-task-model-plan")
    run_fingerprint = analysis_run_bridge_fingerprint(
        request_fingerprint=request_fingerprint,
        input_fingerprint=input_fingerprint,
        analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
        analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=(context.metric_key,),
        provider="synthetic",
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-provider-schema-v1",
        content_schema_version="synthetic-content-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint=model_plan,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        analysis_window_fingerprint=window,
    )
    input_values = context.request.analysis_input.model_dump(mode="python")
    input_values.update(
        input_receipt_id=_id("sealed-task-input-receipt"),
        analysis_run_id=prepared.expected_analysis_run_id,
        analysis_run_fingerprint=run_fingerprint,
        analysis_run_fingerprint_version=ANALYSIS_RUN_BRIDGE_VERSION,
        analysis_run_request_fingerprint=request_fingerprint,
        analysis_window_fingerprint=window,
        provider_schema_version="synthetic-provider-schema-v1",
        source_schema_version="synthetic-provider-schema-v1",
        model_plan_fingerprint=model_plan,
        analysis_run_completed_at=finished_at,
        captured_at=finished_at,
    )
    temporal_request = SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("sealed-task-completion-request"),
        prepared_scope=context.scope,
        analysis_input=AnalysisInputReceiptV2.model_validate(input_values),
        analysis_run_id=prepared.expected_analysis_run_id,
    )
    runs = context.database.session_analysis_run_repository()
    assert runs._temporal_history_repository is not None
    assert runs._temporal_comparison_repository is not None
    runs._temporal_history_repository._clock = lambda: BASE + timedelta(minutes=4)
    runs._temporal_comparison_repository._clock = lambda: BASE + timedelta(minutes=4, seconds=1)
    runs.begin(
        SessionAnalysisRunDraft(
            run_id=prepared.expected_analysis_run_id,
            session_id=context.session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=input_fingerprint,
            analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
            analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
            metric_pack_key=COACHING_METRIC_PACK_KEY,
            metric_pack_version=COACHING_METRIC_PACK_VERSION,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=(context.metric_key,),
            data_tier=DataTier.REDACTED_CONTENT,
            consent_policy_version="synthetic-consent-v1",
            provider=Provider.SYNTHETIC,
            provider_version="synthetic-provider-v1",
            adapter_version="synthetic-adapter-v1",
            source_schema_version="synthetic-provider-schema-v1",
            content_schema_version="synthetic-content-v1",
            metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
            redactor_version="synthetic-redactor-v1",
            model_plan_fingerprint=model_plan,
            schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
            started_at=BASE + timedelta(minutes=2, seconds=30),
        )
    )
    batch = runs.complete(
        prepared.expected_analysis_run_id,
        (context.result.model_copy(update={"computed_at": finished_at}),),
        finished_at=finished_at,
        completion_authority=context.authority,
        temporal_completion_request=temporal_request,
    )
    assert batch is not None
    sealed = comparison.get_sealed_stratum_for_run(
        prepared.expected_analysis_run_id
    )
    assert sealed is not None
    aggregation = (
        context.database.temporal_synthetic_aggregation_validation_repository()
    )
    aggregation._clock = lambda: sealed.sealed_at + timedelta(microseconds=1)
    validation = aggregation.validate_synthetic_aggregation(
        sealed.sealed_stratum_id,
        context.metric_key,
        TemporalWindowSpec(kind=TemporalWindowKind.LAST_N, last_n=3),
        idempotency_key_sha256=_id("sealed-task-aggregation-idempotency"),
    )
    assert context.database.task_repository().delete_task_for_privacy(
        revision.task_id
    ) is True
    assert aggregation.get_synthetic_aggregation_validation(
        validation.validation_receipt_id
    ) is None
    assert comparison.get_prepared_stratum(prepared.prepared_stratum_id) is None
    assert comparison.get_sealed_stratum_for_run(prepared.expected_analysis_run_id) is None
    assert runs.get(prepared.expected_analysis_run_id) is not None
    assert context.temporal.get_sealed_batch(batch.sealed_batch_id) == batch
    with context.database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM synthetic_aggregation_delete_authorizations"
        ).fetchone()[0] == 0


def test_candidate_privacy_expands_to_task_and_comparison_graph(tmp_path) -> None:
    context = _comparison_ready_context(tmp_path)
    revision = _append_reviewed_task(context, "candidate-component")
    candidate_id = _id("comparison-candidate")
    tasks = context.database.task_repository()
    tasks.add_candidate(
        TaskCandidateRecord(
            candidate_id=candidate_id,
            provider=Provider.SYNTHETIC,
            installation_id=context.installation_id,
            project_id=context.project_id,
            session_ids=(context.session_id,),
            signals=(),
            confidence=None,
            observed_count=0,
            eligible_count=1,
            coverage=0.0,
            discovery_version="synthetic-discovery-v1",
            input_fingerprint=_id("comparison-candidate-input"),
            created_at=BASE + timedelta(minutes=2, seconds=10),
        )
    )
    tasks.record_decision(
        TaskDecisionRecord(
            decision_id=_id("comparison-candidate-decision"),
            action=DecisionAction.ACCEPT,
            candidate_ids=(candidate_id,),
            revision_links=(
                DecisionRevisionLink(
                    task_id=revision.task_id,
                    revision=revision.revision,
                    role=DecisionRevisionRole.OUTPUT,
                ),
            ),
            decision_schema_version="synthetic-review-v1",
            decided_at=BASE + timedelta(minutes=2, seconds=18),
        )
    )
    comparison = context.database.temporal_comparison_stratum_repository()
    comparison._clock = lambda: BASE + timedelta(minutes=2, seconds=20)
    prepared = comparison.prepare_automation_stratum(
        context.scope.prepared_scope_id,
        authority=_AutomationComparisonLeaseAuthorityV1(
            job_id=context.authority.job_id,
            automation_grant_id=context.grant_id,
            lease_owner=context.authority.lease_owner,
            lease_token=context.authority.lease_token,
        ),
    )
    assert tasks.delete_candidate_for_privacy(candidate_id) is True
    assert tasks.get_revision(revision.task_id, revision.revision) is None
    assert comparison.get_prepared_stratum(prepared.prepared_stratum_id) is None


def test_migration_21_checksum_remains_exact(tmp_path) -> None:
    path = tmp_path / "synthetic-checksum.sqlite3"
    database = Database(path)
    database.initialize()
    expected = "de98c31d31b7be981e39ea72f2cbb111875fe7fd946460199ad8de7cd78173b9"
    assert hashlib.sha256(migrations.MIGRATION_21.encode("utf-8")).hexdigest() == expected
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=21"
        ).fetchone()[0] == expected
