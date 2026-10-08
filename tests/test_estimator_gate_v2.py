from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators.contracts import (
    ArtifactAvailability,
    EstimatorPlan,
    EstimatorReasoningEffort,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    MetricDirection,
    MetricQuestionSpec,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelSource,
    ProviderSchemaIdentity,
    StageCondition,
    TokenizerIdentity,
)
from prompt_enhancer.application.estimators.gate_contracts import (
    ActivationOutcome,
    CalibrationCohort,
    CalibrationLanguage,
    CalibrationSplit,
    CalibrationTaskStratum,
    CaseOrigin,
    CaseRunState,
    EvidenceTier,
    GateCheckOutcome,
    GatePolicy,
    GatePreregistration,
    HoldoutAccessAuditReceipt,
    LatencyClass,
    MetricGateSpec,
    MetricRiskTier,
    PrivacyScanReceipt,
    ReferenceTruthSource,
    StabilityCondition,
    EstimatorCase,
)
from prompt_enhancer.application.estimators.gate_v2_contracts import (
    ActivationGateDecisionV2,
    AttemptIdentityReceipt,
    AttemptOutcomeReceipt,
    AuthoritativeCandidateProjection,
    BlindCalibrationAdjudication,
    BlindCalibrationJudgment,
    BlindCalibrationResolution,
    BlindCalibrationSource,
    CaseAssignmentManifestV2,
    CaseAssignmentV2,
    ConstellationIdentityReceipt,
    ExecutionIdentityAudit,
    ExpectedAttempt,
    ExpectedAttemptManifest,
    GateEvidenceV2,
    GatePreregistrationV2,
    StabilityReceiptV2,
    StabilityTrialV2,
)
from prompt_enhancer.application.estimators.gate_v2_evaluation import (
    evaluate_activation_gate_v2,
)
from prompt_enhancer.domain import Provider


BASE = datetime(2044, 1, 1, tzinfo=UTC)
METRIC_KEY = "verification_quality"


def _id(value: str) -> str:
    return hashlib.sha256(f"reserved-v2-synthetic:{value}".encode("ascii")).hexdigest()


def _artifact(label: str, *, synthetic: bool) -> ModelArtifactIdentity:
    availability = (
        ArtifactAvailability.SYNTHETIC_NO_WEIGHTS
        if synthetic
        else ArtifactAvailability.PROVIDER_MANAGED
    )
    return ModelArtifactIdentity(
        source=ModelSource.SYNTHETIC if synthetic else ModelSource.OPENAI_API,
        requested_model_id=f"reserved-{label}-model-v1",
        served_model_id=f"reserved-{label}-model-v1",
        requested_revision="reserved-revision-v1",
        served_revision="reserved-revision-v1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        weight_availability=availability,
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"reserved-{label}-tokenizer-v1",
            revision="reserved-revision-v1",
            availability=availability,
        ),
        license_id="reserved-example-license-v1",
    )


def _plan(*, synthetic: bool = False) -> EstimatorPlan:
    question = MetricQuestionSpec(
        metric_key=METRIC_KEY,
        metric_definition_version="metric-v1",
        question_id="verification-quality-question",
        question_version="question-v1",
        question_sha256=_id("question"),
        prompt_template_id="verification-quality-template",
        prompt_template_version="template-v1",
        prompt_template_sha256=_id("template"),
        rubric_id="verification-quality-rubric",
        rubric_version="rubric-v1",
        rubric_sha256=_id("rubric"),
        output_schema_version="metric-output-v1",
        value_kind=MetricValueKind.CATEGORICAL,
        unit_code="label",
        direction=MetricDirection.DESCRIPTIVE,
    )
    model_kinds = {
        EstimatorStageKind.EMBEDDING_RETRIEVAL,
        EstimatorStageKind.RERANKER,
        EstimatorStageKind.SPECIALIST,
        EstimatorStageKind.SECOND_OPINION,
    }
    ordered = tuple(EstimatorStageKind)
    stages = tuple(
        EstimatorStage(
            ordinal=index,
            kind=kind,
            condition=(
                StageCondition.DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE
                if kind is EstimatorStageKind.SECOND_OPINION
                else StageCondition.UNRESOLVED_DISAGREEMENT
                if kind is EstimatorStageKind.HUMAN_ADJUDICATION
                else StageCondition.ALWAYS
            ),
            component_version=f"reserved-stage-{index}-v1",
            configuration_sha256=_id(f"stage-config:{index}"),
            output_schema_version=f"reserved-stage-output-{index}-v1",
            model_artifact=(
                _artifact(f"stage-{index}", synthetic=synthetic)
                if kind in model_kinds
                else None
            ),
        )
        for index, kind in enumerate(ordered, start=1)
    )
    return EstimatorPlan(
        plan_key="reserved-balanced-gate",
        plan_version="reserved-plan-v1",
        route=EstimatorRoute.BALANCED,
        question_specs=(question,),
        evidence_packet_schema_version="reserved-packet-v1",
        provider_schemas=(
            ProviderSchemaIdentity(
                provider=Provider.CODEX,
                adapter_version="reserved-adapter-v1",
                provider_schema_version="reserved-provider-schema-v1",
            ),
        ),
        preprocessing_version="reserved-preprocessing-v1",
        preprocessing_sha256=_id("preprocessing"),
        reasoning_effort=EstimatorReasoningEffort.MEDIUM,
        calibration_version="reserved-calibration-v1",
        calibration_sha256=_id("calibration"),
        router_version="reserved-router-v1",
        router_sha256=_id("router"),
        redactor_version="reserved-redactor-v1",
        redactor_sha256=_id("redactor"),
        stages=stages,
    )


def _policy() -> GatePolicy:
    return GatePolicy(
        policy_id=_id("policy"),
        minimum_holdout_count=8,
        minimum_holdout_per_metric=8,
        minimum_holdout_per_stratum=2,
        minimum_holdout_per_language=4,
        minimum_operational_samples_per_latency_class=4,
        minimum_subgroup_size=2,
        minimum_baseline_margin=0.0,
        minimum_selective_coverage=0.95,
        maximum_selective_risk=0.05,
        false_confidence_threshold=0.90,
        maximum_false_confident_error_rate=0.0,
        maximum_cold_p95_latency_ms=1_000.0,
        maximum_warm_p95_latency_ms=500.0,
        maximum_oom_rate=0.01,
        maximum_error_rate=0.01,
        maximum_refusal_rate=0.01,
        maximum_material_subgroup_regression=0.02,
    )


def _case(role: str, index: int) -> EstimatorCase:
    holdout = role == "holdout"
    reference = "positive" if index % 2 == 0 else "negative"
    baseline = (
        ("negative" if reference == "positive" else "positive")
        if holdout and index % 4 == 0
        else reference
    )
    return EstimatorCase(
        case_id=_id(f"case:{role}:{index}"),
        project_id=_id(f"project:{role if holdout else 'nonholdout'}:{index % 2}"),
        session_revision_id=_id(f"revision:{role}:{index}"),
        metric_key=METRIC_KEY,
        provider=Provider.CODEX,
        origin=CaseOrigin.PRIVATE_REPRESENTATIVE,
        task_stratum=tuple(CalibrationTaskStratum)[index % 4],
        language=tuple(CalibrationLanguage)[index % 2],
        evidence_tier=(EvidenceTier.OBJECTIVE if index % 2 == 0 else EvidenceTier.HUMAN),
        observed_at=BASE + timedelta(days=8 if holdout else 1 + (index % 2)),
        evaluated_at=BASE + timedelta(days=15 if holdout else 11),
        truth_source=(
            ReferenceTruthSource.OBJECTIVE_CHECK
            if index % 2 == 0
            else ReferenceTruthSource.HUMAN_ADJUDICATED
        ),
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


def _blind(
    case: EstimatorCase,
    assignment: CaseAssignmentV2,
    *,
    source: BlindCalibrationSource,
) -> BlindCalibrationAdjudication:
    label = (
        case.reference_label
        if source is BlindCalibrationSource.REFERENCE_TRUTH
        else case.human_baseline_label
    )
    assert label is not None
    adjudication_id = (
        case.truth_receipt_id
        if source is BlindCalibrationSource.REFERENCE_TRUTH
        else case.human_adjudication_receipt_id
    )
    assert adjudication_id is not None
    judgments = tuple(
        BlindCalibrationJudgment(
            judgment_id=_id(f"judgment:{case.case_id}:{source.value}:{index}"),
            adjudicator_id=_id(f"adjudicator:{index}"),
            case_id=case.case_id,
            metric_question_fingerprint=assignment.metric_question_fingerprint,
            evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
            label_code=label,
            annotation_protocol_version="reserved-blind-protocol-v1",
            created_at=BASE + timedelta(days=16, minutes=index),
        )
        for index in (1, 2)
    )
    return BlindCalibrationAdjudication(
        adjudication_id=adjudication_id,
        case_id=case.case_id,
        plan_fingerprint=assignment.plan_fingerprint,
        metric_question_fingerprint=assignment.metric_question_fingerprint,
        evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
        source=source,
        resolution=BlindCalibrationResolution.RESOLVED,
        judgments=judgments,
        resolved_label_code=label,
        completed_at=BASE + timedelta(days=16, minutes=3),
    )


def _build_evidence(
    *,
    plan: EstimatorPlan | None = None,
    include_constellation: bool = True,
    include_attempt_audit: bool = True,
) -> tuple[EstimatorPlan, GateEvidenceV2, GatePolicy]:
    plan = plan or _plan()
    policy = _policy()
    by_role = {
        "development": [_case("development", index) for index in range(8)],
        "active": [_case("active", index) for index in range(100)],
        "holdout": [_case("holdout", index) for index in range(8)],
    }
    all_cases = tuple(
        sorted(
            by_role["development"] + by_role["active"] + by_role["holdout"],
            key=lambda item: item.case_id,
        )
    )
    question_fingerprint = plan.question_specs[0].canonical_fingerprint
    assignments = tuple(
        sorted(
            (
                CaseAssignmentV2.from_case(
                    case,
                    plan_fingerprint=plan.canonical_fingerprint,
                    metric_question_fingerprint=question_fingerprint,
                    evidence_packet_fingerprint=_id(f"packet:{case.case_id}"),
                )
                for case in all_cases
            ),
            key=lambda item: item.case_id,
        )
    )
    manifest = CaseAssignmentManifestV2(
        manifest_id=_id("manifest"),
        plan_fingerprint=plan.canonical_fingerprint,
        frozen_at=BASE + timedelta(days=9),
        assignments=assignments,
    )
    cohort = CalibrationCohort(
        cohort_id=_id("cohort"),
        completed_at=BASE + timedelta(days=16, hours=1),
        cases=all_cases,
    )
    split = CalibrationSplit(
        split_id=_id("split"),
        assignment_manifest_fingerprint=manifest.fingerprint,
        frozen_at=BASE + timedelta(days=10),
        development_case_ids=tuple(
            sorted(case.case_id for case in by_role["development"])
        ),
        active_learning_case_ids=tuple(
            sorted(case.case_id for case in by_role["active"])
        ),
        holdout_case_ids=tuple(sorted(case.case_id for case in by_role["holdout"])),
    )
    constellation = (
        ConstellationIdentityReceipt.from_plan(
            plan,
            constellation_id=_id("constellation"),
            frozen_at=BASE + timedelta(days=10, hours=1),
        )
        if include_constellation
        else None
    )
    preregistration = GatePreregistration(
        preregistration_id=_id("preregistration"),
        policy_fingerprint=policy.fingerprint,
        assignment_manifest_fingerprint=manifest.fingerprint,
        split_fingerprint=split.fingerprint,
        estimator_identity_fingerprint=_id("legacy-v1-identity-not-authoritative"),
        registered_at=BASE + timedelta(days=12),
        metric_specs=(
            MetricGateSpec(
                metric_key=METRIC_KEY,
                label_vocabulary=("negative", "positive"),
                risk_tier=MetricRiskTier.STANDARD,
            ),
        ),
    )
    assignment_by_id = {item.case_id: item for item in assignments}
    attempts: list[AttemptIdentityReceipt] = []
    outcomes: list[AttemptOutcomeReceipt] = []
    candidate_projections: list[AuthoritativeCandidateProjection] = []
    stability: list[StabilityReceiptV2] = []
    if constellation is not None:
        specialist_identity = next(
            item
            for item in constellation.stages
            if item.kind is EstimatorStageKind.SPECIALIST
        )
        specialist_stage = plan.stages[specialist_identity.ordinal - 1]
        assert specialist_stage.model_artifact is not None
        for role in ("active", "holdout"):
            for case in by_role[role]:
                assignment = assignment_by_id[case.case_id]
                primary = AttemptIdentityReceipt.from_artifact(
                    attempt_id=_id(f"attempt:primary:{case.case_id}"),
                    execution_id=_id(f"execution:primary:{case.case_id}"),
                    case_id=case.case_id,
                    plan_fingerprint=plan.canonical_fingerprint,
                    metric_question_fingerprint=assignment.metric_question_fingerprint,
                    evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                    constellation_stage=specialist_identity,
                    artifact=specialist_stage.model_artifact,
                    fallback_used=False,
                    fallback_reason_code=None,
                    attempted_at=BASE
                    + timedelta(days=15 if role == "holdout" else 11, hours=1),
                )
                attempts.append(primary)
                primary_outcome = AttemptOutcomeReceipt(
                    outcome_id=_id(f"outcome:primary:{case.case_id}"),
                    attempt_id=primary.attempt_id,
                    execution_id=primary.execution_id,
                    case_id=case.case_id,
                    plan_fingerprint=plan.canonical_fingerprint,
                    metric_question_fingerprint=assignment.metric_question_fingerprint,
                    evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                    structured_output_fingerprint=_id(f"output:primary:{case.case_id}"),
                    run_state=case.run_state,
                    candidate_label=case.candidate_label,
                    candidate_confidence=case.candidate_confidence,
                    latency_class=case.latency_class,
                    latency_ms=case.latency_ms or 0.0,
                    completed_at=primary.attempted_at + timedelta(minutes=1),
                )
                outcomes.append(primary_outcome)
                candidate_projections.append(
                    AuthoritativeCandidateProjection(
                        projection_id=_id(f"projection:{case.case_id}"),
                        case_id=case.case_id,
                        plan_fingerprint=plan.canonical_fingerprint,
                        metric_question_fingerprint=assignment.metric_question_fingerprint,
                        evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                        authoritative_attempt_id=primary.attempt_id,
                        authoritative_outcome_id=primary_outcome.outcome_id,
                        authoritative_outcome_fingerprint=primary_outcome.fingerprint,
                        final_estimate_fingerprint=_id(f"final-estimate:{case.case_id}"),
                        selected_at=primary_outcome.completed_at + timedelta(minutes=1),
                    )
                )
                if role == "holdout":
                    repeated = AttemptIdentityReceipt.from_artifact(
                        attempt_id=_id(f"attempt:repeat:{case.case_id}"),
                        execution_id=_id(f"execution:repeat:{case.case_id}"),
                        case_id=case.case_id,
                        plan_fingerprint=plan.canonical_fingerprint,
                        metric_question_fingerprint=assignment.metric_question_fingerprint,
                        evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                        constellation_stage=specialist_identity,
                        artifact=specialist_stage.model_artifact,
                        fallback_used=False,
                        fallback_reason_code=None,
                        attempted_at=BASE + timedelta(days=16, hours=2),
                    )
                    attempts.append(repeated)
                    repeated_outcome = AttemptOutcomeReceipt(
                        outcome_id=_id(f"outcome:repeat:{case.case_id}"),
                        attempt_id=repeated.attempt_id,
                        execution_id=repeated.execution_id,
                        case_id=case.case_id,
                        plan_fingerprint=plan.canonical_fingerprint,
                        metric_question_fingerprint=assignment.metric_question_fingerprint,
                        evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                        structured_output_fingerprint=_id(f"output:repeat:{case.case_id}"),
                        run_state=case.run_state,
                        candidate_label=case.candidate_label,
                        candidate_confidence=case.candidate_confidence,
                        latency_class=case.latency_class,
                        latency_ms=case.latency_ms or 0.0,
                        completed_at=repeated.attempted_at + timedelta(minutes=1),
                    )
                    outcomes.append(repeated_outcome)
                    stability.append(
                        StabilityReceiptV2(
                            receipt_id=_id(f"stability:{case.case_id}"),
                            case_id=case.case_id,
                            metric_question_fingerprint=assignment.metric_question_fingerprint,
                            evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
                            condition=StabilityCondition.REPEAT,
                            trials=(
                                StabilityTrialV2(
                                    trial_ordinal=1,
                                    attempt_id=primary.attempt_id,
                                    outcome_receipt_id=primary_outcome.outcome_id,
                                    outcome_fingerprint=primary_outcome.fingerprint,
                                ),
                                StabilityTrialV2(
                                    trial_ordinal=2,
                                    attempt_id=repeated.attempt_id,
                                    outcome_receipt_id=repeated_outcome.outcome_id,
                                    outcome_fingerprint=repeated_outcome.fingerprint,
                                ),
                            ),
                            observed_at=BASE + timedelta(days=17),
                        )
                    )
    expected_attempt_manifest = (
        ExpectedAttemptManifest(
            manifest_id=_id("expected-attempt-manifest"),
            plan_fingerprint=plan.canonical_fingerprint,
            execution_set_fingerprint=_id("persisted-execution-stage-set"),
            attempts=tuple(
                sorted(
                    (
                        ExpectedAttempt(
                            attempt_id=item.attempt_id,
                            execution_id=item.execution_id,
                            case_id=item.case_id,
                            stage_ordinal=item.stage_ordinal,
                            stage_kind=item.stage_kind,
                        )
                        for item in attempts
                    ),
                    key=lambda item: item.attempt_id,
                )
            ),
            frozen_at=BASE + timedelta(days=17),
        )
        if constellation is not None
        else None
    )
    identity_audit = (
        ExecutionIdentityAudit(
            audit_id=_id("identity-audit"),
            plan_fingerprint=plan.canonical_fingerprint,
            constellation_fingerprint=constellation.fingerprint,
            expected_attempt_manifest_fingerprint=expected_attempt_manifest.fingerprint,
            auditor_version="reserved-identity-auditor-v1",
            attempts=tuple(sorted(attempts, key=lambda item: item.attempt_id)),
            outcomes=tuple(sorted(outcomes, key=lambda item: item.attempt_id)),
            candidate_projections=tuple(
                sorted(candidate_projections, key=lambda item: item.case_id)
            ),
            coverage_started_at=BASE + timedelta(days=11),
            coverage_ended_at=BASE + timedelta(days=17),
            completed_at=BASE + timedelta(days=17, hours=1),
        )
        if include_attempt_audit and constellation is not None
        else None
    )
    blind = []
    for role in ("active", "holdout"):
        for case in by_role[role]:
            assignment = assignment_by_id[case.case_id]
            blind.append(
                _blind(
                    case,
                    assignment,
                    source=BlindCalibrationSource.REFERENCE_TRUTH,
                )
            )
            if role == "holdout":
                blind.append(
                    _blind(
                        case,
                        assignment,
                        source=BlindCalibrationSource.HUMAN_BASELINE,
                    )
                )
    access_audit = HoldoutAccessAuditReceipt(
        audit_id=_id("holdout-access-audit"),
        split_fingerprint=split.fingerprint,
        auditor_version="reserved-access-auditor-v1",
        access_log_fingerprint=_id("holdout-access-log"),
        coverage_started_at=BASE + timedelta(days=10),
        coverage_ended_at=BASE + timedelta(days=18),
        unauthorized_access_count=0,
        missing_event_count=0,
    )
    preregistration_v2 = (
        GatePreregistrationV2(
            preregistration_id=_id("preregistration-v2"),
            policy_fingerprint=policy.fingerprint,
            assignment_manifest_fingerprint=manifest.fingerprint,
            split_fingerprint=split.fingerprint,
            stored_plan_fingerprint=plan.canonical_fingerprint,
            constellation_fingerprint=constellation.fingerprint,
            legacy_preregistration_fingerprint=preregistration.fingerprint,
            registered_at=preregistration.registered_at,
        )
        if constellation is not None
        else None
    )
    evidence = GateEvidenceV2(
        evidence_id=_id("evidence"),
        stored_plan_fingerprint=plan.canonical_fingerprint,
        assignment_manifest=manifest,
        cohort=cohort,
        split=split,
        preregistration=preregistration,
        preregistration_v2=preregistration_v2,
        constellation_identity=constellation,
        expected_attempt_manifest=expected_attempt_manifest,
        execution_identity_audit=identity_audit,
        holdout_access_audit=access_audit,
        stability_receipts=tuple(
            sorted(stability, key=lambda item: (item.case_id, item.condition.value))
        ),
        blind_adjudications=tuple(
            sorted(blind, key=lambda item: (item.case_id, item.source.value))
        ),
        completed_at=BASE + timedelta(days=18),
    )
    privacy = PrivacyScanReceipt(
        scan_id=_id("privacy-scan"),
        scanned_bundle_fingerprint=evidence.scannable_fingerprint,
        scanner_version="reserved-privacy-scanner-v1",
        completed_at=BASE + timedelta(days=19),
        pii_finding_count=0,
        secret_finding_count=0,
        private_content_finding_count=0,
    )
    return plan, evidence.model_copy(update={"privacy_scan": privacy}), policy


def _evaluate(
    plan: EstimatorPlan, evidence: GateEvidenceV2, policy: GatePolicy
) -> ActivationGateDecisionV2:
    return evaluate_activation_gate_v2(
        plan,
        evidence,
        policy,
        derived_at=BASE + timedelta(days=20),
    )


def _gate(decision: ActivationGateDecisionV2, key: str):
    return next(item for item in decision.checks if item.check_key == key)


def _rebind_privacy(evidence: GateEvidenceV2) -> GateEvidenceV2:
    assert evidence.privacy_scan is not None
    privacy = evidence.privacy_scan.model_copy(
        update={"scanned_bundle_fingerprint": evidence.scannable_fingerprint}
    )
    return evidence.model_copy(update={"privacy_scan": privacy})


def test_complete_v2_constellation_gate_is_provisional_and_fail_closed() -> None:
    plan, evidence, policy = _build_evidence()

    decision = _evaluate(plan, evidence, policy)

    assert decision.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(decision, "immutable_evidence_persistence").reason_code == (
        "sealed_repository_projection_not_implemented"
    )
    assert all(
        item.outcome is GateCheckOutcome.PASS
        for item in decision.checks
        if item.check_key != "immutable_evidence_persistence"
    )
    assert decision == ActivationGateDecisionV2.model_validate(decision.model_dump())
    assert decision.fingerprint == ActivationGateDecisionV2.model_validate(
        decision.model_dump()
    ).fingerprint


def test_case_assignment_binds_plan_question_and_packet() -> None:
    plan, evidence, policy = _build_evidence()
    assignment = evidence.assignment_manifest.assignments[0]
    for field in (
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    ):
        forged = assignment.model_copy(update={field: _id(f"forged:{field}")})
        assignments = tuple(
            forged if item.case_id == assignment.case_id else item
            for item in evidence.assignment_manifest.assignments
        )
        manifest = evidence.assignment_manifest.model_copy(update={"assignments": assignments})
        changed = evidence.model_copy(update={"assignment_manifest": manifest})

        decision = _evaluate(plan, changed, policy)

        assert decision.outcome is ActivationOutcome.REJECTED
        assert tuple(item.check_key for item in decision.checks) == ("manifest_integrity",)


def test_constellation_must_cover_every_stored_plan_model_stage() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.constellation_identity is not None
    assert len(evidence.constellation_identity.stages) == 4
    shortened = evidence.constellation_identity.model_copy(
        update={"stages": evidence.constellation_identity.stages[:-1]}
    )
    changed = evidence.model_copy(update={"constellation_identity": shortened})

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "manifest_integrity").outcome is GateCheckOutcome.FAIL


def test_v2_preregistration_commits_plan_and_constellation() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.preregistration_v2 is not None
    forged = evidence.preregistration_v2.model_copy(
        update={"constellation_fingerprint": _id("substituted-constellation")}
    )
    changed = evidence.model_copy(update={"preregistration_v2": forged})

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert tuple(item.check_key for item in decision.checks) == ("manifest_integrity",)


def test_missing_v2_preregistration_is_never_eligible() -> None:
    plan, evidence, policy = _build_evidence()
    changed = _rebind_privacy(evidence.model_copy(update={"preregistration_v2": None}))

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(decision, "v2_preregistration").reason_code == (
        "v2_preregistration_missing"
    )


def test_each_attempt_is_audited_against_exact_plan_identity() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.execution_identity_audit is not None
    attempts = list(evidence.execution_identity_audit.attempts)
    attempts[0] = attempts[0].model_copy(
        update={"stage_configuration_sha256": _id("substituted-configuration")}
    )
    audit = evidence.execution_identity_audit.model_copy(update={"attempts": tuple(attempts)})
    changed = _rebind_privacy(
        evidence.model_copy(update={"execution_identity_audit": audit})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "exact_attempt_identity").outcome is GateCheckOutcome.FAIL


def test_identity_audit_cannot_omit_a_persisted_attempt() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.execution_identity_audit is not None
    audit = evidence.execution_identity_audit.model_copy(
        update={
            "attempts": evidence.execution_identity_audit.attempts[1:],
            "outcomes": evidence.execution_identity_audit.outcomes[1:],
        }
    )
    changed = _rebind_privacy(
        evidence.model_copy(update={"execution_identity_audit": audit})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "execution_identity_audit").reason_code == (
        "persisted_attempt_set_mismatch"
    )


def test_fallback_identity_is_exact_and_cannot_activate() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.execution_identity_audit is not None
    original = evidence.execution_identity_audit.attempts[0]
    with pytest.raises(ValidationError):
        AttemptIdentityReceipt.model_validate(
            {
                **original.model_dump(),
                "served_model_id": "reserved-fallback-model-v1",
                "fallback_used": False,
            }
        )
    fallback = original.model_copy(
        update={
            "served_model_id": "reserved-fallback-model-v1",
            "fallback_used": True,
            "fallback_reason_code": "provider_fallback",
        }
    )
    attempts = tuple(
        fallback if item.attempt_id == original.attempt_id else item
        for item in evidence.execution_identity_audit.attempts
    )
    audit = evidence.execution_identity_audit.model_copy(update={"attempts": attempts})

    decision = _evaluate(
        plan,
        _rebind_privacy(evidence.model_copy(update={"execution_identity_audit": audit})),
        policy,
    )

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "exact_attempt_identity").outcome is GateCheckOutcome.FAIL


def test_stability_trials_must_reference_real_audited_attempts() -> None:
    plan, evidence, policy = _build_evidence()
    receipts = list(evidence.stability_receipts)
    first = receipts[0]
    trials = list(first.trials)
    trials[1] = trials[1].model_copy(update={"attempt_id": _id("invented-attempt")})
    receipts[0] = first.model_copy(update={"trials": tuple(trials)})
    changed = _rebind_privacy(
        evidence.model_copy(update={"stability_receipts": tuple(receipts)})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "repeat_stability").reason_code == (
        "stability_attempt_or_label_mismatch"
    )


def test_stability_uses_immutable_outcome_not_trial_supplied_labels() -> None:
    assert "candidate_label" not in StabilityTrialV2.model_fields
    assert "run_state" not in StabilityTrialV2.model_fields
    plan, evidence, policy = _build_evidence()
    receipts = list(evidence.stability_receipts)
    trial = receipts[0].trials[0]
    trials = (
        trial.model_copy(update={"outcome_fingerprint": _id("forged-outcome")}),
        receipts[0].trials[1],
    )
    receipts[0] = receipts[0].model_copy(update={"trials": trials})
    changed = _rebind_privacy(
        evidence.model_copy(update={"stability_receipts": tuple(receipts)})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "repeat_stability").outcome is GateCheckOutcome.FAIL


def test_stability_compares_unavailable_run_states_not_only_labels() -> None:
    first = AttemptOutcomeReceipt(
        outcome_id=_id("abstained-outcome"),
        attempt_id=_id("abstained-attempt"),
        execution_id=_id("abstained-execution"),
        case_id=_id("unavailable-case"),
        plan_fingerprint=_id("unavailable-plan"),
        metric_question_fingerprint=_id("unavailable-question"),
        evidence_packet_fingerprint=_id("unavailable-packet"),
        structured_output_fingerprint=_id("abstained-output"),
        run_state=CaseRunState.ABSTAINED,
        latency_class=LatencyClass.WARM,
        latency_ms=5.0,
        outcome_reason_code="low_confidence",
        completed_at=BASE,
    )
    second = first.model_copy(
        update={
            "outcome_id": _id("error-outcome"),
            "attempt_id": _id("error-attempt"),
            "execution_id": _id("error-execution"),
            "structured_output_fingerprint": _id("error-output"),
            "run_state": CaseRunState.ERROR,
            "outcome_reason_code": "runner_error",
        }
    )
    assert (first.run_state, first.candidate_label) != (
        second.run_state,
        second.candidate_label,
    )


def test_holdout_attempt_must_occur_after_v2_preregistration() -> None:
    plan, evidence, policy = _build_evidence()
    assert evidence.execution_identity_audit is not None
    holdout_ids = set(evidence.split.holdout_case_ids)
    attempts = list(evidence.execution_identity_audit.attempts)
    target_index = next(
        index for index, item in enumerate(attempts) if item.case_id in holdout_ids
    )
    target = attempts[target_index]
    attempts[target_index] = target.model_copy(
        update={"attempted_at": evidence.preregistration.registered_at}
    )
    outcomes = list(evidence.execution_identity_audit.outcomes)
    outcome_index = next(
        index for index, item in enumerate(outcomes) if item.attempt_id == target.attempt_id
    )
    outcomes[outcome_index] = outcomes[outcome_index].model_copy(
        update={"completed_at": evidence.preregistration.registered_at}
    )
    audit = evidence.execution_identity_audit.model_copy(
        update={"attempts": tuple(attempts), "outcomes": tuple(outcomes)}
    )
    changed = _rebind_privacy(
        evidence.model_copy(update={"execution_identity_audit": audit})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "holdout_evaluated_after_preregistration").outcome is (
        GateCheckOutcome.FAIL
    )


def test_authoritative_candidate_cannot_select_retrieval_attempt() -> None:
    plan, evidence, _ = _build_evidence()
    assert evidence.execution_identity_audit is not None
    specialist = evidence.execution_identity_audit.attempts[0]
    retrieval = specialist.model_copy(
        update={
            "attempt_id": _id("retrieval-attempt"),
            "execution_id": _id("retrieval-execution"),
            "stage_ordinal": 3,
            "stage_kind": EstimatorStageKind.EMBEDDING_RETRIEVAL,
            "constellation_stage_fingerprint": next(
                item.fingerprint
                for item in evidence.constellation_identity.stages
                if item.kind is EstimatorStageKind.EMBEDDING_RETRIEVAL
            ),
            "model_artifact_fingerprint": plan.stages[2].model_artifact.canonical_fingerprint,
            "stage_configuration_sha256": plan.stages[2].configuration_sha256,
            "requested_model_id": plan.stages[2].model_artifact.requested_model_id,
            "served_model_id": plan.stages[2].model_artifact.served_model_id,
            "requested_revision": plan.stages[2].model_artifact.requested_revision,
            "served_revision": plan.stages[2].model_artifact.served_revision,
        }
    )
    outcome = evidence.execution_identity_audit.outcomes[0].model_copy(
        update={
            "outcome_id": _id("retrieval-outcome"),
            "attempt_id": retrieval.attempt_id,
            "execution_id": retrieval.execution_id,
            "structured_output_fingerprint": _id("retrieval-output"),
        }
    )
    projection = evidence.execution_identity_audit.candidate_projections[0].model_copy(
        update={
            "authoritative_attempt_id": retrieval.attempt_id,
            "authoritative_outcome_id": outcome.outcome_id,
            "authoritative_outcome_fingerprint": outcome.fingerprint,
        }
    )
    with pytest.raises(ValidationError, match="candidate projection"):
        ExecutionIdentityAudit.model_validate(
            {
                **evidence.execution_identity_audit.model_dump(),
                "attempts": tuple(
                    sorted(
                        evidence.execution_identity_audit.attempts + (retrieval,),
                        key=lambda item: item.attempt_id,
                    )
                ),
                "outcomes": tuple(
                    sorted(
                        evidence.execution_identity_audit.outcomes + (outcome,),
                        key=lambda item: item.attempt_id,
                    )
                ),
                "candidate_projections": tuple(
                    projection if item.case_id == projection.case_id else item
                    for item in evidence.execution_identity_audit.candidate_projections
                ),
            }
        )


def test_candidate_confidence_and_latency_are_bound_to_attempt_outcome() -> None:
    plan, evidence, policy = _build_evidence()
    cases = list(evidence.cohort.cases)
    cases[0] = cases[0].model_copy(
        update={"candidate_confidence": 0.25, "latency_ms": 0.0}
    )
    cohort = evidence.cohort.model_copy(update={"cases": tuple(cases)})
    changed = _rebind_privacy(evidence.model_copy(update={"cohort": cohort}))

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "candidate_projection_integrity").outcome is (
        GateCheckOutcome.FAIL
    )


def test_resolved_blind_calibration_requires_two_distinct_humans() -> None:
    plan, evidence, _ = _build_evidence()
    adjudication = evidence.blind_adjudications[0]
    repeated_reviewer = adjudication.judgments[1].model_copy(
        update={"adjudicator_id": adjudication.judgments[0].adjudicator_id}
    )
    with pytest.raises(ValidationError, match="two distinct humans"):
        BlindCalibrationAdjudication.model_validate(
            {
                **adjudication.model_dump(),
                "judgments": (
                    adjudication.judgments[0],
                    repeated_reviewer,
                ),
            }
        )
    with pytest.raises(ValidationError):
        BlindCalibrationAdjudication.model_validate(
            {**adjudication.model_dump(), "source": "model_consensus"}
        )
    assert all(not item.private_export_allowed for item in adjudication.judgments)
    assert not adjudication.private_export_allowed
    assert not adjudication.team_share_allowed
    assert plan.canonical_fingerprint == adjudication.plan_fingerprint


def test_blind_label_substitution_fails_closed() -> None:
    plan, evidence, policy = _build_evidence()
    blind = list(evidence.blind_adjudications)
    original = blind[0]
    replacement = "negative" if original.resolved_label_code == "positive" else "positive"
    blind[0] = original.model_copy(update={"resolved_label_code": replacement})
    changed = _rebind_privacy(
        evidence.model_copy(update={"blind_adjudications": tuple(blind)})
    )

    decision = _evaluate(plan, changed, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert _gate(decision, "blind_label_integrity").outcome is GateCheckOutcome.FAIL


def test_synthetic_model_rejection_is_derived_from_stored_plan() -> None:
    plan, evidence, policy = _build_evidence(plan=_plan(synthetic=True))

    decision = _evaluate(plan, evidence, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    check = _gate(decision, "stored_plan_non_synthetic")
    assert check.outcome is GateCheckOutcome.FAIL
    assert check.actual == 4
    assert check.reason_code == "synthetic_model_in_stored_plan"


def test_missing_v2_identity_evidence_is_explicitly_insufficient() -> None:
    plan, evidence, policy = _build_evidence(
        include_constellation=False,
        include_attempt_audit=False,
    )

    decision = _evaluate(plan, evidence, policy)

    assert decision.outcome is ActivationOutcome.INSUFFICIENT_DATA
    assert _gate(decision, "constellation_identity").outcome is (
        GateCheckOutcome.INSUFFICIENT_DATA
    )
    assert _gate(decision, "execution_identity_audit").outcome is (
        GateCheckOutcome.INSUFFICIENT_DATA
    )
    assert _gate(decision, "exact_attempt_identity").outcome is (
        GateCheckOutcome.INSUFFICIENT_DATA
    )


@pytest.mark.parametrize(
    "bad_version",
    (
        "https://reserved.example/model",
        "http:/reserved.example/model",
        "file:/reserved/private/model",
        "urn:reserved:model",
        "mailto:reserved",
        "C:/reserved/private/model",
        "C:reserved/private/model",
        "../reserved-model",
        "reserved\\private\\model",
        "/reserved/private/model",
    ),
)
def test_v2_versions_reject_path_and_uri_shapes(bad_version: str) -> None:
    _, evidence, _ = _build_evidence()
    assert evidence.constellation_identity is not None
    stage = evidence.constellation_identity.stages[0]
    with pytest.raises(ValidationError, match="paths or URIs"):
        type(stage).model_validate({**stage.model_dump(), "component_version": bad_version})
    assert evidence.execution_identity_audit is not None
    attempt = evidence.execution_identity_audit.attempts[0]
    with pytest.raises(ValidationError, match="paths or URIs"):
        AttemptIdentityReceipt.model_validate(
            {**attempt.model_dump(), "requested_model_id": bad_version}
        )
    judgment = evidence.blind_adjudications[0].judgments[0]
    with pytest.raises(ValidationError, match="paths or URIs"):
        BlindCalibrationJudgment.model_validate(
            {**judgment.model_dump(), "annotation_protocol_version": bad_version}
        )


def test_gate_input_has_no_caller_eligibility_or_outcome_fields() -> None:
    plan, evidence, policy = _build_evidence()
    forbidden = {
        "eligible",
        "eligibility",
        "outcome",
        "activation_allowed",
        "holdout_untouched",
        "synthetic_only",
        "prompt",
        "transcript",
        "excerpt",
        "model_output",
        "rationale",
    }
    assert forbidden.isdisjoint(GateEvidenceV2.model_fields)
    assert forbidden.isdisjoint(CaseAssignmentV2.model_fields)
    assert not evidence.sensitive_label_export_allowed
    assert not evidence.team_share_allowed

    decision = _evaluate(plan, evidence, policy)
    with pytest.raises(ValidationError, match="derived from its checks"):
        ActivationGateDecisionV2.model_validate(
            {**decision.model_dump(), "outcome": ActivationOutcome.REJECTED}
        )


def test_unsealed_decision_contract_rejects_direct_eligible_forgery() -> None:
    plan, evidence, policy = _build_evidence()
    legitimate = _evaluate(plan, evidence, policy)
    pass_check = next(
        item for item in legitimate.checks if item.outcome is GateCheckOutcome.PASS
    )
    with pytest.raises(ValidationError, match="cannot authorize activation"):
        ActivationGateDecisionV2(
            decision_id=_id("forged-decision"),
            stored_plan_fingerprint=plan.canonical_fingerprint,
            evidence_fingerprint=evidence.fingerprint,
            policy_fingerprint=policy.fingerprint,
            preregistration_fingerprint=evidence.preregistration.fingerprint,
            preregistration_v2_fingerprint=evidence.preregistration_v2.fingerprint,
            outcome=ActivationOutcome.ELIGIBLE,
            checks=(pass_check,),
            derived_at=BASE + timedelta(days=20),
        )


@pytest.mark.parametrize(
    ("plan_field", "bad_version"),
    (
        ("plan_key", "urn:reserved:plan"),
        ("router_version", "file:/reserved/private/router"),
        ("preprocessing_version", "urn:reserved:preprocessing"),
        ("evidence_packet_schema_version", "C:reserved/private/packet"),
    ),
)
def test_evaluator_rejects_unsafe_stored_plan_identifiers(
    plan_field: str, bad_version: str
) -> None:
    plan, _, policy = _build_evidence()
    unsafe_plan = plan.model_copy(update={plan_field: bad_version})
    _, evidence, _ = _build_evidence(plan=unsafe_plan)

    decision = _evaluate(unsafe_plan, evidence, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert tuple(item.check_key for item in decision.checks) == ("manifest_integrity",)


def test_evaluator_rejects_unsafe_question_identity_codes() -> None:
    plan, _, policy = _build_evidence()
    question = plan.question_specs[0].model_copy(
        update={
            "question_id": "urn:reserved:question",
            "prompt_template_id": "file:/reserved/template",
            "rubric_id": "C:reserved/rubric",
        }
    )
    unsafe_plan = plan.model_copy(update={"question_specs": (question,)})
    _, evidence, _ = _build_evidence(plan=unsafe_plan)

    decision = _evaluate(unsafe_plan, evidence, policy)

    assert decision.outcome is ActivationOutcome.REJECTED
    assert tuple(item.check_key for item in decision.checks) == ("manifest_integrity",)


def test_evaluator_audits_provider_and_candidate_artifact_identifiers() -> None:
    plan, _, policy = _build_evidence()
    provider = plan.provider_schemas[0].model_copy(
        update={"adapter_version": "http:/reserved.example/adapter"}
    )
    unsafe_provider_plan = plan.model_copy(update={"provider_schemas": (provider,)})
    _, evidence, _ = _build_evidence(plan=unsafe_provider_plan)
    decision = _evaluate(unsafe_provider_plan, evidence, policy)
    assert decision.outcome is ActivationOutcome.REJECTED

    stage = plan.stages[2]
    assert stage.model_artifact is not None
    artifact = stage.model_artifact.model_copy(
        update={"requested_model_id": "mailto:reserved-model"}
    )
    stages = tuple(
        item.model_copy(update={"model_artifact": artifact})
        if item.ordinal == stage.ordinal
        else item
        for item in plan.stages
    )
    unsafe_artifact_plan = plan.model_copy(update={"stages": stages})
    _, evidence, _ = _build_evidence(plan=unsafe_artifact_plan)
    decision = _evaluate(unsafe_artifact_plan, evidence, policy)
    assert decision.outcome is ActivationOutcome.REJECTED
