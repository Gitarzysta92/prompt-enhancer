from __future__ import annotations

from datetime import UTC, datetime

from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    EventKind,
    EventTimeBasis,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from prompt_enhancer.metrics import compute_session_metrics


NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _session() -> SafeSession:
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="1" * 64,
        project_id="2" * 64,
        session_id="3" * 64,
        provider_version="synthetic-1",
        adapter_version="test-1",
        source_schema_version="synthetic-1",
        started_at=NOW,
        terminal_state=SessionState.UNKNOWN,
        events_complete=True,
    )


def _usage_event(
    event_id: str,
    sequence: int,
    total: int,
    counter_kind: UsageCounterKind,
) -> SafeEvent:
    session = _session()
    return SafeEvent(
        session_id=session.session_id,
        event_id=event_id * 64,
        kind=EventKind.USAGE,
        sequence=sequence,
        occurred_at=NOW,
        time_basis=EventTimeBasis.TURN_COMPLETED,
        usage=UsageRecord(
            total_tokens=total,
            provider_reported=True,
            counter_kind=counter_kind,
            scope=UsageScope.TURN,
        ),
    )


def test_additive_metrics_exclude_cumulative_usage() -> None:
    observations = compute_session_metrics(
        _session(),
        (
            _usage_event("4", 0, 10, UsageCounterKind.DELTA),
            _usage_event("5", 1, 100, UsageCounterKind.CUMULATIVE),
        ),
    )
    total = {item.key: item for item in observations}["usage.total_tokens"]

    assert total.numeric_value == 10
    assert (total.observed_count, total.eligible_count) == (1, 1)
    assert total.coverage == 1


def test_finalized_turn_without_usage_reduces_token_coverage() -> None:
    session = _session().model_copy(update={"events_complete": False})
    events = (
        _usage_event("4", 0, 10, UsageCounterKind.DELTA),
        SafeEvent(
            session_id=session.session_id,
            event_id="7" * 64,
            kind=EventKind.TURN_END,
            sequence=1,
            occurred_at=NOW,
            duration_ms=100,
        ),
        SafeEvent(
            session_id=session.session_id,
            event_id="8" * 64,
            kind=EventKind.TURN_END,
            sequence=2,
            occurred_at=NOW,
            duration_ms=200,
        ),
    )

    observations = compute_session_metrics(session, events)
    total = {item.key: item for item in observations}["usage.total_tokens"]

    assert total.numeric_value == 10
    assert (total.observed_count, total.eligible_count) == (1, 2)
    assert total.coverage == 0.5
    assert total.confidence is None


def test_usage_and_timestamp_provenance_round_trip(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    session = _session()
    event = _usage_event("6", 0, 12, UsageCounterKind.DELTA)

    database.persist_session(session, (event,))
    restored = database.get_session_events(session.session_id)

    assert restored == (event,)
