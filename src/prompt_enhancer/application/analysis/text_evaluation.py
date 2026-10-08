"""Content-free reports for the checked-in synthetic P1 baseline corpus.

The evaluator measures deterministic fixture agreement only.  It is not an EN/PL
calibration result and must not be presented as accuracy on private conversations.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import Field, field_validator, model_validator

from ...domain import DataTier, SAFE_VERSION_PATTERN, StrictModel
from ..persistence import MetricValueState
from .text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    TEXT_METRIC_DEFINITIONS,
    TextMetricEngine,
)
from .text_contracts import P1LocalAnalysisGrant, P1TextAnalysisInput


class SyntheticMetricExpectation(StrictModel):
    metric_key: str
    value_state: MetricValueState
    numeric_value: float | None = Field(default=None, ge=0, le=1)

    @field_validator("metric_key")
    @classmethod
    def safe_metric_key(cls, value: str) -> str:
        if not SAFE_VERSION_PATTERN.fullmatch(value):
            raise ValueError("synthetic expectation keys must be safe")
        return value

    @model_validator(mode="after")
    def state_matches_value(self) -> SyntheticMetricExpectation:
        if (self.value_state is MetricValueState.KNOWN) != (
            self.numeric_value is not None
        ):
            raise ValueError("only known synthetic expectations contain values")
        return self


class SyntheticTextEvaluationCase(StrictModel):
    case_id: str
    analysis_input: P1TextAnalysisInput = Field(repr=False)
    expectations: tuple[SyntheticMetricExpectation, ...]

    @field_validator("case_id")
    @classmethod
    def safe_case_id(cls, value: str) -> str:
        if not SAFE_VERSION_PATTERN.fullmatch(value):
            raise ValueError("synthetic case identifiers must be safe")
        return value

    @model_validator(mode="after")
    def complete_expectations(self) -> SyntheticTextEvaluationCase:
        expected_keys = tuple(definition.key for definition in TEXT_METRIC_DEFINITIONS)
        actual_keys = tuple(item.metric_key for item in self.expectations)
        if actual_keys != expected_keys:
            raise ValueError(
                "synthetic expectations must match the registered metric order"
            )
        return self


class SyntheticMetricEvaluation(StrictModel):
    metric_key: str
    case_count: int = Field(ge=1)
    state_match_count: int = Field(ge=0)
    numeric_match_count: int = Field(ge=0)
    known_true_positive: int = Field(ge=0)
    known_false_positive: int = Field(ge=0)
    known_true_negative: int = Field(ge=0)
    known_false_negative: int = Field(ge=0)
    known_state_precision: float | None = Field(default=None, ge=0, le=1)
    known_state_recall: float | None = Field(default=None, ge=0, le=1)
    mean_absolute_error: float | None = Field(default=None, ge=0)


class SyntheticEvaluationReport(StrictModel):
    corpus_schema_version: int = Field(ge=1)
    case_count: int = Field(ge=1)
    metric_summaries: tuple[SyntheticMetricEvaluation, ...]
    interpretation_code: str = "synthetic_functional_agreement_only"


def evaluate_synthetic_text_cases(
    cases: tuple[SyntheticTextEvaluationCase, ...],
    *,
    engine: TextMetricEngine = DEFAULT_TEXT_METRIC_ENGINE,
    corpus_schema_version: int = 1,
    tolerance: float = 1e-9,
) -> SyntheticEvaluationReport:
    """Evaluate state and numeric agreement without retaining fixture content."""

    if not cases:
        raise ValueError("synthetic evaluation requires at least one case")
    if tolerance < 0:
        raise ValueError("synthetic evaluation tolerance cannot be negative")

    rows: dict[str, list[tuple[MetricValueState, float | None, MetricValueState, float | None]]] = defaultdict(list)
    for case in cases:
        context = case.analysis_input
        grant = P1LocalAnalysisGrant(
            provider=context.provider,
            session_id=context.session_id,
            analysis_window_fingerprint=context.analysis_window_fingerprint,
            data_tier=DataTier.REDACTED_CONTENT,
            consent_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        actual = engine.compute(context, grant)
        for expectation, result in zip(case.expectations, actual, strict=True):
            rows[expectation.metric_key].append(
                (
                    expectation.value_state,
                    expectation.numeric_value,
                    result.value_state,
                    result.observation.numeric_value,
                )
            )

    summaries: list[SyntheticMetricEvaluation] = []
    for definition in TEXT_METRIC_DEFINITIONS:
        samples = rows[definition.key]
        state_matches = sum(expected == actual for expected, _, actual, _ in samples)
        numeric_matches = sum(
            expected_value is not None
            and actual_value is not None
            and abs(expected_value - actual_value) <= tolerance
            for _, expected_value, _, actual_value in samples
        )
        tp = sum(
            expected is MetricValueState.KNOWN
            and actual is MetricValueState.KNOWN
            for expected, _, actual, _ in samples
        )
        fp = sum(
            expected is not MetricValueState.KNOWN
            and actual is MetricValueState.KNOWN
            for expected, _, actual, _ in samples
        )
        tn = sum(
            expected is not MetricValueState.KNOWN
            and actual is not MetricValueState.KNOWN
            for expected, _, actual, _ in samples
        )
        fn = sum(
            expected is MetricValueState.KNOWN
            and actual is not MetricValueState.KNOWN
            for expected, _, actual, _ in samples
        )
        errors = tuple(
            abs(expected_value - actual_value)
            for _, expected_value, _, actual_value in samples
            if expected_value is not None and actual_value is not None
        )
        summaries.append(
            SyntheticMetricEvaluation(
                metric_key=definition.key,
                case_count=len(samples),
                state_match_count=state_matches,
                numeric_match_count=numeric_matches,
                known_true_positive=tp,
                known_false_positive=fp,
                known_true_negative=tn,
                known_false_negative=fn,
                known_state_precision=(None if tp + fp == 0 else tp / (tp + fp)),
                known_state_recall=(None if tp + fn == 0 else tp / (tp + fn)),
                mean_absolute_error=(None if not errors else sum(errors) / len(errors)),
            )
        )
    return SyntheticEvaluationReport(
        corpus_schema_version=corpus_schema_version,
        case_count=len(cases),
        metric_summaries=tuple(summaries),
    )
