"""Trusted metadata-only feature extractors and deterministic calculators."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from ...domain import (
    DataTier,
    EventKind,
    EventTimeBasis,
    MetricObservation,
    MetricSource,
    SafeEvent,
    SessionState,
    UsageCounterKind,
    UsageScope,
)
from .contracts import AnalysisContext, FeatureSet, MetricDefinition, MetricPack
from .registry import MetricEngine, TrustedAnalysisRegistry


METRIC_ENGINE_VERSION = "deterministic-2"
NOT_APPLICABLE_VERSION = "not-applicable"
DEFAULT_METRIC_PACK_KEY = "core.metadata.session"

EVENT_GROUPS_FEATURE = "metadata.event_groups"
KNOWN_DURATIONS_FEATURE = "metadata.known_tool_durations"


@dataclass(frozen=True, slots=True)
class EventGroups:
    """Reusable immutable event classifications for content-free metrics."""

    all_events: tuple[SafeEvent, ...]
    tool_events: tuple[SafeEvent, ...]
    verification_events: tuple[SafeEvent, ...]
    timed_events: tuple[SafeEvent, ...]
    usage_events: tuple[SafeEvent, ...]


@dataclass(frozen=True, slots=True)
class KnownDurations:
    """Known duration subtotal and its observation denominator."""

    values_ms: tuple[int, ...]
    eligible_count: int


class EventGroupsExtractor:
    key = EVENT_GROUPS_FEATURE
    required_features: frozenset[str] = frozenset()
    required_tier = DataTier.METADATA

    def extract(self, context: AnalysisContext, features: FeatureSet) -> EventGroups:
        tool_events = tuple(
            event for event in context.events if event.kind is EventKind.TOOL_END
        )
        verification_events = tuple(
            event for event in context.events if event.kind is EventKind.VERIFICATION
        )
        return EventGroups(
            all_events=context.events,
            tool_events=tool_events,
            verification_events=verification_events,
            timed_events=tool_events + verification_events,
            usage_events=tuple(
                event for event in context.events if event.kind is EventKind.USAGE
            ),
        )


class KnownDurationsExtractor:
    key = KNOWN_DURATIONS_FEATURE
    required_features = frozenset({EVENT_GROUPS_FEATURE})
    required_tier = DataTier.METADATA

    def extract(
        self,
        context: AnalysisContext,
        features: FeatureSet,
    ) -> KnownDurations:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        return KnownDurations(
            values_ms=tuple(
                event.duration_ms
                for event in groups.timed_events
                if event.duration_ms is not None
            ),
            eligible_count=len(groups.timed_events),
        )


SESSION_STATE_DEFINITION = MetricDefinition(
    "outcome.session_state",
    2,
    "outcome",
    "Session state",
    "Provider-reported terminal state; unknown is not treated as failure.",
    "state",
    MetricSource.PROVIDER_REPORTED,
)
CYCLE_TIME_DEFINITION = MetricDefinition(
    "efficiency.cycle_time_ms",
    2,
    "efficiency",
    "Cycle time",
    "Elapsed milliseconds between known session start and end timestamps.",
    "milliseconds",
)
EVENT_COUNT_DEFINITION = MetricDefinition(
    "workflow.event_count",
    2,
    "workflow",
    "Event count",
    "Observed event subtotal; full confidence requires a complete event stream.",
    "count",
)
PLAN_EVENT_COUNT_DEFINITION = MetricDefinition(
    "workflow.plan_event_count",
    2,
    "workflow",
    "Plan event count",
    "Observed plan-event subtotal; full confidence requires a complete event stream.",
    "count",
)
COMPACTION_COUNT_DEFINITION = MetricDefinition(
    "workflow.compaction_count",
    2,
    "workflow",
    "Compaction count",
    "Observed compaction subtotal; full confidence requires a complete event stream.",
    "count",
)
TOOL_EVENT_COUNT_DEFINITION = MetricDefinition(
    "workflow.tool_event_count",
    2,
    "workflow",
    "Completed tool event count",
    "Observed tool-end subtotal; full confidence requires a complete event stream.",
    "count",
)
TOOL_SUCCESS_RATE_DEFINITION = MetricDefinition(
    "reliability.tool_success_rate",
    2,
    "reliability",
    "Tool success rate",
    "Known successful tool-end events divided by tool-end events with a success flag.",
    "ratio",
)
VERIFICATION_COUNT_DEFINITION = MetricDefinition(
    "verification.verification_count",
    2,
    "verification",
    "Verification count",
    "Observed verification subtotal; full confidence requires a complete event stream.",
    "count",
)
VERIFICATION_PASS_RATE_DEFINITION = MetricDefinition(
    "verification.pass_rate",
    2,
    "verification",
    "Verification pass rate",
    "Known successful verification events divided by verification events with a result.",
    "ratio",
)
OBSERVED_TOOL_DURATION_DEFINITION = MetricDefinition(
    "efficiency.observed_tool_duration_ms",
    2,
    "efficiency",
    "Observed tool duration",
    "Subtotal of known tool and verification durations; coverage shows missing durations.",
    "milliseconds",
)
OBSERVED_TURN_DURATION_DEFINITION = MetricDefinition(
    "efficiency.observed_finalized_turn_duration_ms",
    1,
    "efficiency",
    "Observed finalized-turn duration",
    "Subtotal of known finalized-turn durations; coverage shows missing durations.",
    "milliseconds",
)
FINALIZED_TURN_COUNT_DEFINITION = MetricDefinition(
    "workflow.finalized_turn_count",
    1,
    "workflow",
    "Observed agent iterations",
    "Observed finalized-turn subtotal; full confidence requires a complete event stream.",
    "count",
)
TURN_USAGE_COVERAGE_DEFINITION = MetricDefinition(
    "data_quality.turn_usage_coverage",
    1,
    "data_quality",
    "Usable turn usage coverage",
    (
        "Share of observed finalized turns sequence-paired with an additive, "
        "turn-scoped usage record containing at least one token counter."
    ),
    "ratio",
)
TURN_DURATION_COVERAGE_DEFINITION = MetricDefinition(
    "data_quality.turn_duration_coverage",
    1,
    "data_quality",
    "Turn duration coverage",
    "Share of observed finalized turns with a known duration.",
    "ratio",
)
TOOL_RESULT_COVERAGE_DEFINITION = MetricDefinition(
    "data_quality.tool_result_coverage",
    1,
    "data_quality",
    "Tool result coverage",
    "Share of observed completed tool events with a known result.",
    "ratio",
)
TOOL_DURATION_COVERAGE_DEFINITION = MetricDefinition(
    "data_quality.tool_duration_coverage",
    1,
    "data_quality",
    "Tool duration coverage",
    "Share of observed completed tool events with a known duration.",
    "ratio",
)
UNKNOWN_EVENT_KIND_RATE_DEFINITION = MetricDefinition(
    "data_quality.unknown_event_kind_rate",
    1,
    "data_quality",
    "Unknown event kind rate",
    "Share of observed safe events whose event kind is unknown.",
    "ratio",
)
DIRECT_EVENT_TIMESTAMP_RATE_DEFINITION = MetricDefinition(
    "data_quality.direct_event_timestamp_rate",
    2,
    "data_quality",
    "Direct event timestamp rate",
    (
        "Share of observed safe events with an event-specific provider timestamp; "
        "containing-turn and session fallback timestamps are excluded."
    ),
    "ratio",
)

INPUT_TOKENS_DEFINITION = MetricDefinition(
    "usage.input_tokens",
    2,
    "usage",
    "Input tokens",
    "Sum of additive input-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)
CACHED_INPUT_TOKENS_DEFINITION = MetricDefinition(
    "usage.cached_input_tokens",
    2,
    "usage",
    "Cached input tokens",
    "Sum of additive cached-input-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)
CACHE_CREATION_TOKENS_DEFINITION = MetricDefinition(
    "usage.cache_creation_tokens",
    2,
    "usage",
    "Cache creation tokens",
    "Sum of additive cache-creation-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)
OUTPUT_TOKENS_DEFINITION = MetricDefinition(
    "usage.output_tokens",
    2,
    "usage",
    "Output tokens",
    "Sum of additive output-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)
REASONING_OUTPUT_TOKENS_DEFINITION = MetricDefinition(
    "usage.reasoning_output_tokens",
    2,
    "usage",
    "Reasoning output tokens",
    "Sum of additive reasoning-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)
TOTAL_TOKENS_DEFINITION = MetricDefinition(
    "usage.total_tokens",
    2,
    "usage",
    "Total tokens",
    "Sum of additive total-token deltas; cumulative or unknown counters are excluded.",
    "tokens",
    MetricSource.PROVIDER_REPORTED,
)


def _coverage(observed: int, eligible: int) -> float:
    return 0.0 if eligible == 0 else observed / eligible


def _numeric(
    definition: MetricDefinition,
    value: int | float | None,
    observed: int,
    eligible: int,
    *,
    source: MetricSource | None = None,
    allow_full_confidence: bool = True,
) -> MetricObservation:
    return MetricObservation(
        key=definition.key,
        version=definition.version,
        numeric_value=None if value is None else float(value),
        unit=definition.unit,
        source=definition.source if source is None else source,
        observed_count=observed,
        eligible_count=eligible,
        coverage=_coverage(observed, eligible),
        confidence=(
            1.0
            if allow_full_confidence and value is not None and observed == eligible
            else None
        ),
    )


TOKEN_COUNTER_ATTRIBUTES = (
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def paired_usable_turn_usage_events(
    events: tuple[SafeEvent, ...],
) -> tuple[SafeEvent, ...]:
    """Return at most one usable usage event per observed finalized turn.

    The canonical event model does not retain a provider turn identifier. Pairing
    is therefore explicit and deterministic: within sequence order, the latest
    usable turn-scoped usage event since TURN_START or the preceding TURN_END is
    paired with the next TURN_END. Orphan and duplicate records cannot increase
    coverage beyond one observation for that finalized turn.
    """

    paired: list[SafeEvent] = []
    pending: SafeEvent | None = None
    for event in sorted(events, key=lambda item: item.sequence):
        if event.kind is EventKind.TURN_START:
            pending = None
        elif (
            event.kind is EventKind.USAGE
            and event.usage is not None
            and event.usage.scope is UsageScope.TURN
            and event.usage.counter_kind is UsageCounterKind.DELTA
            and any(
                getattr(event.usage, attribute) is not None
                for attribute in TOKEN_COUNTER_ATTRIBUTES
            )
        ):
            pending = event
        elif event.kind is EventKind.TURN_END:
            if pending is not None:
                paired.append(pending)
            pending = None
    return tuple(paired)


@dataclass(frozen=True, slots=True)
class SessionStateCalculator:
    definition: MetricDefinition = SESSION_STATE_DEFINITION
    required_features: frozenset[str] = frozenset()
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        terminal_known = context.session.terminal_state is not SessionState.UNKNOWN
        return MetricObservation(
            key=self.definition.key,
            version=self.definition.version,
            text_value=(
                context.session.terminal_state.value if terminal_known else None
            ),
            unit=self.definition.unit,
            source=self.definition.source,
            observed_count=int(terminal_known),
            eligible_count=1,
            coverage=float(terminal_known),
            confidence=1.0 if terminal_known else None,
        )


@dataclass(frozen=True, slots=True)
class CycleTimeCalculator:
    definition: MetricDefinition = CYCLE_TIME_DEFINITION
    required_features: frozenset[str] = frozenset()
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        ended_known = context.session.ended_at is not None
        cycle_time = (
            int(
                (context.session.ended_at - context.session.started_at).total_seconds()
                * 1000
            )
            if context.session.ended_at is not None
            else None
        )
        return _numeric(
            self.definition,
            cycle_time,
            1 + int(ended_known),
            2,
        )


EventCollection = Literal[
    "all_events", "tool_events", "verification_events"
]


@dataclass(frozen=True, slots=True)
class CompleteCountCalculator:
    definition: MetricDefinition
    collection: EventCollection = "all_events"
    kind: EventKind | None = None
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        events = cast(tuple[SafeEvent, ...], getattr(groups, self.collection))
        value = (
            len(events)
            if self.kind is None
            else sum(event.kind is self.kind for event in events)
        )
        complete = context.session.events_complete
        has_observed_stream = bool(groups.all_events)
        return _numeric(
            self.definition,
            value if complete or has_observed_stream else None,
            int(complete),
            1,
            allow_full_confidence=complete,
        )


@dataclass(frozen=True, slots=True)
class RateCalculator:
    definition: MetricDefinition
    collection: Literal["tool_events", "verification_events"]
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        events = cast(tuple[SafeEvent, ...], getattr(groups, self.collection))
        observed = tuple(
            event.success for event in events if event.success is not None
        )
        value = (
            None
            if not observed
            else sum(bool(item) for item in observed) / len(observed)
        )
        return _numeric(
            self.definition,
            value,
            len(observed),
            len(events),
            allow_full_confidence=context.session.events_complete,
        )


@dataclass(frozen=True, slots=True)
class ObservedToolDurationCalculator:
    definition: MetricDefinition = OBSERVED_TOOL_DURATION_DEFINITION
    required_features: frozenset[str] = frozenset({KNOWN_DURATIONS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        durations = cast(KnownDurations, features[KNOWN_DURATIONS_FEATURE])
        return _numeric(
            self.definition,
            sum(durations.values_ms) if durations.values_ms else None,
            len(durations.values_ms),
            durations.eligible_count,
            allow_full_confidence=context.session.events_complete,
        )


@dataclass(frozen=True, slots=True)
class ObservedTurnDurationCalculator:
    definition: MetricDefinition = OBSERVED_TURN_DURATION_DEFINITION
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        turn_ends = tuple(
            event for event in groups.all_events if event.kind is EventKind.TURN_END
        )
        values = tuple(
            event.duration_ms for event in turn_ends if event.duration_ms is not None
        )
        return _numeric(
            self.definition,
            sum(values) if values else None,
            len(values),
            len(turn_ends),
            allow_full_confidence=context.session.events_complete,
        )


DataCoverageKind = Literal[
    "turn_usage", "turn_duration", "tool_result", "tool_duration"
]


@dataclass(frozen=True, slots=True)
class DataCoverageCalculator:
    """Measure field presence without treating missing values as zero."""

    definition: MetricDefinition
    coverage_kind: DataCoverageKind
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        turn_ends = tuple(
            event for event in groups.all_events if event.kind is EventKind.TURN_END
        )
        if self.coverage_kind == "turn_usage":
            eligible = len(turn_ends)
            observed = len(paired_usable_turn_usage_events(groups.all_events))
        elif self.coverage_kind == "turn_duration":
            eligible = len(turn_ends)
            observed = sum(event.duration_ms is not None for event in turn_ends)
        elif self.coverage_kind == "tool_result":
            eligible = len(groups.tool_events)
            observed = sum(event.success is not None for event in groups.tool_events)
        else:
            eligible = len(groups.tool_events)
            observed = sum(
                event.duration_ms is not None for event in groups.tool_events
            )
        value = None if eligible == 0 else observed / eligible
        return MetricObservation(
            key=self.definition.key,
            version=self.definition.version,
            numeric_value=value,
            unit=self.definition.unit,
            source=self.definition.source,
            observed_count=observed,
            eligible_count=eligible,
            coverage=_coverage(observed, eligible),
            confidence=(
                1.0
                if context.session.events_complete and value is not None
                else None
            ),
        )


EventRateKind = Literal["unknown_kind", "direct_event_timestamp"]


@dataclass(frozen=True, slots=True)
class ObservedEventRateCalculator:
    """Rate over safe events, separate from observation completeness."""

    definition: MetricDefinition
    rate_kind: EventRateKind
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        events = cast(EventGroups, features[EVENT_GROUPS_FEATURE]).all_events
        eligible = len(events)
        matching = sum(
            (
                event.kind is EventKind.UNKNOWN
                if self.rate_kind == "unknown_kind"
                else event.time_basis is EventTimeBasis.PROVIDER_REPORTED
            )
            for event in events
        )
        value = None if eligible == 0 else matching / eligible
        return MetricObservation(
            key=self.definition.key,
            version=self.definition.version,
            numeric_value=value,
            unit=self.definition.unit,
            source=self.definition.source,
            observed_count=eligible,
            eligible_count=eligible,
            coverage=1.0 if eligible else 0.0,
            confidence=(
                1.0
                if context.session.events_complete and value is not None
                else None
            ),
        )


UsageAttribute = Literal[
    "input_tokens",
    "cached_input_tokens",
    "cache_creation_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
]


@dataclass(frozen=True, slots=True)
class UsageCalculator:
    definition: MetricDefinition
    attribute: UsageAttribute
    required_features: frozenset[str] = frozenset({EVENT_GROUPS_FEATURE})
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        groups = cast(EventGroups, features[EVENT_GROUPS_FEATURE])
        additive_events = tuple(
            event
            for event in groups.usage_events
            if event.usage is not None
            and event.usage.counter_kind is UsageCounterKind.DELTA
        )
        eligible_events = tuple(
            event
            for event in groups.usage_events
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
        finalized_turn_count = sum(
            event.kind is EventKind.TURN_END for event in groups.all_events
        )
        observations = tuple(
            (getattr(event.usage, self.attribute), event.usage.provider_reported)
            for event in additive_events
            if event.usage is not None
            and getattr(event.usage, self.attribute) is not None
        )
        values = tuple(value for value, _ in observations)
        source = (
            MetricSource.ESTIMATED
            if any(not provider_reported for _, provider_reported in observations)
            else MetricSource.PROVIDER_REPORTED
        )
        return _numeric(
            self.definition,
            sum(values) if values else None,
            len(values),
            max(finalized_turn_count, len(turn_eligible_events))
            + len(other_eligible_events),
            allow_full_confidence=context.session.events_complete,
            source=source,
        )


DETERMINISTIC_CALCULATORS = (
    SessionStateCalculator(),
    CycleTimeCalculator(),
    CompleteCountCalculator(EVENT_COUNT_DEFINITION),
    CompleteCountCalculator(PLAN_EVENT_COUNT_DEFINITION, kind=EventKind.PLAN),
    CompleteCountCalculator(COMPACTION_COUNT_DEFINITION, kind=EventKind.COMPACTION),
    CompleteCountCalculator(TOOL_EVENT_COUNT_DEFINITION, collection="tool_events"),
    RateCalculator(TOOL_SUCCESS_RATE_DEFINITION, "tool_events"),
    CompleteCountCalculator(
        VERIFICATION_COUNT_DEFINITION, collection="verification_events"
    ),
    RateCalculator(VERIFICATION_PASS_RATE_DEFINITION, "verification_events"),
    ObservedTurnDurationCalculator(),
    ObservedToolDurationCalculator(),
    CompleteCountCalculator(FINALIZED_TURN_COUNT_DEFINITION, kind=EventKind.TURN_END),
    DataCoverageCalculator(TURN_USAGE_COVERAGE_DEFINITION, "turn_usage"),
    DataCoverageCalculator(TURN_DURATION_COVERAGE_DEFINITION, "turn_duration"),
    DataCoverageCalculator(TOOL_RESULT_COVERAGE_DEFINITION, "tool_result"),
    DataCoverageCalculator(TOOL_DURATION_COVERAGE_DEFINITION, "tool_duration"),
    ObservedEventRateCalculator(UNKNOWN_EVENT_KIND_RATE_DEFINITION, "unknown_kind"),
    ObservedEventRateCalculator(
        DIRECT_EVENT_TIMESTAMP_RATE_DEFINITION, "direct_event_timestamp"
    ),
    UsageCalculator(INPUT_TOKENS_DEFINITION, "input_tokens"),
    UsageCalculator(CACHED_INPUT_TOKENS_DEFINITION, "cached_input_tokens"),
    UsageCalculator(CACHE_CREATION_TOKENS_DEFINITION, "cache_creation_tokens"),
    UsageCalculator(OUTPUT_TOKENS_DEFINITION, "output_tokens"),
    UsageCalculator(
        REASONING_OUTPUT_TOKENS_DEFINITION, "reasoning_output_tokens"
    ),
    UsageCalculator(TOTAL_TOKENS_DEFINITION, "total_tokens"),
)

DETERMINISTIC_FEATURE_EXTRACTORS = (
    EventGroupsExtractor(),
    KnownDurationsExtractor(),
)

DEFAULT_METRIC_PACK = MetricPack(
    key=DEFAULT_METRIC_PACK_KEY,
    version=4,
    metric_keys=tuple(
        calculator.definition.key for calculator in DETERMINISTIC_CALCULATORS
    ),
)

DEFAULT_ANALYSIS_REGISTRY = TrustedAnalysisRegistry(
    calculators=DETERMINISTIC_CALCULATORS,
    feature_extractors=DETERMINISTIC_FEATURE_EXTRACTORS,
    packs=(DEFAULT_METRIC_PACK,),
)
DEFAULT_METRIC_ENGINE = MetricEngine(DEFAULT_ANALYSIS_REGISTRY)
