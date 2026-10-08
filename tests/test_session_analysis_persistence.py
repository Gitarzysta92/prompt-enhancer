from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3
from threading import Event

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_PACK_KEY,
    DEFAULT_TEXT_METRIC_PACK_VERSION,
    TEXT_METRIC_ALGORITHM_ID,
    TEXT_METRIC_ALGORITHM_VERSION,
    TEXT_METRIC_DEFINITIONS,
    TEXT_METRIC_ENGINE_VERSION,
)
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    MetricDirection,
    TEXT_METRIC_SCHEMA_VERSION,
    TextMetricDefinition,
)
from prompt_enhancer.application.analysis.session_quality_aggregation import (
    SessionQualityAggregationService,
    SessionQualityCompatibilityState,
    SessionQualitySelection,
)
from prompt_enhancer.application.analysis.session_text_service import (
    SessionTextAnalysisOutcome,
    SessionTextAnalysisPersistenceError,
)
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantService,
    AutomationGrantScope,
    AutomationGrantState,
    SessionQualityAutomationHandler,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobService,
    AnalysisJobState,
    AnalysisJobWorker,
    PowerSourceState,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisSignalRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
    SessionMetricSignalStatus,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    TaskRevisionRecord,
)
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseInvariantError,
    _MIGRATION_1,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import DataTier, MetricObservation, MetricSource, Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.infrastructure.sqlite.migrations import (
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    MIGRATION_6,
    MIGRATION_7,
    MIGRATION_8,
    MIGRATION_9,
    MIGRATION_10,
    MIGRATION_11,
    MIGRATION_12,
    MIGRATION_13,
)
from prompt_enhancer.infrastructure.automation import QueueAutomationJobSink


NOW = datetime(2040, 1, 2, 10, 0, tzinfo=UTC)


class _ExternalPower:
    def current(self) -> PowerSourceState:
        return PowerSourceState.EXTERNAL_POWER
EXAMPLE_TOKEN = "example_session_analysis_token_1234567890"
AGGREGATION_FILTER = {
    "analysis_profile_key": "standard_engineering",
    "analysis_profile_version": 1,
    "metric_pack_key": DEFAULT_TEXT_METRIC_PACK_KEY,
    "metric_pack_version": DEFAULT_TEXT_METRIC_PACK_VERSION,
}


def _create_v7_analysis_run(path) -> str:
    migrations = (
        (1, _MIGRATION_1),
        (2, MIGRATION_2),
        (3, MIGRATION_3),
        (4, MIGRATION_4),
        (5, MIGRATION_5),
        (6, MIGRATION_6),
        (7, MIGRATION_7),
    )
    installation_id, project_id, session_id, run_id = (
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "4" * 64,
    )
    timestamp = NOW.isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for _, script in migrations:
            connection.executescript(script)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO schema_migrations(version, checksum, applied_at)
            VALUES (?, ?, ?)
            """,
            tuple(
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    timestamp,
                )
                for version, script in migrations
            ),
        )
        connection.execute(
            "INSERT INTO installations(installation_id, provider, created_at) VALUES (?, ?, ?)",
            (installation_id, "synthetic", timestamp),
        )
        connection.execute(
            "INSERT INTO projects(project_id, installation_id, provider, created_at) VALUES (?, ?, ?, ?)",
            (project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id, installation_id, project_id, provider,
                provider_version, adapter_version, source_schema_version,
                started_at, ended_at, terminal_state, events_complete,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            INSERT INTO session_analysis_runs(
                run_id, session_id, request_fingerprint, input_fingerprint,
                metric_pack_key, metric_pack_version, data_tier,
                consent_purpose, consent_policy_version, provider,
                provider_version, adapter_version, source_schema_version,
                content_schema_version, metric_engine_version, redactor_version,
                model_plan_fingerprint, schema_version, local_only, started_at,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'running')
            """,
            (
                run_id,
                session_id,
                "5" * 64,
                "6" * 64,
                DEFAULT_TEXT_METRIC_PACK_KEY,
                DEFAULT_TEXT_METRIC_PACK_VERSION,
                "redacted_content",
                "text_analysis",
                "explicit-session-text-analysis-v1",
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-schema-v1",
                "redacted-message-v1",
                TEXT_METRIC_ENGINE_VERSION,
                "deterministic-redactor-v1",
                "7" * 64,
                7,
                timestamp,
            ),
        )
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
    return run_id


def _database_and_session(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    return database, session_id


def _create_v12_scope_runs(
    path,
    *,
    duplicate_versions: bool = False,
) -> tuple[str, str, str, str, str, str, str, str, str]:
    migrations = (
        (1, _MIGRATION_1),
        (2, MIGRATION_2),
        (3, MIGRATION_3),
        (4, MIGRATION_4),
        (5, MIGRATION_5),
        (6, MIGRATION_6),
        (7, MIGRATION_7),
        (8, MIGRATION_8),
        (9, MIGRATION_9),
        (10, MIGRATION_10),
        (11, MIGRATION_11),
        (12, MIGRATION_12),
    )
    installation_id, project_id, session_id = "1" * 64, "2" * 64, "3" * 64
    subset_run_id = "4" * 64
    failed_standard_run_id = "5" * 64
    failed_explicit_run_id = "6" * 64
    failed_coaching_run_id = "7" * 64
    unknown_run_id = "8" * 64
    ambiguous_v12_run_id = "9" * 64
    full_v11_run_id = "d" * 64
    incomplete_v11_run_id = "e" * 64
    foreign_v12_run_id = "f" * 64
    timestamp = NOW.isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for version, script in migrations:
            connection.executescript(script)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, checksum, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    timestamp,
                ),
            )
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()
        connection.execute(
            "INSERT INTO installations(installation_id, provider, created_at) VALUES (?, ?, ?)",
            (installation_id, "synthetic", timestamp),
        )
        connection.execute(
            "INSERT INTO projects(project_id, installation_id, provider, created_at) VALUES (?, ?, ?, ?)",
            (project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id, installation_id, project_id, provider,
                provider_version, adapter_version, source_schema_version,
                started_at, ended_at, terminal_state, events_complete,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'synthetic', ?, ?, ?, ?, ?, 'completed', 1, ?, ?)
            """,
            (
                session_id,
                installation_id,
                project_id,
                "synthetic-v1",
                "synthetic-adapter-v1",
                "synthetic-schema-v1",
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )

        def insert_running(
            run_id: str,
            profile_key: str,
            pack_key: str,
            pack_version: int,
            schema_version: int = 12,
        ) -> None:
            connection.execute(
                """
                INSERT INTO session_analysis_runs(
                    run_id, session_id, request_fingerprint, input_fingerprint,
                    metric_pack_key, metric_pack_version, data_tier,
                    consent_purpose, consent_policy_version, provider,
                    provider_version, adapter_version, source_schema_version,
                    content_schema_version, metric_engine_version,
                    redactor_version, model_plan_fingerprint, schema_version,
                    local_only, started_at, status, analysis_profile_key,
                    analysis_profile_version
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'redacted_content', 'text_analysis',
                    'synthetic-consent-v1', 'synthetic', 'synthetic-v1',
                    'synthetic-adapter-v1', 'synthetic-schema-v1',
                    'redacted-message-v1', 'synthetic-engine-v1',
                    'synthetic-redactor-v1', ?, ?, 1, ?, 'running', ?, 1
                )
                """,
                (
                    run_id,
                    session_id,
                    "7" * 64,
                    "8" * 64,
                    pack_key,
                    pack_version,
                    "9" * 64,
                    schema_version,
                    timestamp,
                    profile_key,
                ),
            )

        def insert_result(
            run_id: str,
            metric_key: str,
            *,
            versions: tuple[int, ...] = (1,),
        ) -> None:
            for version in versions:
                definition_identity = f"{metric_key}:{version}"
                connection.execute(
                    """
                    INSERT OR IGNORE INTO metric_definitions(
                        key, version, dimension, display_name, description, unit,
                        source, algorithm_version, definition_checksum
                    ) VALUES (?, ?, 'synthetic', 'Synthetic metric',
                              'Reserved synthetic migration fixture.', 'ratio',
                              'deterministic', '1', ?)
                    """,
                    (
                        metric_key,
                        version,
                        hashlib.sha256(
                            definition_identity.encode("utf-8")
                        ).hexdigest(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO session_analysis_results(
                        run_id, key, version, metric_schema_version, value_state,
                        numeric_value, unit, source, direction, applicability,
                        aggregation_method, fraction_numerator,
                        fraction_denominator, observed_count, eligible_count,
                        coverage, confidence, evidence_data_tier,
                        explanation_code, error_code, algorithm_id,
                        algorithm_version, model_id, model_revision, model_license,
                        tokenizer_id, prompt_version, rubric_version, computed_at
                    ) VALUES (
                        ?, ?, ?, 2, 'known', 1.0, 'ratio', 'deterministic',
                        'higher_is_better', 'applicable', 'ratio_of_sums', 1, 1,
                        1, 1, 1.0, NULL, 'redacted_content', 'legacy_fixture',
                        NULL, 'legacy.algorithm', '1', NULL, NULL, NULL, NULL,
                        NULL, 'legacy-rubric-v1', ?
                    )
                    """,
                    (run_id, metric_key, version, timestamp),
                )
        def complete(run_id: str) -> None:
            connection.execute(
                """
                UPDATE session_analysis_runs
                SET status = 'completed', finished_at = ?
                WHERE run_id = ?
                """,
                (timestamp, run_id),
            )

        def complete_with_result(
            run_id: str,
            metric_key: str,
            *,
            versions: tuple[int, ...] = (1,),
        ) -> None:
            insert_result(run_id, metric_key, versions=versions)
            complete(run_id)

        insert_running(
            subset_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
        )
        complete_with_result(
            subset_run_id,
            "prompt.context_sufficiency",
            versions=(1, 99) if duplicate_versions else (1,),
        )

        def fail(run_id: str) -> None:
            connection.execute(
                """
                UPDATE session_analysis_runs
                SET status = 'failed', finished_at = ?,
                    failure_code = 'synthetic_failure'
                WHERE run_id = ?
                """,
                (timestamp, run_id),
            )

        insert_running(
            failed_standard_run_id,
            "standard_engineering",
            DEFAULT_TEXT_METRIC_PACK_KEY,
            DEFAULT_TEXT_METRIC_PACK_VERSION,
            schema_version=11,
        )
        fail(failed_standard_run_id)
        insert_running(
            failed_explicit_run_id,
            "explicit.user-profile",
            DEFAULT_TEXT_METRIC_PACK_KEY,
            DEFAULT_TEXT_METRIC_PACK_VERSION,
            schema_version=11,
        )
        fail(failed_explicit_run_id)
        insert_running(
            failed_coaching_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
            schema_version=11,
        )
        fail(failed_coaching_run_id)
        insert_running(
            ambiguous_v12_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
        )
        fail(ambiguous_v12_run_id)
        insert_running(unknown_run_id, "unknown_profile", "unknown.pack", 1)
        complete_with_result(unknown_run_id, "unknown.metric")
        insert_running(
            incomplete_v11_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
            schema_version=11,
        )
        complete_with_result(
            incomplete_v11_run_id,
            "prompt.context_sufficiency",
        )
        insert_running(
            full_v11_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
            schema_version=11,
        )
        for definition in COACHING_METRIC_DEFINITIONS:
            insert_result(full_v11_run_id, definition.key, versions=(99,))
        complete(full_v11_run_id)
        insert_running(
            foreign_v12_run_id,
            "coaching_profile",
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
        )
        insert_result(foreign_v12_run_id, "prompt.context_sufficiency")
        insert_result(foreign_v12_run_id, "synthetic.foreign_metric")
        complete(foreign_v12_run_id)
        connection.commit()
    return (
        subset_run_id,
        failed_standard_run_id,
        failed_explicit_run_id,
        failed_coaching_run_id,
        unknown_run_id,
        ambiguous_v12_run_id,
        full_v11_run_id,
        incomplete_v11_run_id,
        foreign_v12_run_id,
    )


def _draft(
    session_id: str,
    identity: str = "a",
    *,
    started_at: datetime = NOW,
    selected_metric_keys: tuple[str, ...] = ("prompt.goal_definition",),
):
    return SessionAnalysisRunDraft(
        run_id=identity * 64,
        session_id=session_id,
        request_fingerprint="f" * 64,
        input_fingerprint="b" * 64,
        analysis_profile_key="standard_engineering",
        analysis_profile_version=1,
        metric_pack_key=DEFAULT_TEXT_METRIC_PACK_KEY,
        metric_pack_version=DEFAULT_TEXT_METRIC_PACK_VERSION,
        selected_metric_keys=tuple(sorted(selected_metric_keys)),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version="explicit-session-text-analysis-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-schema-v1",
        content_schema_version="redacted-message-v1",
        metric_engine_version=TEXT_METRIC_ENGINE_VERSION,
        redactor_version="deterministic-redactor-v1",
        model_plan_fingerprint="c" * 64,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        started_at=started_at,
    )


def _known_result(
    *,
    key: str = "prompt.goal_definition",
    direction: SessionMetricDirection = SessionMetricDirection.HIGHER_IS_BETTER,
    model_id: str | None = None,
    model_revision: str | None = None,
    model_license: str | None = None,
    tokenizer_id: str | None = None,
    prompt_version: str | None = None,
    rubric_version: str | None = "prompt-logic-rubric-v1",
) -> SessionAnalysisResultRecord:
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=key,
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
        direction=direction,
        applicability=SessionMetricApplicability.APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=2,
        fraction_denominator=3,
        evidence=(
            SessionAnalysisEvidenceRecord(
                message_id="d" * 64,
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
                code="goal.target",
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
        model_id=model_id,
        model_revision=model_revision,
        model_license=model_license,
        tokenizer_id=tokenizer_id,
        prompt_version=prompt_version,
        rubric_version=rubric_version,
        computed_at=NOW + timedelta(minutes=1),
    )


def _automation_queued_fixture(tmp_path):  # type: ignore[no-untyped-def]
    database, session_id = _database_and_session(tmp_path)
    session = next(
        item
        for item in database.list_sessions(limit=10)
        if item["session_id"] == session_id
    )
    metric_keys = ("prompt.goal_definition",)
    grant_id = "6" * 64
    database.automation_grant_repository().create(
        AutomationGrantDraft(
            grant_id=grant_id,
            scope=AutomationGrantScope(
                provider=Provider.SYNTHETIC,
                project_id=str(session["project_id"]),
                metric_keys=metric_keys,
            ),
            created_at=NOW,
            expires_at=NOW + AUTOMATION_GRANT_LIFETIME,
        )
    )
    job_repository = database.analysis_job_repository()
    job_service = AnalysisJobService(job_repository, clock=lambda: NOW)
    queued = job_service.enqueue(
        AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.SYNTHETIC,
            project_id=str(session["project_id"]),
            session_id=session_id,
            input_fingerprint="1" * 64,
            provenance_fingerprint="2" * 64,
            metric_keys=metric_keys,
            estimator_plan_version="synthetic-plan-v1",
            redactor_version="synthetic-redactor-v1",
            provider_schema_version="synthetic-schema-v1",
            automation_grant_id=grant_id,
        )
    ).job
    run_repository = database.session_analysis_run_repository()
    draft = _draft(
        session_id,
        identity="5",
        started_at=NOW,
        selected_metric_keys=metric_keys,
    ).model_copy(
        update={
            "analysis_profile_key": "coaching_profile",
            "analysis_profile_version": 1,
            "metric_pack_key": COACHING_METRIC_PACK_KEY,
            "metric_pack_version": COACHING_METRIC_PACK_VERSION,
            "redactor_version": "synthetic-redactor-v1",
        }
    )
    result = _known_result()
    return (
        database,
        job_service,
        job_repository,
        queued,
        run_repository,
        draft,
        result,
        grant_id,
    )


def _automation_completion_fixture(tmp_path):  # type: ignore[no-untyped-def]
    (
        database,
        job_service,
        job_repository,
        queued,
        run_repository,
        draft,
        result,
        grant_id,
    ) = _automation_queued_fixture(tmp_path)
    claimed = job_repository.claim_next(
        owner="3" * 64,
        token="4" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=5),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == queued.job_id
    assert claimed.lease_owner is not None
    assert claimed.lease_token is not None
    assert claimed.lease_expires_at is not None
    lease = AnalysisJobLease(
        job_id=claimed.job_id,
        owner=claimed.lease_owner,
        token=claimed.lease_token,
        expires_at=claimed.lease_expires_at,
    )
    staged = job_repository.advance_stage(
        lease,
        now=NOW,
        stage_number=2,
        progress_completed=0,
        progress_total=1,
    )
    assert staged.lease_owner is not None and staged.lease_token is not None
    authority = SessionAnalysisCompletionAuthority(
        job_id=staged.job_id,
        automation_grant_id=grant_id,
        lease_owner=staged.lease_owner,
        lease_token=staged.lease_token,
    )
    run_repository.begin(draft, completion_authority=authority)
    return (
        database,
        job_service,
        job_repository,
        lease,
        run_repository,
        draft,
        result,
        authority,
        grant_id,
    )


class _RepositoryBackedBlockingAnalysis:
    """Synthetic compute seam that exercises the real atomic result repository."""

    def __init__(
        self,
        repository,  # type: ignore[no-untyped-def]
        draft: SessionAnalysisRunDraft,
        result: SessionAnalysisResultRecord,
    ) -> None:
        self._repository = repository
        self._draft = draft
        self._result = result
        self.compute_started = Event()
        self.release_compute = Event()

    def run_preset(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: object,
        confirmation: str,
        idempotency_key: str,
        selected_metric_keys: tuple[str, ...],
        completion_authority: SessionAnalysisCompletionAuthority,
        cooperative_check: Callable[[], None],
        publication_committed_callback: Callable[[], None],
    ) -> SessionTextAnalysisOutcome:
        del preset_id, confirmation, idempotency_key
        assert provider is self._draft.provider
        assert session_id == self._draft.session_id
        assert selected_metric_keys == self._draft.selected_metric_keys
        cooperative_check()
        self._repository.begin(
            self._draft,
            completion_authority=completion_authority,
        )
        cooperative_check()
        self.compute_started.set()
        assert self.release_compute.wait(timeout=5)
        cooperative_check()
        try:
            self._repository.complete(
                self._draft.run_id,
                (self._result,),
                finished_at=NOW + timedelta(minutes=1),
                completion_authority=completion_authority,
            )
        except DatabaseInvariantError:
            self._repository.fail(
                self._draft.run_id,
                finished_at=NOW + timedelta(minutes=1),
                failure_code="automation_authorization_revoked",
            )
            raise SessionTextAnalysisPersistenceError(
                "analysis results could not be stored"
            ) from None
        publication_committed_callback()
        return SessionTextAnalysisOutcome(
            run_id=self._draft.run_id,
            status=AnalysisRunStatus.COMPLETED,
            result_count=1,
            applied=True,
            analysis_profile_key=self._draft.analysis_profile_key,
            analysis_profile_version=self._draft.analysis_profile_version,
        )


def _revocation_service(
    database,  # type: ignore[no-untyped-def]
    jobs,  # type: ignore[no-untyped-def]
    *,
    now: datetime = NOW + timedelta(seconds=30),
):  # type: ignore[no-untyped-def]
    """Build only the real revocation path; other scheduler ports stay unused."""

    return AutomationGrantService(
        database.automation_grant_repository(),
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        QueueAutomationJobSink(
            jobs,
            estimator_plan_version="synthetic-plan-v1",
            redactor_version="synthetic-redactor-v1",
        ),
        None,  # type: ignore[arg-type]
        clock=lambda: now,
    )


def test_revocation_during_compute_rejects_result_commit_atomically(tmp_path) -> None:
    (
        database,
        job_service,
        job_repository,
        lease,
        run_repository,
        draft,
        result,
        authority,
        grant_id,
    ) = _automation_completion_fixture(tmp_path)
    compute_started = Event()
    release_compute = Event()

    def finish_after_compute() -> str:
        compute_started.set()
        assert release_compute.wait(timeout=5)
        try:
            run_repository.complete(
                draft.run_id,
                (result,),
                finished_at=NOW + timedelta(minutes=1),
                completion_authority=authority,
            )
        except DatabaseInvariantError:
            run_repository.fail(
                draft.run_id,
                finished_at=NOW + timedelta(minutes=1),
                failure_code="automation_authorization_revoked",
            )
            return "rejected"
        return "committed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(finish_after_compute)
        assert compute_started.wait(timeout=5)
        _revocation_service(database, job_service).revoke(grant_id)
        release_compute.set()
        assert future.result(timeout=5) == "rejected"

    terminal_job = job_repository.finish(
        lease,
        now=NOW + timedelta(minutes=1),
        state=AnalysisJobState.COMPLETED,
        reason_code="local_analysis_completed",
        progress_completed=1,
        progress_total=1,
    )
    stored = run_repository.get(draft.run_id)
    assert terminal_job.state is AnalysisJobState.CANCELLED
    assert stored is not None and stored.status is AnalysisRunStatus.FAILED
    assert run_repository.get_results(draft.run_id) == ()


def test_worker_revocation_during_compute_cannot_publish_results(tmp_path) -> None:
    (
        database,
        job_service,
        job_repository,
        queued,
        run_repository,
        draft,
        result,
        grant_id,
    ) = _automation_queued_fixture(tmp_path)
    analyses = _RepositoryBackedBlockingAnalysis(run_repository, draft, result)

    def authorization_check(job):  # type: ignore[no-untyped-def]
        grant = database.automation_grant_repository().get(
            job.identity.automation_grant_id
        )
        return grant is not None and grant.state is AutomationGrantState.ACTIVE

    worker = AnalysisJobWorker(
        job_repository,
        {
            (AnalysisJobKind.SESSION_QUALITY, Provider.SYNTHETIC): (
                SessionQualityAutomationHandler(analyses)  # type: ignore[arg-type]
            )
        },
        authorization_check=authorization_check,
        fingerprint_resolver=lambda job: (
            job.identity.input_fingerprint,
            job.identity.provenance_fingerprint,
        ),
        power_source=_ExternalPower(),
        clock=lambda: NOW,
        lease_duration=timedelta(minutes=5),
        worker_id="3" * 64,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker.run_once)
        assert analyses.compute_started.wait(timeout=5)
        revoked = _revocation_service(database, job_service).revoke(grant_id)
        analyses.release_compute.set()
        assert future.result(timeout=5) is True

    terminal_job = job_repository.get(queued.job_id)
    stored = run_repository.get(draft.run_id)
    assert revoked.state is AutomationGrantState.REVOKED
    assert terminal_job is not None
    assert terminal_job.state is AnalysisJobState.CANCELLED
    assert stored is not None and stored.status is AnalysisRunStatus.FAILED
    assert run_repository.get_results(draft.run_id) == ()


def test_completion_wins_before_later_revocation_and_keeps_ordered_evidence(
    tmp_path,
) -> None:
    (
        database,
        job_service,
        job_repository,
        lease,
        run_repository,
        draft,
        result,
        authority,
        grant_id,
    ) = _automation_completion_fixture(tmp_path)
    result = result.model_copy(
        update={
            "evidence": (
                SessionAnalysisEvidenceRecord(
                    message_id="e" * 64,
                    origin=SessionEvidenceOrigin.INHERITED,
                ),
                *result.evidence,
            )
        }
    )
    finished_at = NOW + timedelta(minutes=1)
    run_repository.complete(
        draft.run_id,
        (result,),
        finished_at=finished_at,
        completion_authority=authority,
    )
    completed_job = job_repository.finish(
        lease,
        now=finished_at,
        state=AnalysisJobState.COMPLETED,
        reason_code="local_analysis_completed",
        progress_completed=1,
        progress_total=1,
    )
    revoked = _revocation_service(
        database,
        job_service,
        now=finished_at + timedelta(seconds=1),
    ).revoke(grant_id)

    stored = run_repository.get(draft.run_id)
    persisted = run_repository.get_results(draft.run_id)
    assert completed_job.state is AnalysisJobState.COMPLETED
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    assert len(persisted) == 1
    assert revoked.revoked_at is not None
    assert persisted[0].computed_at <= revoked.revoked_at
    assert persisted[0].evidence == result.evidence
    assert persisted[0].signals == result.signals


def _not_applicable_result() -> SessionAnalysisResultRecord:
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key="logic.plan_state_accounting",
            version=1,
            numeric_value=None,
            unit="ratio",
            source=MetricSource.DETERMINISTIC,
            observed_count=0,
            eligible_count=0,
            coverage=0.0,
            confidence=None,
        ),
        value_state=MetricValueState.NOT_APPLICABLE,
        direction=SessionMetricDirection.HIGHER_IS_BETTER,
        applicability=SessionMetricApplicability.NOT_APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        explanation_code="no_explicit_plan",
        algorithm_id=TEXT_METRIC_ALGORITHM_ID,
        algorithm_version=TEXT_METRIC_ALGORITHM_VERSION,
        rubric_version="prompt-logic-rubric-v1",
        computed_at=NOW + timedelta(minutes=1),
    )


def test_v8_migration_marks_legacy_analysis_profile_without_guessing(tmp_path) -> None:
    path = tmp_path / "legacy-metrics.sqlite3"
    run_id = _create_v7_analysis_run(path)

    database = Database(path)
    database.initialize()
    stored = database.session_analysis_run_repository().get(run_id)

    assert stored is not None
    assert stored.draft.analysis_profile_key == "legacy.explicit-profile"
    assert stored.draft.analysis_profile_version == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_result_signals"
        ).fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute(
                """
                UPDATE session_analysis_runs
                SET analysis_profile_key = 'standard_engineering'
                WHERE run_id = ?
                """,
                (run_id,),
            )


def test_v14_repairs_unprovable_v13_metric_scopes(tmp_path) -> None:
    path = tmp_path / "scope-migration.sqlite3"
    (
        subset_run_id,
        failed_standard_run_id,
        failed_explicit_run_id,
        failed_coaching_run_id,
        unknown_run_id,
        ambiguous_v12_run_id,
        full_v11_run_id,
        incomplete_v11_run_id,
        foreign_v12_run_id,
    ) = _create_v12_scope_runs(path)

    # Reproduce the already-published schema-13 state and checksum before the
    # repair migration runs. Migration 13 intentionally remains byte-stable.
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATION_13)
        connection.execute(
            """
            INSERT INTO schema_migrations(version, checksum, applied_at)
            VALUES (13, ?, ?)
            """,
            (hashlib.sha256(MIGRATION_13.encode("utf-8")).hexdigest(), NOW.isoformat()),
        )
        connection.execute("PRAGMA user_version = 13")
        connection.commit()
        assert connection.execute(
            """
            SELECT metric_scope_state FROM session_analysis_runs
            WHERE run_id = ?
            """,
            (incomplete_v11_run_id,),
        ).fetchone()[0] == "exact"
        assert connection.execute(
            """
            SELECT metric_scope_state FROM session_analysis_runs
            WHERE run_id = ?
            """,
            (foreign_v12_run_id,),
        ).fetchone()[0] == "exact"

    database = Database(path)
    database.initialize()
    repository = database.session_analysis_run_repository()
    subset = repository.get(subset_run_id)
    failed_standard = repository.get(failed_standard_run_id)
    failed_explicit = repository.get(failed_explicit_run_id)
    failed_coaching = repository.get(failed_coaching_run_id)
    unknown = repository.get(unknown_run_id)
    ambiguous_v12 = repository.get(ambiguous_v12_run_id)
    full_v11 = repository.get(full_v11_run_id)
    incomplete_v11 = repository.get(incomplete_v11_run_id)
    foreign_v12 = repository.get(foreign_v12_run_id)

    assert subset is not None
    assert subset.draft.metric_scope_state is SessionMetricScopeState.EXACT
    assert subset.draft.selected_metric_keys == ("prompt.context_sufficiency",)
    expected_standard = tuple(
        sorted(definition.key for definition in TEXT_METRIC_DEFINITIONS)
    )
    expected_coaching = tuple(
        sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
    )
    assert failed_standard is not None
    assert failed_explicit is not None
    assert failed_coaching is not None
    assert all(
        run.draft.metric_scope_state is SessionMetricScopeState.EXACT
        for run in (failed_standard, failed_explicit, failed_coaching)
    )
    assert failed_standard.draft.selected_metric_keys == expected_standard
    assert failed_explicit.draft.selected_metric_keys == expected_standard
    assert failed_coaching.draft.selected_metric_keys == expected_coaching
    assert unknown is not None
    assert ambiguous_v12 is not None
    assert (
        unknown.draft.metric_scope_state
        is SessionMetricScopeState.LEGACY_UNKNOWN
    )
    assert unknown.draft.selected_metric_keys == ()
    assert (
        ambiguous_v12.draft.metric_scope_state
        is SessionMetricScopeState.LEGACY_UNKNOWN
    )
    assert ambiguous_v12.draft.selected_metric_keys == ()
    assert full_v11 is not None
    assert full_v11.draft.metric_scope_state is SessionMetricScopeState.EXACT
    assert full_v11.draft.selected_metric_keys == expected_coaching
    assert incomplete_v11 is not None
    assert (
        incomplete_v11.draft.metric_scope_state
        is SessionMetricScopeState.LEGACY_UNKNOWN
    )
    assert incomplete_v11.draft.selected_metric_keys == ()
    assert foreign_v12 is not None
    assert (
        foreign_v12.draft.metric_scope_state
        is SessionMetricScopeState.LEGACY_UNKNOWN
    )
    assert foreign_v12.draft.selected_metric_keys == ()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute(
            "SELECT COUNT(*) FROM session_analysis_run_metrics"
        ).fetchone()[0] == 61


def test_v13_collapses_legacy_metric_versions_to_one_scope_key(tmp_path) -> None:
    path = tmp_path / "multi-version-scope.sqlite3"
    subset_run_id, *_rest = _create_v12_scope_runs(
        path,
        duplicate_versions=True,
    )

    database = Database(path)
    database.initialize()
    repository = database.session_analysis_run_repository()
    run = repository.get(subset_run_id)

    assert run is not None
    assert run.draft.metric_scope_state is SessionMetricScopeState.EXACT
    assert run.draft.selected_metric_keys == ("prompt.context_sufficiency",)
    assert len(repository.get_results(subset_run_id)) == 2
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM session_analysis_run_metrics
            WHERE run_id = ?
            """,
            (subset_run_id,),
        ).fetchone()[0] == 1


def test_backfilled_v12_and_new_v13_runs_share_result_level_cohort(tmp_path) -> None:
    path = tmp_path / "storage-version-cohort.sqlite3"
    subset_run_id, *_rest = _create_v12_scope_runs(path)
    database = Database(path)
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    new_session_id = next(
        row["session_id"]
        for row in database.list_sessions(limit=10)
        if row["session_id"] != "3" * 64
    )
    repository = database.session_analysis_run_repository()
    old = repository.get(subset_run_id)
    assert old is not None and old.draft.schema_version == 12
    draft = SessionAnalysisRunDraft(
        run_id="a" * 64,
        session_id=new_session_id,
        request_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=("prompt.context_sufficiency",),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version="synthetic-consent-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-schema-v1",
        content_schema_version="redacted-message-v1",
        metric_engine_version="synthetic-engine-v1",
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint="d" * 64,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        started_at=NOW + timedelta(minutes=10),
    )
    result = _known_result(key="prompt.context_sufficiency").model_copy(
        update={
            "algorithm_id": "legacy.algorithm",
            "algorithm_version": "1",
            "rubric_version": "legacy-rubric-v1",
            "computed_at": NOW + timedelta(minutes=11),
        }
    )
    repository.begin(draft)
    repository.complete(
        draft.run_id,
        (result,),
        finished_at=NOW + timedelta(minutes=12),
    )
    definition = TextMetricDefinition(
        key="prompt.context_sufficiency",
        version=1,
        dimension="prompt",
        display_name="Context sufficiency",
        description="Reserved synthetic storage-version comparison metric.",
        unit="ratio",
        direction=MetricDirection.HIGHER_IS_BETTER,
    )

    aggregate = SessionQualityAggregationService(
        repository,
        definitions=(definition,),
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
    ).aggregate(
        SessionQualitySelection(session_ids=("3" * 64, new_session_id))
    )
    metric = aggregate.metrics[0]

    assert old.draft.model_plan_fingerprint != draft.model_plan_fingerprint
    assert (
        metric.compatibility_state
        is SessionQualityCompatibilityState.COMPATIBLE
    ), metric.model_dump()
    assert len(metric.compatibility_cohorts) == 1
    assert metric.compatibility_cohorts[0].result_count == 2


def test_session_quality_snapshot_is_immutable_and_privacy_deletion_cascades(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(
        session_id,
        selected_metric_keys=(
            "logic.plan_state_accounting",
            "prompt.goal_definition",
        ),
    )
    known = _known_result()
    not_applicable = _not_applicable_result()

    repository.begin(draft)
    repository.complete(
        draft.run_id,
        (known, not_applicable),
        finished_at=NOW + timedelta(minutes=2),
    )

    stored = repository.get(draft.run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.COMPLETED
    assert repository.get_latest_completed(session_id) == stored
    assert repository.get_latest_for_profile(
        session_id,
        analysis_profile_key=draft.analysis_profile_key,
        analysis_profile_version=draft.analysis_profile_version,
        metric_pack_key=draft.metric_pack_key,
        metric_pack_version=draft.metric_pack_version,
    ) == stored
    assert repository.get_latest_for_profile(
        session_id,
        analysis_profile_key="different_profile",
        analysis_profile_version=1,
        metric_pack_key=draft.metric_pack_key,
        metric_pack_version=draft.metric_pack_version,
    ) is None
    assert repository.list_for_session(session_id) == (stored,)
    assert repository.get_results(draft.run_id) == (not_applicable, known)
    round_tripped_known = repository.get_results(draft.run_id)[1]
    assert round_tripped_known.fraction_numerator == 2
    assert round_tripped_known.fraction_denominator == 3
    assert round_tripped_known.observation.observed_count == 3
    assert round_tripped_known.observation.eligible_count == 4
    assert tuple(signal.code for signal in round_tripped_known.signals) == (
        "goal.action",
        "goal.target",
        "goal.outcome",
    )

    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_analysis_results SET numeric_value = 1 WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_analysis_result_signals SET signal_count = 0 WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM session_analysis_result_signals WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_analysis_result_evidence SET origin = 'inherited' WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM session_analysis_result_evidence WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM session_analysis_results WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM session_analysis_run_metrics WHERE run_id = ?",
                (draft.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute(
                "UPDATE session_analysis_runs SET adapter_version = 'changed-v2' WHERE run_id = ?",
                (draft.run_id,),
            )
        for column, value in (
            ("request_fingerprint", "1" * 64),
            ("input_fingerprint", "2" * 64),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="transition"):
                connection.execute(
                    f"UPDATE session_analysis_runs SET {column} = ? WHERE run_id = ?",
                    (value, draft.run_id),
                )

    assert repository.delete_for_privacy(draft.run_id) is True
    assert repository.get(draft.run_id) is None
    with sqlite3.connect(database.path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_analysis_runs",
                "session_analysis_run_metrics",
                "session_analysis_results",
                "session_analysis_result_evidence",
                "session_analysis_result_signals",
            )
        )
    assert counts == (0, 0, 0, 0, 0)


def test_completion_rejects_result_scope_drift_without_partial_persistence(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(session_id)
    repository.begin(draft)

    with pytest.raises(DatabaseInvariantError, match="selected metric scope"):
        repository.complete(
            draft.run_id,
            (_not_applicable_result(),),
            finished_at=NOW + timedelta(minutes=2),
        )

    stored = repository.get(draft.run_id)
    assert stored is not None and stored.status is AnalysisRunStatus.RUNNING
    assert repository.get_results(draft.run_id) == ()


def test_hybrid_model_provenance_round_trips_per_result(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(
        session_id,
        selected_metric_keys=(
            "logic.requirement_action_traceability",
            "logic.scoped_consistency_candidate_rate",
        ),
    )
    embedding_result = _known_result(
        key="logic.requirement_action_traceability",
        model_id="example/e5-small",
        model_revision="0123456789abcdef",
        model_license="mit",
        tokenizer_id="example/e5-small",
        rubric_version="traceability-rubric-v1",
    )
    nli_result = _known_result(
        key="logic.scoped_consistency_candidate_rate",
        direction=SessionMetricDirection.LOWER_IS_BETTER,
        model_id="example/mdeberta-nli",
        model_revision="fedcba9876543210",
        model_license="mit",
        tokenizer_id="example/mdeberta-nli",
        prompt_version=None,
        rubric_version="consistency-rubric-v1",
    )

    repository.begin(draft)
    repository.complete(
        draft.run_id,
        (embedding_result, nli_result),
        finished_at=NOW + timedelta(minutes=2),
    )

    by_key = {
        result.observation.key: result
        for result in repository.get_results(draft.run_id)
    }
    assert by_key["logic.requirement_action_traceability"].model_id == (
        "example/e5-small"
    )
    assert by_key["logic.scoped_consistency_candidate_rate"].model_id == (
        "example/mdeberta-nli"
    )
    assert all(result.prompt_version is None for result in by_key.values())


def test_authenticated_quality_reads_return_hybrid_profile_without_text(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(
        session_id,
        selected_metric_keys=(
            "logic.requirement_action_traceability",
            "logic.scoped_consistency_candidate_rate",
        ),
    )
    e5 = _known_result(
        key="logic.requirement_action_traceability",
        model_id="example/e5-small",
        model_revision="0123456789abcdef",
        model_license="mit",
        tokenizer_id="example/e5-small",
        rubric_version="traceability-rubric-v1",
    )
    nli = _known_result(
        key="logic.scoped_consistency_candidate_rate",
        direction=SessionMetricDirection.LOWER_IS_BETTER,
        model_id="example/mdeberta-nli",
        model_revision="fedcba9876543210",
        model_license="mit",
        tokenizer_id="example/mdeberta-nli",
        rubric_version="consistency-rubric-v1",
    )
    repository.begin(draft)
    repository.complete(
        draft.run_id,
        (e5, nli),
        finished_at=NOW + timedelta(minutes=2),
    )

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unauthorized = client.get(
            f"/v1/sessions/{session_id}/quality-analysis-runs/latest"
        )
        run_list = client.get(
            f"/v1/sessions/{session_id}/quality-analysis-runs",
            headers=headers,
        )
        latest = client.get(
            f"/v1/sessions/{session_id}/quality-analysis-runs/latest",
            headers=headers,
        )
        detail = client.get(
            f"/v1/quality-analysis/runs/{draft.run_id}",
            headers=headers,
        )

    assert unauthorized.status_code == 401
    assert run_list.status_code == latest.status_code == detail.status_code == 200
    assert run_list.json()["runs"][0]["request_fingerprint"] == "f" * 64
    assert latest.json() == detail.json()
    payload = detail.json()
    assert payload["run"]["input_fingerprint"] == "b" * 64
    assert payload["run"]["analysis_profile_key"] == "standard_engineering"
    assert payload["run"]["analysis_profile_version"] == 1
    assert payload["run"]["metric_scope_state"] == "exact"
    assert payload["run"]["selected_metric_keys"] == [
        "logic.requirement_action_traceability",
        "logic.scoped_consistency_candidate_rate",
    ]
    assert payload["run"]["model_plan_fingerprint"] == "c" * 64
    by_key = {result["key"]: result for result in payload["results"]}
    traceability = by_key["logic.requirement_action_traceability"]
    consistency = by_key["logic.scoped_consistency_candidate_rate"]
    assert traceability["dimension"] == "logic"
    assert traceability["display_name"] == "Requirement-to-action traceability"
    assert traceability["fraction"] == {"numerator": 2, "denominator": 3}
    assert traceability["signals"] == [
        {"code": "goal.action", "status": "detected", "count": 1},
        {"code": "goal.target", "status": "detected", "count": 1},
        {"code": "goal.outcome", "status": "missing", "count": 0},
    ]
    assert (traceability["observed_count"], traceability["eligible_count"]) == (3, 4)
    assert traceability["aggregation_method"] == "ratio_of_sums"
    assert traceability["model_id"] == "example/e5-small"
    assert consistency["model_id"] == "example/mdeberta-nli"
    serialized = detail.text.casefold()
    for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
        assert prohibited not in serialized


def test_authenticated_current_coaching_projection_uses_reviewed_task_context(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    session = database.get_session(session_id)
    assert session is not None
    draft = _draft(session_id).model_copy(
        update={
            "analysis_profile_key": "coaching_profile",
            "metric_pack_key": COACHING_METRIC_PACK_KEY,
            "metric_pack_version": COACHING_METRIC_PACK_VERSION,
            "metric_engine_version": COACHING_METRIC_ENGINE_VERSION,
            "selected_metric_keys": (
                "prompt.acceptance_testability",
                "prompt.deliverable_contract",
            ),
        }
    )
    deliverable = _known_result(key="prompt.deliverable_contract")
    deliverable = deliverable.model_copy(
        update={
            "observation": deliverable.observation.model_copy(
                update={
                    "version": 3,
                    "numeric_value": 1.0,
                    "observed_count": 12,
                    "eligible_count": 12,
                    "coverage": 1.0,
                    "confidence": None,
                }
            ),
            "fraction_numerator": 12,
            "fraction_denominator": 12,
            "algorithm_id": COACHING_METRIC_ALGORITHM_ID,
            "algorithm_version": COACHING_METRIC_ALGORITHM_VERSION,
            "rubric_version": "coaching-observables-rubric-2",
        }
    )
    acceptance = _known_result(key="prompt.acceptance_testability")
    acceptance = acceptance.model_copy(
        update={
            "observation": acceptance.observation.model_copy(
                update={
                    "version": 2,
                    "numeric_value": 0.0,
                    "observed_count": 12,
                    "eligible_count": 12,
                    "coverage": 1.0,
                    "confidence": None,
                }
            ),
            "fraction_numerator": 0,
            "fraction_denominator": 12,
            "algorithm_id": COACHING_METRIC_ALGORITHM_ID,
            "algorithm_version": COACHING_METRIC_ALGORITHM_VERSION,
            "rubric_version": "coaching-observables-rubric-2",
        }
    )
    analysis_repository = database.session_analysis_run_repository()
    analysis_repository.begin(draft)
    analysis_repository.complete(
        draft.run_id,
        (deliverable, acceptance),
        finished_at=NOW + timedelta(minutes=2),
    )
    database.task_repository().append_revision(
        TaskRevisionRecord(
            task_id="9" * 64,
            revision=1,
            project_id=session.project_id,
            task_type="feature_implementation",
            lifecycle_state="confirmed",
            session_ids=(session_id,),
            input_fingerprint="8" * 64,
            created_at=NOW,
        )
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )
    path = f"/v1/quality-analysis/runs/{draft.run_id}/coaching-summary"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unauthorized = client.get(path)
        response = client.get(path, headers={API_TOKEN_HEADER: EXAMPLE_TOKEN})

    assert unauthorized.status_code == 401
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["projection_key"] == "coaching.loop.current"
    assert body["task_type"] == "implementation"
    assert body["task_context_source"] == "reviewed_task"
    assert body["summary"]["outcome"]["status"] == "unknown"
    strength = body["summary"]["strength"]
    friction = body["summary"]["friction"]
    assert strength["code"] == "strength.deliverable_contract"
    assert strength["task_type"] == "implementation"
    assert strength["denominator_kind"] == "event_count"
    assert strength["polarity_successes"] == 12
    assert strength["evidence_lower_bound"] >= 0.75
    assert strength["candidate_policy_version"] == 2
    assert friction["code"] == (
        "friction.acceptance_before_implementation_unclear"
    )
    assert friction["evidence_upper_bound"] <= 0.25
    serialized = response.text.casefold()
    assert session_id not in serialized
    for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
        assert prohibited not in serialized


def test_contracts_reject_text_and_incomplete_model_provenance_without_echoing(
    tmp_path,
) -> None:
    _, session_id = _database_and_session(tmp_path)
    canary = "SYNTHETIC-PRIVATE-SESSION-TEXT-CANARY"
    with pytest.raises(ValidationError) as error:
        SessionAnalysisResultRecord(
            **_known_result().model_dump(),
            prompt_text=canary,
        )
    assert canary not in str(error.value)

    with pytest.raises(ValidationError, match="pinned revision"):
        _known_result(model_id="example/model")
    with pytest.raises(ValidationError, match="redacted-content"):
        SessionAnalysisRunDraft.model_validate(
            {
                **_draft(session_id).model_dump(),
                "data_tier": DataTier.METADATA,
            }
        )
    with pytest.raises(ValidationError, match="unique and sorted"):
        SessionAnalysisRunDraft.model_validate(
            {
                **_draft(session_id).model_dump(),
                "selected_metric_keys": (
                    "prompt.goal_definition",
                    "logic.plan_state_accounting",
                ),
            }
        )
    with pytest.raises(ValidationError, match="exact metric scope requires keys"):
        SessionAnalysisRunDraft.model_validate(
            {
                **_draft(session_id).model_dump(),
                "selected_metric_keys": (),
            }
        )
    with pytest.raises(ValidationError, match="unknown legacy scope"):
        SessionAnalysisRunDraft.model_validate(
            {
                **_draft(session_id).model_dump(),
                "metric_scope_state": SessionMetricScopeState.LEGACY_UNKNOWN,
            }
        )


def test_newer_failed_run_does_not_replace_latest_completed_snapshot(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    completed = _draft(session_id, "a")
    failed = _draft(
        session_id,
        "e",
        started_at=NOW + timedelta(minutes=10),
    )
    repository.begin(completed)
    repository.complete(
        completed.run_id,
        (_known_result(),),
        finished_at=NOW + timedelta(minutes=2),
    )
    repository.begin(failed)
    repository.fail(
        failed.run_id,
        finished_at=NOW + timedelta(minutes=11),
        failure_code="synthetic_failure",
    )

    latest = repository.get_latest_completed(session_id)
    assert latest is not None and latest.draft.run_id == completed.run_id
    assert [run.status for run in repository.list_for_session(session_id)] == [
        AnalysisRunStatus.FAILED,
        AnalysisRunStatus.COMPLETED,
    ]


def test_latest_completed_aggregation_projection_is_one_query_and_evidence_free(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_ids = tuple(
        row["session_id"] for row in database.list_sessions(limit=10)
    )
    assert len(session_ids) == 2
    first_session, second_session = session_ids
    repository = database.session_analysis_run_repository()

    older = _draft(
        first_session,
        "a",
        started_at=NOW - timedelta(minutes=10),
    )
    newer = _draft(first_session, "b", started_at=NOW)
    second = _draft(
        second_session,
        "c",
        started_at=NOW,
        selected_metric_keys=("logic.plan_state_accounting",),
    )
    repository.begin(older)
    repository.complete(
        older.run_id,
        (_known_result(),),
        finished_at=NOW + timedelta(minutes=2),
    )
    repository.begin(newer)
    repository.complete(
        newer.run_id,
        (
            _known_result(
                model_id="example/model",
                model_revision="pinned-revision",
                model_license="mit",
                tokenizer_id="example/tokenizer",
                prompt_version="prompt-v1",
            ),
        ),
        finished_at=NOW + timedelta(minutes=2),
    )
    repository.begin(second)
    repository.complete(
        second.run_id,
        (_not_applicable_result(),),
        finished_at=NOW + timedelta(minutes=2),
    )

    selected_set = set(session_ids)
    missing_ids: list[str] = []
    candidate = 1
    while len(missing_ids) < 98:
        safe_id = f"{candidate:064x}"
        candidate += 1
        if safe_id not in selected_set:
            missing_ids.append(safe_id)
    selection = (
        second_session,
        *missing_ids[:49],
        first_session,
        *missing_ids[49:],
    )
    assert len(selection) == 100

    statements: list[str] = []
    connection_scope = repository._connection_scope

    @contextmanager
    def traced_connection(*, readonly: bool = False):
        with connection_scope(readonly=readonly) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    repository._connection_scope = traced_connection
    snapshots = repository.get_latest_completed_for_aggregation(
        selection,
        **AGGREGATION_FILTER,
    )

    batch_statements = tuple(
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("WITH SELECTED")
    )
    assert len(batch_statements) == 1
    assert all(
        "session_analysis_result_evidence" not in statement.lower()
        for statement in statements
    )
    assert all(
        "session_analysis_result_signals" not in statement.lower()
        for statement in statements
    )
    assert tuple(snapshot.session_id for snapshot in snapshots) == (
        second_session,
        first_session,
    )
    assert snapshots[1].results[0].model_id == "example/model"
    assert snapshots[1].results[0].model_revision == "pinned-revision"

    serialized = "".join(snapshot.model_dump_json() for snapshot in snapshots)
    assert "d" * 64 not in serialized
    for forbidden_field in (
        '"evidence"',
        '"message_id"',
        '"explanation_code"',
        '"error_code"',
        '"computed_at"',
        '"run_id"',
        '"request_fingerprint"',
        '"input_fingerprint"',
    ):
        assert forbidden_field not in serialized


def test_aggregation_projection_rejects_empty_oversized_and_duplicate_selection(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()

    with pytest.raises(ValueError):
        repository.get_latest_completed_for_aggregation((), **AGGREGATION_FILTER)
    with pytest.raises(ValueError):
        repository.get_latest_completed_for_aggregation(
            (session_id, session_id),
            **AGGREGATION_FILTER,
        )
    with pytest.raises(ValueError):
        repository.get_latest_completed_for_aggregation(
            tuple(f"{index:064x}" for index in range(101)),
            **AGGREGATION_FILTER,
        )


def test_aggregation_projection_selects_latest_matching_profile_not_latest_any_pack(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    matching = _draft(session_id, "a", started_at=NOW)
    repository.begin(matching)
    repository.complete(
        matching.run_id,
        (_known_result(),),
        finished_at=NOW + timedelta(minutes=1),
    )
    newer_other_profile = _draft(
        session_id,
        "b",
        started_at=NOW + timedelta(minutes=2),
    ).model_copy(
        update={
            "request_fingerprint": "e" * 64,
            "input_fingerprint": "d" * 64,
            "analysis_profile_key": "alternate_engineering",
        }
    )
    repository.begin(newer_other_profile)
    repository.complete(
        newer_other_profile.run_id,
        (
            _known_result().model_copy(
                update={"computed_at": NOW + timedelta(minutes=2)}
            ),
        ),
        finished_at=NOW + timedelta(minutes=3),
    )

    snapshots = repository.get_latest_completed_for_aggregation(
        (session_id,),
        **AGGREGATION_FILTER,
    )

    assert len(snapshots) == 1
    assert snapshots[0].analysis_profile_key == "standard_engineering"
    assert snapshots[0].metric_pack_key == DEFAULT_TEXT_METRIC_PACK_KEY
