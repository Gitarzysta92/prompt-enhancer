from __future__ import annotations

import json
from pathlib import Path

from prompt_enhancer.application.analysis.text_evaluation import (
    SyntheticTextEvaluationCase,
    evaluate_synthetic_text_cases,
)
from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
)
from prompt_enhancer.application.analysis.text_contracts import P1LocalAnalysisGrant
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.domain import DataTier


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "text_metrics"
    / "bilingual_cases.json"
)


def _cases() -> tuple[int, tuple[SyntheticTextEvaluationCase, ...]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload["corpus_schema_version"], tuple(
        SyntheticTextEvaluationCase.model_validate(case)
        for case in payload["cases"]
    )


def test_checked_in_bilingual_corpus_matches_deterministic_golden_values() -> None:
    schema_version, cases = _cases()

    report = evaluate_synthetic_text_cases(
        cases,
        corpus_schema_version=schema_version,
    )

    assert report.case_count == 3
    assert report.interpretation_code == "synthetic_functional_agreement_only"
    assert all(
        summary.state_match_count == summary.case_count
        for summary in report.metric_summaries
    )
    assert all(
        summary.mean_absolute_error in {None, 0.0}
        for summary in report.metric_summaries
    )
    assert all(
        summary.known_false_positive == 0
        and summary.known_false_negative == 0
        for summary in report.metric_summaries
    )
    assert all(
        summary.known_state_precision in {None, 1.0}
        and summary.known_state_recall in {None, 1.0}
        for summary in report.metric_summaries
    )


def test_evaluation_report_contains_no_synthetic_transcript_content() -> None:
    schema_version, cases = _cases()
    report = evaluate_synthetic_text_cases(
        cases,
        corpus_schema_version=schema_version,
    )

    rendered = report.model_dump_json()
    for canary in ("dashboard PNG", "Stwórz panel", "Created PNG report"):
        assert canary not in rendered


def test_ratio_and_window_coverage_properties_hold_for_every_corpus_case() -> None:
    _, cases = _cases()

    for case in cases:
        context = case.analysis_input
        results = DEFAULT_TEXT_METRIC_ENGINE.compute(
            context,
            P1LocalAnalysisGrant(
                provider=context.provider,
                session_id=context.session_id,
                analysis_window_fingerprint=context.analysis_window_fingerprint,
                data_tier=DataTier.REDACTED_CONTENT,
                consent_active=True,
            ),
        )
        for result in results:
            assert result.observation.coverage == (
                context.observed_message_count / context.eligible_message_count
            )
            if result.value_state is MetricValueState.KNOWN:
                assert result.fraction is not None
                assert result.observation.numeric_value == (
                    result.fraction.numerator / result.fraction.denominator
                )
                assert 0 <= result.observation.numeric_value <= 1
            else:
                assert result.fraction is None
                assert result.observation.numeric_value is None
