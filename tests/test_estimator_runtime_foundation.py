from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import pickle
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.scope_router_contracts import (
    MetricApplicability,
    ScopeCompatibilityState,
    ScopeEvidenceAvailability,
    ScopeEvidenceAvailabilityReceipt,
    ScopeEvidenceKind,
    ScopeExtractionState,
    ScopeRequirementEvidenceLink,
)
from prompt_enhancer.application.estimators.contracts import (
    ArtifactAvailability,
    EstimatorPlan,
    EstimatorReasoningEffort,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    ExecutionDisclosure,
    MetricDirection,
    MetricEstimateState,
    MetricQuestionSpec,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelRun,
    ModelRunState,
    ModelSource,
    ProviderSchemaIdentity,
    RetentionClass,
    StageCondition,
    TokenizerIdentity,
)
from prompt_enhancer.application.estimators.evidence_packets import (
    EphemeralDirectSpan,
    EphemeralMetricEvidencePacket,
    EphemeralMetricQuestionMaterial,
    PacketSpanRole,
    build_runtime_evidence_packet_receipt,
)
from prompt_enhancer.application.estimators.runtime_catalog import (
    EXECUTOR_BINDING_BY_STAGE,
    ROUTE_ORDER,
    RuntimeEstimatorCatalog,
    RuntimePlanRegistration,
    RuntimeStageRegistration,
)
from prompt_enhancer.application.estimators.runtime_contracts import (
    REQUIRED_RESOURCE_KEYS,
    RESOURCE_UNIT_BY_KEY,
    RawModelScoreState,
    ResourceMeasurement,
    ResourceMeasurementState,
    RuntimeAnswerSource,
    RuntimeAuthorizationKind,
    RuntimeAuthorizationReceipt,
    RuntimeExecutionCheckpointReceipt,
    RuntimeExecutionReceipt,
    RuntimeExecutionState,
    RuntimeHumanAdjudicationRequestReceipt,
    RuntimeMetricSelection,
    RuntimeMetricPacketBinding,
    RuntimeQuestionAnswerReceipt,
    RuntimeRawModelScore,
    RuntimeRetrievalHit,
    RuntimeRetrievalResultReceipt,
    RuntimeRetrievalScoreKind,
    RuntimeResourceReceipt,
    RuntimeSecondOpinionDecisionReceipt,
    RuntimeSecondOpinionSignal,
    RuntimeStageAttemptReceipt,
    RuntimeStageOutcomeReceipt,
    RuntimeStageOutcomeState,
    ValidatedExecutionCommitmentReceipt,
    SecondOpinionDecision,
    SecondOpinionSignalKind,
    TriggerSignalState,
    estimator_stage_fingerprint,
    validate_runtime_checkpoint_transition,
)
from prompt_enhancer.application.estimators.scope_projection import (
    RuntimeScopeProjection,
    project_scope_router_input,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.scope_router.deterministic import (
    DeterministicScopeRouter,
)
from prompt_enhancer.application.estimators.contracts import ExecutionDestination


NOW = datetime(2035, 2, 3, 4, 5, tzinfo=timezone.utc)
QUESTION_TEXT = "Does the reserved example satisfy its stated requirement?"
PROMPT_TEXT = "Answer only from direct redacted spans in this reserved example."
RUBRIC_TEXT = "Known requires direct synthetic verification; otherwise abstain."
PRIVATE_MARKER = "reserved-example-evidence-body"


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def synthetic_model(label: str) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=ModelSource.SYNTHETIC,
        requested_model_id=label,
        served_model_id=label,
        requested_revision="synthetic-revision-1",
        served_revision="synthetic-revision-1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        weight_availability=ArtifactAvailability.SYNTHETIC_NO_WEIGHTS,
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"{label}-tokenizer",
            revision="synthetic-revision-1",
            availability=ArtifactAvailability.SYNTHETIC_NO_WEIGHTS,
        ),
        license_id="synthetic-fixture-only",
    )


def metric_question() -> MetricQuestionSpec:
    return MetricQuestionSpec(
        metric_key="outcome.synthetic_verification",
        metric_definition_version="metric-1",
        question_id="synthetic-verification-question",
        question_version="question-1",
        question_sha256=digest(QUESTION_TEXT),
        prompt_template_id="synthetic-evidence-template",
        prompt_template_version="template-1",
        prompt_template_sha256=digest(PROMPT_TEXT),
        rubric_id="synthetic-verification-rubric",
        rubric_version="rubric-1",
        rubric_sha256=digest(RUBRIC_TEXT),
        output_schema_version="runtime-answer-1",
        value_kind=MetricValueKind.FRACTION,
        unit_code="ratio",
        direction=MetricDirection.HIGHER_IS_BETTER,
        lower_bound=0.0,
        upper_bound=1.0,
    )


def synthetic_stages() -> tuple[EstimatorStage, ...]:
    models = {
        EstimatorStageKind.EMBEDDING_RETRIEVAL: synthetic_model("synthetic-embed"),
        EstimatorStageKind.RERANKER: synthetic_model("synthetic-rerank"),
        EstimatorStageKind.SPECIALIST: synthetic_model("synthetic-specialist"),
        EstimatorStageKind.SECOND_OPINION: synthetic_model(
            "synthetic-independent"
        ),
    }
    stages: list[EstimatorStage] = []
    for ordinal, kind in enumerate(
        (
            EstimatorStageKind.OBJECTIVE_EVIDENCE,
            EstimatorStageKind.BM25_RETRIEVAL,
            EstimatorStageKind.EMBEDDING_RETRIEVAL,
            EstimatorStageKind.RERANKER,
            EstimatorStageKind.SPECIALIST,
            EstimatorStageKind.SECOND_OPINION,
            EstimatorStageKind.HUMAN_ADJUDICATION,
        ),
        start=1,
    ):
        condition = StageCondition.ALWAYS
        if kind is EstimatorStageKind.SECOND_OPINION:
            condition = (
                StageCondition.DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE
            )
        elif kind is EstimatorStageKind.HUMAN_ADJUDICATION:
            condition = StageCondition.UNRESOLVED_DISAGREEMENT
        stages.append(
            EstimatorStage(
                ordinal=ordinal,
                kind=kind,
                condition=condition,
                component_version=f"synthetic-component-{ordinal}",
                configuration_sha256=digest(f"synthetic-config-{ordinal}"),
                output_schema_version=f"synthetic-output-{ordinal}",
                model_artifact=models.get(kind),
            )
        )
    return tuple(stages)


def synthetic_plan(route: EstimatorRoute) -> EstimatorPlan:
    return EstimatorPlan(
        plan_key=f"{route.value}-synthetic-runtime",
        plan_version="plan-1",
        route=route,
        question_specs=(metric_question(),),
        evidence_packet_schema_version="runtime-packet-1",
        provider_schemas=(
            ProviderSchemaIdentity(
                provider=Provider.SYNTHETIC,
                adapter_version="synthetic-adapter-1",
                provider_schema_version="synthetic-schema-1",
            ),
        ),
        preprocessing_version="synthetic-preprocessor-1",
        preprocessing_sha256=digest("synthetic-preprocessor"),
        reasoning_effort=EstimatorReasoningEffort.NONE,
        calibration_version="not-assessed-1",
        calibration_sha256=digest("not-assessed"),
        router_version="deterministic-scope-router-v1",
        router_sha256=digest("deterministic-router"),
        redactor_version="synthetic-redactor-1",
        redactor_sha256=digest("synthetic-redactor"),
        stages=synthetic_stages(),
    )


def plan_registration(route: EstimatorRoute) -> RuntimePlanRegistration:
    plan = synthetic_plan(route)
    stages = tuple(
        RuntimeStageRegistration(
            stage_ordinal=stage.ordinal,
            stage_kind=stage.kind,
            stage_fingerprint=estimator_stage_fingerprint(stage),
            executor_key=EXECUTOR_BINDING_BY_STAGE[stage.kind][0],
            invocation_mode=EXECUTOR_BINDING_BY_STAGE[stage.kind][1],
            component_version=stage.component_version,
            configuration_sha256=stage.configuration_sha256,
            input_packet_schema_version=plan.evidence_packet_schema_version,
            output_schema_version=stage.output_schema_version,
            model_artifact_fingerprint=(
                None
                if stage.model_artifact is None
                else stage.model_artifact.canonical_fingerprint
            ),
        )
        for stage in plan.stages
    )
    return RuntimePlanRegistration(
        plan=plan,
        plan_fingerprint=plan.canonical_fingerprint,
        question_bindings=(
            RuntimeMetricSelection(
                metric_key=plan.question_specs[0].metric_key,
                metric_question_fingerprint=plan.question_specs[
                    0
                ].canonical_fingerprint,
            ),
        ),
        stage_registrations=stages,
    )


def runtime_catalog() -> RuntimeEstimatorCatalog:
    return RuntimeEstimatorCatalog(
        registrations=tuple(plan_registration(route) for route in ROUTE_ORDER)
    )


def scope_projection() -> RuntimeScopeProjection:
    requirement_id = digest("synthetic-requirement")
    requirement_version_id = digest("synthetic-requirement-version")
    return RuntimeScopeProjection(
        metric_question_fingerprint=metric_question().canonical_fingerprint,
        metric_applicability=MetricApplicability.APPLICABLE,
        target_project_id=digest("synthetic-project"),
        target_session_id=digest("synthetic-session"),
        target_revision_id=digest("synthetic-revision"),
        target_revision_ordinal=1,
        target_requirement_id=requirement_id,
        target_requirement_version_id=requirement_version_id,
        requirement_observed_sequence=1,
        comparison_project_id=digest("synthetic-project"),
        comparison_session_id=digest("synthetic-session"),
        comparison_revision_id=digest("synthetic-revision"),
        comparison_revision_ordinal=1,
        evidence_observed_sequence=3,
        evidence_requirement_links=(
            ScopeRequirementEvidenceLink(
                requirement_id=requirement_id,
                requirement_version_id=requirement_version_id,
            ),
        ),
        extraction_state=ScopeExtractionState.COMPLETE,
        required_evidence_kinds=(
            ScopeEvidenceKind.ACTION,
            ScopeEvidenceKind.VERIFICATION,
        ),
        evidence_receipts=(
            ScopeEvidenceAvailabilityReceipt(
                kind=ScopeEvidenceKind.ACTION,
                availability=ScopeEvidenceAvailability.AVAILABLE,
                evidence_reference_ids=(digest("synthetic-action-reference"),),
            ),
            ScopeEvidenceAvailabilityReceipt(
                kind=ScopeEvidenceKind.VERIFICATION,
                availability=ScopeEvidenceAvailability.AVAILABLE,
                evidence_reference_ids=(
                    digest("synthetic-verification-reference"),
                ),
            ),
        ),
    )


def question_material(**changes: Any) -> EphemeralMetricQuestionMaterial:
    values: dict[str, Any] = {
        "question_id": "synthetic-verification-question",
        "question_version": "question-1",
        "question_text": SecretStr(QUESTION_TEXT),
        "prompt_template_id": "synthetic-evidence-template",
        "prompt_template_version": "template-1",
        "prompt_template_text": SecretStr(PROMPT_TEXT),
        "rubric_id": "synthetic-verification-rubric",
        "rubric_version": "rubric-1",
        "rubric_text": SecretStr(RUBRIC_TEXT),
    }
    values.update(changes)
    return EphemeralMetricQuestionMaterial(**values)


def direct_span(
    label: str,
    *,
    role: PacketSpanRole,
    sequence: int,
    text: str,
    evidence_kind: ScopeEvidenceKind | None = None,
    linked: bool = False,
) -> EphemeralDirectSpan:
    return EphemeralDirectSpan(
        reference_id=digest(f"{label}-reference"),
        source_record_id=digest(f"{label}-record"),
        role=role,
        observed_sequence=sequence,
        evidence_kind=evidence_kind,
        requirement_id=digest("synthetic-requirement") if linked else None,
        requirement_version_id=(
            digest("synthetic-requirement-version") if linked else None
        ),
        redacted_text=SecretStr(text),
        redacted_text_sha256=digest(text),
    )


def evidence_packet(**changes: Any) -> EphemeralMetricEvidencePacket:
    projection = scope_projection()
    plan = synthetic_plan(EstimatorRoute.BALANCED)
    action = direct_span(
        "synthetic-action",
        role=PacketSpanRole.CANDIDATE_EVIDENCE,
        sequence=2,
        text=PRIVATE_MARKER,
        evidence_kind=ScopeEvidenceKind.ACTION,
        linked=True,
    )
    verification = direct_span(
        "synthetic-verification",
        role=PacketSpanRole.CANDIDATE_EVIDENCE,
        sequence=3,
        text="reserved-example-verification-body",
        evidence_kind=ScopeEvidenceKind.VERIFICATION,
        linked=True,
    )
    values: dict[str, Any] = {
        "packet_schema_version": plan.evidence_packet_schema_version,
        "plan_fingerprint": plan.canonical_fingerprint,
        "route": plan.route,
        "question_spec": plan.question_specs[0],
        "question_material": question_material(),
        "scope_projection": projection,
        "scope_router_output": DeterministicScopeRouter().route(
            project_scope_router_input(projection)
        ),
        "provider": Provider.SYNTHETIC,
        "adapter_version": "synthetic-adapter-1",
        "provider_schema_version": "synthetic-schema-1",
        "preprocessing_version": "synthetic-preprocessor-1",
        "preprocessing_sha256": digest("synthetic-preprocessor"),
        "router_version": "deterministic-scope-router-v1",
        "router_sha256": digest("deterministic-router"),
        "redactor_version": "synthetic-redactor-1",
        "redactor_sha256": digest("synthetic-redactor"),
            "spans": (
                direct_span(
                    "synthetic-chronology",
                    role=PacketSpanRole.CHRONOLOGY,
                    sequence=1,
                    text="The reserved example began.",
                ),
                direct_span(
                    "synthetic-requirement",
                    role=PacketSpanRole.REQUIREMENT,
                    sequence=1,
                    text="The reserved example must produce a checked artifact.",
                    linked=True,
                ),
            action,
            verification,
        ),
        "created_at": NOW,
    }
    values.update(changes)
    return EphemeralMetricEvidencePacket(**values)


def resource_measurements() -> tuple[ResourceMeasurement, ...]:
    known = {
        "cold_start_flag": 0,
        "execution_latency_ms": 125,
        "queue_latency_ms": 4,
    }
    return tuple(
        ResourceMeasurement(
            resource_key=key,
            state=(
                ResourceMeasurementState.KNOWN
                if key in known
                else ResourceMeasurementState.NOT_COLLECTED
            ),
            value=known.get(key),
            unit_code=RESOURCE_UNIT_BY_KEY[key] if key in known else None,
            reason_code=None if key in known else "collector_not_enabled",
        )
        for key in REQUIRED_RESOURCE_KEYS
    )


def execution_bundle() -> tuple[
    RuntimeEstimatorCatalog,
    RuntimeAuthorizationReceipt,
    RuntimeExecutionReceipt,
    ValidatedExecutionCommitmentReceipt,
    Any,
]:
    catalog = runtime_catalog()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)
    packet_receipt = build_runtime_evidence_packet_receipt(evidence_packet())
    selection = RuntimeMetricSelection(
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
    )
    authorization = RuntimeAuthorizationReceipt(
        authorization_id=digest("runtime-authorization"),
        kind=RuntimeAuthorizationKind.SYNTHETIC_TEST,
        provider=Provider.SYNTHETIC,
        destination=ExecutionDestination.SYNTHETIC_TEST,
        plan_fingerprint=registration.plan_fingerprint,
        scope_fingerprint=digest("runtime-input"),
        selected_metrics=(selection,),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=9),
        one_shot=True,
    )
    execution = RuntimeExecutionReceipt(
        execution_id=digest("runtime-execution"),
        authorization_fingerprint=authorization.canonical_fingerprint,
        plan_fingerprint=registration.plan_fingerprint,
        route=EstimatorRoute.BALANCED,
        provider=Provider.SYNTHETIC,
        project_id=digest("synthetic-project"),
        session_id=digest("synthetic-session"),
        session_revision_id=digest("synthetic-revision"),
        input_fingerprint=authorization.scope_fingerprint,
        metric_packets=(
            RuntimeMetricPacketBinding(
                metric_key=packet_receipt.metric_key,
                metric_question_fingerprint=(
                    packet_receipt.metric_question_fingerprint
                ),
                evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
            ),
        ),
        created_at=NOW,
    )
    commitment = catalog.plan_for_route(
        EstimatorRoute.BALANCED
    ).build_execution_commitment(
        execution,
        authorization,
        (packet_receipt,),
    )
    return catalog, authorization, execution, commitment, packet_receipt


def test_closed_catalog_binds_exact_fast_balanced_and_deep_plans() -> None:
    catalog, authorization, execution, commitment, packet_receipt = execution_bundle()

    assert tuple(item.plan.route for item in catalog.registrations) == ROUTE_ORDER
    assert catalog.execution_only is True
    assert catalog.activation_allowed is False
    assert catalog.product_metric_write_allowed is False
    assert catalog.dynamic_discovery_allowed is False
    balanced = catalog.plan_for_route(EstimatorRoute.BALANCED)
    assert balanced.plan.max_loaded_models == 1
    assert balanced.plan.model_load_policy == "one_at_a_time"
    assert balanced.question_spec("outcome.synthetic_verification") == metric_question()
    assert balanced.stage_registration(5).stage_kind is EstimatorStageKind.SPECIALIST
    assert all(
        stage.model_artifact is None
        or stage.model_artifact.source is ModelSource.SYNTHETIC
        for registration in catalog.registrations
        for stage in registration.plan.stages
    )

    specialist = balanced.plan.stages[4]
    attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("catalog-bound-attempt"),
        execution_id=execution.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        authorization_fingerprint=execution.authorization_fingerprint,
        plan_fingerprint=balanced.plan_fingerprint,
        route=execution.route,
        provider=execution.provider,
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=specialist.ordinal,
        stage_kind=specialist.kind,
        stage_fingerprint=estimator_stage_fingerprint(specialist),
        stage_registration_fingerprint=balanced.stage_registration(
            specialist.ordinal
        ).canonical_fingerprint,
        model_artifact_fingerprint=specialist.model_artifact.canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    assert (
        catalog.validate_stage_attempt(
            EstimatorRoute.BALANCED,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
        )
        is attempt
    )
    drifted_attempt = RuntimeStageAttemptReceipt.model_validate(
        {**attempt.__dict__, "stage_fingerprint": digest("unreviewed-stage")}
    )
    with pytest.raises(ValueError, match="reviewed bindings"):
        catalog.validate_stage_attempt(
            EstimatorRoute.BALANCED,
            drifted_attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
        )


def test_catalog_rejects_question_stage_and_plan_hash_drift() -> None:
    registration = plan_registration(EstimatorRoute.BALANCED)
    wrong_questions = (
        RuntimeMetricSelection(
            metric_key="outcome.synthetic_verification",
            metric_question_fingerprint=digest("different-question"),
        ),
    )
    with pytest.raises(ValidationError, match="exact plan question hash"):
        RuntimePlanRegistration(
            plan=registration.plan,
            plan_fingerprint=registration.plan_fingerprint,
            question_bindings=wrong_questions,
            stage_registrations=registration.stage_registrations,
        )

    drifted_stage = RuntimeStageRegistration.model_validate(
        {
            **registration.stage_registrations[0].model_dump(),
            "configuration_sha256": digest("drifted-configuration"),
        }
    )
    with pytest.raises(ValidationError, match="exact immutable stage"):
        RuntimePlanRegistration(
            plan=registration.plan,
            plan_fingerprint=registration.plan_fingerprint,
            question_bindings=registration.question_bindings,
            stage_registrations=(
                drifted_stage,
                *registration.stage_registrations[1:],
            ),
        )

    with pytest.raises(ValidationError, match="exact plan"):
        RuntimePlanRegistration(
            plan=registration.plan,
            plan_fingerprint=digest("drifted-plan"),
            question_bindings=registration.question_bindings,
            stage_registrations=registration.stage_registrations,
        )

    catalog = runtime_catalog()
    with pytest.raises(TypeError, match="update-copy bypass"):
        catalog.registrations[0].model_copy(update={"activation_allowed": True})


def test_ephemeral_packet_hides_text_refuses_serialization_and_emits_only_receipt() -> None:
    packet = evidence_packet()

    assert PRIVATE_MARKER not in repr(packet)
    assert PRIVATE_MARKER not in repr(packet.spans[2])
    with pytest.raises(TypeError, match="cannot be serialized"):
        packet.model_dump()
    with pytest.raises(TypeError, match="cannot be serialized"):
        packet.model_dump_json()
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(packet)

    receipt = build_runtime_evidence_packet_receipt(packet)
    serialized = receipt.model_dump_json()
    assert PRIVATE_MARKER not in serialized
    assert "redacted_text" not in serialized
    assert receipt.packet_fingerprint == packet.packet_fingerprint
    assert receipt.metric_question_fingerprint == metric_question().canonical_fingerprint
    assert receipt.ephemeral_payload_retained is False
    assert receipt.execution_only is True
    assert receipt.activation_allowed is False
    assert receipt.private_export_allowed is False
    assert receipt.team_share_allowed is False


def test_ephemeral_packet_rejects_material_or_direct_span_hash_drift() -> None:
    with pytest.raises(ValidationError, match="exact in-memory text"):
        EphemeralDirectSpan(
            reference_id=digest("tampered-reference"),
            source_record_id=digest("tampered-record"),
            role=PacketSpanRole.CHRONOLOGY,
            observed_sequence=1,
            redacted_text=SecretStr("reserved-example-text"),
            redacted_text_sha256=digest("other"),
        )

    with pytest.raises(ValidationError, match="exact hashes"):
        evidence_packet(
            question_material=question_material(
                rubric_text=SecretStr("A different synthetic rubric.")
            )
        )

    packet = evidence_packet()
    with pytest.raises(TypeError, match="update-copy bypass"):
        packet.model_copy(update={"activation_allowed": True})

    projection = scope_projection()
    foreign_projection = RuntimeScopeProjection.model_validate(
        {
            **projection.model_dump(),
            "evidence_receipts": (
                ScopeEvidenceAvailabilityReceipt(
                    kind=ScopeEvidenceKind.ACTION,
                    availability=ScopeEvidenceAvailability.AVAILABLE,
                    evidence_reference_ids=(digest("foreign-action-reference"),),
                ),
                projection.evidence_receipts[1],
            ),
        }
    )
    with pytest.raises(ValidationError, match="not vetted"):
        evidence_packet(
            scope_projection=foreign_projection,
            scope_router_output=DeterministicScopeRouter().route(
                project_scope_router_input(foreign_projection)
            ),
        )


def test_scope_projection_is_metadata_only_and_routes_without_model_labels() -> None:
    projection = scope_projection()
    router_input = project_scope_router_input(projection)
    result = DeterministicScopeRouter().route(router_input)

    assert result.state is ScopeCompatibilityState.COMPATIBLE
    assert result.evidence_coverage.ratio == 1.0
    guard_fields = {"model_output_allowed", "authored_label_allowed"}
    forbidden_fragments = {"text", "label", "prediction", "score", "outcome"}
    assert not any(
        fragment in field_name
        for field_name in RuntimeScopeProjection.model_fields
        if field_name not in guard_fields
        for fragment in forbidden_fragments
    )
    assert projection.metadata_only is True
    assert projection.model_output_allowed is False
    assert projection.authored_label_allowed is False
    with pytest.raises(TypeError, match="update-copy bypass"):
        projection.model_copy(update={"model_output_allowed": True})


def test_resource_receipt_requires_an_explicit_state_for_every_measurement() -> None:
    measurements = resource_measurements()
    receipt = RuntimeResourceReceipt(
        resource_receipt_id=digest("synthetic-resource-receipt"),
        attempt_id=digest("synthetic-attempt"),
        stage_fingerprint=digest("synthetic-stage"),
        collector_version="synthetic-collector-1",
        runtime_environment_fingerprint=digest("synthetic-runtime-environment"),
        measurements=measurements,
        created_at=NOW,
    )

    assert receipt.measurements[REQUIRED_RESOURCE_KEYS.index("cold_start_flag")].value == 0
    assert all(item.state is not None for item in receipt.measurements)
    with pytest.raises(ValidationError, match="at least 12 items"):
        RuntimeResourceReceipt(
            resource_receipt_id=digest("incomplete-resource-receipt"),
            attempt_id=digest("synthetic-attempt"),
            stage_fingerprint=digest("synthetic-stage"),
            collector_version="synthetic-collector-1",
            runtime_environment_fingerprint=digest("synthetic-runtime-environment"),
            measurements=measurements[:-1],
            created_at=NOW,
        )
    with pytest.raises(ValidationError, match="explicit reason"):
        ResourceMeasurement(
            resource_key="energy_mwh",
            state=ResourceMeasurementState.NOT_COLLECTED,
        )
    with pytest.raises(TypeError, match="update-copy bypass"):
        measurements[0].model_copy(update={"value": -1})


def test_bm25_receipt_ranks_only_opaque_refs_and_never_claims_confidence() -> None:
    catalog, authorization, execution, commitment, packet_receipt = execution_bundle()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)
    bm25_stage = registration.plan.stages[1]
    attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("synthetic-bm25-attempt"),
        execution_id=execution.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        authorization_fingerprint=execution.authorization_fingerprint,
        plan_fingerprint=registration.plan_fingerprint,
        route=execution.route,
        provider=execution.provider,
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=bm25_stage.ordinal,
        stage_kind=bm25_stage.kind,
        stage_fingerprint=estimator_stage_fingerprint(bm25_stage),
        stage_registration_fingerprint=registration.stage_registration(
            bm25_stage.ordinal
        ).canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    result = RuntimeRetrievalResultReceipt(
        result_id=digest("synthetic-bm25-result"),
        execution_id=attempt.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        attempt_id=attempt.attempt_id,
        plan_fingerprint=attempt.plan_fingerprint,
        stage_fingerprint=attempt.stage_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        metric_key=packet_receipt.metric_key,
        stage_kind=EstimatorStageKind.BM25_RETRIEVAL,
        score_kind=RuntimeRetrievalScoreKind.BM25_RAW,
        query_fingerprint=packet_receipt.retrieval_query_fingerprint,
        candidate_index_fingerprint=packet_receipt.retrieval_index_sha256,
        candidate_count=len(packet_receipt.opaque_evidence_refs),
        candidate_reference_ids=packet_receipt.opaque_evidence_refs,
        hits=(
            RuntimeRetrievalHit(
                evidence_reference_id=packet_receipt.opaque_evidence_refs[0],
                rank=1,
                raw_score=1.25,
            ),
        ),
        created_at=NOW + timedelta(seconds=1),
    )

    assert (
        catalog.validate_retrieval_result(
            EstimatorRoute.BALANCED,
            result,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
        )
        is result
    )
    assert result.hits[0].score_semantics == "uncalibrated_retrieval_score"
    assert result.quality_estimate_available is False
    assert result.activation_allowed is False
    assert "confidence" not in RuntimeRetrievalResultReceipt.model_fields
    assert set(hit.evidence_reference_id for hit in result.hits).issubset(
        packet_receipt.opaque_evidence_refs
    )
    with pytest.raises(ValidationError, match="score kind"):
        RuntimeRetrievalResultReceipt.model_validate(
            {
                **result.__dict__,
                "score_kind": RuntimeRetrievalScoreKind.RERANKER_RAW,
            }
        )

    resources = RuntimeResourceReceipt(
        resource_receipt_id=digest("bm25-resource-receipt"),
        attempt_id=attempt.attempt_id,
        stage_fingerprint=attempt.stage_fingerprint,
        collector_version="synthetic-collector-1",
        runtime_environment_fingerprint=digest("bm25-runtime-environment"),
        measurements=resource_measurements(),
        created_at=NOW + timedelta(seconds=1),
    )
    outcome = RuntimeStageOutcomeReceipt(
        outcome_id=digest("bm25-stage-outcome"),
        attempt_id=attempt.attempt_id,
        execution_id=attempt.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        plan_fingerprint=attempt.plan_fingerprint,
        metric_question_fingerprint=attempt.metric_question_fingerprint,
        stage_fingerprint=attempt.stage_fingerprint,
        stage_registration_fingerprint=attempt.stage_registration_fingerprint,
        resource_receipt_fingerprint=resources.canonical_fingerprint,
        state=RuntimeStageOutcomeState.COMPLETED,
        output_fingerprint=result.canonical_fingerprint,
        output_kind="retrieval_result",
        recorded_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(ValueError, match="terminal completion is disabled"):
        catalog.validate_stage_outcome(
            EstimatorRoute.BALANCED,
            outcome,
            attempt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
            packet_receipt,
            resources,
            result,
        )


def test_raw_runtime_answer_never_claims_calibration_or_metric_activation() -> None:
    catalog, authorization, execution, commitment, packet_receipt = execution_bundle()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)
    plan = registration.plan
    specialist = plan.stages[4]
    attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("synthetic-specialist-attempt"),
        execution_id=execution.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        authorization_fingerprint=execution.authorization_fingerprint,
        plan_fingerprint=plan.canonical_fingerprint,
        route=execution.route,
        provider=execution.provider,
        metric_key=metric_question().metric_key,
        metric_question_fingerprint=metric_question().canonical_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=specialist.ordinal,
        stage_kind=specialist.kind,
        stage_fingerprint=estimator_stage_fingerprint(specialist),
        stage_registration_fingerprint=registration.stage_registration(
            specialist.ordinal
        ).canonical_fingerprint,
        model_artifact_fingerprint=specialist.model_artifact.canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    answer = RuntimeQuestionAnswerReceipt(
        answer_id=digest("synthetic-answer"),
        execution_id=attempt.execution_id,
        attempt_id=attempt.attempt_id,
        plan_fingerprint=attempt.plan_fingerprint,
        stage_fingerprint=attempt.stage_fingerprint,
        evidence_packet_fingerprint=attempt.evidence_packet_fingerprint,
        metric_question_fingerprint=attempt.metric_question_fingerprint,
        metric_key=attempt.metric_key,
        stage_kind=attempt.stage_kind,
        source=RuntimeAnswerSource.SYNTHETIC_MODEL_RAW,
        state=MetricEstimateState.KNOWN,
        value_kind=MetricValueKind.FRACTION,
        numeric_value=0.75,
        model_run_id=digest("synthetic-model-run"),
        raw_model_score=RuntimeRawModelScore(
            state=RawModelScoreState.KNOWN,
            value=0.61,
        ),
        opaque_evidence_refs=(digest("synthetic-action-reference"),),
        created_at=NOW + timedelta(seconds=1),
    )
    model_run = ModelRun(
        run_id=answer.model_run_id,
        execution_id=attempt.execution_id,
        plan_fingerprint=attempt.plan_fingerprint,
        evidence_packet_fingerprint=attempt.evidence_packet_fingerprint,
        route=plan.route,
        stage_ordinal=attempt.stage_ordinal,
        stage_kind=attempt.stage_kind,
        model_artifact=specialist.model_artifact,
        execution=ExecutionDisclosure(
            destination=ExecutionDestination.SYNTHETIC_TEST,
            retention_class=RetentionClass.SYNTHETIC,
            retention_days=0,
            disclosure_version="synthetic-disclosure-1",
            retention_acknowledged=False,
        ),
        state=ModelRunState.COMPLETED,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        cold_start=False,
        queue_latency_ms=0,
        latency_ms=1000,
        input_tokens=12,
        output_tokens=2,
        usage_provenance_version="synthetic-usage-1",
        response_schema_version=specialist.output_schema_version,
        structured_output_valid=True,
        fallback_used=False,
    )

    assert (
        catalog.validate_question_answer(
            EstimatorRoute.BALANCED,
            answer,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
            model_run,
        )
        is answer
    )
    assert answer.calibration_state == "not_assessed"
    assert answer.raw_model_score.semantics == "uncalibrated_raw_model_score"
    assert answer.quality_estimate_available is False
    assert answer.execution_only is True
    assert answer.activation_allowed is False
    assert answer.product_metric_write_allowed is False
    assert "confidence" not in RuntimeQuestionAnswerReceipt.model_fields
    with pytest.raises(ValidationError, match="Extra inputs"):
        RuntimeQuestionAnswerReceipt(
            **answer.model_dump(),
            confidence=0.61,
        )
    with pytest.raises(ValidationError, match="only objective"):
        RuntimeQuestionAnswerReceipt.model_validate(
            {
                **answer.model_dump(),
                "numeric_value": 0.5,
                "numerator": 1,
                "denominator": 2,
            }
        )
    foreign_ref_answer = RuntimeQuestionAnswerReceipt.model_validate(
        {
            **answer.model_dump(),
            "opaque_evidence_refs": (digest("foreign-synthetic-evidence"),),
        }
    )
    with pytest.raises(ValueError, match="exact packet and stage"):
        catalog.validate_question_answer(
            EstimatorRoute.BALANCED,
            foreign_ref_answer,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
            model_run,
        )


def second_opinion_signals(
    state_by_kind: dict[SecondOpinionSignalKind, TriggerSignalState],
) -> tuple[RuntimeSecondOpinionSignal, ...]:
    return tuple(
        RuntimeSecondOpinionSignal(
            kind=kind,
            state=state_by_kind.get(kind, TriggerSignalState.ABSENT),
            evidence_fingerprint=(
                digest(f"synthetic-{kind.value}-trigger")
                if state_by_kind.get(kind) is TriggerSignalState.PRESENT
                else None
            ),
        )
        for kind in sorted(SecondOpinionSignalKind, key=lambda item: item.value)
    )


def second_opinion_decision(
    *,
    signals: tuple[RuntimeSecondOpinionSignal, ...],
    decision: SecondOpinionDecision,
) -> RuntimeSecondOpinionDecisionReceipt:
    return RuntimeSecondOpinionDecisionReceipt(
        decision_id=digest(f"synthetic-decision-{decision.value}"),
        execution_id=digest("synthetic-execution"),
        plan_fingerprint=digest("synthetic-plan"),
        metric_question_fingerprint=digest("synthetic-question"),
        evidence_packet_fingerprint=digest("synthetic-packet"),
        specialist_attempt_id=digest("synthetic-specialist-attempt"),
        specialist_answer_fingerprint=digest("synthetic-specialist-answer"),
        policy_version="synthetic-trigger-policy-1",
        policy_sha256=digest("synthetic-trigger-policy"),
        signals=signals,
        decision=decision,
        created_at=NOW,
    )


def test_second_opinion_unknown_is_not_silently_false_and_human_wait_is_explicit() -> None:
    unknown_signals = second_opinion_signals(
        {SecondOpinionSignalKind.DRIFT: TriggerSignalState.UNKNOWN}
    )
    decision = second_opinion_decision(
        signals=unknown_signals,
        decision=SecondOpinionDecision.INSUFFICIENT_EVIDENCE,
    )
    assert decision.decision is SecondOpinionDecision.INSUFFICIENT_EVIDENCE

    present_signals = second_opinion_signals(
        {SecondOpinionSignalKind.DISAGREEMENT: TriggerSignalState.PRESENT}
    )
    trigger_decision = second_opinion_decision(
        signals=present_signals,
        decision=SecondOpinionDecision.TRIGGER,
    )
    assert trigger_decision.decision is SecondOpinionDecision.TRIGGER
    with pytest.raises(ValidationError, match="closed trigger policy"):
        second_opinion_decision(
            signals=unknown_signals,
            decision=SecondOpinionDecision.DO_NOT_TRIGGER,
        )

    request = RuntimeHumanAdjudicationRequestReceipt(
        request_id=digest("synthetic-human-request"),
        execution_id=digest("synthetic-execution"),
        plan_fingerprint=digest("synthetic-plan"),
        metric_question_fingerprint=digest("synthetic-question"),
        evidence_packet_fingerprint=digest("synthetic-packet"),
        human_stage_registration_fingerprint=digest("synthetic-human-stage"),
        second_opinion_decision_fingerprint=trigger_decision.canonical_fingerprint,
        specialist_answer_fingerprint=digest("synthetic-specialist-answer"),
        second_opinion_answer_fingerprint=digest("synthetic-second-answer"),
        reason_code="unresolved_disagreement",
        created_at=NOW,
    )
    assert request.state == "awaiting_human"
    assert request.activation_allowed is False


def test_conditional_stage_attempts_require_exact_gate_lineage() -> None:
    catalog, authorization, execution, commitment, packet_receipt = execution_bundle()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)
    second_stage = registration.plan.stages[5]
    second_attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("gated-second-attempt"),
        execution_id=execution.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        authorization_fingerprint=execution.authorization_fingerprint,
        plan_fingerprint=execution.plan_fingerprint,
        route=execution.route,
        provider=execution.provider,
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=second_stage.ordinal,
        stage_kind=second_stage.kind,
        stage_fingerprint=estimator_stage_fingerprint(second_stage),
        stage_registration_fingerprint=registration.stage_registration(
            second_stage.ordinal
        ).canonical_fingerprint,
        model_artifact_fingerprint=second_stage.model_artifact.canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    with pytest.raises(ValueError, match="exact trigger"):
        catalog.validate_stage_attempt(
            EstimatorRoute.BALANCED,
            second_attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
        )

    human_stage = registration.plan.stages[6]
    human_attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("gated-human-attempt"),
        execution_id=execution.execution_id,
        execution_commitment_fingerprint=commitment.canonical_fingerprint,
        authorization_fingerprint=execution.authorization_fingerprint,
        plan_fingerprint=execution.plan_fingerprint,
        route=execution.route,
        provider=execution.provider,
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=human_stage.ordinal,
        stage_kind=human_stage.kind,
        stage_fingerprint=estimator_stage_fingerprint(human_stage),
        stage_registration_fingerprint=registration.stage_registration(
            human_stage.ordinal
        ).canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    with pytest.raises(ValueError, match="unresolved-disagreement"):
        catalog.validate_stage_attempt(
            EstimatorRoute.BALANCED,
            human_attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            (packet_receipt,),
        )


def test_checkpoint_contract_preserves_restart_and_cancellation_boundaries() -> None:
    running = RuntimeExecutionCheckpointReceipt(
        checkpoint_id=digest("synthetic-running-checkpoint"),
        execution_id=digest("synthetic-execution"),
        execution_commitment_fingerprint=digest("synthetic-commitment"),
        plan_fingerprint=digest("synthetic-plan"),
        metric_key="outcome.synthetic_verification",
        metric_question_fingerprint=digest("synthetic-question"),
        evidence_packet_fingerprint=digest("synthetic-packet"),
        checkpoint_sequence=2,
        restart_generation=1,
        state=RuntimeExecutionState.RUNNING,
        last_completed_stage_ordinal=2,
        last_completed_attempt_id=digest("synthetic-attempt-2"),
        next_stage_ordinal=3,
        next_stage_fingerprint=digest("synthetic-stage-3"),
        cancellation_requested=False,
        recorded_at=NOW,
    )
    assert running.restart_generation == 1

    cancelled = RuntimeExecutionCheckpointReceipt(
        checkpoint_id=digest("synthetic-cancelled-checkpoint"),
        execution_id=digest("synthetic-execution"),
        execution_commitment_fingerprint=digest("synthetic-commitment"),
        plan_fingerprint=digest("synthetic-plan"),
        metric_key="outcome.synthetic_verification",
        metric_question_fingerprint=digest("synthetic-question"),
        evidence_packet_fingerprint=digest("synthetic-packet"),
        previous_checkpoint_fingerprint=running.canonical_fingerprint,
        checkpoint_sequence=3,
        restart_generation=1,
        state=RuntimeExecutionState.CANCELLED,
        last_completed_stage_ordinal=2,
        last_completed_attempt_id=digest("synthetic-attempt-2"),
        cancellation_requested=True,
        state_reason_code="user_cancelled",
        recorded_at=NOW + timedelta(seconds=1),
    )
    assert cancelled.cancellation_requested is True
    assert (
        validate_runtime_checkpoint_transition(running, cancelled)
        == cancelled
    )
    with pytest.raises(ValidationError, match="next stage must follow"):
        RuntimeExecutionCheckpointReceipt.model_validate(
            {**running.__dict__, "next_stage_ordinal": 4}
        )


def test_synthetic_authority_is_exact_one_shot_and_cannot_activate() -> None:
    question = metric_question()
    receipt = RuntimeAuthorizationReceipt(
        authorization_id=digest("synthetic-authorization"),
        kind=RuntimeAuthorizationKind.SYNTHETIC_TEST,
        provider=Provider.SYNTHETIC,
        destination=ExecutionDestination.SYNTHETIC_TEST,
        plan_fingerprint=digest("synthetic-plan"),
        scope_fingerprint=digest("synthetic-scope"),
        selected_metrics=(
            RuntimeMetricSelection(
                metric_key=question.metric_key,
                metric_question_fingerprint=question.canonical_fingerprint,
            ),
        ),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        one_shot=True,
    )

    assert receipt.content_free is True
    assert receipt.execution_only is True
    assert receipt.activation_allowed is False
    assert receipt.consumption_enforced is False
    assert receipt.runtime_enabled is False
    with pytest.raises(ValidationError, match="must be one-shot"):
        RuntimeAuthorizationReceipt(
            **{
                **receipt.model_dump(),
                "one_shot": False,
            }
        )
    with pytest.raises(TypeError, match="update-copy bypass"):
        receipt.model_copy(update={"activation_allowed": True})


def test_execution_authority_binding_rejects_expired_or_foreign_scope() -> None:
    catalog, authorization, execution, commitment, packet_receipt = execution_bundle()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)

    expired = RuntimeAuthorizationReceipt.model_validate(
        {
            **authorization.model_dump(),
            "issued_at": NOW - timedelta(minutes=20),
            "expires_at": NOW - timedelta(minutes=10),
        }
    )
    with pytest.raises(ValueError, match="authority and packet scope"):
        registration.build_execution_commitment(
            execution,
            expired,
            (packet_receipt,),
        )

    foreign_execution = RuntimeExecutionReceipt.model_validate(
        {
            **execution.model_dump(),
            "input_fingerprint": digest("foreign-runtime-input"),
        }
    )
    with pytest.raises(ValueError, match="authority and packet scope"):
        registration.build_execution_commitment(
            foreign_execution,
            authorization,
            (packet_receipt,),
        )

    repeated = registration.build_execution_commitment(
        execution,
        authorization,
        (packet_receipt,),
    )
    assert repeated == commitment
    assert repeated.runtime_enabled is False
    assert repeated.consumption_enforced is False
    assert repeated.disabled_reason == "durable_consumption_not_implemented"

    forged_authorization = RuntimeAuthorizationReceipt.model_validate(
        {
            **authorization.model_dump(),
            "authorization_id": digest("forged-authorization"),
        }
    )
    forged_execution = RuntimeExecutionReceipt.model_validate(
        {
            **execution.model_dump(),
            "authorization_fingerprint": (
                forged_authorization.canonical_fingerprint
            ),
        }
    )
    forged_commitment = ValidatedExecutionCommitmentReceipt(
        commitment_id=digest("forged-commitment"),
        execution_fingerprint=forged_execution.canonical_fingerprint,
        authorization_fingerprint=forged_authorization.canonical_fingerprint,
        plan_fingerprint=registration.plan_fingerprint,
        route=registration.plan.route,
        provider=forged_authorization.provider,
        packet_fingerprints=(packet_receipt.packet_fingerprint,),
        created_at=forged_execution.created_at,
    )
    stage = registration.plan.stages[0]
    forged_attempt = RuntimeStageAttemptReceipt(
        attempt_id=digest("forged-attempt"),
        execution_id=forged_execution.execution_id,
        execution_commitment_fingerprint=forged_commitment.canonical_fingerprint,
        authorization_fingerprint=forged_execution.authorization_fingerprint,
        plan_fingerprint=forged_execution.plan_fingerprint,
        route=forged_execution.route,
        provider=forged_execution.provider,
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
        stage_ordinal=stage.ordinal,
        stage_kind=stage.kind,
        stage_fingerprint=estimator_stage_fingerprint(stage),
        stage_registration_fingerprint=registration.stage_registration(
            stage.ordinal
        ).canonical_fingerprint,
        attempt_ordinal=1,
        started_at=NOW,
    )
    with pytest.raises(ValueError):
        catalog.validate_stage_attempt(
            EstimatorRoute.BALANCED,
            forged_attempt,
            packet_receipt,
            forged_execution,
            forged_commitment,
            authorization,
            (packet_receipt,),
        )


@pytest.mark.parametrize(
    ("provider", "destination", "accepted"),
    (
        (Provider.SYNTHETIC, ExecutionDestination.SYNTHETIC_TEST, True),
        (Provider.CODEX, ExecutionDestination.LOCAL_DEVICE, True),
        (Provider.CODEX, ExecutionDestination.CODEX_CLI, True),
        (Provider.CLAUDE_CODE, ExecutionDestination.LOCAL_DEVICE, True),
        (Provider.CLAUDE_CODE, ExecutionDestination.MANUAL_IMPORT, True),
        (Provider.CODEX, ExecutionDestination.SYNTHETIC_TEST, False),
        (Provider.SYNTHETIC, ExecutionDestination.LOCAL_DEVICE, False),
        (Provider.CODEX, ExecutionDestination.ANTHROPIC_API, False),
    ),
)
def test_authority_provider_destination_matrix(
    provider: Provider,
    destination: ExecutionDestination,
    accepted: bool,
) -> None:
    values = {
        "authorization_id": digest(f"matrix-{provider.value}-{destination.value}"),
        "kind": (
            RuntimeAuthorizationKind.SYNTHETIC_TEST
            if provider is Provider.SYNTHETIC
            else RuntimeAuthorizationKind.MANUAL_ONCE
        ),
        "provider": provider,
        "destination": destination,
        "plan_fingerprint": digest("matrix-plan"),
        "scope_fingerprint": digest("matrix-scope"),
        "selected_metrics": (
            RuntimeMetricSelection(
                metric_key=metric_question().metric_key,
                metric_question_fingerprint=metric_question().canonical_fingerprint,
            ),
        ),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "one_shot": True,
    }
    if accepted:
        assert RuntimeAuthorizationReceipt(**values).provider is provider
    else:
        with pytest.raises(ValidationError):
            RuntimeAuthorizationReceipt(**values)
