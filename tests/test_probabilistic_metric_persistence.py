from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from pydantic import SecretStr

import prompt_enhancer.application.analysis.probabilistic_metrics as probabilistic_module
from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.model_ensemble import (
    build_ensemble_chunks,
    coaching_ensemble_metric_specs,
)
from prompt_enhancer.application.analysis.model_ensemble_watch import (
    ModelEnsembleAttemptState,
    ModelEnsembleStageState,
    ModelEnsembleWatchState,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_evidence_readiness_v2 import (
    project_metric_evidence_readiness_v2,
)
from prompt_enhancer.application.analysis.metric_projection_v3 import (
    project_metric_states_v3,
)
from prompt_enhancer.application.analysis.metric_projection_v4 import (
    project_metric_states_v4,
)
from prompt_enhancer.application.analysis.metric_projection_v5 import (
    project_metric_states_v5,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    MetricStateV2,
    OpportunityStatistics,
    _issue_metric_state_projection,
    project_metric_states_v2,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    MetricPublicationSource,
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    ObjectiveMetricOverride,
    ObjectiveWithholdingCause,
)
from prompt_enhancer.application.analysis.probabilistic_metrics import (
    EVIDENCE_LANE_METRIC_KEYS,
    PROBABILISTIC_METRIC_CONTRACTS,
    PROBABILISTIC_METRIC_PROJECTION_VERSION,
    PROBABILISTIC_MODEL_SET_VERSION,
    PROBABILISTIC_MODEL_SET_VERSION_V2,
    PredictiveMetricState,
    SessionPredictiveMetricProjection,
    SessionPredictiveMetricReceipt,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
    COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION,
    COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION,
    MetricProfileSource,
    SessionMetricProfileBinding,
    SessionModelEnsembleOutcome,
    SessionModelEnsembleRunRecord,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitKind,
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    MetricFraction,
    MetricValueState,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseError,
    _MIGRATION_1,
)
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.infrastructure.text_models.probabilistic_metrics import (
    LIVE_PROBABILISTIC_PLAN_VERSION,
    LocalProbabilisticMetricRunner,
    PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.model_ensemble import (
    SqliteSessionModelEnsembleRepository,
    _metric_profile_binding_fingerprint,
    _metric_publication_profile_fingerprint,
    _metric_publication_v2_fingerprint,
    _predictive_projection_fingerprint,
    to_iso,
)
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2042, 4, 5, 12, 0, tzinfo=UTC)
TOKEN = "example_probabilistic_metric_token_1234567890"


class _SyntheticIdFactory:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256(
            "\x1f".join((namespace, *values)).encode("utf-8")
        ).hexdigest()

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join(
                (namespace, *values, secret.get_secret_value())
            ).encode("utf-8")
        ).hexdigest()


IDS = _SyntheticIdFactory()


def _preset_profile_binding(session_id: str) -> SessionMetricProfileBinding:
    return SessionMetricProfileBinding(
        profile_source=MetricProfileSource.COACHING_PROFILE_V1_UNCONFIGURED,
        provider=Provider.CODEX,
        session_id=session_id,
        source_window_fingerprint="a" * 64,
        profile_fingerprint=COACHING_PROFILE_V1_UNCONFIGURED_FINGERPRINT,
        profile_schema_version=COACHING_PROFILE_V1_UNCONFIGURED_SCHEMA_VERSION,
        profile_policy_version=COACHING_PROFILE_V1_UNCONFIGURED_POLICY_VERSION,
        bound_at=NOW,
    )


class _ReadOnlyService:
    def __init__(self, record: SessionModelEnsembleRunRecord) -> None:
        self._record = record

    def get(self, run_id: str) -> SessionModelEnsembleRunRecord | None:
        return self._record if run_id == self._record.run_id else None

    def latest(self, session_id: str) -> SessionModelEnsembleRunRecord | None:
        return self._record if session_id == self._record.session_id else None

    def run(self, **_values):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")


def _context(session_id: str) -> P1TextAnalysisInput:
    messages = (
        EphemeralRedactedMessage(
            message_id="1" * 64,
            sequence=0,
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "Create a fictional parser, preserve unknown values, and verify it with tests."
            ),
        ),
        EphemeralRedactedMessage(
            message_id="2" * 64,
            sequence=1,
            role=TextRole.AGENT,
            kind=TextMessageKind.VERIFICATION,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "The fictional implementation is linked to a synthetic passing test receipt."
            ),
        ),
    )
    return P1TextAnalysisInput(
        provider=Provider.CODEX,
        session_id=session_id,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.VERIFICATION}
        ),
        analysis_window_fingerprint="a" * 64,
        focus_message_id=messages[0].message_id,
        observed_message_count=2,
        eligible_message_count=2,
        messages=messages,
        task_profile=TextTaskProfile(
            applicability=tuple(
                MetricApplicabilityDecision(
                    metric_key=item.key,
                    applicability=MetricApplicability.APPLICABLE,
                    basis=ApplicabilityBasis.USER_SELECTED,
                )
                for item in COACHING_METRIC_DEFINITIONS
            )
        ),
    )


def _database_and_session(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "probabilistic.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_id = database.list_sessions(provider=Provider.SYNTHETIC, limit=1)[0][
        "session_id"
    ]
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE projects SET provider='codex'")
        connection.execute("UPDATE sessions SET provider='codex'")
        connection.commit()
    return database, session_id


def _database_and_session_at_v38(tmp_path) -> tuple[Database, str, str]:
    """Create a real v38 database without allowing Database to auto-upgrade."""

    path = tmp_path / "probabilistic-v38.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 39)
    )
    applied_at = NOW.isoformat(timespec="microseconds")
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
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    applied_at,
                )
                for version, script in enumerate(scripts, start=1)
            ),
        )
        installation_id = "4" * 64
        project_id = "5" * 64
        session_id = "6" * 64
        connection.execute(
            "INSERT INTO installations VALUES(?,?,?)",
            (installation_id, "codex", applied_at),
        )
        connection.execute(
            """INSERT INTO projects(
                   project_id,installation_id,provider,created_at
               ) VALUES(?,?,?,?)""",
            (project_id, installation_id, "codex", applied_at),
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
                "codex",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-source-v1",
                applied_at,
                applied_at,
                applied_at,
                applied_at,
            ),
        )
        connection.execute("PRAGMA user_version=38")
        connection.commit()

    return Database(path), session_id, project_id


def _completed_result(payload):
    return {
        "status": "completed",
        "device": "cuda",
        "rows": [
            {
                "case_id": item["case_id"],
                "entailment": 0.98,
                "neutral": 0.01,
                "contradiction": 0.01,
            }
            for item in payload["cases"]
        ],
        "runtime": {
            "inference_latency_ms": 80.0,
            "peak_cuda_allocated_mb": 900.0,
            "process_rss_after_load_and_inference_mb": 1_400.0,
        },
    }


def _uncertain_result(payload):
    return {
        "status": "completed",
        "device": "cuda",
        "rows": [
            {
                "case_id": item["case_id"],
                "entailment": 0.35,
                "neutral": 0.50,
                "contradiction": 0.15,
            }
            for item in payload["cases"]
        ],
        "runtime": {
            "inference_latency_ms": 80.0,
            "peak_cuda_allocated_mb": 900.0,
            "process_rss_after_load_and_inference_mb": 1_400.0,
        },
    }


def test_predictive_projection_round_trips_is_immutable_and_privacy_cascades(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    runner = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    )
    receipt = runner.run(
        build_ensemble_chunks(_context(session_id)),
        coaching_ensemble_metric_specs(),
    )
    record = SessionModelEnsembleRunRecord(
        run_id="b" * 64,
        session_id=session_id,
        request_fingerprint="c" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=receipt,
    )

    repository = database.model_ensemble_repository()
    repository.save_completed(record)

    # A stored v35/v1 receipt is historical data. Advancing the active live
    # registry must not make that immutable row unreadable.
    advanced = replace(
        PROBABILISTIC_METRIC_CONTRACTS[0],
        contract_version="probabilistic-metric-contract-v2",
    )
    advanced_registry = (advanced, *PROBABILISTIC_METRIC_CONTRACTS[1:])
    monkeypatch.setattr(
        probabilistic_module,
        "PROBABILISTIC_METRIC_CONTRACTS",
        advanced_registry,
    )
    monkeypatch.setattr(
        probabilistic_module,
        "_CONTRACT_BY_KEY",
        {item.metric_key: item for item in advanced_registry},
    )
    loaded = repository.get(record.run_id)

    assert loaded is not None
    assert loaded.receipt.predictive_projection == receipt.predictive_projection
    assert loaded.receipt.predictive_projection is not None
    assert len(loaded.receipt.predictive_projection.metrics) == 20
    by_key = {
        item.metric_key: item
        for item in loaded.receipt.predictive_projection.metrics
    }
    assert all(
        by_key[key].state is PredictiveMetricState.UNAVAILABLE
        for key in EVIDENCE_LANE_METRIC_KEYS
    )
    contract_by_key = {
        item.metric_key: item for item in PROBABILISTIC_METRIC_CONTRACTS
    }
    assert all(
        item.state
        is (
            PredictiveMetricState.EXPERIMENTAL
            if contract_by_key[key].closure_horizon == "immediate"
            and not contract_by_key[key].objective_evidence_required
            and key not in EVIDENCE_LANE_METRIC_KEYS
            else PredictiveMetricState.UNAVAILABLE
        )
        for key, item in by_key.items()
    )

    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "9" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
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
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(seconds=61),
        outcome=SessionModelEnsembleOutcome(run=record, applied=True),
    )
    first_attempt = watches.list_attempts(watch_id, limit=1)[0]
    assert first_attempt.stage_count == 3

    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=61),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=62),
        next_check_at=NOW + timedelta(seconds=122),
        outcome=SessionModelEnsembleOutcome(run=record, applied=False),
    )
    reused_attempt = watches.list_attempts(watch_id, limit=1)[0]
    assert reused_attempt.stage_count == 0
    assert watches.get_attempt_stages(reused_attempt.attempt_id) == ()
    with sqlite3.connect(database.path) as connection:
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed test constants
            ).fetchone()[0]
            for table in (
                "session_model_ensemble_predictive_metrics",
                "session_model_ensemble_predictive_factors",
                "session_model_ensemble_predictive_density_bins",
                "session_model_ensemble_predictive_model_stages",
                "session_model_ensemble_predictive_metric_seals",
            )
        }
        assert counts["session_model_ensemble_predictive_metrics"] == 20
        assert counts["session_model_ensemble_predictive_density_bins"] == 160
        assert counts["session_model_ensemble_predictive_model_stages"] == 3
        assert counts["session_model_ensemble_predictive_metric_seals"] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE session_model_ensemble_predictive_metrics
                   SET mean=0.0 WHERE run_id=? AND projection_version=?""",
                (record.run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
            )

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=_ReadOnlyService(record),  # type: ignore[arg-type]
    )
    metric_key = receipt.predictive_projection.metrics[0].metric_key
    detail_path = (
        f"/v1/model-ensemble-runs/{record.run_id}/metrics/{metric_key}/predictive-detail"
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get(detail_path).status_code == 401
        detail = client.get(detail_path, headers={API_TOKEN_HEADER: TOKEN})
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store, private"
    assert detail.headers["pragma"] == "no-cache"
    payload = detail.json()
    assert payload["experimental_label"] == "Experimental model range"
    assert payload["universal_trust_percentage_available"] is False
    assert len(payload["density_bins"]) == 20
    assert payload["factors"]
    assert "source_window_fingerprint" not in detail.text
    assert "fragment_id" not in detail.text
    assert "fictional parser" not in detail.text.lower()

    database_bytes = database.path.read_bytes()
    assert b"Create a fictional parser" not in database_bytes
    assert b"fictional implementation" not in database_bytes

    assert repository.delete_for_privacy(record.run_id) is True
    with sqlite3.connect(database.path) as connection:
        for table in (
            "session_model_ensemble_predictive_metrics",
            "session_model_ensemble_predictive_factors",
            "session_model_ensemble_predictive_density_bins",
            "session_model_ensemble_predictive_model_stages",
            "session_model_ensemble_predictive_metric_seals",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed test constants
            ).fetchone()[0] == 0


def test_metric_v2_publication_round_trips_is_immutable_and_privacy_cascades(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )
    assert publication.source is MetricPublicationSource.LIVE_PROJECTION
    assert publication.canonical_live_snapshot is True
    assert publication.compatibility_preview is False
    assert publication.model_stage_consumed is False
    assert len(publication.metrics) == 20

    receipt = receipt.model_copy(
        update={"metric_publication_v2": publication}
    )
    record = SessionModelEnsembleRunRecord(
        run_id="7" * 64,
        session_id=session_id,
        request_fingerprint="8" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=_preset_profile_binding(session_id),
        receipt=receipt,
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, record)

    loaded = repository.get(record.run_id)
    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 == publication
    assert {item.metric_key for item in loaded.receipt.metrics} == {
        item.metric_key for item in record.receipt.metrics
    }

    # A projection fingerprint seals content; it is not a global run identity.
    # Two independent runs may legitimately publish the same twenty states.
    second = record.model_copy(
        update={
            "run_id": "6" * 64,
            "request_fingerprint": "5" * 64,
            "receipt": record.receipt.model_copy(
                update={"predictive_projection": None}
            ),
        }
    )
    _save_historical_r5_fixture(database, second)
    second_loaded = repository.get(second.run_id)
    assert second_loaded is not None
    assert second_loaded.receipt.metric_publication_v2 == publication
    third = second.model_copy(
        update={
            "run_id": "0" * 64,
            "request_fingerprint": "9" * 64,
        }
    )
    _save_historical_r5_fixture(database, third)

    legacy = second.model_copy(
        update={
            "run_id": "4" * 64,
            "request_fingerprint": "3" * 64,
            "metric_profile_binding": None,
            "receipt": second.receipt.model_copy(
                update={"metric_publication_v2": None}
            ),
        }
    )
    repository.save_completed(legacy)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "2" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner="1" * 64,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(seconds=2),
        outcome=SessionModelEnsembleOutcome(run=legacy, applied=True),
    )
    claimed = watches.claim_due(
        owner="1" * 64,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=3),
        next_check_at=NOW + timedelta(seconds=4),
        outcome=SessionModelEnsembleOutcome(run=second, applied=True),
    )
    claimed = watches.claim_due(
        owner="1" * 64,
        now=NOW + timedelta(seconds=4),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=5),
        next_check_at=NOW + timedelta(seconds=60),
        outcome=SessionModelEnsembleOutcome(run=third, applied=True),
    )
    trajectory = watches.list_publications(
        watch_id,
        before_generation=None,
        limit=12,
    )
    assert tuple(point.run_id for point in trajectory.points) == (
        third.run_id,
        second.run_id,
        legacy.run_id,
    )
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is True
    assert trajectory.points[2].comparable_to_head is False
    assert trajectory.points[0].metric_states_v2 == tuple(
        item.state for item in publication.metrics
    )
    assert trajectory.points[1].metric_states_v2 == trajectory.points[0].metric_states_v2
    assert trajectory.points[2].metric_states_v2 == ()

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute(
            """SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 20
        assert connection.execute(
            """SELECT COUNT(*)
               FROM session_model_ensemble_metric_publication_v2_seals_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_metric_states_v2_r5
                   SET source_complete=source_complete
                   WHERE run_id=?""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="sealed"):
            connection.execute(
                """INSERT INTO session_model_ensemble_metric_states_v2_r5
                   SELECT * FROM session_model_ensemble_metric_states_v2_r5
                   WHERE run_id=? LIMIT 1""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_metric_publication_v2_seals_r5
                   SET known_count=known_count WHERE run_id=?""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                """DELETE FROM session_model_ensemble_metric_states_v2_r5
                   WHERE run_id=?""",
                (record.run_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                """DELETE FROM session_model_ensemble_metric_publication_v2_seals_r5
                   WHERE run_id=?""",
                (record.run_id,),
            )

    database_bytes = database.path.read_bytes()
    assert b"Create a fictional parser" not in database_bytes
    assert b"fictional implementation" not in database_bytes

    assert repository.delete_for_privacy(record.run_id) is True
    # Privacy deletion is deliberately session-wide, so the sibling run is
    # erased by the same operation.
    assert repository.get(second.run_id) is None
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            """SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            """SELECT COUNT(*)
               FROM session_model_ensemble_metric_publication_v2_seals_r5
               WHERE run_id=?""",
            (record.run_id,),
        ).fetchone()[0] == 0


def _feedback_focus_context(session_id: str) -> P1TextAnalysisInput:
    """The same window, but the scored focus turn is feedback, not the request."""

    context = _context(session_id)
    feedback = EphemeralRedactedMessage(
        message_id="3" * 64,
        sequence=2,
        role=TextRole.USER,
        kind=TextMessageKind.FEEDBACK,
        language=TextLanguage.ENGLISH,
        text=SecretStr("A neutral fictional remark about the parser."),
    )
    messages = (*context.messages, feedback)
    return context.model_copy(
        update={
            "messages": messages,
            "focus_message_id": feedback.message_id,
            "available_message_kinds": frozenset(
                item.kind for item in messages
            ),
            "observed_message_count": len(messages),
            "eligible_message_count": len(messages),
        }
    )


def test_unowned_rubric_focus_stays_withheld_through_storage_and_the_api(
    tmp_path,
) -> None:
    """A rubric fraction scored on an unowned turn never becomes a stored number."""

    database, session_id = _database_and_session(tmp_path)
    context = _feedback_focus_context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    rubric_keys = (
        "prompt.task_definition_coverage",
        "prompt.problem_evidence_quality",
        "prompt.context_sufficiency",
    )
    perfect_rubric = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic_rubric_result",
    )
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
            conversational_results={key: perfect_rubric for key in rubric_keys},
        )
    )
    published = {item.state.metric_key: item.state for item in publication.metrics}
    for key in rubric_keys:
        assert published[key].value_state is MetricValueStateV2.UNKNOWN
        assert published[key].numeric_value is None
        assert published[key].explanation_code == "rubric_opportunity_not_focus_owned"

    record = SessionModelEnsembleRunRecord(
        run_id="7" * 64,
        session_id=session_id,
        request_fingerprint="8" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=_preset_profile_binding(session_id),
        receipt=receipt.model_copy(
            update={"metric_publication_v2": publication}
        ),
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, record)
    loaded = repository.get(record.run_id)

    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 == publication
    reloaded = {
        item.state.metric_key: item.state
        for item in loaded.receipt.metric_publication_v2.metrics
    }
    for key in rubric_keys:
        assert reloaded[key].value_state is MetricValueStateV2.UNKNOWN
        assert reloaded[key].numerator is reloaded[key].denominator is None

    with sqlite3.connect(database.path) as connection:
        # The stored rows carry the corrected projection identity and no value.
        assert connection.execute(
            """SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r5
               WHERE run_id=? AND projection_version='metric-contract-v2-projection-5'""",
            (record.run_id,),
        ).fetchone()[0] == 20
        stored = connection.execute(
            """SELECT value_state,numeric_value,explanation_code
               FROM session_model_ensemble_metric_states_v2_r5
               WHERE run_id=? AND metric_key=?""",
            (record.run_id, "prompt.task_definition_coverage"),
        ).fetchone()
        assert stored == (
            "unknown",
            None,
            "rubric_opportunity_not_focus_owned",
        )
        # Nothing was written to the frozen r1 sidecar.
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2"
        ).fetchone()[0] == 0

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=_ReadOnlyService(loaded),  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            f"/v1/sessions/{session_id}/model-ensemble-runs/latest",
            headers={API_TOKEN_HEADER: TOKEN},
        )
    assert response.status_code == 200
    payload = response.json()
    served = {
        item["state"]["metric_key"]: item
        for item in payload["metric_publication_v2"]["metrics"]
    }
    readiness = {
        item["metric_key"]: item
        for item in payload["metric_evidence_readiness_v2"]["metrics"]
    }
    for key in rubric_keys:
        assert served[key]["state"]["value_state"] == "unknown"
        assert served[key]["state"]["numeric_value"] is None
        assert served[key]["implementation_state"] == "method_only_withheld"
        assert readiness[key]["availability_state"] == "capability_missing"
        assert (
            readiness[key]["reason_code"]
            == "focus_owned_request_revision_required"
        )
        assert readiness[key]["observed_contributors"] == []
    assert (
        payload["metric_evidence_readiness_v2"]["metric_projection_version"]
        == "metric-contract-v2-projection-5"
    )
    assert payload["metric_evidence_readiness_v2"]["product_metric_eligible"] is False
    assert payload["metric_evidence_readiness_v2"]["calibration_state"] == (
        "not_assessed"
    )
    assert "fictional" not in response.text.lower()
    assert session_id not in response.text


@pytest.mark.parametrize(
    (
        "cause",
        "explanation_code",
        "expected_availability",
        "expected_reason",
        "expected_source_complete",
        "expected_observed_contributors",
    ),
    (
        (
            ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE,
            "typed_objective_extraction_incomplete",
            "source_incomplete",
            "source_reconciliation_incomplete",
            False,
            [],
        ),
        (
            ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED,
            "typed_objective_opportunity_count_exceeds_receipt_bound",
            "evidence_unresolved",
            "opportunity_set_exceeds_receipt_bound",
            True,
            ["declared_objective_opportunity_set"],
        ),
    ),
)
def test_r5_objective_withholding_dimension_survives_persistence_and_api(
    tmp_path,
    cause: ObjectiveWithholdingCause,
    explanation_code: str,
    expected_availability: str,
    expected_reason: str,
    expected_source_complete: bool,
    expected_observed_contributors: list[str],
) -> None:
    """The sealed flags, not prose, preserve the exact remediation dimension."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    metric_key = "outcome.agent_claim_grounding"
    override = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code=explanation_code,
        withholding_cause=cause,
    )
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
            objective_overrides={metric_key: override},
        )
    )
    record = SessionModelEnsembleRunRecord(
        run_id=("1" if expected_source_complete else "2") * 64,
        session_id=session_id,
        request_fingerprint=("3" if expected_source_complete else "4") * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=_preset_profile_binding(session_id),
        receipt=receipt.model_copy(update={"metric_publication_v2": publication}),
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, record)
    loaded = repository.get(record.run_id)

    assert loaded is not None
    sealed = next(
        item.state
        for item in loaded.receipt.metric_publication_v2.metrics
        if item.state.metric_key == metric_key
    )
    assert sealed.statistics.capability_available is True
    assert sealed.statistics.source_complete is expected_source_complete
    assert sealed.statistics.eligible_count == 0

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=_ReadOnlyService(loaded),  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            f"/v1/sessions/{session_id}/model-ensemble-runs/latest",
            headers={API_TOKEN_HEADER: TOKEN},
        )
    assert response.status_code == 200
    body = response.json()
    published = next(
        item
        for item in body["metric_publication_v2"]["metrics"]
        if item["state"]["metric_key"] == metric_key
    )
    readiness = next(
        item
        for item in body["metric_evidence_readiness_v2"]["metrics"]
        if item["metric_key"] == metric_key
    )
    assert published["implementation_state"] == "objective_evidence_unresolved"
    assert readiness["availability_state"] == expected_availability
    assert readiness["reason_code"] == expected_reason
    assert readiness["observed_contributors"] == expected_observed_contributors
    assert readiness["eligible_count"] == 0
    assert readiness["product_metric_eligible"] is False
    assert "fictional" not in response.text.lower()
    assert session_id not in response.text


def _legacy_r1_publication(publication):  # type: ignore[no-untyped-def]
    """The same twenty metrics as identity ``-1`` would have published them.

    The rubric row carries the borrowed-ownership number that identity ``-1``
    could produce and identity ``-2`` refuses to.
    """

    borrowed = MetricStateV2(
        metric_key="prompt.task_definition_coverage",
        contract_version="probabilistic-metric-contract-v2",
        contract_fingerprint=next(
            item.state.contract_fingerprint
            for item in publication.metrics
            if item.state.metric_key == "prompt.task_definition_coverage"
        ),
        evidence_authority=EvidenceAuthority.CONVERSATION,
        value_state=MetricValueStateV2.KNOWN,
        explanation_code="legacy_borrowed_rubric",
        numerator=3,
        denominator=3,
        numeric_value=1.0,
        censoring_lower_bound=1.0,
        censoring_upper_bound=1.0,
        statistics=OpportunityStatistics(
            metric_key="prompt.task_definition_coverage",
            denominator_basis=DenominatorBasis.RUBRIC_FACTORS,
            opportunity_unit_kind=SemanticUnitKind.REQUEST_REVISION,
            capability_available=True,
            source_complete=True,
            eligible_count=3,
            met_count=3,
            distinct_owner_count=1,
        ),
        projection_version="metric-contract-v2-projection-1",
    )
    states = tuple(
        borrowed
        if item.state.metric_key == "prompt.task_definition_coverage"
        else item.state.model_copy(
            update={"projection_version": "metric-contract-v2-projection-1"}
        )
        for item in publication.metrics
    )
    return publish_metric_states_v2(
        _issue_metric_state_projection(states, compatibility=False)
    )


def _insert_frozen_metric_sidecar(  # type: ignore[no-untyped-def]
    database,
    run_id: str,
    publication,
    *,
    states_table: str,
    seals_table: str,
) -> None:
    """Write one historical publication into its frozen synthetic sidecar."""

    assert (states_table, seals_table) in {
        (
            "session_model_ensemble_metric_states_v2",
            "session_model_ensemble_metric_publication_v2_seals",
        ),
        (
            "session_model_ensemble_metric_states_v2_r2",
            "session_model_ensemble_metric_publication_v2_seals_r2",
        ),
        (
            "session_model_ensemble_metric_states_v2_r3",
            "session_model_ensemble_metric_publication_v2_seals_r3",
        ),
        (
            "session_model_ensemble_metric_states_v2_r4",
            "session_model_ensemble_metric_publication_v2_seals_r4",
        ),
    }

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            f"""INSERT INTO {states_table}(
                   run_id,metric_ordinal,registry_version,projection_version,
                   metric_key,contract_version,contract_fingerprint,
                   evidence_authority,value_state,explanation_code,numerator,
                   denominator,numeric_value,censoring_lower_bound,
                   censoring_upper_bound,denominator_basis,opportunity_unit_kind,
                   capability_available,source_complete,eligible_count,met_count,
                   not_met_count,pending_count,unknown_count,
                   superseded_excluded_count,distinct_owner_count,
                   product_metric_eligible
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            tuple(
                (
                    run_id,
                    ordinal,
                    publication.registry_version,
                    publication.projection_version,
                    item.state.metric_key,
                    item.state.contract_version,
                    item.state.contract_fingerprint,
                    item.state.evidence_authority.value,
                    item.state.value_state.value,
                    item.state.explanation_code,
                    item.state.numerator,
                    item.state.denominator,
                    item.state.numeric_value,
                    item.state.censoring_lower_bound,
                    item.state.censoring_upper_bound,
                    item.state.statistics.denominator_basis.value,
                    (
                        None
                        if item.state.statistics.opportunity_unit_kind is None
                        else item.state.statistics.opportunity_unit_kind.value
                    ),
                    int(item.state.statistics.capability_available),
                    int(item.state.statistics.source_complete),
                    item.state.statistics.eligible_count,
                    item.state.statistics.met_count,
                    item.state.statistics.not_met_count,
                    item.state.statistics.pending_count,
                    item.state.statistics.unknown_count,
                    item.state.statistics.superseded_excluded_count,
                    item.state.statistics.distinct_owner_count,
                )
                for ordinal, item in enumerate(publication.metrics)
            ),
        )
        connection.execute(
            f"""INSERT INTO {seals_table}(
                   run_id,publication_key,publication_version,registry_version,
                   contract_set_fingerprint,projection_version,
                   guidance_contract_version,guidance_template_catalog_version,
                   source,canonical_live_snapshot,model_stage_consumed,
                   compatibility_preview,metric_count,known_count,pending_count,
                   unknown_count,not_applicable_count,abstained_count,
                   execution_error_count,objective_measured_count,
                   projection_fingerprint,projected_at,local_only,
                   content_persisted,product_metric_eligible
               ) VALUES(?,?,?,?,?,?,?,?,?,1,0,0,?,?,?,?,?,?,?,?,?,?,1,0,0)""",
            (
                run_id,
                publication.publication_key,
                publication.publication_version,
                publication.registry_version,
                publication.contract_set_fingerprint,
                publication.projection_version,
                publication.guidance_contract_version,
                publication.guidance_template_catalog_version,
                publication.source.value,
                len(publication.metrics),
                publication.known_count,
                publication.pending_count,
                publication.unknown_count,
                publication.not_applicable_count,
                publication.abstained_count,
                publication.execution_error_count,
                publication.objective_measured_count,
                _metric_publication_v2_fingerprint(publication),
                NOW.isoformat(timespec="microseconds"),
            ),
        )
        connection.commit()


def _insert_legacy_r1_sidecar(database, run_id: str, publication) -> None:  # type: ignore[no-untyped-def]
    """Write one ``-1`` publication straight into the frozen v40 sidecar."""

    _insert_frozen_metric_sidecar(
        database,
        run_id,
        publication,
        states_table="session_model_ensemble_metric_states_v2",
        seals_table="session_model_ensemble_metric_publication_v2_seals",
    )


def _insert_legacy_r2_sidecar(database, run_id: str, publication) -> None:  # type: ignore[no-untyped-def]
    """Write one ``-2`` publication straight into the frozen v41 sidecar."""

    _insert_frozen_metric_sidecar(
        database,
        run_id,
        publication,
        states_table="session_model_ensemble_metric_states_v2_r2",
        seals_table="session_model_ensemble_metric_publication_v2_seals_r2",
    )


def _insert_legacy_r3_sidecar(database, run_id: str, publication) -> None:  # type: ignore[no-untyped-def]
    """Write one ``-3`` publication straight into the frozen v42 sidecar."""

    _insert_frozen_metric_sidecar(
        database,
        run_id,
        publication,
        states_table="session_model_ensemble_metric_states_v2_r3",
        seals_table="session_model_ensemble_metric_publication_v2_seals_r3",
    )


def _insert_legacy_r4_sidecar(database, run_id: str, publication) -> None:  # type: ignore[no-untyped-def]
    """Write one ``-4`` publication straight into the frozen v44 sidecar."""

    _insert_frozen_metric_sidecar(
        database,
        run_id,
        publication,
        states_table="session_model_ensemble_metric_states_v2_r4",
        seals_table="session_model_ensemble_metric_publication_v2_seals_r4",
    )


_METRIC_V2_STATE_COLUMNS = (
    "run_id,metric_ordinal,registry_version,projection_version,metric_key,"
    "contract_version,contract_fingerprint,evidence_authority,value_state,"
    "explanation_code,numerator,denominator,numeric_value,"
    "censoring_lower_bound,censoring_upper_bound,denominator_basis,"
    "opportunity_unit_kind,capability_available,source_complete,"
    "eligible_count,met_count,not_met_count,pending_count,unknown_count,"
    "superseded_excluded_count,distinct_owner_count,product_metric_eligible"
)


_METRIC_V2_SEAL_COLUMNS = (
    "run_id,publication_key,publication_version,registry_version,"
    "contract_set_fingerprint,projection_version,guidance_contract_version,"
    "guidance_template_catalog_version,source,canonical_live_snapshot,"
    "model_stage_consumed,compatibility_preview,metric_count,known_count,"
    "pending_count,unknown_count,not_applicable_count,abstained_count,"
    "execution_error_count,objective_measured_count,projection_fingerprint,"
    "projected_at,local_only,content_persisted,product_metric_eligible"
)


def _save_historical_r5_fixture(database, record) -> None:  # type: ignore[no-untyped-def]
    """Persist frozen r5 rows without reopening the current production writer."""

    publication = record.receipt.metric_publication_v2
    binding = record.metric_profile_binding
    assert publication is not None
    assert publication.projection_version == "metric-contract-v2-projection-5"
    assert binding is not None
    bare = record.model_copy(
        update={
            "metric_profile_binding": None,
            "requirement_plan_evidence_binding": None,
            "receipt": record.receipt.model_copy(
                update={"metric_publication_v2": None}
            ),
        }
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(bare)
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        SqliteSessionModelEnsembleRepository._insert_metric_profile_binding(
            connection,
            record,
        )
        connection.executemany(
            f"""INSERT INTO session_model_ensemble_metric_states_v2_r5(
                   {_METRIC_V2_STATE_COLUMNS}
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            tuple(
                (
                    record.run_id,
                    ordinal,
                    publication.registry_version,
                    publication.projection_version,
                    item.state.metric_key,
                    item.state.contract_version,
                    item.state.contract_fingerprint,
                    item.state.evidence_authority.value,
                    item.state.value_state.value,
                    item.state.explanation_code,
                    item.state.numerator,
                    item.state.denominator,
                    item.state.numeric_value,
                    item.state.censoring_lower_bound,
                    item.state.censoring_upper_bound,
                    item.state.statistics.denominator_basis.value,
                    (
                        None
                        if item.state.statistics.opportunity_unit_kind is None
                        else item.state.statistics.opportunity_unit_kind.value
                    ),
                    int(item.state.statistics.capability_available),
                    int(item.state.statistics.source_complete),
                    item.state.statistics.eligible_count,
                    item.state.statistics.met_count,
                    item.state.statistics.not_met_count,
                    item.state.statistics.pending_count,
                    item.state.statistics.unknown_count,
                    item.state.statistics.superseded_excluded_count,
                    item.state.statistics.distinct_owner_count,
                )
                for ordinal, item in enumerate(publication.metrics)
            ),
        )
        projected_at = (
            record.receipt.metric_projection_completed_at
            or record.receipt.completed_at
        )
        connection.execute(
            """INSERT INTO session_model_ensemble_metric_publication_v2_seals_r5(
                   run_id,publication_key,publication_version,registry_version,
                   contract_set_fingerprint,projection_version,
                   guidance_contract_version,guidance_template_catalog_version,
                   source,canonical_live_snapshot,model_stage_consumed,
                   compatibility_preview,metric_count,known_count,pending_count,
                   unknown_count,not_applicable_count,abstained_count,
                   execution_error_count,objective_measured_count,
                   projection_fingerprint,profile_source,profile_id,
                   profile_revision,profile_fingerprint,profile_schema_version,
                   profile_policy_version,profile_binding_fingerprint,
                   publication_profile_fingerprint,projected_at,local_only,
                   content_persisted,product_metric_eligible
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.run_id,
                publication.publication_key,
                publication.publication_version,
                publication.registry_version,
                publication.contract_set_fingerprint,
                publication.projection_version,
                publication.guidance_contract_version,
                publication.guidance_template_catalog_version,
                publication.source.value,
                1,
                0,
                0,
                len(publication.metrics),
                publication.known_count,
                publication.pending_count,
                publication.unknown_count,
                publication.not_applicable_count,
                publication.abstained_count,
                publication.execution_error_count,
                publication.objective_measured_count,
                _metric_publication_v2_fingerprint(publication),
                binding.profile_source.value,
                binding.profile_id,
                binding.profile_revision,
                binding.profile_fingerprint,
                binding.profile_schema_version,
                binding.profile_policy_version,
                _metric_profile_binding_fingerprint(binding),
                _metric_publication_profile_fingerprint(publication, binding),
                to_iso(projected_at),
                1,
                0,
                0,
            ),
        )
        connection.commit()

    loaded = repository.get(record.run_id)
    assert loaded is not None
    assert loaded.metric_profile_binding == binding
    assert loaded.receipt.metric_publication_v2 == publication


def _copy_seal_with_identity(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    target_table: str,
    projection_version: str,
    target_run_id: str | None = None,
) -> None:
    """Re-seal the current sidecar under a different projection identity."""

    connection.execute(
        f"""INSERT INTO {target_table}({_METRIC_V2_SEAL_COLUMNS})
            SELECT ?,publication_key,publication_version,registry_version,
                   contract_set_fingerprint,?,guidance_contract_version,
                   guidance_template_catalog_version,source,
                   canonical_live_snapshot,model_stage_consumed,
                   compatibility_preview,metric_count,known_count,
                   pending_count,unknown_count,not_applicable_count,
                   abstained_count,execution_error_count,
                   objective_measured_count,projection_fingerprint,
                   projected_at,local_only,content_persisted,
                   product_metric_eligible
            FROM session_model_ensemble_metric_publication_v2_seals_r5
            WHERE run_id=?""",
        (target_run_id or run_id, projection_version, run_id),
    )


def _copy_one_current_state(
    connection: sqlite3.Connection,
    *,
    source_run_id: str,
    target_run_id: str,
    target_table: str,
    projection_version: str,
) -> None:
    """Copy one content-free typed row across synthetic run fixtures."""

    assert target_table in {
        "session_model_ensemble_metric_states_v2",
        "session_model_ensemble_metric_states_v2_r2",
        "session_model_ensemble_metric_states_v2_r3",
        "session_model_ensemble_metric_states_v2_r4",
    }
    connection.execute(
        f"""INSERT INTO {target_table}({_METRIC_V2_STATE_COLUMNS})
            SELECT ?,metric_ordinal,registry_version,?,metric_key,
                   contract_version,contract_fingerprint,evidence_authority,
                   value_state,explanation_code,numerator,denominator,
                   numeric_value,censoring_lower_bound,censoring_upper_bound,
                   denominator_basis,opportunity_unit_kind,
                   capability_available,source_complete,eligible_count,
                   met_count,not_met_count,pending_count,unknown_count,
                   superseded_excluded_count,distinct_owner_count,
                   product_metric_eligible
            FROM session_model_ensemble_metric_states_v2_r5
            WHERE run_id=? ORDER BY metric_ordinal LIMIT 1""",
        (target_run_id, projection_version, source_run_id),
    )


def test_legacy_projection_r1_rows_stay_readable_with_their_own_identity(
    tmp_path,
) -> None:
    """MIGRATION_40 rows keep meaning exactly what their producer meant."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    current = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )
    legacy = _legacy_r1_publication(current)
    assert legacy.projection_version == "metric-contract-v2-projection-1"

    record = SessionModelEnsembleRunRecord(
        run_id="7" * 64,
        session_id=session_id,
        request_fingerprint="8" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=receipt,
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(record)
    assert repository.get(record.run_id).receipt.metric_publication_v2 is None

    # Current repository code may read r1, but it must never mint a new r1
    # publication under the frozen producer identity.
    sidecar_free = receipt.model_copy(
        update={
            "metric_projection_version": None,
            "metric_projection_completed_at": None,
            "typed_metrics": (),
            "metric_publication_v2": legacy,
            "predictive_projection": None,
        }
    )
    stale_write = record.model_copy(
        update={
            "run_id": "9" * 64,
            "request_fingerprint": "d" * 64,
            "receipt": sidecar_free,
        }
    )
    with pytest.raises(DatabaseError, match="current projection identity"):
        repository.save_completed(stale_write)
    assert repository.get(stale_write.run_id) is None

    _insert_legacy_r1_sidecar(database, record.run_id, legacy)

    loaded = repository.get(record.run_id)

    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 == legacy
    rehydrated = loaded.receipt.metric_publication_v2
    assert rehydrated.projection_version == "metric-contract-v2-projection-1"
    borrowed = next(
        item.state
        for item in rehydrated.metrics
        if item.state.metric_key == "prompt.task_definition_coverage"
    )
    # The historical number survives verbatim; it is not relabelled as an
    # identity ``-2`` value and not silently withheld.
    assert borrowed.value_state is MetricValueStateV2.KNOWN
    assert (borrowed.numerator, borrowed.denominator) == (3, 3)
    assert borrowed.projection_version == "metric-contract-v2-projection-1"
    assert all(
        item.state.projection_version == "metric-contract-v2-projection-1"
        for item in rehydrated.metrics
    )

    readiness = project_metric_evidence_readiness_v2(
        rehydrated,
        provider=loaded.provider,
        provider_version=loaded.provider_version,
        adapter_version=loaded.adapter_version,
        source_schema_version=loaded.source_schema_version,
    )
    assert readiness.metric_projection_version == "metric-contract-v2-projection-1"

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r2"
        ).fetchone()[0] == 0
        # One run may never carry both identities at once.
        with pytest.raises(sqlite3.IntegrityError, match="sealed"):
            connection.execute(
                """INSERT INTO session_model_ensemble_metric_states_v2_r2
                   SELECT * FROM session_model_ensemble_metric_states_v2
                   WHERE run_id=? LIMIT 1""",
                (record.run_id,),
            )


def test_frozen_projection_r2_rows_stay_readable_after_r5_becomes_current(
    tmp_path,
) -> None:
    """MIGRATION_41 rows rehydrate as r2 while every new write requires r5."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    legacy = publish_metric_states_v2(
        project_metric_states_v2(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )
    assert legacy.projection_version == "metric-contract-v2-projection-2"
    record = SessionModelEnsembleRunRecord(
        run_id="6" * 64,
        session_id=session_id,
        request_fingerprint="5" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=receipt,
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(record)

    stale_write = record.model_copy(
        update={
            "run_id": "3" * 64,
            "request_fingerprint": "2" * 64,
            "receipt": receipt.model_copy(
                update={
                    "metric_projection_version": None,
                    "metric_projection_completed_at": None,
                    "typed_metrics": (),
                    "metric_publication_v2": legacy,
                    "predictive_projection": None,
                }
            ),
        }
    )
    with pytest.raises(DatabaseError, match="current projection identity"):
        repository.save_completed(stale_write)
    assert repository.get(stale_write.run_id) is None

    _insert_legacy_r2_sidecar(database, record.run_id, legacy)
    loaded = repository.get(record.run_id)

    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 == legacy
    assert loaded.receipt.metric_publication_v2.projection_version == (
        "metric-contract-v2-projection-2"
    )
    assert all(
        item.state.projection_version == "metric-contract-v2-projection-2"
        for item in loaded.receipt.metric_publication_v2.metrics
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r3"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r4"
        ).fetchone()[0] == 0


def test_frozen_projection_r3_rows_stay_readable_after_r5_becomes_current(
    tmp_path,
) -> None:
    """MIGRATION_42 rows rehydrate as r3 while every new write requires r5."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    legacy = publish_metric_states_v2(
        project_metric_states_v3(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    assert legacy.projection_version == "metric-contract-v2-projection-3"
    record = SessionModelEnsembleRunRecord(
        run_id="6" * 64,
        session_id=session_id,
        request_fingerprint="5" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=receipt,
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(record)
    stale_write = record.model_copy(
        update={
            "run_id": "3" * 64,
            "request_fingerprint": "2" * 64,
            "receipt": receipt.model_copy(
                update={
                    "metric_projection_version": None,
                    "metric_projection_completed_at": None,
                    "typed_metrics": (),
                    "metric_publication_v2": legacy,
                    "predictive_projection": None,
                }
            ),
        }
    )
    with pytest.raises(DatabaseError, match="current projection identity"):
        repository.save_completed(stale_write)
    assert repository.get(stale_write.run_id) is None

    _insert_legacy_r3_sidecar(database, record.run_id, legacy)
    loaded = repository.get(record.run_id)
    assert loaded is not None
    assert loaded.receipt.metric_publication_v2 == legacy
    assert all(
        item.state.projection_version == "metric-contract-v2-projection-3"
        for item in loaded.receipt.metric_publication_v2.metrics
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r4"
        ).fetchone()[0] == 0


def test_frozen_projection_r4_rows_stay_readable_after_r5_becomes_current(
    tmp_path,
) -> None:
    """MIGRATION_44 rows rehydrate as r4 while every new write requires r5."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    legacy = publish_metric_states_v2(
        project_metric_states_v4(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    assert legacy.projection_version == "metric-contract-v2-projection-4"
    record = SessionModelEnsembleRunRecord(
        run_id="6" * 64,
        session_id=session_id,
        request_fingerprint="5" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=receipt,
    )
    repository = database.model_ensemble_repository()
    repository.save_completed(record)
    stale_write = record.model_copy(
        update={
            "run_id": "3" * 64,
            "request_fingerprint": "2" * 64,
            "receipt": receipt.model_copy(
                update={
                    "metric_publication_v2": legacy,
                    "predictive_projection": None,
                }
            ),
        }
    )
    with pytest.raises(DatabaseError, match="current projection identity"):
        repository.save_completed(stale_write)
    assert repository.get(stale_write.run_id) is None

    _insert_legacy_r4_sidecar(database, record.run_id, legacy)
    loaded = repository.get(record.run_id)

    assert loaded is not None
    assert loaded.metric_profile_binding is None
    assert loaded.receipt.metric_publication_v2 == legacy
    assert all(
        item.state.projection_version == "metric-contract-v2-projection-4"
        for item in loaded.receipt.metric_publication_v2.metrics
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r5"
        ).fetchone()[0] == 0


def test_projection_identity_rows_are_mutually_exclusive_before_and_after_seal(
    tmp_path,
) -> None:
    """No insertion order can mix any frozen r1-r4 child with current r5."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    base_receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    source = SessionModelEnsembleRunRecord(
        run_id="b" * 64,
        session_id=session_id,
        request_fingerprint="c" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=_preset_profile_binding(session_id),
        receipt=base_receipt.model_copy(
            update={"metric_publication_v2": publication}
        ),
    )
    sidecar_free_receipt = base_receipt.model_copy(
        update={
            "metric_projection_version": None,
            "metric_projection_completed_at": None,
            "typed_metrics": (),
            "metric_publication_v2": None,
            "predictive_projection": None,
        }
    )
    #: One bare run per identity, used to prove that even a single *unsealed*
    #: child of one identity blocks the first child of another.
    IDENTITIES = (
        ("metric-contract-v2-projection-1", "session_model_ensemble_metric_states_v2"),
        (
            "metric-contract-v2-projection-2",
            "session_model_ensemble_metric_states_v2_r2",
        ),
        (
            "metric-contract-v2-projection-3",
            "session_model_ensemble_metric_states_v2_r3",
        ),
        (
            "metric-contract-v2-projection-4",
            "session_model_ensemble_metric_states_v2_r4",
        ),
    )
    bare_run_ids = {
        version: character * 64
        for (version, _table), character in zip(IDENTITIES, "def0", strict=True)
    }
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, source)
    for index, (version, _table) in enumerate(IDENTITIES):
        repository.save_completed(
            source.model_copy(
                update={
                    "run_id": bare_run_ids[version],
                    "request_fingerprint": str(index + 2) * 64,
                    "metric_profile_binding": None,
                    "receipt": sidecar_free_receipt,
                }
            )
        )

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")

        # A sealed r5 publication rejects a child of every frozen identity.
        for version, table in IDENTITIES:
            with pytest.raises(sqlite3.IntegrityError, match="identity conflict"):
                _copy_one_current_state(
                    connection,
                    source_run_id=source.run_id,
                    target_run_id=source.run_id,
                    target_table=table,
                    projection_version=version,
                )

        # ...and a legacy *seal* just as much as a legacy state row.
        for seals_table, version in (
            (
                "session_model_ensemble_metric_publication_v2_seals",
                "metric-contract-v2-projection-1",
            ),
            (
                "session_model_ensemble_metric_publication_v2_seals_r2",
                "metric-contract-v2-projection-2",
            ),
            (
                "session_model_ensemble_metric_publication_v2_seals_r3",
                "metric-contract-v2-projection-3",
            ),
            (
                "session_model_ensemble_metric_publication_v2_seals_r4",
                "metric-contract-v2-projection-4",
            ),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="identity conflict"):
                _copy_seal_with_identity(
                    connection,
                    run_id=source.run_id,
                    target_table=seals_table,
                    projection_version=version,
                )

        # Every ordered pair of identities is rejected from both sides, and an
        # unsealed child is enough to establish the identity of a run.
        for holder_version, holder_table in IDENTITIES:
            run_id = bare_run_ids[holder_version]
            _copy_one_current_state(
                connection,
                source_run_id=source.run_id,
                target_run_id=run_id,
                target_table=holder_table,
                projection_version=holder_version,
            )
            for other_version, other_table in IDENTITIES:
                if other_version == holder_version:
                    continue
                with pytest.raises(
                    sqlite3.IntegrityError, match="identity conflict|sealed"
                ):
                    _copy_one_current_state(
                        connection,
                        source_run_id=source.run_id,
                        target_run_id=run_id,
                        target_table=other_table,
                        projection_version=other_version,
                    )

        for version, table in IDENTITIES:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id=?",  # noqa: S608
                (bare_run_ids[version],),
            ).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    # Unsealed child rows are never rehydrated as a canonical publication.
    # This is the read-side half of the no-torn-head contract.
    for version, _table in IDENTITIES:
        loaded = repository.get(bare_run_ids[version])
        assert loaded is not None
        assert loaded.receipt.metric_publication_v2 is None


def test_a_partial_r4_child_set_cannot_be_sealed(tmp_path) -> None:
    """A seal requires exactly twenty rows of its own identity: no torn head."""

    database, session_id = _database_and_session(tmp_path)
    context = _context(session_id)
    receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    ).run(
        build_ensemble_chunks(context),
        coaching_ensemble_metric_specs(),
    )
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    source = SessionModelEnsembleRunRecord(
        run_id="b" * 64,
        session_id=session_id,
        request_fingerprint="c" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        metric_profile_binding=_preset_profile_binding(session_id),
        receipt=receipt.model_copy(update={"metric_publication_v2": publication}),
    )
    partial = source.model_copy(
        update={
            "run_id": "d" * 64,
            "request_fingerprint": "e" * 64,
            "metric_profile_binding": None,
            "receipt": receipt.model_copy(
                update={
                    "metric_projection_version": None,
                    "metric_projection_completed_at": None,
                    "typed_metrics": (),
                    "metric_publication_v2": None,
                    "predictive_projection": None,
                }
            ),
        }
    )
    repository = database.model_ensemble_repository()
    _save_historical_r5_fixture(database, source)
    repository.save_completed(partial)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        _copy_one_current_state(
            connection,
            source_run_id=source.run_id,
            target_run_id=partial.run_id,
            target_table="session_model_ensemble_metric_states_v2_r4",
            projection_version="metric-contract-v2-projection-4",
        )
        with pytest.raises(sqlite3.IntegrityError, match="incomplete"):
            _copy_seal_with_identity(
                connection,
                run_id=source.run_id,
                target_table=(
                    "session_model_ensemble_metric_publication_v2_seals_r4"
                ),
                projection_version="metric-contract-v2-projection-4",
                target_run_id=partial.run_id,
            )

    assert repository.get(partial.run_id).receipt.metric_publication_v2 is None

def test_optional_deep_timeout_publishes_partial_head_and_clears_watch_failure(
    tmp_path,
) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_repository()
    context = _context(session_id)
    chunks = build_ensemble_chunks(context)
    metrics = coaching_ensemble_metric_specs()
    baseline_receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        deep_enabled=False,
        clock=lambda: NOW,
    ).run(chunks, metrics)
    baseline = SessionModelEnsembleRunRecord(
        run_id="b" * 64,
        session_id=session_id,
        request_fingerprint="c" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=baseline_receipt,
    )
    repository.save_completed(baseline)

    timeout_receipt = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _uncertain_result(payload),
        deep_executor=lambda spec, stage, payload, device, quantization: {
            "status": "unavailable",
            "error_code": PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE,
        },
        device="cuda",
        clock=lambda: NOW + timedelta(seconds=2),
    ).run(chunks, metrics)
    timed_out = SessionModelEnsembleRunRecord(
        run_id="d" * 64,
        session_id=session_id,
        request_fingerprint="e" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=timeout_receipt,
    )
    repository.save_completed(timed_out)

    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0][
        "project_id"
    ]
    watches = database.model_ensemble_watch_repository()
    watch_id = "9" * 64
    owner = "8" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
        now=NOW,
    )
    claimed = watches.claim_due(
        owner=owner,
        now=NOW,
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(seconds=2),
        outcome=SessionModelEnsembleOutcome(run=baseline, applied=True),
    )
    assert watches.canonical_head(watch_id).head_run_id == baseline.run_id

    claimed = watches.claim_due(
        owner=owner,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    in_flight = watches.canonical_head(watch_id)
    assert in_flight.head_run_id == baseline.run_id
    assert in_flight.latest_attempt is not None
    assert in_flight.latest_attempt.state is ModelEnsembleAttemptState.RUNNING
    assert in_flight.latest_attempt.prior_head_run_id == baseline.run_id

    watch = watches.complete(
        lease,
        now=NOW + timedelta(seconds=3),
        next_check_at=NOW + timedelta(seconds=63),
        outcome=SessionModelEnsembleOutcome(run=timed_out, applied=True),
    )
    assert watch.state is ModelEnsembleWatchState.IDLE
    assert watch.failure_streak == 0
    head = watches.canonical_head(watch_id)
    assert head.head_run_id == timed_out.run_id
    assert head.latest_attempt is not None
    assert head.latest_attempt.state is ModelEnsembleAttemptState.PARTIAL
    assert head.latest_attempt.published_run_id == timed_out.run_id
    assert head.latest_attempt.stage_count == 4
    assert head.latest_attempt.warning_count == 1
    assert len(head.stages) == 4
    assert head.stages[-1].state is ModelEnsembleStageState.UNAVAILABLE
    assert head.stages[-1].error_code == PROBABILISTIC_DEEP_TIMEOUT_ERROR_CODE
    assert tuple(
        point.run_id
        for point in watches.list_publications(
            watch_id,
            before_generation=None,
            limit=12,
        ).points
    ) == (timed_out.run_id, baseline.run_id)


def test_v39_preserves_v2_writes_v3_and_breaks_trajectory_comparability(
    tmp_path,
) -> None:
    assert SCHEMA_VERSION == 61
    assert LIVE_PROBABILISTIC_PLAN_VERSION == "small-factor-router-v5"
    assert PROBABILISTIC_MODEL_SET_VERSION == "local-factor-router-v3"

    database, session_id, project_id = _database_and_session_at_v38(tmp_path)
    runner = LocalProbabilisticMetricRunner(
        executor=lambda spec, stage, payload, device: _completed_result(payload),
        clock=lambda: NOW,
    )
    live_receipt = runner.run(
        build_ensemble_chunks(_context(session_id)),
        coaching_ensemble_metric_specs(),
    )
    live_projection = live_receipt.predictive_projection
    assert live_projection is not None
    assert live_projection.model_set_version == PROBABILISTIC_MODEL_SET_VERSION

    historical_metrics = tuple(
        SessionPredictiveMetricReceipt.model_validate(
            {
                **item.model_dump(),
                "model_set_version": PROBABILISTIC_MODEL_SET_VERSION_V2,
            }
        )
        for item in live_projection.metrics
    )
    historical_projection = SessionPredictiveMetricProjection.model_validate(
        {
            **live_projection.model_dump(exclude={"metrics"}),
            "model_set_version": PROBABILISTIC_MODEL_SET_VERSION_V2,
            "metrics": historical_metrics,
        }
    )
    historical_receipt = live_receipt.model_copy(
        update={"predictive_projection": historical_projection}
    )
    historical_record = SessionModelEnsembleRunRecord(
        run_id="b" * 64,
        session_id=session_id,
        request_fingerprint="c" * 64,
        input_fingerprint="a" * 64,
        provider=Provider.CODEX,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        redactor_version="synthetic-redactor-v1",
        receipt=historical_receipt,
    )
    legacy_runs = SqliteSessionModelEnsembleRepository(
        database._connection,  # noqa: SLF001 - deliberate pre-upgrade fixture
        lambda: None,
    )
    legacy_runs.save_completed(historical_record)

    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 38
        assert connection.execute(
            """SELECT DISTINCT model_set_version
               FROM session_model_ensemble_predictive_metrics"""
        ).fetchall() == [(PROBABILISTIC_MODEL_SET_VERSION_V2,)]
        assert connection.execute(
            """SELECT projection_fingerprint
               FROM session_model_ensemble_predictive_metric_seals
               WHERE run_id=?""",
            (historical_record.run_id,),
        ).fetchone()[0] == _predictive_projection_fingerprint(
            historical_projection
        )

    database.initialize()
    runs = database.model_ensemble_repository()
    loaded_historical = runs.get(historical_record.run_id)
    assert loaded_historical is not None
    assert loaded_historical.receipt.metric_publication_v2 is None
    assert loaded_historical.receipt.predictive_projection is not None
    assert (
        loaded_historical.receipt.predictive_projection.model_set_version
        == PROBABILISTIC_MODEL_SET_VERSION_V2
    )
    assert all(
        item.model_set_version == PROBABILISTIC_MODEL_SET_VERSION_V2
        for item in loaded_historical.receipt.predictive_projection.metrics
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_metric_states_v2_r2"
        ).fetchone()[0] == 0
        assert connection.execute(
            """SELECT COUNT(*)
               FROM session_model_ensemble_metric_publication_v2_seals_r2"""
        ).fetchone()[0] == 0

    live_record = historical_record.model_copy(
        update={
            "run_id": "d" * 64,
            "request_fingerprint": "e" * 64,
            "receipt": live_receipt,
        }
    )
    runs.save_completed(live_record)

    # Bypass Pydantic deliberately to prove the database seal rejects a graph
    # whose seal claims v3 while its twenty metric rows still claim v2.
    mismatched_projection = historical_projection.model_copy(
        update={"model_set_version": PROBABILISTIC_MODEL_SET_VERSION}
    )
    mismatched_record = historical_record.model_copy(
        update={
            "run_id": "f" * 64,
            "request_fingerprint": "0" * 64,
            "receipt": live_receipt.model_copy(
                update={"predictive_projection": mismatched_projection}
            ),
        }
    )
    with pytest.raises(DatabaseError, match="local database operation failed"):
        runs.save_completed(mismatched_record)
    assert runs.get(mismatched_record.run_id) is None

    expected_triggers = {
        "session_model_ensemble_predictive_seal_complete",
        "session_model_ensemble_predictive_metrics_sealed_insert",
        "session_model_ensemble_predictive_factors_sealed_insert",
        "session_model_ensemble_predictive_density_sealed_insert",
        "session_model_ensemble_predictive_stages_sealed_insert",
        "session_model_ensemble_predictive_metrics_no_update",
        "session_model_ensemble_predictive_factors_no_update",
        "session_model_ensemble_predictive_density_no_update",
        "session_model_ensemble_predictive_stages_no_update",
        "session_model_ensemble_predictive_seals_no_update",
        "session_model_ensemble_predictive_metrics_privacy_delete_only",
        "session_model_ensemble_predictive_factors_privacy_delete_only",
        "session_model_ensemble_predictive_density_privacy_delete_only",
        "session_model_ensemble_predictive_stages_privacy_delete_only",
        "session_model_ensemble_predictive_seals_privacy_delete_only",
    }
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=39"
        ).fetchone()[0] == hashlib.sha256(
            migrations.MIGRATION_39.encode("utf-8")
        ).hexdigest()
        model_sets = connection.execute(
            """SELECT model_set_version,COUNT(*)
               FROM session_model_ensemble_predictive_metrics
               GROUP BY model_set_version ORDER BY model_set_version"""
        ).fetchall()
        assert model_sets == [
            (PROBABILISTIC_MODEL_SET_VERSION_V2, 20),
            (PROBABILISTIC_MODEL_SET_VERSION, 20),
        ]
        trigger_rows = connection.execute(
            """SELECT name,sql FROM sqlite_master
               WHERE type='trigger'
                 AND name LIKE 'session_model_ensemble_predictive_%'"""
        ).fetchall()
        assert {row[0] for row in trigger_rows} == expected_triggers
        assert all("_v39" not in row[1] for row in trigger_rows)
        assert connection.execute(
            """SELECT name FROM sqlite_master
               WHERE sql IS NOT NULL AND sql LIKE '%_v39%'"""
        ).fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                """UPDATE session_model_ensemble_predictive_model_stages
                   SET status=status WHERE run_id=?""",
                (live_record.run_id,),
            )

    watches = database.model_ensemble_watch_repository()
    watch_id = "9" * 64
    watches.enable(
        watch_id=watch_id,
        provider=Provider.CODEX,
        project_id=project_id,
        session_id=session_id,
        max_messages=100,
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
        now=NOW + timedelta(seconds=1),
        next_check_at=NOW + timedelta(seconds=2),
        outcome=SessionModelEnsembleOutcome(run=historical_record, applied=True),
    )
    claimed = watches.claim_due(
        owner="8" * 64,
        now=NOW + timedelta(seconds=2),
        lease_duration=timedelta(minutes=30),
    )
    assert claimed is not None
    _, lease = claimed
    watches.complete(
        lease,
        now=NOW + timedelta(seconds=3),
        next_check_at=NOW + timedelta(seconds=60),
        outcome=SessionModelEnsembleOutcome(run=live_record, applied=True),
    )

    trajectory = watches.list_publications(
        watch_id,
        before_generation=None,
        limit=12,
    )
    assert tuple(point.run_id for point in trajectory.points) == (
        live_record.run_id,
        historical_record.run_id,
    )
    assert trajectory.points[0].comparable_to_head is True
    assert trajectory.points[1].comparable_to_head is False
    assert {
        item.model_set_version for item in trajectory.points[0].predictive_metrics
    } == {PROBABILISTIC_MODEL_SET_VERSION}
    assert {
        item.model_set_version for item in trajectory.points[1].predictive_metrics
    } == {PROBABILISTIC_MODEL_SET_VERSION_V2}
