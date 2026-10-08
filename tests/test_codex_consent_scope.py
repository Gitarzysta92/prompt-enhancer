from __future__ import annotations

from collections.abc import Callable

import pytest

from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CodexAppServerAdapter,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.ingestion import ConsentRequiredError, IngestionService
from prompt_enhancer.privacy import Pseudonymizer


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[str] = []
        self.closed = False

    def _request(self, method: str, _params: dict[str, object]) -> object:
        self.requests.append(method)
        return self.responses.pop(0)

    def _notify(self, method: str, _params: dict[str, object] | None = None) -> None:
        self.requests.append(method)

    def close(self) -> None:
        self.closed = True


def _service(database: Database) -> IngestionService:
    return IngestionService(database, Pseudonymizer(bytes(range(32))))


def _factory(
    transport: RecordingTransport,
    factory_calls: list[str],
) -> Callable[[], CodexAppServerClient]:
    def create() -> CodexAppServerClient:
        factory_calls.append("created")
        return CodexAppServerClient(transport)

    return create


def test_index_requires_content_bearing_local_history_consent(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    database.grant_consent(Provider.CODEX, DataTier.METADATA)
    transport = RecordingTransport([])
    factory_calls: list[str] = []
    adapter = CodexAppServerAdapter(
        client_factory=_factory(transport, factory_calls)
    )

    with pytest.raises(ConsentRequiredError):
        _service(database).ingest(adapter)

    assert factory_calls == []
    assert transport.requests == []


def test_local_history_consent_allows_index_without_a_detail_selector(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    transport = RecordingTransport(
        [{"version": "example-1"}, {"data": [], "nextCursor": None}]
    )
    adapter = CodexAppServerAdapter(
        client_factory=lambda: CodexAppServerClient(transport)
    )

    report = _service(database).ingest(adapter)

    assert report.sessions_seen == 0
    assert transport.requests == ["initialize", "initialized", "thread/list"]
    assert transport.closed is True


def test_operational_history_still_requires_selection_before_client_creation(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    transport = RecordingTransport([])
    factory_calls: list[str] = []
    adapter = CodexAppServerAdapter(
        mode=CodexReadMode.OPERATIONAL_HISTORY,
        client_factory=_factory(transport, factory_calls),
    )

    with pytest.raises(ConsentRequiredError):
        _service(database).ingest(adapter)

    assert factory_calls == []
    assert transport.requests == []
