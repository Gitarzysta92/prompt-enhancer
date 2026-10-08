from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3
from threading import Event

import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.model_ensemble import (
    ChunkMetricCommitteeReceipt,
    ModelEnsembleChunkReceipt,
    ModelExpertReceipt,
    ModelExpertRole,
    ModelExpertStatus,
    ModelMetricVote,
    ModelVoteState,
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    SessionModelEnsembleMetricReceipt,
    SessionModelEnsembleReceipt,
    SessionModelEnsembleTypedMetricReceipt,
    SourceCoverageState,
    ensemble_plan_fingerprint,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    SessionModelEnsembleOutcome,
    SessionModelEnsemblePersistenceAuthority,
    SessionModelEnsembleRunRecord,
)
from prompt_enhancer.application.analysis.model_ensemble_watch import (
    MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
    MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED,
    MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED,
    ModelEnsembleWatchFailureClass,
    ModelEnsembleWatchFailurePolicy,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitExtractionBasis,
    SemanticUnitKind,
    SemanticUnitLifecycle,
    SemanticUnitReceipt,
    SemanticUnitReconciliation,
)
from prompt_enhancer.application.analysis.model_ensemble import (
    coaching_ensemble_metric_specs,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseInvariantError,
    _MIGRATION_1,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    ensemble_expert_specs,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2040, 2, 3, 10, 0, tzinfo=UTC)
METRIC_KEY = "prompt.task_definition_coverage"


def _database_and_session(tmp_path, provider: Provider = Provider.CODEX) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_id = database.list_sessions(provider=Provider.SYNTHETIC, limit=1)[0][
        "session_id"
    ]
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE projects SET provider=?", (provider.value,))
        connection.execute("UPDATE sessions SET provider=?", (provider.value,))
        connection.commit()
    return database, session_id


def _run(session_id: str, provider: Provider = Provider.CODEX) -> SessionModelEnsembleRunRecord:
    identities = tuple(item.identity for item in ensemble_expert_specs())
    expert_receipts = tuple(
        ModelExpertReceipt(
            identity=identity,
            status=ModelExpertStatus.COMPLETED,
            device="cuda",
            inference_latency_ms=float(identity.ordinal + 1),
            peak_accelerator_memory_mb=100.0,
            process_rss_mb=200.0,
        )
        for identity in identities
    )
    selected_identity = {
        identity.model_key: identity for identity in identities
    }
    decision_keys = (
        "mdeberta_xnli",
        "multilingual_minilmv2_l6_nli",
        "multilingual_minilmv2_l12_nli",
        "qwen3_4b_rubric",
    )
    votes = tuple(
        ModelMetricVote(
            chunk_ordinal=0,
            metric_key=METRIC_KEY,
            model_key=key,
            role=selected_identity[key].role,
            state=ModelVoteState.PRESENT,
            raw_score=0.9,
            evidence_fragment_ids=("e" * 64,),
            reason_code="synthetic_present",
        )
        for key in decision_keys
    )
    receipt = SessionModelEnsembleReceipt(
        plan_fingerprint=ensemble_plan_fingerprint(
            identities,
            (coaching_ensemble_metric_specs()[0],),
        ),
        source_window_fingerprint="d" * 64,
        source_coverage_state=SourceCoverageState.COMPLETE_WINDOW,
        chunk_count=1,
        chunk_plan=(
            ModelEnsembleChunkReceipt(
                ordinal=0,
                chunk_fingerprint="c" * 64,
                source_message_count=2,
                fragment_count=2,
                character_count=120,
            ),
        ),
        chunks=(
            ChunkMetricCommitteeReceipt(
                chunk_ordinal=0,
                metric_key=METRIC_KEY,
                value_state=MetricValueState.KNOWN,
                numerator=1,
                denominator=1,
                rubric_vote=ModelVoteState.PRESENT,
                contributing_nli_votes=2,
                diagnostic_nli_votes=1,
                reason_code="model_committee_present",
            ),
        ),
        metrics=(
            SessionModelEnsembleMetricReceipt(
                metric_key=METRIC_KEY,
                value_state=MetricValueState.KNOWN,
                numerator=1,
                denominator=1,
                numeric_value=1.0,
                known_chunk_count=1,
                abstained_chunk_count=0,
                unsupported_chunk_count=0,
                failed_chunk_count=0,
                total_chunk_count=1,
                explanation_code="model_chunk_ratio",
            ),
        ),
        experts=expert_receipts,
        model_votes=tuple(sorted(votes, key=lambda item: item.model_key)),
        created_at=NOW,
        completed_at=NOW + timedelta(seconds=4),
    )
    return SessionModelEnsembleRunRecord(
        run_id="a" * 64,
        session_id=session_id,
        request_fingerprint="b" * 64,
        input_fingerprint="d" * 64,
        provider=provider,
        provider_version="codex-app-server-v1",
        adapter_version="codex-adapter-v1",
        source_schema_version="codex-source-v1",
        content_schema_version="codex-content-v1",
        redactor_version="deterministic-redactor-v1",
        receipt=receipt,
    )


def _with_typed_projection(
    run: SessionModelEnsembleRunRecord,
) -> SessionModelEnsembleRunRecord:
    typed = SessionModelEnsembleTypedMetricReceipt(
        metric_key=METRIC_KEY,
        metric_version=3,
        value_state=MetricValueState.KNOWN,
        numerator=3,
        denominator=4,
        numeric_value=0.75,
        observed_message_count=2,
        eligible_message_count=2,
        coverage=1.0,
        explanation_code="typed_requirement_ratio",
        error_code=None,
        projection_source="deterministic_typed_contract",
        metric_schema_version=2,
        engine_version="coaching-rules-en-pl-2",
        algorithm_id="coaching-text-features",
        algorithm_version="coaching-features-en-pl-2",
        rubric_version="coaching-rubric-v3",
        calibration_state="not_assessed",
        product_metric_eligible=False,
    )
    receipt = SessionModelEnsembleReceipt.model_validate(
        {
            **run.receipt.model_dump(),
            "metric_projection_version": MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
            "metric_projection_completed_at": NOW + timedelta(seconds=5),
            "typed_metrics": (typed,),
        }
    )
    return SessionModelEnsembleRunRecord.model_validate(
        {**run.model_dump(), "receipt": receipt}
    )


def _semantic_units(run: SessionModelEnsembleRunRecord) -> SemanticUnitReconciliation:
    head = SemanticUnitReceipt(
        provider=run.provider,
        session_id=run.session_id,
        receipt_id="1" * 64,
        unit_id="2" * 64,
        unit_digest="3" * 64,
        revision=1,
        kind=SemanticUnitKind.REQUEST_REVISION,
        lifecycle=SemanticUnitLifecycle.OPEN,
        extraction_basis=SemanticUnitExtractionBasis.DOCUMENTED_MESSAGE_KIND,
        owner_source_digest="4" * 64,
        source_digests=("4" * 64,),
        source_version_digest="5" * 64,
        first_sequence=1,
        owner_role="user",
        owner_message_kind="request",
    )
    return SemanticUnitReconciliation(
        provider=run.provider,
        session_id=run.session_id,
        analysis_window_fingerprint=run.input_fingerprint,
        source_complete=True,
        reconciliation_id="6" * 64,
        heads=(head,),
        appended=(head,),
        unchanged_receipt_ids=(),
        retained_unobserved_unit_count=0,
    )


def test_model_ensemble_graph_round_trips_and_contains_no_content_columns(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    run = _run(session_id)

    repository.save_completed(run)
    stored = repository.get(run.run_id)

    assert stored is not None
    assert stored.model_dump(mode="json") == run.model_dump(mode="json")
    assert repository.get_latest(session_id) == stored
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = tuple(
            row[0]
            for row in connection.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name LIKE 'session_model_ensemble_%'"""
            )
        )
        columns = {
            row[1]
            for table in tables
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
    assert not any(
        fragment in column
        for column in columns
        for fragment in ("text", "prompt", "response", "output", "path")
    )


def test_migration_51_admits_claude_code_ensemble_runs_and_watches(tmp_path) -> None:
    """Migration 51 relaxes the provider CHECK on both ensemble tables (ADR 0011 / ADR 0012)."""

    database, session_id = _database_and_session(tmp_path, Provider.CLAUDE_CODE)
    repository = database.model_ensemble_repository()
    run = _run(session_id, Provider.CLAUDE_CODE)
    repository.save_completed(run)
    stored = repository.get(run.run_id)
    assert stored is not None and stored.provider is Provider.CLAUDE_CODE
    project_id = database.list_sessions(provider=Provider.CLAUDE_CODE, limit=1)[0]["project_id"]
    watches = database.model_ensemble_watch_repository()
    enabled = watches.enable(
        watch_id="7" * 64, provider=Provider.CLAUDE_CODE, project_id=project_id, session_id=session_id, max_messages=25, now=NOW,
    )
    assert enabled.provider is Provider.CLAUDE_CODE and enabled.state.value == "queued"
    with sqlite3.connect(database.path) as connection:
        for table in ("session_model_ensemble_runs", "session_model_ensemble_watches"):
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            assert "CHECK(provider IN ('codex','claude_code'))" in sql and "CHECK(provider='codex')" not in sql
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='session_model_ensemble_runs_provider_idx'"
        ).fetchone() is not None
        # Other providers stay rejected by the widened constraint itself (a disabled row dodges the
        # one-active-watch index and the identity trigger, so only the CHECK can refuse it).
        stamp = "2040-02-03T10:00:00.000000+00:00"
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """INSERT INTO session_model_ensemble_watches(watch_id,provider,project_id,session_id,state,generation,
                   progress_completed,progress_total,next_check_at,created_at,updated_at)
                   VALUES (?,?,?,?,'disabled',0,0,10,?,?,?)""",
                ("6" * 64, "synthetic", project_id, session_id, stamp, stamp, stamp),
            )


def test_semantic_unit_sidecar_is_atomic_immutable_and_round_trips(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    run = _run(session_id)
    reconciliation = _semantic_units(run)

    repository.save_completed(run, semantic_units=reconciliation)

    assert repository.get(run.run_id) == run
    assert repository.get_semantic_unit_reconciliation(run.run_id) == reconciliation
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_semantic_unit_heads"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_semantic_unit_sources"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_semantic_unit_seals"
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_semantic_unit_heads
                   SET lifecycle='closed' WHERE run_id=?""",
                (run.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="privacy deletion"):
            connection.execute(
                "DELETE FROM session_model_ensemble_semantic_unit_heads WHERE run_id=?",
                (run.run_id,),
            )

    assert repository.delete_for_privacy(run.run_id) is True
    assert repository.get_semantic_unit_reconciliation(run.run_id) is None
    with sqlite3.connect(database.path) as connection:
        assert tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_model_ensemble_semantic_unit_heads",
                "session_model_ensemble_semantic_unit_sources",
                "session_model_ensemble_semantic_unit_seals",
            )
        ) == (0, 0, 0)


def test_semantic_unit_binding_failure_rolls_back_the_ensemble_graph(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    run = _run(session_id)
    reconciliation = SemanticUnitReconciliation.model_validate(
        {
            **_semantic_units(run).model_dump(),
            "analysis_window_fingerprint": "e" * 64,
        }
    )

    with pytest.raises(DatabaseInvariantError, match="does not match"):
        repository.save_completed(run, semantic_units=reconciliation)

    assert repository.get(run.run_id) is None
    assert repository.get_semantic_unit_reconciliation(run.run_id) is None
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs"
        ).fetchone()[0] == 0


def test_typed_metric_projection_round_trips_and_can_upgrade_a_legacy_seal(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    legacy = _run(session_id)
    projected = _with_typed_projection(legacy)

    repository.save_completed(legacy)
    repository.save_metric_projection(projected)

    assert repository.get(legacy.run_id) == projected
    with sqlite3.connect(database.path) as connection:
        metric = connection.execute(
            """SELECT value_state,numerator,denominator,numeric_value,
                      observed_message_count,eligible_message_count
               FROM session_model_ensemble_typed_metrics WHERE run_id=?""",
            (legacy.run_id,),
        ).fetchone()
        assert metric == ("known", 3, 4, 0.75, 2, 2)
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_typed_metric_seals WHERE run_id=?",
            (legacy.run_id,),
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_typed_metrics
                   SET numeric_value=0 WHERE run_id=?""",
                (legacy.run_id,),
            )


@pytest.mark.parametrize(
    ("observed_messages", "eligible_messages", "coverage"),
    ((0, 0, 0.0), (100, 324, 100 / 324)),
)
def test_typed_metric_projection_preserves_exact_message_coverage(
    tmp_path,
    observed_messages: int,
    eligible_messages: int,
    coverage: float,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    legacy = _run(session_id)
    unavailable = SessionModelEnsembleTypedMetricReceipt(
        metric_key=METRIC_KEY,
        metric_version=3,
        value_state=MetricValueState.UNKNOWN,
        numerator=None,
        denominator=None,
        numeric_value=None,
        observed_message_count=observed_messages,
        eligible_message_count=eligible_messages,
        coverage=coverage,
        explanation_code="typed_opportunity_unavailable",
        error_code=None,
        projection_source="deterministic_typed_contract",
        metric_schema_version=2,
        engine_version="coaching-rules-en-pl-2",
        algorithm_id="coaching-text-features",
        algorithm_version="coaching-features-en-pl-2",
        rubric_version="coaching-rubric-v3",
        calibration_state="not_assessed",
        product_metric_eligible=False,
    )
    receipt = SessionModelEnsembleReceipt.model_validate(
        {
            **legacy.receipt.model_dump(),
            "metric_projection_version": MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
            "metric_projection_completed_at": NOW + timedelta(seconds=5),
            "typed_metrics": (unavailable,),
        }
    )
    projected = SessionModelEnsembleRunRecord.model_validate(
        {**legacy.model_dump(), "receipt": receipt}
    )

    repository.save_completed(legacy)
    repository.save_metric_projection(projected)

    stored = repository.get(legacy.run_id)
    assert stored is not None
    assert stored.receipt.typed_metrics == (unavailable,)


def test_model_ensemble_graph_is_immutable_sealed_and_privacy_deletable(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    run = _run(session_id)
    repository.save_completed(run)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE session_model_ensemble_metrics SET numeric_value=0 WHERE run_id=?",
                (run.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="sealed"):
            connection.execute(
                """INSERT INTO session_model_ensemble_vote_fragments
                   VALUES(?,?,?,?,?,?)""",
                (run.run_id, 0, METRIC_KEY, "qwen3_4b_rubric", 1, "f" * 64),
            )

    assert repository.delete_for_privacy(run.run_id) is True
    assert repository.get(run.run_id) is None
    with sqlite3.connect(database.path) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_model_ensemble_runs",
                "session_model_ensemble_chunks",
                "session_model_ensemble_experts",
                "session_model_ensemble_votes",
                "session_model_ensemble_vote_fragments",
                "session_model_ensemble_chunk_metrics",
                "session_model_ensemble_metrics",
                "session_model_ensemble_seals",
                "session_model_ensemble_typed_metrics",
                "session_model_ensemble_typed_metric_seals",
            )
        )
    assert counts == (0,) * 10


def test_model_ensemble_migrations_have_zero_backfill(tmp_path) -> None:
    database, _ = _database_and_session(tmp_path)
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ) == tuple(range(1, 62))
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs"
        ).fetchone()[0] == 0
        assert tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "session_model_ensemble_semantic_unit_heads",
                "session_model_ensemble_semantic_unit_sources",
                "session_model_ensemble_semantic_unit_seals",
            )
        ) == (0, 0, 0)


def test_v28_watch_upgrade_preserves_the_original_message_window(tmp_path) -> None:
    path = tmp_path / "watch-v28.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 29)
    )
    checksums = tuple(
        hashlib.sha256(script.encode("utf-8")).hexdigest()
        for script in scripts
    )
    timestamp = NOW.isoformat(timespec="microseconds")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            tuple(
                (version, checksum, timestamp)
                for version, checksum in enumerate(checksums, start=1)
            ),
        )
        connection.execute(
            "INSERT INTO installations VALUES(?,?,?)",
            ("1" * 64, "codex", timestamp),
        )
        connection.execute(
            "INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES(?,?,?,?)",
            ("2" * 64, "1" * 64, "codex", timestamp),
        )
        connection.execute(
            """INSERT INTO sessions(
               session_id,installation_id,project_id,provider,provider_version,
               adapter_version,source_schema_version,started_at,ended_at,
               terminal_state,events_complete,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,'completed',1,?,?)""",
            (
                "3" * 64,
                "1" * 64,
                "2" * 64,
                "codex",
                "example-provider-v1",
                "example-adapter-v1",
                "example-schema-v1",
                timestamp,
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """INSERT INTO session_model_ensemble_watches(
               watch_id,provider,project_id,session_id,state,generation,
               progress_completed,progress_total,next_check_at,created_at,updated_at
               ) VALUES(?,?,?,?,'queued',0,0,10,?,?,?)""",
            ("4" * 64, "codex", "2" * 64, "3" * 64, timestamp, timestamp, timestamp),
        )
        connection.execute("PRAGMA user_version=28")
        connection.commit()

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[1] for row in rows[:28]) == checksums
        assert rows[28][1] == hashlib.sha256(
            migrations.MIGRATION_29.encode("utf-8")
        ).hexdigest()
        assert rows[29][1] == hashlib.sha256(
            migrations.MIGRATION_30.encode("utf-8")
        ).hexdigest()
        assert rows[30][1] == hashlib.sha256(
            migrations.MIGRATION_31.encode("utf-8")
        ).hexdigest()
        assert rows[31][1] == hashlib.sha256(
            migrations.MIGRATION_32.encode("utf-8")
        ).hexdigest()
        assert rows[32][1] == hashlib.sha256(
            migrations.MIGRATION_33.encode("utf-8")
        ).hexdigest()
        assert rows[33][1] == hashlib.sha256(
            migrations.MIGRATION_34.encode("utf-8")
        ).hexdigest()
        assert rows[34][1] == hashlib.sha256(
            migrations.MIGRATION_35.encode("utf-8")
        ).hexdigest()
        assert rows[35][1] == hashlib.sha256(
            migrations.MIGRATION_36.encode("utf-8")
        ).hexdigest()
        assert rows[36][1] == hashlib.sha256(
            migrations.MIGRATION_37.encode("utf-8")
        ).hexdigest()
        assert rows[37][1] == hashlib.sha256(
            migrations.MIGRATION_38.encode("utf-8")
        ).hexdigest()
        assert rows[38][1] == hashlib.sha256(
            migrations.MIGRATION_39.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            """SELECT max_messages,failure_streak,quarantined_at,
                      quarantine_reason_code
               FROM session_model_ensemble_watches"""
        ).fetchone() == (100, 0, None, None)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("populated", (False, True))
def test_v25_to_v26_preserves_prior_checksums_and_rows(tmp_path, populated: bool) -> None:
    path = tmp_path / f"{'populated' if populated else 'fresh'}-v25.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 26)
    )
    checksums = tuple(
        hashlib.sha256(script.encode("utf-8")).hexdigest()
        for script in scripts
    )
    timestamp = NOW.isoformat(timespec="microseconds")
    session_id = ""
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
            installation_id = "1" * 64
            project_id = "2" * 64
            session_id = "3" * 64
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
        connection.execute("PRAGMA user_version=25")
        connection.commit()

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in rows) == tuple(range(1, 62))
        assert tuple(row[1] for row in rows[:25]) == checksums
        assert rows[25][1] == hashlib.sha256(
            migrations.MIGRATION_26.encode("utf-8")
        ).hexdigest()
        assert rows[26][1] == hashlib.sha256(
            migrations.MIGRATION_27.encode("utf-8")
        ).hexdigest()
        assert rows[27][1] == hashlib.sha256(
            migrations.MIGRATION_28.encode("utf-8")
        ).hexdigest()
        assert rows[28][1] == hashlib.sha256(
            migrations.MIGRATION_29.encode("utf-8")
        ).hexdigest()
        assert rows[29][1] == hashlib.sha256(
            migrations.MIGRATION_30.encode("utf-8")
        ).hexdigest()
        assert rows[30][1] == hashlib.sha256(
            migrations.MIGRATION_31.encode("utf-8")
        ).hexdigest()
        assert rows[31][1] == hashlib.sha256(
            migrations.MIGRATION_32.encode("utf-8")
        ).hexdigest()
        assert rows[32][1] == hashlib.sha256(
            migrations.MIGRATION_33.encode("utf-8")
        ).hexdigest()
        assert rows[33][1] == hashlib.sha256(
            migrations.MIGRATION_34.encode("utf-8")
        ).hexdigest()
        assert rows[34][1] == hashlib.sha256(
            migrations.MIGRATION_35.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_runs"
        ).fetchone()[0] == 0
        if populated:
            assert connection.execute(
                """SELECT terminal_state,provider_activity_revision
                   FROM sessions WHERE session_id=?""",
                (session_id,),
            ).fetchone() == ("completed", None)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_continuous_watch_claim_progress_completion_and_disable(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    run_repository = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    run_repository.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    repository = database.model_ensemble_watch_repository()
    watch_id = "9" * 64

    enabled = repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=25,
        now=NOW,
    )
    assert enabled.state.value == "queued"
    assert enabled.max_messages == 25
    claimed = repository.claim_due(
        owner="8" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    running, lease = claimed
    assert running.state.value == "running"
    assert running.generation == 1
    running, lease = repository.heartbeat(
        lease,
        now=NOW + timedelta(seconds=10),
        lease_duration=timedelta(minutes=30),
        progress_completed=4,
    )
    assert running.progress_completed == 4

    completed = repository.complete(
        lease,
        now=NOW + timedelta(seconds=20),
        next_check_at=NOW + timedelta(seconds=80),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    assert completed.state.value == "idle"
    assert completed.latest_run_id == run.run_id
    assert completed.latest_input_fingerprint == run.input_fingerprint
    assert completed.progress_completed == 10
    assert repository.get_active() == completed
    trajectory = repository.list_publications(
        watch_id,
        before_generation=None,
        limit=12,
    )
    assert trajectory.head_run_id == run.run_id
    assert trajectory.head_generation == 1
    assert tuple(point.run_id for point in trajectory.points) == (run.run_id,)
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[0].max_messages == 25
    assert trajectory.points[0].metric_projection_version == (
        MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
    )
    assert trajectory.points[0].typed_metrics[0].numeric_value == 0.75
    head = repository.canonical_head(watch_id)
    assert head.head_run_id == run.run_id
    assert head.head_generation == 1
    assert head.latest_attempt is not None
    assert head.latest_attempt.state.value == "completed"
    assert head.latest_attempt.published_run_id == run.run_id
    assert head.latest_attempt.progress_completed == 10
    assert head.latest_attempt.progress_total == 10
    assert head.stages == ()

    repository.disable(watch_id, now=NOW + timedelta(seconds=7))
    reenabled_same_scope = repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=25,
        now=NOW + timedelta(seconds=8),
    )
    assert reenabled_same_scope.state.value == "queued"
    assert reenabled_same_scope.latest_run_id == run.run_id
    retained_head = repository.canonical_head(watch_id)
    assert retained_head.head_run_id == run.run_id
    assert retained_head.head_generation == 1
    assert retained_head.latest_attempt is None
    assert retained_head.stages == ()

    refreshed = repository.request_refresh(watch_id, now=NOW + timedelta(seconds=8))
    assert refreshed.state.value == "queued"
    assert refreshed.latest_run_id == run.run_id
    assert refreshed.next_check_at == NOW + timedelta(seconds=8)

    reclaimed, stale_lease = repository.claim_due(
        owner="e" * 64,
        now=NOW + timedelta(seconds=9),
        lease_duration=timedelta(minutes=30),
    )
    assert reclaimed.state.value == "running"
    restarted = repository.request_refresh(
        watch_id,
        now=NOW + timedelta(seconds=10),
    )
    assert restarted.state.value == "running"
    assert restarted.latest_run_id == run.run_id
    assert restarted.lease_owner == stale_lease.owner
    assert restarted.lease_token == stale_lease.token
    assert restarted.lease_expires_at == stale_lease.expires_at
    continued, _ = repository.heartbeat(
        stale_lease,
        now=NOW + timedelta(seconds=11),
        lease_duration=timedelta(minutes=30),
        progress_completed=2,
    )
    assert continued.state.value == "running"
    assert continued.progress_completed == 2

    reconfigured = repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=50,
        now=NOW + timedelta(seconds=21),
    )
    assert reconfigured.state.value == "queued"
    assert reconfigured.max_messages == 50
    assert reconfigured.progress_completed == 0
    assert reconfigured.latest_run_id is None
    assert reconfigured.latest_input_fingerprint is None
    reconfigured_head = repository.canonical_head(watch_id)
    assert reconfigured_head.head_run_id is None
    assert reconfigured_head.head_generation is None
    assert reconfigured_head.latest_attempt is None
    assert reconfigured_head.stages == ()

    disabled = repository.disable(watch_id, now=NOW + timedelta(seconds=22))
    assert disabled.state.value == "disabled"
    disabled_head = repository.canonical_head(watch_id)
    assert disabled_head.head_run_id is None
    assert disabled_head.head_generation is None
    assert disabled_head.latest_attempt is None
    assert disabled_head.stages == ()
    assert repository.get_active() is None


def test_watch_retry_preserves_the_fixed_failure_reason_until_success(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    run_repository = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    run_repository.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    repository = database.model_ensemble_watch_repository()
    watch_id = "6" * 64
    repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = repository.claim_due(
        owner="7" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, failed_lease = claimed
    failed = repository.fail(
        failed_lease,
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(minutes=1),
        reason_code="local_model_ensemble_execution_failed",
    )
    assert failed.state.value == "failed"
    assert failed.last_error_code == "local_model_ensemble_execution_failed"
    failed_head = repository.canonical_head(watch_id)
    assert failed_head.head_run_id is None
    assert failed_head.latest_attempt is not None
    assert failed_head.latest_attempt.state.value == "failed"
    assert failed_head.latest_attempt.error_code == "local_model_ensemble_execution_failed"
    assert tuple(stage.stage_key for stage in failed_head.stages) == (
        "analysis_pipeline",
    )

    queued = repository.request_refresh(
        watch_id,
        now=NOW + timedelta(seconds=2),
    )
    assert queued.state.value == "queued"
    assert queued.last_error_code == "local_model_ensemble_execution_failed"
    reclaimed = repository.claim_due(
        owner="7" * 64,
        now=NOW + timedelta(seconds=3),
        lease_duration=timedelta(minutes=30),
    )
    assert reclaimed is not None
    retrying, retry_lease = reclaimed
    assert retrying.state.value == "running"
    assert retrying.last_error_code == "local_model_ensemble_execution_failed"

    completed = repository.complete(
        retry_lease,
        now=NOW + timedelta(seconds=4),
        next_check_at=NOW + timedelta(minutes=2),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    assert completed.state.value == "idle"
    assert completed.last_error_code is None
    attempts = repository.list_attempts(watch_id, limit=12)
    assert tuple(item.generation for item in attempts) == (2, 1)
    assert tuple(item.state.value for item in attempts) == ("completed", "failed")
    assert attempts[1].error_code == "local_model_ensemble_execution_failed"


def test_watch_failures_back_off_and_quarantine_until_explicit_refresh(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    repository = database.model_ensemble_watch_repository()
    watch_id = "b" * 64
    owner = "c" * 64
    policy = ModelEnsembleWatchFailurePolicy(
        base_delay=timedelta(seconds=60),
        max_delay=timedelta(minutes=10),
        max_failure_streak=3,
    )
    repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )

    first = repository.claim_due(
        owner=owner,
        now=NOW,
        lease_duration=timedelta(minutes=30),
        policy=policy,
    )
    assert first is not None
    failed_once = repository.fail(
        first[1],
        now=NOW + timedelta(seconds=1),
        reason_code="synthetic_transient_failure",
        failure_class=ModelEnsembleWatchFailureClass.RETRYABLE,
        policy=policy,
    )
    assert failed_once.failure_streak == 1
    assert failed_once.next_check_at == NOW + timedelta(seconds=61)
    assert failed_once.quarantined is False
    assert repository.claim_due(
        owner=owner,
        now=NOW + timedelta(seconds=60),
        lease_duration=timedelta(minutes=30),
        policy=policy,
    ) is None

    second = repository.claim_due(
        owner=owner,
        now=NOW + timedelta(seconds=61),
        lease_duration=timedelta(minutes=30),
        policy=policy,
    )
    assert second is not None
    failed_twice = repository.fail(
        second[1],
        now=NOW + timedelta(seconds=62),
        reason_code="synthetic_transient_failure",
        failure_class=ModelEnsembleWatchFailureClass.RETRYABLE,
        policy=policy,
    )
    assert failed_twice.failure_streak == 2
    assert failed_twice.next_check_at == NOW + timedelta(seconds=182)

    third = repository.claim_due(
        owner=owner,
        now=NOW + timedelta(seconds=182),
        lease_duration=timedelta(minutes=30),
        policy=policy,
    )
    assert third is not None
    quarantined = repository.fail(
        third[1],
        now=NOW + timedelta(seconds=183),
        reason_code="synthetic_transient_failure",
        failure_class=ModelEnsembleWatchFailureClass.RETRYABLE,
        policy=policy,
    )
    assert quarantined.failure_streak == 3
    assert quarantined.quarantined_at == NOW + timedelta(seconds=183)
    assert quarantined.quarantine_reason_code == MODEL_ENSEMBLE_WATCH_STREAK_EXHAUSTED
    assert repository.claim_due(
        owner=owner,
        now=NOW + timedelta(days=1),
        lease_duration=timedelta(minutes=30),
        policy=policy,
    ) is None

    refreshed = repository.request_refresh(
        watch_id,
        now=NOW + timedelta(days=1, seconds=1),
    )
    assert refreshed.state.value == "queued"
    assert refreshed.failure_streak == 0
    assert refreshed.quarantined is False
    assert repository.claim_due(
        owner=owner,
        now=NOW + timedelta(days=1, seconds=1),
        lease_duration=timedelta(minutes=30),
        policy=policy,
    ) is not None


def test_nonretryable_failure_quarantines_immediately(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    repository = database.model_ensemble_watch_repository()
    watch_id = "d" * 64
    repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = repository.claim_due(
        owner="e" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    failed = repository.fail(
        claimed[1],
        now=NOW + timedelta(seconds=1),
        reason_code="redacted_content_consent_required",
        failure_class=ModelEnsembleWatchFailureClass.NONRETRYABLE,
        policy=ModelEnsembleWatchFailurePolicy(),
    )
    assert failed.state.value == "failed"
    assert failed.failure_streak == 1
    assert failed.quarantine_reason_code == "redacted_content_consent_required"
    assert failed.quarantined_at == NOW + timedelta(seconds=1)


def test_startup_recovery_never_steals_an_unexpired_lease(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    repository = database.model_ensemble_watch_repository()
    watch_id = "a" * 64
    owner = "1" * 64
    policy = ModelEnsembleWatchFailurePolicy()
    repository.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = repository.claim_due(
        owner=owner,
        now=NOW,
        lease_duration=timedelta(seconds=30),
        policy=policy,
    )
    assert claimed is not None
    assert repository.recover_orphaned_leases(
        owner="2" * 64,
        now=NOW + timedelta(seconds=29),
        policy=policy,
    ) == 0
    still_running = repository.get(watch_id)
    assert still_running is not None and still_running.state.value == "running"
    assert still_running.lease_owner == owner

    assert repository.recover_orphaned_leases(
        owner="2" * 64,
        now=NOW + timedelta(seconds=30),
        policy=policy,
    ) == 1
    recovered = repository.get(watch_id)
    assert recovered is not None
    assert recovered.state.value == "failed"
    assert recovered.last_error_code == MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED
    assert recovered.failure_streak == 1
    assert recovered.next_check_at == NOW + timedelta(seconds=90)
    head = repository.canonical_head(watch_id)
    assert head.latest_attempt is not None
    assert head.latest_attempt.state.value == "failed"
    assert head.latest_attempt.error_code == MODEL_ENSEMBLE_WATCH_LEASE_RECOVERED


def test_provider_consent_quarantine_cancels_inflight_and_retains_head(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    runs.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "f" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    first = watches.claim_due(
        owner="3" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert first is not None
    watches.complete(
        first[1],
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=6),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    second = watches.claim_due(
        owner="3" * 64,
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(minutes=30),
    )
    assert second is not None

    assert watches.quarantine_provider_watches(
        Provider.CODEX,
        now=NOW + timedelta(seconds=7),
        reason_code=MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED,
    ) == 1
    stopped = watches.get(watch_id)
    assert stopped is not None
    assert stopped.state.value == "failed"
    assert stopped.latest_run_id == run.run_id
    assert stopped.quarantine_reason_code == MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED
    head = watches.canonical_head(watch_id)
    assert head.head_run_id == run.run_id
    assert head.latest_attempt is not None
    assert head.latest_attempt.state.value == "cancelled"
    assert head.stages[0].error_code == MODEL_ENSEMBLE_WATCH_CONSENT_REVOKED
    assert watches.claim_due(
        owner="3" * 64,
        now=NOW + timedelta(days=1),
        lease_duration=timedelta(minutes=30),
    ) is None

    disabled = watches.disable(watch_id, now=NOW + timedelta(days=1, seconds=1))
    assert disabled.state.value == "disabled"
    assert disabled.failure_streak == 0
    assert disabled.quarantined is False


def test_legacy_watch_head_without_a_publication_is_exposed_as_unpublished(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    runs.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "5" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="6" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(minutes=1),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )

    # Migration 30 deliberately performs zero backfill.  Removing only this
    # synthetic publication reproduces a legitimate upgraded pre-v30 watch;
    # DDL-owner attacks are outside the DML security boundary.
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "DROP TRIGGER session_model_ensemble_watch_publications_privacy_delete_only"
        )
        connection.execute(
            "DELETE FROM session_model_ensemble_watch_publications WHERE watch_id=?",
            (watch_id,),
        )
        connection.commit()

    canonical = watches.canonical_head(watch_id)
    assert canonical.head_run_id is None
    assert canonical.head_generation is None
    assert canonical.watch.latest_run_id is None
    assert canonical.watch.latest_input_fingerprint is None
    assert canonical.latest_attempt is None
    assert canonical.stages == ()


@pytest.mark.parametrize("shutdown", (False, True))
def test_watch_cancellation_retains_prior_head_and_seals_the_attempt(tmp_path, shutdown) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    runs.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "5" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    first = watches.claim_due(
        owner="6" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert first is not None
    watches.complete(
        first[1],
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=6),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    second = watches.claim_due(
        owner="6" * 64,
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(minutes=30),
    )
    assert second is not None
    cancel_options = {}
    if shutdown:
        cancel_options = {"lease": second[1], "reason_code": "application_shutdown"}
        with pytest.raises(ValueError):
            watches.cancel_attempt(
                watch_id, now=NOW + timedelta(seconds=7), next_check_at=NOW + timedelta(minutes=1),
                lease=second[1].model_copy(update={"token": "8" * 64}), reason_code="application_shutdown",
            )
        assert watches.get(watch_id).state.value == "running"
    cancelled = watches.cancel_attempt(
        watch_id,
        now=NOW + timedelta(seconds=7),
        next_check_at=NOW + timedelta(minutes=1),
        **cancel_options,
    )
    assert cancelled.state.value == "idle"
    assert cancelled.latest_run_id == run.run_id
    head = watches.canonical_head(watch_id)
    assert head.head_run_id == run.run_id
    assert head.head_generation == 1
    assert head.latest_attempt is not None
    assert head.latest_attempt.state.value == "cancelled"
    assert head.latest_attempt.prior_head_run_id == run.run_id
    assert head.latest_attempt.published_run_id is None
    assert head.stages[0].state.value == "cancelled"
    assert head.stages[0].error_code == ("application_shutdown" if shutdown else "analysis_cancelled")
    paused = watches.quarantine_stopped_attempt(
        second[1], generation=second[0].generation, now=NOW + timedelta(seconds=8),
        reason_code="model_ensemble_cleanup_unconfirmed",
    )
    assert paused.quarantined and paused.failure_streak == 0
    retained = watches.canonical_head(watch_id)
    assert retained.head_run_id == head.head_run_id
    assert retained.head_generation == head.head_generation
    assert retained.latest_attempt == head.latest_attempt
    assert retained.stages == head.stages


@pytest.mark.parametrize("replacement", ["bad-token", "queued", "running", "stopped"])
def test_late_cleanup_quarantine_cannot_mutate_another_claim(tmp_path, replacement) -> None:
    database, session_id = _database_and_session(tmp_path)
    watches = database.model_ensemble_watch_repository()
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    watch_id = "5" * 64
    watches.enable(watch_id=watch_id, provider=Provider.CODEX, project_id=project_id,
        session_id=session_id, now=NOW)
    first, lease = watches.claim_due(owner="6" * 64, now=NOW, lease_duration=timedelta(minutes=5))
    watches.cancel_attempt(watch_id, now=NOW, next_check_at=NOW)
    if replacement == "bad-token":
        lease = lease.model_copy(update={"token": "7" * 64})
    elif replacement == "queued":
        watches.request_refresh(watch_id, now=NOW)
    else:
        watches.claim_due(owner="8" * 64, now=NOW, lease_duration=timedelta(minutes=5))
        if replacement == "stopped":
            watches.cancel_attempt(watch_id, now=NOW, next_check_at=NOW)
    before = watches.canonical_head(watch_id)
    with pytest.raises(ValueError):
        watches.quarantine_stopped_attempt(lease, generation=first.generation, now=NOW,
            reason_code="model_ensemble_cleanup_unconfirmed")
    assert watches.canonical_head(watch_id) == before


def test_worker_shutdown_interrupts_only_its_owned_watch_attempt(tmp_path) -> None:
    from prompt_enhancer.application.analysis.model_ensemble_watch import (
        MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL, ModelEnsembleWatchService, ModelEnsembleWatchWorker,
    )

    database, session_id = _database_and_session(tmp_path)
    watches = database.model_ensemble_watch_repository()
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    watch_id = "5" * 64
    watches.enable(watch_id=watch_id, provider=Provider.CODEX, project_id=project_id, session_id=session_id, now=NOW)
    entered, release = Event(), Event()

    class CooperativeEnsemble:
        def run(self, *, progress_callback, **_kwargs):
            entered.set()
            while not release.wait(0.01):
                progress_callback(0, MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL)
            raise RuntimeError("example_test_teardown")

    service = ModelEnsembleWatchService(watches, CooperativeEnsemble(), clock=lambda: NOW)
    worker = ModelEnsembleWatchWorker(service, wake_seconds=1)
    try:
        worker.start()
        assert entered.wait(2)
        worker.stop(timeout=2)
        head = watches.canonical_head(watch_id)
        assert head.watch.state.value == "idle"
        assert head.watch.failure_streak == 0
        assert head.latest_attempt.state.value == "cancelled"
        assert head.latest_attempt.error_code == "application_shutdown"
        assert head.head_run_id is None
        assert worker.run_once() is None
    finally:
        release.set()
        worker.stop(timeout=2)


def test_terminal_attempt_graph_rejects_raw_mutation_and_unbound_publication(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    run = _with_typed_projection(_run(session_id))
    other = _run(session_id).model_copy(
        update={"run_id": "f" * 64, "request_fingerprint": "e" * 64}
    )
    runs.save_completed(run)
    runs.save_completed(other)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "1" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    first = watches.claim_due(
        owner="2" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert first is not None
    watches.complete(
        first[1],
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=6),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    second = watches.claim_due(
        owner="2" * 64,
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(minutes=30),
    )
    assert second is not None
    watches.fail(
        second[1],
        now=NOW + timedelta(seconds=7),
        next_check_at=NOW + timedelta(seconds=60),
        reason_code="synthetic_stage_failure",
    )
    head = watches.canonical_head(watch_id)
    assert head.latest_attempt is not None and len(head.stages) == 1
    attempt_id = head.latest_attempt.attempt_id
    attempt_snapshot = watches.get_attempt_snapshot(attempt_id)
    assert attempt_snapshot is not None
    assert attempt_snapshot[0] == head.latest_attempt
    assert attempt_snapshot[1] == head.stages

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement, parameters in (
            (
                "DELETE FROM session_model_ensemble_watch_publications WHERE watch_id=?",
                (watch_id,),
            ),
            (
                "DELETE FROM session_model_ensemble_watches WHERE watch_id=?",
                (watch_id,),
            ),
            (
                "DELETE FROM session_model_ensemble_analysis_attempt_stages WHERE attempt_id=?",
                (attempt_id,),
            ),
            (
                "UPDATE session_model_ensemble_analysis_attempts SET prior_head_run_id=NULL WHERE attempt_id=?",
                (attempt_id,),
            ),
            (
                "DELETE FROM session_model_ensemble_analysis_attempts WHERE attempt_id=?",
                (attempt_id,),
            ),
            (
                """INSERT INTO session_model_ensemble_analysis_attempt_stages(
                       attempt_id,stage_ordinal,stage_key,state,repository_id,
                       error_code,quantization,completed_at,local_only,content_persisted
                   ) VALUES(?,1,'forged','failed','../../../private/model',
                            'forged','none',?,1,0)""",
                (attempt_id, (NOW + timedelta(seconds=7)).isoformat(timespec="microseconds")),
            ),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, parameters)
            connection.rollback()

    queued = watches.request_refresh(
        watch_id,
        now=NOW + timedelta(seconds=61),
    )
    assert queued.state.value == "queued"
    third = watches.claim_due(
        owner="2" * 64,
        now=NOW + timedelta(seconds=62),
        lease_duration=timedelta(minutes=30),
    )
    assert third is not None
    running_attempt = watches.canonical_head(watch_id).latest_attempt
    assert running_attempt is not None
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE session_model_ensemble_analysis_attempts
                   SET state='completed',published_run_id=?,progress_completed=10,
                       progress_total=10,completed_at=? WHERE attempt_id=?""",
                (
                    other.run_id,
                    (NOW + timedelta(seconds=63)).isoformat(timespec="microseconds"),
                    running_attempt.attempt_id,
                ),
            )
        connection.rollback()

    unchanged = watches.canonical_head(watch_id)
    assert unchanged.latest_attempt is not None
    assert unchanged.latest_attempt.state.value == "running"


def test_watch_attempt_graph_is_removed_by_session_privacy_cascade(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path / "session")
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "3" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    assert watches.claim_due(
        owner="5" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    ) is not None

    with database._connection() as connection:
        # Parent-cascade semantics are probed at the SQLite-owner boundary;
        # production privacy services add their own transient authorizations.
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_watches WHERE watch_id=?",
            (watch_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_analysis_attempts WHERE watch_id=?",
            (watch_id,),
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_watch_publication_history_skips_unchanged_runs_and_pages_newest_first(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    watches = database.model_ensemble_watch_repository()
    first = _run(session_id)
    second = first.model_copy(
        update={
            "run_id": "f" * 64,
            "request_fingerprint": "e" * 64,
        }
    )
    runs.save_completed(first)
    runs.save_completed(second)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watch_id = "7" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=25,
        now=NOW,
    )

    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=20),
        next_check_at=NOW + timedelta(seconds=80),
        outcome=SessionModelEnsembleOutcome(run=first, applied=True),
    )

    # An unchanged observation may advance the worker attempt generation, but
    # it does not manufacture a second trajectory point.
    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=80),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=81),
        next_check_at=NOW + timedelta(seconds=140),
        outcome=SessionModelEnsembleOutcome(run=first, applied=False),
    )
    assert len(watches.list_publications(watch_id, before_generation=None, limit=12).points) == 1

    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=140),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=141),
        next_check_at=NOW + timedelta(seconds=200),
        outcome=SessionModelEnsembleOutcome(run=second, applied=True),
    )

    first_page = watches.list_publications(
        watch_id,
        before_generation=None,
        limit=1,
    )
    assert first_page.head_run_id == second.run_id
    assert first_page.head_generation == 3
    assert tuple(point.generation for point in first_page.points) == (3,)
    assert first_page.next_before_generation == 3
    second_page = watches.list_publications(
        watch_id,
        before_generation=first_page.next_before_generation,
        limit=1,
    )
    assert tuple(point.generation for point in second_page.points) == (1,)
    assert second_page.next_before_generation is None

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError, match="binding"):
            connection.execute(
                """INSERT INTO session_model_ensemble_watch_publications
                   VALUES(?,?,?,?,?)""",
                (
                    watch_id,
                    4,
                    first.run_id,
                    25,
                    (NOW + timedelta(seconds=200)).isoformat(timespec="microseconds"),
                ),
            )


def test_watch_trajectory_requires_exact_source_provenance_for_comparison(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    watches = database.model_ensemble_watch_repository()
    first = _run(session_id)
    changed_redactor = first.model_copy(
        update={
            "run_id": "b" * 64,
            "request_fingerprint": "c" * 64,
            "redactor_version": "synthetic-redactor-v2",
        }
    )
    changed_plan = first.model_copy(
        update={
            "run_id": "d" * 64,
            "request_fingerprint": "e" * 64,
            "receipt": first.receipt.model_copy(
                update={"plan_fingerprint": "f" * 64}
            ),
        }
    )
    runs.save_completed(first)
    runs.save_completed(changed_redactor)
    runs.save_completed(changed_plan)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watch_id = "a" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=25,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=6),
        outcome=SessionModelEnsembleOutcome(run=first, applied=True),
    )
    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=7),
        next_check_at=NOW + timedelta(seconds=8),
        outcome=SessionModelEnsembleOutcome(run=changed_redactor, applied=True),
    )
    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=8),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=9),
        next_check_at=NOW + timedelta(seconds=60),
        outcome=SessionModelEnsembleOutcome(run=changed_plan, applied=True),
    )

    page = watches.list_publications(watch_id, before_generation=None, limit=12)
    assert tuple(point.run_id for point in page.points) == (
        changed_plan.run_id,
        changed_redactor.run_id,
        first.run_id,
    )
    assert page.points[0].comparable_to_head is True
    assert page.points[1].comparable_to_head is False
    assert page.points[2].comparable_to_head is False


def test_privacy_deletion_clears_the_bound_watch_head_atomically(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    run_repository = database.model_ensemble_repository()
    watch_repository = database.model_ensemble_watch_repository()
    run = _run(session_id)
    run_repository.save_completed(run)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watch = watch_repository.enable(
        watch_id="4" * 64,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = watch_repository.claim_due(
        owner="5" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watch = watch_repository.complete(
        lease,
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(minutes=1),
        outcome=SessionModelEnsembleOutcome(run=run, applied=True),
    )
    assert watch.latest_run_id == run.run_id

    assert run_repository.delete_for_privacy(run.run_id) is True

    stored_watch = watch_repository.get(watch.watch_id)
    assert stored_watch is not None
    assert stored_watch.state.value == "disabled"
    assert stored_watch.latest_run_id is None
    assert stored_watch.latest_input_fingerprint is None
    assert run_repository.get(run.run_id) is None
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_watch_publications"
        ).fetchone()[0] == 0


def test_privacy_deletion_revokes_inflight_watch_persistence_and_erases_a_racing_descendant(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    runs = database.model_ensemble_repository()
    watches = database.model_ensemble_watch_repository()
    first = _run(session_id)
    runs.save_completed(first)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watch_id = "d" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="e" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=6),
        outcome=SessionModelEnsembleOutcome(run=first, applied=True),
    )
    claimed = watches.claim_due(
        owner="e" * 64,
        now=NOW + timedelta(seconds=6),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    running, lease = claimed
    descendant = first.model_copy(
        update={
            "run_id": "1" * 64,
            "request_fingerprint": "2" * 64,
            "input_fingerprint": "3" * 64,
            "receipt": first.receipt.model_copy(
                update={"source_window_fingerprint": "3" * 64}
            ),
        }
    )
    authority = SessionModelEnsemblePersistenceAuthority(
        watch_id=watch_id,
        owner=lease.owner,
        token=lease.token,
        generation=running.generation,
        observed_at=NOW + timedelta(seconds=7),
        prior_run_id=first.run_id,
    )

    # If privacy wins the writer transaction, the lease proof fails closed.
    assert runs.delete_for_privacy(first.run_id) is True
    with pytest.raises(DatabaseInvariantError, match="authority"):
        runs.save_completed(descendant, authority=authority)
    assert runs.get(descendant.run_id) is None
    assert watches.get(watch_id).state.value == "disabled"

    # The opposite transaction order is conservative too: privacy deletion is
    # session-wide for shadow derivatives, so a just-committed descendant is
    # erased together with the requested ancestor.
    reenabled = watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        now=NOW + timedelta(seconds=8),
    )
    assert reenabled.latest_run_id is None
    runs.save_completed(first)
    claimed = watches.claim_due(
        owner="e" * 64,
        now=NOW + timedelta(seconds=8),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    running, lease = claimed
    authority = SessionModelEnsemblePersistenceAuthority(
        watch_id=watch_id,
        owner=lease.owner,
        token=lease.token,
        generation=running.generation,
        observed_at=NOW + timedelta(seconds=9),
        prior_run_id=None,
    )
    runs.save_completed(descendant, authority=authority)
    assert runs.get(descendant.run_id) is not None
    assert runs.delete_for_privacy(first.run_id) is True
    assert runs.get(first.run_id) is None
    assert runs.get(descendant.run_id) is None
    surviving_attempts = watches.list_attempts(watch_id, limit=12)
    assert all(item.state.value != "running" for item in surviving_attempts)
    assert any(
        item.state.value == "cancelled" and item.error_code == "privacy_deleted"
        for item in surviving_attempts
    )


def test_continuous_watch_replaces_another_active_session_atomically(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_watch_repository()
    with sqlite3.connect(database.path) as connection:
        first = connection.execute(
            "SELECT project_id,installation_id FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        second_session = "7" * 64
        connection.execute(
            """INSERT INTO sessions(
               session_id,installation_id,project_id,provider,provider_version,
               adapter_version,source_schema_version,started_at,ended_at,
               terminal_state,events_complete,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,'completed',1,?,?)""",
            (
                second_session,
                first[1],
                first[0],
                "codex",
                "codex-app-server-v1",
                "codex-adapter-v1",
                "codex-source-v1",
                NOW.isoformat(timespec="microseconds"),
                NOW.isoformat(timespec="microseconds"),
                NOW.isoformat(timespec="microseconds"),
                NOW.isoformat(timespec="microseconds"),
            ),
        )
        connection.commit()

    first_watch = repository.enable(
        watch_id="6" * 64,
        provider=Provider.CODEX,
        project_id=first[0],
        session_id=session_id,
        now=NOW,
    )
    second_watch = repository.enable(
        watch_id="5" * 64,
        provider=Provider.CODEX,
        project_id=first[0],
        session_id=second_session,
        now=NOW + timedelta(seconds=1),
    )

    assert repository.get(first_watch.watch_id).state.value == "disabled"
    assert repository.get_active() == second_watch
