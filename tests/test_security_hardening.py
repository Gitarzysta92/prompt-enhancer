from __future__ import annotations

from datetime import UTC, datetime
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.cli import main
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database, DatabaseInvariantError
from prompt_enhancer.domain import (
    EventKind,
    MetricObservation,
    MetricSource,
    SessionState,
    UsageRecord,
    UsageCounterKind,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.metrics import compute_session_metrics
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TOKEN = "example_local_token_do_not_use_1234567890"


class EmptyReadStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self) -> list[dict[str, object]]:
        return []

    def list_sessions(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, object]]:
        return []

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        return []


def _ingested_database(tmp_path) -> Database:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database


def test_newer_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(DatabaseInvariantError, match="newer"):
        Database(path).initialize()


def test_metric_definition_cannot_change_without_version_bump(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE metric_definitions SET definition_checksum = ? WHERE key = ?",
            ("0" * 64, "workflow.event_count"),
        )

    with pytest.raises(DatabaseInvariantError, match="definition"):
        Database(path).initialize()


def test_partial_snapshot_cannot_erase_known_session_or_event_values(tmp_path) -> None:
    database = _ingested_database(tmp_path)
    completed_id = next(
        item["session_id"]
        for item in database.list_sessions()
        if item["terminal_state"] == "completed"
    )
    session = database.get_session(completed_id)
    assert session is not None
    events = database.get_session_events(completed_id)
    known_event = next(event for event in events if event.duration_ms is not None)
    known_usage = next(event for event in events if event.usage is not None)

    degraded_session = session.model_copy(
        update={
            "ended_at": None,
            "terminal_state": SessionState.UNKNOWN,
            "events_complete": False,
        }
    )
    degraded_event = known_event.model_copy(
        update={"duration_ms": None, "success": None, "tool_category": None, "usage": None}
    )
    degraded_usage = known_usage.model_copy(update={"usage": None})
    database.persist_session(
        degraded_session, (degraded_event, degraded_usage)
    )

    stored_session = database.get_session(completed_id)
    stored_event = next(
        event
        for event in database.get_session_events(completed_id)
        if event.event_id == known_event.event_id
    )
    stored_usage = next(
        event
        for event in database.get_session_events(completed_id)
        if event.event_id == known_usage.event_id
    )
    assert stored_session is not None
    assert stored_session.ended_at == session.ended_at
    assert stored_session.terminal_state is SessionState.COMPLETED
    assert stored_session.events_complete is True
    assert stored_event.duration_ms == known_event.duration_ms
    assert stored_event.success == known_event.success
    assert stored_event.tool_category == known_event.tool_category
    assert stored_usage.usage == known_usage.usage


def test_estimated_usage_and_incomplete_rate_keep_provenance_uncertainty() -> None:
    adapter = SyntheticAdapter()
    source = adapter.list_sessions(limit=1).sessions[0]

    from prompt_enhancer.domain import Provider, SafeEvent, SafeSession, ToolCategory

    session = SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="a" * 64,
        project_id="b" * 64,
        session_id="c" * 64,
        provider_version=source.provider_version,
        adapter_version=source.adapter_version,
        source_schema_version=source.source_schema_version,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )
    events = (
        SafeEvent(
            session_id=session.session_id,
            event_id="d" * 64,
            kind=EventKind.TOOL_END,
            sequence=0,
            occurred_at=session.started_at,
            success=True,
            tool_category=ToolCategory.TEST,
        ),
        SafeEvent(
            session_id=session.session_id,
            event_id="e" * 64,
            kind=EventKind.USAGE,
            sequence=1,
            occurred_at=session.started_at,
            usage=UsageRecord(
                total_tokens=10,
                provider_reported=False,
                counter_kind=UsageCounterKind.DELTA,
            ),
        ),
        SafeEvent(
            session_id=session.session_id,
            event_id="f" * 64,
            kind=EventKind.USAGE,
            sequence=2,
            occurred_at=session.started_at,
            usage=None,
        ),
    )
    metrics = {item.key: item for item in compute_session_metrics(session, events)}

    token_metric = metrics["usage.total_tokens"]
    rate_metric = metrics["reliability.tool_success_rate"]
    assert token_metric.numeric_value == 10
    assert token_metric.source is MetricSource.ESTIMATED
    assert (token_metric.observed_count, token_metric.eligible_count) == (1, 2)
    assert rate_metric.numeric_value == 1
    assert rate_metric.confidence is None


def test_api_security_headers_and_malformed_host(tmp_path) -> None:
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=EmptyReadStore(),
        api_token=EXAMPLE_TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        healthy = client.get("/health")
        malformed = client.get(
            "/v1/capabilities",
            headers={
                API_TOKEN_HEADER: EXAMPLE_TOKEN,
                "Host": "127.0.0.1@attacker.invalid",
            },
        )

    assert healthy.headers["cache-control"] == "no-store"
    assert healthy.headers["x-content-type-options"] == "nosniff"
    assert malformed.status_code == 400


def test_cli_error_does_not_echo_private_exception_text(tmp_path, monkeypatch, capsys) -> None:
    private_text = "C:" + "\\Users\\" + "private-user\\state"

    def fail_safely(settings) -> None:
        raise OSError(private_text)

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr("prompt_enhancer.cli._initialize", fail_safely)
    assert main(["init"]) == 1
    captured = capsys.readouterr()
    assert private_text not in captured.err
    assert str(tmp_path) not in captured.err


def test_metric_observations_reject_content_and_non_finite_values() -> None:
    common = {
        "key": "workflow.example",
        "version": 1,
        "unit": "state",
        "source": MetricSource.DETERMINISTIC,
        "observed_count": 1,
        "eligible_count": 1,
        "coverage": 1.0,
    }
    with pytest.raises(ValidationError):
        MetricObservation(**common, text_value="raw conversation text")
    with pytest.raises(ValidationError):
        MetricObservation(**common, numeric_value=float("nan"))
