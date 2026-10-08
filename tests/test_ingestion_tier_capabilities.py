from __future__ import annotations

from collections.abc import Iterator

import pytest

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
)
from prompt_enhancer.ingestion import (
    AdapterUnavailableError,
    IngestionSelection,
    IngestionService,
)
from prompt_enhancer.privacy import Pseudonymizer


class SyntheticCapabilityMismatchAdapter(ProviderAdapter):
    provider = Provider.CODEX

    def __init__(self) -> None:
        self.probe_calls = 0
        self.list_calls = 0
        self.closed = False

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    @property
    def requires_explicit_selection(self) -> bool:
        return True

    def probe(self) -> AdapterProbe:
        self.probe_calls += 1
        return AdapterProbe(
            provider=self.provider,
            provider_version="example-1",
            adapter_version="example-adapter-1",
            source_schema_version="example-schema-1",
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        self.list_calls += 1
        raise AssertionError("capability mismatch must stop before source listing")

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        raise AssertionError("capability mismatch must stop before source reading")

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY

    def close(self) -> None:
        self.closed = True


def test_redacted_ingestion_requires_content_capability_and_always_closes(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    adapter = SyntheticCapabilityMismatchAdapter()
    selection = IngestionSelection(project_ids=frozenset({"1" * 64}))

    with pytest.raises(AdapterUnavailableError):
        IngestionService(
            database, Pseudonymizer(bytes(range(32)))
        ).ingest(adapter, selection=selection)

    assert adapter.probe_calls == 1
    assert adapter.list_calls == 0
    assert adapter.closed is True
