from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prompt_enhancer.domain import (
    EventKind,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    ToolCategory,
    UsageRecord,
)
from prompt_enhancer.metrics import compute_session_metrics


BASE_TIME = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)


def _session(*, events_complete: bool = True) -> SafeSession:
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="a" * 64,
        project_id="b" * 64,
        session_id="c" * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(minutes=1),
        terminal_state=SessionState.INTERRUPTED,
        events_complete=events_complete,
    )


def _by_key(session: SafeSession, events: list[SafeEvent]):
    return {item.key: item for item in compute_session_metrics(session, events)}


def test_missing_duration_success_and_token_values_remain_unknown() -> None:
    events = [
        SafeEvent(
            session_id="c" * 64,
            event_id="d" * 64,
            kind=EventKind.TOOL_END,
            sequence=0,
            occurred_at=BASE_TIME,
            duration_ms=None,
            success=None,
            tool_category=ToolCategory.UNKNOWN,
        ),
        SafeEvent(
            session_id="c" * 64,
            event_id="e" * 64,
            kind=EventKind.USAGE,
            sequence=1,
            occurred_at=BASE_TIME + timedelta(seconds=1),
            usage=UsageRecord(total_tokens=None, provider_reported=True),
        ),
    ]
    metrics = _by_key(_session(), events)

    duration = metrics["efficiency.observed_tool_duration_ms"]
    success = metrics["reliability.tool_success_rate"]
    tokens = metrics["usage.total_tokens"]

    assert duration.numeric_value is None
    assert (duration.observed_count, duration.eligible_count, duration.coverage) == (0, 1, 0)
    assert success.numeric_value is None
    assert (success.observed_count, success.eligible_count, success.coverage) == (0, 1, 0)
    assert tokens.numeric_value is None
    assert (tokens.observed_count, tokens.eligible_count, tokens.coverage) == (0, 1, 0)


def test_complete_event_set_can_report_legitimate_zero_count() -> None:
    metrics = _by_key(_session(events_complete=True), [])
    compactions = metrics["workflow.compaction_count"]

    assert compactions.numeric_value == 0
    assert compactions.coverage == 1


def test_incomplete_event_set_does_not_turn_absence_into_zero() -> None:
    metrics = _by_key(_session(events_complete=False), [])
    compactions = metrics["workflow.compaction_count"]

    assert compactions.numeric_value is None
    assert compactions.coverage == 0
