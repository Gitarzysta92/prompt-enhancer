from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.task_metrics import (
    TASK_METRIC_DEFINITIONS,
    TaskSessionEvidence,
    compute_task_metrics,
)
from prompt_enhancer.domain import EventKind, Provider, SafeEvent, SafeSession, SessionState


NOW = datetime(2026, 5, 5, 8, 0, tzinfo=UTC)


def _session(
    identity: str,
    *,
    ended: bool,
    complete: bool,
    start_minutes: int = 0,
) -> SafeSession:
    started_at = NOW + timedelta(minutes=start_minutes)
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="0" * 64,
        project_id="1" * 64,
        session_id=identity * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=10) if ended else None,
        terminal_state=SessionState.COMPLETED if ended else SessionState.UNKNOWN,
        events_complete=complete,
    )


def _event(session_id: str, identity: str, kind: EventKind, **updates) -> SafeEvent:
    return SafeEvent(
        session_id=session_id,
        event_id=identity * 64,
        kind=kind,
        sequence=0,
        occurred_at=NOW,
        **updates,
    )


def test_task_metrics_keep_partial_coverage_and_unknowns_explicit() -> None:
    complete = _session("a", ended=True, complete=True)
    partial = _session("b", ended=False, complete=False, start_minutes=20)
    verification = _event(
        complete.session_id,
        "c",
        EventKind.VERIFICATION,
        success=True,
    )
    usage_without_values = _event(
        partial.session_id,
        "d",
        EventKind.USAGE,
    )

    results = compute_task_metrics(
        (
            TaskSessionEvidence(complete, (verification,)),
            TaskSessionEvidence(partial, (usage_without_values,)),
        )
    )
    by_key = {result.observation.key: result for result in results}

    assert tuple(by_key) == tuple(definition.key for definition in TASK_METRIC_DEFINITIONS)
    assert by_key["task.workflow.session_count"].observation.numeric_value == 2
    event_count = by_key["task.workflow.observed_event_count"].observation
    assert event_count.numeric_value == 2
    assert event_count.coverage == 0.5
    assert event_count.confidence is None
    cycle_time = by_key["task.efficiency.cycle_time_ms"].observation
    assert cycle_time.numeric_value is None
    assert cycle_time.coverage == 0.5
    token_total = by_key["task.usage.total_tokens"].observation
    assert token_total.numeric_value is None
    assert token_total.coverage == 0
    assert by_key["task.verification.pass_rate"].evidence_event_ids == (
        verification.event_id,
    )


def test_synthetic_adapter_fixture_can_feed_task_metric_pack_without_content() -> None:
    adapter = SyntheticAdapter()
    source_sessions = adapter.list_sessions().sessions

    assert len(source_sessions) == 2
    assert all(not hasattr(session, "prompt") for session in source_sessions)
