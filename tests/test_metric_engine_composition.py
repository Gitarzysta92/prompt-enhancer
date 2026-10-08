from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis import (
    DEFAULT_METRIC_ENGINE,
    DEFAULT_METRIC_PACK_KEY,
    DependencyCycleError,
    DuplicateMetricDefinitionError,
    MetricDefinition,
    MetricEngine,
    MetricPack,
    MissingDependencyError,
    PrivacyTierDeniedError,
    TrustedAnalysisRegistry,
)
from prompt_enhancer.application.analysis.contracts import AnalysisContext, FeatureSet
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    MetricObservation,
    MetricSource,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    ToolCategory,
    UsageRecord,
    UsageCounterKind,
)
from prompt_enhancer.metrics import compute_session_metrics


BASE_TIME = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _session(
    *,
    ended: bool = True,
    state: SessionState = SessionState.COMPLETED,
    events_complete: bool = True,
) -> SafeSession:
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="a" * 64,
        project_id="b" * 64,
        session_id="c" * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(minutes=1) if ended else None,
        terminal_state=state,
        events_complete=events_complete,
    )


def _event(
    suffix: str,
    kind: EventKind,
    sequence: int,
    *,
    duration_ms: int | None = None,
    success: bool | None = None,
    usage: UsageRecord | None = None,
) -> SafeEvent:
    return SafeEvent(
        session_id="c" * 64,
        event_id=suffix * 64,
        kind=kind,
        sequence=sequence,
        occurred_at=BASE_TIME + timedelta(seconds=sequence),
        duration_ms=duration_ms,
        success=success,
        tool_category=(
            ToolCategory.TEST
            if kind in {EventKind.TOOL_END, EventKind.VERIFICATION}
            else None
        ),
        usage=usage,
    )


@dataclass(frozen=True)
class _StaticExtractor:
    key: str
    required_features: frozenset[str] = frozenset()
    required_tier: DataTier = DataTier.METADATA

    def extract(self, context: AnalysisContext, features: FeatureSet) -> object:
        return 1


@dataclass(frozen=True)
class _StaticCalculator:
    definition: MetricDefinition
    required_features: frozenset[str] = frozenset()
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        return MetricObservation(
            key=self.definition.key,
            version=self.definition.version,
            numeric_value=1,
            unit=self.definition.unit,
            source=MetricSource.DETERMINISTIC,
            observed_count=1,
            eligible_count=1,
            coverage=1,
            confidence=1,
        )


def _definition(key: str = "workflow.example") -> MetricDefinition:
    return MetricDefinition(
        key=key,
        version=1,
        dimension="workflow",
        display_name="Example",
        description="Synthetic registry test metric.",
        unit="count",
    )


def test_registry_rejects_duplicate_metric_definitions() -> None:
    calculator = _StaticCalculator(_definition())
    with pytest.raises(DuplicateMetricDefinitionError, match="duplicate metric"):
        TrustedAnalysisRegistry(
            calculators=(calculator, calculator),
            feature_extractors=(),
            packs=(),
        )


def test_registry_rejects_missing_feature_dependencies() -> None:
    calculator = _StaticCalculator(
        _definition(), required_features=frozenset({"metadata.missing"})
    )
    with pytest.raises(MissingDependencyError, match="unregistered feature"):
        TrustedAnalysisRegistry(
            calculators=(calculator,),
            feature_extractors=(),
            packs=(),
        )


def test_registry_rejects_feature_dependency_cycles() -> None:
    with pytest.raises(DependencyCycleError, match="cycle"):
        TrustedAnalysisRegistry(
            calculators=(),
            feature_extractors=(
                _StaticExtractor("metadata.first", frozenset({"metadata.second"})),
                _StaticExtractor("metadata.second", frozenset({"metadata.first"})),
            ),
            packs=(),
        )


def test_facade_and_composed_engine_have_identical_deterministic_output() -> None:
    events = (
        _event("d", EventKind.PLAN, 0),
        _event("e", EventKind.TOOL_END, 1, duration_ms=15, success=True),
        _event("f", EventKind.VERIFICATION, 2, duration_ms=25, success=False),
        _event(
            "1",
            EventKind.USAGE,
            3,
            usage=UsageRecord(
                input_tokens=10,
                output_tokens=4,
                total_tokens=14,
                provider_reported=True,
                counter_kind=UsageCounterKind.DELTA,
            ),
        ),
    )
    session = _session()

    facade = compute_session_metrics(session, events)
    composed = DEFAULT_METRIC_ENGINE.compute_session(
        session,
        events,
        pack_key=DEFAULT_METRIC_PACK_KEY,
    )

    assert facade == composed
    by_key = {observation.key: observation for observation in composed}
    assert len(composed) == 24
    assert by_key["outcome.session_state"].text_value == "completed"
    assert by_key["efficiency.cycle_time_ms"].numeric_value == 60_000
    assert by_key["workflow.event_count"].numeric_value == 4
    assert by_key["workflow.plan_event_count"].numeric_value == 1
    assert by_key["workflow.compaction_count"].numeric_value == 0
    assert by_key["workflow.tool_event_count"].numeric_value == 1
    assert by_key["reliability.tool_success_rate"].numeric_value == 1
    assert by_key["verification.verification_count"].numeric_value == 1
    assert by_key["verification.pass_rate"].numeric_value == 0
    assert by_key["efficiency.observed_tool_duration_ms"].numeric_value == 40
    assert by_key["usage.input_tokens"].numeric_value == 10
    assert by_key["usage.output_tokens"].numeric_value == 4
    assert by_key["usage.total_tokens"].numeric_value == 14


def test_unknown_values_survive_composed_calculation() -> None:
    events = (
        _event("d", EventKind.TOOL_END, 0, duration_ms=None, success=None),
        _event(
            "e",
            EventKind.USAGE,
            1,
            usage=UsageRecord(total_tokens=None, provider_reported=True),
        ),
    )
    observations = DEFAULT_METRIC_ENGINE.compute_session(
        _session(
            ended=False,
            state=SessionState.UNKNOWN,
            events_complete=False,
        ),
        events,
        pack_key=DEFAULT_METRIC_PACK_KEY,
    )
    metrics = {observation.key: observation for observation in observations}

    for key in (
        "outcome.session_state",
        "efficiency.cycle_time_ms",
        "reliability.tool_success_rate",
        "efficiency.observed_tool_duration_ms",
        "usage.total_tokens",
    ):
        observation = metrics[key]
        assert observation.numeric_value is None
        assert observation.text_value is None
        assert observation.confidence is None

    compactions = metrics["workflow.compaction_count"]
    assert compactions.numeric_value == 0
    assert compactions.coverage == 0
    assert compactions.confidence is None

def test_privacy_tier_gate_fails_before_restricted_calculator_runs() -> None:
    class RestrictedCalculator(_StaticCalculator):
        def calculate(
            self, context: AnalysisContext, features: FeatureSet
        ) -> MetricObservation:
            raise AssertionError("privacy gate must run before calculation")

    calculator = RestrictedCalculator(
        _definition(), required_tier=DataTier.REDACTED_CONTENT
    )
    registry = TrustedAnalysisRegistry(
        calculators=(calculator,),
        feature_extractors=(),
        packs=(MetricPack("restricted", 1, (calculator.definition.key,)),),
    )

    with pytest.raises(PrivacyTierDeniedError, match="unavailable data tier"):
        MetricEngine(registry).compute_session(
            _session(),
            (),
            pack_key="restricted",
            allowed_tiers=frozenset({DataTier.METADATA}),
        )
