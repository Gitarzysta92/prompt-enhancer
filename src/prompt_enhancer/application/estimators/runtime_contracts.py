"""Execution-only contracts for the serialized estimator runtime.

This module is deliberately separate from calibration and product metric contracts.
Its receipts prove what was attempted, with which immutable plan/question/stage
identities, and which resource measurements were or were not available.  A
runtime answer is never a calibrated estimate and can never activate a metric.

All identifiers, fingerprints, labels, and reasons are content-free.  Evidence
text belongs only in :mod:`evidence_packets` and must not cross this boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .contracts import (
    MODEL_STAGE_KINDS,
    STAGE_ORDER,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    ExecutionDestination,
    MetricEstimateState,
    MetricValueKind,
    REMOTE_DESTINATIONS,
)


RUNTIME_AUTHORIZATION_RECEIPT_VERSION = "runtime-authorization-receipt-v1"
RUNTIME_EVIDENCE_PACKET_RECEIPT_VERSION = "runtime-evidence-packet-receipt-v1"
RUNTIME_EXECUTION_RECEIPT_VERSION = "runtime-execution-receipt-v1"
VALIDATED_EXECUTION_COMMITMENT_VERSION = "validated-execution-commitment-v1"
RUNTIME_STAGE_ATTEMPT_RECEIPT_VERSION = "runtime-stage-attempt-receipt-v1"
RUNTIME_STAGE_OUTCOME_RECEIPT_VERSION = "runtime-stage-outcome-receipt-v1"
RUNTIME_RESOURCE_RECEIPT_VERSION = "runtime-resource-receipt-v1"
RUNTIME_RETRIEVAL_RESULT_RECEIPT_VERSION = "runtime-retrieval-result-receipt-v1"
RUNTIME_CHECKPOINT_RECEIPT_VERSION = "runtime-checkpoint-receipt-v1"
RUNTIME_QUESTION_ANSWER_RECEIPT_VERSION = "runtime-question-answer-receipt-v1"
RUNTIME_SECOND_OPINION_DECISION_VERSION = "runtime-second-opinion-decision-v1"
RUNTIME_HUMAN_ADJUDICATION_REQUEST_VERSION = (
    "runtime-human-adjudication-request-v1"
)

MAX_RUNTIME_METRICS = 100
MAX_RUNTIME_EVIDENCE_REFS = 512
SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _safe_code(value: str) -> str:
    if SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _safe_version(value: str) -> str:
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _canonical_digest(model: StrictModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def estimator_stage_fingerprint(stage: EstimatorStage) -> str:
    """Return the exact canonical hash of one immutable plan stage."""

    return _canonical_digest(stage)


def _canonical_digests(values: tuple[str, ...]) -> tuple[str, ...]:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("digests must be unique and sorted")
    return tuple(_digest(value) for value in values)


class _RuntimeStrictModel(StrictModel):
    """Revalidate copied nested receipts at every runtime boundary."""

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
    ) -> _RuntimeStrictModel:
        if update:
            raise TypeError("validated runtime contracts forbid update-copy bypass")
        return super().model_copy(deep=deep)


class RuntimeAuthorizationKind(StrEnum):
    MANUAL_ONCE = "manual_once"
    AUTOMATION_GRANT = "automation_grant"
    SYNTHETIC_TEST = "synthetic_test"


class RuntimeExecutionState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


TERMINAL_RUNTIME_STATES = frozenset(
    {
        RuntimeExecutionState.COMPLETED,
        RuntimeExecutionState.PARTIAL,
        RuntimeExecutionState.FAILED,
        RuntimeExecutionState.CANCELLED,
        RuntimeExecutionState.SUPERSEDED,
    }
)


class RuntimeStageOutcomeState(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_HUMAN = "awaiting_human"


class ResourceMeasurementState(StrEnum):
    KNOWN = "known"
    UNSUPPORTED = "unsupported"
    NOT_COLLECTED = "not_collected"
    FAILED = "failed"


class RuntimeAnswerSource(StrEnum):
    OBJECTIVE_EVIDENCE = "objective_evidence"
    DETERMINISTIC_RULE = "deterministic_rule"
    LOCAL_MODEL_RAW = "local_model_raw"
    REMOTE_MODEL_RAW = "remote_model_raw"
    SYNTHETIC_MODEL_RAW = "synthetic_model_raw"
    HUMAN_ADJUDICATION = "human_adjudication"


class RuntimeRetrievalScoreKind(StrEnum):
    BM25_RAW = "bm25_raw"
    EMBEDDING_SIMILARITY_RAW = "embedding_similarity_raw"
    RERANKER_RAW = "reranker_raw"


class RawModelScoreState(StrEnum):
    KNOWN = "known"
    NOT_PROVIDED = "not_provided"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class TriggerSignalState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class SecondOpinionSignalKind(StrEnum):
    AUDIT = "audit"
    DISAGREEMENT = "disagreement"
    DRIFT = "drift"
    HIGH_VALUE = "high_value"
    LOW_RAW_SCORE = "low_raw_score"


SECOND_OPINION_SIGNAL_ORDER = tuple(
    sorted(SecondOpinionSignalKind, key=lambda item: item.value)
)


class SecondOpinionDecision(StrEnum):
    TRIGGER = "trigger"
    DO_NOT_TRIGGER = "do_not_trigger"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RuntimeMetricSelection(_RuntimeStrictModel):
    metric_key: str
    metric_question_fingerprint: str

    _safe_metric = field_validator("metric_key")(_safe_code)
    _safe_question = field_validator("metric_question_fingerprint")(_digest)


class RuntimeMetricPacketBinding(RuntimeMetricSelection):
    evidence_packet_fingerprint: str

    _safe_packet = field_validator("evidence_packet_fingerprint")(_digest)


class RuntimeAuthorizationReceipt(_RuntimeStrictModel):
    """Content-free authority binding for exactly one runtime scope and plan."""

    contract_version: Literal[RUNTIME_AUTHORIZATION_RECEIPT_VERSION] = (
        RUNTIME_AUTHORIZATION_RECEIPT_VERSION
    )
    authorization_id: str
    kind: RuntimeAuthorizationKind
    provider: Provider
    destination: ExecutionDestination
    plan_fingerprint: str
    scope_fingerprint: str
    selected_metrics: tuple[RuntimeMetricSelection, ...] = Field(
        min_length=1,
        max_length=MAX_RUNTIME_METRICS,
    )
    issued_at: datetime
    expires_at: datetime
    one_shot: bool
    content_free: Literal[True] = True
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    runtime_enabled: Literal[False] = False
    disabled_reason: Literal["durable_consumption_not_implemented"] = (
        "durable_consumption_not_implemented"
    )
    consumption_enforced: Literal[False] = False

    _safe_ids = field_validator(
        "authorization_id", "plan_fingerprint", "scope_fingerprint"
    )(_digest)
    _utc_times = field_validator("issued_at", "expires_at")(_utc)

    @field_validator("selected_metrics")
    @classmethod
    def canonical_metrics(
        cls, values: tuple[RuntimeMetricSelection, ...]
    ) -> tuple[RuntimeMetricSelection, ...]:
        keys = tuple(item.metric_key for item in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("selected metrics must be unique and metric-key sorted")
        return values

    @model_validator(mode="after")
    def validate_authority(self) -> RuntimeAuthorizationReceipt:
        if self.expires_at <= self.issued_at:
            raise ValueError("runtime authority must expire after it is issued")
        if self.kind is RuntimeAuthorizationKind.AUTOMATION_GRANT:
            if self.one_shot:
                raise ValueError("automation grants are renewable, not one-shot")
            if self.destination in REMOTE_DESTINATIONS:
                raise ValueError("automation grants cannot authorize remote execution")
        elif not self.one_shot:
            raise ValueError("manual and synthetic authority must be one-shot")
        if self.kind is RuntimeAuthorizationKind.SYNTHETIC_TEST:
            if self.provider is not Provider.SYNTHETIC:
                raise ValueError("synthetic authority requires the synthetic provider")
            if self.destination is not ExecutionDestination.SYNTHETIC_TEST:
                raise ValueError("synthetic authority requires the synthetic destination")
        elif self.provider is Provider.SYNTHETIC:
            raise ValueError("real authority cannot claim the synthetic provider")
        allowed_destinations = {
            Provider.SYNTHETIC: {ExecutionDestination.SYNTHETIC_TEST},
            Provider.CODEX: {
                ExecutionDestination.LOCAL_DEVICE,
                ExecutionDestination.CODEX_CLI,
            },
            Provider.CLAUDE_CODE: {
                ExecutionDestination.LOCAL_DEVICE,
                ExecutionDestination.ANTHROPIC_API,
                ExecutionDestination.CLAUDE_API,
                ExecutionDestination.MANUAL_IMPORT,
            },
        }
        if self.destination not in allowed_destinations[self.provider]:
            raise ValueError("provider and execution destination are incompatible")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeEvidencePacketReceipt(_RuntimeStrictModel):
    """Persistable receipt for an ephemeral, selected-metric evidence packet."""

    contract_version: Literal[RUNTIME_EVIDENCE_PACKET_RECEIPT_VERSION] = (
        RUNTIME_EVIDENCE_PACKET_RECEIPT_VERSION
    )
    packet_schema_version: str
    packet_fingerprint: str
    plan_fingerprint: str
    metric_key: str
    metric_question_fingerprint: str
    route: EstimatorRoute
    scope_projection_fingerprint: str
    scope_router_output_fingerprint: str
    retrieval_query_fingerprint: str
    requirements_sha256: str
    chronology_sha256: str
    retrieval_index_sha256: str
    provider: Provider
    adapter_version: str
    provider_schema_version: str
    preprocessing_version: str
    preprocessing_sha256: str
    router_version: str
    router_sha256: str
    redactor_version: str
    redactor_sha256: str
    source_record_count: int = Field(ge=0, le=10_000_000)
    requirement_count: int = Field(ge=0, le=1_000_000)
    chronology_count: int = Field(ge=0, le=10_000_000)
    action_count: int = Field(ge=0, le=1_000_000)
    decision_count: int = Field(ge=0, le=1_000_000)
    feedback_count: int = Field(ge=0, le=1_000_000)
    verification_count: int = Field(ge=0, le=1_000_000)
    opaque_evidence_refs: tuple[str, ...] = Field(
        default=(), max_length=MAX_RUNTIME_EVIDENCE_REFS
    )
    created_at: datetime
    content_free: Literal[True] = True
    ephemeral_payload_retained: Literal[False] = False
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _safe_versions = field_validator(
        "packet_schema_version",
        "adapter_version",
        "provider_schema_version",
        "preprocessing_version",
        "router_version",
        "redactor_version",
    )(_safe_version)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _safe_digests = field_validator(
        "packet_fingerprint",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "scope_projection_fingerprint",
        "scope_router_output_fingerprint",
        "retrieval_query_fingerprint",
        "requirements_sha256",
        "chronology_sha256",
        "retrieval_index_sha256",
        "preprocessing_sha256",
        "router_sha256",
        "redactor_sha256",
    )(_digest)
    _utc_created = field_validator("created_at")(_utc)
    _canonical_refs = field_validator("opaque_evidence_refs")(_canonical_digests)

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeExecutionReceipt(_RuntimeStrictModel):
    """Immutable start receipt for one exact plan and selected packet set."""

    contract_version: Literal[RUNTIME_EXECUTION_RECEIPT_VERSION] = (
        RUNTIME_EXECUTION_RECEIPT_VERSION
    )
    execution_id: str
    authorization_fingerprint: str
    plan_fingerprint: str
    route: EstimatorRoute
    provider: Provider
    project_id: str
    session_id: str
    session_revision_id: str
    input_fingerprint: str
    metric_packets: tuple[RuntimeMetricPacketBinding, ...] = Field(
        min_length=1,
        max_length=MAX_RUNTIME_METRICS,
    )
    created_at: datetime
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False
    runtime_enabled: Literal[False] = False
    disabled_reason: Literal["durable_consumption_not_implemented"] = (
        "durable_consumption_not_implemented"
    )

    _safe_ids = field_validator(
        "execution_id",
        "authorization_fingerprint",
        "plan_fingerprint",
        "project_id",
        "session_id",
        "session_revision_id",
        "input_fingerprint",
    )(_digest)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("metric_packets")
    @classmethod
    def canonical_packets(
        cls, values: tuple[RuntimeMetricPacketBinding, ...]
    ) -> tuple[RuntimeMetricPacketBinding, ...]:
        keys = tuple(item.metric_key for item in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("metric packets must be unique and metric-key sorted")
        packet_ids = tuple(item.evidence_packet_fingerprint for item in values)
        if len(packet_ids) != len(set(packet_ids)):
            raise ValueError("each selected metric requires its own evidence packet")
        return values

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class ValidatedExecutionCommitmentReceipt(_RuntimeStrictModel):
    """Disabled R0 lineage proof; durable one-shot consumption arrives in R1."""

    contract_version: Literal[VALIDATED_EXECUTION_COMMITMENT_VERSION] = (
        VALIDATED_EXECUTION_COMMITMENT_VERSION
    )
    commitment_id: str
    execution_fingerprint: str
    authorization_fingerprint: str
    plan_fingerprint: str
    route: EstimatorRoute
    provider: Provider
    packet_fingerprints: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_RUNTIME_METRICS
    )
    created_at: datetime
    content_free: Literal[True] = True
    consumption_enforced: Literal[False] = False
    runtime_enabled: Literal[False] = False
    disabled_reason: Literal["durable_consumption_not_implemented"] = (
        "durable_consumption_not_implemented"
    )
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "commitment_id",
        "execution_fingerprint",
        "authorization_fingerprint",
        "plan_fingerprint",
    )(_digest)
    _safe_packets = field_validator("packet_fingerprints")(_canonical_digests)
    _utc_created = field_validator("created_at")(_utc)

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeStageAttemptReceipt(_RuntimeStrictModel):
    """Start receipt binding a stage attempt to one exact metric packet."""

    contract_version: Literal[RUNTIME_STAGE_ATTEMPT_RECEIPT_VERSION] = (
        RUNTIME_STAGE_ATTEMPT_RECEIPT_VERSION
    )
    attempt_id: str
    execution_id: str
    execution_commitment_fingerprint: str
    authorization_fingerprint: str
    plan_fingerprint: str
    route: EstimatorRoute
    provider: Provider
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    stage_ordinal: int = Field(ge=1, le=len(STAGE_ORDER))
    stage_kind: EstimatorStageKind
    stage_fingerprint: str
    stage_registration_fingerprint: str
    model_artifact_fingerprint: str | None = None
    attempt_ordinal: int = Field(ge=1, le=100)
    started_at: datetime
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    runtime_enabled: Literal[False] = False
    disabled_reason: Literal["durable_consumption_not_implemented"] = (
        "durable_consumption_not_implemented"
    )

    _safe_ids = field_validator(
        "attempt_id",
        "execution_id",
        "execution_commitment_fingerprint",
        "authorization_fingerprint",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "stage_fingerprint",
        "stage_registration_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _utc_started = field_validator("started_at")(_utc)

    @field_validator("model_artifact_fingerprint")
    @classmethod
    def safe_optional_model(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_stage_identity(self) -> RuntimeStageAttemptReceipt:
        if self.stage_kind is not STAGE_ORDER[self.stage_ordinal - 1]:
            raise ValueError("stage ordinal and kind must match the serialized plan")
        if (self.stage_kind in MODEL_STAGE_KINDS) != (
            self.model_artifact_fingerprint is not None
        ):
            raise ValueError("only model stages require an exact model fingerprint")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class ResourceMeasurement(_RuntimeStrictModel):
    resource_key: str
    state: ResourceMeasurementState
    value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit_code: str | None = None
    reason_code: str | None = None

    _safe_resource = field_validator("resource_key")(_safe_code)

    @field_validator("unit_code", "reason_code")
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_measurement(self) -> ResourceMeasurement:
        if self.state is ResourceMeasurementState.KNOWN:
            if self.value is None or self.unit_code is None or self.reason_code is not None:
                raise ValueError("known resources require a value and unit only")
        elif (
            self.value is not None
            or self.unit_code is not None
            or self.reason_code is None
        ):
            raise ValueError(
                "unavailable resources require only an explicit reason code"
            )
        return self


RESOURCE_UNIT_BY_KEY = {
    "api_cost_microusd": "microusd",
    "cold_start_flag": "count",
    "disk_mib": "mib",
    "energy_mwh": "mwh",
    "execution_latency_ms": "milliseconds",
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "peak_ram_mib": "mib",
    "peak_vram_mib": "mib",
    "queue_latency_ms": "milliseconds",
    "throughput_unit_count": "count",
    "throughput_window_ms": "milliseconds",
}
REQUIRED_RESOURCE_KEYS = tuple(sorted(RESOURCE_UNIT_BY_KEY))


class RuntimeResourceReceipt(_RuntimeStrictModel):
    """Closed resource ledger: every required measurement has an explicit state."""

    contract_version: Literal[RUNTIME_RESOURCE_RECEIPT_VERSION] = (
        RUNTIME_RESOURCE_RECEIPT_VERSION
    )
    resource_receipt_id: str
    attempt_id: str
    stage_fingerprint: str
    collector_version: str
    runtime_environment_fingerprint: str
    measurements: tuple[ResourceMeasurement, ...] = Field(
        min_length=len(REQUIRED_RESOURCE_KEYS),
        max_length=len(REQUIRED_RESOURCE_KEYS),
    )
    created_at: datetime
    content_free: Literal[True] = True
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "resource_receipt_id",
        "attempt_id",
        "stage_fingerprint",
        "runtime_environment_fingerprint",
    )(_digest)
    _safe_collector = field_validator("collector_version")(_safe_version)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("measurements")
    @classmethod
    def complete_measurements(
        cls, values: tuple[ResourceMeasurement, ...]
    ) -> tuple[ResourceMeasurement, ...]:
        keys = tuple(item.resource_key for item in values)
        if keys != REQUIRED_RESOURCE_KEYS:
            raise ValueError("resource measurements must cover the closed sorted key set")
        for item in values:
            if (
                item.state is ResourceMeasurementState.KNOWN
                and item.unit_code != RESOURCE_UNIT_BY_KEY[item.resource_key]
            ):
                raise ValueError("known resource unit does not match its resource key")
            if item.state is ResourceMeasurementState.KNOWN:
                assert item.value is not None
                if item.unit_code in {"count", "tokens", "microusd"} and not float(
                    item.value
                ).is_integer():
                    raise ValueError("discrete resource measurements must be integers")
                if item.resource_key == "cold_start_flag" and item.value not in {0, 1}:
                    raise ValueError("cold-start flag must be exactly zero or one")
        return values

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeStageOutcomeReceipt(_RuntimeStrictModel):
    contract_version: Literal[RUNTIME_STAGE_OUTCOME_RECEIPT_VERSION] = (
        RUNTIME_STAGE_OUTCOME_RECEIPT_VERSION
    )
    outcome_id: str
    attempt_id: str
    execution_id: str
    execution_commitment_fingerprint: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    stage_fingerprint: str
    stage_registration_fingerprint: str
    resource_receipt_fingerprint: str
    state: RuntimeStageOutcomeState
    output_fingerprint: str | None = None
    output_kind: str | None = None
    reason_code: str | None = None
    recorded_at: datetime
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    runtime_enabled: Literal[False] = False
    disabled_reason: Literal["durable_consumption_not_implemented"] = (
        "durable_consumption_not_implemented"
    )

    _safe_ids = field_validator(
        "outcome_id",
        "attempt_id",
        "execution_id",
        "execution_commitment_fingerprint",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "stage_fingerprint",
        "stage_registration_fingerprint",
        "resource_receipt_fingerprint",
    )(_digest)
    _utc_recorded = field_validator("recorded_at")(_utc)

    @field_validator("output_fingerprint")
    @classmethod
    def safe_optional_output(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("reason_code", "output_kind")
    @classmethod
    def safe_optional_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_outcome(self) -> RuntimeStageOutcomeReceipt:
        if self.state is RuntimeStageOutcomeState.COMPLETED:
            if (
                self.output_fingerprint is None
                or self.output_kind is None
                or self.reason_code is not None
            ):
                raise ValueError("completed stages require an output fingerprint only")
        elif (
            self.output_fingerprint is not None
            or self.output_kind is not None
            or self.reason_code is None
        ):
            raise ValueError("non-completed stages require only an explicit reason")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeRetrievalHit(_RuntimeStrictModel):
    """Opaque ranked reference with a raw retrieval score, never confidence."""

    evidence_reference_id: str
    rank: int = Field(ge=1, le=MAX_RUNTIME_EVIDENCE_REFS)
    raw_score: float = Field(allow_inf_nan=False)
    score_semantics: Literal["uncalibrated_retrieval_score"] = (
        "uncalibrated_retrieval_score"
    )

    _safe_reference = field_validator("evidence_reference_id")(_digest)


class RuntimeRetrievalResultReceipt(_RuntimeStrictModel):
    """Content-free result of BM25, embedding retrieval, or reranking."""

    contract_version: Literal[RUNTIME_RETRIEVAL_RESULT_RECEIPT_VERSION] = (
        RUNTIME_RETRIEVAL_RESULT_RECEIPT_VERSION
    )
    result_id: str
    execution_id: str
    execution_commitment_fingerprint: str
    attempt_id: str
    plan_fingerprint: str
    stage_fingerprint: str
    evidence_packet_fingerprint: str
    metric_question_fingerprint: str
    metric_key: str
    stage_kind: EstimatorStageKind
    score_kind: RuntimeRetrievalScoreKind
    query_fingerprint: str
    candidate_index_fingerprint: str
    upstream_result_fingerprint: str | None = None
    candidate_count: int = Field(ge=0, le=10_000_000)
    candidate_reference_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_RUNTIME_EVIDENCE_REFS
    )
    hits: tuple[RuntimeRetrievalHit, ...] = Field(
        default=(), max_length=MAX_RUNTIME_EVIDENCE_REFS
    )
    created_at: datetime
    content_free: Literal[True] = True
    calibration_state: Literal["not_assessed"] = "not_assessed"
    quality_estimate_available: Literal[False] = False
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "result_id",
        "execution_id",
        "execution_commitment_fingerprint",
        "attempt_id",
        "plan_fingerprint",
        "stage_fingerprint",
        "evidence_packet_fingerprint",
        "metric_question_fingerprint",
        "query_fingerprint",
        "candidate_index_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _utc_created = field_validator("created_at")(_utc)
    _canonical_candidates = field_validator("candidate_reference_ids")(
        _canonical_digests
    )

    @field_validator("upstream_result_fingerprint")
    @classmethod
    def safe_optional_upstream(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("hits")
    @classmethod
    def canonical_hits(
        cls, values: tuple[RuntimeRetrievalHit, ...]
    ) -> tuple[RuntimeRetrievalHit, ...]:
        if tuple(item.rank for item in values) != tuple(range(1, len(values) + 1)):
            raise ValueError("retrieval hits must have contiguous rank order")
        references = tuple(item.evidence_reference_id for item in values)
        if len(references) != len(set(references)):
            raise ValueError("retrieval hits must have unique evidence references")
        return values

    @model_validator(mode="after")
    def validate_retrieval(self) -> RuntimeRetrievalResultReceipt:
        expected_score_kind = {
            EstimatorStageKind.BM25_RETRIEVAL: RuntimeRetrievalScoreKind.BM25_RAW,
            EstimatorStageKind.EMBEDDING_RETRIEVAL: (
                RuntimeRetrievalScoreKind.EMBEDDING_SIMILARITY_RAW
            ),
            EstimatorStageKind.RERANKER: RuntimeRetrievalScoreKind.RERANKER_RAW,
        }.get(self.stage_kind)
        if expected_score_kind is None or self.score_kind is not expected_score_kind:
            raise ValueError("retrieval score kind must match its retrieval stage")
        if self.candidate_count != len(self.candidate_reference_ids):
            raise ValueError("candidate count must match the exact reference index")
        candidate_ids = set(self.candidate_reference_ids)
        if any(hit.evidence_reference_id not in candidate_ids for hit in self.hits):
            raise ValueError("retrieval hits must come from the candidate index")
        if self.stage_kind is EstimatorStageKind.BM25_RETRIEVAL:
            if self.upstream_result_fingerprint is not None:
                raise ValueError("BM25 retrieval begins from the evidence packet")
        elif self.upstream_result_fingerprint is None:
            raise ValueError("later retrieval stages require an upstream result")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeExecutionCheckpointReceipt(_RuntimeStrictModel):
    """Content-free restart boundary for a durable queue implementation."""

    contract_version: Literal[RUNTIME_CHECKPOINT_RECEIPT_VERSION] = (
        RUNTIME_CHECKPOINT_RECEIPT_VERSION
    )
    checkpoint_id: str
    execution_id: str
    execution_commitment_fingerprint: str
    plan_fingerprint: str
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    previous_checkpoint_fingerprint: str | None = None
    checkpoint_sequence: int = Field(ge=0)
    restart_generation: int = Field(ge=0)
    state: RuntimeExecutionState
    last_completed_stage_ordinal: int = Field(ge=0, le=len(STAGE_ORDER))
    last_completed_attempt_id: str | None = None
    next_stage_ordinal: int | None = Field(default=None, ge=1, le=len(STAGE_ORDER))
    next_stage_fingerprint: str | None = None
    cancellation_requested: bool
    state_reason_code: str | None = None
    recorded_at: datetime
    content_free: Literal[True] = True
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "checkpoint_id",
        "execution_id",
        "execution_commitment_fingerprint",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _utc_recorded = field_validator("recorded_at")(_utc)

    @field_validator(
        "previous_checkpoint_fingerprint",
        "last_completed_attempt_id",
        "next_stage_fingerprint",
    )
    @classmethod
    def safe_optional_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("state_reason_code")
    @classmethod
    def safe_optional_state_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_checkpoint(self) -> RuntimeExecutionCheckpointReceipt:
        if (self.last_completed_stage_ordinal == 0) != (
            self.last_completed_attempt_id is None
        ):
            raise ValueError("completed stage ordinal and attempt identity must agree")
        next_pair = (self.next_stage_ordinal, self.next_stage_fingerprint)
        if (next_pair[0] is None) != (next_pair[1] is None):
            raise ValueError("next stage identity must be complete")
        if self.state in TERMINAL_RUNTIME_STATES:
            if next_pair[0] is not None:
                raise ValueError("terminal checkpoints cannot claim a next stage")
        else:
            if next_pair[0] is None:
                raise ValueError("non-terminal checkpoints require an exact next stage")
            if self.next_stage_ordinal != self.last_completed_stage_ordinal + 1:
                raise ValueError("checkpoint next stage must follow the completed prefix")
        if self.state is RuntimeExecutionState.CANCELLED and not self.cancellation_requested:
            raise ValueError("cancelled checkpoints require a cancellation request")
        reason_required = self.state in {
            RuntimeExecutionState.AWAITING_APPROVAL,
            RuntimeExecutionState.AWAITING_HUMAN,
            RuntimeExecutionState.PARTIAL,
            RuntimeExecutionState.FAILED,
            RuntimeExecutionState.CANCELLED,
            RuntimeExecutionState.SUPERSEDED,
        } or self.cancellation_requested
        if reason_required != (self.state_reason_code is not None):
            raise ValueError("checkpoint state and explicit reason must agree")
        if self.state is RuntimeExecutionState.COMPLETED:
            if self.last_completed_stage_ordinal != len(STAGE_ORDER):
                raise ValueError("completed checkpoints require the complete cascade")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


def validate_runtime_checkpoint_transition(
    previous: RuntimeExecutionCheckpointReceipt,
    current: RuntimeExecutionCheckpointReceipt,
) -> RuntimeExecutionCheckpointReceipt:
    """Require monotonic, hash-chained restart/cancellation progress per metric."""

    previous = RuntimeExecutionCheckpointReceipt.model_validate(
        previous.model_dump(mode="python")
    )
    current = RuntimeExecutionCheckpointReceipt.model_validate(
        current.model_dump(mode="python")
    )
    same_lineage = (
        current.execution_id == previous.execution_id
        and current.plan_fingerprint == previous.plan_fingerprint
        and current.metric_key == previous.metric_key
        and current.metric_question_fingerprint
        == previous.metric_question_fingerprint
        and current.evidence_packet_fingerprint
        == previous.evidence_packet_fingerprint
        and current.previous_checkpoint_fingerprint
        == previous.canonical_fingerprint
    )
    monotonic = (
        current.checkpoint_sequence == previous.checkpoint_sequence + 1
        and current.restart_generation in {
            previous.restart_generation,
            previous.restart_generation + 1,
        }
        and current.recorded_at >= previous.recorded_at
        and current.last_completed_stage_ordinal
        >= previous.last_completed_stage_ordinal
        and (not previous.cancellation_requested or current.cancellation_requested)
        and previous.state not in TERMINAL_RUNTIME_STATES
    )
    if not same_lineage or not monotonic:
        raise ValueError("checkpoint transition must be monotonic and hash chained")
    return current


class RuntimeRawModelScore(_RuntimeStrictModel):
    """A model-emitted score with no calibration or confidence semantics."""

    state: RawModelScoreState
    value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    reason_code: str | None = None
    semantics: Literal["uncalibrated_raw_model_score"] = (
        "uncalibrated_raw_model_score"
    )

    @field_validator("reason_code")
    @classmethod
    def safe_optional_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_score(self) -> RuntimeRawModelScore:
        if self.state is RawModelScoreState.KNOWN:
            if self.value is None or self.reason_code is not None:
                raise ValueError("known raw scores require a value only")
        elif self.value is not None or self.reason_code is None:
            raise ValueError("unavailable raw scores require only an explicit reason")
        return self


def _validate_runtime_answer_value(
    *,
    state: MetricEstimateState,
    value_kind: MetricValueKind,
    numeric_value: float | None,
    label_code: str | None,
    reason_code: str | None,
) -> None:
    numeric_kind = value_kind in {MetricValueKind.CONTINUOUS, MetricValueKind.FRACTION}
    if state is MetricEstimateState.KNOWN:
        if numeric_kind != (numeric_value is not None):
            raise ValueError("known answer value does not match its metric kind")
        if numeric_kind == (label_code is not None):
            raise ValueError("known answers require exactly one value representation")
        if reason_code is not None:
            raise ValueError("known answers cannot carry an unavailable reason")
        if value_kind is MetricValueKind.FRACTION and not 0 <= numeric_value <= 1:
            raise ValueError("known fractions must remain within 0..1")
    elif numeric_value is not None or label_code is not None or reason_code is None:
        raise ValueError("unavailable answers require only an explicit reason")


class RuntimeQuestionAnswerReceipt(_RuntimeStrictModel):
    """Execution evidence only; deliberately not a calibrated ``MetricEstimate``."""

    contract_version: Literal[RUNTIME_QUESTION_ANSWER_RECEIPT_VERSION] = (
        RUNTIME_QUESTION_ANSWER_RECEIPT_VERSION
    )
    answer_id: str
    execution_id: str
    attempt_id: str
    plan_fingerprint: str
    stage_fingerprint: str
    evidence_packet_fingerprint: str
    metric_question_fingerprint: str
    metric_key: str
    stage_kind: EstimatorStageKind
    source: RuntimeAnswerSource
    state: MetricEstimateState
    value_kind: MetricValueKind
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    unavailable_reason_code: str | None = None
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, gt=0)
    model_run_id: str | None = None
    raw_model_score: RuntimeRawModelScore | None = None
    opaque_evidence_refs: tuple[str, ...] = Field(
        default=(), max_length=MAX_RUNTIME_EVIDENCE_REFS
    )
    created_at: datetime
    calibration_state: Literal["not_assessed"] = "not_assessed"
    quality_estimate_available: Literal[False] = False
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "answer_id",
        "execution_id",
        "attempt_id",
        "plan_fingerprint",
        "stage_fingerprint",
        "evidence_packet_fingerprint",
        "metric_question_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _utc_created = field_validator("created_at")(_utc)
    _safe_refs = field_validator("opaque_evidence_refs")(_canonical_digests)

    @field_validator("label_code", "unavailable_reason_code")
    @classmethod
    def safe_optional_code(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @field_validator("model_run_id")
    @classmethod
    def safe_optional_run(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_answer(self) -> RuntimeQuestionAnswerReceipt:
        _validate_runtime_answer_value(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            reason_code=self.unavailable_reason_code,
        )
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("objective fractions require numerator and denominator")
        if self.numerator is not None:
            if (
                self.state is not MetricEstimateState.KNOWN
                or self.value_kind is not MetricValueKind.FRACTION
                or self.numeric_value is None
                or not math.isclose(
                    self.numeric_value,
                    self.numerator / self.denominator,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError("fraction value must equal its objective counts")
            if self.source not in {
                RuntimeAnswerSource.OBJECTIVE_EVIDENCE,
                RuntimeAnswerSource.DETERMINISTIC_RULE,
            }:
                raise ValueError("only objective stage-one answers may carry counts")
        if (
            self.source is RuntimeAnswerSource.OBJECTIVE_EVIDENCE
            and self.state is MetricEstimateState.KNOWN
            and self.value_kind is MetricValueKind.FRACTION
            and self.numerator is None
        ):
            raise ValueError("known objective fractions require exact counts")

        model_source = self.source in {
            RuntimeAnswerSource.LOCAL_MODEL_RAW,
            RuntimeAnswerSource.REMOTE_MODEL_RAW,
            RuntimeAnswerSource.SYNTHETIC_MODEL_RAW,
        }
        if model_source:
            if self.stage_kind not in {
                EstimatorStageKind.SPECIALIST,
                EstimatorStageKind.SECOND_OPINION,
            }:
                raise ValueError("raw model answers are limited to judgment stages")
            if self.model_run_id is None or self.raw_model_score is None:
                raise ValueError("raw model answers require run and raw-score receipts")
        elif self.model_run_id is not None or self.raw_model_score is not None:
            raise ValueError("non-model answers cannot claim model-run output")

        if self.source is RuntimeAnswerSource.OBJECTIVE_EVIDENCE:
            if self.stage_kind is not EstimatorStageKind.OBJECTIVE_EVIDENCE:
                raise ValueError("objective answers belong to the objective stage")
        elif self.source is RuntimeAnswerSource.DETERMINISTIC_RULE:
            if self.stage_kind is not EstimatorStageKind.OBJECTIVE_EVIDENCE:
                raise ValueError("deterministic metric answers belong to stage one")
        elif self.source is RuntimeAnswerSource.HUMAN_ADJUDICATION:
            if self.stage_kind is not EstimatorStageKind.HUMAN_ADJUDICATION:
                raise ValueError("human answers belong to the adjudication stage")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeSecondOpinionSignal(_RuntimeStrictModel):
    kind: SecondOpinionSignalKind
    state: TriggerSignalState
    evidence_fingerprint: str | None = None

    @field_validator("evidence_fingerprint")
    @classmethod
    def safe_optional_evidence(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_signal(self) -> RuntimeSecondOpinionSignal:
        if self.state is TriggerSignalState.PRESENT:
            if self.evidence_fingerprint is None:
                raise ValueError("present trigger signals require objective evidence")
        elif self.evidence_fingerprint is not None:
            raise ValueError("absent and unknown trigger signals cannot claim evidence")
        return self


class RuntimeSecondOpinionDecisionReceipt(_RuntimeStrictModel):
    contract_version: Literal[RUNTIME_SECOND_OPINION_DECISION_VERSION] = (
        RUNTIME_SECOND_OPINION_DECISION_VERSION
    )
    decision_id: str
    execution_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    specialist_attempt_id: str
    specialist_answer_fingerprint: str
    policy_version: str
    policy_sha256: str
    signals: tuple[RuntimeSecondOpinionSignal, ...] = Field(
        min_length=len(SECOND_OPINION_SIGNAL_ORDER),
        max_length=len(SECOND_OPINION_SIGNAL_ORDER),
    )
    decision: SecondOpinionDecision
    created_at: datetime
    content_free: Literal[True] = True
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "decision_id",
        "execution_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "specialist_attempt_id",
        "specialist_answer_fingerprint",
        "policy_sha256",
    )(_digest)
    _safe_policy = field_validator("policy_version")(_safe_version)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("signals")
    @classmethod
    def complete_signals(
        cls, values: tuple[RuntimeSecondOpinionSignal, ...]
    ) -> tuple[RuntimeSecondOpinionSignal, ...]:
        if tuple(item.kind for item in values) != SECOND_OPINION_SIGNAL_ORDER:
            raise ValueError("second-opinion signals must use the closed sorted set")
        return values

    @model_validator(mode="after")
    def validate_decision(self) -> RuntimeSecondOpinionDecisionReceipt:
        states = tuple(item.state for item in self.signals)
        expected = (
            SecondOpinionDecision.TRIGGER
            if TriggerSignalState.PRESENT in states
            else SecondOpinionDecision.INSUFFICIENT_EVIDENCE
            if TriggerSignalState.UNKNOWN in states
            else SecondOpinionDecision.DO_NOT_TRIGGER
        )
        if self.decision is not expected:
            raise ValueError("second-opinion decision must follow the closed trigger policy")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class RuntimeHumanAdjudicationRequestReceipt(_RuntimeStrictModel):
    """Content-free handoff when two execution answers remain unresolved."""

    contract_version: Literal[RUNTIME_HUMAN_ADJUDICATION_REQUEST_VERSION] = (
        RUNTIME_HUMAN_ADJUDICATION_REQUEST_VERSION
    )
    request_id: str
    execution_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    human_stage_registration_fingerprint: str
    second_opinion_decision_fingerprint: str
    specialist_answer_fingerprint: str
    second_opinion_answer_fingerprint: str
    reason_code: Literal["unresolved_disagreement"] = "unresolved_disagreement"
    created_at: datetime
    state: Literal["awaiting_human"] = "awaiting_human"
    content_free: Literal[True] = True
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "request_id",
        "execution_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "human_stage_registration_fingerprint",
        "second_opinion_decision_fingerprint",
        "specialist_answer_fingerprint",
        "second_opinion_answer_fingerprint",
    )(_digest)
    _utc_created = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def distinct_answers(self) -> RuntimeHumanAdjudicationRequestReceipt:
        if (
            self.specialist_answer_fingerprint
            == self.second_opinion_answer_fingerprint
        ):
            raise ValueError("human review requires two independent answer receipts")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


__all__ = [
    "REQUIRED_RESOURCE_KEYS",
    "RESOURCE_UNIT_BY_KEY",
    "RawModelScoreState",
    "ResourceMeasurement",
    "ResourceMeasurementState",
    "RuntimeAnswerSource",
    "RuntimeAuthorizationKind",
    "RuntimeAuthorizationReceipt",
    "RuntimeEvidencePacketReceipt",
    "RuntimeExecutionCheckpointReceipt",
    "RuntimeExecutionReceipt",
    "RuntimeExecutionState",
    "RuntimeHumanAdjudicationRequestReceipt",
    "RuntimeMetricPacketBinding",
    "RuntimeMetricSelection",
    "RuntimeQuestionAnswerReceipt",
    "RuntimeRawModelScore",
    "RuntimeRetrievalHit",
    "RuntimeRetrievalResultReceipt",
    "RuntimeRetrievalScoreKind",
    "RuntimeResourceReceipt",
    "RuntimeSecondOpinionDecisionReceipt",
    "RuntimeSecondOpinionSignal",
    "RuntimeStageAttemptReceipt",
    "RuntimeStageOutcomeReceipt",
    "RuntimeStageOutcomeState",
    "SecondOpinionDecision",
    "SecondOpinionSignalKind",
    "TriggerSignalState",
    "ValidatedExecutionCommitmentReceipt",
    "estimator_stage_fingerprint",
    "validate_runtime_checkpoint_transition",
]
