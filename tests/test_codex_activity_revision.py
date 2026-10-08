from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import re
import sqlite3

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.automation import AutomationGrantScope
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    ADAPTER_VERSION,
    SOURCE_SCHEMA_VERSION,
    RawThread,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.mapping import (
    CodexThreadMapper,
)
from prompt_enhancer.privacy import Pseudonymizer


PROVIDER_VERSION = "example-provider-v1"
STARTED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FIRST_ACTIVITY_AT = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
SECOND_ACTIVITY_AT = datetime(2026, 2, 3, 4, 7, 8, tzinfo=UTC)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _thread(activity_at: datetime) -> RawThread:
    return RawThread.model_validate(
        {
            "id": "example-activity-session",
            "cwd": "/example/activity-project",
            "createdAt": STARTED_AT,
            "updatedAt": activity_at,
            "status": "idle",
            "turns": [],
        }
    )


class _MetadataActivityAdapter(ProviderAdapter):
    provider = Provider.CODEX

    def __init__(self, activity_at: datetime) -> None:
        self._source = CodexThreadMapper(provider_version=PROVIDER_VERSION).session(
            _thread(activity_at), events_complete=False
        )

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    def probe(self) -> AdapterProbe:
        return AdapterProbe(
            provider=self.provider,
            provider_version=PROVIDER_VERSION,
            adapter_version=ADAPTER_VERSION,
            source_schema_version=SOURCE_SCHEMA_VERSION,
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        assert cursor is None
        return SourceSessionPage(sessions=(self._source,))

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        assert session == self._source
        return SourceSessionSnapshot(session=session, events=())

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        del session
        yield from ()

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY


def _candidate_fingerprint(database: Database) -> str:
    indexed = database.list_sessions(provider=Provider.CODEX)
    assert len(indexed) == 1
    scope = AutomationGrantScope(
        provider=Provider.CODEX,
        project_id=str(indexed[0]["project_id"]),
        metric_keys=(COACHING_METRIC_DEFINITIONS[0].key,),
    )
    candidates = database.automation_candidate_source(
        estimator_plan_version="synthetic-plan-v1",
        redactor_version="synthetic-redactor-v1",
    ).newest_changed(scope, limit=scope.newest_session_limit)
    assert len(candidates) == 1
    return candidates[0].input_fingerprint


def test_codex_updated_at_becomes_only_an_hmac_activity_revision(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    database = Database(path)
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    service = IngestionService(database, Pseudonymizer(bytes(range(32))))

    mapped = CodexThreadMapper(provider_version=PROVIDER_VERSION).session(
        _thread(FIRST_ACTIVITY_AT), events_complete=False
    )
    assert mapped.source_activity_at == FIRST_ACTIVITY_AT

    first = service.ingest(_MetadataActivityAdapter(FIRST_ACTIVITY_AT))
    first_fingerprint = _candidate_fingerprint(database)
    stored = database.get_session(str(database.list_sessions()[0]["session_id"]))
    assert stored is not None
    first_revision = stored.provider_activity_revision
    assert first_revision is not None and _DIGEST.fullmatch(first_revision)

    second = service.ingest(_MetadataActivityAdapter(SECOND_ACTIVITY_AT))
    second_fingerprint = _candidate_fingerprint(database)
    stored = database.get_session(stored.session_id)
    assert stored is not None
    second_revision = stored.provider_activity_revision

    repeated = service.ingest(_MetadataActivityAdapter(SECOND_ACTIVITY_AT))
    repeated_fingerprint = _candidate_fingerprint(database)

    assert first.sessions_inserted == 1
    assert second.sessions_updated == 1
    assert repeated.sessions_updated == 0
    assert second_revision is not None and _DIGEST.fullmatch(second_revision)
    assert second_revision != first_revision
    assert second_fingerprint != first_fingerprint
    assert repeated_fingerprint == second_fingerprint

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT provider_activity_revision FROM sessions"
        ).fetchone()
        assert row == (second_revision,)

    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )
    assert FIRST_ACTIVITY_AT.isoformat().encode("ascii") not in sqlite_payload
    assert SECOND_ACTIVITY_AT.isoformat().encode("ascii") not in sqlite_payload


def test_missing_provider_activity_preserves_backward_compatible_null(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    database = Database(path)
    database.initialize()
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        assert "provider_activity_revision" in columns
        assert connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE provider_activity_revision IS NOT NULL"
        ).fetchone() == (0,)
