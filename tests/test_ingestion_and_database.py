from __future__ import annotations

from collections.abc import Iterator
import threading

import pytest

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.ingestion import SessionMetricPlan
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCooperativeStop,
    runtime_request_scope,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider, SourceEvent, SourceSession, SourceSessionPage
from prompt_enhancer.ingestion import ConsentRequiredError, IngestionService
from prompt_enhancer.metrics import compute_session_metrics
from prompt_enhancer.privacy import Pseudonymizer


RAW_SYNTHETIC_IDENTIFIERS = (
    b"example-installation",
    b"example-project-alpha",
    b"example-project-beta",
    b"example-session-completed",
    b"example-session-interrupted",
    b"completed-event-0",
    b"interrupted-event-0",
)


class NeverReadCodexAdapter(ProviderAdapter):
    provider = Provider.CODEX

    def __init__(self) -> None:
        self.access_attempted = False

    def _unexpected_access(self):
        self.access_attempted = True
        raise AssertionError("provider source was accessed before consent")

    def probe(self) -> AdapterProbe:
        return self._unexpected_access()

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        return self._unexpected_access()

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        return self._unexpected_access()
        yield

    def health(self) -> AdapterHealth:
        return self._unexpected_access()


def _service(tmp_path) -> tuple[Database, IngestionService]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    service = IngestionService(database, Pseudonymizer(bytes(range(32))))
    return database, service


def test_non_synthetic_provider_is_rejected_before_any_source_read(tmp_path) -> None:
    _, service = _service(tmp_path)
    adapter = NeverReadCodexAdapter()

    with pytest.raises(ConsentRequiredError):
        service.ingest(adapter)

    assert adapter.access_attempted is False


def test_cancelled_background_ingestion_never_reads_the_adapter(tmp_path) -> None:
    database, service = _service(tmp_path)

    class CloseObservedSynthetic(SyntheticAdapter):
        closed = False

        def close(self) -> None:
            self.closed = True

    adapter = CloseObservedSynthetic()
    cancelled = threading.Event()
    cancelled.set()

    with runtime_request_scope(cancelled), pytest.raises(
        RuntimeCooperativeStop, match="^provider_ingestion_cancelled$"
    ):
        service.ingest(adapter)

    assert database.summary()["sessions"] == 0
    assert adapter.closed is True


def test_synthetic_ingestion_is_idempotent(tmp_path) -> None:
    database, service = _service(tmp_path)

    first = service.ingest(SyntheticAdapter())
    after_first = database.summary()
    second = service.ingest(SyntheticAdapter())
    after_second = database.summary()

    assert first.sessions_seen == 2
    assert first.events_seen == 10
    assert second.sessions_seen == 2
    assert second.events_seen == 10
    assert after_first == after_second
    assert after_second["sessions"] == 2
    assert after_second["events"] == 10


def test_injected_metric_plan_persists_its_own_pack_and_engine_provenance(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    plan = SessionMetricPlan(
        computer=compute_session_metrics,
        pack_key="synthetic.metadata.session",
        pack_version=7,
        metric_engine_version="synthetic-engine-v7",
    )

    IngestionService(
        database,
        Pseudonymizer(bytes(range(32))),
        metric_plan=plan,
    ).ingest(SyntheticAdapter())

    for session in database.list_sessions():
        metrics = database.get_session_metrics(session["session_id"])
        assert metrics
        assert {
            (
                item["metric_pack_key"],
                item["metric_pack_version"],
                item["metric_engine_version"],
            )
            for item in metrics
        } == {(plan.pack_key, plan.pack_version, plan.metric_engine_version)}


def test_raw_source_identifiers_never_cross_sqlite_boundary(tmp_path) -> None:
    _, service = _service(tmp_path)
    service.ingest(SyntheticAdapter())

    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )

    assert sqlite_payload
    for raw_identifier in RAW_SYNTHETIC_IDENTIFIERS:
        assert raw_identifier not in sqlite_payload


def test_public_database_views_contain_only_pseudonymous_ids(tmp_path) -> None:
    database, service = _service(tmp_path)
    service.ingest(SyntheticAdapter())

    sessions = database.list_sessions()

    assert len(sessions) == 2
    assert all(len(record["session_id"]) == 64 for record in sessions)
    assert all(len(record["installation_id"]) == 64 for record in sessions)
    assert all(len(record["project_id"]) == 64 for record in sessions)
    assert all("source_session_id" not in record for record in sessions)
    assert all("source_project_id" not in record for record in sessions)
