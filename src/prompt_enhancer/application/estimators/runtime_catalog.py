"""Closed, content-free catalog for reviewed serialized estimator plans.

The catalog stores metadata bindings only.  It performs no filesystem discovery,
imports no runner callable, and accepts no shell command.  A later composition
root may map each reviewed ``executor_key`` to a concrete implementation after
this exact plan, question, and stage validation succeeds.
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from .contracts import (
    MODEL_STAGE_KINDS,
    STAGE_ORDER,
    EstimatorPlan,
    EstimatorRoute,
    EstimatorStageKind,
    MetricQuestionSpec,
    ModelRun,
    ModelRunState,
    ModelSource,
)
from .runtime_contracts import (
    RuntimeAnswerSource,
    RuntimeAuthorizationReceipt,
    RuntimeEvidencePacketReceipt,
    RuntimeExecutionReceipt,
    RuntimeHumanAdjudicationRequestReceipt,
    RuntimeMetricSelection,
    RuntimeQuestionAnswerReceipt,
    RuntimeRetrievalResultReceipt,
    RuntimeSecondOpinionDecisionReceipt,
    RuntimeStageAttemptReceipt,
    RuntimeStageOutcomeReceipt,
    RuntimeResourceReceipt,
    RuntimeStageOutcomeState,
    ValidatedExecutionCommitmentReceipt,
    SecondOpinionDecision,
    estimator_stage_fingerprint,
)


RUNTIME_STAGE_REGISTRATION_VERSION = "runtime-stage-registration-v1"
RUNTIME_PLAN_REGISTRATION_VERSION = "runtime-plan-registration-v1"
RUNTIME_ESTIMATOR_CATALOG_VERSION = "runtime-estimator-catalog-v1"
ROUTE_ORDER = (
    EstimatorRoute.FAST,
    EstimatorRoute.BALANCED,
    EstimatorRoute.DEEP,
)


class RuntimeExecutorInvocation(StrEnum):
    IN_PROCESS = "in_process"
    DIRECT_ARGUMENT_ARRAY = "direct_argument_array"


EXECUTOR_BINDING_BY_STAGE = {
    EstimatorStageKind.OBJECTIVE_EVIDENCE: (
        "objective_evidence.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.BM25_RETRIEVAL: (
        "bm25_retrieval.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.EMBEDDING_RETRIEVAL: (
        "embedding_retrieval.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.RERANKER: (
        "reranker.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.SPECIALIST: (
        "specialist.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.SECOND_OPINION: (
        "second_opinion.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
    EstimatorStageKind.HUMAN_ADJUDICATION: (
        "human_adjudication_queue.v1",
        RuntimeExecutorInvocation.IN_PROCESS,
    ),
}


def _safe_code(value: str) -> str:
    import re

    if re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _safe_version(value: str) -> str:
    import re

    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[/\\]", value) is not None
        or "\\" in value
        or "://" in value
        or ".." in value.split("/")
    ):
        raise ValueError("version identifiers cannot encode paths or URIs")
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


def _canonical_model_digest(model: StrictModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _CatalogStrictModel(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> _CatalogStrictModel:
        if update:
            raise TypeError("validated catalog contracts forbid update-copy bypass")
        return super().model_copy(deep=deep)


class RuntimeStageRegistration(_CatalogStrictModel):
    """Exact metadata binding from one plan stage to a reviewed executor key."""

    contract_version: Literal[RUNTIME_STAGE_REGISTRATION_VERSION] = (
        RUNTIME_STAGE_REGISTRATION_VERSION
    )
    stage_ordinal: int = Field(ge=1, le=len(STAGE_ORDER))
    stage_kind: EstimatorStageKind
    stage_fingerprint: str
    executor_key: str
    component_version: str
    configuration_sha256: str
    input_packet_schema_version: str
    output_schema_version: str
    model_artifact_fingerprint: str | None = None
    invocation_mode: RuntimeExecutorInvocation = RuntimeExecutorInvocation.IN_PROCESS
    shell_interpolation_allowed: Literal[False] = False
    model_load_policy: Literal["one_at_a_time"] = "one_at_a_time"
    max_loaded_models: Literal[1] = 1
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_executor = field_validator("executor_key")(_safe_code)
    _safe_versions = field_validator(
        "component_version", "input_packet_schema_version", "output_schema_version"
    )(_safe_version)
    _safe_digests = field_validator("stage_fingerprint", "configuration_sha256")(
        _digest
    )

    @field_validator("model_artifact_fingerprint")
    @classmethod
    def safe_optional_model(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_stage_shape(self) -> RuntimeStageRegistration:
        if self.stage_kind is not STAGE_ORDER[self.stage_ordinal - 1]:
            raise ValueError("registered stage ordinal must match the cascade")
        if (self.stage_kind in MODEL_STAGE_KINDS) != (
            self.model_artifact_fingerprint is not None
        ):
            raise ValueError("only model executors bind a model artifact")
        if (
            self.executor_key,
            self.invocation_mode,
        ) != EXECUTOR_BINDING_BY_STAGE[self.stage_kind]:
            raise ValueError("executor binding is absent from the code-owned allowlist")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_model_digest(self)


class RuntimePlanRegistration(_CatalogStrictModel):
    """Reviewed exact bindings for all questions and stages of one route plan."""

    contract_version: Literal[RUNTIME_PLAN_REGISTRATION_VERSION] = (
        RUNTIME_PLAN_REGISTRATION_VERSION
    )
    plan: EstimatorPlan
    plan_fingerprint: str
    question_bindings: tuple[RuntimeMetricSelection, ...] = Field(min_length=1)
    stage_registrations: tuple[RuntimeStageRegistration, ...] = Field(
        min_length=len(STAGE_ORDER),
        max_length=len(STAGE_ORDER),
    )
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False
    dynamic_discovery_allowed: Literal[False] = False
    shell_interpolation_allowed: Literal[False] = False

    _safe_plan = field_validator("plan_fingerprint")(_digest)

    @field_validator("question_bindings")
    @classmethod
    def canonical_questions(
        cls, values: tuple[RuntimeMetricSelection, ...]
    ) -> tuple[RuntimeMetricSelection, ...]:
        keys = tuple(item.metric_key for item in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("question bindings must be unique and metric-key sorted")
        return values

    @field_validator("stage_registrations")
    @classmethod
    def canonical_stages(
        cls, values: tuple[RuntimeStageRegistration, ...]
    ) -> tuple[RuntimeStageRegistration, ...]:
        if tuple(item.stage_ordinal for item in values) != tuple(
            range(1, len(STAGE_ORDER) + 1)
        ):
            raise ValueError("stage registrations must cover the complete ordered cascade")
        return values

    @model_validator(mode="after")
    def validate_exact_plan_bindings(self) -> RuntimePlanRegistration:
        EstimatorPlan.model_validate(self.plan.model_dump(mode="python"))
        for binding in self.question_bindings:
            RuntimeMetricSelection.model_validate(binding.model_dump(mode="python"))
        for registration in self.stage_registrations:
            RuntimeStageRegistration.model_validate(
                registration.model_dump(mode="python")
            )
        if self.plan_fingerprint != self.plan.canonical_fingerprint:
            raise ValueError("registered plan fingerprint must match the exact plan")
        if self.plan.execution_mode != "serial":
            raise ValueError("runtime plans must use serialized execution")
        if self.plan.model_load_policy != "one_at_a_time" or self.plan.max_loaded_models != 1:
            raise ValueError("runtime plans may load only one model at a time")

        expected_questions = tuple(
            RuntimeMetricSelection(
                metric_key=question.metric_key,
                metric_question_fingerprint=question.canonical_fingerprint,
            )
            for question in self.plan.question_specs
        )
        if self.question_bindings != expected_questions:
            raise ValueError("question bindings must match every exact plan question hash")

        for stage, registration in zip(
            self.plan.stages,
            self.stage_registrations,
            strict=True,
        ):
            artifact_fingerprint = (
                None
                if stage.model_artifact is None
                else stage.model_artifact.canonical_fingerprint
            )
            exact = (
                registration.stage_ordinal == stage.ordinal
                and registration.stage_kind is stage.kind
                and registration.stage_fingerprint
                == estimator_stage_fingerprint(stage)
                and registration.component_version == stage.component_version
                and registration.configuration_sha256 == stage.configuration_sha256
                and registration.input_packet_schema_version
                == self.plan.evidence_packet_schema_version
                and registration.output_schema_version == stage.output_schema_version
                and registration.model_artifact_fingerprint == artifact_fingerprint
            )
            if not exact:
                raise ValueError("stage registration must match the exact immutable stage")
        return self

    def question_spec(self, metric_key: str) -> MetricQuestionSpec:
        safe_key = _safe_code(metric_key)
        for question in self.plan.question_specs:
            if question.metric_key == safe_key:
                return question
        raise KeyError(f"metric is not registered for route: {safe_key}")

    def stage_registration(self, ordinal: int) -> RuntimeStageRegistration:
        if not 1 <= ordinal <= len(STAGE_ORDER):
            raise KeyError(f"stage ordinal is outside the cascade: {ordinal}")
        return self.stage_registrations[ordinal - 1]

    def validate_packet_receipt(
        self,
        receipt: RuntimeEvidencePacketReceipt,
    ) -> RuntimeEvidencePacketReceipt:
        """Fail closed unless a packet receipt matches this entire plan boundary."""

        RuntimeEvidencePacketReceipt.model_validate(receipt.model_dump(mode="python"))
        question = self.question_spec(receipt.metric_key)
        provider_identity = (
            receipt.provider,
            receipt.adapter_version,
            receipt.provider_schema_version,
        )
        reviewed_provider_identities = {
            (
                identity.provider,
                identity.adapter_version,
                identity.provider_schema_version,
            )
            for identity in self.plan.provider_schemas
        }
        exact = (
            receipt.plan_fingerprint == self.plan_fingerprint
            and receipt.route is self.plan.route
            and receipt.metric_question_fingerprint
            == question.canonical_fingerprint
            and receipt.packet_schema_version
            == self.plan.evidence_packet_schema_version
            and provider_identity in reviewed_provider_identities
            and receipt.preprocessing_version == self.plan.preprocessing_version
            and receipt.preprocessing_sha256 == self.plan.preprocessing_sha256
            and receipt.router_version == self.plan.router_version
            and receipt.router_sha256 == self.plan.router_sha256
            and receipt.redactor_version == self.plan.redactor_version
            and receipt.redactor_sha256 == self.plan.redactor_sha256
        )
        if not exact:
            raise ValueError("packet receipt does not match the exact reviewed plan")
        return receipt

    def build_execution_commitment(
        self,
        execution: RuntimeExecutionReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
    ) -> ValidatedExecutionCommitmentReceipt:
        """Validate lineage and return a disabled proof pending durable consumption."""

        RuntimeExecutionReceipt.model_validate(execution.model_dump(mode="python"))
        RuntimeAuthorizationReceipt.model_validate(
            authorization.model_dump(mode="python")
        )
        if not packet_receipts:
            raise ValueError("executions require at least one selected metric packet")
        for receipt in packet_receipts:
            self.validate_packet_receipt(receipt)
        packet_bindings = tuple(
            RuntimeMetricSelection(
                metric_key=receipt.metric_key,
                metric_question_fingerprint=receipt.metric_question_fingerprint,
            )
            for receipt in packet_receipts
        )
        expected_execution_packets = tuple(
            (
                receipt.metric_key,
                receipt.metric_question_fingerprint,
                receipt.packet_fingerprint,
            )
            for receipt in packet_receipts
        )
        actual_execution_packets = tuple(
            (
                item.metric_key,
                item.metric_question_fingerprint,
                item.evidence_packet_fingerprint,
            )
            for item in execution.metric_packets
        )
        exact = (
            execution.authorization_fingerprint
            == authorization.canonical_fingerprint
            and execution.plan_fingerprint == self.plan_fingerprint
            and execution.route is self.plan.route
            and execution.provider is authorization.provider
            and authorization.plan_fingerprint == self.plan_fingerprint
            and authorization.scope_fingerprint == execution.input_fingerprint
            and authorization.selected_metrics == packet_bindings
            and expected_execution_packets == actual_execution_packets
            and authorization.issued_at <= execution.created_at < authorization.expires_at
        )
        if not exact:
            raise ValueError("execution does not match exact authority and packet scope")
        packet_fingerprints = tuple(
            sorted(receipt.packet_fingerprint for receipt in packet_receipts)
        )
        commitment_seed = {
            "execution_fingerprint": execution.canonical_fingerprint,
            "authorization_fingerprint": authorization.canonical_fingerprint,
            "plan_fingerprint": self.plan_fingerprint,
            "packet_fingerprints": packet_fingerprints,
        }
        commitment_id = hashlib.sha256(
            json.dumps(
                commitment_seed,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return ValidatedExecutionCommitmentReceipt(
            commitment_id=commitment_id,
            execution_fingerprint=execution.canonical_fingerprint,
            authorization_fingerprint=authorization.canonical_fingerprint,
            plan_fingerprint=self.plan_fingerprint,
            route=self.plan.route,
            provider=authorization.provider,
            packet_fingerprints=packet_fingerprints,
            created_at=execution.created_at,
        )

    def validate_stage_attempt(
        self,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        *,
        specialist_answer: RuntimeQuestionAnswerReceipt | None = None,
        second_opinion_decision: RuntimeSecondOpinionDecisionReceipt | None = None,
        second_opinion_answer: RuntimeQuestionAnswerReceipt | None = None,
        human_request: RuntimeHumanAdjudicationRequestReceipt | None = None,
    ) -> RuntimeStageAttemptReceipt:
        """Bind a runtime attempt to reviewed plan, question, packet, and stage hashes."""

        RuntimeStageAttemptReceipt.model_validate(attempt.model_dump(mode="python"))
        self.validate_packet_receipt(packet_receipt)
        RuntimeExecutionReceipt.model_validate(execution.model_dump(mode="python"))
        ValidatedExecutionCommitmentReceipt.model_validate(
            commitment.model_dump(mode="python")
        )
        expected_commitment = self.build_execution_commitment(
            execution,
            authorization,
            packet_receipts,
        )
        if commitment != expected_commitment:
            raise ValueError("execution commitment was not issued from exact authority")
        execution_packets = {
            item.evidence_packet_fingerprint: item for item in execution.metric_packets
        }
        execution_binding = execution_packets.get(packet_receipt.packet_fingerprint)
        registration = self.stage_registration(attempt.stage_ordinal)
        exact = (
            execution_binding is not None
            and attempt.execution_id == execution.execution_id
            and attempt.execution_commitment_fingerprint
            == commitment.canonical_fingerprint
            and attempt.authorization_fingerprint
            == execution.authorization_fingerprint
            and attempt.plan_fingerprint == self.plan_fingerprint
            and attempt.route is execution.route
            and attempt.provider is execution.provider
            and commitment.execution_fingerprint == execution.canonical_fingerprint
            and commitment.authorization_fingerprint
            == execution.authorization_fingerprint
            and commitment.plan_fingerprint == self.plan_fingerprint
            and commitment.route is self.plan.route
            and commitment.provider is execution.provider
            and packet_receipt.packet_fingerprint in commitment.packet_fingerprints
            and commitment.runtime_enabled is False
            and commitment.consumption_enforced is False
            and attempt.metric_key == packet_receipt.metric_key
            and attempt.metric_question_fingerprint
            == packet_receipt.metric_question_fingerprint
            and attempt.evidence_packet_fingerprint
            == packet_receipt.packet_fingerprint
            and attempt.stage_kind is registration.stage_kind
            and attempt.stage_fingerprint == registration.stage_fingerprint
            and attempt.stage_registration_fingerprint
            == registration.canonical_fingerprint
            and attempt.model_artifact_fingerprint
            == registration.model_artifact_fingerprint
        )
        if not exact:
            raise ValueError("stage attempt does not match the exact reviewed bindings")

        gate_values = (
            specialist_answer,
            second_opinion_decision,
            second_opinion_answer,
            human_request,
        )
        if attempt.stage_kind is EstimatorStageKind.SECOND_OPINION:
            if specialist_answer is None or second_opinion_decision is None:
                raise ValueError("second-opinion attempts require an exact trigger receipt")
            if second_opinion_answer is not None or human_request is not None:
                raise ValueError("second-opinion attempts cannot claim human-gate output")
            RuntimeQuestionAnswerReceipt.model_validate(
                specialist_answer.model_dump(mode="python")
            )
            RuntimeSecondOpinionDecisionReceipt.model_validate(
                second_opinion_decision.model_dump(mode="python")
            )
            gate_exact = (
                specialist_answer.stage_kind is EstimatorStageKind.SPECIALIST
                and specialist_answer.execution_id == attempt.execution_id
                and specialist_answer.plan_fingerprint == attempt.plan_fingerprint
                and specialist_answer.evidence_packet_fingerprint
                == packet_receipt.packet_fingerprint
                and specialist_answer.metric_question_fingerprint
                == packet_receipt.metric_question_fingerprint
                and second_opinion_decision.decision
                is SecondOpinionDecision.TRIGGER
                and second_opinion_decision.execution_id == attempt.execution_id
                and second_opinion_decision.plan_fingerprint
                == attempt.plan_fingerprint
                and second_opinion_decision.metric_question_fingerprint
                == attempt.metric_question_fingerprint
                and second_opinion_decision.evidence_packet_fingerprint
                == packet_receipt.packet_fingerprint
                and second_opinion_decision.specialist_attempt_id
                == specialist_answer.attempt_id
                and second_opinion_decision.specialist_answer_fingerprint
                == specialist_answer.canonical_fingerprint
            )
            if not gate_exact:
                raise ValueError("second-opinion trigger lineage does not match")
        elif attempt.stage_kind is EstimatorStageKind.HUMAN_ADJUDICATION:
            if any(value is None for value in gate_values):
                raise ValueError("human attempts require an unresolved-disagreement request")
            assert specialist_answer is not None
            assert second_opinion_decision is not None
            assert second_opinion_answer is not None
            assert human_request is not None
            RuntimeQuestionAnswerReceipt.model_validate(
                specialist_answer.model_dump(mode="python")
            )
            RuntimeQuestionAnswerReceipt.model_validate(
                second_opinion_answer.model_dump(mode="python")
            )
            RuntimeSecondOpinionDecisionReceipt.model_validate(
                second_opinion_decision.model_dump(mode="python")
            )
            RuntimeHumanAdjudicationRequestReceipt.model_validate(
                human_request.model_dump(mode="python")
            )
            gate_exact = (
                specialist_answer.stage_kind is EstimatorStageKind.SPECIALIST
                and second_opinion_answer.stage_kind
                is EstimatorStageKind.SECOND_OPINION
                and specialist_answer.execution_id == attempt.execution_id
                and second_opinion_answer.execution_id == attempt.execution_id
                and second_opinion_decision.execution_id == attempt.execution_id
                and second_opinion_decision.decision
                is SecondOpinionDecision.TRIGGER
                and human_request.execution_id == attempt.execution_id
                and human_request.plan_fingerprint == attempt.plan_fingerprint
                and human_request.metric_question_fingerprint
                == attempt.metric_question_fingerprint
                and human_request.evidence_packet_fingerprint
                == packet_receipt.packet_fingerprint
                and human_request.human_stage_registration_fingerprint
                == registration.canonical_fingerprint
                and human_request.second_opinion_decision_fingerprint
                == second_opinion_decision.canonical_fingerprint
                and human_request.specialist_answer_fingerprint
                == specialist_answer.canonical_fingerprint
                and human_request.second_opinion_answer_fingerprint
                == second_opinion_answer.canonical_fingerprint
            )
            if not gate_exact:
                raise ValueError("human-adjudication request lineage does not match")
        elif any(value is not None for value in gate_values):
            raise ValueError("unconditional stages cannot consume conditional gate receipts")
        return attempt

    def validate_retrieval_result(
        self,
        result: RuntimeRetrievalResultReceipt,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        upstream_result: RuntimeRetrievalResultReceipt | None = None,
    ) -> RuntimeRetrievalResultReceipt:
        """Bind ranked opaque references to the exact reviewed packet and attempt."""

        RuntimeRetrievalResultReceipt.model_validate(result.model_dump(mode="python"))
        self.validate_stage_attempt(
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
        )
        exact = (
            result.execution_id == attempt.execution_id
            and result.execution_commitment_fingerprint
            == commitment.canonical_fingerprint
            and result.attempt_id == attempt.attempt_id
            and result.plan_fingerprint == attempt.plan_fingerprint
            and result.stage_fingerprint == attempt.stage_fingerprint
            and result.evidence_packet_fingerprint
            == packet_receipt.packet_fingerprint
            and result.metric_question_fingerprint
            == packet_receipt.metric_question_fingerprint
            and result.metric_key == packet_receipt.metric_key
            and result.stage_kind is attempt.stage_kind
        )
        if result.stage_kind is EstimatorStageKind.BM25_RETRIEVAL:
            exact = exact and (
                upstream_result is None
                and result.query_fingerprint
                == packet_receipt.retrieval_query_fingerprint
                and result.candidate_index_fingerprint
                == packet_receipt.retrieval_index_sha256
                and result.candidate_reference_ids
                == packet_receipt.opaque_evidence_refs
            )
        else:
            if upstream_result is None:
                raise ValueError("later retrieval stages require an upstream result")
            RuntimeRetrievalResultReceipt.model_validate(
                upstream_result.model_dump(mode="python")
            )
            expected_upstream_kind = {
                EstimatorStageKind.EMBEDDING_RETRIEVAL: (
                    EstimatorStageKind.BM25_RETRIEVAL
                ),
                EstimatorStageKind.RERANKER: EstimatorStageKind.EMBEDDING_RETRIEVAL,
            }[result.stage_kind]
            upstream_refs = tuple(
                sorted(hit.evidence_reference_id for hit in upstream_result.hits)
            )
            upstream_index_fingerprint = hashlib.sha256(
                json.dumps(
                    upstream_refs,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            exact = exact and (
                upstream_result.stage_kind is expected_upstream_kind
                and upstream_result.execution_id == attempt.execution_id
                and upstream_result.plan_fingerprint == attempt.plan_fingerprint
                and upstream_result.evidence_packet_fingerprint
                == packet_receipt.packet_fingerprint
                and result.upstream_result_fingerprint
                == upstream_result.canonical_fingerprint
                and result.query_fingerprint == upstream_result.query_fingerprint
                and result.candidate_index_fingerprint
                == upstream_index_fingerprint
                and result.candidate_reference_ids == upstream_refs
            )
        if not exact:
            raise ValueError("retrieval result does not match the exact packet and stage")
        return result

    def validate_question_answer(
        self,
        answer: RuntimeQuestionAnswerReceipt,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        model_run: ModelRun | None = None,
    ) -> RuntimeQuestionAnswerReceipt:
        """Validate execution lineage and value shape without claiming quality."""

        RuntimeQuestionAnswerReceipt.model_validate(answer.model_dump(mode="python"))
        self.validate_stage_attempt(
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
        )
        question = self.question_spec(packet_receipt.metric_key)
        exact = (
            answer.execution_id == attempt.execution_id
            and answer.attempt_id == attempt.attempt_id
            and answer.plan_fingerprint == attempt.plan_fingerprint
            and answer.stage_fingerprint == attempt.stage_fingerprint
            and answer.evidence_packet_fingerprint
            == packet_receipt.packet_fingerprint
            and answer.metric_question_fingerprint
            == question.canonical_fingerprint
            and answer.metric_key == question.metric_key
            and answer.stage_kind is attempt.stage_kind
            and answer.value_kind is question.value_kind
            and set(answer.opaque_evidence_refs).issubset(
                packet_receipt.opaque_evidence_refs
            )
        )
        artifact = self.plan.stages[attempt.stage_ordinal - 1].model_artifact
        if artifact is not None:
            expected_source = {
                ModelSource.LOCAL_WEIGHTS: RuntimeAnswerSource.LOCAL_MODEL_RAW,
                ModelSource.SYNTHETIC: RuntimeAnswerSource.SYNTHETIC_MODEL_RAW,
                ModelSource.OPENAI_API: RuntimeAnswerSource.REMOTE_MODEL_RAW,
                ModelSource.ANTHROPIC_API: RuntimeAnswerSource.REMOTE_MODEL_RAW,
                ModelSource.CODEX_CLI: RuntimeAnswerSource.REMOTE_MODEL_RAW,
                ModelSource.CLAUDE_CLI: RuntimeAnswerSource.REMOTE_MODEL_RAW,
            }[artifact.source]
            exact = exact and answer.source is expected_source
            if model_run is None:
                raise ValueError("model answers require the exact model-run receipt")
            ModelRun.model_validate(model_run.model_dump(mode="python"))
            registration = self.stage_registration(attempt.stage_ordinal)
            exact = exact and (
                answer.model_run_id == model_run.run_id
                and model_run.execution_id == attempt.execution_id
                and model_run.plan_fingerprint == attempt.plan_fingerprint
                and model_run.evidence_packet_fingerprint
                == packet_receipt.packet_fingerprint
                and model_run.route is self.plan.route
                and model_run.stage_ordinal == attempt.stage_ordinal
                and model_run.stage_kind is attempt.stage_kind
                and model_run.model_artifact.canonical_fingerprint
                == registration.model_artifact_fingerprint
                and model_run.state is ModelRunState.COMPLETED
                and model_run.structured_output_valid
                and model_run.response_schema_version
                == registration.output_schema_version
            )
        elif model_run is not None:
            raise ValueError("non-model answers cannot claim a model-run receipt")
        if not exact:
            raise ValueError("runtime answer does not match the exact packet and stage")
        if answer.numeric_value is not None and (
            question.lower_bound is None
            or question.upper_bound is None
            or not question.lower_bound
            <= answer.numeric_value
            <= question.upper_bound
        ):
            raise ValueError("runtime answer is outside the documented metric bounds")
        return answer

    def validate_stage_outcome(
        self,
        outcome: RuntimeStageOutcomeReceipt,
        attempt: RuntimeStageAttemptReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        packet_receipt: RuntimeEvidencePacketReceipt,
        resource_receipt: RuntimeResourceReceipt,
        output_receipt: (
            RuntimeQuestionAnswerReceipt
            | RuntimeRetrievalResultReceipt
            | RuntimeHumanAdjudicationRequestReceipt
            | RuntimeSecondOpinionDecisionReceipt
            | None
        ),
    ) -> RuntimeStageOutcomeReceipt:
        """Bind terminal stage state to exact resource and typed output receipts."""

        RuntimeStageOutcomeReceipt.model_validate(outcome.model_dump(mode="python"))
        RuntimeResourceReceipt.model_validate(
            resource_receipt.model_dump(mode="python")
        )
        if outcome.state is RuntimeStageOutcomeState.COMPLETED:
            raise ValueError(
                "terminal completion is disabled until durable consumption exists"
            )
        self.validate_stage_attempt(
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
        )
        exact = (
            outcome.attempt_id == attempt.attempt_id
            and outcome.execution_id == attempt.execution_id
            and outcome.execution_commitment_fingerprint
            == commitment.canonical_fingerprint
            and outcome.plan_fingerprint == attempt.plan_fingerprint
            and outcome.metric_question_fingerprint
            == attempt.metric_question_fingerprint
            and outcome.stage_fingerprint == attempt.stage_fingerprint
            and outcome.stage_registration_fingerprint
            == attempt.stage_registration_fingerprint
            and resource_receipt.attempt_id == attempt.attempt_id
            and resource_receipt.stage_fingerprint == attempt.stage_fingerprint
            and outcome.resource_receipt_fingerprint
            == resource_receipt.canonical_fingerprint
        )
        if outcome.state is RuntimeStageOutcomeState.COMPLETED:
            if output_receipt is None:
                raise ValueError("completed outcomes require an exact typed output")
            output_fingerprint = output_receipt.canonical_fingerprint
            expected_kind = {
                RuntimeQuestionAnswerReceipt: "question_answer",
                RuntimeRetrievalResultReceipt: "retrieval_result",
                RuntimeHumanAdjudicationRequestReceipt: "human_request",
                RuntimeSecondOpinionDecisionReceipt: "second_opinion_decision",
            }.get(type(output_receipt))
            exact = exact and (
                outcome.output_fingerprint == output_fingerprint
                and outcome.output_kind == expected_kind
            )
        elif output_receipt is not None:
            raise ValueError("non-completed outcomes cannot claim stage output")
        if not exact:
            raise ValueError("stage outcome does not match exact execution lineage")
        return outcome


class RuntimeEstimatorCatalog(_CatalogStrictModel):
    """Closed Fast/Balanced/Deep catalog; all entries remain execution-only."""

    contract_version: Literal[RUNTIME_ESTIMATOR_CATALOG_VERSION] = (
        RUNTIME_ESTIMATOR_CATALOG_VERSION
    )
    registrations: tuple[RuntimePlanRegistration, ...] = Field(
        min_length=len(ROUTE_ORDER),
        max_length=len(ROUTE_ORDER),
    )
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False
    dynamic_discovery_allowed: Literal[False] = False

    @field_validator("registrations")
    @classmethod
    def complete_routes(
        cls, values: tuple[RuntimePlanRegistration, ...]
    ) -> tuple[RuntimePlanRegistration, ...]:
        if tuple(item.plan.route for item in values) != ROUTE_ORDER:
            raise ValueError("catalog must contain Fast, Balanced, and Deep in order")
        fingerprints = tuple(item.plan_fingerprint for item in values)
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("each runtime route requires a distinct plan fingerprint")
        return values

    @model_validator(mode="after")
    def compatible_metric_questions(self) -> RuntimeEstimatorCatalog:
        for registration in self.registrations:
            RuntimePlanRegistration.model_validate(
                registration.model_dump(mode="python")
            )
        expected = self.registrations[0].question_bindings
        if any(
            registration.question_bindings != expected
            for registration in self.registrations[1:]
        ):
            raise ValueError("all routes must bind the same exact metric questions")
        return self

    def plan_for_route(self, route: EstimatorRoute) -> RuntimePlanRegistration:
        return self.registrations[ROUTE_ORDER.index(route)]

    def question_for_route(
        self,
        route: EstimatorRoute,
        metric_key: str,
    ) -> MetricQuestionSpec:
        return self.plan_for_route(route).question_spec(metric_key)

    def stage_for_route(
        self,
        route: EstimatorRoute,
        ordinal: int,
    ) -> RuntimeStageRegistration:
        return self.plan_for_route(route).stage_registration(ordinal)

    def validate_stage_attempt(
        self,
        route: EstimatorRoute,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        *,
        specialist_answer: RuntimeQuestionAnswerReceipt | None = None,
        second_opinion_decision: RuntimeSecondOpinionDecisionReceipt | None = None,
        second_opinion_answer: RuntimeQuestionAnswerReceipt | None = None,
        human_request: RuntimeHumanAdjudicationRequestReceipt | None = None,
    ) -> RuntimeStageAttemptReceipt:
        return self.plan_for_route(route).validate_stage_attempt(
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
            specialist_answer=specialist_answer,
            second_opinion_decision=second_opinion_decision,
            second_opinion_answer=second_opinion_answer,
            human_request=human_request,
        )

    def validate_retrieval_result(
        self,
        route: EstimatorRoute,
        result: RuntimeRetrievalResultReceipt,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        upstream_result: RuntimeRetrievalResultReceipt | None = None,
    ) -> RuntimeRetrievalResultReceipt:
        return self.plan_for_route(route).validate_retrieval_result(
            result,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
            upstream_result,
        )

    def validate_question_answer(
        self,
        route: EstimatorRoute,
        answer: RuntimeQuestionAnswerReceipt,
        attempt: RuntimeStageAttemptReceipt,
        packet_receipt: RuntimeEvidencePacketReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        model_run: ModelRun | None = None,
    ) -> RuntimeQuestionAnswerReceipt:
        return self.plan_for_route(route).validate_question_answer(
            answer,
            attempt,
            packet_receipt,
            execution,
            commitment,
            authorization,
            packet_receipts,
            model_run,
        )

    def validate_stage_outcome(
        self,
        route: EstimatorRoute,
        outcome: RuntimeStageOutcomeReceipt,
        attempt: RuntimeStageAttemptReceipt,
        execution: RuntimeExecutionReceipt,
        commitment: ValidatedExecutionCommitmentReceipt,
        authorization: RuntimeAuthorizationReceipt,
        packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...],
        packet_receipt: RuntimeEvidencePacketReceipt,
        resource_receipt: RuntimeResourceReceipt,
        output_receipt: (
            RuntimeQuestionAnswerReceipt
            | RuntimeRetrievalResultReceipt
            | RuntimeHumanAdjudicationRequestReceipt
            | RuntimeSecondOpinionDecisionReceipt
            | None
        ),
    ) -> RuntimeStageOutcomeReceipt:
        return self.plan_for_route(route).validate_stage_outcome(
            outcome,
            attempt,
            execution,
            commitment,
            authorization,
            packet_receipts,
            packet_receipt,
            resource_receipt,
            output_receipt,
        )


__all__ = [
    "ROUTE_ORDER",
    "RuntimeExecutorInvocation",
    "RuntimeEstimatorCatalog",
    "RuntimePlanRegistration",
    "RuntimeStageRegistration",
]
