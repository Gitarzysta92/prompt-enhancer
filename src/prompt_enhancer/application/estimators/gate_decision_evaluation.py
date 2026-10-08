"""Code-owned v20 gate evaluation over sealed v16/v17/v19 values only."""

from __future__ import annotations

from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Iterable

from ...domain import Provider
from .contracts import ModelSource

from .calibration_report_contracts import (
    CalibrationMeasurementShape,
    CalibrationMeasurementState,
    CalibrationMeasurementV1,
    CalibrationMetricReportV1,
    CalibrationScopeDimension,
)
from .calibration_report_persistence import (
    RepositorySealedCalibrationReportV1,
    revalidate_repository_sealed_calibration_report_v1,
)
from .calibration_reporting import (
    UntrustedCalibrationProjectionV1,
    derive_untrusted_calibration_report,
)
from .evidence_contracts import (
    AttemptTerminalState,
    CalibrationEvidenceSubmissionV1,
    CalibrationValueState,
    HumanParticipantKind,
    ServedIdentityState,
    revalidate_calibration_evidence_submission_v1,
    revalidate_content_free_contract,
)
from .gate_contracts import (
    CaseOrigin,
    MetricRiskTier,
    StabilityCondition,
    SubgroupDimension,
)
from .gate_decision_contracts import (
    FIXED_GATE_DECISION_DEFINITION,
    NONE_GATE_VALUE,
    GateDecisionCheckCategory,
    GateDecisionCheckOutcome,
    GateDecisionCheckV1,
    GateDecisionOperator,
    GateDecisionOutcome,
    GateDecisionValueShape,
    GateDecisionValueV1,
    RepositorySealedGateDecisionV1,
    canonical_payload_digest,
    repository_gate_decision_id,
    revalidate_repository_sealed_gate_decision_v1,
)
from .persistence import PreregisteredEstimatorCampaign


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("repository gate clock must return UTC")
    return value


def _count(value: int, unit: str) -> GateDecisionValueV1:
    return GateDecisionValueV1(
        shape=GateDecisionValueShape.COUNT,
        unit_code=unit,
        integer_value=value,
    )


def _scalar(value: float, unit: str = "score") -> GateDecisionValueV1:
    return GateDecisionValueV1(
        shape=GateDecisionValueShape.SCALAR,
        unit_code=unit,
        scalar_value=value,
    )


def _rate(value: float) -> GateDecisionValueV1:
    return GateDecisionValueV1(
        shape=GateDecisionValueShape.RATE,
        unit_code="ratio",
        scalar_value=value,
    )


def _known(
    key: str,
    actual: GateDecisionValueV1,
    operator: GateDecisionOperator,
    threshold: GateDecisionValueV1,
    *,
    category: GateDecisionCheckCategory = GateDecisionCheckCategory.POLICY,
    failure_reason: str | None = None,
) -> GateDecisionCheckV1:
    left = actual.numeric_value
    right = threshold.numeric_value
    assert left is not None and right is not None
    passed = {
        GateDecisionOperator.EQ: left == right,
        GateDecisionOperator.GTE: left >= right,
        GateDecisionOperator.GT: left > right,
        GateDecisionOperator.LTE: left <= right,
        GateDecisionOperator.LT: left < right,
    }[operator]
    return GateDecisionCheckV1(
        check_key=key,
        category=category,
        outcome=(
            GateDecisionCheckOutcome.PASS
            if passed
            else GateDecisionCheckOutcome.FAIL
        ),
        operator=operator,
        actual=actual,
        threshold=threshold,
        reason_code=(
            None
            if passed
            else failure_reason
            or (
                "threshold_exceeded"
                if operator in {GateDecisionOperator.LTE, GateDecisionOperator.LT}
                else "threshold_not_met"
            )
        ),
    )


def _unknown(
    key: str,
    threshold: GateDecisionValueV1,
    operator: GateDecisionOperator,
    reason: str,
    *,
    unsupported: bool = False,
    category: GateDecisionCheckCategory = GateDecisionCheckCategory.POLICY,
) -> GateDecisionCheckV1:
    return GateDecisionCheckV1(
        check_key=key,
        category=category,
        outcome=(
            GateDecisionCheckOutcome.UNSUPPORTED
            if unsupported
            else GateDecisionCheckOutcome.INSUFFICIENT_DATA
        ),
        operator=operator,
        actual=NONE_GATE_VALUE,
        threshold=threshold,
        reason_code=reason,
    )


def _integrity(key: str, mismatch_count: int) -> GateDecisionCheckV1:
    return _known(
        key,
        _count(mismatch_count, "mismatches"),
        GateDecisionOperator.EQ,
        _count(0, "mismatches"),
        category=GateDecisionCheckCategory.INTEGRITY,
        failure_reason="integrity_mismatch",
    )


def _complete_count(
    key: str,
    actual: int,
    required: int,
    unit: str,
    reason: str,
    *,
    category: GateDecisionCheckCategory = GateDecisionCheckCategory.POLICY,
) -> GateDecisionCheckV1:
    """Require complete evidence without turning a missing count into failure."""

    threshold = _count(required, unit)
    if actual < required:
        return _unknown(
            key,
            threshold,
            GateDecisionOperator.GTE,
            reason,
            category=category,
        )
    return _known(
        key,
        _count(actual, unit),
        GateDecisionOperator.GTE,
        threshold,
        category=category,
    )


def _fixed_unthresholded(
    key: str,
    reason: str,
    *,
    category: GateDecisionCheckCategory = GateDecisionCheckCategory.POLICY,
) -> GateDecisionCheckV1:
    return _unknown(
        key,
        NONE_GATE_VALUE,
        GateDecisionOperator.EQ,
        reason,
        unsupported=True,
        category=category,
    )


def _overall(metric: CalibrationMetricReportV1):
    return next(
        item
        for item in metric.scopes
        if item.dimension is CalibrationScopeDimension.OVERALL
    )


def _measurement(
    metric: CalibrationMetricReportV1, key: str
) -> CalibrationMeasurementV1:
    scope_id = _overall(metric).scope_id
    return next(
        item
        for item in metric.measurements
        if item.scope_id == scope_id and item.measurement_key == key
    )


def _measurement_value(item: CalibrationMeasurementV1) -> GateDecisionValueV1:
    if item.shape is CalibrationMeasurementShape.COUNT:
        assert item.integer_value is not None
        return _count(item.integer_value, item.unit_code)
    if item.shape is CalibrationMeasurementShape.SCALAR:
        assert item.scalar_value is not None
        return _scalar(item.scalar_value, item.unit_code)
    assert item.scalar_value is not None
    return _rate(item.scalar_value)


def _measurement_check(
    key: str,
    item: CalibrationMeasurementV1,
    operator: GateDecisionOperator,
    threshold: GateDecisionValueV1,
) -> GateDecisionCheckV1:
    if item.state is CalibrationMeasurementState.KNOWN:
        return _known(key, _measurement_value(item), operator, threshold)
    return _unknown(
        key,
        threshold,
        operator,
        item.reason_code or "measurement_unavailable",
        unsupported=item.state
        in {
            CalibrationMeasurementState.UNSUPPORTED,
            CalibrationMeasurementState.NOT_APPLICABLE,
            CalibrationMeasurementState.INCOMPATIBLE,
        },
    )


def _operational_latency_checks(
    *,
    sample_key: str,
    value_key: str,
    item: CalibrationMeasurementV1,
    required_samples: int,
    maximum_latency_ms: float,
) -> tuple[GateDecisionCheckV1, GateDecisionCheckV1]:
    """Gate a latency percentile behind its preregistered sample minimum."""

    sample_threshold = _count(required_samples, "samples")
    value_threshold = _scalar(maximum_latency_ms, "milliseconds")
    if item.state is not CalibrationMeasurementState.KNOWN:
        unsupported = item.state in {
            CalibrationMeasurementState.UNSUPPORTED,
            CalibrationMeasurementState.NOT_APPLICABLE,
            CalibrationMeasurementState.INCOMPATIBLE,
        }
        reason = item.reason_code or "latency_measurement_unavailable"
        return (
            _unknown(
                sample_key,
                sample_threshold,
                GateDecisionOperator.GTE,
                reason,
                unsupported=unsupported,
            ),
            _unknown(
                value_key,
                value_threshold,
                GateDecisionOperator.LTE,
                reason,
                unsupported=unsupported,
            ),
        )

    sample_check = _complete_count(
        sample_key,
        item.sample_count,
        required_samples,
        "samples",
        "latency_samples_incomplete",
    )
    if item.sample_count < required_samples:
        return (
            sample_check,
            _unknown(
                value_key,
                value_threshold,
                GateDecisionOperator.LTE,
                "latency_samples_incomplete",
            ),
        )
    return (
        sample_check,
        _measurement_check(
            value_key,
            item,
            GateDecisionOperator.LTE,
            value_threshold,
        ),
    )


def _measurement_complete_count_check(
    key: str,
    item: CalibrationMeasurementV1,
    required: int,
    unit: str,
    reason: str,
) -> GateDecisionCheckV1:
    """Treat incomplete coverage as unknown, never as a numeric failure."""

    threshold = _count(required, unit)
    if item.state is not CalibrationMeasurementState.KNOWN:
        return _unknown(
            key,
            threshold,
            GateDecisionOperator.GTE,
            item.reason_code or reason,
            unsupported=item.state
            in {
                CalibrationMeasurementState.UNSUPPORTED,
                CalibrationMeasurementState.NOT_APPLICABLE,
                CalibrationMeasurementState.INCOMPATIBLE,
            },
        )
    if (
        item.shape is not CalibrationMeasurementShape.COUNT
        or item.integer_value is None
        or item.unit_code != unit
    ):
        return _unknown(
            key,
            threshold,
            GateDecisionOperator.GTE,
            "coverage_measurement_incompatible",
            unsupported=True,
        )
    return _complete_count(key, item.integer_value, required, unit, reason)


def _absence_check(
    key: str,
    actual: int,
    unit: str,
    reason: str,
    *,
    incomplete: bool = False,
) -> GateDecisionCheckV1:
    """Evaluate a prohibited count while preserving incomplete-as-unknown."""

    threshold = _count(0, unit)
    if incomplete and actual:
        return _unknown(key, threshold, GateDecisionOperator.EQ, reason)
    return _known(
        key,
        _count(actual, unit),
        GateDecisionOperator.EQ,
        threshold,
        failure_reason=reason,
    )


def _selective_check(
    key: str,
    metric: CalibrationMetricReportV1,
    *,
    coverage: bool,
    operator: GateDecisionOperator,
    threshold: float,
) -> GateDecisionCheckV1:
    point = next(
        (item for item in metric.selective_points if item.threshold == 0.0), None
    )
    limit = _rate(threshold)
    if point is None or point.state is not CalibrationMeasurementState.KNOWN:
        return _unknown(
            key,
            limit,
            operator,
            point.reason_code if point is not None and point.reason_code else "selective_point_unavailable",
        )
    numerator = point.coverage_numerator if coverage else point.risk_numerator
    denominator = point.coverage_denominator if coverage else point.risk_denominator
    if denominator == 0:
        return _unknown(key, limit, operator, "selective_denominator_unavailable")
    return _known(key, _rate(numerator / denominator), operator, limit)


def _unsupported_policy_checks(
    metric_key: str,
    campaign: PreregisteredEstimatorCampaign,
) -> Iterable[GateDecisionCheckV1]:
    policy = campaign.policy
    yield _unknown(
        f"policy.baseline_margin.{metric_key}",
        _scalar(policy.minimum_baseline_margin, "score"),
        GateDecisionOperator.GT,
        "baseline_comparison_not_recorded",
        unsupported=True,
    )
    yield _unknown(
        f"policy.human_gap.{metric_key}",
        _rate(policy.maximum_human_gap),
        GateDecisionOperator.LTE,
        "human_comparison_not_recorded",
        unsupported=True,
    )


_STATIC_GATE_CHECK_KEYS = frozenset(
    {
        "integrity.access_lineage",
        "integrity.blind_human_independence",
        "integrity.blind_human_lineage",
        "integrity.campaign_lineage",
        "integrity.candidate_projection_lineage",
        "integrity.deterministic_baseline_lineage",
        "integrity.evaluator_definition",
        "integrity.expected_attempt_set",
        "integrity.holdout_activity_chronology",
        "integrity.identity.plan_binding",
        "integrity.identity.runner_configuration",
        "integrity.identity.runner_preregistration",
        "integrity.identity.served_binding",
        "integrity.launch_lineage",
        "integrity.objective_truth_lineage",
        "integrity.outcome_lineage",
        "integrity.partition_membership",
        "integrity.preregistration_chronology",
        "integrity.privacy_lineage",
        "integrity.project_separation",
        "integrity.report_lineage",
        "integrity.report_metric_identity",
        "integrity.report_rederivation",
        "integrity.stability_lineage",
        "integrity.structured_estimate_lineage",
        "integrity.submission_lineage",
        "integrity.time_separation",
        "policy.access.coverage",
        "policy.access.gaps",
        "policy.access.prohibited_pre_unseal",
        "policy.access.unauthorized",
        "policy.active_learning.maximum",
        "policy.active_learning.minimum",
        "policy.high_risk.registration",
        "policy.holdout.total",
        "policy.identity.fallback",
        "policy.identity.served_coverage",
        "policy.identity.unavailable",
        "policy.privacy.findings",
        "policy.privacy.scan_coverage",
        "policy.privacy.unscanned",
        "policy.representative_private_evidence",
        "policy.stored_plan.non_synthetic",
    }
)


def repository_gate_check_vocabulary(
    campaign: PreregisteredEstimatorCampaign,
    sealed_report: RepositorySealedCalibrationReportV1,
) -> tuple[str, ...]:
    """Return the exact code-owned vocabulary for registered policy inputs."""

    campaign = revalidate_content_free_contract(PreregisteredEstimatorCampaign, campaign)
    sealed_report = revalidate_repository_sealed_calibration_report_v1(sealed_report)
    keys = set(_STATIC_GATE_CHECK_KEYS)
    keys.update(
        f"policy.active_learning.stratum.{value.value}"
        for value in campaign.policy.required_strata
    )
    keys.update(
        f"policy.active_learning.language.{value.value}"
        for value in campaign.policy.required_languages
    )
    keys.update(
        f"policy.holdout.stratum.{value.value}"
        for value in campaign.policy.required_strata
    )
    keys.update(
        f"policy.holdout.language.{value.value}"
        for value in campaign.policy.required_languages
    )
    metric_keys = tuple(
        sorted(
            {
                *(item.metric_key for item in campaign.stored_plan.question_specs),
                *(
                    item.metric_key
                    for item in campaign.legacy_preregistration.metric_specs
                ),
                *(
                    item.metric_key
                    for item in sealed_report.report.metric_reports
                ),
                *(
                    item.metric_key
                    for item in campaign.policy.high_risk_precision_rules
                ),
            }
        )
    )
    high_risk = {
        item.metric_key
        for item in campaign.legacy_preregistration.metric_specs
        if item.risk_tier is MetricRiskTier.HIGH
    } | {item.metric_key for item in campaign.policy.high_risk_precision_rules}
    for metric_key in metric_keys:
        keys.update(
            {
                f"policy.baseline_margin.{metric_key}",
                f"policy.calibration_ece.{metric_key}",
                f"policy.candidate_projection_coverage.{metric_key}",
                f"policy.cold_latency_samples.{metric_key}",
                f"policy.cold_latency_p95.{metric_key}",
                f"policy.deterministic_baseline_coverage.{metric_key}",
                f"policy.error_rate.{metric_key}",
                f"policy.false_confident_error_rate.{metric_key}",
                f"policy.holdout.metric.{metric_key}",
                f"policy.human_adjudication_coverage.{metric_key}",
                f"policy.human_gap.{metric_key}",
                f"policy.objective_or_human_truth_coverage.{metric_key}",
                f"policy.oom_rate.{metric_key}",
                f"policy.refusal_rate.{metric_key}",
                f"policy.selective_coverage.{metric_key}",
                f"policy.selective_risk.{metric_key}",
                f"policy.stability.format.{metric_key}",
                f"policy.stability.injection.{metric_key}",
                f"policy.stability.order.{metric_key}",
                f"policy.stability.repeat.{metric_key}",
                f"policy.warm_latency_p95.{metric_key}",
                f"policy.warm_latency_samples.{metric_key}",
            }
        )
        for dimension in campaign.policy.subgroup_dimensions:
            keys.add(f"policy.subgroup.minimum.{dimension.value}.{metric_key}")
            keys.add(f"policy.subgroup.regression.{dimension.value}.{metric_key}")
        if metric_key in high_risk:
            keys.add(f"policy.high_risk_positive_predictions.{metric_key}")
            keys.add(f"policy.high_risk_precision.{metric_key}")
    return tuple(sorted(keys))


def _computed_integrity_checks(
    campaign: PreregisteredEstimatorCampaign,
    submission: CalibrationEvidenceSubmissionV1,
    sealed_report: RepositorySealedCalibrationReportV1,
) -> list[GateDecisionCheckV1]:
    """Recompute explicit integrity facts; no zero is assumed by construction."""

    plan = campaign.stored_plan
    policy = campaign.policy
    manifest = campaign.assignment_manifest
    split = campaign.split
    legacy = campaign.legacy_preregistration
    preregistration = campaign.preregistration_v2
    constellation = campaign.constellation_identity
    report = sealed_report.report
    plan_fingerprint = plan.canonical_fingerprint
    manifest_fingerprint = manifest.fingerprint
    split_fingerprint = split.fingerprint
    policy_fingerprint = policy.fingerprint
    legacy_fingerprint = legacy.fingerprint
    constellation_fingerprint = constellation.fingerprint
    assignments = {item.case_id: item for item in manifest.assignments}
    partition_ids = {
        *split.development_case_ids,
        *split.active_learning_case_ids,
        *split.holdout_case_ids,
    }
    holdout_ids = set(split.holdout_case_ids)

    campaign_mismatches = sum(
        (
            manifest.plan_fingerprint != plan_fingerprint,
            split.assignment_manifest_fingerprint != manifest_fingerprint,
            legacy.policy_fingerprint != policy_fingerprint,
            legacy.assignment_manifest_fingerprint != manifest_fingerprint,
            legacy.split_fingerprint != split_fingerprint,
            preregistration.policy_fingerprint != policy_fingerprint,
            preregistration.assignment_manifest_fingerprint != manifest_fingerprint,
            preregistration.split_fingerprint != split_fingerprint,
            preregistration.stored_plan_fingerprint != plan_fingerprint,
            preregistration.constellation_fingerprint != constellation_fingerprint,
            preregistration.legacy_preregistration_fingerprint != legacy_fingerprint,
            constellation.plan_fingerprint != plan_fingerprint,
        )
    )
    submission_groups = (
        submission.attempt_launches,
        submission.attempt_outcomes,
        submission.structured_estimate_receipts,
        submission.candidate_projections,
        submission.deterministic_baseline_projections,
        submission.objective_truth_projections,
        submission.blind_human_judgments,
        submission.blind_human_adjudications,
        submission.stability_series,
    )
    submission_mismatches = sum(
        (
            submission.campaign_id != campaign.campaign_id,
            submission.expected_attempt_manifest.campaign_id != campaign.campaign_id,
            submission.expected_attempt_manifest.plan_fingerprint != plan_fingerprint,
            submission.campaign_holdout_case_ids != split.holdout_case_ids,
            submission.holdout_access_audit.campaign_id != campaign.campaign_id,
            submission.privacy_scan.campaign_id != campaign.campaign_id,
        )
    ) + sum(
        getattr(item, "campaign_id") != campaign.campaign_id
        for group in submission_groups
        for item in group
    )
    report_mismatches = sum(
        (
            report.campaign_id != campaign.campaign_id,
            report.campaign_fingerprint != campaign.fingerprint,
            report.submission_id != submission.submission_id,
            report.submission_fingerprint != submission.fingerprint,
            report.stored_plan_fingerprint != plan_fingerprint,
            report.policy_fingerprint != policy_fingerprint,
            report.assignment_manifest_fingerprint != manifest_fingerprint,
            report.split_fingerprint != split_fingerprint,
            report.preregistration_fingerprint != legacy_fingerprint,
            report.preregistration_v2_fingerprint != preregistration.fingerprint,
            report.constellation_fingerprint != constellation_fingerprint,
            sealed_report.report_fingerprint != report.fingerprint,
            sealed_report.definition_fingerprint != report.definition.fingerprint,
            sealed_report.derived_at != report.source_observed_at,
        )
    )
    metric_by_key = {item.metric_key: item for item in report.metric_reports}
    questions = {item.metric_key: item for item in plan.question_specs}
    specs = {item.metric_key: item for item in legacy.metric_specs}
    metric_mismatches = len(set(metric_by_key) ^ set(questions)) + len(
        set(metric_by_key) ^ set(specs)
    )
    for key, metric in metric_by_key.items():
        if key not in questions or key not in specs:
            continue
        identity = metric.comparison_identity
        metric_mismatches += sum(
            (
                identity.metric_key != key,
                identity.gate_policy_fingerprint != policy_fingerprint,
                identity.split_fingerprint != split_fingerprint,
                identity.submission_fingerprint != submission.fingerprint,
                identity.report_definition_fingerprint != report.definition.fingerprint,
                identity.estimator_configuration_fingerprint != plan_fingerprint,
                identity.constellation_fingerprint != constellation_fingerprint,
            )
        )
    try:
        expected_report = derive_untrusted_calibration_report(
            UntrustedCalibrationProjectionV1(
                campaign=campaign,
                submission=submission,
                source_observed_at=sealed_report.derived_at,
            )
        )
        report_rederivation_mismatches = int(expected_report != report)
    except (TypeError, ValueError):
        report_rederivation_mismatches = 1

    partition_mismatches = len(set(assignments) ^ partition_ids)
    nonholdout_ids = set(split.development_case_ids) | set(
        split.active_learning_case_ids
    )
    nonholdout = [assignments[item] for item in nonholdout_ids if item in assignments]
    holdout = [assignments[item] for item in holdout_ids if item in assignments]
    project_overlap = len(
        {item.project_id for item in nonholdout}
        & {item.project_id for item in holdout}
    )
    time_mismatches = int(
        not nonholdout
        or not holdout
        or max(item.observed_at for item in nonholdout)
        >= min(item.observed_at for item in holdout)
    )
    chronology = (
        manifest.frozen_at,
        split.frozen_at,
        constellation.frozen_at,
        legacy.registered_at,
        preregistration.registered_at,
        campaign.registered_at,
        submission.expected_attempt_manifest.frozen_at,
        submission.submitted_at,
        sealed_report.derived_at,
    )
    chronology_mismatches = sum(
        right < left for left, right in zip(chronology, chronology[1:], strict=False)
    )
    holdout_activity = (
        *(
            item.launched_at
            for item in submission.attempt_launches
            if item.case_id in holdout_ids
        ),
        *(
            item.started_at
            for item in submission.attempt_outcomes
            if item.case_id in holdout_ids
        ),
        *(
            item.selected_at
            for item in submission.candidate_projections
            if item.case_id in holdout_ids
        ),
        *(
            item.evaluated_at
            for item in submission.deterministic_baseline_projections
            if item.case_id in holdout_ids
        ),
        *(
            item.observed_at
            for item in submission.objective_truth_projections
            if item.case_id in holdout_ids
        ),
        *(
            item.created_at
            for item in submission.blind_human_judgments
            if item.case_id in holdout_ids
        ),
    )
    holdout_chronology_mismatches = sum(
        item <= campaign.registered_at for item in holdout_activity
    )

    expected_by_id = {
        item.attempt_id: item for item in submission.expected_attempt_manifest.attempts
    }
    launches = {item.attempt_id: item for item in submission.attempt_launches}
    outcomes = {item.attempt_id: item for item in submission.attempt_outcomes}
    estimates = {item.receipt_id: item for item in submission.structured_estimate_receipts}
    attempt_set_mismatches = len(set(expected_by_id) ^ set(launches)) + len(
        set(expected_by_id) ^ set(outcomes)
    )
    stage_by_ordinal = {item.ordinal: item for item in plan.stages}
    constellation_by_ordinal = {item.ordinal: item for item in constellation.stages}
    launch_lineage_mismatches = 0
    plan_identity_mismatches = 0
    runner_configuration_mismatches = 0
    for attempt_id, launch in launches.items():
        expected = expected_by_id.get(attempt_id)
        assignment = assignments.get(launch.case_id)
        stage = stage_by_ordinal.get(launch.stage_ordinal)
        constellation_stage = constellation_by_ordinal.get(launch.stage_ordinal)
        artifact = stage.model_artifact if stage is not None else None
        launch_lineage_mismatches += int(
            expected is None
            or assignment is None
            or (
                expected.execution_id,
                expected.case_id,
                expected.plan_fingerprint,
                expected.metric_question_fingerprint,
                expected.evidence_packet_fingerprint,
                expected.constellation_stage_fingerprint,
                expected.stage_configuration_sha256,
                expected.stage_ordinal,
                expected.stage_kind,
            )
            != (
                launch.execution_id,
                launch.case_id,
                launch.plan_fingerprint,
                launch.metric_question_fingerprint,
                launch.evidence_packet_fingerprint,
                launch.constellation_stage_fingerprint,
                launch.stage_configuration_sha256,
                launch.stage_ordinal,
                launch.stage_kind,
            )
            or launch.campaign_id != campaign.campaign_id
            or launch.plan_fingerprint != plan_fingerprint
            or (
                assignment is not None
                and (
                    launch.metric_question_fingerprint
                    != assignment.metric_question_fingerprint
                    or launch.evidence_packet_fingerprint
                    != assignment.evidence_packet_fingerprint
                )
            )
        )
        plan_identity_mismatches += int(
            artifact is None
            or launch.model_artifact_fingerprint
            != (artifact.canonical_fingerprint if artifact is not None else None)
            or launch.requested_source
            is not (artifact.source if artifact is not None else None)
            or launch.requested_model_id
            != (artifact.requested_model_id if artifact is not None else None)
            or launch.requested_revision
            != (artifact.requested_revision if artifact is not None else None)
            or launch.requested_execution_mode
            is not (
                artifact.requested_execution_mode if artifact is not None else None
            )
        )
        runner_configuration_mismatches += int(
            stage is None
            or constellation_stage is None
            or launch.stage_kind is not stage.kind
            or launch.stage_configuration_sha256 != stage.configuration_sha256
            or launch.response_schema_version != stage.output_schema_version
            or launch.constellation_stage_fingerprint
            != (
                constellation_stage.stage_fingerprint
                if constellation_stage is not None
                else None
            )
        )

    outcome_lineage_mismatches = 0
    served_binding_mismatches = 0
    for attempt_id, outcome in outcomes.items():
        launch = launches.get(attempt_id)
        stage = (
            stage_by_ordinal.get(launch.stage_ordinal) if launch is not None else None
        )
        artifact = stage.model_artifact if stage is not None else None
        outcome_lineage_mismatches += int(
            launch is None
            or (
                outcome.campaign_id,
                outcome.execution_id,
                outcome.case_id,
                outcome.plan_fingerprint,
                outcome.metric_question_fingerprint,
                outcome.evidence_packet_fingerprint,
                outcome.started_at,
            )
            != (
                launch.campaign_id,
                launch.execution_id,
                launch.case_id,
                launch.plan_fingerprint,
                launch.metric_question_fingerprint,
                launch.evidence_packet_fingerprint,
                launch.launched_at,
            )
        )
        served = outcome.served_identity
        if served.state is ServedIdentityState.OBSERVED:
            served_binding_mismatches += int(
                artifact is None
                or served.served_source
                is not (artifact.source if artifact is not None else None)
                or served.served_model_id
                != (artifact.served_model_id if artifact is not None else None)
                or served.served_revision
                != (artifact.served_revision if artifact is not None else None)
                or served.served_execution_mode
                is not (
                    artifact.served_execution_mode if artifact is not None else None
                )
            )

    structured_mismatches = 0
    for estimate in estimates.values():
        outcome = outcomes.get(estimate.attempt_id)
        structured_mismatches += int(
            outcome is None
            or outcome.state is not AttemptTerminalState.SUCCESS
            or estimate.outcome_id != outcome.outcome_id
            or estimate.outcome_fingerprint != outcome.fingerprint
            or estimate.structured_output_fingerprint
            != outcome.structured_output_fingerprint
            or (
                estimate.campaign_id,
                estimate.case_id,
                estimate.plan_fingerprint,
                estimate.metric_question_fingerprint,
                estimate.evidence_packet_fingerprint,
            )
            != (
                outcome.campaign_id,
                outcome.case_id,
                outcome.plan_fingerprint,
                outcome.metric_question_fingerprint,
                outcome.evidence_packet_fingerprint,
            )
        )
    candidate_mismatches = 0
    for projection in submission.candidate_projections:
        outcome = outcomes.get(projection.attempt_id)
        estimate = estimates.get(projection.estimate_receipt_id)
        candidate_mismatches += int(
            outcome is None
            or estimate is None
            or projection.outcome_id != (outcome.outcome_id if outcome else None)
            or projection.outcome_fingerprint
            != (outcome.fingerprint if outcome else None)
            or projection.estimate_receipt_fingerprint
            != (estimate.fingerprint if estimate else None)
            or (estimate is not None and estimate.attempt_id != projection.attempt_id)
            or projection.case_id not in holdout_ids
        )
    baseline_mismatches = sum(
        item.case_id not in holdout_ids
        or item.plan_fingerprint != plan_fingerprint
        or item.case_id not in assignments
        or (
            item.case_id in assignments
            and (
                item.metric_question_fingerprint
                != assignments[item.case_id].metric_question_fingerprint
                or item.evidence_packet_fingerprint
                != assignments[item.case_id].evidence_packet_fingerprint
            )
        )
        for item in submission.deterministic_baseline_projections
    )
    objective_mismatches = sum(
        item.case_id not in holdout_ids
        or item.plan_fingerprint != plan_fingerprint
        or item.case_id not in assignments
        or (
            item.case_id in assignments
            and (
                item.metric_question_fingerprint
                != assignments[item.case_id].metric_question_fingerprint
                or item.evidence_packet_fingerprint
                != assignments[item.case_id].evidence_packet_fingerprint
            )
        )
        for item in submission.objective_truth_projections
    )

    judgments = {item.judgment_id: item for item in submission.blind_human_judgments}
    blind_lineage_mismatches = 0
    independence_mismatches = 0
    for adjudication in submission.blind_human_adjudications:
        bound = [judgments.get(item) for item in adjudication.judgment_ids]
        blind_lineage_mismatches += int(
            adjudication.case_id not in holdout_ids
            or adjudication.plan_fingerprint != plan_fingerprint
            or any(item is None for item in bound)
            or any(
                item is not None
                and (
                    item.case_id != adjudication.case_id
                    or item.plan_fingerprint != adjudication.plan_fingerprint
                    or item.metric_question_fingerprint
                    != adjudication.metric_question_fingerprint
                    or item.evidence_packet_fingerprint
                    != adjudication.evidence_packet_fingerprint
                    or item.annotation_protocol_version
                    != adjudication.annotation_protocol_version
                    or item.created_at > adjudication.completed_at
                )
                for item in bound
            )
        )
        participants = {
            item.participant_id for item in bound if item is not None
        }
        independence_mismatches += int(
            len(participants) < 2
            or adjudication.adjudicator_id in participants
            or not adjudication.blinded_to_candidate
            or any(
                item is not None
                and (
                    not item.blinded_to_candidate
                    or item.participant_kind is HumanParticipantKind.ADJUDICATOR
                )
                for item in bound
            )
        )

    stability_mismatches = 0
    for series in submission.stability_series:
        for index, trial in enumerate(series.trials, start=1):
            outcome = outcomes.get(trial.attempt_id)
            estimate = estimates.get(trial.estimate_receipt_id)
            stability_mismatches += int(
                trial.trial_ordinal != index
                or trial.condition is not series.condition
                or trial.case_id != series.case_id
                or trial.plan_fingerprint != series.plan_fingerprint
                or trial.metric_question_fingerprint
                != series.metric_question_fingerprint
                or trial.evidence_packet_fingerprint
                != series.evidence_packet_fingerprint
                or outcome is None
                or estimate is None
                or trial.outcome_id != (outcome.outcome_id if outcome else None)
                or trial.outcome_fingerprint
                != (outcome.fingerprint if outcome else None)
                or trial.estimate_receipt_fingerprint
                != (estimate.fingerprint if estimate else None)
            )

    scan = submission.privacy_scan
    required_artifacts = {
        item.structured_output_fingerprint
        for item in submission.attempt_outcomes
        if item.structured_output_fingerprint is not None
    } | {
        item.final_estimate_fingerprint
        for item in submission.deterministic_baseline_projections
    } | {
        item.objective_evidence_fingerprint
        for item in submission.objective_truth_projections
    }
    privacy_mismatches = sum(
        (
            scan.campaign_id != campaign.campaign_id,
            scan.manifest.campaign_id != campaign.campaign_id,
            not required_artifacts.issubset(
                scan.manifest.expected_artifact_fingerprints
            ),
            any(
                item.campaign_id != campaign.campaign_id
                or item.artifact_fingerprint
                not in scan.manifest.scanned_artifact_fingerprints
                for item in scan.manifest.findings
            ),
        )
    )
    access = submission.holdout_access_audit
    access_mismatches = sum(
        (
            access.campaign_id != campaign.campaign_id,
            access.manifest.campaign_id != campaign.campaign_id,
            access.holdout_case_ids != split.holdout_case_ids,
            any(item.case_id not in holdout_ids for item in access.manifest.events),
        )
    )

    return [
        _integrity("integrity.campaign_lineage", campaign_mismatches),
        _integrity("integrity.submission_lineage", submission_mismatches),
        _integrity("integrity.report_lineage", report_mismatches),
        _integrity("integrity.report_metric_identity", metric_mismatches),
        _integrity("integrity.report_rederivation", report_rederivation_mismatches),
        _integrity(
            "integrity.evaluator_definition",
            int(FIXED_GATE_DECISION_DEFINITION.activation_allowed is not False),
        ),
        _integrity("integrity.partition_membership", partition_mismatches),
        _integrity("integrity.project_separation", project_overlap),
        _integrity("integrity.time_separation", time_mismatches),
        _integrity("integrity.preregistration_chronology", chronology_mismatches),
        _integrity(
            "integrity.holdout_activity_chronology",
            holdout_chronology_mismatches,
        ),
        _integrity("integrity.expected_attempt_set", attempt_set_mismatches),
        _integrity("integrity.launch_lineage", launch_lineage_mismatches),
        _integrity("integrity.outcome_lineage", outcome_lineage_mismatches),
        _integrity(
            "integrity.structured_estimate_lineage", structured_mismatches
        ),
        _integrity("integrity.candidate_projection_lineage", candidate_mismatches),
        _integrity(
            "integrity.deterministic_baseline_lineage", baseline_mismatches
        ),
        _integrity("integrity.objective_truth_lineage", objective_mismatches),
        _integrity("integrity.blind_human_lineage", blind_lineage_mismatches),
        _integrity(
            "integrity.blind_human_independence", independence_mismatches
        ),
        _integrity("integrity.stability_lineage", stability_mismatches),
        _integrity("integrity.privacy_lineage", privacy_mismatches),
        _integrity("integrity.access_lineage", access_mismatches),
        _integrity("integrity.identity.plan_binding", plan_identity_mismatches),
        _integrity(
            "integrity.identity.runner_configuration",
            runner_configuration_mismatches,
        ),
        _fixed_unthresholded(
            "integrity.identity.runner_preregistration",
            "runner_identity_not_preregistered",
            category=GateDecisionCheckCategory.INTEGRITY,
        ),
        _integrity("integrity.identity.served_binding", served_binding_mismatches),
    ]


def _validate_lineage(
    campaign: PreregisteredEstimatorCampaign,
    submission: CalibrationEvidenceSubmissionV1,
    sealed_report: RepositorySealedCalibrationReportV1,
) -> None:
    report = sealed_report.report
    expected = (
        submission.campaign_id == campaign.campaign_id,
        report.campaign_id == campaign.campaign_id,
        report.campaign_fingerprint == campaign.fingerprint,
        report.submission_id == submission.submission_id,
        report.submission_fingerprint == submission.fingerprint,
        report.stored_plan_fingerprint == campaign.stored_plan.canonical_fingerprint,
        report.policy_fingerprint == campaign.policy.fingerprint,
        report.assignment_manifest_fingerprint == campaign.assignment_manifest.fingerprint,
        report.split_fingerprint == campaign.split.fingerprint,
        report.preregistration_fingerprint == campaign.legacy_preregistration.fingerprint,
        report.preregistration_v2_fingerprint == campaign.preregistration_v2.fingerprint,
        report.constellation_fingerprint == campaign.constellation_identity.fingerprint,
        sealed_report.definition_fingerprint == report.definition.fingerprint,
        sealed_report.report_fingerprint == report.fingerprint,
        sealed_report.derived_at == report.source_observed_at,
    )
    if not all(expected):
        raise ValueError("sealed campaign, submission, and report lineage mismatch")


def derive_repository_sealed_gate_decision_v1(
    campaign: PreregisteredEstimatorCampaign,
    submission: CalibrationEvidenceSubmissionV1,
    sealed_report: RepositorySealedCalibrationReportV1,
    *,
    derived_at: datetime,
) -> RepositorySealedGateDecisionV1:
    """Derive every v20 check without caller-provided facts or outcomes."""

    campaign = revalidate_content_free_contract(PreregisteredEstimatorCampaign, campaign)
    submission = revalidate_calibration_evidence_submission_v1(submission)
    sealed_report = revalidate_repository_sealed_calibration_report_v1(sealed_report)
    derived_at = _utc(derived_at)
    _validate_lineage(campaign, submission, sealed_report)
    report = sealed_report.report
    if derived_at < sealed_report.derived_at:
        raise ValueError("gate decision cannot predate its sealed report")

    policy = campaign.policy
    split = campaign.split
    manifest = campaign.assignment_manifest
    assignments = {item.case_id: item for item in manifest.assignments}
    holdout = [assignments[item] for item in split.holdout_case_ids]
    active = [assignments[item] for item in split.active_learning_case_ids]
    active_count = len(split.active_learning_case_ids)
    checks = _computed_integrity_checks(campaign, submission, sealed_report)

    synthetic_stage_count = sum(
        item.model_artifact is not None
        and item.model_artifact.source is ModelSource.SYNTHETIC
        for item in campaign.stored_plan.stages
    )
    high_risk_specs = {
        item.metric_key: item
        for item in campaign.legacy_preregistration.metric_specs
        if item.risk_tier is MetricRiskTier.HIGH
    }
    rules = {item.metric_key: item for item in policy.high_risk_precision_rules}
    high_risk_registration_mismatches = len(set(high_risk_specs) ^ set(rules))
    calibration_assignments = (*active, *holdout)
    representative_private_count = sum(
        item.origin is CaseOrigin.PRIVATE_REPRESENTATIVE
        and item.provider is not Provider.SYNTHETIC
        for item in calibration_assignments
    )
    checks.extend(
        (
            _known(
                "policy.stored_plan.non_synthetic",
                _count(synthetic_stage_count, "stages"),
                GateDecisionOperator.EQ,
                _count(0, "stages"),
            ),
            _complete_count(
                "policy.representative_private_evidence",
                representative_private_count,
                len(calibration_assignments),
                "cases",
                "private_evidence_incomplete",
            ),
            _complete_count(
                "policy.active_learning.minimum",
                active_count,
                policy.minimum_active_learning_count,
                "cases",
                "active_learning_sample_incomplete",
            ),
            _known(
                "policy.active_learning.maximum",
                _count(active_count, "cases"),
                GateDecisionOperator.LTE,
                _count(policy.maximum_active_learning_count, "cases"),
            ),
            _complete_count(
                "policy.holdout.total",
                len(holdout),
                policy.minimum_holdout_count,
                "cases",
                "holdout_incomplete",
            ),
            _known(
                "policy.high_risk.registration",
                _count(high_risk_registration_mismatches, "mismatches"),
                GateDecisionOperator.EQ,
                _count(0, "mismatches"),
            ),
        )
    )

    active_strata = Counter(item.task_stratum for item in active)
    active_languages = Counter(item.language for item in active)
    holdout_strata = Counter(item.task_stratum for item in holdout)
    holdout_languages = Counter(item.language for item in holdout)
    for stratum in policy.required_strata:
        checks.extend(
            (
                _complete_count(
                    f"policy.active_learning.stratum.{stratum.value}",
                    active_strata.get(stratum, 0),
                    1,
                    "cases",
                    "active_learning_stratum_missing",
                ),
                _complete_count(
                    f"policy.holdout.stratum.{stratum.value}",
                    holdout_strata.get(stratum, 0),
                    policy.minimum_holdout_per_stratum,
                    "cases",
                    "holdout_stratum_incomplete",
                ),
            )
        )
    for language in policy.required_languages:
        checks.extend(
            (
                _complete_count(
                    f"policy.active_learning.language.{language.value}",
                    active_languages.get(language, 0),
                    1,
                    "cases",
                    "active_learning_language_missing",
                ),
                _complete_count(
                    f"policy.holdout.language.{language.value}",
                    holdout_languages.get(language, 0),
                    policy.minimum_holdout_per_language,
                    "cases",
                    "holdout_language_incomplete",
                ),
            )
        )

    holdout_ids = set(split.holdout_case_ids)
    holdout_outcomes = tuple(
        item for item in submission.attempt_outcomes if item.case_id in holdout_ids
    )
    observed_identity_count = sum(
        item.served_identity.state is ServedIdentityState.OBSERVED
        for item in holdout_outcomes
    )
    unavailable_identity_count = sum(
        item.served_identity.state is ServedIdentityState.UNAVAILABLE
        for item in holdout_outcomes
    )
    fallback_count = sum(
        item.served_identity.fallback_used is True for item in holdout_outcomes
    )
    checks.extend(
        (
            _complete_count(
                "policy.identity.served_coverage",
                observed_identity_count,
                len(holdout_outcomes),
                "attempts",
                "served_identity_incomplete",
            ),
            _absence_check(
                "policy.identity.unavailable",
                unavailable_identity_count,
                "attempts",
                "served_identity_unavailable",
                incomplete=True,
            ),
            _absence_check(
                "policy.identity.fallback",
                fallback_count,
                "attempts",
                "served_identity_fallback",
            ),
        )
    )

    access = submission.holdout_access_audit
    access_activity = (
        *(item.launched_at for item in submission.attempt_launches if item.case_id in holdout_ids),
        *(item.finished_at for item in holdout_outcomes),
        *(item.selected_at for item in submission.candidate_projections if item.case_id in holdout_ids),
        *(item.evaluated_at for item in submission.deterministic_baseline_projections if item.case_id in holdout_ids),
        *(item.observed_at for item in submission.objective_truth_projections if item.case_id in holdout_ids),
        *(item.created_at for item in submission.blind_human_judgments if item.case_id in holdout_ids),
        *(item.completed_at for item in submission.blind_human_adjudications if item.case_id in holdout_ids),
        *(item.frozen_at for item in submission.stability_series if item.case_id in holdout_ids),
        access.holdout_unsealed_at,
    )
    access_window_complete = bool(access_activity) and (
        access.manifest.coverage_started_at <= min(access_activity)
        and access.manifest.coverage_ended_at >= max(access_activity)
    )
    checks.extend(
        (
            _complete_count(
                "policy.access.coverage",
                int(access_window_complete),
                1,
                "complete_windows",
                "access_audit_window_incomplete",
            ),
            _absence_check(
                "policy.access.gaps",
                access.manifest.gap_count,
                "gaps",
                "access_audit_gaps_present",
                incomplete=True,
            ),
            _absence_check(
                "policy.access.prohibited_pre_unseal",
                access.prohibited_pre_unseal_count,
                "events",
                "prohibited_pre_unseal_access",
            ),
            _absence_check(
                "policy.access.unauthorized",
                access.unauthorized_access_count,
                "events",
                "unauthorized_holdout_access",
            ),
        )
    )

    scan = submission.privacy_scan
    required_artifacts = {
        item.structured_output_fingerprint
        for item in submission.attempt_outcomes
        if item.structured_output_fingerprint is not None
    } | {
        item.final_estimate_fingerprint
        for item in submission.deterministic_baseline_projections
    } | {
        item.objective_evidence_fingerprint
        for item in submission.objective_truth_projections
    }
    scanned_required = required_artifacts.intersection(
        scan.manifest.scanned_artifact_fingerprints
    )
    checks.extend(
        (
            _absence_check(
                "policy.privacy.findings",
                scan.finding_count,
                "findings",
                "privacy_findings_present",
            ),
            _absence_check(
                "policy.privacy.unscanned",
                scan.manifest.unscanned_artifact_count,
                "artifacts",
                "privacy_scan_incomplete",
                incomplete=True,
            ),
            _complete_count(
                "policy.privacy.scan_coverage",
                len(scanned_required),
                len(required_artifacts),
                "artifacts",
                "required_artifacts_unscanned",
            ),
        )
    )

    metric_by_key = {item.metric_key: item for item in report.metric_reports}
    metric_keys = tuple(
        sorted(
            {
                *(item.metric_key for item in campaign.stored_plan.question_specs),
                *(item.metric_key for item in campaign.legacy_preregistration.metric_specs),
                *(item.metric_key for item in report.metric_reports),
                *(item.metric_key for item in policy.high_risk_precision_rules),
            }
        )
    )
    high_risk_metric_keys = set(high_risk_specs) | set(rules)
    for key in metric_keys:
        metric = metric_by_key.get(key)
        metric_holdout = tuple(item for item in holdout if item.metric_key == key)
        metric_holdout_count = len(metric_holdout)
        checks.append(
            _complete_count(
                f"policy.holdout.metric.{key}",
                metric_holdout_count,
                policy.minimum_holdout_per_metric,
                "cases",
                "metric_holdout_incomplete",
            )
        )
        checks.extend(_unsupported_policy_checks(key, campaign))

        measurement_specs = (
            (
                f"policy.calibration_ece.{key}",
                "calibration.selected_confidence_ece",
                GateDecisionOperator.LTE,
                _rate(policy.maximum_ece),
            ),
            (
                f"policy.stability.repeat.{key}",
                "stability.repeat",
                GateDecisionOperator.GTE,
                _rate(policy.minimum_repeat_stability),
            ),
            (
                f"policy.false_confident_error_rate.{key}",
                "calibration.false_confident_error_rate",
                GateDecisionOperator.LTE,
                _rate(policy.maximum_false_confident_error_rate),
            ),
            (
                f"policy.oom_rate.{key}",
                "resource.oom_rate",
                GateDecisionOperator.LTE,
                _rate(policy.maximum_oom_rate),
            ),
            (
                f"policy.error_rate.{key}",
                "resource.error_rate",
                GateDecisionOperator.LTE,
                _rate(policy.maximum_error_rate),
            ),
            (
                f"policy.refusal_rate.{key}",
                "resource.refusal_rate",
                GateDecisionOperator.LTE,
                _rate(policy.maximum_refusal_rate),
            ),
        )
        for check_key, measurement_key, operator, threshold in measurement_specs:
            checks.append(
                _unknown(
                    check_key,
                    threshold,
                    operator,
                    "metric_report_unavailable",
                )
                if metric is None
                else _measurement_check(
                    check_key,
                    _measurement(metric, measurement_key),
                    operator,
                    threshold,
                )
            )

        for latency_class, maximum_latency_ms in (
            ("cold", policy.maximum_cold_p95_latency_ms),
            ("warm", policy.maximum_warm_p95_latency_ms),
        ):
            sample_key = f"policy.{latency_class}_latency_samples.{key}"
            value_key = f"policy.{latency_class}_latency_p95.{key}"
            if metric is None:
                checks.extend(
                    (
                        _unknown(
                            sample_key,
                            _count(
                                policy.minimum_operational_samples_per_latency_class,
                                "samples",
                            ),
                            GateDecisionOperator.GTE,
                            "metric_report_unavailable",
                        ),
                        _unknown(
                            value_key,
                            _scalar(maximum_latency_ms, "milliseconds"),
                            GateDecisionOperator.LTE,
                            "metric_report_unavailable",
                        ),
                    )
                )
                continue
            checks.extend(
                _operational_latency_checks(
                    sample_key=sample_key,
                    value_key=value_key,
                    item=_measurement(
                        metric, f"resource.{latency_class}_latency_p95_ms"
                    ),
                    required_samples=(
                        policy.minimum_operational_samples_per_latency_class
                    ),
                    maximum_latency_ms=maximum_latency_ms,
                )
            )

        coverage_specs = (
            (
                f"policy.candidate_projection_coverage.{key}",
                "coverage.candidate_known",
                "candidate_projection_incomplete",
            ),
            (
                f"policy.deterministic_baseline_coverage.{key}",
                "coverage.baseline_known",
                "deterministic_baseline_incomplete",
            ),
            (
                f"policy.objective_or_human_truth_coverage.{key}",
                "coverage.truth_known",
                "truth_evidence_incomplete",
            ),
            (
                f"policy.human_adjudication_coverage.{key}",
                "coverage.human_adjudicated",
                "human_adjudication_incomplete",
            ),
        )
        for check_key, measurement_key, reason in coverage_specs:
            checks.append(
                _unknown(
                    check_key,
                    _count(metric_holdout_count, "cases"),
                    GateDecisionOperator.GTE,
                    "metric_report_unavailable",
                )
                if metric is None
                else _measurement_complete_count_check(
                    check_key,
                    _measurement(metric, measurement_key),
                    metric_holdout_count,
                    "cases",
                    reason,
                )
            )

        if metric is None:
            checks.extend(
                (
                    _unknown(
                        f"policy.selective_coverage.{key}",
                        _rate(policy.minimum_selective_coverage),
                        GateDecisionOperator.GTE,
                        "metric_report_unavailable",
                    ),
                    _unknown(
                        f"policy.selective_risk.{key}",
                        _rate(policy.maximum_selective_risk),
                        GateDecisionOperator.LTE,
                        "metric_report_unavailable",
                    ),
                )
            )
        else:
            checks.extend(
                (
                    _selective_check(
                        f"policy.selective_coverage.{key}",
                        metric,
                        coverage=True,
                        operator=GateDecisionOperator.GTE,
                        threshold=policy.minimum_selective_coverage,
                    ),
                    _selective_check(
                        f"policy.selective_risk.{key}",
                        metric,
                        coverage=False,
                        operator=GateDecisionOperator.LTE,
                        threshold=policy.maximum_selective_risk,
                    ),
                )
            )

        for condition in (
            StabilityCondition.ORDER,
            StabilityCondition.FORMAT,
            StabilityCondition.INJECTION,
        ):
            checks.append(
                _fixed_unthresholded(
                    f"policy.stability.{condition.value}.{key}",
                    "stability_threshold_not_preregistered",
                )
            )

        for dimension in policy.subgroup_dimensions:
            grouped: dict[str, int] = defaultdict(int)
            for assignment in metric_holdout:
                group_key = {
                    SubgroupDimension.TASK_STRATUM: assignment.task_stratum.value,
                    SubgroupDimension.LANGUAGE: assignment.language.value,
                    SubgroupDimension.PROVIDER: assignment.provider.value,
                    SubgroupDimension.EVIDENCE_TIER: assignment.evidence_tier.value,
                }[dimension]
                grouped[group_key] += 1
            minimum_group_size = min(grouped.values(), default=0)
            checks.extend(
                (
                    _complete_count(
                        f"policy.subgroup.minimum.{dimension.value}.{key}",
                        minimum_group_size,
                        policy.minimum_subgroup_size,
                        "cases",
                        "subgroup_sample_incomplete",
                    ),
                    _unknown(
                        f"policy.subgroup.regression.{dimension.value}.{key}",
                        _scalar(
                            -policy.maximum_material_subgroup_regression,
                            "score",
                        ),
                        GateDecisionOperator.GTE,
                        (
                            "evidence_tier_comparison_not_recorded"
                            if dimension is SubgroupDimension.EVIDENCE_TIER
                            else "subgroup_baseline_comparison_not_recorded"
                        ),
                        unsupported=True,
                    ),
                )
            )

        if key not in high_risk_metric_keys:
            continue
        rule = rules.get(key)
        spec = high_risk_specs.get(key)
        if rule is None:
            checks.extend(
                (
                    _fixed_unthresholded(
                        f"policy.high_risk_positive_predictions.{key}",
                        "high_risk_rule_not_registered",
                    ),
                    _fixed_unthresholded(
                        f"policy.high_risk_precision.{key}",
                        "high_risk_rule_not_registered",
                    ),
                )
            )
            continue
        if spec is None or metric is None:
            reason = (
                "high_risk_metric_not_registered"
                if spec is None
                else "metric_report_unavailable"
            )
            checks.extend(
                (
                    _unknown(
                        f"policy.high_risk_positive_predictions.{key}",
                        _count(rule.minimum_positive_predictions, "predictions"),
                        GateDecisionOperator.GTE,
                        reason,
                    ),
                    _unknown(
                        f"policy.high_risk_precision.{key}",
                        _rate(rule.minimum_precision),
                        GateDecisionOperator.GTE,
                        reason,
                    ),
                )
            )
            continue
        overall_scope = _overall(metric).scope_id
        receipt = next(
            (
                item
                for item in metric.class_receipts
                if item.scope_id == overall_scope
                and item.label_code == spec.positive_label
            ),
            None,
        )
        if receipt is None:
            checks.extend(
                (
                    _unknown(
                        f"policy.high_risk_positive_predictions.{key}",
                        _count(rule.minimum_positive_predictions, "predictions"),
                        GateDecisionOperator.GTE,
                        "class_receipt_unavailable",
                    ),
                    _unknown(
                        f"policy.high_risk_precision.{key}",
                        _rate(rule.minimum_precision),
                        GateDecisionOperator.GTE,
                        "class_receipt_unavailable",
                    ),
                )
            )
        elif receipt.predicted_count < rule.minimum_positive_predictions:
            checks.extend(
                (
                    _unknown(
                        f"policy.high_risk_positive_predictions.{key}",
                        _count(rule.minimum_positive_predictions, "predictions"),
                        GateDecisionOperator.GTE,
                        "positive_predictions_below_minimum",
                    ),
                    _unknown(
                        f"policy.high_risk_precision.{key}",
                        _rate(rule.minimum_precision),
                        GateDecisionOperator.GTE,
                        "positive_predictions_below_minimum",
                    ),
                )
            )
        else:
            checks.extend(
                (
                    _known(
                        f"policy.high_risk_positive_predictions.{key}",
                        _count(receipt.predicted_count, "predictions"),
                        GateDecisionOperator.GTE,
                        _count(rule.minimum_positive_predictions, "predictions"),
                    ),
                    _known(
                        f"policy.high_risk_precision.{key}",
                        _rate(receipt.precision),
                        GateDecisionOperator.GTE,
                        _rate(rule.minimum_precision),
                    ),
                )
            )

    ordered = tuple(sorted(checks, key=lambda item: item.check_key))
    if tuple(item.check_key for item in ordered) != repository_gate_check_vocabulary(
        campaign, sealed_report
    ):
        raise ValueError("gate evaluator did not emit its exact code-owned vocabulary")
    check_set_fingerprint = canonical_payload_digest(
        [item.model_dump(mode="json") for item in ordered]
    )
    outcome = (
        GateDecisionOutcome.REJECTED
        if any(item.outcome is GateDecisionCheckOutcome.FAIL for item in ordered)
        else GateDecisionOutcome.INSUFFICIENT_DATA
    )
    decision = RepositorySealedGateDecisionV1(
        decision_id=repository_gate_decision_id(
            report.report_id,
            sealed_report.fingerprint,
            FIXED_GATE_DECISION_DEFINITION.fingerprint,
            derived_at,
        ),
        campaign_id=campaign.campaign_id,
        campaign_fingerprint=campaign.fingerprint,
        stored_plan_fingerprint=campaign.stored_plan.canonical_fingerprint,
        policy_fingerprint=campaign.policy.fingerprint,
        assignment_manifest_fingerprint=campaign.assignment_manifest.fingerprint,
        split_fingerprint=campaign.split.fingerprint,
        preregistration_fingerprint=campaign.legacy_preregistration.fingerprint,
        preregistration_v2_fingerprint=campaign.preregistration_v2.fingerprint,
        constellation_fingerprint=campaign.constellation_identity.fingerprint,
        submission_id=submission.submission_id,
        submission_fingerprint=submission.fingerprint,
        report_id=report.report_id,
        report_receipt_id=sealed_report.receipt_id,
        report_fingerprint=sealed_report.report_fingerprint,
        report_receipt_fingerprint=sealed_report.fingerprint,
        report_definition_fingerprint=sealed_report.definition_fingerprint,
        report_source_bundle_fingerprint=report.source_bundle_fingerprint,
        definition=FIXED_GATE_DECISION_DEFINITION,
        definition_fingerprint=FIXED_GATE_DECISION_DEFINITION.fingerprint,
        checks=ordered,
        check_set_fingerprint=check_set_fingerprint,
        outcome=outcome,
        campaign_registered_at=campaign.registered_at,
        submission_submitted_at=submission.submitted_at,
        report_derived_at=sealed_report.derived_at,
        derived_at=derived_at,
    )
    return revalidate_repository_sealed_gate_decision_v1(decision)


__all__ = [
    "derive_repository_sealed_gate_decision_v1",
    "repository_gate_check_vocabulary",
]
