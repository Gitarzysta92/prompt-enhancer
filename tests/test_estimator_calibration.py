from __future__ import annotations

from dataclasses import replace
import math

import pytest

from prompt_enhancer.application.estimators.calibration import (
    ActivationGateEvidence,
    AgreementObservation,
    CalibrationSliceDimensions,
    CalibrationTaskStratum,
    CascadeObservation,
    CheckOutcome,
    ClassificationObservation,
    EvaluationState,
    EvidenceAvailability,
    GateOutcome,
    PerturbationStabilityObservation,
    REQUIRED_CALIBRATION_STRATA,
    RepeatObservation,
    RetrievalObservation,
    RunTelemetry,
    SlicedClassificationObservation,
    StabilityCondition,
    SubgroupDelta,
    TruthSource,
    evaluate_activation_gate,
    evaluate_cascade,
    evaluate_classification,
    evaluate_classification_slices,
    evaluate_repeat_stability,
    evaluate_retrieval,
    evaluate_stability_suite,
    human_human_agreement,
    model_human_agreement,
    summarize_telemetry,
)


def _binary_observation(
    truth: str,
    prediction: str,
    positive_probability: float,
) -> ClassificationObservation:
    return ClassificationObservation(
        truth=truth,
        prediction=prediction,
        truth_source=TruthSource.HUMAN_ADJUDICATED,
        probabilities=(
            ("negative", 1.0 - positive_probability),
            ("positive", positive_probability),
        ),
    )


def test_classification_reports_confusion_calibration_and_selective_risk() -> None:
    report = evaluate_classification(
        (
            _binary_observation("negative", "negative", 0.2),
            _binary_observation("negative", "positive", 0.9),
            _binary_observation("positive", "positive", 0.8),
            _binary_observation("positive", "negative", 0.4),
        ),
        reliability_bins=5,
        false_confidence_threshold=0.85,
        selective_thresholds=(0.0, 0.85, 0.95),
    )

    assert report.state is EvaluationState.READY
    assert report.labels == ("negative", "positive")
    assert report.confusion_matrix == ((1, 1), (1, 1))
    assert report.accuracy.value == pytest.approx(0.5)
    assert report.macro_precision.value == pytest.approx(0.5)
    assert report.macro_recall.value == pytest.approx(0.5)
    assert report.macro_f1.value == pytest.approx(0.5)
    assert report.brier_score.value == pytest.approx(0.625)
    assert report.log_loss.value == pytest.approx(
        -(math.log(0.8) + math.log(0.1) + math.log(0.8) + math.log(0.4)) / 4
    )
    assert report.expected_calibration_error.value == pytest.approx(0.275)
    assert sum(item.count for item in report.reliability) == 4
    assert report.false_confident_errors.numerator == 1
    assert report.false_confident_errors.denominator == 4
    assert report.selective_risk[1].coverage.value == pytest.approx(0.25)
    assert report.selective_risk[1].risk.value == pytest.approx(1.0)
    assert report.selective_risk[2].coverage.value == pytest.approx(0.0)
    assert report.selective_risk[2].risk.state is EvaluationState.INSUFFICIENT_DATA
    assert report.calibration_slope.state is EvaluationState.INSUFFICIENT_DATA
    assert report.calibration_slope.reason == "too_few_cases"


def test_macro_metrics_keep_unpredicted_and_reference_absent_classes() -> None:
    report = evaluate_classification(
        (
            ClassificationObservation(
                truth="alpha",
                prediction="beta",
                truth_source=TruthSource.OBJECTIVE_CHECK,
            ),
        )
    )

    assert report.labels == ("alpha", "beta")
    assert report.macro_precision.value == 0.0
    assert report.macro_recall.value == 0.0
    assert report.macro_f1.value == 0.0
    assert all(item.precision == 0.0 or item.recall == 0.0 for item in report.per_class)
    assert report.brier_score.state is EvaluationState.INSUFFICIENT_DATA
    assert report.brier_score.reason == "probabilities_missing"


def test_binary_calibration_slope_uses_only_probability_receipts() -> None:
    probability_cases: list[ClassificationObservation] = []
    for probability, positive_count in ((0.2, 2), (0.4, 4), (0.6, 6), (0.8, 8)):
        prediction = "positive" if probability >= 0.5 else "negative"
        probability_cases.extend(
            _binary_observation("positive", prediction, probability)
            for _ in range(positive_count)
        )
        probability_cases.extend(
            _binary_observation("negative", prediction, probability)
            for _ in range(10 - positive_count)
        )
    cases = (
        *probability_cases,
        ClassificationObservation(
            truth="negative",
            prediction="negative",
            truth_source=TruthSource.OBJECTIVE_CHECK,
        ),
    )

    report = evaluate_classification(cases, slope_minimum_cases=10)

    assert report.sample_count == 41
    assert report.probability_sample_count == 40
    assert report.calibration_slope.state is EvaluationState.READY
    assert report.calibration_slope.sample_count == 40
    assert report.calibration_slope.intercept == pytest.approx(0.0, abs=1e-8)
    assert report.calibration_slope.slope == pytest.approx(1.0, abs=1e-8)


def test_classification_missing_and_invalid_probability_inputs_are_explicit() -> None:
    empty = evaluate_classification(())
    assert empty.state is EvaluationState.INSUFFICIENT_DATA
    assert empty.reason == "no_cases"
    assert empty.accuracy.value is None
    assert empty.expected_calibration_error.value is None

    with pytest.raises(ValueError, match="sum to one"):
        ClassificationObservation(
            truth="negative",
            prediction="negative",
            truth_source=TruthSource.OBJECTIVE_CHECK,
            probabilities=(("negative", 0.7), ("positive", 0.2)),
        )
    with pytest.raises(ValueError, match="include truth and prediction"):
        ClassificationObservation(
            truth="negative",
            prediction="negative",
            truth_source=TruthSource.OBJECTIVE_CHECK,
            probabilities=(("other", 1.0),),
        )
    with pytest.raises(ValueError, match="unique and increasing"):
        evaluate_classification(
            (_binary_observation("negative", "negative", 0.2),),
            selective_thresholds=(0.9, 0.5),
        )


def _sliced_case(
    case_key: str,
    task: CalibrationTaskStratum,
    *,
    language: str,
    provider: str,
    project: str,
    period: str,
    availability: EvidenceAvailability,
) -> SlicedClassificationObservation:
    return SlicedClassificationObservation(
        case_key=case_key,
        classification=_binary_observation("positive", "positive", 0.8),
        dimensions=CalibrationSliceDimensions(
            task_stratum=task,
            language=language,
            provider=provider,
            project_bucket=project,
            time_bucket=period,
            evidence_availability=availability,
        ),
    )


def _four_strata_cases() -> tuple[SlicedClassificationObservation, ...]:
    return (
        _sliced_case(
            "case-a",
            CalibrationTaskStratum.BUG_FIX,
            language="en",
            provider="provider-a",
            project="project-a",
            period="period-a",
            availability=EvidenceAvailability.AVAILABLE,
        ),
        _sliced_case(
            "case-b",
            CalibrationTaskStratum.FEATURE,
            language="pl",
            provider="provider-a",
            project="project-a",
            period="period-a",
            availability=EvidenceAvailability.PARTIAL,
        ),
        _sliced_case(
            "case-c",
            CalibrationTaskStratum.CODE_REVIEW,
            language="en",
            provider="provider-b",
            project="project-b",
            period="period-b",
            availability=EvidenceAvailability.AVAILABLE,
        ),
        _sliced_case(
            "case-d",
            CalibrationTaskStratum.RESEARCH_DESIGN,
            language="pl",
            provider="provider-b",
            project="project-b",
            period="period-b",
            availability=EvidenceAvailability.UNAVAILABLE,
        ),
    )


def test_classification_slices_cover_four_strata_and_required_dimensions() -> None:
    report = evaluate_classification_slices(_four_strata_cases())

    assert report.state is EvaluationState.READY
    assert report.strata_present == REQUIRED_CALIBRATION_STRATA
    assert report.missing_strata == ()
    assert report.get("task", "bug_fix").sample_count == 1
    assert report.get("language", "en").sample_count == 2
    assert report.get("provider", "provider-a").sample_count == 2
    assert report.get("project", "project-b").sample_count == 2
    assert report.get("time", "period-a").sample_count == 2
    assert report.get("evidence_availability", "partial").sample_count == 1


def test_classification_slices_do_not_hide_small_or_missing_strata() -> None:
    cases = _four_strata_cases()[:-1]
    report = evaluate_classification_slices(cases, minimum_cases_per_slice=2)

    assert report.missing_strata == (CalibrationTaskStratum.RESEARCH_DESIGN,)
    bug_fix = report.get("task", "bug_fix")
    assert bug_fix.state is EvaluationState.INSUFFICIENT_DATA
    assert bug_fix.report is None
    assert bug_fix.reason == "too_few_cases"
    assert report.get("language", "en").state is EvaluationState.READY

    with pytest.raises(ValueError, match="unique"):
        evaluate_classification_slices((cases[0], cases[0]))

    all_small = evaluate_classification_slices(cases, minimum_cases_per_slice=4)
    assert all_small.state is EvaluationState.INSUFFICIENT_DATA
    assert all_small.reason == "all_slices_too_small"


def test_retrieval_reports_recall_mrr_ndcg_and_link_precision() -> None:
    report = evaluate_retrieval(
        (
            RetrievalObservation(
                case_key="case-a",
                relevant_ids=("evidence-a", "evidence-b"),
                ranked_ids=("evidence-a", "distractor-a", "evidence-b"),
                linked_ids=("evidence-a", "distractor-a"),
            ),
            RetrievalObservation(
                case_key="case-b",
                relevant_ids=("evidence-c",),
                ranked_ids=("distractor-b", "evidence-c"),
                linked_ids=("evidence-c",),
            ),
            RetrievalObservation(
                case_key="case-unjudged",
                relevant_ids=(),
                ranked_ids=("distractor-c",),
                linked_ids=("distractor-c",),
                judgment_available=False,
            ),
        ),
        ks=(1, 3),
    )

    assert report.state is EvaluationState.READY
    assert report.case_count == 3
    assert report.judged_case_count == 2
    assert report.eligible_case_count == 2
    assert report.at_k[0].recall.value == pytest.approx(0.25)
    assert report.at_k[0].ndcg.value == pytest.approx(0.5)
    assert report.at_k[1].recall.value == pytest.approx(1.0)
    assert report.mean_reciprocal_rank.value == pytest.approx(0.75)
    assert report.link_precision.numerator == 2
    assert report.link_precision.denominator == 3


def test_retrieval_separates_zero_relevance_from_unjudged_cases() -> None:
    report = evaluate_retrieval(
        (
            RetrievalObservation(
                case_key="case-zero",
                relevant_ids=(),
                ranked_ids=("evidence-a",),
            ),
            RetrievalObservation(
                case_key="case-unknown",
                relevant_ids=(),
                ranked_ids=("evidence-b",),
                judgment_available=False,
            ),
        )
    )
    assert report.state is EvaluationState.INSUFFICIENT_DATA
    assert report.reason == "no_positive_relevance_cases"
    assert report.judged_case_count == 1
    assert report.zero_relevant_case_count == 1

    with pytest.raises(ValueError, match="cannot carry"):
        RetrievalObservation(
            case_key="case-invalid",
            relevant_ids=("evidence-a",),
            ranked_ids=("evidence-a",),
            judgment_available=False,
        )

    duplicate = RetrievalObservation(
        case_key="case-duplicate",
        relevant_ids=("evidence-a",),
        ranked_ids=("evidence-a",),
    )
    with pytest.raises(ValueError, match="unique"):
        evaluate_retrieval((duplicate, duplicate))


def test_agreement_and_repeat_stability_preserve_denominators() -> None:
    pairs = (
        AgreementObservation("alpha", "alpha"),
        AgreementObservation("alpha", "beta"),
        AgreementObservation("beta", "beta"),
        AgreementObservation("beta", "beta"),
    )
    human = human_human_agreement(pairs)
    model = model_human_agreement(pairs)
    assert human.observed_agreement.value == pytest.approx(0.75)
    assert human.cohen_kappa.value == pytest.approx(0.5)
    assert model.kind == "model_human"
    assert model.cohen_kappa.value == human.cohen_kappa.value

    stability = evaluate_repeat_stability(
        (
            RepeatObservation("case-a", ("alpha", "alpha", "alpha")),
            RepeatObservation("case-b", ("alpha", "beta", "alpha")),
            RepeatObservation("case-single", ("alpha",)),
        )
    )
    assert stability.case_count == 2
    assert stability.repeat_pair_count == 6
    assert stability.pairwise_stability.value == pytest.approx(4 / 6)
    assert stability.fully_stable_cases.value == pytest.approx(0.5)


def test_stability_suite_keeps_repeat_order_format_and_injection_separate() -> None:
    report = evaluate_stability_suite(
        (
            PerturbationStabilityObservation(
                "case-repeat", StabilityCondition.REPEAT, "accept", "accept"
            ),
            PerturbationStabilityObservation(
                "case-order", StabilityCondition.ORDER, "accept", "accept"
            ),
            PerturbationStabilityObservation(
                "case-format", StabilityCondition.FORMAT, "accept", "accept"
            ),
            PerturbationStabilityObservation(
                "case-injection", StabilityCondition.INJECTION, "accept", "abstain"
            ),
        )
    )
    by_condition = {item.condition: item for item in report.conditions}
    assert report.state is EvaluationState.READY
    assert report.missing_conditions == ()
    assert by_condition[StabilityCondition.REPEAT].stability.value == 1.0
    assert by_condition[StabilityCondition.INJECTION].stability.value == 0.0

    empty = evaluate_stability_suite(())
    assert empty.state is EvaluationState.INSUFFICIENT_DATA
    assert empty.missing_conditions == tuple(StabilityCondition)


def test_telemetry_summarizes_latency_resources_failures_and_cost() -> None:
    report = summarize_telemetry(
        (
            RunTelemetry(
                latency_ms=100,
                cold=True,
                queue_ms=10,
                throughput_per_second=2,
                peak_ram_mb=100,
                peak_vram_mb=200,
                disk_mb=50,
                energy_wh=1,
                api_cost_usd=0.1,
            ),
            RunTelemetry(
                latency_ms=200,
                cold=False,
                queue_ms=30,
                throughput_per_second=4,
                peak_ram_mb=150,
                peak_vram_mb=250,
                disk_mb=50,
                api_cost_usd=0.2,
                oom=True,
                error=True,
            ),
            RunTelemetry(
                latency_ms=300,
                cold=False,
                queue_ms=20,
                throughput_per_second=6,
                peak_ram_mb=120,
                disk_mb=60,
                energy_wh=2,
                refused=True,
            ),
        )
    )
    assert report.state is EvaluationState.READY
    assert report.distribution("latency_ms").p50 == pytest.approx(200)
    assert report.distribution("latency_ms").p95 == pytest.approx(290)
    assert report.distribution("cold_latency_ms").p50 == pytest.approx(100)
    assert report.distribution("warm_latency_ms").p50 == pytest.approx(250)
    assert report.distribution("energy_wh").total == pytest.approx(3)
    assert report.distribution("api_cost_usd").count == 2
    assert report.distribution("api_cost_usd").total == pytest.approx(0.3)
    assert report.oom_rate.value == pytest.approx(1 / 3)
    assert report.error_rate.value == pytest.approx(1 / 3)
    assert report.refusal_rate.value == pytest.approx(1 / 3)

    empty = summarize_telemetry(())
    assert empty.state is EvaluationState.INSUFFICIENT_DATA
    assert empty.distribution("latency_ms").state is EvaluationState.INSUFFICIENT_DATA

    with pytest.raises(ValueError, match="finite"):
        RunTelemetry(latency_ms=math.inf, cold=True)


def test_cascade_reports_conditional_stop_rate_and_paired_incremental_value() -> None:
    report = evaluate_cascade(
        (
            CascadeObservation(
                case_key="case-a",
                stage_values=(("objective", 0.4), ("retrieval", 0.6), ("specialist", 0.8)),
                stop_stage="specialist",
                value_source=TruthSource.OBJECTIVE_CHECK,
            ),
            CascadeObservation(
                case_key="case-b",
                stage_values=(("objective", 0.7), ("retrieval", 0.75)),
                stop_stage="retrieval",
                value_source=TruthSource.HUMAN_ADJUDICATED,
            ),
            CascadeObservation(
                case_key="case-c",
                stage_values=(("objective", 0.5),),
                stop_stage="objective",
                value_source=TruthSource.INDEPENDENT_HUMAN,
            ),
        ),
        stage_order=("objective", "retrieval", "specialist"),
    )
    by_stage = {item.stage: item for item in report.stages}
    assert by_stage["objective"].stop_rate.value == pytest.approx(1 / 3)
    assert by_stage["objective"].incremental_value.state is EvaluationState.INSUFFICIENT_DATA
    assert by_stage["retrieval"].stop_rate.value == pytest.approx(0.5)
    assert by_stage["retrieval"].incremental_value.value == pytest.approx(0.125)
    assert by_stage["specialist"].incremental_value.value == pytest.approx(0.2)

    with pytest.raises(ValueError, match="contiguous ordered prefix"):
        evaluate_cascade(
            (
                CascadeObservation(
                    case_key="case-invalid",
                    stage_values=(("objective", 0.5), ("specialist", 0.7)),
                    stop_stage="specialist",
                    value_source=TruthSource.OBJECTIVE_CHECK,
                ),
            ),
            stage_order=("objective", "retrieval", "specialist"),
        )


def _activation_evidence() -> ActivationGateEvidence:
    return ActivationGateEvidence(
        candidate_performance=0.90,
        baseline_performance=0.84,
        adjudicated_human_performance=0.94,
        expected_calibration_error=0.05,
        repeat_stability=0.95,
        subgroup_deltas=(SubgroupDelta("language-en", -0.02),),
        holdout_untouched=True,
        human_baseline_adjudicated=True,
        synthetic_only=False,
        truth_sources=frozenset({TruthSource.HUMAN_ADJUDICATED}),
        calibration_strata=frozenset(REQUIRED_CALIBRATION_STRATA),
    )


def test_activation_gate_applies_exact_inclusive_release_thresholds() -> None:
    report = evaluate_activation_gate(_activation_evidence())
    checks = {check.key: check for check in report.checks}

    assert report.outcome is GateOutcome.ELIGIBLE
    assert all(check.outcome is CheckOutcome.PASS for check in report.checks)
    assert checks["ece"].actual == 0.05
    assert checks["repeat_stability"].actual == 0.95
    assert checks["subgroup_regression"].actual == -0.02
    assert checks["calibration_strata"].actual is True


@pytest.mark.parametrize(
    ("updates", "failed_check"),
    (
        ({"candidate_performance": 0.84, "baseline_performance": 0.84}, "beats_baseline"),
        (
            {"candidate_performance": 0.99, "adjudicated_human_performance": 0.90},
            "within_human_baseline",
        ),
        ({"expected_calibration_error": 0.051}, "ece"),
        ({"repeat_stability": 0.949}, "repeat_stability"),
        ({"subgroup_deltas": (SubgroupDelta("language-en", -0.021),)}, "subgroup_regression"),
        ({"synthetic_only": True}, "representative_private_holdout"),
        (
            {"calibration_strata": frozenset({CalibrationTaskStratum.BUG_FIX})},
            "calibration_strata",
        ),
    ),
)
def test_activation_gate_rejects_any_failed_release_condition(
    updates: dict[str, object],
    failed_check: str,
) -> None:
    report = evaluate_activation_gate(replace(_activation_evidence(), **updates))
    checks = {check.key: check for check in report.checks}
    assert report.outcome is GateOutcome.REJECTED
    assert checks[failed_check].outcome is CheckOutcome.FAIL


def test_activation_gate_never_turns_missing_evidence_into_a_pass() -> None:
    evidence = ActivationGateEvidence(
        candidate_performance=None,
        baseline_performance=None,
        adjudicated_human_performance=None,
        expected_calibration_error=None,
        repeat_stability=None,
        subgroup_deltas=None,
        holdout_untouched=None,
        human_baseline_adjudicated=None,
        synthetic_only=None,
        truth_sources=frozenset(),
        calibration_strata=None,
    )
    report = evaluate_activation_gate(evidence)

    assert report.outcome is GateOutcome.INSUFFICIENT_DATA
    assert all(check.outcome is CheckOutcome.INSUFFICIENT_DATA for check in report.checks)
    assert all(check.actual is None for check in report.checks)

    partial = replace(_activation_evidence(), subgroup_deltas=())
    partial_report = evaluate_activation_gate(partial)
    assert partial_report.outcome is GateOutcome.INSUFFICIENT_DATA
    subgroup = next(
        check for check in partial_report.checks if check.key == "subgroup_regression"
    )
    assert subgroup.reason == "subgroup_evaluation_missing"
