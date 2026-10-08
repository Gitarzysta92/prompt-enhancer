from __future__ import annotations

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.deterministic import DEFAULT_METRIC_PACK
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


def _ingested_database(tmp_path) -> Database:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database


def test_database_preserves_unknown_metric_values_and_coverage(tmp_path) -> None:
    database = _ingested_database(tmp_path)
    interrupted = next(
        record
        for record in database.list_sessions()
        if record["terminal_state"] == "interrupted"
    )
    metrics = {
        record["key"]: record
        for record in database.get_session_metrics(interrupted["session_id"])
    }

    duration = metrics["efficiency.observed_tool_duration_ms"]
    tokens = metrics["usage.total_tokens"]

    assert duration["numeric_value"] is None
    assert duration["observed_count"] == 0
    assert duration["eligible_count"] == 1
    assert duration["coverage"] == 0
    assert tokens["numeric_value"] is None
    assert tokens["observed_count"] == 0
    assert tokens["coverage"] == 0


def test_consent_grant_is_explicit_and_revocable(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()

    assert database.has_active_consent(Provider.CODEX, DataTier.METADATA) is False
    database.grant_consent(Provider.CODEX, DataTier.METADATA)
    assert database.has_active_consent(Provider.CODEX, DataTier.METADATA) is True
    database.revoke_consent(Provider.CODEX, DataTier.METADATA)
    assert database.has_active_consent(Provider.CODEX, DataTier.METADATA) is False


def test_metric_rows_record_definition_and_analysis_provenance(tmp_path) -> None:
    database = _ingested_database(tmp_path)
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    metrics = database.get_session_metrics(session_id)

    required = {
        "version",
        "source",
        "metric_pack_key",
        "metric_pack_version",
        "metric_engine_version",
        "redactor_version",
        "model_id",
        "model_revision",
        "tokenizer_id",
        "prompt_version",
        "rubric_version",
    }
    assert metrics
    assert all(required <= record.keys() for record in metrics)
    assert all(record["metric_engine_version"] for record in metrics)
    assert all(record["redactor_version"] for record in metrics)
    assert {
        (record["metric_pack_key"], record["metric_pack_version"])
        for record in metrics
    } == {(DEFAULT_METRIC_PACK.key, DEFAULT_METRIC_PACK.version)}
