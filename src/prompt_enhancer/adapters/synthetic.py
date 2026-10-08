"""Content-free synthetic adapter used for demos and contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterator

from pydantic import SecretStr

from ..domain import (
    EventKind,
    Provider,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    ToolCategory,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from .base import AdapterHealth, AdapterProbe, ProviderAdapter


BASE_TIME = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


class SyntheticAdapter(ProviderAdapter):
    """Two deterministic fictional sessions containing no message text."""

    provider = Provider.SYNTHETIC

    def __init__(self) -> None:
        self._sessions = (
            SourceSession(
                provider=self.provider,
                source_installation_id=SecretStr("example-installation"),
                source_project_id=SecretStr("example-project-alpha"),
                source_session_id=SecretStr("example-session-completed"),
                provider_version="synthetic-1",
                adapter_version="0.1.0",
                source_schema_version="synthetic-1",
                started_at=BASE_TIME,
                ended_at=BASE_TIME + timedelta(minutes=14),
                terminal_state=SessionState.COMPLETED,
                events_complete=True,
            ),
            SourceSession(
                provider=self.provider,
                source_installation_id=SecretStr("example-installation"),
                source_project_id=SecretStr("example-project-alpha"),
                source_session_id=SecretStr("example-session-interrupted"),
                provider_version="synthetic-1",
                adapter_version="0.1.0",
                source_schema_version="synthetic-1",
                started_at=BASE_TIME + timedelta(hours=1),
                ended_at=BASE_TIME + timedelta(hours=1, minutes=3),
                terminal_state=SessionState.INTERRUPTED,
                events_complete=True,
            ),
        )

    def probe(self) -> AdapterProbe:
        return AdapterProbe(
            provider=self.provider,
            provider_version="synthetic-1",
            adapter_version="0.1.0",
            source_schema_version="synthetic-1",
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(self, *, cursor: str | None = None, limit: int = 100) -> SourceSessionPage:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        offset = 0 if cursor is None else int(cursor)
        page = self._sessions[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = str(next_offset) if next_offset < len(self._sessions) else None
        return SourceSessionPage(sessions=page, next_cursor=next_cursor)

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        source_id = session.source_session_id.get_secret_value()
        if source_id == "example-session-completed":
            events = (
                SourceEvent(
                    source_event_id=SecretStr("completed-event-0"),
                    kind=EventKind.SESSION_START,
                    sequence=0,
                    occurred_at=session.started_at,
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-1"),
                    kind=EventKind.PLAN,
                    sequence=1,
                    occurred_at=session.started_at + timedelta(minutes=1),
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-2"),
                    kind=EventKind.TOOL_END,
                    sequence=2,
                    occurred_at=session.started_at + timedelta(minutes=4),
                    duration_ms=2500,
                    success=False,
                    tool_category=ToolCategory.TEST,
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-3"),
                    kind=EventKind.TOOL_END,
                    sequence=3,
                    occurred_at=session.started_at + timedelta(minutes=8),
                    duration_ms=900,
                    success=True,
                    tool_category=ToolCategory.FILE_WRITE,
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-4"),
                    kind=EventKind.VERIFICATION,
                    sequence=4,
                    occurred_at=session.started_at + timedelta(minutes=12),
                    duration_ms=3200,
                    success=True,
                    tool_category=ToolCategory.TEST,
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-5"),
                    kind=EventKind.USAGE,
                    sequence=5,
                    occurred_at=session.started_at + timedelta(minutes=13),
                    usage=UsageRecord(
                        input_tokens=1200,
                        cached_input_tokens=300,
                        output_tokens=450,
                        total_tokens=1650,
                        model_id="example-local-model",
                        provider_reported=True,
                        counter_kind=UsageCounterKind.DELTA,
                        scope=UsageScope.TURN,
                    ),
                ),
                SourceEvent(
                    source_event_id=SecretStr("completed-event-6"),
                    kind=EventKind.SESSION_END,
                    sequence=6,
                    occurred_at=session.ended_at,
                ),
            )
        elif source_id == "example-session-interrupted":
            events = (
                SourceEvent(
                    source_event_id=SecretStr("interrupted-event-0"),
                    kind=EventKind.SESSION_START,
                    sequence=0,
                    occurred_at=session.started_at,
                ),
                SourceEvent(
                    source_event_id=SecretStr("interrupted-event-1"),
                    kind=EventKind.TOOL_END,
                    sequence=1,
                    occurred_at=session.started_at + timedelta(minutes=2),
                    duration_ms=None,
                    success=None,
                    tool_category=ToolCategory.UNKNOWN,
                ),
                SourceEvent(
                    source_event_id=SecretStr("interrupted-event-2"),
                    kind=EventKind.SESSION_END,
                    sequence=2,
                    occurred_at=session.ended_at,
                ),
            )
        else:
            raise KeyError("unknown synthetic session")
        yield from events

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY
