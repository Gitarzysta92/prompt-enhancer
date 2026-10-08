from __future__ import annotations

from datetime import timedelta
import hashlib
import json

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators.calibration_report_contracts import (
    CALIBRATION_MEASUREMENT_SPECS,
    FIXED_CALIBRATION_REPORT_DEFINITION,
    CalibrationMeasurementState,
    CalibrationReportScopeV1,
    CalibrationReportState,
    CalibrationScopeDimension,
    UntrustedCalibrationReportV1,
)
from prompt_enhancer.application.estimators.calibration_reporting import (
    UntrustedCalibrationProjectionV1,
    derive_untrusted_calibration_report,
    summarize_untrusted_calibration_report,
)
from prompt_enhancer.application.estimators.evidence_contracts import (
    AttemptTerminalOutcomeV1,
    AttemptTerminalState,
    BlindHumanAdjudicationInputV1,
    BlindHumanJudgmentInputV1,
    CalibrationEvidenceSubmissionV1,
    MeasurementState,
    ResourceUsageProvenanceV1,
)
from prompt_enhancer.application.estimators.contracts import (
    EstimatorPlan,
    MetricQuestionSpec,
    MetricValueKind,
)
from prompt_enhancer.application.estimators.gate_contracts import GatePolicy

from test_estimator_campaign_persistence import _campaign, _plan, _policy
from test_estimator_evidence_persistence import _submission


def _projection(
    *,
    minimum_holdout_per_metric: int | None = None,
    minimum_subgroup_size: int | None = None,
) -> UntrustedCalibrationProjectionV1:
    policy = _policy()
    if minimum_holdout_per_metric is not None or minimum_subgroup_size is not None:
        payload = policy.model_dump(mode="python")
        if minimum_holdout_per_metric is not None:
            payload["minimum_holdout_per_metric"] = minimum_holdout_per_metric
        if minimum_subgroup_size is not None:
            payload["minimum_subgroup_size"] = minimum_subgroup_size
        policy = GatePolicy.model_validate(payload)
    campaign = _campaign(policy=policy)
    submission = _submission(campaign)
    return UntrustedCalibrationProjectionV1(
        campaign=campaign,
        submission=submission,
        source_observed_at=submission.submitted_at + timedelta(seconds=1),
    )


def _report(
    *,
    minimum_holdout_per_metric: int | None = None,
    minimum_subgroup_size: int | None = None,
) -> UntrustedCalibrationReportV1:
    return derive_untrusted_calibration_report(
        _projection(
            minimum_holdout_per_metric=minimum_holdout_per_metric,
            minimum_subgroup_size=minimum_subgroup_size,
        )
    )


def _overall(metric):
    return next(
        item
        for item in metric.scopes
        if item.dimension is CalibrationScopeDimension.OVERALL
    )


def _measurement(metric, key: str):
    overall = _overall(metric)
    return next(
        item
        for item in metric.measurements
        if item.scope_id == overall.scope_id and item.measurement_key == key
    )


def _unreferenced_outcome(submission: CalibrationEvidenceSubmissionV1):
    referenced_attempts = {
        item.attempt_id for item in submission.candidate_projections
    } | {
        trial.attempt_id
        for series in submission.stability_series
        for trial in series.trials
    }
    return next(
        item
        for item in submission.attempt_outcomes
        if item.attempt_id not in referenced_attempts
    )


def _projection_with_submission(
    projection: UntrustedCalibrationProjectionV1,
    submission: CalibrationEvidenceSubmissionV1,
) -> UntrustedCalibrationProjectionV1:
    return UntrustedCalibrationProjectionV1(
        campaign=projection.campaign,
        submission=submission,
        source_observed_at=projection.source_observed_at,
    )


def _numeric_projection() -> UntrustedCalibrationProjectionV1:
    source_plan = _plan(plan_version="reserved-numeric-plan-v1")
    source_question = source_plan.question_specs[0]
    numeric_question = MetricQuestionSpec.model_validate(
        {
            **source_question.model_dump(mode="python"),
            "value_kind": MetricValueKind.CONTINUOUS,
            "unit_code": "score",
            "lower_bound": 0.0,
            "upper_bound": 1.0,
        }
    )
    plan = EstimatorPlan.model_validate(
        {
            **source_plan.model_dump(mode="python"),
            "question_specs": (numeric_question,),
        }
    )
    policy_payload = _policy().model_dump(mode="python")
    policy_payload.update(
        minimum_holdout_per_metric=1,
        minimum_holdout_per_stratum=1,
        minimum_holdout_per_language=1,
        minimum_subgroup_size=1,
    )
    campaign = _campaign(plan=plan, policy=GatePolicy.model_validate(policy_payload))
    source = _submission(campaign)

    def numeric_value(item):
        return type(item).model_validate(
            {
                **item.model_dump(mode="python"),
                "value_kind": MetricValueKind.CONTINUOUS,
                "numeric_value": 0.75,
                "label_code": None,
            }
        )

    estimates = tuple(numeric_value(item) for item in source.structured_estimate_receipts)
    estimates_by_id = {item.receipt_id: item for item in estimates}
    candidates = tuple(
        type(item).model_validate(
            {
                **item.model_dump(mode="python"),
                "estimate_receipt_fingerprint": estimates_by_id[
                    item.estimate_receipt_id
                ].fingerprint,
            }
        )
        for item in source.candidate_projections
    )
    stability = []
    for series in source.stability_series:
        trials = tuple(
            type(trial).model_validate(
                {
                    **trial.model_dump(mode="python"),
                    "estimate_receipt_fingerprint": estimates_by_id[
                        trial.estimate_receipt_id
                    ].fingerprint,
                }
            )
            for trial in series.trials
        )
        stability.append(
            type(series).model_validate(
                {**series.model_dump(mode="python"), "trials": trials}
            )
        )
    submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **source.model_dump(mode="python"),
            "structured_estimate_receipts": estimates,
            "candidate_projections": candidates,
            "deterministic_baseline_projections": tuple(
                numeric_value(item)
                for item in source.deterministic_baseline_projections
            ),
            "objective_truth_projections": tuple(
                numeric_value(item) for item in source.objective_truth_projections
            ),
            "blind_human_judgments": tuple(
                numeric_value(item) for item in source.blind_human_judgments
            ),
            "blind_human_adjudications": tuple(
                numeric_value(item) for item in source.blind_human_adjudications
            ),
            "stability_series": tuple(stability),
        }
    )
    return UntrustedCalibrationProjectionV1(
        campaign=campaign,
        submission=submission,
        source_observed_at=submission.submitted_at + timedelta(seconds=1),
    )


def test_fixed_definition_and_report_surface_are_non_activating() -> None:
    report = _report()

    assert report.persistence_state == "untrusted_projection"
    assert report.repository_owned is False
    assert report.comparison_allowed is False
    assert report.derived_at is None
    assert report.activation_allowed is False
    assert report.private_export_allowed is False
    assert report.team_share_allowed is False
    assert report.definition == FIXED_CALIBRATION_REPORT_DEFINITION
    assert report.definition.activation_allowed is False
    assert "activation" not in {
        key
        for key in UntrustedCalibrationReportV1.model_fields
        if key != "activation_allowed"
    }
    assert report.state is CalibrationReportState.PARTIAL
    assert report.metric_reports[0].state is CalibrationReportState.PARTIAL


def test_full_preregistered_vocabulary_keeps_absent_class_in_macro_denominator() -> None:
    report = _report(minimum_holdout_per_metric=1, minimum_subgroup_size=1)
    metric = report.metric_reports[0]
    overall = _overall(metric)
    classes = {
        item.label_code: item
        for item in metric.class_receipts
        if item.scope_id == overall.scope_id
    }

    assert metric.label_vocabulary == ("negative", "positive")
    assert set(classes) == {"negative", "positive"}
    assert classes["negative"].support == 0
    assert classes["negative"].predicted_count == 0
    assert classes["negative"].f1 == 0.0
    assert classes["positive"].f1 == 1.0
    macro_f1 = _measurement(metric, "classification.macro_f1")
    assert macro_f1.state is CalibrationMeasurementState.KNOWN
    assert macro_f1.scalar_value == pytest.approx(0.5)

    cells = tuple(
        item for item in metric.confusion_cells if item.scope_id == overall.scope_id
    )
    assert len(cells) == 4
    assert sum(item.count for item in cells) == 1


def test_selected_confidence_calibration_does_not_fabricate_probability_vectors() -> None:
    report = _report(minimum_holdout_per_metric=1, minimum_subgroup_size=1)
    metric = report.metric_reports[0]

    ece = _measurement(metric, "calibration.selected_confidence_ece")
    false_confident = _measurement(
        metric, "calibration.false_confident_error_rate"
    )
    assert ece.state is CalibrationMeasurementState.KNOWN
    assert ece.scalar_value == pytest.approx(0.2)
    assert false_confident.state is CalibrationMeasurementState.KNOWN
    assert false_confident.numerator == 0
    assert false_confident.denominator == 1

    for key in (
        "calibration.brier_score",
        "calibration.log_loss",
        "calibration.slope",
    ):
        item = _measurement(metric, key)
        assert item.state is CalibrationMeasurementState.UNSUPPORTED
        assert item.reason_code == "full_probability_vector_not_recorded"
        assert item.scalar_value is None
    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert "probabilities" not in serialized


def test_objective_truth_precedes_a_conflicting_resolved_human_value() -> None:
    projection = _projection(minimum_holdout_per_metric=1, minimum_subgroup_size=1)
    submission = projection.submission
    judgments = tuple(
        BlindHumanJudgmentInputV1.model_validate(
            {**item.model_dump(mode="python"), "label_code": "negative"}
        )
        for item in submission.blind_human_judgments
    )
    adjudications = tuple(
        BlindHumanAdjudicationInputV1.model_validate(
            {**item.model_dump(mode="python"), "label_code": "negative"}
        )
        for item in submission.blind_human_adjudications
    )
    changed_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **submission.model_dump(mode="python"),
            "blind_human_judgments": judgments,
            "blind_human_adjudications": adjudications,
        }
    )
    report = derive_untrusted_calibration_report(
        UntrustedCalibrationProjectionV1(
            campaign=projection.campaign,
            submission=changed_submission,
            source_observed_at=projection.source_observed_at,
        )
    )
    metric = report.metric_reports[0]

    accuracy = _measurement(metric, "classification.accuracy")
    model_human = _measurement(metric, "agreement.model_human_observed")
    assert accuracy.scalar_value == 1.0
    assert accuracy.numerator == 1
    assert model_human.scalar_value == 0.0
    assert model_human.numerator == 0
    assert model_human.denominator == 1


def test_individual_human_judgments_are_not_consensus_ground_truth() -> None:
    projection = _projection(minimum_holdout_per_metric=1, minimum_subgroup_size=1)
    submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **projection.submission.model_dump(mode="python"),
            "objective_truth_projections": (),
            "blind_human_adjudications": (),
        }
    )
    report = derive_untrusted_calibration_report(
        UntrustedCalibrationProjectionV1(
            campaign=projection.campaign,
            submission=submission,
            source_observed_at=projection.source_observed_at,
        )
    )
    metric = report.metric_reports[0]

    assert _measurement(metric, "coverage.truth_known").integer_value == 0
    assert (
        _measurement(metric, "classification.accuracy").state
        is CalibrationMeasurementState.INSUFFICIENT_DATA
    )
    assert _measurement(metric, "classification.accuracy").scalar_value is None


def test_every_slice_and_overall_missing_state_is_explicit_and_canonical() -> None:
    report = _report()
    metric = report.metric_reports[0]
    expected_dimensions = {
        "overall",
        "task",
        "language",
        "provider",
        "project",
        "time",
        "evidence_availability",
    }
    assert {item.dimension.value for item in metric.scopes} == expected_dimensions
    assert tuple(
        (item.dimension.value, item.bucket_code, item.scope_id)
        for item in metric.scopes
    ) == tuple(
        sorted(
            (item.dimension.value, item.bucket_code, item.scope_id)
            for item in metric.scopes
        )
    )

    fixed_keys = {item.measurement_key for item in CALIBRATION_MEASUREMENT_SPECS}
    for scope in metric.scopes:
        members = tuple(
            item for item in metric.measurements if item.scope_id == scope.scope_id
        )
        assert {item.measurement_key for item in members} == fixed_keys
        assert len(members) == len(fixed_keys)
        if scope.state is CalibrationMeasurementState.INSUFFICIENT_DATA:
            assert scope.reason_code == "slice_below_minimum"
    assert {
        item.measurement_key for item in metric.missingness
    } == {
        item.measurement_key
        for item in metric.measurements
        if item.scope_id == _overall(metric).scope_id
        and item.state is not CalibrationMeasurementState.KNOWN
    }


def test_terminal_failure_and_resources_preserve_counts_instead_of_zero_fill() -> None:
    projection = _projection()
    submission = projection.submission
    referenced_attempts = {
        item.attempt_id for item in submission.candidate_projections
    } | {
        trial.attempt_id
        for series in submission.stability_series
        for trial in series.trials
    }
    target = next(
        item
        for item in submission.attempt_outcomes
        if item.attempt_id not in referenced_attempts
    )
    changed = AttemptTerminalOutcomeV1.model_validate(
        {
            **target.model_dump(mode="python"),
            "state": AttemptTerminalState.OOM,
            "structured_output_fingerprint": None,
            "reason_code": "out_of_memory",
        }
    )
    outcomes = tuple(
        changed if item.attempt_id == target.attempt_id else item
        for item in submission.attempt_outcomes
    )
    changed_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {**submission.model_dump(mode="python"), "attempt_outcomes": outcomes}
    )
    report = derive_untrusted_calibration_report(
        UntrustedCalibrationProjectionV1(
            campaign=projection.campaign,
            submission=changed_submission,
            source_observed_at=projection.source_observed_at,
        )
    )
    metric = report.metric_reports[0]

    oom = _measurement(metric, "resource.oom_rate")
    assert oom.state is CalibrationMeasurementState.KNOWN
    assert oom.numerator == 1
    assert oom.denominator == len(outcomes)
    assert oom.scalar_value == pytest.approx(1 / len(outcomes))
    assert _measurement(metric, "resource.peak_ram_bytes").scalar_value == 1024.0
    cold = _measurement(metric, "resource.cold_latency_p95_ms")
    assert cold.state is CalibrationMeasurementState.UNSUPPORTED
    assert cold.reason_code == "cold_warm_marker_not_recorded"


def test_retrieval_cascade_and_unrecorded_operational_fields_are_not_available() -> None:
    metric = _report().metric_reports[0]
    expected = {
        "retrieval.mean_reciprocal_rank": "ranked_relevance_receipts_not_recorded",
        "retrieval.link_precision": "ranked_relevance_receipts_not_recorded",
        "retrieval.recall_at_k": "ranked_relevance_receipts_not_recorded",
        "retrieval.ndcg_at_k": "ranked_relevance_receipts_not_recorded",
        "cascade.stop_rate": "cascade_stop_receipts_not_recorded",
        "cascade.incremental_value": "paired_stage_utility_not_recorded",
        "resource.throughput_per_second": "throughput_not_recorded",
        "resource.disk_bytes": "disk_measurement_not_recorded",
    }
    for key, reason in expected.items():
        item = _measurement(metric, key)
        assert item.state is CalibrationMeasurementState.UNSUPPORTED
        assert item.reason_code == reason
        assert item.scalar_value is None
    affected = {
        item.measurement_key: item.affected_count for item in metric.missingness
    }
    assert affected["retrieval.mean_reciprocal_rank"] == _overall(metric).case_count
    assert affected["cascade.stop_rate"] == _overall(metric).case_count


def test_model_copy_bypass_and_unsafe_identifiers_fail_at_public_boundaries() -> None:
    projection = _projection()
    forged_campaign = projection.campaign.model_copy(
        update={"activation_allowed": True}
    )
    forged_projection = projection.model_copy(update={"campaign": forged_campaign})
    with pytest.raises(ValidationError):
        derive_untrusted_calibration_report(forged_projection)

    report = derive_untrusted_calibration_report(projection)
    forged_report = report.model_copy(update={"activation_allowed": True})
    with pytest.raises(ValidationError):
        summarize_untrusted_calibration_report(forged_report)

    overall = _overall(report.metric_reports[0])
    with pytest.raises(ValidationError):
        CalibrationReportScopeV1(
            scope_id=overall.scope_id,
            metric_key=overall.metric_key,
            dimension=CalibrationScopeDimension.PROJECT,
            bucket_code="file:reserved-secret",
            case_count=1,
            minimum_required_count=1,
            state=CalibrationMeasurementState.KNOWN,
        )


def test_fingerprints_ordering_and_safe_model_lab_summary_are_reproducible() -> None:
    projection = _projection()
    first = derive_untrusted_calibration_report(projection)
    second = derive_untrusted_calibration_report(projection)
    hydrated = UntrustedCalibrationReportV1.model_validate(
        first.model_dump(mode="python")
    )

    assert first == second == hydrated
    assert first.fingerprint == second.fingerprint == hydrated.fingerprint
    assert first.report_id == second.report_id
    assert tuple(item.metric_key for item in first.metric_reports) == tuple(
        sorted(item.metric_key for item in first.metric_reports)
    )
    metric = first.metric_reports[0]
    assert tuple(
        (item.scope_id, item.measurement_key) for item in metric.measurements
    ) == tuple(
        sorted(
            (item.scope_id, item.measurement_key) for item in metric.measurements
        )
    )
    assert (
        metric.comparison_identity.observation_identity_fingerprint
        != metric.comparison_identity.comparison_family_fingerprint
    )

    summary = summarize_untrusted_calibration_report(first)
    assert summary.repository_sealed is False
    assert summary.comparison_allowed is False
    assert summary.product_activation_allowed is False
    serialized = json.dumps(summary.model_dump(mode="json"), sort_keys=True)
    for forbidden in (
        "campaign_id",
        "submission_id",
        "case_id",
        "project_id",
        "session_revision_id",
        "evidence_packet",
        "participant_id",
        "provider",
    ):
        assert forbidden not in serialized


def test_report_identifier_changes_with_untrusted_source_observation_time() -> None:
    projection = _projection()
    first = derive_untrusted_calibration_report(projection)
    later = derive_untrusted_calibration_report(
        UntrustedCalibrationProjectionV1(
            campaign=projection.campaign,
            submission=projection.submission,
            source_observed_at=projection.source_observed_at
            + timedelta(microseconds=1),
        )
    )

    assert first.report_id != later.report_id
    assert first.fingerprint != later.fingerprint
    assert (
        first.metric_reports[0].comparison_identity
        == later.metric_reports[0].comparison_identity
    )


def test_untrusted_source_clock_never_claims_repository_derivation() -> None:
    projection = _projection()
    assert projection.repository_owned is False

    report = derive_untrusted_calibration_report(projection)
    summary = summarize_untrusted_calibration_report(report)
    assert report.source_observed_at == projection.source_observed_at
    assert report.derived_at is None
    assert report.repository_owned is False
    assert report.persistence_state == "untrusted_projection"
    assert report.comparison_allowed is False
    assert summary.source_observed_at == projection.source_observed_at
    assert summary.derived_at is None

    forged = projection.model_copy(update={"repository_owned": True})
    with pytest.raises(ValidationError):
        derive_untrusted_calibration_report(forged)


def test_policy_and_resource_provenance_change_the_correct_version_boundaries() -> None:
    baseline_projection = _projection()
    baseline_report = derive_untrusted_calibration_report(baseline_projection)
    baseline_identity = baseline_report.metric_reports[0].comparison_identity

    changed_policy_report = derive_untrusted_calibration_report(
        _projection(minimum_holdout_per_metric=1)
    )
    changed_policy_identity = changed_policy_report.metric_reports[0].comparison_identity
    assert changed_policy_identity.gate_policy_fingerprint != (
        baseline_identity.gate_policy_fingerprint
    )
    assert changed_policy_identity.threshold_policy_fingerprint != (
        baseline_identity.threshold_policy_fingerprint
    )
    assert changed_policy_identity.comparison_family_fingerprint != (
        baseline_identity.comparison_family_fingerprint
    )

    submission = baseline_projection.submission
    target = _unreferenced_outcome(submission)
    changed_resources = ResourceUsageProvenanceV1.model_validate(
        {
            **target.resources.model_dump(mode="python"),
            "collector_version": "reserved-resource-v2",
            "peak_ram_bytes": 4096,
        }
    )
    changed_outcome = AttemptTerminalOutcomeV1.model_validate(
        {
            **target.model_dump(mode="python"),
            "resources": changed_resources,
        }
    )
    changed_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **submission.model_dump(mode="python"),
            "attempt_outcomes": tuple(
                changed_outcome if item.attempt_id == target.attempt_id else item
                for item in submission.attempt_outcomes
            ),
        }
    )
    changed_resource_report = derive_untrusted_calibration_report(
        _projection_with_submission(baseline_projection, changed_submission)
    )
    changed_resource_identity = (
        changed_resource_report.metric_reports[0].comparison_identity
    )
    assert changed_resource_identity.measurement_provenance_fingerprint != (
        baseline_identity.measurement_provenance_fingerprint
    )
    assert changed_resource_identity.submission_fingerprint != (
        baseline_identity.submission_fingerprint
    )
    assert changed_resource_identity.observation_source_fingerprint != (
        baseline_identity.observation_source_fingerprint
    )
    assert changed_resource_identity.comparison_family_fingerprint == (
        baseline_identity.comparison_family_fingerprint
    )
    assert changed_resource_report.source_bundle_fingerprint != (
        baseline_report.source_bundle_fingerprint
    )
    assert changed_resource_report.fingerprint != baseline_report.fingerprint


def test_insufficient_scopes_emit_no_numeric_detail_rows() -> None:
    report = _report(minimum_subgroup_size=5)
    metric = report.metric_reports[0]
    insufficient_scope_ids = {
        item.scope_id
        for item in metric.scopes
        if item.state is CalibrationMeasurementState.INSUFFICIENT_DATA
    }
    assert insufficient_scope_ids
    for rows in (
        metric.confusion_cells,
        metric.class_receipts,
        metric.reliability_bins,
        metric.selective_points,
    ):
        assert not any(item.scope_id in insufficient_scope_ids for item in rows)


def test_selective_coverage_uses_all_known_truth_even_when_candidate_is_missing() -> None:
    projection = _projection(minimum_holdout_per_metric=1, minimum_subgroup_size=1)
    submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **projection.submission.model_dump(mode="python"),
            "candidate_projections": (),
        }
    )
    report = derive_untrusted_calibration_report(
        _projection_with_submission(projection, submission)
    )
    metric = report.metric_reports[0]
    overall = _overall(metric)
    point = next(
        item
        for item in metric.selective_points
        if item.scope_id == overall.scope_id and item.threshold == 0.0
    )
    assert _measurement(metric, "coverage.truth_known").integer_value == 1
    assert _measurement(metric, "coverage.candidate_known").integer_value == 0
    assert point.coverage_numerator == 0
    assert point.coverage_denominator == 1
    assert point.risk_numerator == 0
    assert point.risk_denominator == 0
    assert point.state is CalibrationMeasurementState.INSUFFICIENT_DATA


def test_resource_aggregates_require_complete_observation_and_count_missing_attempts() -> None:
    projection = _projection()
    submission = projection.submission
    target = _unreferenced_outcome(submission)
    unavailable_resources = ResourceUsageProvenanceV1(
        state=MeasurementState.NOT_APPLICABLE,
        collector_version=target.resources.collector_version,
        reason_code="hardware_counter_not_applicable",
    )
    changed_outcome = AttemptTerminalOutcomeV1.model_validate(
        {**target.model_dump(mode="python"), "resources": unavailable_resources}
    )
    changed_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **submission.model_dump(mode="python"),
            "attempt_outcomes": tuple(
                changed_outcome if item.attempt_id == target.attempt_id else item
                for item in submission.attempt_outcomes
            ),
        }
    )
    report = derive_untrusted_calibration_report(
        _projection_with_submission(projection, changed_submission)
    )
    metric = report.metric_reports[0]
    ram = _measurement(metric, "resource.peak_ram_bytes")
    assert ram.state is CalibrationMeasurementState.INSUFFICIENT_DATA
    assert ram.scalar_value is None
    assert ram.numerator == len(submission.attempt_outcomes) - 1
    assert ram.denominator == len(submission.attempt_outcomes)
    missing = next(
        item
        for item in metric.missingness
        if item.measurement_key == "resource.peak_ram_bytes"
    )
    assert missing.affected_count == 1

    unsupported = next(
        item
        for item in metric.missingness
        if item.measurement_key == "resource.disk_bytes"
    )
    assert unsupported.affected_count == len(submission.attempt_outcomes)


def test_all_not_applicable_resource_receipts_remain_distinct_from_missing() -> None:
    projection = _projection()
    submission = projection.submission
    outcomes = tuple(
        AttemptTerminalOutcomeV1.model_validate(
            {
                **item.model_dump(mode="python"),
                "resources": ResourceUsageProvenanceV1(
                    state=MeasurementState.NOT_APPLICABLE,
                    collector_version=item.resources.collector_version,
                    reason_code="hardware_counter_not_applicable",
                ),
            }
        )
        for item in submission.attempt_outcomes
    )
    changed_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **submission.model_dump(mode="python"),
            "attempt_outcomes": outcomes,
            "structured_estimate_receipts": (),
            "candidate_projections": (),
            "stability_series": (),
        }
    )
    report = derive_untrusted_calibration_report(
        _projection_with_submission(projection, changed_submission)
    )
    ram = _measurement(report.metric_reports[0], "resource.peak_ram_bytes")
    assert ram.state is CalibrationMeasurementState.NOT_APPLICABLE
    assert ram.reason_code == "ram_measurement_not_applicable"
    assert ram.numerator == 0
    assert ram.denominator == len(outcomes)


def test_human_agreement_uses_distinct_participants_and_rejects_duplicates() -> None:
    projection = _projection()
    report = derive_untrusted_calibration_report(projection)
    receipt = next(
        item
        for item in report.metric_reports[0].agreement_receipts
        if item.kind.value == "human_human"
    )
    assert receipt.pair_count == 1

    judgments = projection.submission.blind_human_judgments
    duplicate = type(judgments[1]).model_validate(
        {
            **judgments[1].model_dump(mode="python"),
            "participant_id": judgments[0].participant_id,
        }
    )
    duplicate_submission = CalibrationEvidenceSubmissionV1.model_validate(
        {
            **projection.submission.model_dump(mode="python"),
            "blind_human_judgments": (judgments[0], duplicate),
            "blind_human_adjudications": (),
        }
    )
    with pytest.raises(ValidationError, match="one judgment per case"):
        _projection_with_submission(projection, duplicate_submission)


def test_project_slice_uses_domain_separated_hash_of_the_full_project_id() -> None:
    projection = _projection()
    metric = derive_untrusted_calibration_report(projection).metric_reports[0]
    project_ids = {
        item.project_id
        for item in projection.campaign.assignment_manifest.assignments
        if item.case_id in set(projection.campaign.split.holdout_case_ids)
    }
    expected = {
        "project."
        + hashlib.sha256(
            f"calibration-project-slice-v1:{project_id}".encode("ascii")
        ).hexdigest()
        for project_id in project_ids
    }
    actual = {
        item.bucket_code
        for item in metric.scopes
        if item.dimension is CalibrationScopeDimension.PROJECT
    }
    assert actual == expected
    assert all(len(item) == len("project.") + 64 for item in actual)
    assert not any(project_id[:16] in bucket for project_id in project_ids for bucket in actual)


def test_numeric_truth_is_preserved_but_performance_and_tolerance_abstain() -> None:
    report = derive_untrusted_calibration_report(_numeric_projection())
    metric = report.metric_reports[0]
    assert metric.value_kind == "continuous"
    assert metric.label_vocabulary == ()
    assert _measurement(metric, "coverage.truth_known").integer_value == 1
    assert _measurement(metric, "coverage.objective_truth").integer_value == 1
    for key, reason in (
        ("numeric.mean_absolute_error", "numeric_performance_contract_not_registered"),
        ("numeric.root_mean_squared_error", "numeric_performance_contract_not_registered"),
        ("numeric.within_tolerance_rate", "numeric_tolerance_not_preregistered"),
    ):
        measurement = _measurement(metric, key)
        assert measurement.state is CalibrationMeasurementState.UNSUPPORTED
        assert measurement.reason_code == reason
        assert measurement.scalar_value is None
    assert any(
        item.state is CalibrationMeasurementState.UNSUPPORTED
        and item.reason_code == "numeric_tolerance_not_preregistered"
        for item in metric.stability_receipts
    )
    assert all(
        item.state is CalibrationMeasurementState.UNSUPPORTED
        and item.reason_code == "numeric_tolerance_not_preregistered"
        for item in metric.agreement_receipts
    )
