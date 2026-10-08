from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
)
from prompt_enhancer.application.history.coaching_identity import (
    COACHING_TEMPORAL_CATALOG_SHA256,
    COACHING_TEMPORAL_ENGINE_SHA256,
    COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
    COACHING_TEMPORAL_METRIC_KEYS,
    COACHING_TEMPORAL_PACK_SHA256,
    COACHING_TEMPORAL_PROFILE_KEY,
    COACHING_TEMPORAL_PROFILE_SHA256,
    COACHING_TEMPORAL_PROFILE_VERSION,
)
from prompt_enhancer.application.history.contracts import (
    AnalysisInputExtractionCompleteness,
    AnalysisInputReceiptV2,
    AnalysisInputSelectionCoverage,
)
from prompt_enhancer.application.history.persistence import (
    SyntheticTemporalCompletionRequestV1,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobService,
    AnalysisJobState,
    PowerSourceState,
)
from prompt_enhancer.application.persistence import (
    MetricValueState,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
)
from prompt_enhancer.database import (
    Database,
    DatabaseError,
    DatabaseInvariantError,
    _MIGRATION_1,
    _definition_checksum,
    SCHEMA_VERSION,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.domain import DataTier, MetricObservation, MetricSource, Provider
from prompt_enhancer.infrastructure.sqlite.temporal_history import (
    ANALYSIS_RUN_BRIDGE_VERSION,
    COACHING_AUTOMATION_JOB_PLAN_VERSION,
    analysis_run_bridge_fingerprint,
)
from prompt_enhancer.metrics import METRIC_DEFINITIONS, metric_engine_version_for_definition


BASE = datetime(2042, 1, 2, 3, 4, tzinfo=UTC)


def _id(role: str) -> str:
    return hashlib.sha256(f"synthetic-temporal:{role}".encode("ascii")).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _seed_project(database: Database) -> tuple[str, str]:
    installation_id = _id("installation")
    project_id = _id("project")
    with database._connection() as connection:
        connection.execute(
            """INSERT INTO installations(installation_id,provider,created_at)
               VALUES (?,?,?)""",
            (installation_id, "synthetic", _iso(BASE - timedelta(days=1))),
        )
        connection.execute(
            """INSERT INTO projects(project_id,installation_id,provider,created_at)
               VALUES (?,?,?,?)""",
            (
                project_id,
                installation_id,
                "synthetic",
                _iso(BASE - timedelta(days=1)),
            ),
        )
        connection.commit()
    return installation_id, project_id


def _prepare(database: Database) -> SimpleNamespace:
    installation_id, project_id = _seed_project(database)
    metric_key = COACHING_TEMPORAL_METRIC_KEYS[0]
    grant_id = _id("grant")
    created_at = BASE - timedelta(minutes=5)
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=project_id,
                metric_keys=(metric_key,),
            ),
            created_at=created_at,
            expires_at=created_at + AUTOMATION_GRANT_LIFETIME,
        )
    )
    temporal = database.temporal_history_repository()
    temporal._clock = lambda: BASE
    scope = temporal.prepare_automation_scope(grant_id)
    return SimpleNamespace(
        database=database,
        temporal=temporal,
        installation_id=installation_id,
        project_id=project_id,
        metric_key=metric_key,
        grant_id=grant_id,
        scope=scope,
    )


def _completion_fixture(
    tmp_path, *, bind_publication: bool = True
) -> SimpleNamespace:
    database = Database(tmp_path / "synthetic-temporal.sqlite3")
    database.initialize()
    context = _prepare(database)
    metric_key = context.metric_key
    definition = next(
        item for item in COACHING_METRIC_DEFINITIONS if item.key == metric_key
    )
    session_id = _id("session")
    session_started_at = BASE + timedelta(minutes=1)
    session_ended_at = BASE + timedelta(minutes=2)
    with database._connection() as connection:
        connection.execute(
            """INSERT INTO sessions(
                   session_id,installation_id,project_id,provider,
                   provider_version,adapter_version,source_schema_version,
                   started_at,ended_at,terminal_state,events_complete,
                   created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                context.installation_id,
                context.project_id,
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-source-v1",
                _iso(session_started_at),
                _iso(session_ended_at),
                "completed",
                1,
                _iso(session_started_at),
                _iso(session_ended_at),
            ),
        )
        connection.commit()

    jobs = database.analysis_job_repository()
    job = AnalysisJobService(
        jobs, clock=lambda: BASE + timedelta(minutes=2, seconds=5)
    ).enqueue(
        AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.SYNTHETIC,
            project_id=context.project_id,
            session_id=session_id,
            input_fingerprint=_id("job-input"),
            provenance_fingerprint=_id("job-provenance"),
            metric_keys=(metric_key,),
            estimator_plan_version=COACHING_AUTOMATION_JOB_PLAN_VERSION,
            redactor_version="synthetic-redactor-v1",
            provider_schema_version="synthetic-provider-schema-v1",
            automation_grant_id=context.grant_id,
        )
    ).job
    claimed = jobs.claim_next(
        owner=_id("lease-owner"),
        token=_id("lease-token"),
        now=BASE + timedelta(minutes=2, seconds=10),
        lease_duration=timedelta(minutes=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == job.job_id
    assert claimed.lease_owner is not None and claimed.lease_token is not None

    request_fingerprint = _id("run-request")
    stored_input_fingerprint = _id("stored-run-input")
    model_plan_fingerprint = _id("installation-keyed-model-plan")
    window_fingerprint = _id("selected-window")
    run_id = _id("analysis-run")
    authority = SessionAnalysisCompletionAuthority(
        job_id=claimed.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=claimed.lease_owner,
        lease_token=claimed.lease_token,
    )
    run_fingerprint = analysis_run_bridge_fingerprint(
        request_fingerprint=request_fingerprint,
        input_fingerprint=stored_input_fingerprint,
        analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
        analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=(metric_key,),
        provider="synthetic",
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint=model_plan_fingerprint,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        analysis_window_fingerprint=window_fingerprint,
    )
    runs = database.session_analysis_run_repository()
    assert runs._temporal_history_repository is not None
    runs._temporal_history_repository._clock = lambda: BASE + timedelta(minutes=4)
    runs.begin(
        SessionAnalysisRunDraft(
            run_id=run_id,
            session_id=session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=stored_input_fingerprint,
            analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
            analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
            metric_pack_key=COACHING_METRIC_PACK_KEY,
            metric_pack_version=COACHING_METRIC_PACK_VERSION,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=(metric_key,),
            data_tier=DataTier.REDACTED_CONTENT,
            consent_policy_version="synthetic-consent-v1",
            provider=Provider.SYNTHETIC,
            provider_version="synthetic-provider-v1",
            adapter_version="synthetic-adapter-v1",
            source_schema_version="synthetic-source-v1",
            content_schema_version="synthetic-content-v1",
            metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
            redactor_version="synthetic-redactor-v1",
            model_plan_fingerprint=model_plan_fingerprint,
            schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
            started_at=BASE + timedelta(minutes=2, seconds=20),
        ),
        completion_authority=authority if bind_publication else None,
    )
    finished_at = BASE + timedelta(minutes=3)
    selected_manifest_root = _id("selected-manifest")
    source_manifest_root = _id("source-manifest")
    analysis_input = AnalysisInputReceiptV2(
        input_receipt_id=_id("input-receipt"),
        root_receipt_id=context.scope.history_root.root_receipt_id,
        root_receipt_fingerprint=context.scope.history_root.fingerprint,
        selection_revision_id=context.scope.selection_revision.selection_revision_id,
        selection_revision_fingerprint=context.scope.selection_revision.fingerprint,
        selection_scope_fingerprint=context.scope.selection_revision.metric_set_fingerprint,
        analysis_run_id=run_id,
        analysis_run_fingerprint=run_fingerprint,
        analysis_run_fingerprint_version=ANALYSIS_RUN_BRIDGE_VERSION,
        analysis_run_request_fingerprint=request_fingerprint,
        project_id=context.project_id,
        session_id=session_id,
        selected_metric_keys=(metric_key,),
        analysis_window_fingerprint=window_fingerprint,
        selected_window_manifest_root=selected_manifest_root,
        selected_window_manifest_entry_count=2,
        selected_window_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.selected_manifest_identity(
                root=selected_manifest_root, entry_count=2
            )
        ),
        post_floor_observed_allowlisted_source_manifest_root=source_manifest_root,
        post_floor_observed_allowlisted_source_manifest_entry_count=2,
        post_floor_observed_allowlisted_source_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.observed_source_manifest_identity(
                root=source_manifest_root, entry_count=2
            )
        ),
        successfully_extracted_source_entry_count=2,
        selection_eligible_entry_count=2,
        extraction_completeness=AnalysisInputExtractionCompleteness.COMPLETE,
        selection_coverage=AnalysisInputSelectionCoverage.COMPLETE,
        analysis_window_started_at=session_started_at,
        analysis_window_ended_at=session_ended_at,
        analysis_run_completed_at=finished_at,
        captured_at=finished_at,
        capture_contract_version="synthetic-capture-v2",
        analysis_profile_key=COACHING_TEMPORAL_PROFILE_KEY,
        analysis_profile_version=COACHING_TEMPORAL_PROFILE_VERSION,
        analysis_profile_sha256=COACHING_TEMPORAL_PROFILE_SHA256,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        metric_pack_sha256=COACHING_TEMPORAL_PACK_SHA256,
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        metric_engine_sha256=COACHING_TEMPORAL_ENGINE_SHA256,
        metric_catalog_version=COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
        metric_catalog_sha256=COACHING_TEMPORAL_CATALOG_SHA256,
        consent_policy_version="synthetic-consent-v1",
        consent_receipt_id=_id("consent-receipt"),
        consent_receipt_fingerprint=_id("consent-receipt-fingerprint"),
        privacy_policy_version="synthetic-privacy-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-provider-v1",
        provider_adapter_version="synthetic-adapter-v1",
        provider_schema_version="synthetic-provider-schema-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        redactor_sha256=_id("redactor-sha"),
        preprocessing_version="synthetic-preprocessing-v1",
        preprocessing_sha256=_id("preprocessing-sha"),
        router_version="synthetic-router-v1",
        router_sha256=_id("router-sha"),
        model_plan_fingerprint=model_plan_fingerprint,
        analysis_run_schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        full_run_metric_observation_count=1,
    )
    result = SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=metric_key,
            version=definition.version,
            numeric_value=0.5,
            unit=definition.unit,
            source=MetricSource.DETERMINISTIC,
            observed_count=1,
            eligible_count=2,
            coverage=0.5,
            confidence=None,
        ),
        value_state=MetricValueState.KNOWN,
        direction=SessionMetricDirection(definition.direction.value),
        applicability=SessionMetricApplicability.APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=2,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=1,
        fraction_denominator=2,
        explanation_code="synthetic_known",
        algorithm_id=COACHING_METRIC_ALGORITHM_ID,
        algorithm_version=COACHING_METRIC_ALGORITHM_VERSION,
        rubric_version=COACHING_METRIC_RUBRIC_VERSION,
        computed_at=finished_at,
    )
    request = SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("completion-request"),
        prepared_scope=context.scope,
        analysis_input=analysis_input,
        analysis_run_id=run_id,
    )
    context.__dict__.update(
        session_id=session_id,
        run_id=run_id,
        runs=runs,
        request=request,
        result=result,
        finished_at=finished_at,
        authority=authority,
    )
    return context


def test_v21_schema_is_normalized_zero_backfill_and_auth_is_transient(tmp_path) -> None:
    database = Database(tmp_path / "schema.sqlite3")
    database.initialize()
    with database._connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        temporal_tables = tuple(
            row["name"]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'temporal_%' ORDER BY name"""
            )
        )
        assert temporal_tables
        for table in temporal_tables:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            assert not {"field_name", "scalar_kind", "json", "payload"} & {
                str(column["name"]) for column in columns
            }
            assert all(str(column["type"]).upper() != "BLOB" for column in columns)
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_scope_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_run_delete_authorizations"
        ).fetchone()[0] == 0


def test_populated_v20_migrates_to_v21_without_temporal_backfill(tmp_path) -> None:
    path = tmp_path / "v20.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 21)
    )
    applied_at = _iso(BASE - timedelta(days=1))
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL)"""
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?,?)",
            (
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    applied_at,
                )
                for version, script in enumerate(scripts, start=1)
            ),
        )
        connection.execute("PRAGMA user_version=20")
        installation_id = _id("v20-installation")
        project_id = _id("v20-project")
        session_id = _id("v20-session")
        run_id = _id("v20-run")
        grant_id = _id("v20-grant")
        connection.execute(
            "INSERT INTO installations VALUES (?,?,?)",
            (installation_id, "synthetic", applied_at),
        )
        connection.execute(
            """INSERT INTO projects(
                   project_id,installation_id,provider,created_at)
               VALUES (?,?,?,?)""",
            (project_id, installation_id, "synthetic", applied_at),
        )
        connection.execute(
            """INSERT INTO sessions(
                   session_id,installation_id,project_id,provider,
                   provider_version,adapter_version,source_schema_version,
                   started_at,ended_at,terminal_state,events_complete,
                   created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                installation_id,
                project_id,
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-source-v1",
                applied_at,
                applied_at,
                "completed",
                1,
                applied_at,
                applied_at,
            ),
        )
        connection.execute(
            """INSERT INTO automation_grants(
                   grant_id,revision,provider,project_id,newest_session_limit,
                   check_interval_seconds,route,max_gpu_workers,max_cpu_workers,
                   pause_on_battery,maximum_session_seconds,local_only,
                   remote_requires_fresh_approval,state,created_at,renewed_at,
                   expires_at,next_check_at,last_checked_at,revoked_at,
                   last_error_code) VALUES (
                   ?,1,'synthetic',?,20,900,'balanced',1,2,1,1800,1,1,
                   'active',?,?,?,?,NULL,NULL,NULL)""",
            (
                grant_id,
                project_id,
                applied_at,
                applied_at,
                _iso(BASE + timedelta(days=20)),
                applied_at,
            ),
        )
        connection.execute(
            "INSERT INTO automation_grant_metrics VALUES (?,?,0)",
            (grant_id, COACHING_TEMPORAL_METRIC_KEYS[0]),
        )
        connection.execute(
            """INSERT INTO session_analysis_runs(
                   run_id,session_id,request_fingerprint,input_fingerprint,
                   metric_pack_key,metric_pack_version,data_tier,consent_purpose,
                   consent_policy_version,provider,provider_version,
                   adapter_version,source_schema_version,content_schema_version,
                   metric_engine_version,redactor_version,model_plan_fingerprint,
                   schema_version,local_only,started_at,finished_at,status,
                   failure_code,analysis_profile_key,analysis_profile_version,
                   metric_scope_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                session_id,
                _id("v20-request"),
                _id("v20-input"),
                "legacy.synthetic",
                1,
                "redacted_content",
                "text_analysis",
                "synthetic-consent-v1",
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-source-v1",
                "synthetic-content-v1",
                "synthetic-engine-v1",
                "synthetic-redactor-v1",
                _id("v20-plan"),
                20,
                1,
                applied_at,
                None,
                "running",
                None,
                "legacy.synthetic",
                1,
                "exact",
            ),
        )
        connection.execute(
            "INSERT INTO session_analysis_run_metrics VALUES (?,?,0)",
            (run_id, COACHING_TEMPORAL_METRIC_KEYS[0]),
        )
        definition = next(
            item
            for item in COACHING_METRIC_DEFINITIONS
            if item.key == COACHING_TEMPORAL_METRIC_KEYS[0]
        )
        persisted_definition = next(
            item for item in METRIC_DEFINITIONS if item.key == definition.key
        )
        connection.execute(
            """INSERT INTO metric_definitions(
                   key,version,dimension,display_name,description,unit,source,
                   algorithm_version,definition_checksum)
               VALUES (?,?,?,?,? ,?,'deterministic',?,?)""",
            (
                persisted_definition.key,
                persisted_definition.version,
                persisted_definition.dimension,
                persisted_definition.display_name,
                persisted_definition.description,
                persisted_definition.unit,
                metric_engine_version_for_definition(persisted_definition),
                _definition_checksum(persisted_definition),
            ),
        )
        connection.execute(
            """INSERT INTO session_analysis_results(
                   run_id,key,version,metric_schema_version,value_state,
                   numeric_value,unit,source,direction,applicability,
                   aggregation_method,fraction_numerator,fraction_denominator,
                   observed_count,eligible_count,coverage,confidence,
                   evidence_data_tier,explanation_code,error_code,algorithm_id,
                   algorithm_version,model_id,model_revision,model_license,
                   tokenizer_id,prompt_version,rubric_version,computed_at)
               VALUES (?,?,?,2,'known',? ,?,'deterministic',?,'applicable',
                       'ratio_of_sums',1,2,1,2,0.5,NULL,'redacted_content',
                       'synthetic_known',NULL,?,?,NULL,NULL,NULL,NULL,NULL,?,?)""",
            (
                run_id,
                definition.key,
                definition.version,
                0.5,
                definition.unit,
                definition.direction.value,
                COACHING_METRIC_ALGORITHM_ID,
                COACHING_METRIC_ALGORITHM_VERSION,
                COACHING_METRIC_RUBRIC_VERSION,
                applied_at,
            ),
        )
        connection.execute(
            """UPDATE session_analysis_runs
               SET status='completed',finished_at=? WHERE run_id=?""",
            (applied_at, run_id),
        )
        before = tuple(connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ))
        connection.commit()

    database = Database(path)
    database.initialize()
    with database._connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        after = tuple(
            (row["version"], row["checksum"])
            for row in connection.execute(
                "SELECT version,checksum FROM schema_migrations ORDER BY version"
            )
        )
        assert after[:20] == before
        assert len(after) == 61
        durable_tables = tuple(
            row["name"]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'temporal_%'
                     AND name NOT IN (
                       'temporal_coaching_identity_registry',
                       'temporal_scope_append_authorizations',
                       'temporal_history_append_authorizations',
                       'temporal_run_delete_authorizations')"""
            )
        )
        assert durable_tables
        assert all(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            for table in durable_tables
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_coaching_identity_registry"
        ).fetchone()[0] == len(COACHING_TEMPORAL_METRIC_KEYS)


def test_prepare_is_prospective_idempotent_and_repository_owned(tmp_path) -> None:
    database = Database(tmp_path / "prepare.sqlite3")
    database.initialize()
    context = _prepare(database)
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = tuple(
            pool.map(
                lambda _: context.temporal.prepare_automation_scope(
                    context.grant_id
                ),
                range(2),
            )
        )
    assert repeated == (context.scope, context.scope)
    assert context.scope.history_root.history_floor_at == BASE
    assert context.scope.prepared_at == BASE
    assert context.scope.repository_owned is True
    assert context.scope.sealed is True
    assert context.scope.capture_authority_verified is False
    with database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_root_drafts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_prepared_scope_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_scope_append_authorizations"
        ).fetchone()[0] == 0


def test_a_b_a_grants_reuse_one_root_and_append_exact_cas_chain(tmp_path) -> None:
    database = Database(tmp_path / "selection-chain.sqlite3")
    database.initialize()
    context = _prepare(database)
    metric_a = context.metric_key
    metric_b = COACHING_TEMPORAL_METRIC_KEYS[1]
    grants = database.automation_grant_repository()
    grants.revoke(context.grant_id, now=BASE + timedelta(minutes=1))

    grant_b = _id("grant-b")
    created_b = BASE + timedelta(minutes=2)
    grants.create(
        AutomationGrantDraft(
            grant_id=grant_b,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=context.project_id,
                metric_keys=(metric_b,),
            ),
            created_at=created_b,
            expires_at=created_b + AUTOMATION_GRANT_LIFETIME,
        )
    )
    context.temporal._clock = lambda: created_b
    scope_b = context.temporal.prepare_automation_scope(grant_b)
    grants.revoke(grant_b, now=BASE + timedelta(minutes=3))

    grant_a2 = _id("grant-a2")
    created_a2 = BASE + timedelta(minutes=4)
    grants.create(
        AutomationGrantDraft(
            grant_id=grant_a2,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=context.project_id,
                metric_keys=(metric_a,),
            ),
            created_at=created_a2,
            expires_at=created_a2 + AUTOMATION_GRANT_LIFETIME,
        )
    )
    context.temporal._clock = lambda: created_a2
    scope_a2 = context.temporal.prepare_automation_scope(grant_a2)

    scopes = (context.scope, scope_b, scope_a2)
    assert tuple(scope.history_root.root_receipt_id for scope in scopes) == (
        context.scope.history_root.root_receipt_id,
    ) * 3
    assert tuple(
        scope.selection_revision.selection_ordinal for scope in scopes
    ) == (1, 2, 3)
    assert scope_b.selection_revision.compare_and_swap_predecessor_id == (
        context.scope.selection_revision.selection_revision_id
    )
    assert scope_a2.selection_revision.compare_and_swap_predecessor_id == (
        scope_b.selection_revision.selection_revision_id
    )
    assert tuple(
        scope.selection_revision.selected_metric_keys for scope in scopes
    ) == ((metric_a,), (metric_b,), (metric_a,))
    assert len({scope.selection_revision.fingerprint for scope in scopes}) == 3
    assert len({scope.fingerprint for scope in scopes}) == 3
    with database._connection() as connection:
        indexed_columns = {
            tuple(
                item["name"]
                for item in connection.execute(f"PRAGMA index_info({index['name']})")
            )
            for index in connection.execute(
                "PRAGMA index_list(temporal_metric_selection_drafts)"
            )
            if index["unique"]
        }
        assert ("metric_set_fingerprint",) not in indexed_columns
        with pytest.raises(sqlite3.Error):
            connection.execute(
                """INSERT INTO temporal_metric_selection_drafts(
                          selection_revision_id,operation_id,contract_version,
                          root_receipt_id,root_receipt_fingerprint,project_id,
                          selection_ordinal,predecessor_selection_id,
                          predecessor_selection_fingerprint,source,
                          effective_at_us,recorded_at_us,metric_pack_key,
                          metric_pack_version,metric_pack_sha256,
                          metric_catalog_version,metric_catalog_sha256,
                          source_authority_kind,source_authority_id,
                          source_authority_fingerprint,source_authority_version,
                          metric_count,metric_set_fingerprint,
                          selection_fingerprint)
                   SELECT ?,?,contract_version,root_receipt_id,
                          root_receipt_fingerprint,project_id,selection_ordinal+2,
                          selection_revision_id,selection_fingerprint,
                          source,effective_at_us,recorded_at_us,
                          metric_pack_key,metric_pack_version,metric_pack_sha256,
                          metric_catalog_version,metric_catalog_sha256,
                          source_authority_kind,source_authority_id,
                          source_authority_fingerprint,source_authority_version,
                          metric_count,metric_set_fingerprint,?
                   FROM temporal_metric_selection_drafts
                   WHERE selection_revision_id=?""",
                (
                    _id("forged-selection"),
                    _id("forged-operation"),
                    _id("forged-selection-fingerprint"),
                    scope_a2.selection_revision.selection_revision_id,
                ),
            )
        connection.rollback()
        middle_operation = connection.execute(
            """SELECT operation_id FROM temporal_metric_selection_drafts
               WHERE selection_revision_id=?""",
            (scope_b.selection_revision.selection_revision_id,),
        ).fetchone()[0]
        connection.execute("DROP TRIGGER temporal_metric_selection_no_update")
        connection.execute(
            """UPDATE temporal_metric_selection_drafts SET operation_id=?
               WHERE selection_revision_id=?""",
            (
                _id("corrupt-middle-selection-operation"),
                scope_b.selection_revision.selection_revision_id,
            ),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_prepared_scope(scope_a2.prepared_scope_id)
    with database._connection() as connection:
        connection.execute(
            """UPDATE temporal_metric_selection_drafts SET operation_id=?
               WHERE selection_revision_id=?""",
            (middle_operation, scope_b.selection_revision.selection_revision_id),
        )
        connection.commit()
        connection.execute("DROP TRIGGER temporal_history_root_no_update")
        connection.execute(
            """UPDATE temporal_history_root_drafts SET operation_id=?
               WHERE root_receipt_id=?""",
            (
                _id("corrupt-later-scope-root-operation"),
                context.scope.history_root.root_receipt_id,
            ),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_prepared_scope(scope_a2.prepared_scope_id)


def test_prepare_rejects_authority_that_does_not_yet_exist(tmp_path) -> None:
    database = Database(tmp_path / "future-grant.sqlite3")
    database.initialize()
    _, project_id = _seed_project(database)
    future_created_at = BASE + timedelta(minutes=1)
    grant_id = _id("future-grant")
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=project_id,
                metric_keys=(COACHING_TEMPORAL_METRIC_KEYS[0],),
            ),
            created_at=future_created_at,
            expires_at=future_created_at + AUTOMATION_GRANT_LIFETIME,
        )
    )
    temporal = database.temporal_history_repository()
    temporal._clock = lambda: BASE
    with pytest.raises(DatabaseInvariantError):
        temporal.prepare_automation_scope(grant_id)
    with database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_root_drafts"
        ).fetchone()[0] == 0
        trigger = connection.execute(
            """SELECT sql FROM sqlite_master
               WHERE type='trigger' AND name='temporal_prepared_scope_root_insert_guard'"""
        ).fetchone()[0]
        assert "gs.renewed_at_us<=NEW.prepared_at_us" in trigger


def test_malformed_selection_authority_version_fails_as_database_invariant(
    tmp_path,
) -> None:
    database = Database(tmp_path / "malformed-authority.sqlite3")
    database.initialize()
    context = _prepare(database)
    with database._connection() as connection:
        connection.execute("DROP TRIGGER temporal_metric_selection_no_update")
        connection.execute(
            """UPDATE temporal_metric_selection_drafts
               SET source_authority_version='malformed-version'
               WHERE selection_revision_id=?""",
            (context.scope.selection_revision.selection_revision_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_prepared_scope(context.scope.prepared_scope_id)


def test_synthetic_completion_is_atomic_root_last_and_exactly_rehydrated(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    assert sealed.repository_owned is True
    assert sealed.repository_graph_verified is True
    assert sealed.source_authority_verified is False
    assert sealed.product_history_eligible is False
    assert context.temporal.get_sealed_batch_for_run(context.run_id) == sealed
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT status FROM session_analysis_runs WHERE run_id=?",
            (context.run_id,),
        ).fetchone()[0] == "completed"
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_sealed_batch_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_append_authorizations"
        ).fetchone()[0] == 0
        for table in (
            "temporal_count_exposure_values",
            "temporal_distribution_sample_values",
            "temporal_sampled_proportion_values",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        root_guard = connection.execute(
            """SELECT sql FROM sqlite_master WHERE type='trigger'
               AND name='temporal_sealed_batch_root_insert_guard'"""
        ).fetchone()[0]
        for table in (
            "analysis_job_metrics",
            "automation_grant_metrics",
            "session_analysis_run_metrics",
        ):
            assert f"COUNT(*) FROM {table}" in root_guard
            assert f"FROM {table}" in root_guard


def test_exact_completed_replay_returns_same_seal_and_conflict_fails(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    first = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    replay = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert replay == first
    changed = context.result.model_copy(
        update={"explanation_code": "synthetic_changed"}
    )
    with pytest.raises(DatabaseError):
        context.runs.complete(
            context.run_id,
            (changed,),
            finished_at=context.finished_at,
            completion_authority=context.authority,
            temporal_completion_request=context.request,
        )


def test_two_concurrent_exact_completions_converge_on_one_seal(tmp_path) -> None:
    context = _completion_fixture(tmp_path)

    def complete_once():  # type: ignore[no-untyped-def]
        return context.runs.complete(
            context.run_id,
            (context.result,),
            finished_at=context.finished_at,
            completion_authority=context.authority,
            temporal_completion_request=context.request,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        sealed = tuple(pool.map(lambda _: complete_once(), range(2)))
    assert sealed[0] is not None and sealed[0] == sealed[1]
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_sealed_batch_roots"
        ).fetchone()[0] == 1


def test_second_temporal_run_for_same_session_is_bounded_and_rolls_back(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    first = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert first is not None

    jobs = context.database.analysis_job_repository()
    first_job = jobs.get(context.authority.job_id)
    assert first_job is not None
    assert first_job.lease_expires_at is not None
    assert first_job.lease_owner is not None and first_job.lease_token is not None
    jobs.finish(
        AnalysisJobLease(
            job_id=first_job.job_id,
            owner=first_job.lease_owner,
            token=first_job.lease_token,
            expires_at=first_job.lease_expires_at,
        ),
        now=context.finished_at + timedelta(seconds=1),
        state=AnalysisJobState.COMPLETED,
        reason_code="completed",
        progress_completed=1,
        progress_total=1,
    )
    second_job = AnalysisJobService(
        jobs, clock=lambda: BASE + timedelta(minutes=4, seconds=5)
    ).enqueue(
        AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.SYNTHETIC,
            project_id=context.project_id,
            session_id=context.session_id,
            input_fingerprint=_id("second-job-input"),
            provenance_fingerprint=_id("second-job-provenance"),
            metric_keys=(context.metric_key,),
            estimator_plan_version=COACHING_AUTOMATION_JOB_PLAN_VERSION,
            redactor_version="synthetic-redactor-v1",
            provider_schema_version="synthetic-provider-schema-v1",
            automation_grant_id=context.grant_id,
        )
    ).job
    claimed = jobs.claim_next(
        owner=_id("second-lease-owner"),
        token=_id("second-lease-token"),
        now=BASE + timedelta(minutes=4, seconds=10),
        lease_duration=timedelta(minutes=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == second_job.job_id
    assert claimed.lease_owner is not None and claimed.lease_token is not None

    first_input = context.request.analysis_input
    run_id = _id("second-analysis-run")
    request_fingerprint = _id("second-run-request")
    stored_input_fingerprint = _id("second-stored-run-input")
    window_fingerprint = _id("second-selected-window")
    run_fingerprint = analysis_run_bridge_fingerprint(
        request_fingerprint=request_fingerprint,
        input_fingerprint=stored_input_fingerprint,
        analysis_profile_key=first_input.analysis_profile_key,
        analysis_profile_version=first_input.analysis_profile_version,
        metric_pack_key=first_input.metric_pack_key,
        metric_pack_version=first_input.metric_pack_version,
        selected_metric_keys=first_input.selected_metric_keys,
        provider=first_input.provider.value,
        provider_version=first_input.provider_version,
        adapter_version=first_input.provider_adapter_version,
        source_schema_version=first_input.source_schema_version,
        content_schema_version=first_input.content_schema_version,
        metric_engine_version=first_input.metric_engine_version,
        redactor_version=first_input.redactor_version,
        model_plan_fingerprint=first_input.model_plan_fingerprint,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        analysis_window_fingerprint=window_fingerprint,
    )
    context.runs.begin(
        SessionAnalysisRunDraft(
            run_id=run_id,
            session_id=context.session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=stored_input_fingerprint,
            analysis_profile_key=first_input.analysis_profile_key,
            analysis_profile_version=first_input.analysis_profile_version,
            metric_pack_key=first_input.metric_pack_key,
            metric_pack_version=first_input.metric_pack_version,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=first_input.selected_metric_keys,
            data_tier=first_input.data_tier,
            consent_policy_version=first_input.consent_policy_version,
            provider=first_input.provider,
            provider_version=first_input.provider_version,
            adapter_version=first_input.provider_adapter_version,
            source_schema_version=first_input.source_schema_version,
            content_schema_version=first_input.content_schema_version,
            metric_engine_version=first_input.metric_engine_version,
            redactor_version=first_input.redactor_version,
            model_plan_fingerprint=first_input.model_plan_fingerprint,
            schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
            started_at=BASE + timedelta(minutes=4, seconds=20),
        )
    )
    finished_at = BASE + timedelta(minutes=5)
    selected_root = _id("second-selected-manifest")
    source_root = _id("second-source-manifest")
    second_input = AnalysisInputReceiptV2(
        **{
            **first_input.model_dump(),
            "input_receipt_id": _id("second-input-receipt"),
            "analysis_run_id": run_id,
            "analysis_run_fingerprint": run_fingerprint,
            "analysis_run_request_fingerprint": request_fingerprint,
            "analysis_window_fingerprint": window_fingerprint,
            "selected_window_manifest_root": selected_root,
            "selected_window_manifest_identity_fingerprint": (
                AnalysisInputReceiptV2.selected_manifest_identity(
                    root=selected_root,
                    entry_count=first_input.selected_window_manifest_entry_count,
                )
            ),
            "post_floor_observed_allowlisted_source_manifest_root": source_root,
            "post_floor_observed_allowlisted_source_manifest_identity_fingerprint": (
                AnalysisInputReceiptV2.observed_source_manifest_identity(
                    root=source_root,
                    entry_count=(
                        first_input.post_floor_observed_allowlisted_source_manifest_entry_count
                    ),
                )
            ),
            "consent_receipt_id": _id("second-consent-receipt"),
            "consent_receipt_fingerprint": _id(
                "second-consent-receipt-fingerprint"
            ),
            "analysis_run_completed_at": finished_at,
            "captured_at": finished_at,
        }
    )
    second_request = SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("second-completion-request"),
        prepared_scope=context.scope,
        analysis_input=second_input,
        analysis_run_id=run_id,
    )
    second_result = context.result.model_copy(
        update={"computed_at": finished_at}
    )
    authority = SessionAnalysisCompletionAuthority(
        job_id=claimed.job_id,
        automation_grant_id=context.grant_id,
        lease_owner=claimed.lease_owner,
        lease_token=claimed.lease_token,
    )
    assert context.runs._temporal_history_repository is not None
    context.runs._temporal_history_repository._clock = (
        lambda: BASE + timedelta(minutes=6)
    )
    with pytest.raises(DatabaseError):
        context.runs.complete(
            run_id,
            (second_result,),
            finished_at=finished_at,
            completion_authority=authority,
            temporal_completion_request=second_request,
        )
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT status FROM session_analysis_runs WHERE run_id=?", (run_id,)
        ).fetchone()[0] == "running"
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_results WHERE run_id=?",
            (run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_session_revisions WHERE session_id=?",
            (context.session_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_sealed_batch_roots"
        ).fetchone()[0] == 1


def test_temporal_run_requires_authorized_privacy_cascade_and_wal_purge(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    raw = sqlite3.connect(context.database.path)
    try:
        raw.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.Error):
            raw.execute(
                "DELETE FROM session_analysis_runs WHERE run_id=?",
                (context.run_id,),
            )
        raw.rollback()
    finally:
        raw.close()
    assert context.runs.delete_for_privacy(context.run_id) is True
    assert context.runs.delete_for_privacy(context.run_id) is False
    assert context.temporal.get_sealed_batch_for_run(context.run_id) is None
    assert context.temporal.get_prepared_scope(
        context.scope.prepared_scope_id
    ) == context.scope
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_run_delete_authorizations"
        ).fetchone()[0] == 0


def test_pinned_reader_reports_wal_pending_and_absent_retry_purges(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    pinned = sqlite3.connect(context.database.path)
    try:
        pinned.execute("PRAGMA journal_mode=WAL")
        pinned.execute("BEGIN")
        assert pinned.execute(
            "SELECT COUNT(*) FROM temporal_sealed_batch_roots"
        ).fetchone()[0] == 1
        with pytest.raises(
            DatabaseInvariantError, match="WAL purge pending"
        ):
            context.runs.delete_for_privacy(context.run_id)
    finally:
        pinned.rollback()
        pinned.close()
    assert context.runs.delete_for_privacy(context.run_id) is False
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_run_delete_authorizations"
        ).fetchone()[0] == 0


def test_forged_stale_and_cross_run_delete_capabilities_fail_closed(tmp_path) -> None:
    database = Database(tmp_path / "delete-capability.sqlite3")
    database.initialize()
    run_id = _id("capability-run")
    other_run_id = _id("capability-other-run")

    def raw_attempt(operation_id: str, target: str, tag: str) -> None:
        with pytest.raises(DatabaseError):
            with database._connection() as connection:
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute(
                    "INSERT INTO temporal_run_delete_authorizations VALUES (?,?,?)",
                    (operation_id, target, tag),
                )

    raw_attempt(_id("forged-operation"), run_id, _id("forged-tag"))
    operation_id, tag = database._begin_temporal_run_delete_authorization(run_id)
    database._end_temporal_run_delete_authorization(operation_id, run_id, tag)
    raw_attempt(operation_id, run_id, tag)
    operation_id, tag = database._begin_temporal_run_delete_authorization(run_id)
    try:
        raw_attempt(operation_id, other_run_id, tag)
    finally:
        database._end_temporal_run_delete_authorization(operation_id, run_id, tag)
    with database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_run_delete_authorizations"
        ).fetchone()[0] == 0
    assert database._temporal_run_delete_authorizations == set()


def test_live_append_capability_cannot_be_substituted_across_lineage(tmp_path) -> None:
    database = Database(tmp_path / "append-capability.sqlite3")
    database.initialize()
    scope_values: tuple[object, ...] = (
        _id("scope-grant"),
        1,
        _id("scope-grant-fingerprint"),
        _id("scope-project"),
        _id("scope-id"),
        _id("scope-fingerprint"),
        _id("scope-root"),
        _id("scope-root-fingerprint"),
        _id("scope-selection"),
        _id("scope-selection-fingerprint"),
        _id("scope-authorization-fingerprint"),
    )
    operation_id, tag = database._begin_temporal_scope_authorization(
        *scope_values
    )
    try:
        altered = list(scope_values)
        altered[3] = _id("substituted-project")
        with pytest.raises(DatabaseError):
            with database._connection() as connection:
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute(
                    """INSERT INTO temporal_scope_append_authorizations
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (operation_id, *altered[:-1], altered[-1], tag),
                )
    finally:
        database._end_temporal_scope_authorization(
            operation_id, str(scope_values[-1]), tag
        )

    history_values: tuple[object, ...] = (
        _id("history-job"),
        _id("history-grant"),
        1,
        _id("history-grant-fingerprint"),
        _id("history-run"),
        _id("history-run-fingerprint"),
        _id("history-root"),
        _id("history-root-fingerprint"),
        _id("history-selection"),
        _id("history-selection-fingerprint"),
        _id("history-scope"),
        _id("history-scope-fingerprint"),
        _id("history-request"),
        _id("history-request-fingerprint"),
        _id("history-draft"),
        _id("history-draft-fingerprint"),
        _id("history-seal"),
        _id("history-seal-fingerprint"),
        _id("history-authorization-fingerprint"),
    )
    operation_id, tag = database._begin_temporal_history_authorization(
        *history_values
    )
    try:
        altered = list(history_values)
        altered[4] = _id("substituted-run")
        with pytest.raises(DatabaseError):
            with database._connection() as connection:
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute(
                    """INSERT INTO temporal_history_append_authorizations
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (operation_id, *altered[:-1], altered[-1], tag),
                )
    finally:
        database._end_temporal_history_authorization(
            operation_id, str(history_values[-1]), tag
        )
    assert database._temporal_scope_authorizations == set()
    assert database._temporal_history_authorizations == set()
    with database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_scope_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_append_authorizations"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "drift",
    ("grant_revoked", "grant_renewed", "job_cancelled", "lease_token"),
)
def test_authority_drift_aborts_legacy_and_temporal_completion(
    tmp_path, drift: str
) -> None:
    context = _completion_fixture(tmp_path)
    if drift == "grant_revoked":
        context.database.automation_grant_repository().revoke(
            context.grant_id, now=BASE + timedelta(minutes=2, seconds=30)
        )
    elif drift == "grant_renewed":
        context.database.automation_grant_repository().renew(
            context.grant_id, now=BASE + timedelta(minutes=2, seconds=30)
        )
    elif drift == "job_cancelled":
        context.database.analysis_job_repository().request_cancel(
            context.authority.job_id,
            now=BASE + timedelta(minutes=2, seconds=30),
        )
    else:
        with context.database._connection() as connection:
            connection.execute(
                "UPDATE analysis_jobs SET lease_token=? WHERE job_id=?",
                (_id("drifted-lease-token"), context.authority.job_id),
            )
            connection.commit()
    with pytest.raises(DatabaseError):
        context.runs.complete(
            context.run_id,
            (context.result,),
            finished_at=context.finished_at,
            completion_authority=context.authority,
            temporal_completion_request=context.request,
        )
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_results WHERE run_id=?",
            (context.run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_completion_requests"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_append_authorizations"
        ).fetchone()[0] == 0
    assert context.database._temporal_history_authorizations == set()


def test_post_seal_append_update_and_delete_are_closed(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    observation_id = sealed.seal_draft.observation_batch.observations[0].observation_id
    attempts = (
        (
            "UPDATE temporal_observations SET evidence_numerator=0 WHERE observation_id=?",
            (observation_id,),
        ),
        (
            "DELETE FROM temporal_observations WHERE observation_id=?",
            (observation_id,),
        ),
        (
            """INSERT INTO temporal_seal_graph_commitments
               (seal_draft_id,ordinal,graph_fingerprint) VALUES (?,?,?)""",
            (sealed.seal_draft.seal_draft_id, 8, _id("late-graph")),
        ),
    )
    for statement, parameters in attempts:
        with pytest.raises(DatabaseError):
            with context.database._connection() as connection:
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute(statement, parameters)
    assert context.temporal.get_sealed_batch(sealed.sealed_batch_id) == sealed


def test_replace_cannot_remove_committed_run_graph_with_recursive_triggers_off(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    with context.database._connection() as connection:
        connection.execute("PRAGMA recursive_triggers=OFF")
        with pytest.raises(sqlite3.Error):
            connection.execute(
                """INSERT OR REPLACE INTO session_analysis_runs
                   SELECT * FROM session_analysis_runs WHERE run_id=?""",
                (context.run_id,),
            )
        connection.rollback()
        assert connection.execute(
            "SELECT status FROM session_analysis_runs WHERE run_id=?",
            (context.run_id,),
        ).fetchone()[0] == "completed"
        assert connection.execute(
            """SELECT COUNT(*) FROM temporal_completion_requests
               WHERE analysis_run_id=?""",
            (context.run_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            """SELECT COUNT(*) FROM temporal_sealed_batch_roots
               WHERE sealed_batch_id=?""",
            (sealed.sealed_batch_id,),
        ).fetchone()[0] == 1
    assert context.temporal.get_sealed_batch(sealed.sealed_batch_id) == sealed


def test_sealed_read_and_replay_do_not_require_live_lease_or_active_grant(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    with context.database._connection() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(temporal_completion_requests)"
            )
        }
        assert "job_id" not in columns
        assert connection.execute(
            "SELECT COUNT(*) FROM analysis_jobs WHERE job_id=?",
            (context.authority.job_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM automation_grants WHERE grant_id=?",
            (context.grant_id,),
        ).fetchone()[0] == 1
    context.database.automation_grant_repository().revoke(
        context.grant_id,
        now=context.finished_at + timedelta(microseconds=1),
    )
    hydrated = context.temporal.get_sealed_batch(sealed.sealed_batch_id)
    assert hydrated == sealed
    assert hydrated is not None
    assert hydrated.source_authority_verified is False
    assert hydrated.product_history_eligible is False
    replay = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=SessionAnalysisCompletionAuthority(
            job_id=_id("expired-job-placeholder"),
            automation_grant_id=_id("expired-grant-placeholder"),
            lease_owner=_id("expired-owner-placeholder"),
            lease_token=_id("expired-token-placeholder"),
        ),
        temporal_completion_request=context.request,
    )
    assert replay == sealed


def test_replace_cannot_remove_project_root_or_mutate_registry_when_recursive_off(
    tmp_path,
) -> None:
    database = Database(tmp_path / "replace-closed-roots.sqlite3")
    database.initialize()
    context = _prepare(database)
    metric_key = context.metric_key
    with database._connection() as connection:
        connection.execute("PRAGMA recursive_triggers=OFF")
        with pytest.raises(sqlite3.Error):
            connection.execute(
                """INSERT OR REPLACE INTO projects
                   SELECT * FROM projects WHERE project_id=?""",
                (context.project_id,),
            )
        connection.rollback()
        before = tuple(
            connection.execute(
                """SELECT * FROM temporal_coaching_identity_registry
                   WHERE metric_key=?""",
                (metric_key,),
            ).fetchone()
        )
        with pytest.raises(sqlite3.Error):
            connection.execute(
                """INSERT OR REPLACE INTO temporal_coaching_identity_registry
                   SELECT * FROM temporal_coaching_identity_registry
                   WHERE metric_key=?""",
                (metric_key,),
            )
        connection.rollback()
        after = tuple(
            connection.execute(
                """SELECT * FROM temporal_coaching_identity_registry
                   WHERE metric_key=?""",
                (metric_key,),
            ).fetchone()
        )
        assert after == before
        assert connection.execute(
            """SELECT COUNT(*) FROM temporal_history_root_drafts
               WHERE project_id=?""",
            (context.project_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM projects WHERE project_id=?",
            (context.project_id,),
        ).fetchone()[0] == 1
    assert context.temporal.get_prepared_scope(context.scope.prepared_scope_id) == (
        context.scope
    )


def test_temporal_failure_rolls_back_legacy_results_and_graph(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    forged = context.request.model_copy(
        update={"analysis_run_id": _id("wrong-run")}
    )
    with pytest.raises((DatabaseError, ValueError)):
        context.runs.complete(
            context.run_id,
            (context.result,),
            finished_at=context.finished_at,
            completion_authority=context.authority,
            temporal_completion_request=forged,
        )
    with context.database._connection() as connection:
        assert connection.execute(
            "SELECT status FROM session_analysis_runs WHERE run_id=?",
            (context.run_id,),
        ).fetchone()[0] == "running"
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_results WHERE run_id=?",
            (context.run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_completion_requests"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM temporal_history_append_authorizations"
        ).fetchone()[0] == 0


def test_hydration_rejects_corrupted_immutable_source_result(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    with context.database._connection() as connection:
        connection.execute("DROP TRIGGER session_analysis_results_no_update")
        connection.execute(
            """UPDATE session_analysis_results
               SET numeric_value=0.25,fraction_denominator=4
               WHERE run_id=?""",
            (context.run_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_sealed_batch(sealed.sealed_batch_id)


def test_corrupt_source_timestamps_fail_with_sanitized_invariant(tmp_path) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    with context.database._connection() as connection:
        connection.execute("DROP TRIGGER session_analysis_results_no_update")
        connection.execute(
            """UPDATE session_analysis_results
               SET computed_at='private-looking-corrupt-value'
               WHERE run_id=?""",
            (context.run_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError) as captured:
        context.temporal.get_sealed_batch(sealed.sealed_batch_id)
    assert str(captured.value) == "stored temporal timestamp is invalid"
    assert captured.value.__cause__ is None

    replay_path = tmp_path / "replay"
    replay_path.mkdir()
    replay_context = _completion_fixture(replay_path)
    replay_context.runs.complete(
        replay_context.run_id,
        (replay_context.result,),
        finished_at=replay_context.finished_at,
        completion_authority=replay_context.authority,
        temporal_completion_request=replay_context.request,
    )
    with replay_context.database._connection() as connection:
        connection.execute("DROP TRIGGER session_analysis_runs_terminal_transition_only")
        connection.execute(
            """UPDATE session_analysis_runs
               SET finished_at='private-looking-corrupt-value'
               WHERE run_id=?""",
            (replay_context.run_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError) as replay_error:
        replay_context.runs.complete(
            replay_context.run_id,
            (replay_context.result,),
            finished_at=replay_context.finished_at,
            completion_authority=replay_context.authority,
            temporal_completion_request=replay_context.request,
        )
    assert str(replay_error.value) == "stored temporal timestamp is invalid"
    assert replay_error.value.__cause__ is None


@pytest.mark.parametrize(
    ("status", "finished_at"),
    (("running", None), ("completed", _iso(BASE + timedelta(minutes=3, seconds=1)))),
)
def test_hydration_rejects_corrupted_source_run_terminal_truth(
    tmp_path, status: str, finished_at: str | None
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    with context.database._connection() as connection:
        connection.execute("DROP TRIGGER session_analysis_runs_terminal_transition_only")
        connection.execute("DROP TRIGGER session_analysis_runs_automation_deadline_guard")
        connection.execute(
            """UPDATE session_analysis_runs SET status=?,finished_at=?
               WHERE run_id=?""",
            (status, finished_at, context.run_id),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_sealed_batch(sealed.sealed_batch_id)


def test_hydration_rejects_coordinated_temporal_child_fingerprint_tamper(
    tmp_path,
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    observation = sealed.seal_draft.observation_batch.observations[0]
    changed_observation = type(observation)(
        **{
            **observation.model_dump(),
            "evidence_numerator": 0,
        }
    )
    with context.database._connection() as connection:
        connection.executescript(
            """DROP TRIGGER temporal_observation_no_update;
               DROP TRIGGER temporal_seal_observation_commitment_no_update;
               DROP TRIGGER temporal_seal_graph_commitment_no_update;"""
        )
        connection.execute(
            """UPDATE temporal_observations
               SET evidence_numerator=?,observation_fingerprint=?
               WHERE observation_id=?""",
            (
                changed_observation.evidence_numerator,
                changed_observation.fingerprint,
                observation.observation_id,
            ),
        )
        connection.execute(
            """UPDATE temporal_seal_observation_commitments
               SET observation_fingerprint=? WHERE observation_id=?""",
            (changed_observation.fingerprint, observation.observation_id),
        )
        connection.execute(
            """UPDATE temporal_seal_graph_commitments
               SET graph_fingerprint=?
               WHERE seal_draft_id=? AND ordinal=7""",
            (
                changed_observation.fingerprint,
                sealed.seal_draft.seal_draft_id,
            ),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_sealed_batch(sealed.sealed_batch_id)


@pytest.mark.parametrize(
    "corruption",
    (
        "observation_request",
        "draft_request",
        "draft_batch",
        "selection_key_ordinal",
        "scope_operation",
        "snapshot_operation",
        "selection_operation",
        "root_operation",
    ),
)
def test_hydration_rejects_denormalized_graph_lineage_corruption(
    tmp_path, corruption: str
) -> None:
    context = _completion_fixture(tmp_path)
    sealed = context.runs.complete(
        context.run_id,
        (context.result,),
        finished_at=context.finished_at,
        completion_authority=context.authority,
        temporal_completion_request=context.request,
    )
    assert sealed is not None
    wrong = _id(f"corrupt-{corruption}")
    with context.database._connection() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        if corruption == "observation_request":
            connection.execute("DROP TRIGGER temporal_observation_no_update")
            connection.execute(
                """UPDATE temporal_observations SET completion_request_id=?
                   WHERE batch_id=?""",
                (wrong, sealed.seal_draft.observation_batch.batch_id),
            )
        elif corruption == "draft_request":
            connection.execute("DROP TRIGGER temporal_seal_draft_no_update")
            connection.execute(
                """UPDATE temporal_seal_drafts SET completion_request_id=?
                   WHERE seal_draft_id=?""",
                (wrong, sealed.seal_draft.seal_draft_id),
            )
        elif corruption == "draft_batch":
            connection.execute("DROP TRIGGER temporal_seal_draft_no_update")
            connection.execute(
                """UPDATE temporal_seal_drafts SET batch_id=?
                   WHERE seal_draft_id=?""",
                (wrong, sealed.seal_draft.seal_draft_id),
            )
        elif corruption == "selection_key_ordinal":
            connection.execute("DROP TRIGGER temporal_metric_selection_key_no_update")
            connection.execute(
                """UPDATE temporal_metric_selection_keys SET ordinal=1
                   WHERE selection_revision_id=?""",
                (
                    context.scope.selection_revision.selection_revision_id,
                ),
            )
        elif corruption == "scope_operation":
            connection.execute("DROP TRIGGER temporal_prepared_scope_no_update")
            connection.execute(
                """UPDATE temporal_prepared_scope_roots SET operation_id=?
                   WHERE prepared_scope_id=?""",
                (wrong, context.scope.prepared_scope_id),
            )
        elif corruption == "snapshot_operation":
            connection.execute("DROP TRIGGER temporal_grant_snapshot_no_update")
            connection.execute(
                """UPDATE temporal_automation_grant_snapshots SET operation_id=?
                   WHERE selection_revision_id=?""",
                (
                    wrong,
                    context.scope.selection_revision.selection_revision_id,
                ),
            )
        elif corruption == "selection_operation":
            connection.execute("DROP TRIGGER temporal_metric_selection_no_update")
            connection.execute(
                """UPDATE temporal_metric_selection_drafts SET operation_id=?
                   WHERE selection_revision_id=?""",
                (
                    wrong,
                    context.scope.selection_revision.selection_revision_id,
                ),
            )
        else:
            connection.execute("DROP TRIGGER temporal_history_root_no_update")
            connection.execute(
                """UPDATE temporal_history_root_drafts SET operation_id=?
                   WHERE root_receipt_id=?""",
                (wrong, context.scope.history_root.root_receipt_id),
            )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_sealed_batch(sealed.sealed_batch_id)


def test_prepared_hydration_rejects_snapshot_and_scope_tamper(tmp_path) -> None:
    database = Database(tmp_path / "prepared-corruption.sqlite3")
    database.initialize()
    context = _prepare(database)
    with database._connection() as connection:
        connection.executescript(
            """DROP TRIGGER temporal_grant_snapshot_no_update;
               DROP TRIGGER temporal_prepared_scope_no_update;"""
        )
        connection.execute(
            """UPDATE temporal_automation_grant_snapshots
               SET max_cpu_workers=max_cpu_workers+1
               WHERE selection_revision_id=?""",
            (context.scope.selection_revision.selection_revision_id,),
        )
        connection.execute(
            """UPDATE temporal_prepared_scope_roots
               SET prepared_scope_fingerprint=? WHERE prepared_scope_id=?""",
            (_id("tampered-prepared-scope"), context.scope.prepared_scope_id),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError):
        context.temporal.get_prepared_scope(context.scope.prepared_scope_id)
