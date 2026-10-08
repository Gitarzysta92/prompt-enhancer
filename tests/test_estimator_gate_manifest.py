from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from typing import Callable

from pydantic import ValidationError
import pytest

from prompt_enhancer.application.estimators.gate_contracts import (
    ActivationGateDecision,
    ActivationOutcome,
    CaseAssignment,
    CaseAssignmentManifest,
    CalibrationCohort,
    CalibrationEvidenceBundle,
    CalibrationLanguage,
    CalibrationReport,
    CalibrationSplit,
    CalibrationTaskStratum,
    CaseOrigin,
    CaseRunState,
    EstimatorCase,
    EstimatorExecutionMode,
    EstimatorIdentityReceipt,
    EstimatorSource,
    EvidenceTier,
    GateCheckOutcome,
    GatePolicy,
    GatePreregistration,
    HighRiskPrecisionRule,
    HoldoutAccessAuditReceipt,
    LatencyClass,
    MetricGateSpec,
    MetricRiskTier,
    PrivacyScanReceipt,
    ReferenceTruthSource,
    StabilityCondition,
    StabilityReceipt,
)
from prompt_enhancer.application.estimators.gate_evaluation import (
    evaluate_activation_gate,
)
from prompt_enhancer.domain import Provider


BASE = datetime(2042, 1, 1, tzinfo=UTC)
METRIC_KEY = "verification_quality"


def _id(value: str) -> str:
    return hashlib.sha256(f"reserved-synthetic:{value}".encode("ascii")).hexdigest()


def _case(
    role: str,
    index: int,
    *,
    origin: CaseOrigin = CaseOrigin.PRIVATE_REPRESENTATIVE,
) -> EstimatorCase:
    holdout = role == "holdout"
    reference = "positive" if index % 2 == 0 else "negative"
    baseline = (
        ("negative" if reference == "positive" else "positive")
        if index % 5 == 0
        else reference
    )
    observed_day = 8 + (index % 2) if holdout else 1 + (index % 5)
    evaluated_day = 16 if holdout else 10
    return EstimatorCase(
        case_id=_id(f"case:{role}:{index}"),
        project_id=_id(
            f"project:{'holdout' if holdout else 'calibration'}:{index % 2}"
        ),
        session_revision_id=_id(f"revision:{role}:{index}"),
        metric_key=METRIC_KEY,
        provider=Provider.CODEX if index % 2 == 0 else Provider.CLAUDE_CODE,
        origin=origin,
        task_stratum=tuple(CalibrationTaskStratum)[index % 4],
        language=tuple(CalibrationLanguage)[index % 2],
        evidence_tier=EvidenceTier.OBJECTIVE
        if index % 2 == 0
        else EvidenceTier.HUMAN,
        observed_at=BASE + timedelta(days=observed_day),
        evaluated_at=BASE + timedelta(days=evaluated_day),
        truth_source=ReferenceTruthSource.OBJECTIVE_CHECK
        if index % 2 == 0
        else ReferenceTruthSource.HUMAN_ADJUDICATED,
        truth_receipt_id=_id(f"truth:{role}:{index}"),
        reference_label=reference,
        candidate_label=reference,
        candidate_confidence=0.99,
        baseline_label=baseline,
        human_baseline_label=reference,
        human_adjudication_receipt_id=_id(f"human:{role}:{index}"),
        run_state=CaseRunState.COMPLETED,
        latency_class=LatencyClass.COLD if index % 2 == 0 else LatencyClass.WARM,
        latency_ms=100.0 if index % 2 == 0 else 50.0,
    )


def _policy(**updates: object) -> GatePolicy:
    values: dict[str, object] = {
        "policy_id": _id("policy"),
        "minimum_holdout_count": 40,
        "minimum_holdout_per_metric": 40,
        "minimum_holdout_per_stratum": 10,
        "minimum_holdout_per_language": 20,
        "minimum_operational_samples_per_latency_class": 20,
        "minimum_subgroup_size": 5,
        "minimum_baseline_margin": 0.0,
        "minimum_selective_coverage": 0.95,
        "maximum_selective_risk": 0.05,
        "false_confidence_threshold": 0.90,
        "maximum_false_confident_error_rate": 0.0,
        "maximum_cold_p95_latency_ms": 1_000.0,
        "maximum_warm_p95_latency_ms": 500.0,
        "maximum_oom_rate": 0.01,
        "maximum_error_rate": 0.01,
        "maximum_refusal_rate": 0.01,
        "maximum_material_subgroup_regression": 0.02,
        "high_risk_precision_rules": (
            HighRiskPrecisionRule(
                metric_key=METRIC_KEY,
                minimum_precision=0.98,
                minimum_positive_predictions=10,
            ),
        ),
    }
    values.update(updates)
    return GatePolicy(**values)


def _build_report(
    *,
    active_count: int = 100,
    holdout_count: int = 40,
    development_count: int = 8,
    case_mutator: Callable[[str, int, EstimatorCase], EstimatorCase] | None = None,
    origin: CaseOrigin = CaseOrigin.PRIVATE_REPRESENTATIVE,
    estimator_source: EstimatorSource = EstimatorSource.LOCAL_WEIGHTS,
    policy: GatePolicy | None = None,
    include_audit: bool = True,
    unauthorized_access_count: int = 0,
    missing_access_event_count: int = 0,
    audit_start: datetime | None = None,
    audit_end: datetime | None = None,
    include_privacy: bool = True,
    pii_findings: int = 0,
    secret_findings: int = 0,
    private_content_findings: int = 0,
    include_repeat: bool = True,
    repeat_mismatch: bool = False,
) -> tuple[CalibrationReport, GatePolicy]:
    policy = policy or _policy()
    by_role: dict[str, list[EstimatorCase]] = {}
    for role, count in (
        ("development", development_count),
        ("active", active_count),
        ("holdout", holdout_count),
    ):
        role_cases = []
        for index in range(count):
            item = _case(role, index, origin=origin)
            if case_mutator is not None:
                item = case_mutator(role, index, item)
            role_cases.append(item)
        by_role[role] = role_cases
    all_cases = tuple(
        sorted(
            by_role["development"] + by_role["active"] + by_role["holdout"],
            key=lambda item: item.case_id,
        )
    )
    cohort = CalibrationCohort(
        cohort_id=_id("cohort"),
        completed_at=BASE + timedelta(days=18),
        cases=all_cases,
    )
    assignment_manifest = CaseAssignmentManifest(
        manifest_id=_id("assignment-manifest"),
        frozen_at=BASE + timedelta(days=11),
        assignments=tuple(
            sorted(
                (CaseAssignment.from_case(case) for case in all_cases),
                key=lambda item: item.case_id,
            )
        ),
    )
    split = CalibrationSplit(
        split_id=_id("split"),
        assignment_manifest_fingerprint=assignment_manifest.fingerprint,
        frozen_at=BASE + timedelta(days=12),
        development_case_ids=tuple(
            sorted(case.case_id for case in by_role["development"])
        ),
        active_learning_case_ids=tuple(
            sorted(case.case_id for case in by_role["active"])
        ),
        holdout_case_ids=tuple(sorted(case.case_id for case in by_role["holdout"])),
    )
    identity = EstimatorIdentityReceipt(
        identity_id=_id("identity"),
        source=estimator_source,
        plan_fingerprint=_id("plan"),
        requested_model_id="reserved-model-v1",
        served_model_id="reserved-model-v1",
        requested_model_revision="reserved-revision-v1",
        served_model_revision="reserved-revision-v1",
        requested_execution_mode=EstimatorExecutionMode.STANDARD,
        served_execution_mode=EstimatorExecutionMode.STANDARD,
        configuration_fingerprint=_id("configuration"),
        frozen_at=BASE + timedelta(days=13),
    )
    preregistration = GatePreregistration(
        preregistration_id=_id("preregistration"),
        policy_fingerprint=policy.fingerprint,
        assignment_manifest_fingerprint=assignment_manifest.fingerprint,
        split_fingerprint=split.fingerprint,
        estimator_identity_fingerprint=identity.fingerprint,
        registered_at=BASE + timedelta(days=14),
        metric_specs=(
            MetricGateSpec(
                metric_key=METRIC_KEY,
                label_vocabulary=("negative", "positive"),
                risk_tier=MetricRiskTier.HIGH,
                positive_label="positive",
            ),
        ),
    )
    audit = (
        HoldoutAccessAuditReceipt(
            audit_id=_id("access-audit"),
            split_fingerprint=split.fingerprint,
            auditor_version="reserved-auditor-v1",
            access_log_fingerprint=_id("access-log"),
            coverage_started_at=audit_start or BASE + timedelta(days=12),
            coverage_ended_at=audit_end or BASE + timedelta(days=19),
            unauthorized_access_count=unauthorized_access_count,
            missing_event_count=missing_access_event_count,
        )
        if include_audit
        else None
    )
    stability: list[StabilityReceipt] = []
    if include_repeat:
        for index, case in enumerate(by_role["holdout"]):
            second = (
                "negative" if case.candidate_label == "positive" else "positive"
            ) if repeat_mismatch and index < 3 else case.candidate_label
            stability.append(
                StabilityReceipt(
                    receipt_id=_id(f"stability:{index}"),
                    case_id=case.case_id,
                    condition=StabilityCondition.REPEAT,
                    trial_labels=(case.candidate_label, second),
                    observed_at=BASE + timedelta(days=17),
                )
            )
    bundle = CalibrationEvidenceBundle(
        estimator_identity=identity,
        assignment_manifest=assignment_manifest,
        cohort=cohort,
        split=split,
        preregistration=preregistration,
        holdout_access_audit=audit,
        stability_receipts=tuple(
            sorted(stability, key=lambda item: (item.case_id, item.condition.value))
        ),
        completed_at=BASE + timedelta(days=18),
    )
    privacy = (
        PrivacyScanReceipt(
            scan_id=_id("privacy-scan"),
            scanned_bundle_fingerprint=bundle.fingerprint,
            scanner_version="reserved-privacy-v1",
            completed_at=BASE + timedelta(days=19),
            pii_finding_count=pii_findings,
            secret_finding_count=secret_findings,
            private_content_finding_count=private_content_findings,
        )
        if include_privacy
        else None
    )
    return (
        CalibrationReport(
            report_id=_id("report"),
            evidence_bundle=bundle,
            privacy_scan=privacy,
            emitted_at=BASE + timedelta(days=20),
        ),
        policy,
    )


def _evaluate(report: CalibrationReport, policy: GatePolicy) -> ActivationGateDecision:
    return evaluate_activation_gate(
        report,
        policy,
        derived_at=BASE + timedelta(days=21),
    )


def _gate(decision: ActivationGateDecision, key: str):
    return next(check for check in decision.checks if check.check_key == key)


def test_complete_private_receipts_are_eligible() -> None:
    report, policy = _build_report()

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.ELIGIBLE
    assert all(check.outcome is GateCheckOutcome.PASS for check in decision.checks)
    assert _gate(decision, "active_learning_count").actual == 100
    assert _gate(decision, "holdout_count").actual == 40
    assert _gate(decision, "non_synthetic_origin").actual == 0
    assert _gate(decision, f"high_risk_precision.{METRIC_KEY}").actual == 1.0


@pytest.mark.parametrize(
    "forged_field",
    ("eligible", "synthetic_only", "holdout_untouched", "human_baseline_adjudicated"),
)
def test_caller_forged_gate_flags_are_impossible_by_contract(forged_field: str) -> None:
    report, _ = _build_report()
    values = report.model_dump()
    values[forged_field] = True

    with pytest.raises(ValidationError):
        CalibrationReport.model_validate(values)

    assert forged_field not in CalibrationReport.model_fields
    assert forged_field not in GatePreregistration.model_fields
    assert forged_field not in GatePolicy.model_fields


@pytest.mark.parametrize(
    ("origin", "source"),
    (
        (CaseOrigin.SYNTHETIC, EstimatorSource.LOCAL_WEIGHTS),
        (CaseOrigin.PRIVATE_REPRESENTATIVE, EstimatorSource.SYNTHETIC),
    ),
)
def test_synthetic_case_or_estimator_is_rejected(
    origin: CaseOrigin, source: EstimatorSource
) -> None:
    report, policy = _build_report(origin=origin, estimator_source=source)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "non_synthetic_origin").outcome is GateCheckOutcome.FAIL


@pytest.mark.parametrize(
    "source",
    (
        EstimatorSource.CODEX_CLI,
        EstimatorSource.MANUAL_IMPORT,
        EstimatorSource.OPENAI_API,
        EstimatorSource.ANTHROPIC_API,
    ),
)
def test_unverified_external_execution_boundaries_cannot_activate(
    source: EstimatorSource,
) -> None:
    report, policy = _build_report(estimator_source=source)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    boundary = _gate(decision, "activation_boundary")
    assert boundary.outcome is GateCheckOutcome.FAIL
    assert boundary.reason_code == "activation_boundary_unverified"


@pytest.mark.parametrize(
    ("field", "served_value"),
    (
        ("served_model_id", "reserved-fallback-model-v1"),
        ("served_model_revision", "reserved-fallback-revision-v1"),
        ("served_execution_mode", EstimatorExecutionMode.PRO),
    ),
)
def test_requested_and_served_identity_must_match_exactly(
    field: str,
    served_value: object,
) -> None:
    report, policy = _build_report()
    identity = report.evidence_bundle.estimator_identity.model_copy(
        update={field: served_value}
    )
    preregistration = report.evidence_bundle.preregistration.model_copy(
        update={"estimator_identity_fingerprint": identity.fingerprint}
    )
    bundle = report.evidence_bundle.model_copy(
        update={"estimator_identity": identity, "preregistration": preregistration}
    )
    privacy = report.privacy_scan
    assert privacy is not None
    privacy = privacy.model_copy(update={"scanned_bundle_fingerprint": bundle.fingerprint})
    changed = report.model_copy(update={"evidence_bundle": bundle, "privacy_scan": privacy})

    decision = _evaluate(changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    exact = _gate(decision, "exact_served_identity")
    assert exact.outcome is GateCheckOutcome.FAIL
    assert exact.reason_code == "requested_served_identity_mismatch"


def test_public_benchmark_without_private_evaluation_is_insufficient() -> None:
    report, policy = _build_report(origin=CaseOrigin.PUBLIC_BENCHMARK)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert (
        _gate(decision, "representative_private_evidence").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )


def test_cross_link_fingerprint_forgery_is_rejected_before_scoring() -> None:
    report, policy = _build_report()
    forged_split = report.evidence_bundle.split.model_copy(
        update={"assignment_manifest_fingerprint": _id("different-case-assignment")}
    )
    forged_bundle = report.evidence_bundle.model_copy(update={"split": forged_split})
    forged_report = report.model_copy(update={"evidence_bundle": forged_bundle})

    decision = _evaluate(forged_report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert tuple(check.check_key for check in decision.checks) == ("manifest_integrity",)
    assert decision.checks[0].outcome is GateCheckOutcome.FAIL


def test_split_identity_excludes_results_but_binds_static_case_assignment() -> None:
    report, policy = _build_report()
    bundle = report.evidence_bundle
    first_case = bundle.cohort.cases[0]
    original_assignment = CaseAssignment.from_case(first_case)

    changed_prediction = first_case.model_copy(
        update={"candidate_confidence": 0.75, "latency_ms": 75.0}
    )
    assert CaseAssignment.from_case(changed_prediction) == original_assignment
    assert (
        bundle.split.assignment_manifest_fingerprint
        == bundle.assignment_manifest.fingerprint
    )

    for update in (
        {"project_id": _id("changed-project")},
        {"observed_at": first_case.observed_at - timedelta(days=1)},
        {
            "task_stratum": next(
                value
                for value in CalibrationTaskStratum
                if value is not first_case.task_stratum
            )
        },
    ):
        changed_static = first_case.model_copy(update=update)
        changed_assignment = CaseAssignment.from_case(changed_static)
        assert changed_assignment != original_assignment
        changed_assignments = tuple(
            sorted(
                (
                    changed_assignment
                    if item.case_id == original_assignment.case_id
                    else item
                    for item in bundle.assignment_manifest.assignments
                ),
                key=lambda item: item.case_id,
            )
        )
        changed_manifest = bundle.assignment_manifest.model_copy(
            update={"assignments": changed_assignments}
        )
        assert changed_manifest.fingerprint != bundle.assignment_manifest.fingerprint

    membership_manifest = bundle.assignment_manifest.model_copy(
        update={"assignments": bundle.assignment_manifest.assignments[1:]}
    )
    assert membership_manifest.fingerprint != bundle.assignment_manifest.fingerprint

    changed_cases = (bundle.cohort.cases[1:])
    changed_cohort = bundle.cohort.model_copy(update={"cases": changed_cases})
    changed_bundle = bundle.model_copy(update={"cohort": changed_cohort})
    changed_report = report.model_copy(update={"evidence_bundle": changed_bundle})
    membership_decision = _evaluate(changed_report, policy)
    assert membership_decision.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(membership_decision, "manifest_integrity").outcome
        is GateCheckOutcome.FAIL
    )


def test_completed_result_static_projection_must_match_frozen_assignment() -> None:
    report, policy = _build_report()
    bundle = report.evidence_bundle
    cases = list(bundle.cohort.cases)
    cases[0] = cases[0].model_copy(update={"project_id": _id("substituted-project")})
    changed_cohort = bundle.cohort.model_copy(update={"cases": tuple(cases)})
    changed_bundle = bundle.model_copy(update={"cohort": changed_cohort})
    changed_report = report.model_copy(update={"evidence_bundle": changed_bundle})

    decision = _evaluate(changed_report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "manifest_integrity").outcome is GateCheckOutcome.FAIL


def test_privacy_scan_is_bound_and_findings_fail_closed() -> None:
    missing_report, policy = _build_report(include_privacy=False)
    missing = _evaluate(missing_report, policy)
    assert missing.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(missing, "privacy_scan").outcome is GateCheckOutcome.INSUFFICIENT_DATA

    findings_report, policy = _build_report(pii_findings=1)
    findings = _evaluate(findings_report, policy)
    assert findings.outcome is ActivationOutcome.REJECTED
    assert _gate(findings, "privacy_scan").outcome is GateCheckOutcome.FAIL

    clean_report, policy = _build_report()
    assert clean_report.privacy_scan is not None
    forged_scan = clean_report.privacy_scan.model_copy(
        update={"scanned_bundle_fingerprint": _id("unrelated-bundle")}
    )
    forged_report = clean_report.model_copy(update={"privacy_scan": forged_scan})
    forged = _evaluate(forged_report, policy)
    assert forged.outcome is ActivationOutcome.REJECTED
    assert _gate(forged, "manifest_integrity").outcome is GateCheckOutcome.FAIL


def test_holdout_access_is_derived_from_audit_and_preregistration_times() -> None:
    missing_report, policy = _build_report(include_audit=False)
    missing = _evaluate(missing_report, policy)
    assert missing.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert (
        _gate(missing, "holdout_access_audit").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )

    violated_report, policy = _build_report(unauthorized_access_count=1)
    violated = _evaluate(violated_report, policy)
    assert violated.outcome is ActivationOutcome.REJECTED
    assert _gate(violated, "holdout_access_audit").outcome is GateCheckOutcome.FAIL

    def early(role: str, _: int, case: EstimatorCase) -> EstimatorCase:
        return (
            case.model_copy(update={"evaluated_at": BASE + timedelta(days=13)})
            if role == "holdout"
            else case
        )

    early_report, policy = _build_report(case_mutator=early)
    early_decision = _evaluate(early_report, policy)
    assert early_decision.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(early_decision, "holdout_evaluated_after_preregistration").outcome
        is GateCheckOutcome.FAIL
    )


@pytest.mark.parametrize(
    ("active_count", "expected"),
    ((99, GateCheckOutcome.INSUFFICIENT_DATA), (201, GateCheckOutcome.FAIL)),
)
def test_active_learning_judgment_count_is_derived_and_bounded(
    active_count: int, expected: GateCheckOutcome
) -> None:
    report, policy = _build_report(active_count=active_count)

    decision = _evaluate(report, policy)

    assert decision.outcome is not ActivationOutcome.ELIGIBLE
    assert _gate(decision, "active_learning_count").outcome is expected


def test_holdout_adequacy_four_strata_and_en_pl_are_derived() -> None:
    small_report, policy = _build_report(holdout_count=39)
    small = _evaluate(small_report, policy)
    assert small.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(small, "holdout_count").outcome is GateCheckOutcome.INSUFFICIENT_DATA

    def collapse(role: str, _: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout":
            return case.model_copy(
                update={
                    "task_stratum": CalibrationTaskStratum.BUG_FIX,
                    "language": CalibrationLanguage.EN,
                }
            )
        return case

    collapsed_report, policy = _build_report(case_mutator=collapse)
    collapsed = _evaluate(collapsed_report, policy)
    assert collapsed.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(collapsed, "holdout_strata").outcome is GateCheckOutcome.INSUFFICIENT_DATA
    assert (
        _gate(collapsed, "holdout_languages").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )


def test_project_and_time_separation_are_derived_from_case_receipts() -> None:
    shared_project = _id("project:calibration:0")

    def overlap(role: str, _: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout":
            return case.model_copy(
                update={
                    "project_id": shared_project,
                    "observed_at": BASE + timedelta(days=2),
                }
            )
        return case

    report, policy = _build_report(case_mutator=overlap)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "project_separation").outcome is GateCheckOutcome.FAIL
    assert _gate(decision, "time_separation").outcome is GateCheckOutcome.FAIL


@pytest.mark.parametrize(
    "truth_source",
    (ReferenceTruthSource.MODEL_CONSENSUS, ReferenceTruthSource.SELF_REPORTED_COMPLETION),
)
def test_model_consensus_and_completion_claims_are_not_truth(
    truth_source: ReferenceTruthSource,
) -> None:
    def unsupported(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        return (
            case.model_copy(update={"truth_source": truth_source})
            if role == "holdout" and index == 0
            else case
        )

    report, policy = _build_report(case_mutator=unsupported)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "non_consensus_truth").outcome is GateCheckOutcome.FAIL


def test_human_baseline_requires_adjudication_receipts() -> None:
    def missing(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        return (
            case.model_copy(
                update={
                    "human_baseline_label": None,
                    "human_adjudication_receipt_id": None,
                }
            )
            if role == "holdout" and index == 0
            else case
        )

    report, policy = _build_report(case_mutator=missing)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert (
        _gate(decision, "human_adjudicated_baseline").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )
    assert (
        _gate(decision, "human_performance_gap").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )


def test_calibration_and_repeat_stability_are_derived_from_trials() -> None:
    def uncalibrated(role: str, _: int, case: EstimatorCase) -> EstimatorCase:
        return (
            case.model_copy(update={"candidate_confidence": 0.50})
            if role == "holdout"
            else case
        )

    report, policy = _build_report(case_mutator=uncalibrated)
    decision = _evaluate(report, policy)
    assert decision.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(decision, "expected_calibration_error").outcome is GateCheckOutcome.FAIL
    )

    no_repeat_report, policy = _build_report(include_repeat=False)
    no_repeat = _evaluate(no_repeat_report, policy)
    assert no_repeat.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert (
        _gate(no_repeat, "repeat_stability").outcome
        is GateCheckOutcome.INSUFFICIENT_DATA
    )

    unstable_report, policy = _build_report(repeat_mismatch=True)
    unstable = _evaluate(unstable_report, policy)
    assert unstable.outcome is ActivationOutcome.REJECTED
    assert _gate(unstable, "repeat_stability").outcome is GateCheckOutcome.FAIL


def test_selective_risk_coverage_and_false_confident_errors_are_derived() -> None:
    def abstain(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout" and index < 3:
            return case.model_copy(
                update={
                    "run_state": CaseRunState.ABSTAINED,
                    "candidate_label": None,
                    "candidate_confidence": None,
                }
            )
        return case

    coverage_report, policy = _build_report(case_mutator=abstain)
    coverage = _evaluate(coverage_report, policy)
    assert coverage.outcome is ActivationOutcome.REJECTED
    assert _gate(coverage, "selective_coverage").outcome is GateCheckOutcome.FAIL

    def false_confident(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout" and index == 1:
            return case.model_copy(update={"candidate_label": "positive"})
        return case

    error_report, policy = _build_report(case_mutator=false_confident)
    error = _evaluate(error_report, policy)
    assert error.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(error, "false_confident_error_rate").outcome is GateCheckOutcome.FAIL
    )


@pytest.mark.parametrize(
    ("state", "check_key"),
    (
        (CaseRunState.OOM, "run_rate.oom"),
        (CaseRunState.ERROR, "run_rate.error"),
        (CaseRunState.REFUSAL, "run_rate.refusal"),
    ),
)
def test_operational_failure_rates_are_derived(
    state: CaseRunState, check_key: str
) -> None:
    def fail(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout" and index == 0:
            return case.model_copy(
                update={
                    "run_state": state,
                    "candidate_label": None,
                    "candidate_confidence": None,
                }
            )
        return case

    report, policy = _build_report(case_mutator=fail)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, check_key).outcome is GateCheckOutcome.FAIL


def test_latency_gate_uses_cold_and_warm_p95_receipts() -> None:
    def slow(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        return (
            case.model_copy(update={"latency_ms": 2_000.0})
            if role == "holdout" and index % 2 == 0
            else case
        )

    report, policy = _build_report(case_mutator=slow)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "latency_p95.cold").outcome is GateCheckOutcome.FAIL
    assert _gate(decision, "latency_p95.warm").outcome is GateCheckOutcome.PASS


def test_material_subgroup_regression_is_not_hidden_by_aggregate_performance() -> None:
    def regress(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        if (
            role == "holdout"
            and case.task_stratum is CalibrationTaskStratum.CODE_REVIEW
        ):
            replacement = "negative" if case.reference_label == "positive" else "positive"
            return case.model_copy(update={"candidate_label": replacement})
        return case

    report, policy = _build_report(case_mutator=regress)

    decision = _evaluate(report, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(decision, "subgroup_regression.task_stratum").outcome
        is GateCheckOutcome.FAIL
    )


def test_high_risk_precision_is_metric_specific_and_preregistered() -> None:
    def false_positives(role: str, index: int, case: EstimatorCase) -> EstimatorCase:
        if role == "holdout" and index in {1, 3, 5}:
            return case.model_copy(update={"candidate_label": "positive"})
        return case

    report, policy = _build_report(case_mutator=false_positives)
    decision = _evaluate(report, policy)
    assert decision.outcome is ActivationOutcome.REJECTED
    assert (
        _gate(decision, f"high_risk_precision.{METRIC_KEY}").outcome
        is GateCheckOutcome.FAIL
    )

    mismatched_policy = policy.model_copy(update={"high_risk_precision_rules": ()})
    mismatch = _evaluate(report, mismatched_policy)
    assert mismatch.outcome is ActivationOutcome.REJECTED
    assert tuple(check.check_key for check in mismatch.checks) == ("manifest_integrity",)


def test_gate_records_are_frozen_fingerprinted_and_content_free() -> None:
    report, policy = _build_report()
    decision = _evaluate(report, policy)

    assert report.fingerprint == CalibrationReport.model_validate(
        report.model_dump()
    ).fingerprint
    assert decision.fingerprint == ActivationGateDecision.model_validate(
        decision.model_dump()
    ).fingerprint
    with pytest.raises(ValidationError):
        report.report_id = _id("mutated")  # type: ignore[misc]

    forbidden = {
        "prompt",
        "transcript",
        "excerpt",
        "rationale",
        "chain_of_thought",
        "model_output",
        "eligible",
        "synthetic_only",
        "holdout_untouched",
    }
    models = (
        EstimatorCase,
        CalibrationCohort,
        CalibrationSplit,
        GatePreregistration,
        CalibrationReport,
        GatePolicy,
        ActivationGateDecision,
    )
    assert all(forbidden.isdisjoint(model.model_fields) for model in models)


def test_invalid_labels_timestamps_and_execution_shapes_fail_closed() -> None:
    case = _case("holdout", 0)
    with pytest.raises(ValidationError):
        EstimatorCase.model_validate(
            {**case.model_dump(), "candidate_label": "contains private prose"}
        )
    with pytest.raises(ValidationError):
        EstimatorCase.model_validate(
            {**case.model_dump(), "evaluated_at": datetime(2042, 1, 1)}
        )
    with pytest.raises(ValidationError):
        EstimatorCase.model_validate(
            {
                **case.model_dump(),
                "run_state": CaseRunState.ERROR,
                "candidate_label": "positive",
            }
        )
