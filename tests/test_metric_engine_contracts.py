from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from prompt_enhancer.application.analysis import (
    MetricContractError,
    MetricDefinition,
    MetricEngine,
    MetricPack,
    PrivacyTierDeniedError,
    TrustedAnalysisRegistry,
)
from prompt_enhancer.application.analysis.contracts import AnalysisContext, FeatureSet
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
    SafeSession,
    SessionState,
)


def _session() -> SafeSession:
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="a" * 64,
        project_id="b" * 64,
        session_id="c" * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=datetime(2026, 4, 1, tzinfo=UTC),
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )


def _definition(key: str) -> MetricDefinition:
    return MetricDefinition(
        key=key,
        version=1,
        dimension="workflow",
        display_name="Synthetic metric",
        description="Content-free metric-engine contract fixture.",
        unit="count",
    )


@dataclass(frozen=True)
class _RecordingExtractor:
    key: str
    order: list[str]
    required_features: frozenset[str] = frozenset()
    required_tier: DataTier = DataTier.METADATA

    def extract(self, context: AnalysisContext, features: FeatureSet) -> object:
        self.order.append(self.key)
        return len(self.order)


@dataclass(frozen=True)
class _FeatureCalculator:
    definition: MetricDefinition
    required_features: frozenset[str]
    access_feature: str | None = None
    result_key: str | None = None
    required_tier: DataTier = DataTier.METADATA

    def calculate(
        self, context: AnalysisContext, features: FeatureSet
    ) -> MetricObservation:
        if self.access_feature is not None:
            features[self.access_feature]
        return MetricObservation(
            key=self.definition.key if self.result_key is None else self.result_key,
            version=self.definition.version,
            numeric_value=1,
            unit=self.definition.unit,
            source=MetricSource.DETERMINISTIC,
            observed_count=1,
            eligible_count=1,
            coverage=1,
            confidence=1,
        )


def _engine(
    calculators: tuple[_FeatureCalculator, ...],
    extractors: tuple[_RecordingExtractor, ...],
) -> MetricEngine:
    pack = MetricPack(
        "contract-test",
        1,
        tuple(calculator.definition.key for calculator in calculators),
    )
    return MetricEngine(
        TrustedAnalysisRegistry(
            calculators=calculators,
            feature_extractors=extractors,
            packs=(pack,),
        )
    )


def test_feature_dag_execution_is_deterministic_and_shared_features_are_cached() -> None:
    order: list[str] = []
    extractors = (
        _RecordingExtractor("metadata.base", order),
        _RecordingExtractor(
            "metadata.left", order, frozenset({"metadata.base"})
        ),
        _RecordingExtractor(
            "metadata.right", order, frozenset({"metadata.base"})
        ),
    )
    calculator = _FeatureCalculator(
        _definition("workflow.composed"),
        frozenset({"metadata.right", "metadata.left"}),
    )

    _engine((calculator,), extractors).compute_session(
        _session(), (), pack_key="contract-test"
    )

    assert order == ["metadata.base", "metadata.left", "metadata.right"]


def test_calculator_cannot_read_an_undeclared_precomputed_feature() -> None:
    order: list[str] = []
    first = _FeatureCalculator(
        _definition("workflow.first"),
        frozenset({"metadata.first"}),
        access_feature="metadata.second",
    )
    second = _FeatureCalculator(
        _definition("workflow.second"),
        frozenset({"metadata.second"}),
    )
    engine = _engine(
        (first, second),
        (
            _RecordingExtractor("metadata.first", order),
            _RecordingExtractor("metadata.second", order),
        ),
    )

    with pytest.raises(KeyError):
        engine.compute_session(_session(), (), pack_key="contract-test")


def test_calculator_result_must_match_registered_definition() -> None:
    calculator = _FeatureCalculator(
        _definition("workflow.registered"),
        frozenset(),
        result_key="workflow.different",
    )

    with pytest.raises(MetricContractError, match="outside its definition"):
        _engine((calculator,), ()).compute_session(
            _session(), (), pack_key="contract-test"
        )


def test_restricted_feature_is_gated_before_extraction() -> None:
    order: list[str] = []
    extractor = _RecordingExtractor(
        "redacted.example",
        order,
        required_tier=DataTier.REDACTED_CONTENT,
    )
    calculator = _FeatureCalculator(
        _definition("workflow.restricted"),
        frozenset({extractor.key}),
    )

    with pytest.raises(PrivacyTierDeniedError, match="unavailable data tier"):
        _engine((calculator,), (extractor,)).compute_session(
            _session(),
            (),
            pack_key="contract-test",
            allowed_tiers=frozenset({DataTier.METADATA}),
        )
    assert order == []
