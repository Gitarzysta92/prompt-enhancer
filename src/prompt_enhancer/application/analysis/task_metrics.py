"""Deterministic metadata-only metrics over one reviewed task revision."""

from __future__ import annotations

from dataclasses import dataclass

from ...domain import (
    EventKind,
    EventTimeBasis,
    MetricObservation,
    MetricSource,
    SafeEvent,
    SafeSession,
    UsageCounterKind,
    UsageScope,
)
from .contracts import MetricDefinition, MetricPack
from .deterministic import paired_usable_turn_usage_events


TASK_METRIC_ENGINE_VERSION = "task-deterministic-2"
DEFAULT_TASK_METRIC_PACK_KEY = "core.metadata.task"


TASK_SESSION_COUNT = MetricDefinition(
    key="task.workflow.session_count",
    version=2,
    dimension="workflow",
    display_name="Session count",
    description="Number of reviewed sessions assigned to this task revision.",
    unit="count",
)
TASK_OBSERVED_EVENT_COUNT = MetricDefinition(
    key="task.workflow.observed_event_count",
    version=2,
    dimension="workflow",
    display_name="Observed event count",
    description=(
        "Events available for this task; coverage is the share of sessions whose "
        "event stream is marked complete."
    ),
    unit="count",
)
TASK_CYCLE_TIME = MetricDefinition(
    key="task.efficiency.cycle_time_ms",
    version=2,
    dimension="efficiency",
    display_name="Task cycle time",
    description=(
        "Elapsed time from the earliest session start to the latest session end; "
        "unknown until every assigned session has an end timestamp."
    ),
    unit="milliseconds",
)
TASK_VERIFICATION_COUNT = MetricDefinition(
    key="task.verification.observed_count",
    version=2,
    dimension="verification",
    display_name="Observed verifications",
    description=(
        "Verification events available for the task; stream completeness is "
        "reported as coverage."
    ),
    unit="count",
)
TASK_VERIFICATION_PASS_RATE = MetricDefinition(
    key="task.verification.pass_rate",
    version=2,
    dimension="verification",
    display_name="Verification pass rate",
    description="Successful verification results divided by known results.",
    unit="ratio",
)
TASK_INPUT_TOKENS = MetricDefinition(
    key="task.usage.input_tokens",
    version=2,
    dimension="usage",
    display_name="Input tokens",
    description="Subtotal of additive input-token deltas across task sessions.",
    unit="tokens",
    source=MetricSource.PROVIDER_REPORTED,
)
TASK_OUTPUT_TOKENS = MetricDefinition(
    key="task.usage.output_tokens",
    version=2,
    dimension="usage",
    display_name="Output tokens",
    description="Subtotal of additive output-token deltas across task sessions.",
    unit="tokens",
    source=MetricSource.PROVIDER_REPORTED,
)
TASK_TOTAL_TOKENS = MetricDefinition(
    key="task.usage.total_tokens",
    version=2,
    dimension="usage",
    display_name="Total tokens",
    description="Subtotal of additive total-token deltas across task sessions.",
    unit="tokens",
    source=MetricSource.PROVIDER_REPORTED,
)
TASK_FINALIZED_TURN_COUNT = MetricDefinition(
    key="task.workflow.finalized_turn_count",
    version=1,
    dimension="workflow",
    display_name="Observed agent iterations",
    description=(
        "Observed finalized-turn subtotal across reviewed task sessions; full "
        "confidence requires complete event streams."
    ),
    unit="count",
)
TASK_TURN_USAGE_COVERAGE = MetricDefinition(
    key="task.data_quality.turn_usage_coverage",
    version=1,
    dimension="data_quality",
    display_name="Usable turn usage coverage",
    description=(
        "Share of observed finalized turns sequence-paired with an additive, "
        "turn-scoped usage record containing at least one token counter."
    ),
    unit="ratio",
)
TASK_TURN_DURATION_COVERAGE = MetricDefinition(
    key="task.data_quality.turn_duration_coverage",
    version=1,
    dimension="data_quality",
    display_name="Turn duration coverage",
    description="Share of observed finalized turns with a known duration.",
    unit="ratio",
)
TASK_TOOL_RESULT_COVERAGE = MetricDefinition(
    key="task.data_quality.tool_result_coverage",
    version=1,
    dimension="data_quality",
    display_name="Tool result coverage",
    description="Share of observed completed tool events with a known result.",
    unit="ratio",
)
TASK_TOOL_DURATION_COVERAGE = MetricDefinition(
    key="task.data_quality.tool_duration_coverage",
    version=1,
    dimension="data_quality",
    display_name="Tool duration coverage",
    description="Share of observed completed tool events with a known duration.",
    unit="ratio",
)
TASK_UNKNOWN_EVENT_KIND_RATE = MetricDefinition(
    key="task.data_quality.unknown_event_kind_rate",
    version=1,
    dimension="data_quality",
    display_name="Unknown event kind rate",
    description="Share of observed safe events whose event kind is unknown.",
    unit="ratio",
)
TASK_DIRECT_EVENT_TIMESTAMP_RATE = MetricDefinition(
    key="task.data_quality.direct_event_timestamp_rate",
    version=2,
    dimension="data_quality",
    display_name="Direct event timestamp rate",
    description=(
        "Share of observed safe events with an event-specific provider timestamp; "
        "containing-turn and session fallback timestamps are excluded."
    ),
    unit="ratio",
)


TASK_METRIC_DEFINITIONS = (
    TASK_SESSION_COUNT,
    TASK_OBSERVED_EVENT_COUNT,
    TASK_CYCLE_TIME,
    TASK_VERIFICATION_COUNT,
    TASK_VERIFICATION_PASS_RATE,
    TASK_INPUT_TOKENS,
    TASK_OUTPUT_TOKENS,
    TASK_TOTAL_TOKENS,
    TASK_FINALIZED_TURN_COUNT,
    TASK_TURN_USAGE_COVERAGE,
    TASK_TURN_DURATION_COVERAGE,
    TASK_TOOL_RESULT_COVERAGE,
    TASK_TOOL_DURATION_COVERAGE,
    TASK_UNKNOWN_EVENT_KIND_RATE,
    TASK_DIRECT_EVENT_TIMESTAMP_RATE,
)
DEFAULT_TASK_METRIC_PACK = MetricPack(
    key=DEFAULT_TASK_METRIC_PACK_KEY,
    version=4,
    metric_keys=tuple(definition.key for definition in TASK_METRIC_DEFINITIONS),
)


@dataclass(frozen=True, slots=True)
class TaskSessionEvidence:
    session: SafeSession
    events: tuple[SafeEvent, ...]

    def __post_init__(self) -> None:
        if any(event.session_id != self.session.session_id for event in self.events):
            raise ValueError("task events must belong to their safe session")


@dataclass(frozen=True, slots=True)
class TaskMetricResult:
    observation: MetricObservation
    evidence_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.evidence_event_ids)) != len(self.evidence_event_ids):
            raise ValueError("task metric evidence cannot contain duplicate events")


def _coverage(observed: int, eligible: int) -> float:
    return 0.0 if eligible == 0 else observed / eligible


def _numeric(
    definition: MetricDefinition,
    value: int | float | None,
    observed: int,
    eligible: int,
    *,
    confidence: float | None = None,
    source: MetricSource | None = None,
    evidence: tuple[str, ...] = (),
) -> TaskMetricResult:
    return TaskMetricResult(
        observation=MetricObservation(
            key=definition.key,
            version=definition.version,
            numeric_value=None if value is None else float(value),
            unit=definition.unit,
            source=definition.source if source is None else source,
            observed_count=observed,
            eligible_count=eligible,
            coverage=_coverage(observed, eligible),
            confidence=confidence,
        ),
        evidence_event_ids=evidence,
    )


def _usage_metric(
    definition: MetricDefinition,
    attribute: str,
    usage_events: tuple[SafeEvent, ...],
    *,
    finalized_turn_count: int,
    streams_complete: bool,
) -> TaskMetricResult:
    additive_events = tuple(
        event
        for event in usage_events
        if event.usage is not None
        and event.usage.counter_kind is UsageCounterKind.DELTA
    )
    eligible_events = tuple(
        event
        for event in usage_events
        if event.usage is None
        or event.usage.counter_kind is not UsageCounterKind.CUMULATIVE
    )
    turn_eligible_events = tuple(
        event
        for event in eligible_events
        if event.usage is not None
        and event.usage.scope is UsageScope.TURN
    )
    other_eligible_events = tuple(
        event
        for event in eligible_events
        if event.usage is None
        or event.usage.scope is not UsageScope.TURN
    )
    eligible_count = max(finalized_turn_count, len(turn_eligible_events)) + len(
        other_eligible_events
    )
    known = tuple(
        event
        for event in additive_events
        if event.usage is not None
        and getattr(event.usage, attribute) is not None
    )
    values = tuple(getattr(event.usage, attribute) for event in known)
    source = (
        MetricSource.ESTIMATED
        if any(not event.usage.provider_reported for event in known)
        else MetricSource.PROVIDER_REPORTED
    )
    fully_known = (
        bool(known)
        and len(known) == eligible_count
        and streams_complete
    )
    return _numeric(
        definition,
        sum(values) if values else None,
        len(known),
        eligible_count,
        confidence=1.0 if fully_known else None,
        source=source,
        evidence=tuple(event.event_id for event in known),
    )


def _coverage_metric(
    definition: MetricDefinition,
    observed_events: tuple[SafeEvent, ...],
    eligible_events: tuple[SafeEvent, ...],
    *,
    streams_complete: bool,
) -> TaskMetricResult:
    eligible = len(eligible_events)
    observed = min(len(observed_events), eligible)
    value = None if eligible == 0 else observed / eligible
    return _numeric(
        definition,
        value,
        observed,
        eligible,
        confidence=1.0 if streams_complete and value is not None else None,
        evidence=tuple(event.event_id for event in observed_events[:observed]),
    )


def _observed_event_rate(
    definition: MetricDefinition,
    events: tuple[SafeEvent, ...],
    *,
    matching_count: int,
    streams_complete: bool,
) -> TaskMetricResult:
    eligible = len(events)
    value = None if eligible == 0 else matching_count / eligible
    return _numeric(
        definition,
        value,
        eligible,
        eligible,
        confidence=1.0 if streams_complete and value is not None else None,
        evidence=tuple(event.event_id for event in events),
    )


def compute_task_metrics(
    sessions: tuple[TaskSessionEvidence, ...],
) -> tuple[TaskMetricResult, ...]:
    """Compute the explicit task metric pack from safe metadata only."""

    if not sessions:
        raise ValueError("task analysis requires at least one safe session")
    session_ids = tuple(item.session.session_id for item in sessions)
    if len(set(session_ids)) != len(session_ids):
        raise ValueError("task analysis sessions cannot contain duplicates")

    all_events = tuple(event for item in sessions for event in item.events)
    verification_events = tuple(
        event for event in all_events if event.kind is EventKind.VERIFICATION
    )
    usage_events = tuple(event for event in all_events if event.kind is EventKind.USAGE)
    streams_observed = sum(item.session.events_complete for item in sessions)
    finalized_turn_count = sum(
        event.kind is EventKind.TURN_END for event in all_events
    )
    finalized_turns = tuple(
        event for event in all_events if event.kind is EventKind.TURN_END
    )
    turn_usage_events = tuple(
        event
        for item in sessions
        for event in paired_usable_turn_usage_events(item.events)
    )
    tool_events = tuple(
        event for event in all_events if event.kind is EventKind.TOOL_END
    )
    streams_complete = streams_observed == len(sessions)
    known_ends = tuple(
        item.session.ended_at
        for item in sessions
        if item.session.ended_at is not None
    )
    cycle_time = (
        int(
            (
                max(known_ends)
                - min(item.session.started_at for item in sessions)
            ).total_seconds()
            * 1000
        )
        if len(known_ends) == len(sessions)
        else None
    )
    known_verifications = tuple(
        event for event in verification_events if event.success is not None
    )
    verification_rate = (
        None
        if not known_verifications
        else sum(bool(event.success) for event in known_verifications)
        / len(known_verifications)
    )

    return (
        _numeric(
            TASK_SESSION_COUNT,
            len(sessions),
            len(sessions),
            len(sessions),
            confidence=1.0,
        ),
        _numeric(
            TASK_OBSERVED_EVENT_COUNT,
            len(all_events),
            streams_observed,
            len(sessions),
            confidence=1.0 if streams_complete else None,
            evidence=tuple(event.event_id for event in all_events),
        ),
        _numeric(
            TASK_CYCLE_TIME,
            cycle_time,
            len(known_ends),
            len(sessions),
            confidence=1.0 if cycle_time is not None else None,
        ),
        _numeric(
            TASK_VERIFICATION_COUNT,
            len(verification_events),
            streams_observed,
            len(sessions),
            confidence=1.0 if streams_complete else None,
            evidence=tuple(event.event_id for event in verification_events),
        ),
        _numeric(
            TASK_VERIFICATION_PASS_RATE,
            verification_rate,
            len(known_verifications),
            len(verification_events),
            confidence=(
                1.0
                if verification_rate is not None
                and len(known_verifications) == len(verification_events)
                and streams_complete
                else None
            ),
            evidence=tuple(event.event_id for event in known_verifications),
        ),
        _usage_metric(
            TASK_INPUT_TOKENS,
            "input_tokens",
            usage_events,
            streams_complete=streams_complete,
            finalized_turn_count=finalized_turn_count,
        ),
        _usage_metric(
            TASK_OUTPUT_TOKENS,
            "output_tokens",
            usage_events,
            streams_complete=streams_complete,
            finalized_turn_count=finalized_turn_count,
        ),
        _usage_metric(
            TASK_TOTAL_TOKENS,
            "total_tokens",
            usage_events,
            streams_complete=streams_complete,
            finalized_turn_count=finalized_turn_count,
        ),
        _numeric(
            TASK_FINALIZED_TURN_COUNT,
            finalized_turn_count,
            streams_observed,
            len(sessions),
            confidence=1.0 if streams_complete else None,
            evidence=tuple(event.event_id for event in finalized_turns),
        ),
        _coverage_metric(
            TASK_TURN_USAGE_COVERAGE,
            turn_usage_events,
            finalized_turns,
            streams_complete=streams_complete,
        ),
        _coverage_metric(
            TASK_TURN_DURATION_COVERAGE,
            tuple(event for event in finalized_turns if event.duration_ms is not None),
            finalized_turns,
            streams_complete=streams_complete,
        ),
        _coverage_metric(
            TASK_TOOL_RESULT_COVERAGE,
            tuple(event for event in tool_events if event.success is not None),
            tool_events,
            streams_complete=streams_complete,
        ),
        _coverage_metric(
            TASK_TOOL_DURATION_COVERAGE,
            tuple(event for event in tool_events if event.duration_ms is not None),
            tool_events,
            streams_complete=streams_complete,
        ),
        _observed_event_rate(
            TASK_UNKNOWN_EVENT_KIND_RATE,
            all_events,
            matching_count=sum(
                event.kind is EventKind.UNKNOWN for event in all_events
            ),
            streams_complete=streams_complete,
        ),
        _observed_event_rate(
            TASK_DIRECT_EVENT_TIMESTAMP_RATE,
            all_events,
            matching_count=sum(
                event.time_basis is EventTimeBasis.PROVIDER_REPORTED
                for event in all_events
            ),
            streams_complete=streams_complete,
        ),
    )
