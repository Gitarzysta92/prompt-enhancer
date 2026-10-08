"""Derived estimator activation gate over immutable calibration receipts."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import math
from typing import Callable, Iterable, Sequence

from ...domain import Provider
from .gate_contracts import (
    ActivationGateCheck,
    ActivationGateDecision,
    ActivationOutcome,
    CalibrationLanguage,
    CalibrationReport,
    CalibrationTaskStratum,
    CaseOrigin,
    CaseAssignment,
    CaseRunState,
    EstimatorCase,
    EstimatorSource,
    EvidenceTier,
    GateCheckOutcome,
    GatePolicy,
    LatencyClass,
    MetricGateSpec,
    MetricRiskTier,
    ReferenceTruthSource,
    StabilityCondition,
    SubgroupDimension,
)


_SUPPORTED_TRUTH_SOURCES = frozenset(
    {
        ReferenceTruthSource.OBJECTIVE_CHECK,
        ReferenceTruthSource.HUMAN_ADJUDICATED,
        ReferenceTruthSource.INDEPENDENT_HUMAN,
    }
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("derived_at must be UTC")
    return value


def _check(
    key: str,
    outcome: GateCheckOutcome,
    *,
    actual: float | int | None = None,
    threshold: float | int | None = None,
    reason: str | None = None,
) -> ActivationGateCheck:
    return ActivationGateCheck(
        check_key=key,
        outcome=outcome,
        actual=actual,
        threshold=threshold,
        reason_code=reason,
    )


def _minimum_check(
    key: str,
    actual: float | int | None,
    threshold: float | int,
    *,
    missing_is_insufficient: bool = True,
    strict: bool = False,
    below_is_insufficient: bool = False,
    reason: str = "evidence_missing",
) -> ActivationGateCheck:
    if actual is None:
        return _check(
            key,
            GateCheckOutcome.INSUFFICIENT_DATA
            if missing_is_insufficient
            else GateCheckOutcome.FAIL,
            threshold=threshold,
            reason=reason,
        )
    passed = actual > threshold if strict else actual >= threshold
    return _check(
        key,
        GateCheckOutcome.PASS
        if passed
        else GateCheckOutcome.INSUFFICIENT_DATA
        if below_is_insufficient
        else GateCheckOutcome.FAIL,
        actual=actual,
        threshold=threshold,
        reason=None
        if passed
        else reason
        if below_is_insufficient
        else "threshold_not_met",
    )


def _maximum_check(
    key: str,
    actual: float | int | None,
    threshold: float | int,
    *,
    missing_reason: str = "evidence_missing",
) -> ActivationGateCheck:
    if actual is None:
        return _check(
            key,
            GateCheckOutcome.INSUFFICIENT_DATA,
            threshold=threshold,
            reason=missing_reason,
        )
    passed = actual <= threshold
    return _check(
        key,
        GateCheckOutcome.PASS if passed else GateCheckOutcome.FAIL,
        actual=actual,
        threshold=threshold,
        reason=None if passed else "threshold_exceeded",
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _accuracy(
    cases: Sequence[EstimatorCase],
    label: Callable[[EstimatorCase], str | None],
) -> float | None:
    if not cases:
        return None
    return sum(label(case) == case.reference_label for case in cases) / len(cases)


def _macro_f1_for_metric(
    cases: Sequence[EstimatorCase],
    labels: tuple[str, ...],
    prediction: Callable[[EstimatorCase], str | None],
) -> float | None:
    if not cases:
        return None
    scores: list[float] = []
    for label in labels:
        true_positive = sum(
            prediction(case) == label and case.reference_label == label for case in cases
        )
        false_positive = sum(
            prediction(case) == label and case.reference_label != label for case in cases
        )
        false_negative = sum(
            prediction(case) != label and case.reference_label == label for case in cases
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else (2 * true_positive) / denominator)
    return sum(scores) / len(scores)


def _mean_metric_macro_f1(
    cases: Sequence[EstimatorCase],
    specs: dict[str, MetricGateSpec],
    prediction: Callable[[EstimatorCase], str | None],
) -> float | None:
    scores: list[float] = []
    for metric_key, spec in specs.items():
        metric_cases = [case for case in cases if case.metric_key == metric_key]
        score = _macro_f1_for_metric(metric_cases, spec.label_vocabulary, prediction)
        if score is None:
            return None
        scores.append(score)
    return None if not scores else sum(scores) / len(scores)


def _ece(cases: Sequence[EstimatorCase], bin_count: int = 10) -> float | None:
    answered = [
        case
        for case in cases
        if case.run_state is CaseRunState.COMPLETED
        and case.candidate_label is not None
        and case.candidate_confidence is not None
    ]
    if not answered:
        return None
    bins: dict[int, list[EstimatorCase]] = defaultdict(list)
    for case in answered:
        assert case.candidate_confidence is not None
        index = min(bin_count - 1, int(case.candidate_confidence * bin_count))
        bins[index].append(case)
    total = len(answered)
    result = 0.0
    for members in bins.values():
        confidence = sum(case.candidate_confidence or 0.0 for case in members) / len(members)
        accuracy = sum(
            case.candidate_label == case.reference_label for case in members
        ) / len(members)
        result += (len(members) / total) * abs(accuracy - confidence)
    return result


def _subgroup_value(case: EstimatorCase, dimension: SubgroupDimension) -> str:
    if dimension is SubgroupDimension.TASK_STRATUM:
        return case.task_stratum.value
    if dimension is SubgroupDimension.LANGUAGE:
        return case.language.value
    if dimension is SubgroupDimension.PROVIDER:
        return case.provider.value
    return case.evidence_tier.value


def _decision(
    report: CalibrationReport,
    policy: GatePolicy,
    derived_at: datetime,
    checks: Iterable[ActivationGateCheck],
) -> ActivationGateDecision:
    ordered = tuple(sorted(checks, key=lambda check: check.check_key))
    outcomes = {check.outcome for check in ordered}
    outcome = (
        ActivationOutcome.REJECTED
        if GateCheckOutcome.FAIL in outcomes
        else ActivationOutcome.INSUFFICIENT_DATA
        if GateCheckOutcome.INSUFFICIENT_DATA in outcomes
        else ActivationOutcome.ELIGIBLE
    )
    preregistration = report.evidence_bundle.preregistration
    identity = "|".join(
        (
            report.fingerprint,
            policy.fingerprint,
            preregistration.fingerprint,
            derived_at.isoformat(),
        )
    )
    return ActivationGateDecision(
        decision_id=hashlib.sha256(identity.encode("ascii")).hexdigest(),
        report_fingerprint=report.fingerprint,
        policy_fingerprint=policy.fingerprint,
        preregistration_fingerprint=preregistration.fingerprint,
        outcome=outcome,
        checks=ordered,
        derived_at=derived_at,
    )


def evaluate_activation_gate(
    report: CalibrationReport,
    policy: GatePolicy,
    *,
    derived_at: datetime,
) -> ActivationGateDecision:
    """Derive activation eligibility from a fingerprint-linked evidence report.

    The API intentionally accepts no eligibility hints.  An integrity mismatch
    rejects immediately; absent evidence remains insufficient; synthetic or
    unsupported truth can never activate an estimator.
    """

    derived_at = _utc(derived_at)
    bundle = report.evidence_bundle
    assignment_manifest = bundle.assignment_manifest
    cohort = bundle.cohort
    split = bundle.split
    preregistration = bundle.preregistration
    identity = bundle.estimator_identity
    cases_by_id = {case.case_id: case for case in cohort.cases}
    assignments_by_id = {
        assignment.case_id: assignment
        for assignment in assignment_manifest.assignments
    }
    all_partition_ids = set(split.development_case_ids) | set(
        split.active_learning_case_ids
    ) | set(split.holdout_case_ids)

    integrity_failures = 0
    expected_links = (
        (
            split.assignment_manifest_fingerprint,
            assignment_manifest.fingerprint,
        ),
        (preregistration.policy_fingerprint, policy.fingerprint),
        (
            preregistration.assignment_manifest_fingerprint,
            assignment_manifest.fingerprint,
        ),
        (preregistration.split_fingerprint, split.fingerprint),
        (preregistration.estimator_identity_fingerprint, identity.fingerprint),
    )
    integrity_failures += sum(actual != expected for actual, expected in expected_links)
    integrity_failures += int(all_partition_ids != set(cases_by_id))
    integrity_failures += int(all_partition_ids != set(assignments_by_id))
    integrity_failures += sum(
        CaseAssignment.from_case(case) != assignments_by_id.get(case.case_id)
        for case in cohort.cases
    )
    integrity_failures += int(identity.frozen_at > preregistration.registered_at)
    integrity_failures += int(split.frozen_at > preregistration.registered_at)
    integrity_failures += int(assignment_manifest.frozen_at > split.frozen_at)
    integrity_failures += int(cohort.completed_at > bundle.completed_at)
    integrity_failures += int(
        any(case.evaluated_at > bundle.completed_at for case in cohort.cases)
    )
    integrity_failures += int(
        any(receipt.observed_at > bundle.completed_at for receipt in bundle.stability_receipts)
    )
    if bundle.holdout_access_audit is not None:
        integrity_failures += int(
            bundle.holdout_access_audit.split_fingerprint != split.fingerprint
        )
    if report.privacy_scan is not None:
        integrity_failures += int(
            report.privacy_scan.scanned_bundle_fingerprint != bundle.fingerprint
        )
        integrity_failures += int(report.privacy_scan.completed_at < bundle.completed_at)
        integrity_failures += int(report.privacy_scan.completed_at > report.emitted_at)
    integrity_failures += int(derived_at < report.emitted_at)

    specs = {spec.metric_key: spec for spec in preregistration.metric_specs}
    registered_keys = set(specs)
    observed_keys = {case.metric_key for case in cohort.cases}
    integrity_failures += int(not observed_keys.issubset(registered_keys))
    integrity_failures += sum(
        case.reference_label not in specs[case.metric_key].label_vocabulary
        or (
            case.candidate_label is not None
            and case.candidate_label not in specs[case.metric_key].label_vocabulary
        )
        or (
            case.baseline_label is not None
            and case.baseline_label not in specs[case.metric_key].label_vocabulary
        )
        or (
            case.human_baseline_label is not None
            and case.human_baseline_label not in specs[case.metric_key].label_vocabulary
        )
        for case in cohort.cases
        if case.metric_key in specs
    )
    high_risk_specs = {
        spec.metric_key for spec in specs.values() if spec.risk_tier is MetricRiskTier.HIGH
    }
    high_risk_rules = {rule.metric_key for rule in policy.high_risk_precision_rules}
    integrity_failures += int(high_risk_specs != high_risk_rules)

    manifest_check = _check(
        "manifest_integrity",
        GateCheckOutcome.PASS if integrity_failures == 0 else GateCheckOutcome.FAIL,
        actual=integrity_failures,
        threshold=0,
        reason=None if integrity_failures == 0 else "fingerprint_or_manifest_mismatch",
    )
    if integrity_failures:
        return _decision(report, policy, derived_at, (manifest_check,))

    development = [cases_by_id[case_id] for case_id in split.development_case_ids]
    active = [cases_by_id[case_id] for case_id in split.active_learning_case_ids]
    holdout = [cases_by_id[case_id] for case_id in split.holdout_case_ids]
    calibration_cases = active + holdout
    checks: list[ActivationGateCheck] = [manifest_check]

    synthetic_count = sum(
        case.origin is CaseOrigin.SYNTHETIC or case.provider is Provider.SYNTHETIC
        for case in calibration_cases
    ) + int(identity.source is EstimatorSource.SYNTHETIC)
    checks.append(
        _check(
            "non_synthetic_origin",
            GateCheckOutcome.PASS if synthetic_count == 0 else GateCheckOutcome.FAIL,
            actual=synthetic_count,
            threshold=0,
            reason=None if synthetic_count == 0 else "synthetic_evidence_forbidden",
        )
    )
    activation_boundary_verified = identity.source in {
        EstimatorSource.DETERMINISTIC,
        EstimatorSource.LOCAL_WEIGHTS,
    }
    checks.append(
        _check(
            "activation_boundary",
            GateCheckOutcome.PASS
            if activation_boundary_verified
            else GateCheckOutcome.FAIL,
            actual=1 if activation_boundary_verified else 0,
            threshold=1,
            reason=None
            if activation_boundary_verified
            else "activation_boundary_unverified",
        )
    )
    exact_identity = (
        identity.requested_model_id == identity.served_model_id
        and identity.requested_model_revision == identity.served_model_revision
        and identity.requested_execution_mode == identity.served_execution_mode
    )
    checks.append(
        _check(
            "exact_served_identity",
            GateCheckOutcome.PASS if exact_identity else GateCheckOutcome.FAIL,
            actual=1 if exact_identity else 0,
            threshold=1,
            reason=None if exact_identity else "requested_served_identity_mismatch",
        )
    )
    private_count = sum(
        case.origin is CaseOrigin.PRIVATE_REPRESENTATIVE for case in calibration_cases
    )
    checks.append(
        _check(
            "representative_private_evidence",
            GateCheckOutcome.PASS
            if private_count == len(calibration_cases)
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=private_count,
            threshold=len(calibration_cases),
            reason=None
            if private_count == len(calibration_cases)
            else "private_evidence_incomplete",
        )
    )

    active_count = len(active)
    if active_count < policy.minimum_active_learning_count:
        active_outcome = GateCheckOutcome.INSUFFICIENT_DATA
        active_reason = "active_learning_sample_incomplete"
    elif active_count > policy.maximum_active_learning_count:
        active_outcome = GateCheckOutcome.FAIL
        active_reason = "active_learning_preregistration_bound_exceeded"
    else:
        active_outcome = GateCheckOutcome.PASS
        active_reason = None
    checks.append(
        _check(
            "active_learning_count",
            active_outcome,
            actual=active_count,
            threshold=policy.minimum_active_learning_count,
            reason=active_reason,
        )
    )
    checks.append(
        _minimum_check(
            "holdout_count",
            len(holdout),
            policy.minimum_holdout_count,
            below_is_insufficient=True,
            reason="holdout_incomplete",
        )
    )
    per_metric_counts = Counter(case.metric_key for case in holdout)
    minimum_metric_count = min(
        (per_metric_counts.get(metric_key, 0) for metric_key in registered_keys),
        default=0,
    )
    checks.append(
        _minimum_check(
            "holdout_per_metric",
            minimum_metric_count,
            policy.minimum_holdout_per_metric,
            below_is_insufficient=True,
            reason="metric_holdout_incomplete",
        )
    )

    active_strata = {case.task_stratum for case in active}
    active_languages = {case.language for case in active}
    checks.append(
        _minimum_check(
            "active_learning_strata",
            len(active_strata.intersection(policy.required_strata)),
            len(policy.required_strata),
            below_is_insufficient=True,
            reason="required_strata_missing",
        )
    )
    checks.append(
        _minimum_check(
            "active_learning_languages",
            len(active_languages.intersection(policy.required_languages)),
            len(policy.required_languages),
            below_is_insufficient=True,
            reason="required_languages_missing",
        )
    )
    holdout_strata_counts = Counter(case.task_stratum for case in holdout)
    holdout_language_counts = Counter(case.language for case in holdout)
    min_stratum_count = min(
        (holdout_strata_counts.get(value, 0) for value in policy.required_strata),
        default=0,
    )
    min_language_count = min(
        (holdout_language_counts.get(value, 0) for value in policy.required_languages),
        default=0,
    )
    checks.append(
        _minimum_check(
            "holdout_strata",
            min_stratum_count,
            policy.minimum_holdout_per_stratum,
            below_is_insufficient=True,
            reason="required_strata_missing",
        )
    )
    checks.append(
        _minimum_check(
            "holdout_languages",
            min_language_count,
            policy.minimum_holdout_per_language,
            below_is_insufficient=True,
            reason="required_languages_missing",
        )
    )

    nonholdout = development + active
    holdout_projects = {case.project_id for case in holdout}
    nonholdout_projects = {case.project_id for case in nonholdout}
    project_overlap = len(holdout_projects.intersection(nonholdout_projects))
    checks.append(
        _check(
            "project_separation",
            GateCheckOutcome.PASS if project_overlap == 0 else GateCheckOutcome.FAIL,
            actual=project_overlap,
            threshold=0,
            reason=None if project_overlap == 0 else "project_overlap",
        )
    )
    time_separated = bool(nonholdout and holdout) and max(
        case.observed_at for case in nonholdout
    ) < min(case.observed_at for case in holdout)
    checks.append(
        _check(
            "time_separation",
            GateCheckOutcome.PASS if time_separated else GateCheckOutcome.FAIL,
            actual=1 if time_separated else 0,
            threshold=1,
            reason=None if time_separated else "observation_windows_overlap",
        )
    )

    audit = bundle.holdout_access_audit
    if audit is None:
        checks.append(
            _check(
                "holdout_access_audit",
                GateCheckOutcome.INSUFFICIENT_DATA,
                threshold=0,
                reason="access_audit_missing",
            )
        )
    else:
        access_violations = audit.unauthorized_access_count + audit.missing_event_count
        coverage_complete = (
            audit.coverage_started_at <= split.frozen_at
            and audit.coverage_ended_at >= bundle.completed_at
        )
        if access_violations:
            audit_outcome = GateCheckOutcome.FAIL
            audit_reason = "holdout_access_violation"
        elif not coverage_complete:
            audit_outcome = GateCheckOutcome.INSUFFICIENT_DATA
            audit_reason = "access_audit_window_incomplete"
        else:
            audit_outcome = GateCheckOutcome.PASS
            audit_reason = None
        checks.append(
            _check(
                "holdout_access_audit",
                audit_outcome,
                actual=access_violations,
                threshold=0,
                reason=audit_reason,
            )
        )
    early_holdout_evaluations = sum(
        case.evaluated_at <= preregistration.registered_at for case in holdout
    )
    checks.append(
        _check(
            "holdout_evaluated_after_preregistration",
            GateCheckOutcome.PASS
            if early_holdout_evaluations == 0
            else GateCheckOutcome.FAIL,
            actual=early_holdout_evaluations,
            threshold=0,
            reason=None
            if early_holdout_evaluations == 0
            else "holdout_evaluated_before_preregistration",
        )
    )

    unsupported_truth = sum(
        case.truth_source not in _SUPPORTED_TRUTH_SOURCES for case in calibration_cases
    )
    missing_truth_receipts = sum(case.truth_receipt_id is None for case in calibration_cases)
    truth_failures = unsupported_truth + missing_truth_receipts
    checks.append(
        _check(
            "non_consensus_truth",
            GateCheckOutcome.PASS if truth_failures == 0 else GateCheckOutcome.FAIL,
            actual=truth_failures,
            threshold=0,
            reason=None if truth_failures == 0 else "unsupported_or_unreceipted_truth",
        )
    )
    human_missing = sum(
        case.human_baseline_label is None
        or case.human_adjudication_receipt_id is None
        for case in holdout
    )
    checks.append(
        _check(
            "human_adjudicated_baseline",
            GateCheckOutcome.PASS
            if human_missing == 0
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=len(holdout) - human_missing,
            threshold=len(holdout),
            reason=None if human_missing == 0 else "human_baseline_incomplete",
        )
    )

    privacy = report.privacy_scan
    if privacy is None:
        checks.append(
            _check(
                "privacy_scan",
                GateCheckOutcome.INSUFFICIENT_DATA,
                threshold=0,
                reason="privacy_scan_missing",
            )
        )
    else:
        findings = (
            privacy.pii_finding_count
            + privacy.secret_finding_count
            + privacy.private_content_finding_count
        )
        checks.append(
            _check(
                "privacy_scan",
                GateCheckOutcome.PASS if findings == 0 else GateCheckOutcome.FAIL,
                actual=findings,
                threshold=0,
                reason=None if findings == 0 else "privacy_findings_present",
            )
        )

    baseline_missing = any(case.baseline_label is None for case in holdout)
    human_performance_missing = any(case.human_baseline_label is None for case in holdout)
    candidate_performance = _mean_metric_macro_f1(
        holdout, specs, lambda case: case.candidate_label
    )
    baseline_performance = (
        None
        if baseline_missing
        else _mean_metric_macro_f1(holdout, specs, lambda case: case.baseline_label)
    )
    human_performance = (
        None
        if human_performance_missing
        else _mean_metric_macro_f1(
            holdout, specs, lambda case: case.human_baseline_label
        )
    )
    baseline_margin = (
        None
        if candidate_performance is None or baseline_performance is None
        else candidate_performance - baseline_performance
    )
    checks.append(
        _minimum_check(
            "beats_baseline",
            baseline_margin,
            policy.minimum_baseline_margin,
            strict=True,
            reason="baseline_comparison_missing",
        )
    )
    human_gap = (
        None
        if candidate_performance is None or human_performance is None
        else abs(candidate_performance - human_performance)
    )
    checks.append(
        _maximum_check(
            "human_performance_gap",
            human_gap,
            policy.maximum_human_gap,
            missing_reason="human_comparison_missing",
        )
    )
    checks.append(
        _maximum_check(
            "expected_calibration_error",
            _ece(holdout),
            policy.maximum_ece,
            missing_reason="calibration_observations_missing",
        )
    )

    repeat_receipts = {
        receipt.case_id: receipt
        for receipt in bundle.stability_receipts
        if receipt.condition is StabilityCondition.REPEAT
    }
    missing_repeat = set(split.holdout_case_ids).difference(repeat_receipts)
    mismatched_repeat = sum(
        bool(receipt.trial_labels)
        and receipt.trial_labels[0] != cases_by_id[case_id].candidate_label
        for case_id, receipt in repeat_receipts.items()
        if case_id in cases_by_id and case_id in split.holdout_case_ids
    )
    extra_repeat = set(repeat_receipts).difference(split.holdout_case_ids)
    if mismatched_repeat or extra_repeat:
        checks.append(
            _check(
                "repeat_stability",
                GateCheckOutcome.FAIL,
                actual=mismatched_repeat + len(extra_repeat),
                threshold=0,
                reason="stability_receipt_mismatch",
            )
        )
    elif missing_repeat:
        checks.append(
            _check(
                "repeat_stability",
                GateCheckOutcome.INSUFFICIENT_DATA,
                actual=len(repeat_receipts),
                threshold=len(holdout),
                reason="repeat_receipts_incomplete",
            )
        )
    else:
        comparisons = [
            label == receipt.trial_labels[0]
            for receipt in repeat_receipts.values()
            for label in receipt.trial_labels[1:]
        ]
        stability = _ratio(sum(comparisons), len(comparisons))
        checks.append(
            _minimum_check(
                "repeat_stability",
                stability,
                policy.minimum_repeat_stability,
                reason="repeat_observations_missing",
            )
        )

    completed = [case for case in holdout if case.run_state is CaseRunState.COMPLETED]
    coverage = _ratio(len(completed), len(holdout))
    risk = _ratio(
        sum(case.candidate_label != case.reference_label for case in completed),
        len(completed),
    )
    false_confident = _ratio(
        sum(
            case.candidate_label != case.reference_label
            and (case.candidate_confidence or 0.0) >= policy.false_confidence_threshold
            for case in completed
        ),
        len(completed),
    )
    checks.extend(
        (
            _minimum_check(
                "selective_coverage",
                coverage,
                policy.minimum_selective_coverage,
                reason="coverage_missing",
            ),
            _maximum_check(
                "selective_risk",
                risk,
                policy.maximum_selective_risk,
                missing_reason="answered_cases_missing",
            ),
            _maximum_check(
                "false_confident_error_rate",
                false_confident,
                policy.maximum_false_confident_error_rate,
                missing_reason="confidence_observations_missing",
            ),
        )
    )

    for latency_class, threshold in (
        (LatencyClass.COLD, policy.maximum_cold_p95_latency_ms),
        (LatencyClass.WARM, policy.maximum_warm_p95_latency_ms),
    ):
        values = [
            case.latency_ms
            for case in holdout
            if case.latency_class is latency_class and case.latency_ms is not None
        ]
        key = f"latency_p95.{latency_class.value}"
        if len(values) < policy.minimum_operational_samples_per_latency_class:
            checks.append(
                _check(
                    key,
                    GateCheckOutcome.INSUFFICIENT_DATA,
                    actual=len(values),
                    threshold=policy.minimum_operational_samples_per_latency_class,
                    reason="latency_samples_incomplete",
                )
            )
        else:
            checks.append(
                _maximum_check(key, _nearest_rank_percentile(values, 0.95), threshold)
            )

    for state, threshold in (
        (CaseRunState.OOM, policy.maximum_oom_rate),
        (CaseRunState.ERROR, policy.maximum_error_rate),
        (CaseRunState.REFUSAL, policy.maximum_refusal_rate),
    ):
        checks.append(
            _maximum_check(
                f"run_rate.{state.value}",
                _ratio(sum(case.run_state is state for case in holdout), len(holdout)),
                threshold,
                missing_reason="holdout_missing",
            )
        )

    for dimension in policy.subgroup_dimensions:
        grouped: dict[str, list[EstimatorCase]] = defaultdict(list)
        for case in holdout:
            grouped[_subgroup_value(case, dimension)].append(case)
        small_group = any(
            len(members) < policy.minimum_subgroup_size for members in grouped.values()
        )
        baseline_incomplete = any(
            case.baseline_label is None for members in grouped.values() for case in members
        )
        if not grouped or small_group or baseline_incomplete:
            checks.append(
                _check(
                    f"subgroup_regression.{dimension.value}",
                    GateCheckOutcome.INSUFFICIENT_DATA,
                    actual=min((len(value) for value in grouped.values()), default=0),
                    threshold=policy.minimum_subgroup_size,
                    reason="subgroup_evidence_incomplete",
                )
            )
            continue
        deltas = [
            (_accuracy(members, lambda case: case.candidate_label) or 0.0)
            - (_accuracy(members, lambda case: case.baseline_label) or 0.0)
            for members in grouped.values()
        ]
        worst_delta = min(deltas)
        checks.append(
            _minimum_check(
                f"subgroup_regression.{dimension.value}",
                worst_delta,
                -policy.maximum_material_subgroup_regression,
                reason="subgroup_comparison_missing",
            )
        )

    rules_by_metric = {
        rule.metric_key: rule for rule in policy.high_risk_precision_rules
    }
    for metric_key in sorted(high_risk_specs):
        spec = specs[metric_key]
        rule = rules_by_metric[metric_key]
        metric_cases = [case for case in holdout if case.metric_key == metric_key]
        predicted_positive = [
            case
            for case in metric_cases
            if case.run_state is CaseRunState.COMPLETED
            and case.candidate_label == spec.positive_label
        ]
        if len(predicted_positive) < rule.minimum_positive_predictions:
            checks.append(
                _check(
                    f"high_risk_precision.{metric_key}",
                    GateCheckOutcome.INSUFFICIENT_DATA,
                    actual=len(predicted_positive),
                    threshold=rule.minimum_positive_predictions,
                    reason="positive_predictions_incomplete",
                )
            )
        else:
            precision = _ratio(
                sum(case.reference_label == spec.positive_label for case in predicted_positive),
                len(predicted_positive),
            )
            checks.append(
                _minimum_check(
                    f"high_risk_precision.{metric_key}",
                    precision,
                    rule.minimum_precision,
                    reason="precision_observations_missing",
                )
            )

    return _decision(report, policy, derived_at, checks)
