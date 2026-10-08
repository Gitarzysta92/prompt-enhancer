from __future__ import annotations

from collections.abc import Iterator

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


class EmptyConsentedAdapter(ProviderAdapter):
    provider = Provider.CODEX

    def __init__(self) -> None:
        self.probe_calls = 0
        self.list_calls = 0

    def probe(self) -> AdapterProbe:
        self.probe_calls += 1
        return AdapterProbe(
            provider=self.provider,
            provider_version="example-1",
            adapter_version="0.1.0",
            source_schema_version="example-1",
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        self.list_calls += 1
        return SourceSessionPage(sessions=(), next_cursor=None)

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        raise AssertionError("an empty adapter has no sessions to read")

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY


def test_explicit_metadata_consent_allows_read_only_adapter_access(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    database.grant_consent(Provider.CODEX, DataTier.METADATA)
    adapter = EmptyConsentedAdapter()

    report = IngestionService(
        database, Pseudonymizer(bytes(range(32)))
    ).ingest(adapter)

    assert adapter.probe_calls == 1
    assert adapter.list_calls == 1
    assert report.sessions_seen == 0
    assert report.events_seen == 0
