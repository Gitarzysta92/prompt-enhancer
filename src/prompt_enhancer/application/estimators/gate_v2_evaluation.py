"""Pure, fail-closed activation evaluation for v2 constellation evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import math
from typing import Callable, Sequence

from .contracts import EstimatorPlan, EstimatorStageKind
from .gate_contracts import (
    ActivationGateCheck,
    ActivationOutcome,
    CalibrationTaskStratum,
    CalibrationLanguage,
    CaseOrigin,
    CaseRunState,
    EstimatorCase,
    GateCheckOutcome,
    GatePolicy,
    MetricRiskTier,
    ReferenceTruthSource,
    StabilityCondition,
    SubgroupDimension,
)
from .gate_v2_contracts import (
    ActivationGateDecisionV2,
    AttemptOutcomeReceipt,
    BlindCalibrationResolution,
    BlindCalibrationSource,
    CaseAssignmentV2,
    ConstellationStageIdentity,
    GateEvidenceV2,
)
from ...domain import Provider


_SUPPORTED_TRUTH = frozenset(
    {
        ReferenceTruthSource.OBJECTIVE_CHECK,
        ReferenceTruthSource.HUMAN_ADJUDICATED,
        ReferenceTruthSource.INDEPENDENT_HUMAN,
    }
)


def _version_is_path_or_uri(value: str) -> bool:
    import re

    return bool(
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
        or "\\" in value
        or ".." in value.split("/")
    )


def _stored_plan_unsafe_identifier_count(plan: EstimatorPlan) -> int:
    """Audit every free-form v1 plan identifier before trusting its fingerprint."""

    values: list[str] = [
        plan.plan_key,
        plan.plan_version,
        plan.evidence_packet_schema_version,
        plan.preprocessing_version,
        plan.calibration_version,
        plan.router_version,
        plan.redactor_version,
    ]
    for provider in plan.provider_schemas:
        values.extend((provider.adapter_version, provider.provider_schema_version))
    for question in plan.question_specs:
        values.extend(
            (
                question.question_id,
                question.prompt_template_id,
                question.rubric_id,
                question.metric_definition_version,
                question.question_version,
                question.prompt_template_version,
                question.rubric_version,
                question.output_schema_version,
            )
        )
    for stage in plan.stages:
        values.extend((stage.component_version, stage.output_schema_version))
        if stage.candidate_family_key is not None:
            values.append(stage.candidate_family_key)
        artifact = stage.model_artifact
        if artifact is None:
            continue
        values.extend(
            (
                artifact.requested_model_id,
                artifact.served_model_id,
                artifact.requested_revision,
                artifact.served_revision,
                artifact.license_id,
                artifact.tokenizer.tokenizer_id,
                artifact.tokenizer.revision,
            )
        )
    for family in plan.candidate_families:
        values.append(family.family_key)
        values.extend(family.deterministic_baseline_ids)
        for artifact in family.screened_candidates:
            values.extend(
                (
                    artifact.requested_model_id,
                    artifact.served_model_id,
                    artifact.requested_revision,
                    artifact.served_revision,
                    artifact.license_id,
                    artifact.tokenizer.tokenizer_id,
                    artifact.tokenizer.revision,
                )
            )
    return sum(_version_is_path_or_uri(value) for value in values)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
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


def _minimum(
    key: str,
    value: float | int | None,
    threshold: float | int,
    *,
    strict: bool = False,
    missing_reason: str = "measurement_missing",
    below_is_insufficient: bool = False,
) -> ActivationGateCheck:
    if value is None:
        return _check(
            key,
            GateCheckOutcome.INSUFFICIENT_DATA,
            threshold=threshold,
            reason=missing_reason,
        )
    passed = value > threshold if strict else value >= threshold
    return _check(
        key,
        GateCheckOutcome.PASS
        if passed
        else GateCheckOutcome.INSUFFICIENT_DATA
        if below_is_insufficient
        else GateCheckOutcome.FAIL,
        actual=value,
        threshold=threshold,
        reason=None
        if passed
        else missing_reason
        if below_is_insufficient
        else "threshold_not_met",
    )


def _maximum(
    key: str,
    value: float | int | None,
    threshold: float | int,
    *,
    missing_reason: str = "measurement_missing",
) -> ActivationGateCheck:
    if value is None:
        return _check(
            key,
            GateCheckOutcome.INSUFFICIENT_DATA,
            threshold=threshold,
            reason=missing_reason,
        )
    passed = value <= threshold
    return _check(
        key,
        GateCheckOutcome.PASS if passed else GateCheckOutcome.FAIL,
        actual=value,
        threshold=threshold,
        reason=None if passed else "threshold_exceeded",
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _macro_f1(
    cases: Sequence[EstimatorCase],
    labels: Sequence[str],
    prediction: Callable[[EstimatorCase], str | None],
) -> float | None:
    if not cases:
        return None
    scores: list[float] = []
    for label in labels:
        true_positive = sum(
            case.reference_label == label and prediction(case) == label for case in cases
        )
        false_positive = sum(
            case.reference_label != label and prediction(case) == label for case in cases
        )
        false_negative = sum(
            case.reference_label == label and prediction(case) != label for case in cases
        )
        denominator = (2 * true_positive) + false_positive + false_negative
        scores.append(0.0 if denominator == 0 else (2 * true_positive) / denominator)
    return sum(scores) / len(scores) if scores else None


def _mean_metric_macro_f1(
    cases: Sequence[EstimatorCase],
    vocabularies: dict[str, tuple[str, ...]],
    prediction: Callable[[EstimatorCase], str | None],
) -> float | None:
    values = [
        value
        for metric_key, labels in vocabularies.items()
        if (
            value := _macro_f1(
                [case for case in cases if case.metric_key == metric_key],
                labels,
                prediction,
            )
        )
        is not None
    ]
    return sum(values) / len(values) if values else None


def _ece(cases: Sequence[EstimatorCase], bins: int = 10) -> float | None:
    observed = [
        case
        for case in cases
        if case.run_state is CaseRunState.COMPLETED
        and case.candidate_label is not None
        and case.candidate_confidence is not None
    ]
    if not observed:
        return None
    total = len(observed)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            case
            for case in observed
            if lower <= (case.candidate_confidence or 0.0) <= upper
            and (index == bins - 1 or (case.candidate_confidence or 0.0) < upper)
        ]
        if not members:
            continue
        confidence = sum(case.candidate_confidence or 0.0 for case in members) / len(
            members
        )
        accuracy = sum(
            case.candidate_label == case.reference_label for case in members
        ) / len(members)
        error += (len(members) / total) * abs(accuracy - confidence)
    return error


def _decision(
    plan: EstimatorPlan,
    evidence: GateEvidenceV2,
    policy: GatePolicy,
    derived_at: datetime,
    checks: Sequence[ActivationGateCheck],
) -> ActivationGateDecisionV2:
    ordered = tuple(sorted(checks, key=lambda item: item.check_key))
    outcomes = {item.outcome for item in ordered}
    outcome = (
        ActivationOutcome.REJECTED
        if GateCheckOutcome.FAIL in outcomes
        else ActivationOutcome.INSUFFICIENT_DATA
        if GateCheckOutcome.INSUFFICIENT_DATA in outcomes
        else ActivationOutcome.ELIGIBLE
    )
    identity = "|".join(
        (
            plan.canonical_fingerprint,
            evidence.fingerprint,
            policy.fingerprint,
            evidence.preregistration.fingerprint,
            derived_at.isoformat(),
        )
    )
    return ActivationGateDecisionV2(
        decision_id=hashlib.sha256(identity.encode("ascii")).hexdigest(),
        stored_plan_fingerprint=plan.canonical_fingerprint,
        evidence_fingerprint=evidence.fingerprint,
        policy_fingerprint=policy.fingerprint,
        preregistration_fingerprint=evidence.preregistration.fingerprint,
        preregistration_v2_fingerprint=(
            evidence.preregistration_v2.fingerprint
            if evidence.preregistration_v2 is not None
            else None
        ),
        outcome=outcome,
        checks=ordered,
        derived_at=derived_at,
    )


def evaluate_activation_gate_v2(
    stored_plan: EstimatorPlan,
    evidence: GateEvidenceV2,
    policy: GatePolicy,
    *,
    derived_at: datetime,
) -> ActivationGateDecisionV2:
    """Derive an activation decision from a stored plan and v2 receipts only.

    The function accepts no eligibility, integrity, synthetic, identity, or
    outcome hints. Missing v2 evidence remains explicitly insufficient, while a
    contradictory fingerprint, substituted identity, or synthetic stored model
    rejects the candidate.
    """

    derived_at = _utc(derived_at)
    plan_fingerprint = stored_plan.canonical_fingerprint
    manifest = evidence.assignment_manifest
    cohort = evidence.cohort
    split = evidence.split
    preregistration = evidence.preregistration
    assignments = {item.case_id: item for item in manifest.assignments}
    cases = {item.case_id: item for item in cohort.cases}
    partition_ids = (
        set(split.development_case_ids)
        | set(split.active_learning_case_ids)
        | set(split.holdout_case_ids)
    )
    questions_by_metric: dict[str, set[str]] = defaultdict(set)
    for question in stored_plan.question_specs:
        questions_by_metric[question.metric_key].add(question.canonical_fingerprint)

    integrity_failures = 0
    integrity_failures += _stored_plan_unsafe_identifier_count(stored_plan)
    integrity_failures += int(evidence.stored_plan_fingerprint != plan_fingerprint)
    integrity_failures += int(manifest.plan_fingerprint != plan_fingerprint)
    integrity_failures += int(split.assignment_manifest_fingerprint != manifest.fingerprint)
    integrity_failures += int(
        preregistration.assignment_manifest_fingerprint != manifest.fingerprint
    )
    integrity_failures += int(preregistration.split_fingerprint != split.fingerprint)
    integrity_failures += int(preregistration.policy_fingerprint != policy.fingerprint)
    preregistration_v2 = evidence.preregistration_v2
    constellation = evidence.constellation_identity
    if preregistration_v2 is not None:
        integrity_failures += int(
            preregistration_v2.policy_fingerprint != policy.fingerprint
            or preregistration_v2.assignment_manifest_fingerprint != manifest.fingerprint
            or preregistration_v2.split_fingerprint != split.fingerprint
            or preregistration_v2.stored_plan_fingerprint != plan_fingerprint
            or preregistration_v2.legacy_preregistration_fingerprint
            != preregistration.fingerprint
            or constellation is None
            or preregistration_v2.constellation_fingerprint
            != constellation.fingerprint
            or preregistration_v2.registered_at != preregistration.registered_at
        )
    integrity_failures += int(partition_ids != set(assignments))
    integrity_failures += int(partition_ids != set(cases))
    integrity_failures += int(manifest.frozen_at > split.frozen_at)
    integrity_failures += int(split.frozen_at > preregistration.registered_at)
    integrity_failures += int(cohort.completed_at > evidence.completed_at)
    integrity_failures += int(derived_at < evidence.completed_at)

    for case_id, case in cases.items():
        assignment = assignments.get(case_id)
        if assignment is None:
            continue
        integrity_failures += int(
            CaseAssignmentV2.from_case(
                case,
                plan_fingerprint=assignment.plan_fingerprint,
                metric_question_fingerprint=assignment.metric_question_fingerprint,
                evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
            )
            != assignment
        )
        integrity_failures += int(
            assignment.metric_question_fingerprint
            not in questions_by_metric.get(case.metric_key, set())
        )

    expected_constellation_stages = tuple(
        ConstellationStageIdentity.from_stage(stage)
        for stage in stored_plan.stages
        if stage.model_artifact is not None
    )
    if constellation is not None:
        integrity_failures += int(constellation.plan_fingerprint != plan_fingerprint)
        integrity_failures += int(constellation.stages != expected_constellation_stages)
        integrity_failures += int(constellation.frozen_at > preregistration.registered_at)

    audit = evidence.execution_identity_audit
    expected_attempt_manifest = evidence.expected_attempt_manifest
    if audit is not None:
        integrity_failures += int(audit.plan_fingerprint != plan_fingerprint)
        integrity_failures += int(
            constellation is None
            or audit.constellation_fingerprint != constellation.fingerprint
        )
        integrity_failures += int(audit.completed_at > evidence.completed_at)
        integrity_failures += int(
            expected_attempt_manifest is None
            or audit.expected_attempt_manifest_fingerprint
            != expected_attempt_manifest.fingerprint
        )
    if expected_attempt_manifest is not None:
        integrity_failures += int(
            expected_attempt_manifest.plan_fingerprint != plan_fingerprint
            or expected_attempt_manifest.frozen_at > evidence.completed_at
        )
        if audit is not None:
            integrity_failures += int(
                expected_attempt_manifest.frozen_at < audit.coverage_ended_at
                or expected_attempt_manifest.frozen_at > audit.completed_at
            )

    if evidence.holdout_access_audit is not None:
        integrity_failures += int(
            evidence.holdout_access_audit.split_fingerprint != split.fingerprint
        )
    if evidence.privacy_scan is not None:
        integrity_failures += int(
            evidence.privacy_scan.scanned_bundle_fingerprint
            != evidence.scannable_fingerprint
        )
        integrity_failures += int(
            evidence.privacy_scan.completed_at < evidence.completed_at
            or evidence.privacy_scan.completed_at > derived_at
        )

    for receipt in evidence.stability_receipts:
        assignment = assignments.get(receipt.case_id)
        integrity_failures += int(
            assignment is None
            or receipt.metric_question_fingerprint
            != assignment.metric_question_fingerprint
            or receipt.evidence_packet_fingerprint
            != assignment.evidence_packet_fingerprint
        )
    for adjudication in evidence.blind_adjudications:
        assignment = assignments.get(adjudication.case_id)
        integrity_failures += int(
            assignment is None
            or adjudication.plan_fingerprint != plan_fingerprint
            or adjudication.metric_question_fingerprint
            != assignment.metric_question_fingerprint
            or adjudication.evidence_packet_fingerprint
            != assignment.evidence_packet_fingerprint
        )

    specs = {item.metric_key: item for item in preregistration.metric_specs}
    observed_metrics = {item.metric_key for item in cohort.cases}
    integrity_failures += int(not observed_metrics.issubset(specs))
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
    for adjudication in evidence.blind_adjudications:
        assignment = assignments.get(adjudication.case_id)
        spec = specs.get(assignment.metric_key) if assignment is not None else None
        if spec is None:
            integrity_failures += 1
            continue
        vocabulary = set(spec.label_vocabulary)
        integrity_failures += int(
            adjudication.resolved_label_code is not None
            and adjudication.resolved_label_code not in vocabulary
        )
        integrity_failures += sum(
            judgment.label_code not in vocabulary
            for judgment in adjudication.judgments
        )

    manifest_check = _check(
        "manifest_integrity",
        GateCheckOutcome.PASS if integrity_failures == 0 else GateCheckOutcome.FAIL,
        actual=integrity_failures,
        threshold=0,
        reason=None if integrity_failures == 0 else "fingerprint_or_manifest_mismatch",
    )
    if integrity_failures:
        return _decision(stored_plan, evidence, policy, derived_at, (manifest_check,))

    checks: list[ActivationGateCheck] = [manifest_check]

    checks.append(
        _check(
            "immutable_evidence_persistence",
            GateCheckOutcome.INSUFFICIENT_DATA,
            actual=0,
            threshold=1,
            reason="sealed_repository_projection_not_implemented",
        )
    )

    checks.append(
        _check(
            "v2_preregistration",
            GateCheckOutcome.PASS
            if preregistration_v2 is not None
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=1 if preregistration_v2 is not None else 0,
            threshold=1,
            reason=None
            if preregistration_v2 is not None
            else "v2_preregistration_missing",
        )
    )

    synthetic_stage_count = sum(
        stage.model_artifact is not None
        and stage.model_artifact.source.value == "synthetic"
        for stage in stored_plan.stages
    )
    checks.append(
        _check(
            "stored_plan_non_synthetic",
            GateCheckOutcome.FAIL
            if stored_plan.uses_synthetic_model
            else GateCheckOutcome.PASS,
            actual=synthetic_stage_count,
            threshold=0,
            reason="synthetic_model_in_stored_plan"
            if stored_plan.uses_synthetic_model
            else None,
        )
    )

    checks.append(
        _check(
            "constellation_identity",
            GateCheckOutcome.PASS
            if constellation is not None
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=len(constellation.stages) if constellation is not None else 0,
            threshold=len(expected_constellation_stages),
            reason=None if constellation is not None else "constellation_receipt_missing",
        )
    )

    active_ids = set(split.active_learning_case_ids)
    holdout_ids = set(split.holdout_case_ids)
    calibration_ids = active_ids | holdout_ids
    attempt_by_id = {
        item.attempt_id: item for item in audit.attempts
    } if audit is not None else {}
    outcome_by_attempt = {
        item.attempt_id: item for item in audit.outcomes
    } if audit is not None else {}
    exact_attempt_failures = 0
    covered_candidate_cases: set[str] = set()
    if audit is not None and constellation is not None:
        constellation_by_fingerprint = {
            item.fingerprint: item for item in constellation.stages
        }
        plan_stage_by_ordinal = {
            item.ordinal: item for item in stored_plan.stages if item.model_artifact is not None
        }
        for attempt in audit.attempts:
            assignment = assignments.get(attempt.case_id)
            identity = constellation_by_fingerprint.get(
                attempt.constellation_stage_fingerprint
            )
            plan_stage = plan_stage_by_ordinal.get(attempt.stage_ordinal)
            artifact = plan_stage.model_artifact if plan_stage is not None else None
            lineage_matches = (
                assignment is not None
                and attempt.metric_question_fingerprint
                == assignment.metric_question_fingerprint
                and attempt.evidence_packet_fingerprint
                == assignment.evidence_packet_fingerprint
                and identity is not None
                and plan_stage is not None
                and artifact is not None
            )
            exact = bool(lineage_matches) and (
                attempt.stage_kind is identity.kind
                and attempt.stage_ordinal == identity.ordinal
                and attempt.source is artifact.source
                and attempt.model_artifact_fingerprint
                == artifact.canonical_fingerprint
                and attempt.stage_configuration_sha256
                == plan_stage.configuration_sha256
                and attempt.requested_model_id == artifact.requested_model_id
                and attempt.served_model_id == artifact.served_model_id
                and attempt.requested_revision == artifact.requested_revision
                and attempt.served_revision == artifact.served_revision
                and attempt.requested_execution_mode
                is artifact.requested_execution_mode
                and attempt.served_execution_mode is artifact.served_execution_mode
                and not attempt.fallback_used
            )
            exact_attempt_failures += int(not exact)
            if exact and attempt.stage_kind is EstimatorStageKind.SPECIALIST:
                covered_candidate_cases.add(attempt.case_id)

    expected_attempts = {
        item.attempt_id: item for item in expected_attempt_manifest.attempts
    } if expected_attempt_manifest is not None else {}
    audited_attempts = set(attempt_by_id)
    attempt_set_mismatch = len(audited_attempts.symmetric_difference(expected_attempts))
    if audit is not None and expected_attempt_manifest is not None:
        attempt_set_mismatch += sum(
            attempt.execution_id != expected_attempts[attempt_id].execution_id
            or attempt.case_id != expected_attempts[attempt_id].case_id
            or attempt.stage_ordinal != expected_attempts[attempt_id].stage_ordinal
            or attempt.stage_kind is not expected_attempts[attempt_id].stage_kind
            for attempt_id, attempt in attempt_by_id.items()
            if attempt_id in expected_attempts
        )

    if audit is None:
        checks.append(
            _check(
                "execution_identity_audit",
                GateCheckOutcome.INSUFFICIENT_DATA,
                actual=0,
                threshold=len(calibration_ids),
                reason="attempt_identity_audit_missing",
            )
        )
        checks.append(
            _check(
                "exact_attempt_identity",
                GateCheckOutcome.INSUFFICIENT_DATA,
                threshold=0,
                reason="attempt_identity_audit_missing",
            )
        )
    else:
        missing_candidate_attempts = len(calibration_ids - covered_candidate_cases)
        if expected_attempt_manifest is None:
            missing_candidate_attempts = max(1, missing_candidate_attempts)
        checks.append(
            _check(
                "execution_identity_audit",
                GateCheckOutcome.FAIL
                if attempt_set_mismatch
                else GateCheckOutcome.PASS
                if missing_candidate_attempts == 0
                else GateCheckOutcome.INSUFFICIENT_DATA,
                actual=len(covered_candidate_cases),
                threshold=len(calibration_ids),
                reason=None
                if missing_candidate_attempts == 0 and attempt_set_mismatch == 0
                else "persisted_attempt_set_mismatch"
                if attempt_set_mismatch
                else "candidate_attempt_identity_incomplete",
            )
        )
        checks.append(
            _check(
                "exact_attempt_identity",
                GateCheckOutcome.PASS
                if exact_attempt_failures == 0
                else GateCheckOutcome.FAIL,
                actual=exact_attempt_failures,
                threshold=0,
                reason=None
                if exact_attempt_failures == 0
                else "requested_served_or_configuration_mismatch",
            )
        )

    calibration_cases = [cases[case_id] for case_id in sorted(calibration_ids)]
    private_count = sum(
        case.origin is CaseOrigin.PRIVATE_REPRESENTATIVE
        and case.provider is not Provider.SYNTHETIC
        for case in calibration_cases
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

    active_count = len(active_ids)
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

    holdout = [cases[case_id] for case_id in split.holdout_case_ids]
    active = [cases[case_id] for case_id in split.active_learning_case_ids]
    development = [cases[case_id] for case_id in split.development_case_ids]
    checks.append(
        _minimum(
            "holdout_count",
            len(holdout),
            policy.minimum_holdout_count,
            below_is_insufficient=True,
            missing_reason="holdout_incomplete",
        )
    )
    per_metric = Counter(case.metric_key for case in holdout)
    registered_metrics = {item.metric_key for item in preregistration.metric_specs}
    checks.append(
        _minimum(
            "holdout_per_metric",
            min((per_metric.get(key, 0) for key in registered_metrics), default=0),
            policy.minimum_holdout_per_metric,
            below_is_insufficient=True,
            missing_reason="metric_holdout_incomplete",
        )
    )
    active_strata = {case.task_stratum for case in active}
    active_languages = {case.language for case in active}
    checks.append(
        _minimum(
            "active_learning_strata",
            len(active_strata.intersection(policy.required_strata)),
            len(policy.required_strata),
            below_is_insufficient=True,
            missing_reason="required_strata_missing",
        )
    )
    checks.append(
        _minimum(
            "active_learning_languages",
            len(active_languages.intersection(policy.required_languages)),
            len(policy.required_languages),
            below_is_insufficient=True,
            missing_reason="required_languages_missing",
        )
    )
    holdout_strata = Counter(case.task_stratum for case in holdout)
    holdout_languages = Counter(case.language for case in holdout)
    checks.append(
        _minimum(
            "holdout_strata",
            min(
                (holdout_strata.get(item, 0) for item in policy.required_strata),
                default=0,
            ),
            policy.minimum_holdout_per_stratum,
            below_is_insufficient=True,
            missing_reason="required_strata_missing",
        )
    )
    checks.append(
        _minimum(
            "holdout_languages",
            min(
                (holdout_languages.get(item, 0) for item in policy.required_languages),
                default=0,
            ),
            policy.minimum_holdout_per_language,
            below_is_insufficient=True,
            missing_reason="required_languages_missing",
        )
    )

    nonholdout = development + active
    project_overlap = len(
        {case.project_id for case in nonholdout}.intersection(
            case.project_id for case in holdout
        )
    )
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
            actual=int(time_separated),
            threshold=1,
            reason=None if time_separated else "observation_windows_overlap",
        )
    )

    access_audit = evidence.holdout_access_audit
    if access_audit is None:
        checks.append(
            _check(
                "holdout_access_audit",
                GateCheckOutcome.INSUFFICIENT_DATA,
                threshold=0,
                reason="access_audit_missing",
            )
        )
    else:
        violations = (
            access_audit.unauthorized_access_count + access_audit.missing_event_count
        )
        complete_window = (
            access_audit.coverage_started_at <= split.frozen_at
            and access_audit.coverage_ended_at >= evidence.completed_at
        )
        checks.append(
            _check(
                "holdout_access_audit",
                GateCheckOutcome.FAIL
                if violations
                else GateCheckOutcome.PASS
                if complete_window
                else GateCheckOutcome.INSUFFICIENT_DATA,
                actual=violations,
                threshold=0,
                reason="holdout_access_violation"
                if violations
                else None
                if complete_window
                else "access_audit_window_incomplete",
            )
        )

    early_holdout = sum(
        case.evaluated_at <= preregistration.registered_at for case in holdout
    )
    if audit is not None:
        early_holdout += sum(
            attempt.case_id in holdout_ids
            and attempt.attempted_at <= preregistration.registered_at
            for attempt in audit.attempts
        )
        early_holdout += sum(
            outcome.case_id in holdout_ids
            and outcome.completed_at <= preregistration.registered_at
            for outcome in audit.outcomes
        )
    checks.append(
        _check(
            "holdout_evaluated_after_preregistration",
            GateCheckOutcome.PASS if early_holdout == 0 else GateCheckOutcome.FAIL,
            actual=early_holdout,
            threshold=0,
            reason=None if early_holdout == 0 else "holdout_evaluated_before_preregistration",
        )
    )

    adjudications = {
        (item.case_id, item.source): item for item in evidence.blind_adjudications
    }
    reference_missing = 0
    human_missing = 0
    blind_mismatch = 0
    unsupported_truth = 0
    for case in calibration_cases:
        reference = adjudications.get(
            (case.case_id, BlindCalibrationSource.REFERENCE_TRUTH)
        )
        if reference is None or (
            reference.resolution is BlindCalibrationResolution.UNRESOLVED
        ):
            reference_missing += 1
        else:
            blind_mismatch += int(
                reference.resolved_label_code != case.reference_label
                or reference.adjudication_id != case.truth_receipt_id
            )
        unsupported_truth += int(case.truth_source not in _SUPPORTED_TRUTH)
    for case in holdout:
        baseline = adjudications.get(
            (case.case_id, BlindCalibrationSource.HUMAN_BASELINE)
        )
        if baseline is None or baseline.resolution is BlindCalibrationResolution.UNRESOLVED:
            human_missing += 1
        else:
            blind_mismatch += int(
                baseline.resolved_label_code != case.human_baseline_label
                or baseline.adjudication_id != case.human_adjudication_receipt_id
            )
    checks.append(
        _check(
            "blind_label_integrity",
            GateCheckOutcome.PASS
            if blind_mismatch == 0 and unsupported_truth == 0
            else GateCheckOutcome.FAIL,
            actual=blind_mismatch + unsupported_truth,
            threshold=0,
            reason=None
            if blind_mismatch == 0 and unsupported_truth == 0
            else "blind_label_or_truth_mismatch",
        )
    )
    checks.append(
        _check(
            "blind_reference_truth",
            GateCheckOutcome.PASS
            if reference_missing == 0
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=len(calibration_cases) - reference_missing,
            threshold=len(calibration_cases),
            reason=None if reference_missing == 0 else "blind_reference_truth_incomplete",
        )
    )
    checks.append(
        _check(
            "blind_human_baseline",
            GateCheckOutcome.PASS
            if human_missing == 0
            else GateCheckOutcome.INSUFFICIENT_DATA,
            actual=len(holdout) - human_missing,
            threshold=len(holdout),
            reason=None if human_missing == 0 else "blind_human_baseline_incomplete",
        )
    )

    repeat = {
        item.case_id: item
        for item in evidence.stability_receipts
        if item.condition is StabilityCondition.REPEAT
    }
    missing_repeat = holdout_ids - set(repeat)
    stability_link_failures = 0
    comparisons: list[bool] = []
    for case_id, receipt in repeat.items():
        case = cases.get(case_id)
        if case_id not in holdout_ids or case is None:
            stability_link_failures += 1
            continue
        for trial in receipt.trials:
            attempt = attempt_by_id.get(trial.attempt_id)
            outcome = outcome_by_attempt.get(trial.attempt_id)
            stability_link_failures += int(
                attempt is None
                or outcome is None
                or attempt.case_id != case_id
                or attempt.metric_question_fingerprint
                != receipt.metric_question_fingerprint
                or attempt.evidence_packet_fingerprint
                != receipt.evidence_packet_fingerprint
                or outcome.outcome_id != trial.outcome_receipt_id
                or outcome.fingerprint != trial.outcome_fingerprint
                or attempt.stage_kind is not EstimatorStageKind.SPECIALIST
                or attempt.attempted_at > receipt.observed_at
                or outcome.completed_at > receipt.observed_at
            )
        linked_times = [
            (
                attempt_by_id[trial.attempt_id].attempted_at,
                outcome_by_attempt[trial.attempt_id].completed_at,
            )
            for trial in receipt.trials
            if trial.attempt_id in attempt_by_id
            and trial.attempt_id in outcome_by_attempt
        ]
        stability_link_failures += int(
            len(linked_times) != len(receipt.trials)
            or linked_times != sorted(linked_times)
            or any(
                linked_times[index][0] < linked_times[index - 1][1]
                for index in range(1, len(linked_times))
            )
        )
        executions = {
            attempt_by_id[trial.attempt_id].execution_id
            for trial in receipt.trials
            if trial.attempt_id in attempt_by_id
        }
        stability_link_failures += int(len(executions) != len(receipt.trials))
        first_outcome = outcome_by_attempt.get(receipt.trials[0].attempt_id)
        first = (
            (first_outcome.run_state, first_outcome.candidate_label)
            if first_outcome is not None
            else None
        )
        stability_link_failures += int(
            first != (case.run_state, case.candidate_label)
        )
        authoritative = (
            next(
                (
                    item
                    for item in audit.candidate_projections
                    if item.case_id == case_id
                ),
                None,
            )
            if audit is not None
            else None
        )
        stability_link_failures += int(
            authoritative is None
            or authoritative.authoritative_attempt_id
            != receipt.trials[0].attempt_id
        )
        comparisons.extend(
            (
                outcome_by_attempt.get(trial.attempt_id) is not None
                and (
                    outcome_by_attempt[trial.attempt_id].run_state,
                    outcome_by_attempt[trial.attempt_id].candidate_label,
                )
                == first
            )
            for trial in receipt.trials[1:]
        )
    if stability_link_failures:
        checks.append(
            _check(
                "repeat_stability",
                GateCheckOutcome.FAIL,
                actual=stability_link_failures,
                threshold=0,
                reason="stability_attempt_or_label_mismatch",
            )
        )
    elif missing_repeat:
        checks.append(
            _check(
                "repeat_stability",
                GateCheckOutcome.INSUFFICIENT_DATA,
                actual=len(repeat),
                threshold=len(holdout),
                reason="repeat_receipts_incomplete",
            )
        )
    else:
        checks.append(
            _minimum(
                "repeat_stability",
                _ratio(sum(comparisons), len(comparisons)),
                policy.minimum_repeat_stability,
                missing_reason="repeat_observations_missing",
            )
        )

    privacy = evidence.privacy_scan
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

    candidate_outcome_by_case: dict[str, AttemptOutcomeReceipt] = {}
    candidate_projection_failures = 0
    candidate_projection_cases: set[str] = set()
    if audit is not None:
        for projection in audit.candidate_projections:
            candidate_projection_cases.add(projection.case_id)
            attempt = attempt_by_id.get(projection.authoritative_attempt_id)
            outcome = outcome_by_attempt.get(projection.authoritative_attempt_id)
            candidate_projection_failures += int(
                attempt is None
                or outcome is None
                or projection.authoritative_outcome_id != outcome.outcome_id
                or projection.authoritative_outcome_fingerprint != outcome.fingerprint
                or projection.case_id != outcome.case_id
            )
            if outcome is not None:
                candidate_outcome_by_case[projection.case_id] = outcome
    for case in calibration_cases:
        outcome = candidate_outcome_by_case.get(case.case_id)
        if outcome is None:
            continue
        candidate_projection_failures += int(
            outcome.run_state is not case.run_state
            or outcome.candidate_label != case.candidate_label
            or outcome.candidate_confidence != case.candidate_confidence
            or outcome.latency_class is not case.latency_class
            or outcome.latency_ms != case.latency_ms
        )
    missing_candidate_projections = calibration_ids - candidate_projection_cases
    if candidate_projection_failures:
        checks.append(
            _check(
                "candidate_projection_integrity",
                GateCheckOutcome.FAIL,
                actual=candidate_projection_failures,
                threshold=0,
                reason="case_projection_does_not_match_immutable_outcome",
            )
        )
    elif missing_candidate_projections:
        checks.append(
            _check(
                "candidate_projection_integrity",
                GateCheckOutcome.INSUFFICIENT_DATA,
                actual=len(candidate_projection_cases),
                threshold=len(calibration_ids),
                reason="authoritative_candidate_projection_incomplete",
            )
        )
    else:
        checks.append(
            _check(
                "candidate_projection_integrity",
                GateCheckOutcome.PASS,
                actual=0,
                threshold=0,
            )
        )
    vocabularies = {
        item.metric_key: item.label_vocabulary for item in preregistration.metric_specs
    }
    candidate_performance = _mean_metric_macro_f1(
        holdout, vocabularies, lambda case: case.candidate_label
    )
    baseline_performance = (
        None
        if any(case.baseline_label is None for case in holdout)
        else _mean_metric_macro_f1(holdout, vocabularies, lambda case: case.baseline_label)
    )
    human_performance = (
        None
        if any(case.human_baseline_label is None for case in holdout)
        else _mean_metric_macro_f1(
            holdout, vocabularies, lambda case: case.human_baseline_label
        )
    )
    baseline_margin = (
        None
        if candidate_performance is None or baseline_performance is None
        else candidate_performance - baseline_performance
    )
    human_gap = (
        None
        if candidate_performance is None or human_performance is None
        else abs(candidate_performance - human_performance)
    )
    checks.append(
        _minimum(
            "beats_baseline",
            baseline_margin,
            policy.minimum_baseline_margin,
            strict=True,
            missing_reason="baseline_comparison_missing",
        )
    )
    checks.append(
        _maximum(
            "human_performance_gap",
            human_gap,
            policy.maximum_human_gap,
            missing_reason="human_comparison_missing",
        )
    )
    checks.append(
        _maximum(
            "expected_calibration_error",
            _ece(holdout),
            policy.maximum_ece,
            missing_reason="calibration_observations_missing",
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
            _minimum(
                "selective_coverage",
                coverage,
                policy.minimum_selective_coverage,
                missing_reason="coverage_missing",
            ),
            _maximum(
                "selective_risk",
                risk,
                policy.maximum_selective_risk,
                missing_reason="answered_cases_missing",
            ),
            _maximum(
                "false_confident_error_rate",
                false_confident,
                policy.maximum_false_confident_error_rate,
                missing_reason="confidence_observations_missing",
            ),
        )
    )

    for latency_class, threshold in (
        ("cold", policy.maximum_cold_p95_latency_ms),
        ("warm", policy.maximum_warm_p95_latency_ms),
    ):
        values = [
            case.latency_ms
            for case in holdout
            if case.latency_class.value == latency_class and case.latency_ms is not None
        ]
        key = f"latency_p95.{latency_class}"
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
            checks.append(_maximum(key, _nearest_rank(values, 0.95), threshold))

    for state, threshold in (
        (CaseRunState.OOM, policy.maximum_oom_rate),
        (CaseRunState.ERROR, policy.maximum_error_rate),
        (CaseRunState.REFUSAL, policy.maximum_refusal_rate),
    ):
        checks.append(
            _maximum(
                f"run_rate.{state.value}",
                _ratio(sum(case.run_state is state for case in holdout), len(holdout)),
                threshold,
                missing_reason="holdout_missing",
            )
        )

    for dimension in policy.subgroup_dimensions:
        grouped: dict[str, list[EstimatorCase]] = defaultdict(list)
        for case in holdout:
            subgroup = {
                SubgroupDimension.TASK_STRATUM: case.task_stratum.value,
                SubgroupDimension.LANGUAGE: case.language.value,
                SubgroupDimension.PROVIDER: case.provider.value,
                SubgroupDimension.EVIDENCE_TIER: case.evidence_tier.value,
            }[dimension]
            grouped[subgroup].append(case)
        incomplete = (
            not grouped
            or any(len(items) < policy.minimum_subgroup_size for items in grouped.values())
            or any(
                case.baseline_label is None
                for items in grouped.values()
                for case in items
            )
        )
        if incomplete:
            checks.append(
                _check(
                    f"subgroup_regression.{dimension.value}",
                    GateCheckOutcome.INSUFFICIENT_DATA,
                    actual=min((len(items) for items in grouped.values()), default=0),
                    threshold=policy.minimum_subgroup_size,
                    reason="subgroup_evidence_incomplete",
                )
            )
            continue
        deltas: list[float] = []
        for members in grouped.values():
            candidate_accuracy = sum(
                case.candidate_label == case.reference_label for case in members
            ) / len(members)
            baseline_accuracy = sum(
                case.baseline_label == case.reference_label for case in members
            ) / len(members)
            deltas.append(candidate_accuracy - baseline_accuracy)
        checks.append(
            _minimum(
                f"subgroup_regression.{dimension.value}",
                min(deltas),
                -policy.maximum_material_subgroup_regression,
                missing_reason="subgroup_comparison_missing",
            )
        )

    high_risk_specs = {
        item.metric_key: item
        for item in preregistration.metric_specs
        if item.risk_tier is MetricRiskTier.HIGH
    }
    rules = {item.metric_key: item for item in policy.high_risk_precision_rules}
    if set(high_risk_specs) != set(rules):
        checks.append(
            _check(
                "high_risk_preregistration",
                GateCheckOutcome.FAIL,
                actual=len(rules),
                threshold=len(high_risk_specs),
                reason="high_risk_policy_mismatch",
            )
        )
    else:
        checks.append(
            _check(
                "high_risk_preregistration",
                GateCheckOutcome.PASS,
                actual=len(rules),
                threshold=len(high_risk_specs),
            )
        )
        for metric_key in sorted(high_risk_specs):
            spec = high_risk_specs[metric_key]
            rule = rules[metric_key]
            predicted_positive = [
                case
                for case in holdout
                if case.metric_key == metric_key
                and case.run_state is CaseRunState.COMPLETED
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
                    sum(
                        case.reference_label == spec.positive_label
                        for case in predicted_positive
                    ),
                    len(predicted_positive),
                )
                checks.append(
                    _minimum(
                        f"high_risk_precision.{metric_key}",
                        precision,
                        rule.minimum_precision,
                        missing_reason="precision_observations_missing",
                    )
                )

    return _decision(stored_plan, evidence, policy, derived_at, checks)
