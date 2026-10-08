from __future__ import annotations

from collections.abc import Iterator

import pytest

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
)
from prompt_enhancer.ingestion import IngestionError, IngestionSelection, IngestionService
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    ADAPTER_VERSION,
    SOURCE_SCHEMA_VERSION,
    RawThread,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import (
    CodexThreadMapper,
)
from prompt_enhancer.privacy import Pseudonymizer


PROVIDER_VERSION = "example-1"


def _thread(revision: int, *, first_input_tokens: int = 10) -> RawThread:
    first_turn: dict[str, object] = {
        "id": "example-turn-stable",
        "status": "active" if revision == 1 else "completed",
        "startedAt": 1_768_473_700,
        "items": [],
    }
    if revision >= 2:
        first_turn.update(
            {
                "completedAt": 1_768_474_100,
                "durationMs": 400_000,
                "items": [
                    {
                        "id": "example-item-stable",
                        "type": "commandExecution",
                        "status": "completed",
                        "durationMs": 250,
                    }
                ],
                "usage": {"inputTokens": first_input_tokens, "outputTokens": 5},
            }
        )
    turns: list[dict[str, object]] = [first_turn]
    if revision >= 3:
        turns.append(
            {
                "id": "example-turn-appended",
                "status": "completed",
                "startedAt": 1_768_474_200,
                "completedAt": 1_768_474_260,
                "durationMs": 60_000,
                "items": [],
            }
        )
    return RawThread.model_validate(
        {
            "id": "example-session-reimport",
            "cwd": "/example/reimport-project",
            "createdAt": 1_768_473_600,
            "updatedAt": 1_768_474_000 + revision,
            "status": "idle",
            "usage": {"inputTokens": revision * 1_000},
            "turns": turns,
        }
    )


class RevisionAdapter(ProviderAdapter):
    provider = Provider.CODEX

    def __init__(self, thread: RawThread) -> None:
        self._thread = thread
        self._mapper = CodexThreadMapper(provider_version=PROVIDER_VERSION)

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    @property
    def requires_explicit_selection(self) -> bool:
        return True

    def probe(self) -> AdapterProbe:
        return AdapterProbe(
            provider=self.provider,
            provider_version=PROVIDER_VERSION,
            adapter_version=ADAPTER_VERSION,
            source_schema_version=SOURCE_SCHEMA_VERSION,
            supports_metadata=True,
            supports_content=True,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        assert cursor is None
        return SourceSessionPage(
            sessions=(self._mapper.session(self._thread, events_complete=False),)
        )

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        snapshot = self._mapper.snapshot(self._thread)
        assert snapshot.session == session
        return snapshot

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        yield from self.read_session(session).events

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY


def _safe_session_id(pseudonymizer: Pseudonymizer, source: SourceSession) -> str:
    installation_id = pseudonymizer.pseudonymize(
        "codex:installation", source.source_installation_id.get_secret_value()
    )
    return pseudonymizer.pseudonymize(
        f"codex:session:{installation_id}",
        source.source_session_id.get_secret_value(),
    )


def test_active_turn_can_finalize_and_new_turn_can_append_idempotently(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    service = IngestionService(database, pseudonymizer)
    initial_source = CodexThreadMapper(provider_version=PROVIDER_VERSION).session(
        _thread(1), events_complete=False
    )
    safe_session_id = _safe_session_id(pseudonymizer, initial_source)
    selection = IngestionSelection(session_ids=frozenset({safe_session_id}))

    active = service.ingest(RevisionAdapter(_thread(1)), selection=selection)
    finalized = service.ingest(RevisionAdapter(_thread(2)), selection=selection)
    appended = service.ingest(RevisionAdapter(_thread(3)), selection=selection)
    repeated = service.ingest(RevisionAdapter(_thread(3)), selection=selection)

    assert active.events_inserted == 1
    assert finalized.events_inserted == 4
    assert appended.events_inserted == 2
    assert repeated.events_inserted == 0
    immutable_value_canary = "SYNTHETIC-IMMUTABLE-USAGE-CANARY"
    with pytest.raises(IngestionError) as error:
        service.ingest(
            RevisionAdapter(_thread(3, first_input_tokens=11)),
            selection=selection,
        )
    assert str(error.value) == "provider metadata ingestion failed"
    assert immutable_value_canary not in str(error.value)

    assert repeated.events_updated == 0

    events = database.get_session_events(safe_session_id)
    assert len(events) == 7
    assert sum(event.kind is EventKind.TURN_END for event in events) == 2
    assert sum(event.kind is EventKind.USAGE for event in events) == 1
    assert tuple(event.sequence for event in events) == (
        0,
        1,
        2,
        9_999,
        10_000,
        10_001,
        20_000,
    )

    metrics = {
        item["key"]: item for item in database.get_session_metrics(safe_session_id)
    }
    input_tokens = metrics["usage.input_tokens"]
    assert input_tokens["numeric_value"] == 10
    assert input_tokens["observed_count"] == 1
    assert input_tokens["eligible_count"] == 2
    assert input_tokens["coverage"] == 0.5
    assert input_tokens["confidence"] is None
    turn_duration = metrics["efficiency.observed_finalized_turn_duration_ms"]
    assert turn_duration["numeric_value"] == 460_000
    assert turn_duration["coverage"] == 1
    assert turn_duration["confidence"] is None

    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )
    for canary in (
        b"example-session-reimport",
        b"example-turn-stable",
        b"example-item-stable",
        b"/example/reimport-project",
    ):
        assert canary not in sqlite_payload
