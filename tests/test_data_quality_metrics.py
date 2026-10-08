from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prompt_enhancer.application.analysis.deterministic import DEFAULT_METRIC_PACK
from prompt_enhancer.application.analysis.task_metrics import (
    DEFAULT_TASK_METRIC_PACK,
    TASK_METRIC_DEFINITIONS,
    TaskSessionEvidence,
    compute_task_metrics,
)
from prompt_enhancer.domain import (
    EventKind,
    EventTimeBasis,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    UsageRecord,
    UsageCounterKind,
    UsageScope,
)
from prompt_enhancer.metrics import compute_session_metrics


NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def _session(identity: str = "1", *, complete: bool) -> SafeSession:
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="2" * 64,
        project_id="3" * 64,
        session_id=identity * 64,
        provider_version="synthetic-1",
        adapter_version="test-1",
        source_schema_version="synthetic-1",
        started_at=NOW,
        terminal_state=SessionState.UNKNOWN,
        events_complete=complete,
    )


def _event(
    session: SafeSession,
    identity: str,
    kind: EventKind,
    sequence: int,
    **updates: object,
) -> SafeEvent:
    return SafeEvent(
        session_id=session.session_id,
        event_id=identity * 64,
        kind=kind,
        sequence=sequence,
        occurred_at=NOW,
        **updates,
    )


def _representative_events(session: SafeSession) -> tuple[SafeEvent, ...]:
    return (
        _event(
            session,
            "6",
            EventKind.USAGE,
            0,
            usage=UsageRecord(
                total_tokens=10,
                counter_kind=UsageCounterKind.DELTA,
                scope=UsageScope.TURN,
            ),
        ),
        _event(session, "4", EventKind.TURN_END, 1, duration_ms=120),
        _event(session, "5", EventKind.TURN_END, 2),
        _event(session, "7", EventKind.TOOL_END, 3, success=True),
        _event(session, "8", EventKind.TOOL_END, 4, duration_ms=30),
        _event(
            session,
            "9",
            EventKind.UNKNOWN,
            5,
            time_basis=EventTimeBasis.SESSION_STARTED,
        ),
    )


def test_session_readiness_metrics_report_exact_partial_subtotals() -> None:
    session = _session(complete=False)
    by_key = {
        item.key: item
        for item in compute_session_metrics(session, _representative_events(session))
    }

    iterations = by_key["workflow.finalized_turn_count"]
    assert iterations.numeric_value == 2
    assert (iterations.observed_count, iterations.eligible_count) == (0, 1)
    assert iterations.confidence is None

    for key in (
        "data_quality.turn_usage_coverage",
        "data_quality.turn_duration_coverage",
        "data_quality.tool_result_coverage",
        "data_quality.tool_duration_coverage",
    ):
        metric = by_key[key]
        assert metric.numeric_value == 0.5
        assert (metric.observed_count, metric.eligible_count, metric.coverage) == (
            1,
            2,
            0.5,
        )
        assert metric.confidence is None

    unknown_rate = by_key["data_quality.unknown_event_kind_rate"]
    assert unknown_rate.numeric_value == pytest.approx(1 / 6)
    assert (unknown_rate.observed_count, unknown_rate.eligible_count) == (6, 6)
    assert unknown_rate.coverage == 1
    assert unknown_rate.confidence is None

    timestamp_rate = by_key["data_quality.direct_event_timestamp_rate"]
    assert timestamp_rate.numeric_value == pytest.approx(5 / 6)
    assert (timestamp_rate.observed_count, timestamp_rate.eligible_count) == (6, 6)
    assert timestamp_rate.coverage == 1
    assert timestamp_rate.confidence is None


def test_complete_stream_makes_coverage_rate_known_even_when_fields_are_missing() -> None:
    session = _session(complete=True)
    by_key = {
        item.key: item
        for item in compute_session_metrics(session, _representative_events(session))
    }

    assert by_key["data_quality.turn_duration_coverage"].confidence == 1
    assert by_key["data_quality.turn_duration_coverage"].numeric_value == 0.5
    assert by_key["data_quality.unknown_event_kind_rate"].confidence == 1


def test_turn_usage_coverage_rejects_empty_cumulative_and_duplicate_records() -> None:
    session = _session(complete=True)
    events = (
        _event(
            session,
            "a",
            EventKind.USAGE,
            0,
            usage=UsageRecord(
                counter_kind=UsageCounterKind.DELTA,
                scope=UsageScope.TURN,
            ),
        ),
        _event(session, "b", EventKind.TURN_END, 1),
        _event(
            session,
            "c",
            EventKind.USAGE,
            2,
            usage=UsageRecord(
                total_tokens=20,
                counter_kind=UsageCounterKind.CUMULATIVE,
                scope=UsageScope.TURN,
            ),
        ),
        _event(session, "d", EventKind.TURN_END, 3),
        _event(
            session,
            "e",
            EventKind.USAGE,
            4,
            usage=UsageRecord(
                total_tokens=8,
                counter_kind=UsageCounterKind.DELTA,
                scope=UsageScope.TURN,
            ),
        ),
        _event(
            session,
            "f",
            EventKind.USAGE,
            5,
            usage=UsageRecord(
                input_tokens=5,
                counter_kind=UsageCounterKind.DELTA,
                scope=UsageScope.TURN,
            ),
        ),
        _event(session, "0", EventKind.TURN_END, 6),
        _event(session, "1", EventKind.TURN_END, 7),
    )

    by_key = {item.key: item for item in compute_session_metrics(session, events)}
    coverage = by_key["data_quality.turn_usage_coverage"]

    assert coverage.numeric_value == 0.25
    assert (coverage.observed_count, coverage.eligible_count) == (1, 4)
    assert coverage.confidence == 1


def test_coverage_metrics_are_unknown_when_nothing_is_eligible() -> None:
    session = _session(complete=True)
    by_key = {item.key: item for item in compute_session_metrics(session, ())}

    for key in (
        "data_quality.turn_usage_coverage",
        "data_quality.turn_duration_coverage",
        "data_quality.tool_result_coverage",
        "data_quality.tool_duration_coverage",
        "data_quality.unknown_event_kind_rate",
        "data_quality.direct_event_timestamp_rate",
    ):
        metric = by_key[key]
        assert metric.numeric_value is None
        assert (metric.observed_count, metric.eligible_count, metric.coverage) == (
            0,
            0,
            0,
        )
        assert metric.confidence is None


def test_task_readiness_metrics_aggregate_safe_events_without_false_confidence() -> None:
    first = _session("a", complete=True)
    second = _session("b", complete=False)
    first_events = _representative_events(first)[:3]
    second_events = _representative_events(second)[3:]
    results = compute_task_metrics(
        (
            TaskSessionEvidence(first, first_events),
            TaskSessionEvidence(second, second_events),
        )
    )
    by_key = {result.observation.key: result for result in results}

    iterations = by_key["task.workflow.finalized_turn_count"]
    assert iterations.observation.numeric_value == 2
    assert iterations.observation.coverage == 0.5
    assert iterations.observation.confidence is None
    assert iterations.evidence_event_ids == tuple(
        event.event_id
        for event in first_events
        if event.kind is EventKind.TURN_END
    )

    for key in (
        "task.data_quality.turn_usage_coverage",
        "task.data_quality.turn_duration_coverage",
        "task.data_quality.tool_result_coverage",
        "task.data_quality.tool_duration_coverage",
    ):
        metric = by_key[key].observation
        assert metric.numeric_value == 0.5
        assert (metric.observed_count, metric.eligible_count, metric.coverage) == (
            1,
            2,
            0.5,
        )
        assert metric.confidence is None

    unknown_rate = by_key["task.data_quality.unknown_event_kind_rate"].observation
    assert unknown_rate.numeric_value == pytest.approx(1 / 6)
    assert (unknown_rate.observed_count, unknown_rate.eligible_count) == (6, 6)
    assert unknown_rate.coverage == 1
    assert unknown_rate.confidence is None

    timestamp_rate = by_key[
        "task.data_quality.direct_event_timestamp_rate"
    ].observation
    assert timestamp_rate.numeric_value == pytest.approx(5 / 6)
    assert (timestamp_rate.observed_count, timestamp_rate.eligible_count) == (6, 6)
    assert timestamp_rate.coverage == 1
    assert timestamp_rate.confidence is None


def test_receiver_observed_timestamps_are_not_provider_direct() -> None:
    session = _session(complete=False)
    events = (
        _event(session, "a", EventKind.TURN_START, 0),
        _event(
            session,
            "b",
            EventKind.TOOL_START,
            1,
            time_basis=EventTimeBasis.RECEIVER_OBSERVED,
        ),
        _event(
            session,
            "c",
            EventKind.TURN_END,
            2,
            time_basis=EventTimeBasis.TURN_COMPLETED,
        ),
    )

    session_metric = next(
        metric
        for metric in compute_session_metrics(session, events)
        if metric.key == "data_quality.direct_event_timestamp_rate"
    )
    task_metric = next(
        result.observation
        for result in compute_task_metrics((TaskSessionEvidence(session, events),))
        if result.observation.key == "task.data_quality.direct_event_timestamp_rate"
    )

    assert session_metric.version == 2 and session_metric.numeric_value == pytest.approx(1 / 3)
    assert task_metric.version == 2 and task_metric.numeric_value == pytest.approx(1 / 3)


def test_operational_metric_packs_are_version_four_without_engine_family_change() -> None:
    assert DEFAULT_METRIC_PACK.version == 4
    assert DEFAULT_TASK_METRIC_PACK.version == 4
    assert tuple(
        definition.key for definition in TASK_METRIC_DEFINITIONS
    ) == DEFAULT_TASK_METRIC_PACK.metric_keys

    session = _session(complete=True)
    computed = compute_task_metrics(
        (TaskSessionEvidence(session, _representative_events(session)),)
    )
    assert tuple(
        result.observation.key for result in computed
    ) == DEFAULT_TASK_METRIC_PACK.metric_keys
    assert tuple(
        (result.observation.key, result.observation.version) for result in computed
    ) == tuple(
        (definition.key, definition.version)
        for definition in TASK_METRIC_DEFINITIONS
    )
