"""Versioned, content-free contracts for calibrated metric estimation.

These contracts describe estimator configuration and structured judgments only.
They intentionally have no prompt, transcript, excerpt, evidence body, model
response, rationale, or chain-of-thought field. Evidence crosses this boundary
only as counts, SHA-256 digests, and opaque pseudonymous references.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    StrictModel,
)


ESTIMATOR_CONTRACT_VERSION = "estimator-contract-v1"
METRIC_QUESTION_CONTRACT_VERSION = "metric-question-v1"
EVIDENCE_PACKET_RECEIPT_VERSION = "evidence-packet-receipt-v1"
MODEL_ARTIFACT_CONTRACT_VERSION = "model-artifact-v1"
ESTIMATOR_PLAN_CONTRACT_VERSION = "estimator-plan-v1"
ESTIMATOR_EXECUTION_CONTRACT_VERSION = "estimator-execution-v1"
MODEL_RUN_CONTRACT_VERSION = "model-run-v1"
MODEL_VOTE_CONTRACT_VERSION = "model-vote-v1"
METRIC_ESTIMATE_CONTRACT_VERSION = "metric-estimate-v1"
IMMUTABLE_JUDGMENT_CONTRACT_VERSION = "immutable-judgment-v1"
ADJUDICATION_CONTRACT_VERSION = "adjudication-v1"

MAX_METRICS_PER_PLAN = 100
MAX_EVIDENCE_REFS = 512
MAX_SCREENED_CANDIDATES_PER_FAMILY = 5
MAX_PROMOTED_CANDIDATES_PER_FAMILY = 2

SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
SAFE_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


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


def _safe_code(value: str) -> str:
    if SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _sha256(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a 64-character pseudonymous identifier")
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


def _canonical_safe_versions(values: tuple[str, ...]) -> tuple[str, ...]:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("values must be unique and sorted")
    return tuple(_safe_version(value) for value in values)


def _canonical_digests(values: tuple[str, ...]) -> tuple[str, ...]:
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("digests must be unique and sorted")
    return tuple(_sha256(value) for value in values)


class EstimatorRoute(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


class MetricValueKind(StrEnum):
    CONTINUOUS = "continuous"
    FRACTION = "fraction"
    BINARY = "binary"
    CATEGORICAL = "categorical"


class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    DESCRIPTIVE = "descriptive"


class ModelSource(StrEnum):
    LOCAL_WEIGHTS = "local_weights"
    OPENAI_API = "openai_api"
    ANTHROPIC_API = "anthropic_api"
    CODEX_CLI = "codex_cli"
    CLAUDE_CLI = "claude_cli"
    SYNTHETIC = "synthetic"


class ModelExecutionMode(StrEnum):
    """Exact model-service execution tier used by an evaluated configuration."""

    STANDARD = "standard"
    PRO = "pro"


class ArtifactAvailability(StrEnum):
    PINNED_HASHES = "pinned_hashes"
    PROVIDER_MANAGED = "provider_managed"
    SYNTHETIC_NO_WEIGHTS = "synthetic_no_weights"


class EstimatorReasoningEffort(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class EstimatorStageKind(StrEnum):
    OBJECTIVE_EVIDENCE = "objective_evidence"
    BM25_RETRIEVAL = "bm25_retrieval"
    EMBEDDING_RETRIEVAL = "embedding_retrieval"
    RERANKER = "reranker"
    SPECIALIST = "specialist"
    SECOND_OPINION = "second_opinion"
    HUMAN_ADJUDICATION = "human_adjudication"


class StageCondition(StrEnum):
    ALWAYS = "always"
    DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE = (
        "disagreement_low_confidence_drift_audit_or_high_value"
    )
    UNRESOLVED_DISAGREEMENT = "unresolved_disagreement"


STAGE_ORDER = (
    EstimatorStageKind.OBJECTIVE_EVIDENCE,
    EstimatorStageKind.BM25_RETRIEVAL,
    EstimatorStageKind.EMBEDDING_RETRIEVAL,
    EstimatorStageKind.RERANKER,
    EstimatorStageKind.SPECIALIST,
    EstimatorStageKind.SECOND_OPINION,
    EstimatorStageKind.HUMAN_ADJUDICATION,
)

MODEL_STAGE_KINDS = frozenset(
    {
        EstimatorStageKind.EMBEDDING_RETRIEVAL,
        EstimatorStageKind.RERANKER,
        EstimatorStageKind.SPECIALIST,
        EstimatorStageKind.SECOND_OPINION,
    }
)


class MetricQuestionSpec(StrictModel):
    """A metric question identified entirely by safe IDs and source digests."""

    contract_version: Literal[METRIC_QUESTION_CONTRACT_VERSION] = (
        METRIC_QUESTION_CONTRACT_VERSION
    )
    metric_key: str
    metric_definition_version: str
    question_id: str
    question_version: str
    question_sha256: str
    prompt_template_id: str
    prompt_template_version: str
    prompt_template_sha256: str
    rubric_id: str
    rubric_version: str
    rubric_sha256: str
    output_schema_version: str
    value_kind: MetricValueKind
    unit_code: str
    direction: MetricDirection
    lower_bound: float | None = Field(default=None, allow_inf_nan=False)
    upper_bound: float | None = Field(default=None, allow_inf_nan=False)

    _safe_codes = field_validator(
        "metric_key", "question_id", "prompt_template_id", "rubric_id", "unit_code"
    )(_safe_code)
    _safe_versions = field_validator(
        "metric_definition_version",
        "question_version",
        "prompt_template_version",
        "rubric_version",
        "output_schema_version",
    )(_safe_version)
    _safe_digests = field_validator(
        "question_sha256", "prompt_template_sha256", "rubric_sha256"
    )(_sha256)

    @model_validator(mode="after")
    def validate_bounds(self) -> MetricQuestionSpec:
        numeric = self.value_kind in {
            MetricValueKind.CONTINUOUS,
            MetricValueKind.FRACTION,
        }
        if numeric != (self.lower_bound is not None and self.upper_bound is not None):
            raise ValueError("numeric metrics require two finite bounds")
        if numeric and self.lower_bound >= self.upper_bound:
            raise ValueError("metric lower bound must be below its upper bound")
        if self.value_kind is MetricValueKind.FRACTION and (
            self.lower_bound != 0.0 or self.upper_bound != 1.0
        ):
            raise ValueError("fraction metrics must use the documented 0..1 bound")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EvidencePacketReceipt(StrictModel):
    """Opaque receipt for an ephemeral evidence packet; no evidence body survives."""

    contract_version: Literal[EVIDENCE_PACKET_RECEIPT_VERSION] = (
        EVIDENCE_PACKET_RECEIPT_VERSION
    )
    packet_schema_version: str
    packet_sha256: str = Field(
        description=(
            "Digest of the ephemeral evidence-packet payload; this is not the "
            "canonical identity of this receipt."
        )
    )
    requirements_sha256: str
    chronology_sha256: str
    retrieval_index_sha256: str
    provider: Provider
    adapter_version: str
    provider_schema_version: str
    preprocessing_version: str
    preprocessing_sha256: str
    redactor_version: str
    redactor_sha256: str
    source_record_count: int = Field(ge=0, le=10_000_000)
    requirement_count: int = Field(ge=0, le=1_000_000)
    action_count: int = Field(ge=0, le=1_000_000)
    decision_count: int = Field(ge=0, le=1_000_000)
    feedback_count: int = Field(ge=0, le=1_000_000)
    verification_count: int = Field(ge=0, le=1_000_000)
    opaque_evidence_refs: tuple[str, ...] = Field(
        default=(), max_length=MAX_EVIDENCE_REFS
    )
    created_at: datetime
    ephemeral_payload_retained: Literal[False] = False

    _safe_versions = field_validator(
        "packet_schema_version",
        "adapter_version",
        "provider_schema_version",
        "preprocessing_version",
        "redactor_version",
    )(_safe_version)
    _safe_digests = field_validator(
        "packet_sha256",
        "requirements_sha256",
        "chronology_sha256",
        "retrieval_index_sha256",
        "preprocessing_sha256",
        "redactor_sha256",
    )(_sha256)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("opaque_evidence_refs")
    @classmethod
    def canonical_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values)

    @property
    def canonical_fingerprint(self) -> str:
        """Canonical identity of the complete content-free receipt."""

        return _canonical_digest(self)


class ArtifactDigest(StrictModel):
    file_name: str
    sha256: str

    @field_validator("file_name")
    @classmethod
    def safe_file_name(cls, value: str) -> str:
        if SAFE_FILE_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("artifact names must be safe basenames")
        return value

    _safe_digest = field_validator("sha256")(_sha256)


class TokenizerIdentity(StrictModel):
    tokenizer_id: str
    revision: str
    availability: ArtifactAvailability
    artifacts: tuple[ArtifactDigest, ...] = Field(default=(), max_length=64)

    _safe_versions = field_validator("tokenizer_id", "revision")(_safe_version)

    @model_validator(mode="after")
    def validate_artifact_disclosure(self) -> TokenizerIdentity:
        names = tuple(artifact.file_name for artifact in self.artifacts)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("tokenizer artifacts must have unique sorted names")
        has_hashes = bool(self.artifacts)
        if (self.availability is ArtifactAvailability.PINNED_HASHES) != has_hashes:
            raise ValueError("pinned tokenizer availability requires artifact hashes")
        return self


class ModelArtifactIdentity(StrictModel):
    """Exact requested/served model and immutable artifact provenance."""

    contract_version: Literal[MODEL_ARTIFACT_CONTRACT_VERSION] = (
        MODEL_ARTIFACT_CONTRACT_VERSION
    )
    source: ModelSource
    requested_model_id: str
    served_model_id: str
    requested_revision: str
    served_revision: str
    requested_execution_mode: ModelExecutionMode
    served_execution_mode: ModelExecutionMode
    weight_availability: ArtifactAvailability
    weight_artifacts: tuple[ArtifactDigest, ...] = Field(default=(), max_length=256)
    tokenizer: TokenizerIdentity
    license_id: str
    trust_remote_code: Literal[False] = False

    _safe_versions = field_validator(
        "requested_model_id",
        "served_model_id",
        "requested_revision",
        "served_revision",
        "license_id",
    )(_safe_version)

    @model_validator(mode="after")
    def validate_artifacts(self) -> ModelArtifactIdentity:
        names = tuple(artifact.file_name for artifact in self.weight_artifacts)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("weight artifacts must have unique sorted names")
        has_hashes = bool(self.weight_artifacts)
        if (self.weight_availability is ArtifactAvailability.PINNED_HASHES) != has_hashes:
            raise ValueError("pinned weight availability requires artifact hashes")

        if self.source is ModelSource.LOCAL_WEIGHTS:
            if self.weight_availability is not ArtifactAvailability.PINNED_HASHES:
                raise ValueError("local model weights must be pinned by hash")
            if self.tokenizer.availability is not ArtifactAvailability.PINNED_HASHES:
                raise ValueError("local tokenizers must be pinned by hash")
        elif self.source is ModelSource.SYNTHETIC:
            if self.weight_availability is not ArtifactAvailability.SYNTHETIC_NO_WEIGHTS:
                raise ValueError("synthetic models cannot claim real weight artifacts")
            if self.tokenizer.availability is not ArtifactAvailability.SYNTHETIC_NO_WEIGHTS:
                raise ValueError("synthetic models cannot claim real tokenizer artifacts")
        elif self.weight_availability is not ArtifactAvailability.PROVIDER_MANAGED:
            raise ValueError("remote model weights must be marked provider-managed")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class CandidateFamilySelection(StrictModel):
    """Bounded local screening result; promotion is not product activation."""

    family_key: str
    screened_candidates: tuple[ModelArtifactIdentity, ...] = Field(
        min_length=1,
        max_length=MAX_SCREENED_CANDIDATES_PER_FAMILY,
    )
    promoted_artifact_fingerprints: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_PROMOTED_CANDIDATES_PER_FAMILY,
    )
    deterministic_baseline_ids: tuple[str, ...] = Field(default=(), max_length=16)

    _safe_family = field_validator("family_key")(_safe_code)

    @field_validator("promoted_artifact_fingerprints")
    @classmethod
    def canonical_promotions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values)

    @field_validator("deterministic_baseline_ids")
    @classmethod
    def canonical_baselines(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_safe_versions(values)

    @model_validator(mode="after")
    def validate_local_screening(self) -> CandidateFamilySelection:
        fingerprints = tuple(
            candidate.canonical_fingerprint for candidate in self.screened_candidates
        )
        if fingerprints != tuple(sorted(fingerprints)) or len(fingerprints) != len(
            set(fingerprints)
        ):
            raise ValueError("screened candidates must be unique and fingerprint-sorted")
        if any(
            candidate.source is not ModelSource.LOCAL_WEIGHTS
            for candidate in self.screened_candidates
        ):
            raise ValueError("candidate screening is limited to pinned local models")
        if not set(self.promoted_artifact_fingerprints).issubset(fingerprints):
            raise ValueError("promoted candidates must come from the screened family")
        return self


class EstimatorStage(StrictModel):
    ordinal: int = Field(ge=1, le=len(STAGE_ORDER))
    kind: EstimatorStageKind
    condition: StageCondition
    component_version: str
    configuration_sha256: str
    output_schema_version: str
    model_artifact: ModelArtifactIdentity | None = None
    candidate_family_key: str | None = None

    _safe_versions = field_validator(
        "component_version", "output_schema_version"
    )(_safe_version)
    _safe_configuration = field_validator("configuration_sha256")(_sha256)

    @field_validator("candidate_family_key")
    @classmethod
    def safe_optional_family(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_stage_shape(self) -> EstimatorStage:
        expected_kind = STAGE_ORDER[self.ordinal - 1]
        if self.kind is not expected_kind:
            raise ValueError("stage ordinal does not match the serialized cascade")

        is_model_stage = self.kind in MODEL_STAGE_KINDS
        if is_model_stage != (self.model_artifact is not None):
            raise ValueError("only model stages carry a model artifact identity")
        if not is_model_stage and self.candidate_family_key is not None:
            raise ValueError("deterministic and human stages cannot name a model family")

        expected_condition = StageCondition.ALWAYS
        if self.kind is EstimatorStageKind.SECOND_OPINION:
            expected_condition = (
                StageCondition.DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE
            )
        elif self.kind is EstimatorStageKind.HUMAN_ADJUDICATION:
            expected_condition = StageCondition.UNRESOLVED_DISAGREEMENT
        if self.condition is not expected_condition:
            raise ValueError("stage condition does not match the cascade policy")
        return self


class ProviderSchemaIdentity(StrictModel):
    provider: Provider
    adapter_version: str
    provider_schema_version: str

    _safe_versions = field_validator(
        "adapter_version", "provider_schema_version"
    )(_safe_version)


class EstimatorPlan(StrictModel):
    """Canonical serial plan. It contains no activation or release switch."""

    contract_version: Literal[ESTIMATOR_PLAN_CONTRACT_VERSION] = (
        ESTIMATOR_PLAN_CONTRACT_VERSION
    )
    plan_key: str
    plan_version: str
    route: EstimatorRoute
    question_specs: tuple[MetricQuestionSpec, ...] = Field(
        min_length=1, max_length=MAX_METRICS_PER_PLAN
    )
    evidence_packet_schema_version: str
    provider_schemas: tuple[ProviderSchemaIdentity, ...] = Field(min_length=1)
    preprocessing_version: str
    preprocessing_sha256: str
    reasoning_effort: EstimatorReasoningEffort
    calibration_version: str
    calibration_sha256: str
    router_version: str
    router_sha256: str
    redactor_version: str
    redactor_sha256: str
    stages: tuple[EstimatorStage, ...] = Field(
        min_length=len(STAGE_ORDER), max_length=len(STAGE_ORDER)
    )
    candidate_families: tuple[CandidateFamilySelection, ...] = ()
    execution_mode: Literal["serial"] = "serial"
    model_load_policy: Literal["one_at_a_time"] = "one_at_a_time"
    max_loaded_models: Literal[1] = 1

    _safe_plan_key = field_validator("plan_key")(_safe_code)
    _safe_versions = field_validator(
        "plan_version",
        "evidence_packet_schema_version",
        "preprocessing_version",
        "calibration_version",
        "router_version",
        "redactor_version",
    )(_safe_version)
    _safe_digests = field_validator(
        "preprocessing_sha256",
        "calibration_sha256",
        "router_sha256",
        "redactor_sha256",
    )(_sha256)

    @model_validator(mode="after")
    def validate_canonical_plan(self) -> EstimatorPlan:
        question_keys = tuple(
            (
                question.metric_key,
                question.metric_definition_version,
                question.question_version,
            )
            for question in self.question_specs
        )
        if question_keys != tuple(sorted(question_keys)) or len(question_keys) != len(
            set(question_keys)
        ):
            raise ValueError("metric question specs must be unique and sorted")

        provider_keys = tuple(
            (
                identity.provider.value,
                identity.adapter_version,
                identity.provider_schema_version,
            )
            for identity in self.provider_schemas
        )
        if provider_keys != tuple(sorted(provider_keys)) or len(provider_keys) != len(
            set(provider_keys)
        ):
            raise ValueError("provider schema identities must be unique and sorted")

        if tuple(stage.kind for stage in self.stages) != STAGE_ORDER:
            raise ValueError("estimator stages must use the complete serialized order")

        family_keys = tuple(family.family_key for family in self.candidate_families)
        if family_keys != tuple(sorted(family_keys)) or len(family_keys) != len(
            set(family_keys)
        ):
            raise ValueError("candidate families must be unique and sorted")
        families = {family.family_key: family for family in self.candidate_families}
        for stage in self.stages:
            artifact = stage.model_artifact
            if artifact is None:
                continue
            if artifact.source is ModelSource.LOCAL_WEIGHTS:
                if stage.candidate_family_key is None:
                    raise ValueError("local model stages require a screened family")
                family = families.get(stage.candidate_family_key)
                if family is None:
                    raise ValueError("local model stage references an unknown family")
                if artifact.canonical_fingerprint not in (
                    family.promoted_artifact_fingerprints
                ):
                    raise ValueError("local model stage must use a promoted candidate")
            elif stage.candidate_family_key is not None:
                raise ValueError("remote and synthetic stages cannot claim local screening")

        specialist = self.stages[4].model_artifact
        second_opinion = self.stages[5].model_artifact
        if (
            specialist is not None
            and second_opinion is not None
            and specialist.canonical_fingerprint
            == second_opinion.canonical_fingerprint
        ):
            raise ValueError("the independent second opinion must use another model")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        """Fingerprint the whole evaluated configuration, never runtime labels."""

        return _canonical_digest(self)

    @property
    def uses_synthetic_model(self) -> bool:
        return any(
            stage.model_artifact is not None
            and stage.model_artifact.source is ModelSource.SYNTHETIC
            for stage in self.stages
        )

    @property
    def activation_review_eligible(self) -> bool:
        """Synthetic estimators cannot enter any downstream activation review."""

        return not self.uses_synthetic_model


class EstimatorStageReceiptState(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EstimatorStageReceipt(StrictModel):
    """Content-free result of one reached stage in a serialized cascade."""

    ordinal: int = Field(ge=1, le=len(STAGE_ORDER))
    kind: EstimatorStageKind
    state: EstimatorStageReceiptState
    outcome_code: str
    started_at: datetime | None = None
    finished_at: datetime | None = None

    _safe_outcome = field_validator("outcome_code")(_safe_code)

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> EstimatorStageReceipt:
        if self.kind is not STAGE_ORDER[self.ordinal - 1]:
            raise ValueError("stage receipt ordinal and kind disagree")
        if self.state is EstimatorStageReceiptState.SKIPPED:
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("skipped stage receipts cannot claim execution time")
        elif self.started_at is None or self.finished_at is None:
            raise ValueError("executed stage receipts require start and finish times")
        elif self.finished_at < self.started_at:
            raise ValueError("stage receipt cannot finish before it starts")
        return self


class EstimatorExecutionState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    AWAITING_ADJUDICATION = "awaiting_adjudication"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_EXECUTION_STATES = frozenset(
    {
        EstimatorExecutionState.COMPLETED,
        EstimatorExecutionState.PARTIAL,
        EstimatorExecutionState.FAILED,
        EstimatorExecutionState.CANCELLED,
    }
)


class EstimatorExecution(StrictModel):
    """One repeatable cascade execution; children reference it, never vice versa."""

    contract_version: Literal[ESTIMATOR_EXECUTION_CONTRACT_VERSION] = (
        ESTIMATOR_EXECUTION_CONTRACT_VERSION
    )
    execution_id: str
    plan_fingerprint: str
    evidence_packet_fingerprint: str
    route: EstimatorRoute
    project_id: str | None = None
    session_id: str | None = None
    state: EstimatorExecutionState
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stage_receipts: tuple[EstimatorStageReceipt, ...] = Field(
        default=(), max_length=len(STAGE_ORDER)
    )
    cascade_stop_stage_ordinal: int | None = Field(
        default=None, ge=1, le=len(STAGE_ORDER)
    )
    cascade_stop_stage_kind: EstimatorStageKind | None = None
    cascade_stop_reason_code: str | None = None

    _safe_ids = field_validator(
        "execution_id", "plan_fingerprint", "evidence_packet_fingerprint"
    )(_pseudonym)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("project_id", "session_id")
    @classmethod
    def safe_optional_scope_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_optional_lifecycle(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @field_validator("cascade_stop_reason_code")
    @classmethod
    def safe_optional_stop_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_execution(self) -> EstimatorExecution:
        if len(
            {
                self.execution_id,
                self.plan_fingerprint,
                self.evidence_packet_fingerprint,
            }
        ) != 3:
            raise ValueError("execution and provenance identifiers must be distinct")
        if self.session_id is not None and self.project_id is None:
            raise ValueError("session-scoped executions require a project scope")

        if self.state is EstimatorExecutionState.CREATED:
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.finished_at,
                    self.cascade_stop_stage_ordinal,
                    self.cascade_stop_stage_kind,
                    self.cascade_stop_reason_code,
                )
            ) or self.stage_receipts:
                raise ValueError("created executions cannot claim work or a cascade stop")
            return self

        if self.started_at is None or self.started_at < self.created_at:
            raise ValueError("started executions require an ordered start time")

        expected_ordinals = tuple(range(1, len(self.stage_receipts) + 1))
        if tuple(receipt.ordinal for receipt in self.stage_receipts) != expected_ordinals:
            raise ValueError("stage receipts must be an ordered contiguous cascade prefix")
        previous_finish = self.started_at
        for receipt in self.stage_receipts:
            if receipt.started_at is not None:
                if receipt.started_at < previous_finish:
                    raise ValueError("executed stage receipts cannot overlap or go backwards")
                assert receipt.finished_at is not None
                previous_finish = receipt.finished_at

        stopped = self.state in TERMINAL_EXECUTION_STATES or self.state is (
            EstimatorExecutionState.AWAITING_ADJUDICATION
        )
        stop_fields = (
            self.cascade_stop_stage_ordinal,
            self.cascade_stop_stage_kind,
            self.cascade_stop_reason_code,
        )
        if stopped:
            if not self.stage_receipts or any(value is None for value in stop_fields):
                raise ValueError("stopped executions require an exact cascade stop identity")
            last = self.stage_receipts[-1]
            if (
                self.cascade_stop_stage_ordinal != last.ordinal
                or self.cascade_stop_stage_kind is not last.kind
            ):
                raise ValueError("cascade stop identity must match the last stage receipt")
        elif any(value is not None for value in stop_fields):
            raise ValueError("running executions cannot claim a cascade stop")

        if self.state in TERMINAL_EXECUTION_STATES:
            if self.finished_at is None or self.finished_at < previous_finish:
                raise ValueError("terminal executions require an ordered finish time")
        elif self.finished_at is not None:
            raise ValueError("non-terminal executions cannot claim a finish time")
        return self


class ExecutionDestination(StrEnum):
    LOCAL_DEVICE = "local_device"
    OPENAI_API = "openai_api"
    ANTHROPIC_API = "anthropic_api"
    CODEX_CLI = "codex_cli"
    CLAUDE_API = "claude_api"
    MANUAL_IMPORT = "manual_import"
    SYNTHETIC_TEST = "synthetic_test"


class RetentionClass(StrEnum):
    LOCAL_EPHEMERAL = "local_ephemeral"
    PROVIDER_ZERO_DAY = "provider_zero_day"
    PROVIDER_30_DAY = "provider_30_day"
    PROVIDER_DISCLOSED_OTHER = "provider_disclosed_other"
    MANUAL_EXPORT = "manual_export"
    SYNTHETIC = "synthetic"


REMOTE_DESTINATIONS = frozenset(
    {
        ExecutionDestination.OPENAI_API,
        ExecutionDestination.ANTHROPIC_API,
        ExecutionDestination.CODEX_CLI,
        ExecutionDestination.CLAUDE_API,
    }
)


class ExecutionDisclosure(StrictModel):
    destination: ExecutionDestination
    retention_class: RetentionClass
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    disclosure_version: str
    approval_receipt_id: str | None = None
    retention_acknowledged: bool

    _safe_disclosure_version = field_validator("disclosure_version")(_safe_version)

    @field_validator("approval_receipt_id")
    @classmethod
    def safe_optional_approval(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def validate_disclosure(self) -> ExecutionDisclosure:
        if self.destination in REMOTE_DESTINATIONS:
            if self.approval_receipt_id is None or not self.retention_acknowledged:
                raise ValueError("remote execution requires an acknowledged approval receipt")
            if self.retention_class not in {
                RetentionClass.PROVIDER_ZERO_DAY,
                RetentionClass.PROVIDER_30_DAY,
                RetentionClass.PROVIDER_DISCLOSED_OTHER,
            }:
                raise ValueError("remote execution requires provider retention disclosure")
            if self.retention_days is None:
                raise ValueError("remote retention days must be disclosed exactly")
        elif self.approval_receipt_id is not None:
            raise ValueError("local, manual, and synthetic runs do not use remote approval")

        expected_days = {
            RetentionClass.LOCAL_EPHEMERAL: 0,
            RetentionClass.PROVIDER_ZERO_DAY: 0,
            RetentionClass.PROVIDER_30_DAY: 30,
            RetentionClass.MANUAL_EXPORT: None,
            RetentionClass.SYNTHETIC: 0,
        }.get(self.retention_class)
        if expected_days is not None and self.retention_days != expected_days:
            raise ValueError("retention class and exact retention days disagree")
        if (
            self.retention_class is RetentionClass.PROVIDER_DISCLOSED_OTHER
            and self.retention_days is None
        ):
            raise ValueError("other provider retention must disclose a day count")

        allowed_local = {
            ExecutionDestination.LOCAL_DEVICE: RetentionClass.LOCAL_EPHEMERAL,
            ExecutionDestination.MANUAL_IMPORT: RetentionClass.MANUAL_EXPORT,
            ExecutionDestination.SYNTHETIC_TEST: RetentionClass.SYNTHETIC,
        }
        if self.destination in allowed_local and self.retention_class is not allowed_local[
            self.destination
        ]:
            raise ValueError("destination and retention class disagree")
        if (
            self.destination is ExecutionDestination.MANUAL_IMPORT
            and self.retention_days is not None
        ):
            raise ValueError("manual imports do not claim provider retention days")
        return self


class ModelRunState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    REFUSED = "refused"
    TIMED_OUT = "timed_out"
    OUT_OF_MEMORY = "out_of_memory"
    CANCELLED = "cancelled"


class ModelRun(StrictModel):
    """Structured run provenance with no model-written material."""

    contract_version: Literal[MODEL_RUN_CONTRACT_VERSION] = MODEL_RUN_CONTRACT_VERSION
    run_id: str
    execution_id: str
    plan_fingerprint: str
    evidence_packet_fingerprint: str
    route: EstimatorRoute
    stage_ordinal: int = Field(ge=1, le=len(STAGE_ORDER))
    stage_kind: EstimatorStageKind
    model_artifact: ModelArtifactIdentity
    execution: ExecutionDisclosure
    state: ModelRunState
    started_at: datetime
    finished_at: datetime
    cold_start: bool
    queue_latency_ms: int = Field(ge=0, le=86_400_000)
    latency_ms: int = Field(ge=0, le=86_400_000)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    peak_ram_mib: int | None = Field(default=None, ge=0)
    peak_vram_mib: int | None = Field(default=None, ge=0)
    disk_mib: int | None = Field(default=None, ge=0)
    energy_mwh: int | None = Field(default=None, ge=0)
    api_cost_microusd: int | None = Field(default=None, ge=0)
    throughput_unit_code: str | None = None
    measured_unit_count: int | None = Field(default=None, ge=0)
    throughput_window_ms: int | None = Field(default=None, gt=0, le=86_400_000)
    throughput_provenance_version: str | None = None
    usage_provenance_version: str
    response_schema_version: str
    structured_output_valid: bool
    fallback_used: bool
    fallback_reason_code: str | None = None
    refusal_code: str | None = None
    failure_code: str | None = None

    _safe_ids = field_validator(
        "run_id", "execution_id", "plan_fingerprint", "evidence_packet_fingerprint"
    )(_pseudonym)
    _safe_versions = field_validator(
        "usage_provenance_version", "response_schema_version"
    )(_safe_version)

    @field_validator("throughput_unit_code")
    @classmethod
    def safe_optional_throughput_unit(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @field_validator("throughput_provenance_version")
    @classmethod
    def safe_optional_throughput_version(cls, value: str | None) -> str | None:
        return None if value is None else _safe_version(value)

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("fallback_reason_code", "refusal_code", "failure_code")
    @classmethod
    def safe_optional_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_run(self) -> ModelRun:
        if len(
            {
                self.run_id,
                self.execution_id,
                self.plan_fingerprint,
                self.evidence_packet_fingerprint,
            }
        ) != 4:
            raise ValueError("run, execution, and provenance identifiers must be distinct")
        if self.stage_kind is not STAGE_ORDER[self.stage_ordinal - 1]:
            raise ValueError("model run stage ordinal and kind disagree")
        if self.stage_kind not in MODEL_STAGE_KINDS:
            raise ValueError("model runs can only represent model stages")
        if self.finished_at < self.started_at:
            raise ValueError("model run cannot finish before it starts")

        fallback_observed = (
            self.model_artifact.requested_model_id
            != self.model_artifact.served_model_id
            or self.model_artifact.requested_revision
            != self.model_artifact.served_revision
            or self.model_artifact.requested_execution_mode
            is not self.model_artifact.served_execution_mode
        )
        if self.fallback_used != fallback_observed:
            raise ValueError("fallback flag must match requested and served model identity")
        if self.fallback_used != (self.fallback_reason_code is not None):
            raise ValueError("fallback use requires exactly one safe reason code")

        throughput_fields = (
            self.throughput_unit_code,
            self.measured_unit_count,
            self.throughput_window_ms,
            self.throughput_provenance_version,
        )
        if any(value is not None for value in throughput_fields) and any(
            value is None for value in throughput_fields
        ):
            raise ValueError(
                "throughput requires a unit, measured count, window, and provenance"
            )

        if self.state is ModelRunState.COMPLETED:
            if not self.structured_output_valid:
                raise ValueError("completed model runs require schema-valid structured output")
            if self.refusal_code is not None or self.failure_code is not None:
                raise ValueError("completed model runs cannot carry failure reasons")
        elif self.state is ModelRunState.REFUSED:
            if self.refusal_code is None or self.failure_code is not None:
                raise ValueError("refused model runs require only a refusal code")
            if self.structured_output_valid:
                raise ValueError("refused model runs cannot claim valid output")
        else:
            if self.failure_code is None or self.refusal_code is not None:
                raise ValueError("unsuccessful model runs require only a failure code")
            if self.structured_output_valid:
                raise ValueError("unsuccessful model runs cannot claim valid output")

        source_for_destination = {
            ExecutionDestination.LOCAL_DEVICE: {ModelSource.LOCAL_WEIGHTS},
            ExecutionDestination.OPENAI_API: {ModelSource.OPENAI_API},
            ExecutionDestination.ANTHROPIC_API: {ModelSource.ANTHROPIC_API},
            ExecutionDestination.CODEX_CLI: {ModelSource.CODEX_CLI},
            ExecutionDestination.CLAUDE_API: {ModelSource.ANTHROPIC_API},
            ExecutionDestination.MANUAL_IMPORT: {ModelSource.CLAUDE_CLI},
            ExecutionDestination.SYNTHETIC_TEST: {ModelSource.SYNTHETIC},
        }
        if self.model_artifact.source not in source_for_destination[
            self.execution.destination
        ]:
            raise ValueError("model source and execution destination disagree")
        return self

    @property
    def throughput_per_second(self) -> float | None:
        """Derived rate; persisted provenance remains the exact count and window."""

        if self.measured_unit_count is None or self.throughput_window_ms is None:
            return None
        return self.measured_unit_count * 1000 / self.throughput_window_ms


class MetricEstimateState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSTAINED = "abstained"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class LabelProbability(StrictModel):
    label_code: str
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)

    _safe_label = field_validator("label_code")(_safe_code)


def _validate_probabilities(
    probabilities: tuple[LabelProbability, ...],
) -> tuple[LabelProbability, ...]:
    labels = tuple(item.label_code for item in probabilities)
    if labels != tuple(sorted(labels)) or len(labels) != len(set(labels)):
        raise ValueError("label probabilities must be unique and label-sorted")
    if probabilities and not math.isclose(
        sum(item.probability for item in probabilities), 1.0, abs_tol=1e-6
    ):
        raise ValueError("label probabilities must sum to one")
    return probabilities


def _validate_value_shape(
    *,
    state: MetricEstimateState,
    value_kind: MetricValueKind,
    numeric_value: float | None,
    label_code: str | None,
    unknown_reason_code: str | None,
    abstention_reason_code: str | None,
    not_applicable_reason_code: str | None,
    failure_code: str | None,
) -> None:
    reasons = (
        unknown_reason_code,
        abstention_reason_code,
        not_applicable_reason_code,
        failure_code,
    )
    if state is MetricEstimateState.KNOWN:
        numeric_kind = value_kind in {
            MetricValueKind.CONTINUOUS,
            MetricValueKind.FRACTION,
        }
        if numeric_kind != (numeric_value is not None):
            raise ValueError("known metric value does not match its value kind")
        if numeric_kind == (label_code is not None):
            raise ValueError("known metric values require exactly one value representation")
        if any(reason is not None for reason in reasons):
            raise ValueError("known metric values cannot carry unavailable-state reasons")
        if value_kind is MetricValueKind.FRACTION and not 0 <= numeric_value <= 1:
            raise ValueError("known fractions must remain within 0..1")
        return

    if numeric_value is not None or label_code is not None:
        raise ValueError("unavailable metric states cannot carry a value")
    expected_reason = {
        MetricEstimateState.UNKNOWN: unknown_reason_code,
        MetricEstimateState.ABSTAINED: abstention_reason_code,
        MetricEstimateState.NOT_APPLICABLE: not_applicable_reason_code,
        MetricEstimateState.FAILED: failure_code,
    }[state]
    if expected_reason is None or sum(reason is not None for reason in reasons) != 1:
        raise ValueError("unavailable metric state requires exactly its matching reason")


class ModelVote(StrictModel):
    contract_version: Literal[MODEL_VOTE_CONTRACT_VERSION] = MODEL_VOTE_CONTRACT_VERSION
    vote_id: str
    execution_id: str
    model_run_id: str
    plan_fingerprint: str
    evidence_packet_fingerprint: str
    metric_question_fingerprint: str
    metric_key: str
    state: MetricEstimateState
    value_kind: MetricValueKind
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    probabilities: tuple[LabelProbability, ...] = Field(default=(), max_length=128)
    opaque_evidence_refs: tuple[str, ...] = Field(
        default=(), max_length=MAX_EVIDENCE_REFS
    )
    unknown_reason_code: str | None = None
    abstention_reason_code: str | None = None
    not_applicable_reason_code: str | None = None
    failure_code: str | None = None

    _safe_ids = field_validator(
        "vote_id",
        "execution_id",
        "model_run_id",
        "plan_fingerprint",
        "evidence_packet_fingerprint",
        "metric_question_fingerprint",
    )(_pseudonym)
    _safe_metric = field_validator("metric_key")(_safe_code)

    @field_validator(
        "label_code",
        "unknown_reason_code",
        "abstention_reason_code",
        "not_applicable_reason_code",
        "failure_code",
    )
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @field_validator("probabilities")
    @classmethod
    def canonical_probabilities(
        cls, values: tuple[LabelProbability, ...]
    ) -> tuple[LabelProbability, ...]:
        return _validate_probabilities(values)

    @field_validator("opaque_evidence_refs")
    @classmethod
    def canonical_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values)

    @model_validator(mode="after")
    def validate_vote(self) -> ModelVote:
        if len(
            {
                self.vote_id,
                self.execution_id,
                self.model_run_id,
                self.plan_fingerprint,
                self.evidence_packet_fingerprint,
                self.metric_question_fingerprint,
            }
        ) != 6:
            raise ValueError("vote and lineage identifiers must be distinct")
        _validate_value_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            unknown_reason_code=self.unknown_reason_code,
            abstention_reason_code=self.abstention_reason_code,
            not_applicable_reason_code=self.not_applicable_reason_code,
            failure_code=self.failure_code,
        )
        if self.state is MetricEstimateState.KNOWN:
            if self.confidence is None:
                raise ValueError("known model votes require calibrated confidence")
            categorical = self.value_kind in {
                MetricValueKind.BINARY,
                MetricValueKind.CATEGORICAL,
            }
            if categorical != bool(self.probabilities):
                raise ValueError("categorical votes require a full probability distribution")
            if categorical and self.label_code not in {
                item.label_code for item in self.probabilities
            }:
                raise ValueError("selected label is absent from the probability distribution")
        elif self.confidence is not None or self.probabilities:
            raise ValueError("unavailable votes cannot claim confidence")
        return self


class UncertaintyKind(StrEnum):
    CONFIDENCE = "confidence"
    INTERVAL = "interval"
    DISTRIBUTION = "distribution"
    NOT_QUANTIFIED = "not_quantified"


class EstimateUncertainty(StrictModel):
    kind: UncertaintyKind
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    lower_bound: float | None = Field(default=None, allow_inf_nan=False)
    upper_bound: float | None = Field(default=None, allow_inf_nan=False)
    confidence_level: float | None = Field(
        default=None, gt=0, lt=1, allow_inf_nan=False
    )
    entropy: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    reason_code: str | None = None

    @field_validator("reason_code")
    @classmethod
    def safe_optional_reason(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_uncertainty(self) -> EstimateUncertainty:
        if self.kind is UncertaintyKind.CONFIDENCE:
            valid = self.confidence is not None and all(
                value is None
                for value in (
                    self.lower_bound,
                    self.upper_bound,
                    self.confidence_level,
                    self.entropy,
                    self.reason_code,
                )
            )
        elif self.kind is UncertaintyKind.INTERVAL:
            valid = (
                self.lower_bound is not None
                and self.upper_bound is not None
                and self.lower_bound <= self.upper_bound
                and self.confidence_level is not None
                and self.confidence is None
                and self.entropy is None
                and self.reason_code is None
            )
        elif self.kind is UncertaintyKind.DISTRIBUTION:
            valid = self.entropy is not None and all(
                value is None
                for value in (
                    self.confidence,
                    self.lower_bound,
                    self.upper_bound,
                    self.confidence_level,
                    self.reason_code,
                )
            )
        else:
            valid = self.reason_code is not None and all(
                value is None
                for value in (
                    self.confidence,
                    self.lower_bound,
                    self.upper_bound,
                    self.confidence_level,
                    self.entropy,
                )
            )
        if not valid:
            raise ValueError("uncertainty fields do not match their declared kind")
        return self


class MetricEstimateSource(StrEnum):
    OBJECTIVE_EVIDENCE = "objective_evidence"
    DETERMINISTIC = "deterministic"
    MODEL_CASCADE = "model_cascade"
    HUMAN_ADJUDICATED = "human_adjudicated"


class MetricEstimate(StrictModel):
    contract_version: Literal[METRIC_ESTIMATE_CONTRACT_VERSION] = (
        METRIC_ESTIMATE_CONTRACT_VERSION
    )
    estimate_id: str
    execution_id: str
    plan_fingerprint: str
    evidence_packet_fingerprint: str
    metric_question_fingerprint: str
    metric_key: str
    source: MetricEstimateSource
    state: MetricEstimateState
    value_kind: MetricValueKind
    unit_code: str
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, gt=0)
    uncertainty: EstimateUncertainty | None = None
    evidence_coverage: float = Field(ge=0, le=1, allow_inf_nan=False)
    vote_ids: tuple[str, ...] = Field(default=(), max_length=32)
    adjudication_id: str | None = None
    unknown_reason_code: str | None = None
    abstention_reason_code: str | None = None
    not_applicable_reason_code: str | None = None
    failure_code: str | None = None
    created_at: datetime

    _safe_ids = field_validator(
        "estimate_id",
        "execution_id",
        "plan_fingerprint",
        "evidence_packet_fingerprint",
        "metric_question_fingerprint",
    )(_pseudonym)
    _safe_codes = field_validator("metric_key", "unit_code")(_safe_code)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("vote_ids")
    @classmethod
    def canonical_vote_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values)

    @field_validator("adjudication_id")
    @classmethod
    def safe_optional_adjudication(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator(
        "label_code",
        "unknown_reason_code",
        "abstention_reason_code",
        "not_applicable_reason_code",
        "failure_code",
    )
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_estimate(self) -> MetricEstimate:
        lineage_ids = {
            self.estimate_id,
            self.execution_id,
            self.plan_fingerprint,
            self.evidence_packet_fingerprint,
            self.metric_question_fingerprint,
            *self.vote_ids,
        }
        expected_lineage_count = 5 + len(self.vote_ids)
        if self.adjudication_id is not None:
            lineage_ids.add(self.adjudication_id)
            expected_lineage_count += 1
        if len(lineage_ids) != expected_lineage_count:
            raise ValueError("estimate and lineage identifiers must be distinct")
        _validate_value_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            unknown_reason_code=self.unknown_reason_code,
            abstention_reason_code=self.abstention_reason_code,
            not_applicable_reason_code=self.not_applicable_reason_code,
            failure_code=self.failure_code,
        )
        if self.state is MetricEstimateState.KNOWN:
            if self.uncertainty is None:
                raise ValueError("known estimates require explicit uncertainty")
        elif self.uncertainty is not None:
            raise ValueError("unavailable estimates cannot claim quantified uncertainty")

        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("fraction evidence requires both numerator and denominator")
        if self.numerator is not None:
            if self.value_kind is not MetricValueKind.FRACTION or self.numeric_value is None:
                raise ValueError("numerator and denominator are limited to known fractions")
            if not math.isclose(
                self.numeric_value,
                self.numerator / self.denominator,
                abs_tol=1e-9,
            ):
                raise ValueError("fraction value must equal numerator divided by denominator")

        if self.source is MetricEstimateSource.MODEL_CASCADE and not self.vote_ids:
            raise ValueError("model-cascade estimates require at least one model vote")
        if self.source is MetricEstimateSource.HUMAN_ADJUDICATED:
            if self.adjudication_id is None:
                raise ValueError("human-adjudicated estimates require an adjudication")
        elif self.adjudication_id is not None:
            raise ValueError("only human-adjudicated estimates reference adjudication")
        return self


class JudgmentSource(StrEnum):
    HUMAN = "human"
    OBJECTIVE_EVIDENCE = "objective_evidence"


class ImmutableJudgment(StrictModel):
    contract_version: Literal[IMMUTABLE_JUDGMENT_CONTRACT_VERSION] = (
        IMMUTABLE_JUDGMENT_CONTRACT_VERSION
    )
    judgment_id: str
    source: JudgmentSource
    adjudicator_id: str | None = None
    objective_evidence_fingerprint: str | None = None
    annotation_protocol_version: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    metric_key: str
    state: MetricEstimateState
    value_kind: MetricValueKind
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    unknown_reason_code: str | None = None
    abstention_reason_code: str | None = None
    not_applicable_reason_code: str | None = None
    created_at: datetime
    supersedes_judgment_id: str | None = None

    _safe_ids = field_validator(
        "judgment_id", "metric_question_fingerprint", "evidence_packet_fingerprint"
    )(_pseudonym)
    _safe_protocol = field_validator("annotation_protocol_version")(_safe_version)
    _safe_metric = field_validator("metric_key")(_safe_code)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator(
        "adjudicator_id", "objective_evidence_fingerprint", "supersedes_judgment_id"
    )
    @classmethod
    def safe_optional_ids(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator(
        "label_code",
        "unknown_reason_code",
        "abstention_reason_code",
        "not_applicable_reason_code",
    )
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_judgment(self) -> ImmutableJudgment:
        if self.state is MetricEstimateState.FAILED:
            raise ValueError("judgments abstain or stay unknown; they are never failed runs")
        _validate_value_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            unknown_reason_code=self.unknown_reason_code,
            abstention_reason_code=self.abstention_reason_code,
            not_applicable_reason_code=self.not_applicable_reason_code,
            failure_code=None,
        )
        if self.state is MetricEstimateState.KNOWN and self.confidence is None:
            raise ValueError("known judgments require confidence")
        if self.state is not MetricEstimateState.KNOWN and self.confidence is not None:
            raise ValueError("unavailable judgments cannot claim confidence")

        if self.source is JudgmentSource.HUMAN:
            if self.adjudicator_id is None or self.objective_evidence_fingerprint is not None:
                raise ValueError("human judgments require only a pseudonymous adjudicator")
        elif (
            self.objective_evidence_fingerprint is None or self.adjudicator_id is not None
        ):
            raise ValueError("objective judgments require only objective evidence provenance")
        if self.supersedes_judgment_id == self.judgment_id:
            raise ValueError("a judgment cannot supersede itself")
        return self


class AdjudicationTrigger(StrEnum):
    DISAGREEMENT = "disagreement"
    LOW_CONFIDENCE = "low_confidence"
    DRIFT = "drift"
    AUDIT = "audit"
    HIGH_VALUE = "high_value"
    FALSE_CONFIDENT_ERROR_REVIEW = "false_confident_error_review"


class AdjudicationState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class Adjudication(StrictModel):
    """Review of one pre-adjudication estimate; the final estimate is a new record.

    A later human-adjudicated ``MetricEstimate`` points to this bundle through
    ``adjudication_id``. This bundle deliberately does not point back to that
    final estimate, avoiding a circular identity graph.
    """

    contract_version: Literal[ADJUDICATION_CONTRACT_VERSION] = (
        ADJUDICATION_CONTRACT_VERSION
    )
    adjudication_id: str
    plan_fingerprint: str
    reviewed_estimate_id: str = Field(
        description=(
            "Identifier of the pre-adjudication estimate under review; never the "
            "identifier of the distinct final human-adjudicated estimate."
        )
    )
    trigger: AdjudicationTrigger
    state: AdjudicationState
    judgments: tuple[ImmutableJudgment, ...] = Field(min_length=1, max_length=32)
    selected_judgment_id: str | None = None
    final_state: MetricEstimateState | None = None
    final_numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    final_label_code: str | None = None
    unresolved_reason_code: str | None = None
    created_at: datetime

    _safe_ids = field_validator(
        "adjudication_id", "plan_fingerprint", "reviewed_estimate_id"
    )(_pseudonym)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("selected_judgment_id")
    @classmethod
    def safe_optional_judgment_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("final_label_code", "unresolved_reason_code")
    @classmethod
    def safe_optional_codes(cls, value: str | None) -> str | None:
        return None if value is None else _safe_code(value)

    @model_validator(mode="after")
    def validate_adjudication(self) -> Adjudication:
        if len(
            {
                self.adjudication_id,
                self.plan_fingerprint,
                self.reviewed_estimate_id,
                *(item.judgment_id for item in self.judgments),
            }
        ) != 3 + len(self.judgments):
            raise ValueError("adjudication, reviewed estimate, and judgments must be distinct")
        keys = tuple((item.created_at, item.judgment_id) for item in self.judgments)
        if keys != tuple(sorted(keys)) or len({item.judgment_id for item in self.judgments}) != len(
            self.judgments
        ):
            raise ValueError("judgments must be unique and chronologically sorted")
        if not any(item.source is JudgmentSource.HUMAN for item in self.judgments):
            raise ValueError("adjudication requires at least one human judgment")
        first = self.judgments[0]
        if any(
            item.metric_question_fingerprint != first.metric_question_fingerprint
            or item.evidence_packet_fingerprint != first.evidence_packet_fingerprint
            or item.metric_key != first.metric_key
            or item.value_kind is not first.value_kind
            for item in self.judgments
        ):
            raise ValueError("adjudication judgments must address one evidence-bound question")

        if self.state is AdjudicationState.RESOLVED:
            if self.selected_judgment_id is None or self.final_state is None:
                raise ValueError("resolved adjudication requires a selected judgment")
            if self.unresolved_reason_code is not None:
                raise ValueError("resolved adjudication cannot carry an unresolved reason")
            selected = next(
                (
                    item
                    for item in self.judgments
                    if item.judgment_id == self.selected_judgment_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("selected judgment is absent from the adjudication")
            if (
                self.final_state is not selected.state
                or self.final_numeric_value != selected.numeric_value
                or self.final_label_code != selected.label_code
            ):
                raise ValueError("resolved value must exactly match the selected judgment")
        else:
            if any(
                value is not None
                for value in (
                    self.selected_judgment_id,
                    self.final_state,
                    self.final_numeric_value,
                    self.final_label_code,
                )
            ) or self.unresolved_reason_code is None:
                raise ValueError("unresolved adjudication requires only a safe reason code")
        return self
