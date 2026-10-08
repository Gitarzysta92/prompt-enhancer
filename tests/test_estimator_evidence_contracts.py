from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators.contracts import (
    EstimatorStageKind,
    ExecutionDestination,
    MetricValueKind,
    ModelExecutionMode,
    ModelSource,
    RetentionClass,
)
from prompt_enhancer.application.estimators.evidence_contracts import (
    AttemptApprovalKind,
    AttemptLaunchReceiptV1,
    AttemptTerminalOutcomeV1,
    AttemptTerminalState,
    AuthoritativeCandidateProjectionV2,
    AuthoritativeDeterministicBaselineProjectionV1,
    BlindAdjudicationResolution,
    BlindHumanAdjudicationInputV1,
    BlindHumanJudgmentInputV1,
    CalibrationEvidenceSubmissionV1,
    CalibrationValueState,
    CostProvenanceV1,
    ExpectedAttemptManifestV2,
    HoldoutAccessAuditV1,
    HoldoutAccessEventV1,
    HoldoutAccessGapV1,
    HoldoutAccessKind,
    HoldoutAccessManifestV1,
    HoldoutActorKind,
    HumanParticipantKind,
    MeasurementState,
    ObjectiveTruthKind,
    ObjectiveTruthProjectionV1,
    PrivacyFindingCategory,
    PrivacyFindingV1,
    PrivacyScanManifestV1,
    PrivacyScanReceiptV1,
    QueueProvenanceV1,
    ResourceUsageProvenanceV1,
    ServedIdentityState,
    ServedIdentityV1,
    StabilitySeriesManifestV1,
    StabilityTrialReceiptV1,
    StructuredEstimateReceiptV1,
    TokenUsageProvenanceV1,
    revalidate_calibration_evidence_submission_v1,
)
from prompt_enhancer.application.estimators.gate_contracts import StabilityCondition


BASE = datetime(2045, 1, 1, tzinfo=UTC)


def _id(value: str) -> str:
    return hashlib.sha256(f"reserved-v17-synthetic:{value}".encode("ascii")).hexdigest()


def _launch(*, attempt: str = "attempt-1", stage: EstimatorStageKind = EstimatorStageKind.SPECIALIST) -> AttemptLaunchReceiptV1:
    return AttemptLaunchReceiptV1(
        launch_id=_id(f"launch:{attempt}"),
        campaign_id=_id("campaign"),
        attempt_id=_id(attempt),
        execution_id=_id(f"execution:{attempt}"),
        case_id=_id("case"),
        plan_fingerprint=_id("plan"),
        metric_question_fingerprint=_id("question"),
        evidence_packet_fingerprint=_id("packet"),
        constellation_stage_fingerprint=_id(f"stage:{stage.value}"),
        stage_ordinal=5 if stage is EstimatorStageKind.SPECIALIST else 6,
        stage_kind=stage,
        stage_configuration_sha256=_id(f"config:{stage.value}"),
        model_artifact_fingerprint=_id(f"artifact:{stage.value}"),
        requested_source=ModelSource.LOCAL_WEIGHTS,
        requested_model_id="reserved-local-model-v1",
        requested_revision="reserved-revision-v1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        runner_adapter_key="reserved_runner",
        runner_adapter_version="reserved-runner-v1",
        runner_configuration_sha256=_id("runner-config"),
        response_schema_version="reserved-schema-v1",
        destination=ExecutionDestination.LOCAL_DEVICE,
        retention_class=RetentionClass.LOCAL_EPHEMERAL,
        approval_kind=AttemptApprovalKind.NOT_REQUIRED_LOCAL,
        launched_at=BASE + timedelta(minutes=1),
    )


def _queue() -> QueueProvenanceV1:
    return QueueProvenanceV1(
        queue_key="calibration",
        queue_version="reserved-queue-v1",
        worker_id=_id("worker"),
        enqueued_at=BASE,
        dequeued_at=BASE + timedelta(seconds=30),
        wait_ms=30_000,
    )


def _outcome(launch: AttemptLaunchReceiptV1, *, state: AttemptTerminalState = AttemptTerminalState.SUCCESS) -> AttemptTerminalOutcomeV1:
    success = state is AttemptTerminalState.SUCCESS
    return AttemptTerminalOutcomeV1(
        outcome_id=_id(f"outcome:{launch.attempt_id}"),
        campaign_id=launch.campaign_id,
        attempt_id=launch.attempt_id,
        execution_id=launch.execution_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        state=state,
        served_identity=ServedIdentityV1(
            state=ServedIdentityState.OBSERVED,
            served_source=launch.requested_source,
            served_model_id=launch.requested_model_id,
            served_revision=launch.requested_revision,
            served_execution_mode=launch.requested_execution_mode,
            fallback_used=False,
        ),
        structured_output_fingerprint=_id("structured-output") if success else None,
        reason_code=None if success else "reserved_failure",
        usage=TokenUsageProvenanceV1(
            state=MeasurementState.OBSERVED,
            collector_version="reserved-collector-v1",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
        ),
        resources=ResourceUsageProvenanceV1(
            state=MeasurementState.OBSERVED,
            collector_version="reserved-collector-v1",
            peak_ram_bytes=1024,
        ),
        cost=CostProvenanceV1(
            state=MeasurementState.NOT_APPLICABLE,
            collector_version="reserved-collector-v1",
            reason_code="local_execution",
        ),
        queue=_queue(),
        started_at=launch.launched_at,
        finished_at=launch.launched_at + timedelta(seconds=2),
        latency_ms=2_000,
    )


def _access_audit(campaign_id: str, case_id: str) -> HoldoutAccessAuditV1:
    manifest = HoldoutAccessManifestV1(
        manifest_id=_id("access-manifest"),
        campaign_id=campaign_id,
        auditor_version="reserved-auditor-v1",
        coverage_started_at=BASE,
        coverage_ended_at=BASE + timedelta(minutes=5),
        events=(
            HoldoutAccessEventV1(
                event_id=_id("access-event"),
                campaign_id=campaign_id,
                case_id=case_id,
                actor_id=_id("runner"),
                actor_kind=HoldoutActorKind.CANDIDATE_RUNNER,
                access_kind=HoldoutAccessKind.CASE_INPUT_READ,
                occurred_at=BASE + timedelta(minutes=1),
            ),
        ),
        frozen_at=BASE + timedelta(minutes=6),
    )
    return HoldoutAccessAuditV1(
        audit_id=_id("access-audit"),
        campaign_id=campaign_id,
        manifest=manifest,
        holdout_case_ids=(case_id,),
        holdout_unsealed_at=BASE + timedelta(minutes=4),
        completed_at=BASE + timedelta(minutes=7),
    )


def _privacy_scan(campaign_id: str, artifact_ids: tuple[str, ...]) -> PrivacyScanReceiptV1:
    manifest = PrivacyScanManifestV1(
        manifest_id=_id("privacy-manifest"),
        campaign_id=campaign_id,
        expected_artifact_fingerprints=tuple(sorted(artifact_ids)),
        scanned_artifact_fingerprints=tuple(sorted(artifact_ids)),
        frozen_at=BASE + timedelta(minutes=9),
    )
    return PrivacyScanReceiptV1(
        scan_id=_id("privacy-scan"),
        campaign_id=campaign_id,
        scanner_version="reserved-scanner-v1",
        manifest=manifest,
        started_at=BASE + timedelta(minutes=8),
        completed_at=BASE + timedelta(minutes=10),
    )


def _submission() -> CalibrationEvidenceSubmissionV1:
    launch = _launch()
    outcome = _outcome(launch)
    manifest = ExpectedAttemptManifestV2.from_launches(
        manifest_id=_id("expected-manifest"),
        campaign_id=launch.campaign_id,
        launches=(launch,),
        frozen_at=BASE,
    )
    estimate = StructuredEstimateReceiptV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        confidence=0.8,
        receipt_id=_id("structured-estimate"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        attempt_id=launch.attempt_id,
        outcome_id=outcome.outcome_id,
        outcome_fingerprint=outcome.fingerprint,
        structured_output_fingerprint=outcome.structured_output_fingerprint,
        recorded_at=BASE + timedelta(minutes=2),
    )
    candidate = AuthoritativeCandidateProjectionV2(
        projection_id=_id("candidate"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        attempt_id=launch.attempt_id,
        outcome_id=outcome.outcome_id,
        outcome_fingerprint=outcome.fingerprint,
        estimate_receipt_id=estimate.receipt_id,
        estimate_receipt_fingerprint=estimate.fingerprint,
        stage_ordinal=launch.stage_ordinal,
        stage_kind=launch.stage_kind,
        selected_at=BASE + timedelta(minutes=3),
    )
    return CalibrationEvidenceSubmissionV1(
        submission_id=_id("submission"),
        campaign_id=launch.campaign_id,
        campaign_holdout_case_ids=(launch.case_id,),
        expected_attempt_manifest=manifest,
        attempt_launches=(launch,),
        attempt_outcomes=(outcome,),
        structured_estimate_receipts=(estimate,),
        holdout_access_audit=_access_audit(launch.campaign_id, launch.case_id),
        privacy_scan=_privacy_scan(
            launch.campaign_id,
            (outcome.structured_output_fingerprint,),
        ),
        candidate_projections=(candidate,),
        submitted_at=BASE + timedelta(minutes=11),
    )


def test_launch_outcome_and_submission_are_content_free_and_non_activating() -> None:
    submission = _submission()
    assert submission.activation_allowed is False
    assert submission.private_export_allowed is False
    assert submission.team_share_allowed is False
    assert submission.privacy_scan.passed is True
    assert submission.privacy_scan.persistence_state == "untrusted_until_sealed"
    assert submission.holdout_access_audit.passed is True
    serialized = submission.model_dump_json()
    for forbidden in ("prompt", "rationale", "chain_of_thought", "C:\\", "https://"):
        assert forbidden not in serialized


def test_expected_attempt_fingerprint_is_derived_and_order_independent_at_factory() -> None:
    first = _launch(attempt="attempt-a")
    second = _launch(attempt="attempt-b", stage=EstimatorStageKind.SECOND_OPINION)
    one = ExpectedAttemptManifestV2.from_launches(
        manifest_id=_id("manifest"),
        campaign_id=first.campaign_id,
        launches=(first, second),
        frozen_at=BASE,
    )
    two = ExpectedAttemptManifestV2.from_launches(
        manifest_id=_id("manifest"),
        campaign_id=first.campaign_id,
        launches=(second, first),
        frozen_at=BASE,
    )
    assert one.execution_set_fingerprint == two.execution_set_fingerprint
    assert one.fingerprint == two.fingerprint
    with pytest.raises(ValidationError):
        ExpectedAttemptManifestV2.model_validate(
            {**one.model_dump(mode="python"), "execution_set_fingerprint": _id("caller")}
        )


@pytest.mark.parametrize(
    "state",
    tuple(state for state in AttemptTerminalState if state is not AttemptTerminalState.SUCCESS),
)
def test_every_non_success_terminal_state_requires_only_a_reason(
    state: AttemptTerminalState,
) -> None:
    receipt = _outcome(_launch(), state=state)
    assert receipt.reason_code == "reserved_failure"
    with pytest.raises(ValidationError):
        AttemptTerminalOutcomeV1.model_validate(
            {
                **receipt.model_dump(mode="python"),
                "structured_output_fingerprint": _id("forbidden-output"),
            }
        )


def test_served_identity_is_explicitly_observed_or_unavailable() -> None:
    unavailable = ServedIdentityV1(
        state=ServedIdentityState.UNAVAILABLE,
        unavailable_reason_code="provider_did_not_expose",
    )
    assert unavailable.served_model_id is None
    with pytest.raises(ValidationError):
        ServedIdentityV1(
            state=ServedIdentityState.UNAVAILABLE,
            served_model_id="reserved-model-v1",
            unavailable_reason_code="provider_did_not_expose",
        )
    with pytest.raises(ValidationError):
        ServedIdentityV1(state=ServedIdentityState.OBSERVED)


def test_success_requires_an_observed_served_identity() -> None:
    launch = _launch()
    outcome = _outcome(launch)
    with pytest.raises(ValidationError, match="observed served identity"):
        AttemptTerminalOutcomeV1.model_validate(
            {
                **outcome.model_dump(mode="python"),
                "served_identity": ServedIdentityV1(
                    state=ServedIdentityState.UNAVAILABLE,
                    unavailable_reason_code="provider_did_not_expose",
                ).model_dump(mode="python"),
            }
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"cached_input_tokens": 11},
        {"reasoning_output_tokens": 3},
        {"total_tokens": 13},
        {"input_tokens": None},
        {"output_tokens": None},
    ),
)
def test_token_usage_has_explicit_billed_and_subset_semantics(
    changes: dict[str, object]
) -> None:
    valid = TokenUsageProvenanceV1(
        state=MeasurementState.OBSERVED,
        collector_version="reserved-collector-v1",
        input_tokens=10,
        cached_input_tokens=4,
        output_tokens=2,
        reasoning_output_tokens=1,
        total_tokens=12,
    )
    with pytest.raises(ValidationError):
        TokenUsageProvenanceV1.model_validate(
            {**valid.model_dump(mode="python"), **changes}
        )
    unknown = TokenUsageProvenanceV1(
        state=MeasurementState.UNAVAILABLE,
        collector_version="reserved-collector-v1",
        reason_code="provider_did_not_expose",
    )
    assert unknown.total_tokens is None


def test_launch_enforces_destination_retention_approval_and_safe_versions() -> None:
    local = _launch()
    with pytest.raises(ValidationError):
        AttemptLaunchReceiptV1.model_validate(
            {
                **local.model_dump(mode="python"),
                "requested_model_id": "file:reserved-secret",
            }
        )
    with pytest.raises(ValidationError):
        AttemptLaunchReceiptV1.model_validate(
            {
                **local.model_dump(mode="python"),
                "destination": ExecutionDestination.OPENAI_API,
            }
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.0, -1.0])
def test_numeric_measurements_reject_nonfinite_negative_and_negative_zero(bad: float) -> None:
    with pytest.raises(ValidationError):
        ResourceUsageProvenanceV1(
            state=MeasurementState.OBSERVED,
            collector_version="reserved-v1",
            energy_millijoules=bad,
        )


def test_timestamps_require_canonical_utc_and_outcome_must_follow_launch() -> None:
    launch = _launch()
    with pytest.raises(ValidationError):
        AttemptLaunchReceiptV1.model_validate(
            {**launch.model_dump(mode="python"), "launched_at": BASE.replace(tzinfo=None)}
        )
    submission = _submission()
    outcome = submission.attempt_outcomes[0].model_copy(
        update={"started_at": BASE - timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {**submission.model_dump(mode="python"), "attempt_outcomes": (outcome,)}
        )


def test_access_manifest_derives_counts_fingerprints_and_flags_pre_unseal_truth() -> None:
    clean = _access_audit(_id("campaign"), _id("case"))
    assert clean.manifest.event_count == 1
    assert clean.manifest.gap_count == 0
    assert clean.passed is True
    bad_event = clean.manifest.events[0].model_copy(
        update={"access_kind": HoldoutAccessKind.REFERENCE_TRUTH_READ}
    )
    bad_manifest = HoldoutAccessManifestV1.model_validate(
        {**clean.manifest.model_dump(mode="python"), "events": (bad_event,)}
    )
    bad = HoldoutAccessAuditV1.model_validate(
        {**clean.model_dump(mode="python"), "manifest": bad_manifest}
    )
    assert bad.prohibited_pre_unseal_count == 1
    assert bad.passed is False


def test_access_gap_makes_audit_fail_without_caller_boolean() -> None:
    audit = _access_audit(_id("campaign"), _id("case"))
    gap = HoldoutAccessGapV1(
        gap_id=_id("gap"),
        campaign_id=audit.campaign_id,
        reason_code="collector_restart",
        started_at=BASE + timedelta(minutes=2),
        ended_at=BASE + timedelta(minutes=3),
    )
    manifest = HoldoutAccessManifestV1.model_validate(
        {**audit.manifest.model_dump(mode="python"), "gaps": (gap,)}
    )
    failed = HoldoutAccessAuditV1.model_validate(
        {**audit.model_dump(mode="python"), "manifest": manifest}
    )
    assert failed.passed is False


def test_access_authorization_matrix_derives_violations_from_events() -> None:
    clean = _access_audit(_id("campaign"), _id("case"))
    unauthorized = clean.manifest.events[0].model_copy(
        update={"access_kind": HoldoutAccessKind.CANDIDATE_OUTPUT_READ}
    )
    manifest = HoldoutAccessManifestV1.model_validate(
        {**clean.manifest.model_dump(mode="python"), "events": (unauthorized,)}
    )
    audit = HoldoutAccessAuditV1.model_validate(
        {**clean.model_dump(mode="python"), "manifest": manifest}
    )
    assert audit.unauthorized_access_count == 1
    assert audit.passed is False
    assert audit.persistence_state == "untrusted_until_sealed"


def test_privacy_manifest_derives_categories_counts_and_coverage() -> None:
    campaign = _id("campaign")
    artifact = _id("artifact")
    finding = PrivacyFindingV1(
        finding_id=_id("finding"),
        campaign_id=campaign,
        artifact_fingerprint=artifact,
        detector_key="content_canary",
        detector_version="reserved-detector-v1",
        category=PrivacyFindingCategory.REASONING_TRACE,
        occurrence_count=2,
        detected_at=BASE + timedelta(minutes=1),
    )
    manifest = PrivacyScanManifestV1(
        manifest_id=_id("privacy-manifest"),
        campaign_id=campaign,
        expected_artifact_fingerprints=(artifact, _id("unscanned")),
        scanned_artifact_fingerprints=(artifact,),
        findings=(finding,),
        frozen_at=BASE + timedelta(minutes=2),
    )
    assert manifest.unscanned_artifact_count == 1
    assert manifest.finding_count == 2
    assert manifest.category_counts == ((PrivacyFindingCategory.REASONING_TRACE.value, 2),)


def test_projection_stage_and_outcome_lineage_are_authoritative() -> None:
    submission = _submission()
    projection = submission.candidate_projections[0]
    with pytest.raises(ValidationError):
        AuthoritativeCandidateProjectionV2.model_validate(
            {**projection.model_dump(mode="python"), "stage_kind": EstimatorStageKind.RERANKER}
        )
    bad = projection.model_copy(update={"outcome_fingerprint": _id("wrong")})
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {**submission.model_dump(mode="python"), "candidate_projections": (bad,)}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("label_code", "forged"),
        ("state", CalibrationValueState.ABSTAINED),
        ("confidence", 1.0),
    ),
)
def test_candidate_cannot_restate_or_forge_structured_estimate_values(
    field: str, value: object
) -> None:
    projection = _submission().candidate_projections[0]
    with pytest.raises(ValidationError):
        AuthoritativeCandidateProjectionV2.model_validate(
            {**projection.model_dump(mode="python"), field: value}
        )


def test_candidate_must_reference_exact_successful_structured_estimate_receipt() -> None:
    submission = _submission()
    estimate = submission.structured_estimate_receipts[0]
    forged = estimate.model_copy(update={"label_code": "forged"})
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "structured_estimate_receipts": (forged,),
            }
        )


def test_deterministic_and_objective_projections_are_not_model_attempts() -> None:
    launch = _launch()
    baseline = AuthoritativeDeterministicBaselineProjectionV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        projection_id=_id("baseline"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        baseline_id="reserved-baseline-v1",
        baseline_version="reserved-v1",
        baseline_configuration_sha256=_id("baseline-config"),
        final_estimate_fingerprint=_id("baseline-estimate"),
        evaluated_at=BASE + timedelta(minutes=3),
    )
    truth = ObjectiveTruthProjectionV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        projection_id=_id("truth"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        truth_kind=ObjectiveTruthKind.TEST_RESULT,
        objective_evidence_fingerprint=_id("objective-artifact"),
        verification_adapter_version="reserved-verifier-v1",
        observed_at=BASE + timedelta(minutes=3),
    )
    assert "attempt_id" not in type(baseline).model_fields
    assert "attempt_id" not in type(truth).model_fields
    assert truth.persistence_state == "untrusted_until_sealed"


def test_every_evidence_family_requires_exact_expected_lineage_membership() -> None:
    submission = _submission()
    launch = submission.attempt_launches[0]
    wrong_packet = _id("wrong-packet")

    baseline = AuthoritativeDeterministicBaselineProjectionV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        projection_id=_id("wrong-lineage-baseline"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=wrong_packet,
        baseline_id="reserved-baseline-v1",
        baseline_version="reserved-v1",
        baseline_configuration_sha256=_id("baseline-config"),
        final_estimate_fingerprint=_id("baseline-estimate"),
        evaluated_at=BASE + timedelta(minutes=3),
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "deterministic_baseline_projections": (baseline,),
            }
        )

    truth = ObjectiveTruthProjectionV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        projection_id=_id("wrong-lineage-truth"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=wrong_packet,
        truth_kind=ObjectiveTruthKind.TEST_RESULT,
        objective_evidence_fingerprint=_id("objective-artifact"),
        verification_adapter_version="reserved-verifier-v1",
        observed_at=BASE + timedelta(minutes=3),
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "objective_truth_projections": (truth,),
            }
        )

    def judgment(actor: str, minute: int) -> BlindHumanJudgmentInputV1:
        return BlindHumanJudgmentInputV1(
            value_kind=MetricValueKind.CATEGORICAL,
            state=CalibrationValueState.KNOWN,
            label_code="supported",
            judgment_id=_id(f"lineage-judgment:{actor}"),
            campaign_id=launch.campaign_id,
            case_id=launch.case_id,
            plan_fingerprint=launch.plan_fingerprint,
            metric_question_fingerprint=launch.metric_question_fingerprint,
            evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
            participant_id=_id(actor),
            participant_kind=HumanParticipantKind.INDEPENDENT_ANNOTATOR,
            annotation_protocol_version="reserved-protocol-v1",
            created_at=BASE + timedelta(minutes=minute),
        )

    first, second = judgment("lineage-human-a", 2), judgment("lineage-human-b", 3)
    wrong_judgment = first.model_copy(update={"evidence_packet_fingerprint": wrong_packet})
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "blind_human_judgments": (wrong_judgment,),
            }
        )

    adjudication = BlindHumanAdjudicationInputV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        adjudication_id=_id("wrong-lineage-adjudication"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=_id("wrong-plan"),
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        adjudicator_id=_id("lineage-human-c"),
        adjudicator_kind=HumanParticipantKind.ADJUDICATOR,
        resolution=BlindAdjudicationResolution.RESOLVED,
        judgment_ids=tuple(sorted((first.judgment_id, second.judgment_id))),
        annotation_protocol_version="reserved-protocol-v1",
        completed_at=BASE + timedelta(minutes=4),
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "blind_human_judgments": (first, second),
                "blind_human_adjudications": (adjudication,),
            }
        )

    wrong_plan = _id("wrong-stability-plan")
    trials = tuple(
        StabilityTrialReceiptV1(
            receipt_id=_id(f"wrong-lineage-trial:{index}"),
            campaign_id=launch.campaign_id,
            case_id=launch.case_id,
            plan_fingerprint=wrong_plan,
            metric_question_fingerprint=launch.metric_question_fingerprint,
            evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
            condition=StabilityCondition.REPEAT,
            trial_ordinal=index,
            attempt_id=_id(f"wrong-lineage-attempt:{index}"),
            outcome_id=_id(f"wrong-lineage-outcome:{index}"),
            outcome_fingerprint=_id(f"wrong-lineage-outcome-fingerprint:{index}"),
            estimate_receipt_id=_id(f"wrong-lineage-estimate:{index}"),
            estimate_receipt_fingerprint=_id(
                f"wrong-lineage-estimate-fingerprint:{index}"
            ),
            recorded_at=BASE + timedelta(minutes=index + 1),
        )
        for index in (1, 2)
    )
    series = StabilitySeriesManifestV1(
        series_id=_id("wrong-lineage-series"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=wrong_plan,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        condition=StabilityCondition.REPEAT,
        trials=trials,
        frozen_at=BASE + timedelta(minutes=3, seconds=30),
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {**submission.model_dump(mode="python"), "stability_series": (series,)}
        )


def test_blind_human_inputs_require_kinds_independence_and_supported_resolution() -> None:
    launch = _launch()
    def judgment(label: str, actor: str, ordinal: int) -> BlindHumanJudgmentInputV1:
        return BlindHumanJudgmentInputV1(
            value_kind=MetricValueKind.CATEGORICAL,
            state=CalibrationValueState.KNOWN,
            label_code=label,
            judgment_id=_id(f"judgment:{actor}"),
            campaign_id=launch.campaign_id,
            case_id=launch.case_id,
            plan_fingerprint=launch.plan_fingerprint,
            metric_question_fingerprint=launch.metric_question_fingerprint,
            evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
            participant_id=_id(actor),
            participant_kind=HumanParticipantKind.INDEPENDENT_ANNOTATOR,
            annotation_protocol_version="reserved-protocol-v1",
            created_at=BASE + timedelta(minutes=ordinal),
        )
    first, second = judgment("supported", "human-a", 2), judgment("unsupported", "human-b", 3)
    adjudication = BlindHumanAdjudicationInputV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        adjudication_id=_id("adjudication"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        adjudicator_id=_id("human-c"),
        adjudicator_kind=HumanParticipantKind.ADJUDICATOR,
        resolution=BlindAdjudicationResolution.RESOLVED,
        judgment_ids=tuple(sorted((first.judgment_id, second.judgment_id))),
        annotation_protocol_version="reserved-protocol-v1",
        completed_at=BASE + timedelta(minutes=4),
    )
    assert adjudication.blinded_to_candidate is True
    with pytest.raises(ValidationError):
        BlindHumanJudgmentInputV1.model_validate(
            {**first.model_dump(mode="python"), "participant_kind": HumanParticipantKind.ADJUDICATOR}
        )


def test_stability_series_links_distinct_terminal_outcomes() -> None:
    first_launch = _launch(attempt="stability-a")
    second_launch = _launch(attempt="stability-b")
    first_outcome, second_outcome = _outcome(first_launch), _outcome(second_launch)
    estimates = tuple(
        StructuredEstimateReceiptV1(
            value_kind=MetricValueKind.CATEGORICAL,
            state=CalibrationValueState.KNOWN,
            label_code="supported",
            confidence=0.8,
            receipt_id=_id(f"stability-estimate:{index}"),
            campaign_id=launch.campaign_id,
            case_id=launch.case_id,
            plan_fingerprint=launch.plan_fingerprint,
            metric_question_fingerprint=launch.metric_question_fingerprint,
            evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
            attempt_id=launch.attempt_id,
            outcome_id=outcome.outcome_id,
            outcome_fingerprint=outcome.fingerprint,
            structured_output_fingerprint=outcome.structured_output_fingerprint,
            recorded_at=BASE + timedelta(minutes=2 + index),
        )
        for index, (launch, outcome) in enumerate(
            ((first_launch, first_outcome), (second_launch, second_outcome)), start=1
        )
    )
    trials = tuple(
        StabilityTrialReceiptV1(
            receipt_id=_id(f"trial:{index}"),
            campaign_id=launch.campaign_id,
            case_id=launch.case_id,
            plan_fingerprint=launch.plan_fingerprint,
            metric_question_fingerprint=launch.metric_question_fingerprint,
            evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
            condition=StabilityCondition.REPEAT,
            trial_ordinal=index,
            attempt_id=launch.attempt_id,
            outcome_id=outcome.outcome_id,
            outcome_fingerprint=outcome.fingerprint,
            estimate_receipt_id=estimate.receipt_id,
            estimate_receipt_fingerprint=estimate.fingerprint,
            recorded_at=BASE + timedelta(minutes=4 + index),
        )
        for index, (launch, outcome, estimate) in enumerate(
            (
                (first_launch, first_outcome, estimates[0]),
                (second_launch, second_outcome, estimates[1]),
            ),
            start=1,
        )
    )
    series = StabilitySeriesManifestV1(
        series_id=_id("series"),
        campaign_id=first_launch.campaign_id,
        case_id=first_launch.case_id,
        plan_fingerprint=first_launch.plan_fingerprint,
        metric_question_fingerprint=first_launch.metric_question_fingerprint,
        evidence_packet_fingerprint=first_launch.evidence_packet_fingerprint,
        condition=StabilityCondition.REPEAT,
        trials=trials,
        frozen_at=BASE + timedelta(minutes=7),
    )
    assert series.trial_set_fingerprint
    with pytest.raises(ValidationError):
        StabilityTrialReceiptV1.model_validate(
            {**trials[0].model_dump(mode="python"), "label_code": "forged"}
        )


def test_holdout_identity_is_exact_and_access_coverage_reaches_all_evidence() -> None:
    submission = _submission()
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "campaign_holdout_case_ids": (_id("different-holdout"),),
            }
        )
    short_manifest = submission.holdout_access_audit.manifest.model_copy(
        update={
            "coverage_ended_at": BASE + timedelta(minutes=2, seconds=30),
            "frozen_at": BASE + timedelta(minutes=2, seconds=30),
        }
    )
    short_audit = submission.holdout_access_audit.model_copy(
        update={"manifest": short_manifest, "completed_at": BASE + timedelta(minutes=3)}
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "holdout_access_audit": short_audit,
            }
        )
    late_start_manifest = submission.holdout_access_audit.manifest.model_copy(
        update={"coverage_started_at": BASE + timedelta(seconds=30)}
    )
    late_start_audit = submission.holdout_access_audit.model_copy(
        update={"manifest": late_start_manifest}
    )
    with pytest.raises(ValidationError, match="begin before all holdout activity"):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "holdout_access_audit": late_start_audit,
            }
        )


def test_holdout_candidate_and_baseline_outputs_freeze_strictly_before_unseal() -> None:
    submission = _submission()
    unsealed_at = submission.holdout_access_audit.holdout_unsealed_at
    late_candidate = submission.candidate_projections[0].model_copy(
        update={"selected_at": unsealed_at}
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "candidate_projections": (late_candidate,),
            }
        )

    launch = submission.attempt_launches[0]
    baseline = AuthoritativeDeterministicBaselineProjectionV1(
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="supported",
        projection_id=_id("late-baseline"),
        campaign_id=launch.campaign_id,
        case_id=launch.case_id,
        plan_fingerprint=launch.plan_fingerprint,
        metric_question_fingerprint=launch.metric_question_fingerprint,
        evidence_packet_fingerprint=launch.evidence_packet_fingerprint,
        baseline_id="reserved-baseline-v1",
        baseline_version="reserved-v1",
        baseline_configuration_sha256=_id("late-baseline-config"),
        final_estimate_fingerprint=_id("late-baseline-estimate"),
        evaluated_at=unsealed_at,
    )
    scan = _privacy_scan(
        launch.campaign_id,
        tuple(
            sorted(
                (
                    submission.attempt_outcomes[0].structured_output_fingerprint,
                    baseline.final_estimate_fingerprint,
                )
            )
        ),
    )
    with pytest.raises(ValidationError):
        CalibrationEvidenceSubmissionV1.model_validate(
            {
                **submission.model_dump(mode="python"),
                "deterministic_baseline_projections": (baseline,),
                "privacy_scan": scan,
            }
        )


def test_revalidation_closes_model_copy_bypass() -> None:
    submission = _submission()
    bypass = submission.model_copy(update={"activation_allowed": True})
    assert bypass.activation_allowed is True
    with pytest.raises(ValidationError):
        revalidate_calibration_evidence_submission_v1(bypass)
    nested = submission.privacy_scan.model_copy(update={"team_share_allowed": True})
    nested_bypass = submission.model_copy(update={"privacy_scan": nested})
    with pytest.raises(ValidationError):
        revalidate_calibration_evidence_submission_v1(nested_bypass)
    mapping_with_nested_model = submission.model_dump(mode="python")
    mapping_with_nested_model["privacy_scan"] = nested
    with pytest.raises(ValidationError):
        revalidate_calibration_evidence_submission_v1(mapping_with_nested_model)


def test_contracts_forbid_prose_paths_uris_and_extra_fields() -> None:
    launch = _launch()
    for unsafe in ("C:/reserved/secret", "https://example.invalid", "../secret", "contains prose"):
        with pytest.raises(ValidationError):
            AttemptLaunchReceiptV1.model_validate(
                {**launch.model_dump(mode="python"), "runner_adapter_version": unsafe}
            )
    with pytest.raises(ValidationError):
        AttemptLaunchReceiptV1.model_validate(
            {**launch.model_dump(mode="python"), "commentary": "forbidden"}
        )
