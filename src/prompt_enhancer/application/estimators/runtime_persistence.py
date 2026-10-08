"""Durable, content-free receipts for the first estimator runtime vertical.

The runtime database deliberately stores lineage, closed states, scalar values,
and opaque SHA-256 references only.  Redacted packet text remains in memory and
is never accepted by this persistence boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from ..jobs import AnalysisJobRecord
from .contracts import (
    EstimatorRoute,
    EstimatorStageKind,
    ExecutionDestination,
    MetricEstimateState,
    MetricValueKind,
    REMOTE_DESTINATIONS,
    RetentionClass,
    STAGE_ORDER,
)
from .runtime_contracts import (
    RuntimeEvidencePacketReceipt,
    RuntimeRetrievalScoreKind,
)


DURABLE_RUNTIME_AUTHORIZATION_VERSION = "durable-runtime-authorization-v1"
ESTIMATOR_RUNTIME_LAUNCH_VERSION = "estimator-runtime-launch-v1"
ESTIMATOR_RUNTIME_BINDING_VERSION = "estimator-runtime-binding-v1"
ESTIMATOR_RUNTIME_STATE_VERSION = "estimator-runtime-state-v1"
ESTIMATOR_RUNTIME_STAGE_ATTEMPT_VERSION = "estimator-runtime-stage-attempt-v1"
ESTIMATOR_RUNTIME_STAGE_OUTCOME_VERSION = "estimator-runtime-stage-outcome-v1"
ESTIMATOR_RUNTIME_CHECKPOINT_VERSION = "estimator-runtime-checkpoint-v1"
ESTIMATOR_RUNTIME_RETRIEVAL_VERSION = "estimator-runtime-retrieval-v1"
ESTIMATOR_RUNTIME_OBSERVATION_VERSION = "estimator-runtime-observation-v1"
MAX_RUNTIME_AUTHORIZATION_TTL = timedelta(minutes=10)
MAX_RUNTIME_REFS = 512

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_version(value: str) -> str:
    if (
        SAFE_VERSION_PATTERN.fullmatch(value) is None
        or value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[/\\]", value) is not None
        or "\\" in value
        or "://" in value
        or ".." in value.split("/")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("value must be a content-free version identifier")
    return value


def _code(value: str) -> str:
    if _SAFE_CODE.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _canonical_digest(value: StrictModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _RuntimePersistenceModel(StrictModel):
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
    ) -> _RuntimePersistenceModel:
        if update:
            raise TypeError("durable runtime contracts forbid update-copy bypass")
        return super().model_copy(deep=deep)


class DurableRuntimeAuthorizationKind(StrEnum):
    MANUAL_ONCE = "manual_once"
    AUTOMATION_ONCE = "automation_once"
    SYNTHETIC_TEST = "synthetic_test"


class EstimatorRuntimeState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


TERMINAL_ESTIMATOR_RUNTIME_STATES = frozenset(
    {
        EstimatorRuntimeState.PARTIAL,
        EstimatorRuntimeState.FAILED,
        EstimatorRuntimeState.CANCELLED,
        EstimatorRuntimeState.SUPERSEDED,
    }
)


class EstimatorRuntimeStageOutcomeState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class DurableRuntimePacketBinding(_RuntimePersistenceModel):
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str

    _safe_metric = field_validator("metric_key")(_code)
    _safe_digests = field_validator(
        "metric_question_fingerprint", "evidence_packet_fingerprint"
    )(_digest)


class DurableRuntimeAuthorizationReceipt(_RuntimePersistenceModel):
    """One-shot authority for one exact job, execution, window, and packet set."""

    contract_version: Literal[DURABLE_RUNTIME_AUTHORIZATION_VERSION] = (
        DURABLE_RUNTIME_AUTHORIZATION_VERSION
    )
    authorization_id: str
    job_id: str
    execution_id: str
    kind: DurableRuntimeAuthorizationKind
    provider: Provider
    destination: ExecutionDestination
    retention_class: RetentionClass
    project_id: str
    session_id: str
    session_revision_id: str
    window_fingerprint: str
    input_fingerprint: str
    provenance_fingerprint: str
    plan_fingerprint: str
    route: EstimatorRoute
    provider_schema_version: str
    redactor_version: str
    redactor_sha256: str
    packet_bindings: tuple[DurableRuntimePacketBinding, ...] = Field(
        min_length=1, max_length=100
    )
    automation_grant_id: str | None = None
    issued_at: datetime
    expires_at: datetime
    one_shot: Literal[True] = True
    preview_text_retained: Literal[False] = False
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _safe_digests = field_validator(
        "authorization_id",
        "job_id",
        "execution_id",
        "project_id",
        "session_id",
        "session_revision_id",
        "window_fingerprint",
        "input_fingerprint",
        "provenance_fingerprint",
        "plan_fingerprint",
        "redactor_sha256",
    )(_digest)
    _safe_versions = field_validator(
        "provider_schema_version", "redactor_version"
    )(_safe_version)
    _utc_times = field_validator("issued_at", "expires_at")(_utc)

    @field_validator("automation_grant_id")
    @classmethod
    def safe_optional_grant(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("packet_bindings")
    @classmethod
    def canonical_packets(
        cls, values: tuple[DurableRuntimePacketBinding, ...]
    ) -> tuple[DurableRuntimePacketBinding, ...]:
        keys = tuple(item.metric_key for item in values)
        packets = tuple(item.evidence_packet_fingerprint for item in values)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("packet bindings must be unique and metric-key sorted")
        if len(packets) != len(set(packets)):
            raise ValueError("each metric requires a distinct packet")
        return values

    @model_validator(mode="after")
    def coherent_authority(self) -> DurableRuntimeAuthorizationReceipt:
        if not self.issued_at < self.expires_at <= self.issued_at + MAX_RUNTIME_AUTHORIZATION_TTL:
            raise ValueError("runtime authorization must use the ten-minute TTL bound")
        if self.kind is DurableRuntimeAuthorizationKind.AUTOMATION_ONCE:
            if self.automation_grant_id is None:
                raise ValueError("automation authority requires its exact grant")
            if self.destination in REMOTE_DESTINATIONS:
                raise ValueError("automation cannot authorize remote execution")
        elif self.automation_grant_id is not None:
            raise ValueError("only automation authority can bind an automation grant")
        if self.kind is DurableRuntimeAuthorizationKind.SYNTHETIC_TEST:
            if (
                self.provider is not Provider.SYNTHETIC
                or self.destination is not ExecutionDestination.SYNTHETIC_TEST
                or self.retention_class is not RetentionClass.SYNTHETIC
            ):
                raise ValueError("synthetic authority requires synthetic provenance")
        elif self.provider is Provider.SYNTHETIC:
            raise ValueError("real authority cannot claim the synthetic provider")
        allowed_destinations = {
            Provider.SYNTHETIC: {ExecutionDestination.SYNTHETIC_TEST},
            Provider.CODEX: {
                ExecutionDestination.LOCAL_DEVICE,
                ExecutionDestination.CODEX_CLI,
                ExecutionDestination.OPENAI_API,
            },
            Provider.CLAUDE_CODE: {
                ExecutionDestination.LOCAL_DEVICE,
                ExecutionDestination.ANTHROPIC_API,
                ExecutionDestination.CLAUDE_API,
                ExecutionDestination.MANUAL_IMPORT,
            },
        }
        if self.destination not in allowed_destinations[self.provider]:
            raise ValueError("provider and destination are incompatible")
        local_pair = (
            self.destination is ExecutionDestination.LOCAL_DEVICE
            and self.retention_class is RetentionClass.LOCAL_EPHEMERAL
        )
        synthetic_pair = (
            self.destination is ExecutionDestination.SYNTHETIC_TEST
            and self.retention_class is RetentionClass.SYNTHETIC
        )
        remote_pair = (
            self.destination in REMOTE_DESTINATIONS
            and self.retention_class
            in {
                RetentionClass.PROVIDER_ZERO_DAY,
                RetentionClass.PROVIDER_30_DAY,
                RetentionClass.PROVIDER_DISCLOSED_OTHER,
            }
        )
        manual_pair = (
            self.destination is ExecutionDestination.MANUAL_IMPORT
            and self.retention_class is RetentionClass.MANUAL_EXPORT
        )
        if not (local_pair or synthetic_pair or remote_pair or manual_pair):
            raise ValueError("destination and retention class are incompatible")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorRuntimeLaunch(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_LAUNCH_VERSION] = (
        ESTIMATOR_RUNTIME_LAUNCH_VERSION
    )
    authorization: DurableRuntimeAuthorizationReceipt
    packet_receipts: tuple[RuntimeEvidencePacketReceipt, ...] = Field(
        min_length=1, max_length=100
    )
    consumed_at: datetime
    max_attempts: int = Field(default=3, ge=1, le=5)

    _utc_consumed = field_validator("consumed_at")(_utc)

    @model_validator(mode="after")
    def exact_packet_lineage(self) -> EstimatorRuntimeLaunch:
        authorization = DurableRuntimeAuthorizationReceipt.model_validate(
            self.authorization.model_dump(mode="python")
        )
        if not authorization.issued_at <= self.consumed_at < authorization.expires_at:
            raise ValueError("authorization must be consumed before its expiry")
        receipts = tuple(
            RuntimeEvidencePacketReceipt.model_validate(item.model_dump(mode="python"))
            for item in self.packet_receipts
        )
        keys = tuple(item.metric_key for item in receipts)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("packet receipts must be unique and metric-key sorted")
        expected = tuple(
            (item.metric_key, item.metric_question_fingerprint, item.packet_fingerprint)
            for item in receipts
        )
        actual = tuple(
            (
                item.metric_key,
                item.metric_question_fingerprint,
                item.evidence_packet_fingerprint,
            )
            for item in authorization.packet_bindings
        )
        if expected != actual:
            raise ValueError("authorization must bind the exact packet receipt set")
        if any(
            item.plan_fingerprint != authorization.plan_fingerprint
            or item.route is not authorization.route
            or item.provider is not authorization.provider
            or item.provider_schema_version != authorization.provider_schema_version
            or item.redactor_version != authorization.redactor_version
            or item.redactor_sha256 != authorization.redactor_sha256
            for item in receipts
        ):
            raise ValueError("packet provenance must match the exact authorization")
        return self


class EstimatorRuntimeJobBinding(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_BINDING_VERSION] = (
        ESTIMATOR_RUNTIME_BINDING_VERSION
    )
    job_id: str
    execution_id: str
    authorization_id: str
    authorization_fingerprint: str
    plan_fingerprint: str
    route: EstimatorRoute
    provider: Provider
    project_id: str
    session_id: str
    session_revision_id: str
    window_fingerprint: str
    input_fingerprint: str
    provenance_fingerprint: str
    created_at: datetime

    _safe_ids = field_validator(
        "job_id",
        "execution_id",
        "authorization_id",
        "authorization_fingerprint",
        "plan_fingerprint",
        "project_id",
        "session_id",
        "session_revision_id",
        "window_fingerprint",
        "input_fingerprint",
        "provenance_fingerprint",
    )(_digest)
    _utc_created = field_validator("created_at")(_utc)


class EstimatorRuntimeStateReceipt(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_STATE_VERSION] = (
        ESTIMATOR_RUNTIME_STATE_VERSION
    )
    state_receipt_id: str
    execution_id: str
    sequence: int = Field(ge=0, le=1_000_000)
    previous_state_receipt_fingerprint: str | None = None
    state: EstimatorRuntimeState
    reason_code: str
    recorded_at: datetime

    _safe_ids = field_validator("state_receipt_id", "execution_id")(_digest)
    _safe_reason = field_validator("reason_code")(_code)
    _utc_recorded = field_validator("recorded_at")(_utc)

    @field_validator("previous_state_receipt_fingerprint")
    @classmethod
    def safe_previous(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorRuntimeStageAttemptReceipt(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_STAGE_ATTEMPT_VERSION] = (
        ESTIMATOR_RUNTIME_STAGE_ATTEMPT_VERSION
    )
    attempt_id: str
    execution_id: str
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind
    stage_fingerprint: str
    attempt_ordinal: int = Field(ge=1, le=100)
    started_at: datetime

    _safe_ids = field_validator(
        "attempt_id",
        "execution_id",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "stage_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_code)
    _utc_started = field_validator("started_at")(_utc)

    @model_validator(mode="after")
    def exact_stage(self) -> EstimatorRuntimeStageAttemptReceipt:
        if self.stage_kind is not STAGE_ORDER[self.stage_ordinal - 1]:
            raise ValueError("stage ordinal and kind disagree")
        return self


class EstimatorRuntimeStageOutcomeReceipt(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_STAGE_OUTCOME_VERSION] = (
        ESTIMATOR_RUNTIME_STAGE_OUTCOME_VERSION
    )
    outcome_id: str
    attempt_id: str
    execution_id: str
    state: EstimatorRuntimeStageOutcomeState
    reason_code: str
    output_fingerprint: str | None = None
    finished_at: datetime

    _safe_ids = field_validator("outcome_id", "attempt_id", "execution_id")(_digest)
    _safe_reason = field_validator("reason_code")(_code)
    _utc_finished = field_validator("finished_at")(_utc)

    @field_validator("output_fingerprint")
    @classmethod
    def safe_output(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def output_shape(self) -> EstimatorRuntimeStageOutcomeReceipt:
        if (self.state is EstimatorRuntimeStageOutcomeState.COMPLETED) != (
            self.output_fingerprint is not None
        ):
            raise ValueError("completed stage outcomes require exactly one output")
        return self


class EstimatorRuntimeCheckpointReceipt(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_CHECKPOINT_VERSION] = (
        ESTIMATOR_RUNTIME_CHECKPOINT_VERSION
    )
    checkpoint_id: str
    execution_id: str
    metric_key: str
    sequence: int = Field(ge=0, le=1_000_000)
    previous_checkpoint_fingerprint: str | None = None
    last_completed_stage_ordinal: int = Field(ge=0, le=7)
    next_stage_ordinal: int | None = Field(default=None, ge=1, le=7)
    restart_generation: int = Field(ge=0, le=1_000_000)
    state: EstimatorRuntimeState
    reason_code: str
    recorded_at: datetime

    _safe_ids = field_validator("checkpoint_id", "execution_id")(_digest)
    _safe_metric = field_validator("metric_key")(_code)
    _safe_reason = field_validator("reason_code")(_code)
    _utc_recorded = field_validator("recorded_at")(_utc)

    @field_validator("previous_checkpoint_fingerprint")
    @classmethod
    def safe_previous(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def coherent_checkpoint(self) -> EstimatorRuntimeCheckpointReceipt:
        expected_next = self.last_completed_stage_ordinal + 1
        if self.state in TERMINAL_ESTIMATOR_RUNTIME_STATES:
            if self.next_stage_ordinal is not None:
                raise ValueError("terminal checkpoints cannot schedule another stage")
        elif self.next_stage_ordinal != expected_next:
            raise ValueError("checkpoint next stage must follow the completed stage")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorRuntimeRetrievalHit(_RuntimePersistenceModel):
    evidence_reference_id: str
    rank: int = Field(ge=1, le=MAX_RUNTIME_REFS)
    raw_score: float = Field(allow_inf_nan=False)

    _safe_ref = field_validator("evidence_reference_id")(_digest)


class EstimatorRuntimeRetrievalReceipt(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_RETRIEVAL_VERSION] = (
        ESTIMATOR_RUNTIME_RETRIEVAL_VERSION
    )
    retrieval_id: str
    execution_id: str
    attempt_id: str
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    stage_ordinal: Literal[2] = 2
    stage_kind: Literal[EstimatorStageKind.BM25_RETRIEVAL] = (
        EstimatorStageKind.BM25_RETRIEVAL
    )
    score_kind: Literal[RuntimeRetrievalScoreKind.BM25_RAW] = (
        RuntimeRetrievalScoreKind.BM25_RAW
    )
    query_fingerprint: str
    candidate_index_fingerprint: str
    candidate_reference_ids: tuple[str, ...] = Field(max_length=MAX_RUNTIME_REFS)
    hits: tuple[EstimatorRuntimeRetrievalHit, ...] = Field(max_length=MAX_RUNTIME_REFS)
    created_at: datetime
    calibration_state: Literal["not_assessed"] = "not_assessed"
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "retrieval_id",
        "execution_id",
        "attempt_id",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "query_fingerprint",
        "candidate_index_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_code)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("candidate_reference_ids")
    @classmethod
    def canonical_candidates(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("candidate references must be unique and sorted")
        return tuple(_digest(value) for value in values)

    @field_validator("hits")
    @classmethod
    def canonical_hits(
        cls, values: tuple[EstimatorRuntimeRetrievalHit, ...]
    ) -> tuple[EstimatorRuntimeRetrievalHit, ...]:
        if tuple(item.rank for item in values) != tuple(range(1, len(values) + 1)):
            raise ValueError("retrieval ranks must be contiguous")
        if len({item.evidence_reference_id for item in values}) != len(values):
            raise ValueError("retrieval hits must be unique")
        return values

    @model_validator(mode="after")
    def hits_are_candidates(self) -> EstimatorRuntimeRetrievalReceipt:
        candidates = set(self.candidate_reference_ids)
        if any(item.evidence_reference_id not in candidates for item in self.hits):
            raise ValueError("retrieval hits must come from the candidate set")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorRuntimeMetricObservation(_RuntimePersistenceModel):
    contract_version: Literal[ESTIMATOR_RUNTIME_OBSERVATION_VERSION] = (
        ESTIMATOR_RUNTIME_OBSERVATION_VERSION
    )
    observation_id: str
    execution_id: str
    attempt_id: str
    metric_key: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    stage_ordinal: Literal[1] = 1
    state: MetricEstimateState
    value_kind: MetricValueKind
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, gt=0)
    reason_code: str | None = None
    opaque_evidence_refs: tuple[str, ...] = Field(max_length=MAX_RUNTIME_REFS)
    observed_at: datetime
    calibration_state: Literal["not_assessed"] = "not_assessed"
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False
    product_metric_write_allowed: Literal[False] = False

    _safe_ids = field_validator(
        "observation_id",
        "execution_id",
        "attempt_id",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_digest)
    _safe_metric = field_validator("metric_key")(_code)
    _utc_observed = field_validator("observed_at")(_utc)

    @field_validator("label_code", "reason_code")
    @classmethod
    def safe_optional_code(cls, value: str | None) -> str | None:
        return None if value is None else _code(value)

    @field_validator("opaque_evidence_refs")
    @classmethod
    def canonical_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("evidence references must be unique and sorted")
        return tuple(_digest(value) for value in values)

    @model_validator(mode="after")
    def truthful_value(self) -> EstimatorRuntimeMetricObservation:
        numeric_kind = self.value_kind in {
            MetricValueKind.CONTINUOUS,
            MetricValueKind.FRACTION,
        }
        if self.state is MetricEstimateState.KNOWN:
            if numeric_kind != (self.numeric_value is not None):
                raise ValueError("known observation value kind disagrees")
            if numeric_kind == (self.label_code is not None) or self.reason_code is not None:
                raise ValueError("known observations require exactly one value")
        elif (
            self.numeric_value is not None
            or self.label_code is not None
            or self.reason_code is None
        ):
            raise ValueError("unavailable observations require only a reason")
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("fraction counts must be an exact pair")
        if self.numerator is not None:
            if (
                self.value_kind is not MetricValueKind.FRACTION
                or self.state is not MetricEstimateState.KNOWN
                or self.numeric_value is None
                or self.numerator > self.denominator
                or not math.isclose(
                    self.numeric_value,
                    self.numerator / self.denominator,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError("fraction counts must prove the exact observation")
        return self

    @property
    def canonical_fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorRuntimeSnapshot(_RuntimePersistenceModel):
    binding: EstimatorRuntimeJobBinding
    authorization: DurableRuntimeAuthorizationReceipt
    job: AnalysisJobRecord
    states: tuple[EstimatorRuntimeStateReceipt, ...]
    attempts: tuple[EstimatorRuntimeStageAttemptReceipt, ...]
    outcomes: tuple[EstimatorRuntimeStageOutcomeReceipt, ...]
    checkpoints: tuple[EstimatorRuntimeCheckpointReceipt, ...]
    retrievals: tuple[EstimatorRuntimeRetrievalReceipt, ...]
    observations: tuple[EstimatorRuntimeMetricObservation, ...]
    authorization_consumed: Literal[True] = True
    authorization_revoked: bool
    activation_allowed: Literal[False] = False


class EstimatorRuntimePrivacyDeleteOutcome(_RuntimePersistenceModel):
    execution_deleted: bool
    plan_retained: bool
    durable_revocation_retained: bool


class EstimatorRuntimeRepository(Protocol):
    def launch(self, launch: EstimatorRuntimeLaunch) -> EstimatorRuntimeSnapshot: ...

    def get_by_job(self, job_id: str) -> EstimatorRuntimeSnapshot | None: ...

    def get_by_execution(self, execution_id: str) -> EstimatorRuntimeSnapshot | None: ...

    def authorization_is_valid(self, job_id: str, *, now: datetime) -> bool: ...

    def reconcile_expired(self, *, now: datetime) -> None: ...

    def reconcile_invalid_automation_grants(self, *, now: datetime) -> None: ...

    def revoke_authorization(
        self, authorization_id: str, *, revoked_at: datetime
    ) -> None: ...

    def cancel(self, job_id: str, *, cancelled_at: datetime) -> EstimatorRuntimeSnapshot: ...

    def append_state(self, receipt: EstimatorRuntimeStateReceipt) -> None: ...

    def append_stage_attempt(
        self, receipt: EstimatorRuntimeStageAttemptReceipt
    ) -> None: ...

    def append_metric_observation(
        self, receipt: EstimatorRuntimeMetricObservation
    ) -> None: ...

    def append_retrieval(self, receipt: EstimatorRuntimeRetrievalReceipt) -> None: ...

    def append_stage_outcome(
        self, receipt: EstimatorRuntimeStageOutcomeReceipt
    ) -> None: ...

    def append_checkpoint(
        self, receipt: EstimatorRuntimeCheckpointReceipt
    ) -> None: ...

    def delete_execution_for_privacy(
        self, execution_id: str
    ) -> EstimatorRuntimePrivacyDeleteOutcome: ...


__all__ = [
    "DURABLE_RUNTIME_AUTHORIZATION_VERSION",
    "DurableRuntimeAuthorizationKind",
    "DurableRuntimeAuthorizationReceipt",
    "DurableRuntimePacketBinding",
    "EstimatorRuntimeCheckpointReceipt",
    "EstimatorRuntimeJobBinding",
    "EstimatorRuntimeLaunch",
    "EstimatorRuntimeMetricObservation",
    "EstimatorRuntimePrivacyDeleteOutcome",
    "EstimatorRuntimeRepository",
    "EstimatorRuntimeRetrievalHit",
    "EstimatorRuntimeRetrievalReceipt",
    "EstimatorRuntimeSnapshot",
    "EstimatorRuntimeStageAttemptReceipt",
    "EstimatorRuntimeStageOutcomeReceipt",
    "EstimatorRuntimeStageOutcomeState",
    "EstimatorRuntimeState",
    "EstimatorRuntimeStateReceipt",
    "TERMINAL_ESTIMATOR_RUNTIME_STATES",
]
