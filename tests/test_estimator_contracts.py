from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators import (
    MAX_PROMOTED_CANDIDATES_PER_FAMILY,
    MAX_SCREENED_CANDIDATES_PER_FAMILY,
    Adjudication,
    AdjudicationState,
    AdjudicationTrigger,
    ArtifactAvailability,
    ArtifactDigest,
    CandidateFamilySelection,
    EstimateUncertainty,
    EstimatorExecution,
    EstimatorExecutionState,
    EstimatorPlan,
    EstimatorReasoningEffort,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    EstimatorStageReceipt,
    EstimatorStageReceiptState,
    EvidencePacketReceipt,
    ExecutionDestination,
    ExecutionDisclosure,
    ImmutableJudgment,
    IMMUTABLE_JUDGMENT_CONTRACT_VERSION,
    JudgmentSource,
    LabelProbability,
    MetricDirection,
    MetricEstimate,
    MetricEstimateSource,
    MetricEstimateState,
    MetricQuestionSpec,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelRun,
    ModelRunState,
    ModelSource,
    ModelVote,
    ProviderSchemaIdentity,
    RetentionClass,
    StageCondition,
    TokenizerIdentity,
    UncertaintyKind,
)
from prompt_enhancer.domain import Provider, StrictModel


NOW = datetime(2030, 1, 2, 3, 4, tzinfo=timezone.utc)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def artifact_digest(label: str, *, file_name: str = "model.safetensors") -> ArtifactDigest:
    return ArtifactDigest(file_name=file_name, sha256=digest(label))


def synthetic_model(
    label: str = "synthetic-model-a",
    *,
    requested_mode: ModelExecutionMode = ModelExecutionMode.STANDARD,
    served_mode: ModelExecutionMode | None = None,
    served_model_id: str | None = None,
    served_revision: str | None = None,
) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=ModelSource.SYNTHETIC,
        requested_model_id=label,
        served_model_id=served_model_id or label,
        requested_revision="revision-1",
        served_revision=served_revision or "revision-1",
        requested_execution_mode=requested_mode,
        served_execution_mode=served_mode or requested_mode,
        weight_availability=ArtifactAvailability.SYNTHETIC_NO_WEIGHTS,
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"{label}-tokenizer",
            revision="revision-1",
            availability=ArtifactAvailability.SYNTHETIC_NO_WEIGHTS,
        ),
        license_id="synthetic-fixture-only",
    )


def remote_model(
    source: ModelSource,
    label: str,
    *,
    requested_mode: ModelExecutionMode = ModelExecutionMode.STANDARD,
    served_mode: ModelExecutionMode | None = None,
    served_model_id: str | None = None,
) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=source,
        requested_model_id=label,
        served_model_id=served_model_id or label,
        requested_revision="provider-current-1",
        served_revision="provider-current-1",
        requested_execution_mode=requested_mode,
        served_execution_mode=served_mode or requested_mode,
        weight_availability=ArtifactAvailability.PROVIDER_MANAGED,
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"{label}-tokenizer",
            revision="provider-current-1",
            availability=ArtifactAvailability.PROVIDER_MANAGED,
        ),
        license_id="provider-terms-1",
    )


def local_model(label: str) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=ModelSource.LOCAL_WEIGHTS,
        requested_model_id=label,
        served_model_id=label,
        requested_revision="revision-1",
        served_revision="revision-1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        weight_availability=ArtifactAvailability.PINNED_HASHES,
        weight_artifacts=(artifact_digest(f"{label}-weights"),),
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"{label}-tokenizer",
            revision="revision-1",
            availability=ArtifactAvailability.PINNED_HASHES,
            artifacts=(
                artifact_digest(
                    f"{label}-tokenizer", file_name="tokenizer.json"
                ),
            ),
        ),
        license_id="example-license-1",
    )


def question(
    *,
    value_kind: MetricValueKind = MetricValueKind.FRACTION,
    metric_key: str = "quality.requirement_coverage",
) -> MetricQuestionSpec:
    numeric = value_kind in {MetricValueKind.CONTINUOUS, MetricValueKind.FRACTION}
    lower = 0.0 if numeric else None
    upper = 1.0 if numeric else None
    return MetricQuestionSpec(
        metric_key=metric_key,
        metric_definition_version="metric-1",
        question_id="requirement-coverage-question",
        question_version="question-1",
        question_sha256=digest("question"),
        prompt_template_id="metric-question-template",
        prompt_template_version="template-1",
        prompt_template_sha256=digest("template"),
        rubric_id="requirement-coverage-rubric",
        rubric_version="rubric-1",
        rubric_sha256=digest("rubric"),
        output_schema_version="estimate-schema-1",
        value_kind=value_kind,
        unit_code="ratio" if numeric else "label",
        direction=MetricDirection.HIGHER_IS_BETTER,
        lower_bound=lower,
        upper_bound=upper,
    )


def stages(*, synthetic: bool = True) -> tuple[EstimatorStage, ...]:
    models = {
        EstimatorStageKind.EMBEDDING_RETRIEVAL: synthetic_model("synthetic-embed"),
        EstimatorStageKind.RERANKER: synthetic_model("synthetic-rerank"),
        EstimatorStageKind.SPECIALIST: synthetic_model("synthetic-specialist"),
        EstimatorStageKind.SECOND_OPINION: synthetic_model("synthetic-independent"),
    }
    if not synthetic:
        models = {
            EstimatorStageKind.EMBEDDING_RETRIEVAL: local_model("local-embed"),
            EstimatorStageKind.RERANKER: local_model("local-rerank"),
            EstimatorStageKind.SPECIALIST: local_model("local-specialist"),
            EstimatorStageKind.SECOND_OPINION: local_model("local-independent"),
        }
    ordered = (
        EstimatorStageKind.OBJECTIVE_EVIDENCE,
        EstimatorStageKind.BM25_RETRIEVAL,
        EstimatorStageKind.EMBEDDING_RETRIEVAL,
        EstimatorStageKind.RERANKER,
        EstimatorStageKind.SPECIALIST,
        EstimatorStageKind.SECOND_OPINION,
        EstimatorStageKind.HUMAN_ADJUDICATION,
    )
    result: list[EstimatorStage] = []
    for ordinal, kind in enumerate(ordered, start=1):
        condition = StageCondition.ALWAYS
        if kind is EstimatorStageKind.SECOND_OPINION:
            condition = (
                StageCondition.DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE
            )
        elif kind is EstimatorStageKind.HUMAN_ADJUDICATION:
            condition = StageCondition.UNRESOLVED_DISAGREEMENT
        result.append(
            EstimatorStage(
                ordinal=ordinal,
                kind=kind,
                condition=condition,
                component_version=f"component-{ordinal}",
                configuration_sha256=digest(f"configuration-{ordinal}"),
                output_schema_version=f"stage-output-{ordinal}",
                model_artifact=models.get(kind),
                candidate_family_key=(f"family-{ordinal}" if not synthetic and kind in models else None),
            )
        )
    return tuple(result)


def synthetic_plan(**changes: Any) -> EstimatorPlan:
    values: dict[str, Any] = {
        "plan_key": "balanced-quality",
        "plan_version": "plan-1",
        "route": EstimatorRoute.BALANCED,
        "question_specs": (question(),),
        "evidence_packet_schema_version": "evidence-packet-1",
        "provider_schemas": (
            ProviderSchemaIdentity(
                provider=Provider.SYNTHETIC,
                adapter_version="adapter-1",
                provider_schema_version="provider-schema-1",
            ),
        ),
        "preprocessing_version": "preprocessing-1",
        "preprocessing_sha256": digest("preprocessing"),
        "reasoning_effort": EstimatorReasoningEffort.MAX,
        "calibration_version": "calibration-1",
        "calibration_sha256": digest("calibration"),
        "router_version": "router-1",
        "router_sha256": digest("router"),
        "redactor_version": "redactor-1",
        "redactor_sha256": digest("redactor"),
        "stages": stages(),
    }
    values.update(changes)
    return EstimatorPlan(**values)


def execution(
    destination: ExecutionDestination,
    *,
    retention_class: RetentionClass | None = None,
) -> ExecutionDisclosure:
    remote = destination in {
        ExecutionDestination.OPENAI_API,
        ExecutionDestination.ANTHROPIC_API,
        ExecutionDestination.CODEX_CLI,
        ExecutionDestination.CLAUDE_API,
    }
    if retention_class is None:
        retention_class = {
            ExecutionDestination.LOCAL_DEVICE: RetentionClass.LOCAL_EPHEMERAL,
            ExecutionDestination.MANUAL_IMPORT: RetentionClass.MANUAL_EXPORT,
            ExecutionDestination.SYNTHETIC_TEST: RetentionClass.SYNTHETIC,
        }.get(destination, RetentionClass.PROVIDER_ZERO_DAY)
    days = {
        RetentionClass.LOCAL_EPHEMERAL: 0,
        RetentionClass.PROVIDER_ZERO_DAY: 0,
        RetentionClass.PROVIDER_30_DAY: 30,
        RetentionClass.SYNTHETIC: 0,
        RetentionClass.MANUAL_EXPORT: None,
        RetentionClass.PROVIDER_DISCLOSED_OTHER: 45,
    }[retention_class]
    return ExecutionDisclosure(
        destination=destination,
        retention_class=retention_class,
        retention_days=days,
        disclosure_version="disclosure-1",
        approval_receipt_id=digest("approval") if remote else None,
        retention_acknowledged=remote,
    )


def stage_receipt(
    ordinal: int,
    *,
    state: EstimatorStageReceiptState = EstimatorStageReceiptState.COMPLETED,
) -> EstimatorStageReceipt:
    ordered = tuple(EstimatorStageKind)
    started = NOW + timedelta(seconds=ordinal)
    return EstimatorStageReceipt(
        ordinal=ordinal,
        kind=ordered[ordinal - 1],
        state=state,
        outcome_code="stage_complete" if state is not EstimatorStageReceiptState.SKIPPED else "not_needed",
        started_at=None if state is EstimatorStageReceiptState.SKIPPED else started,
        finished_at=(
            None
            if state is EstimatorStageReceiptState.SKIPPED
            else started + timedelta(milliseconds=500)
        ),
    )


def estimator_execution(**changes: Any) -> EstimatorExecution:
    receipts = (stage_receipt(1), stage_receipt(2))
    values: dict[str, Any] = {
        "execution_id": digest("execution"),
        "plan_fingerprint": digest("plan"),
        "evidence_packet_fingerprint": digest("packet"),
        "route": EstimatorRoute.BALANCED,
        "project_id": digest("project"),
        "session_id": digest("session"),
        "state": EstimatorExecutionState.COMPLETED,
        "created_at": NOW,
        "started_at": NOW + timedelta(milliseconds=500),
        "finished_at": NOW + timedelta(seconds=3),
        "stage_receipts": receipts,
        "cascade_stop_stage_ordinal": 2,
        "cascade_stop_stage_kind": EstimatorStageKind.BM25_RETRIEVAL,
        "cascade_stop_reason_code": "sufficient_objective_evidence",
    }
    values.update(changes)
    return EstimatorExecution(**values)


def model_run(
    *,
    model: ModelArtifactIdentity | None = None,
    destination: ExecutionDestination = ExecutionDestination.SYNTHETIC_TEST,
    state: ModelRunState = ModelRunState.COMPLETED,
    **changes: Any,
) -> ModelRun:
    values: dict[str, Any] = {
        "run_id": digest("run"),
        "execution_id": digest("execution"),
        "plan_fingerprint": digest("plan"),
        "evidence_packet_fingerprint": digest("packet"),
        "route": EstimatorRoute.BALANCED,
        "stage_ordinal": 5,
        "stage_kind": EstimatorStageKind.SPECIALIST,
        "model_artifact": model or synthetic_model(),
        "execution": execution(destination),
        "state": state,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=1),
        "cold_start": False,
        "queue_latency_ms": 4,
        "latency_ms": 1000,
        "input_tokens": 20,
        "output_tokens": 3,
        "peak_ram_mib": 256,
        "peak_vram_mib": 0,
        "disk_mib": 32,
        "energy_mwh": None,
        "api_cost_microusd": None,
        "usage_provenance_version": "usage-1",
        "response_schema_version": "response-1",
        "structured_output_valid": state is ModelRunState.COMPLETED,
        "fallback_used": False,
        "refusal_code": "provider_refusal" if state is ModelRunState.REFUSED else None,
        "failure_code": (
            "execution_failed"
            if state not in {ModelRunState.COMPLETED, ModelRunState.REFUSED}
            else None
        ),
    }
    values.update(changes)
    return ModelRun(**values)


def human_judgment(label: str = "judgment-a", **changes: Any) -> ImmutableJudgment:
    values: dict[str, Any] = {
        "judgment_id": digest(label),
        "source": JudgmentSource.HUMAN,
        "adjudicator_id": digest("adjudicator"),
        "annotation_protocol_version": "annotation-1",
        "metric_question_fingerprint": digest("question-fingerprint"),
        "evidence_packet_fingerprint": digest("packet"),
        "metric_key": "quality.requirement_coverage",
        "state": MetricEstimateState.KNOWN,
        "value_kind": MetricValueKind.FRACTION,
        "numeric_value": 0.75,
        "confidence": 0.8,
        "created_at": NOW,
    }
    values.update(changes)
    return ImmutableJudgment(**values)


def test_full_serial_plan_is_canonical_content_free_and_synthetic_only() -> None:
    plan = synthetic_plan()

    assert plan.reasoning_effort is EstimatorReasoningEffort.MAX
    assert tuple(stage.ordinal for stage in plan.stages) == tuple(range(1, 8))
    assert plan.execution_mode == "serial"
    assert plan.model_load_policy == "one_at_a_time"
    assert plan.max_loaded_models == 1
    assert plan.uses_synthetic_model is True
    assert plan.activation_review_eligible is False
    assert len(plan.canonical_fingerprint) == 64
    assert plan.canonical_fingerprint == synthetic_plan().canonical_fingerprint


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("preprocessing_sha256", digest("different-preprocessing")),
        ("reasoning_effort", EstimatorReasoningEffort.XHIGH),
        ("calibration_sha256", digest("different-calibration")),
        ("router_sha256", digest("different-router")),
        ("redactor_sha256", digest("different-redactor")),
        ("evidence_packet_schema_version", "evidence-packet-2"),
    ),
)
def test_plan_fingerprint_covers_complete_estimator_configuration(
    field: str, replacement: object
) -> None:
    baseline = synthetic_plan()
    changed = synthetic_plan(**{field: replacement})

    assert changed.canonical_fingerprint != baseline.canonical_fingerprint


def test_plan_fingerprint_covers_prompt_rubric_and_execution_mode() -> None:
    baseline = synthetic_plan()
    changed_question = question().model_copy(
        update={"prompt_template_sha256": digest("different-template")}
    )
    first_mode = baseline.stages[2].model_artifact
    assert first_mode is not None
    changed_model = first_mode.model_copy(
        update={"requested_execution_mode": ModelExecutionMode.PRO}
    )
    changed_stages = list(baseline.stages)
    changed_stages[2] = changed_stages[2].model_copy(
        update={"model_artifact": changed_model}
    )

    assert (
        synthetic_plan(question_specs=(changed_question,)).canonical_fingerprint
        != baseline.canonical_fingerprint
    )
    assert (
        synthetic_plan(stages=tuple(changed_stages)).canonical_fingerprint
        != baseline.canonical_fingerprint
    )


def test_contract_models_have_no_raw_content_or_chain_of_thought_fields() -> None:
    models: tuple[type[StrictModel], ...] = (
        MetricQuestionSpec,
        EvidencePacketReceipt,
        ModelArtifactIdentity,
        CandidateFamilySelection,
        EstimatorStage,
        EstimatorPlan,
        EstimatorStageReceipt,
        EstimatorExecution,
        ExecutionDisclosure,
        ModelRun,
        ModelVote,
        MetricEstimate,
        ImmutableJudgment,
        Adjudication,
    )
    prohibited = {
        "text",
        "content",
        "prompt_text",
        "prompt_body",
        "transcript",
        "excerpt",
        "source_snippet",
        "evidence_body",
        "model_response",
        "response_body",
        "output_body",
        "rationale",
        "reasoning",
        "chain_of_thought",
        "cot",
    }

    for model in models:
        assert prohibited.isdisjoint(model.model_fields), model.__name__

    with pytest.raises(ValidationError) as error:
        synthetic_plan().model_copy(update={"prompt_text": "must-not-survive"}).__class__(
            **{
                **synthetic_plan().model_dump(),
                "prompt_text": "synthetic-private-canary",
            }
        )
    assert "synthetic-private-canary" not in str(error.value)


@pytest.mark.parametrize(
    ("kind", "lower", "upper"),
    (
        (MetricValueKind.FRACTION, None, None),
        (MetricValueKind.FRACTION, 0.0, 2.0),
        (MetricValueKind.CONTINUOUS, 1.0, 1.0),
        (MetricValueKind.BINARY, 0.0, 1.0),
    ),
)
def test_metric_question_rejects_invalid_bounds(
    kind: MetricValueKind, lower: float | None, upper: float | None
) -> None:
    values = question(value_kind=kind).model_dump()
    values.update(lower_bound=lower, upper_bound=upper)
    with pytest.raises(ValidationError):
        MetricQuestionSpec(**values)


def test_evidence_packet_receipt_is_opaque_canonical_and_ephemeral() -> None:
    refs = tuple(sorted((digest("evidence-a"), digest("evidence-b"))))
    receipt = EvidencePacketReceipt(
        packet_schema_version="packet-1",
        packet_sha256=digest("packet"),
        requirements_sha256=digest("requirements"),
        chronology_sha256=digest("chronology"),
        retrieval_index_sha256=digest("retrieval"),
        provider=Provider.SYNTHETIC,
        adapter_version="adapter-1",
        provider_schema_version="provider-schema-1",
        preprocessing_version="preprocessing-1",
        preprocessing_sha256=digest("preprocessing"),
        redactor_version="redactor-1",
        redactor_sha256=digest("redactor"),
        source_record_count=10,
        requirement_count=2,
        action_count=3,
        decision_count=1,
        feedback_count=1,
        verification_count=2,
        opaque_evidence_refs=refs,
        created_at=NOW,
    )

    assert receipt.ephemeral_payload_retained is False
    assert receipt.opaque_evidence_refs == refs
    assert receipt.canonical_fingerprint != receipt.packet_sha256
    assert receipt.canonical_fingerprint == EvidencePacketReceipt(
        **receipt.model_dump()
    ).canonical_fingerprint
    with pytest.raises(ValidationError):
        EvidencePacketReceipt(**{**receipt.model_dump(), "opaque_evidence_refs": refs[::-1]})
    with pytest.raises(ValidationError):
        EvidencePacketReceipt(**{**receipt.model_dump(), "created_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValidationError):
        EvidencePacketReceipt(**{**receipt.model_dump(), "ephemeral_payload_retained": True})


@pytest.mark.parametrize(
    "unsafe_id",
    (
        "C:/Users/Example/private-model",
        "/private/model",
        "org/../private-model",
        "https://example.test/model",
    ),
)
def test_model_identity_rejects_path_or_uri_shaped_ids(unsafe_id: str) -> None:
    with pytest.raises(ValidationError, match="paths or URIs"):
        synthetic_model(unsafe_id)


def test_model_artifact_requires_pinned_local_hashes_and_disables_remote_code() -> None:
    model = local_model("local-specialist")

    assert model.trust_remote_code is False
    assert model.weight_artifacts[0].file_name == "model.safetensors"
    with pytest.raises(ValidationError):
        ModelArtifactIdentity(
            **{
                **model.model_dump(exclude={"weight_artifacts", "weight_availability"}),
                "weight_availability": ArtifactAvailability.PROVIDER_MANAGED,
            }
        )
    with pytest.raises(ValidationError):
        ModelArtifactIdentity(**{**model.model_dump(), "trust_remote_code": True})


def test_synthetic_model_cannot_claim_weights_or_activation_screening() -> None:
    model = synthetic_model()
    with pytest.raises(ValidationError):
        ModelArtifactIdentity(
            **{
                **model.model_dump(),
                "weight_availability": ArtifactAvailability.PINNED_HASHES,
                "weight_artifacts": (artifact_digest("fabricated-weight"),),
            }
        )
    with pytest.raises(ValidationError):
        CandidateFamilySelection(
            family_key="synthetic-family",
            screened_candidates=(model,),
        )


def test_candidate_family_caps_screening_and_promotion() -> None:
    candidates = tuple(
        sorted(
            (local_model(f"local-candidate-{index}") for index in range(5)),
            key=lambda item: item.canonical_fingerprint,
        )
    )
    promoted = tuple(sorted(item.canonical_fingerprint for item in candidates[:2]))
    selection = CandidateFamilySelection(
        family_key="specialist-family",
        screened_candidates=candidates,
        promoted_artifact_fingerprints=promoted,
        deterministic_baseline_ids=("baseline-1",),
    )

    assert len(selection.screened_candidates) == MAX_SCREENED_CANDIDATES_PER_FAMILY
    assert len(selection.promoted_artifact_fingerprints) == MAX_PROMOTED_CANDIDATES_PER_FAMILY
    extra = local_model("local-candidate-extra")
    too_many = tuple(sorted((*candidates, extra), key=lambda item: item.canonical_fingerprint))
    with pytest.raises(ValidationError):
        CandidateFamilySelection(
            family_key="specialist-family",
            screened_candidates=too_many,
        )
    with pytest.raises(ValidationError):
        CandidateFamilySelection(
            family_key="specialist-family",
            screened_candidates=candidates,
            promoted_artifact_fingerprints=tuple(
                sorted(item.canonical_fingerprint for item in candidates[:3])
            ),
        )


@pytest.mark.parametrize(
    "change",
    (
        {"ordinal": 2},
        {"condition": StageCondition.UNRESOLVED_DISAGREEMENT},
        {"model_artifact": None},
    ),
)
def test_estimator_stage_rejects_wrong_order_condition_or_shape(change: dict[str, object]) -> None:
    stage = stages()[2]
    with pytest.raises(ValidationError):
        EstimatorStage(**{**stage.model_dump(), **change})


def test_plan_requires_independent_second_opinion() -> None:
    plan = synthetic_plan()
    changed = list(plan.stages)
    changed[5] = changed[5].model_copy(
        update={"model_artifact": changed[4].model_artifact}
    )
    with pytest.raises(ValidationError):
        synthetic_plan(stages=tuple(changed))


def test_execution_groups_repeated_runs_without_conflating_plan_or_packet() -> None:
    first = estimator_execution()
    repeat = estimator_execution(execution_id=digest("execution-repeat"))

    assert first.plan_fingerprint == repeat.plan_fingerprint
    assert first.evidence_packet_fingerprint == repeat.evidence_packet_fingerprint
    assert first.execution_id != repeat.execution_id
    assert first.stage_receipts == repeat.stage_receipts
    assert first.cascade_stop_stage_ordinal == 2
    assert first.cascade_stop_stage_kind is EstimatorStageKind.BM25_RETRIEVAL


def test_execution_requires_contiguous_stage_receipts_and_exact_stop_identity() -> None:
    for change in (
        {"stage_receipts": (stage_receipt(2),)},
        {"cascade_stop_stage_ordinal": 1},
        {"cascade_stop_stage_kind": EstimatorStageKind.OBJECTIVE_EVIDENCE},
        {"cascade_stop_reason_code": None},
        {"finished_at": None},
    ):
        with pytest.raises(ValidationError):
            estimator_execution(**change)


def test_execution_lifecycle_and_scope_are_truthful() -> None:
    created = estimator_execution(
        state=EstimatorExecutionState.CREATED,
        started_at=None,
        finished_at=None,
        stage_receipts=(),
        cascade_stop_stage_ordinal=None,
        cascade_stop_stage_kind=None,
        cascade_stop_reason_code=None,
    )
    assert created.stage_receipts == ()
    with pytest.raises(ValidationError):
        estimator_execution(project_id=None)
    with pytest.raises(ValidationError):
        estimator_execution(execution_id=digest("plan"))


def test_stage_receipt_rejects_wrong_kind_timing_and_skipped_execution_claims() -> None:
    completed = stage_receipt(1)
    with pytest.raises(ValidationError):
        EstimatorStageReceipt(**{**completed.model_dump(), "ordinal": 2})
    with pytest.raises(ValidationError):
        EstimatorStageReceipt(
            **{
                **completed.model_dump(),
                "finished_at": completed.started_at - timedelta(milliseconds=1),
            }
        )
    with pytest.raises(ValidationError):
        EstimatorStageReceipt(
            **{
                **completed.model_dump(),
                "state": EstimatorStageReceiptState.SKIPPED,
            }
        )


@pytest.mark.parametrize(
    "destination",
    (
        ExecutionDestination.OPENAI_API,
        ExecutionDestination.ANTHROPIC_API,
        ExecutionDestination.CODEX_CLI,
        ExecutionDestination.CLAUDE_API,
    ),
)
def test_remote_execution_requires_one_shot_approval_and_retention_acknowledgement(
    destination: ExecutionDestination,
) -> None:
    valid = execution(destination)
    assert valid.approval_receipt_id == digest("approval")

    for change in (
        {"approval_receipt_id": None},
        {"retention_acknowledged": False},
        {"retention_days": 30},
    ):
        with pytest.raises(ValidationError):
            ExecutionDisclosure(**{**valid.model_dump(), **change})


def test_manual_claude_import_has_no_remote_approval_or_provider_retention_claim() -> None:
    disclosure = execution(ExecutionDestination.MANUAL_IMPORT)

    assert disclosure.retention_class is RetentionClass.MANUAL_EXPORT
    assert disclosure.retention_days is None
    assert disclosure.approval_receipt_id is None
    with pytest.raises(ValidationError):
        ExecutionDisclosure(**{**disclosure.model_dump(), "retention_days": 30})
    with pytest.raises(ValidationError):
        ExecutionDisclosure(
            **{**disclosure.model_dump(), "approval_receipt_id": digest("approval")}
        )


def test_claude_consumer_cli_is_manual_import_only() -> None:
    cli_model = remote_model(ModelSource.CLAUDE_CLI, "claude-consumer-export")
    manual = model_run(
        model=cli_model,
        destination=ExecutionDestination.MANUAL_IMPORT,
    )

    assert manual.execution.destination is ExecutionDestination.MANUAL_IMPORT
    automated_destinations = (
        ExecutionDestination.LOCAL_DEVICE,
        ExecutionDestination.OPENAI_API,
        ExecutionDestination.ANTHROPIC_API,
        ExecutionDestination.CODEX_CLI,
        ExecutionDestination.CLAUDE_API,
        ExecutionDestination.SYNTHETIC_TEST,
    )
    for destination in automated_destinations:
        with pytest.raises(ValidationError):
            model_run(model=cli_model, destination=destination)


def test_claude_api_requires_anthropic_api_source() -> None:
    api_model = remote_model(ModelSource.ANTHROPIC_API, "claude-api-model")
    run = model_run(model=api_model, destination=ExecutionDestination.CLAUDE_API)

    assert run.model_artifact.source is ModelSource.ANTHROPIC_API
    with pytest.raises(ValidationError):
        model_run(
            model=remote_model(ModelSource.CLAUDE_CLI, "claude-consumer-export"),
            destination=ExecutionDestination.CLAUDE_API,
        )


def test_model_run_records_exact_requested_and_served_mode_fallback() -> None:
    fallback_model = synthetic_model(
        requested_mode=ModelExecutionMode.PRO,
        served_mode=ModelExecutionMode.STANDARD,
    )
    run = model_run(
        model=fallback_model,
        fallback_used=True,
        fallback_reason_code="execution_mode_fallback",
    )

    assert run.model_artifact.requested_execution_mode is ModelExecutionMode.PRO
    assert run.model_artifact.served_execution_mode is ModelExecutionMode.STANDARD
    with pytest.raises(ValidationError):
        model_run(model=fallback_model)


def test_model_run_records_exact_requested_and_served_model_fallback() -> None:
    fallback_model = synthetic_model(
        served_model_id="synthetic-model-b",
        served_revision="revision-2",
    )
    run = model_run(
        model=fallback_model,
        fallback_used=True,
        fallback_reason_code="provider_model_fallback",
    )

    assert run.model_artifact.requested_model_id == "synthetic-model-a"
    assert run.model_artifact.served_model_id == "synthetic-model-b"
    assert run.model_artifact.requested_revision == "revision-1"
    assert run.model_artifact.served_revision == "revision-2"


def test_model_run_preserves_exact_disk_and_throughput_measurement() -> None:
    run = model_run(
        throughput_unit_code="evidence_record",
        measured_unit_count=25,
        throughput_window_ms=2000,
        throughput_provenance_version="throughput-clock-1",
    )

    assert run.disk_mib == 32
    assert run.measured_unit_count == 25
    assert run.throughput_per_second == 12.5
    for missing_field in (
        "throughput_unit_code",
        "measured_unit_count",
        "throughput_window_ms",
        "throughput_provenance_version",
    ):
        invalid = {
            "throughput_unit_code": "evidence_record",
            "measured_unit_count": 25,
            "throughput_window_ms": 2000,
            "throughput_provenance_version": "throughput-clock-1",
            missing_field: None,
        }
        with pytest.raises(ValidationError):
            model_run(**invalid)


@pytest.mark.parametrize(
    "state",
    tuple(ModelRunState),
)
def test_model_run_state_has_exact_structured_result_or_reason(state: ModelRunState) -> None:
    run = model_run(state=state)

    if state is ModelRunState.COMPLETED:
        assert run.structured_output_valid is True
        assert run.refusal_code is None and run.failure_code is None
    elif state is ModelRunState.REFUSED:
        assert run.refusal_code == "provider_refusal"
        assert run.failure_code is None
    else:
        assert run.failure_code == "execution_failed"
        assert run.refusal_code is None


def test_model_run_rejects_invalid_timing_stage_and_success_shape() -> None:
    for change in (
        {"finished_at": NOW - timedelta(seconds=1)},
        {"stage_ordinal": 4},
        {"structured_output_valid": False},
        {"failure_code": "failure_on_success"},
    ):
        with pytest.raises(ValidationError):
            model_run(**change)


def test_model_vote_known_fraction_and_categorical_probability_contracts() -> None:
    common = {
        "vote_id": digest("vote"),
        "execution_id": digest("execution"),
        "model_run_id": digest("run"),
        "plan_fingerprint": digest("plan"),
        "evidence_packet_fingerprint": digest("packet"),
        "metric_question_fingerprint": digest("question-fingerprint"),
        "metric_key": "quality.requirement_coverage",
        "state": MetricEstimateState.KNOWN,
        "confidence": 0.8,
    }
    fraction = ModelVote(
        **common,
        value_kind=MetricValueKind.FRACTION,
        numeric_value=0.75,
    )
    categorical = ModelVote(
        **{**common, "vote_id": digest("categorical-vote")},
        value_kind=MetricValueKind.CATEGORICAL,
        label_code="satisfied",
        probabilities=(
            LabelProbability(label_code="not_satisfied", probability=0.2),
            LabelProbability(label_code="satisfied", probability=0.8),
        ),
    )

    assert fraction.probabilities == ()
    assert sum(item.probability for item in categorical.probabilities) == 1
    with pytest.raises(ValidationError):
        ModelVote(
            **{
                **categorical.model_dump(),
                "probabilities": (
                    {"label_code": "not_satisfied", "probability": 0.4},
                    {"label_code": "satisfied", "probability": 0.4},
                ),
            }
        )


@pytest.mark.parametrize(
    ("state", "reason_field"),
    (
        (MetricEstimateState.UNKNOWN, "unknown_reason_code"),
        (MetricEstimateState.ABSTAINED, "abstention_reason_code"),
        (MetricEstimateState.NOT_APPLICABLE, "not_applicable_reason_code"),
        (MetricEstimateState.FAILED, "failure_code"),
    ),
)
def test_model_vote_unavailable_states_require_one_matching_reason(
    state: MetricEstimateState, reason_field: str
) -> None:
    vote = ModelVote(
        vote_id=digest(f"{state}-vote"),
        execution_id=digest("execution"),
        model_run_id=digest("run"),
        plan_fingerprint=digest("plan"),
        evidence_packet_fingerprint=digest("packet"),
        metric_question_fingerprint=digest("question-fingerprint"),
        metric_key="quality.requirement_coverage",
        state=state,
        value_kind=MetricValueKind.FRACTION,
        **{reason_field: f"{state}_reason"},
    )
    assert vote.confidence is None

    with pytest.raises(ValidationError):
        ModelVote(
            **{
                **vote.model_dump(),
                "confidence": 0.5,
            }
        )


@pytest.mark.parametrize(
    "uncertainty",
    (
        EstimateUncertainty(kind=UncertaintyKind.CONFIDENCE, confidence=0.8),
        EstimateUncertainty(
            kind=UncertaintyKind.INTERVAL,
            lower_bound=0.6,
            upper_bound=0.9,
            confidence_level=0.95,
        ),
        EstimateUncertainty(kind=UncertaintyKind.DISTRIBUTION, entropy=0.3),
        EstimateUncertainty(
            kind=UncertaintyKind.NOT_QUANTIFIED,
            reason_code="insufficient_calibration",
        ),
    ),
)
def test_uncertainty_kinds_are_explicit_and_exclusive(
    uncertainty: EstimateUncertainty,
) -> None:
    assert uncertainty.kind in UncertaintyKind

    conflicting_field = (
        {"entropy": 0.1}
        if uncertainty.kind is UncertaintyKind.CONFIDENCE
        else {"confidence": 0.1}
    )
    with pytest.raises(ValidationError):
        EstimateUncertainty(**{**uncertainty.model_dump(), **conflicting_field})


def test_metric_estimate_preserves_fraction_and_model_vote_provenance() -> None:
    estimate = MetricEstimate(
        estimate_id=digest("estimate"),
        execution_id=digest("execution"),
        plan_fingerprint=digest("plan"),
        evidence_packet_fingerprint=digest("packet"),
        metric_question_fingerprint=digest("question-fingerprint"),
        metric_key="quality.requirement_coverage",
        source=MetricEstimateSource.MODEL_CASCADE,
        state=MetricEstimateState.KNOWN,
        value_kind=MetricValueKind.FRACTION,
        unit_code="ratio",
        numeric_value=0.75,
        numerator=3,
        denominator=4,
        uncertainty=EstimateUncertainty(
            kind=UncertaintyKind.CONFIDENCE,
            confidence=0.8,
        ),
        evidence_coverage=0.7,
        vote_ids=(digest("vote"),),
        created_at=NOW,
    )

    assert estimate.numeric_value == estimate.numerator / estimate.denominator
    with pytest.raises(ValidationError):
        MetricEstimate(**{**estimate.model_dump(), "numeric_value": 0.5})
    with pytest.raises(ValidationError):
        MetricEstimate(**{**estimate.model_dump(), "vote_ids": ()})


def test_metric_estimate_keeps_not_applicable_distinct_from_missing_or_abstained() -> None:
    estimate = MetricEstimate(
        estimate_id=digest("not-applicable-estimate"),
        execution_id=digest("execution"),
        plan_fingerprint=digest("plan"),
        evidence_packet_fingerprint=digest("packet"),
        metric_question_fingerprint=digest("question-fingerprint"),
        metric_key="quality.requirement_coverage",
        source=MetricEstimateSource.OBJECTIVE_EVIDENCE,
        state=MetricEstimateState.NOT_APPLICABLE,
        value_kind=MetricValueKind.FRACTION,
        unit_code="ratio",
        evidence_coverage=1.0,
        not_applicable_reason_code="task_has_no_requirements",
        created_at=NOW,
    )

    assert estimate.state is MetricEstimateState.NOT_APPLICABLE
    assert estimate.unknown_reason_code is None
    assert estimate.abstention_reason_code is None
    with pytest.raises(ValidationError):
        MetricEstimate(
            **{
                **estimate.model_dump(),
                "unknown_reason_code": "missing_evidence",
            }
        )


def test_human_and_objective_judgments_are_distinct_and_models_are_not_ground_truth() -> None:
    human = human_judgment()
    objective = ImmutableJudgment(
        **{
            **human.model_dump(exclude={"adjudicator_id"}),
            "judgment_id": digest("objective-judgment"),
            "source": JudgmentSource.OBJECTIVE_EVIDENCE,
            "objective_evidence_fingerprint": digest("objective-evidence"),
        }
    )

    assert human.adjudicator_id is not None
    assert human.contract_version == IMMUTABLE_JUDGMENT_CONTRACT_VERSION
    assert objective.objective_evidence_fingerprint is not None
    assert set(JudgmentSource) == {
        JudgmentSource.HUMAN,
        JudgmentSource.OBJECTIVE_EVIDENCE,
    }
    with pytest.raises(ValidationError):
        ImmutableJudgment(
            **{
                **human.model_dump(),
                "source": "model_consensus",
            }
        )


def test_adjudication_requires_human_and_exact_selected_judgment() -> None:
    selected = human_judgment()
    resolved = Adjudication(
        adjudication_id=digest("adjudication"),
        plan_fingerprint=digest("plan"),
        reviewed_estimate_id=digest("reviewed-estimate"),
        trigger=AdjudicationTrigger.DISAGREEMENT,
        state=AdjudicationState.RESOLVED,
        judgments=(selected,),
        selected_judgment_id=selected.judgment_id,
        final_state=selected.state,
        final_numeric_value=selected.numeric_value,
        created_at=NOW,
    )

    assert resolved.final_numeric_value == selected.numeric_value
    assert resolved.reviewed_estimate_id == digest("reviewed-estimate")
    assert "estimate_id" not in Adjudication.model_fields
    assert "final_estimate_id" not in Adjudication.model_fields
    with pytest.raises(ValidationError):
        Adjudication(**{**resolved.model_dump(), "final_numeric_value": 0.5})

    objective = ImmutableJudgment(
        **{
            **selected.model_dump(exclude={"adjudicator_id"}),
            "judgment_id": digest("objective-only"),
            "source": JudgmentSource.OBJECTIVE_EVIDENCE,
            "objective_evidence_fingerprint": digest("objective-evidence"),
        }
    )
    with pytest.raises(ValidationError):
        Adjudication(**{**resolved.model_dump(), "judgments": (objective,)})


def test_unresolved_adjudication_has_no_implied_value() -> None:
    unresolved = Adjudication(
        adjudication_id=digest("unresolved-adjudication"),
        plan_fingerprint=digest("plan"),
        reviewed_estimate_id=digest("reviewed-estimate"),
        trigger=AdjudicationTrigger.LOW_CONFIDENCE,
        state=AdjudicationState.UNRESOLVED,
        judgments=(human_judgment(),),
        unresolved_reason_code="human_disagreement",
        created_at=NOW,
    )

    assert unresolved.final_state is None
    assert unresolved.final_numeric_value is None
    with pytest.raises(ValidationError):
        Adjudication(
            **{
                **unresolved.model_dump(),
                "final_state": MetricEstimateState.KNOWN,
                "final_numeric_value": 0.75,
            }
        )


def test_final_human_estimate_is_distinct_and_avoids_circular_ids() -> None:
    reviewed_estimate_id = digest("reviewed-estimate")
    adjudication_id = digest("adjudication")
    final_estimate_id = digest("final-human-estimate")
    bundle = Adjudication(
        adjudication_id=adjudication_id,
        plan_fingerprint=digest("plan"),
        reviewed_estimate_id=reviewed_estimate_id,
        trigger=AdjudicationTrigger.DISAGREEMENT,
        state=AdjudicationState.RESOLVED,
        judgments=(human_judgment(),),
        selected_judgment_id=digest("judgment-a"),
        final_state=MetricEstimateState.KNOWN,
        final_numeric_value=0.75,
        created_at=NOW,
    )
    final_estimate = MetricEstimate(
        estimate_id=final_estimate_id,
        execution_id=digest("execution"),
        plan_fingerprint=digest("plan"),
        evidence_packet_fingerprint=digest("packet"),
        metric_question_fingerprint=digest("question-fingerprint"),
        metric_key="quality.requirement_coverage",
        source=MetricEstimateSource.HUMAN_ADJUDICATED,
        state=MetricEstimateState.KNOWN,
        value_kind=MetricValueKind.FRACTION,
        unit_code="ratio",
        numeric_value=0.75,
        uncertainty=EstimateUncertainty(
            kind=UncertaintyKind.CONFIDENCE,
            confidence=0.8,
        ),
        evidence_coverage=0.7,
        adjudication_id=adjudication_id,
        created_at=NOW + timedelta(seconds=1),
    )

    assert len({reviewed_estimate_id, adjudication_id, final_estimate_id}) == 3
    assert bundle.reviewed_estimate_id == reviewed_estimate_id
    assert final_estimate.adjudication_id == bundle.adjudication_id
    with pytest.raises(ValidationError):
        MetricEstimate(
            **{
                **final_estimate.model_dump(),
                "estimate_id": adjudication_id,
            }
        )
