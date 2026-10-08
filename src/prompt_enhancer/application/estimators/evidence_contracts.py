"""Content-free, non-activating calibration-evidence contracts.

These v17 application contracts are deliberately additive.  They describe the
dynamic receipts produced after a v16 estimator campaign has been registered,
but they neither embed that static campaign nor represent an activation
decision.  Prompt text, evidence text, model output, rationales, paths, URIs,
and reviewer prose are outside this boundary.

All persistent identifiers are opaque SHA-256 values.  Human-readable values
are closed enumerations or short, path-free/version-free codes.  Caller-supplied
summary counts and set fingerprints are intentionally absent: manifests derive
them from their canonically ordered members.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .contracts import (
    MODEL_STAGE_KINDS,
    EstimatorStageKind,
    ExecutionDestination,
    MetricValueKind,
    ModelExecutionMode,
    ModelSource,
    RetentionClass,
)
from .gate_contracts import StabilityCondition


ATTEMPT_LAUNCH_RECEIPT_V1 = "attempt-launch-receipt-v1"
SERVED_IDENTITY_V1 = "served-identity-v1"
TOKEN_USAGE_PROVENANCE_V1 = "token-usage-provenance-v1"
RESOURCE_USAGE_PROVENANCE_V1 = "resource-usage-provenance-v1"
COST_PROVENANCE_V1 = "cost-provenance-v1"
QUEUE_PROVENANCE_V1 = "queue-provenance-v1"
ATTEMPT_TERMINAL_OUTCOME_V1 = "attempt-terminal-outcome-v1"
STRUCTURED_ESTIMATE_RECEIPT_V1 = "structured-estimate-receipt-v1"
EXPECTED_ATTEMPT_V2 = "expected-attempt-v2"
EXPECTED_ATTEMPT_MANIFEST_V2 = "expected-attempt-manifest-v2"
HOLDOUT_ACCESS_EVENT_V1 = "holdout-access-event-v1"
HOLDOUT_ACCESS_GAP_V1 = "holdout-access-gap-v1"
HOLDOUT_ACCESS_MANIFEST_V1 = "holdout-access-manifest-v1"
HOLDOUT_ACCESS_AUDIT_V1 = "holdout-access-audit-v1"
PRIVACY_FINDING_V1 = "privacy-finding-v1"
PRIVACY_SCAN_MANIFEST_V1 = "privacy-scan-manifest-v1"
PRIVACY_SCAN_RECEIPT_V1 = "privacy-scan-receipt-v1"
AUTHORITATIVE_CANDIDATE_PROJECTION_V2 = (
    "authoritative-candidate-projection-v2"
)
AUTHORITATIVE_DETERMINISTIC_BASELINE_PROJECTION_V1 = (
    "authoritative-deterministic-baseline-projection-v1"
)
OBJECTIVE_TRUTH_PROJECTION_V1 = "objective-truth-projection-v1"
BLIND_HUMAN_JUDGMENT_INPUT_V1 = "blind-human-judgment-input-v1"
BLIND_HUMAN_ADJUDICATION_INPUT_V1 = "blind-human-adjudication-input-v1"
STABILITY_TRIAL_RECEIPT_V1 = "stability-trial-receipt-v1"
STABILITY_SERIES_MANIFEST_V1 = "stability-series-manifest-v1"
CALIBRATION_EVIDENCE_SUBMISSION_V1 = "calibration-evidence-submission-v1"

MAX_ATTEMPTS = 20_000
MAX_CASE_EVIDENCE = 20_000
MAX_FINDINGS = 20_000
MAX_TOKEN_COUNT = 9_007_199_254_740_991
MAX_BYTE_COUNT = 9_007_199_254_740_991
MAX_DURATION_MS = 604_800_000
MAX_COST_MICROUSD = 9_007_199_254_740_991

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def _canonical_payload_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_digest(model: StrictModel) -> str:
    return _canonical_payload_digest(model.model_dump(mode="json"))


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    if ".." in value:
        raise ValueError("content-free codes cannot contain path traversal")
    return value


def _optional_code(value: str | None) -> str | None:
    return None if value is None else _safe_code(value)


def _safe_version(value: str) -> str:
    if _SAFE_VERSION_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a path-free, URI-free version identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _canonical_digests(
    values: tuple[str, ...], *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not allow_empty and not values:
        raise ValueError("digest set may not be empty")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("digests must be unique and sorted")
    return tuple(_digest(value) for value in values)


def _finite_nonnegative(value: Any, *, field_name: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    if number == 0 and math.copysign(1.0, number) < 0:
        raise ValueError(f"{field_name} cannot be negative zero")
    return number


def _finite_bounded(value: Any, *, field_name: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{field_name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or abs(number) > 1e308:
        raise ValueError(f"{field_name} must be finite and bounded")
    if number == 0 and math.copysign(1.0, number) < 0:
        raise ValueError(f"{field_name} cannot be negative zero")
    return number


def _probability(value: Any) -> float:
    number = _finite_nonnegative(value, field_name="probability")
    if number > 1:
        raise ValueError("probability must be between zero and one")
    return number


def _bounded_nonnegative_int(value: Any, *, upper: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not 0 <= value <= upper:
        raise ValueError(f"{field_name} is outside its allowed range")
    return value


def _validate_label_shape(
    *,
    state: CalibrationValueState,
    value_kind: MetricValueKind,
    numeric_value: float | None,
    label_code: str | None,
    confidence: float | None,
    reason_code: str | None,
    confidence_required: bool,
) -> None:
    numeric_kind = value_kind in {MetricValueKind.CONTINUOUS, MetricValueKind.FRACTION}
    if state is CalibrationValueState.KNOWN:
        if reason_code is not None:
            raise ValueError("known values cannot carry an unavailable reason")
        if numeric_kind != (numeric_value is not None):
            raise ValueError("known value shape does not match its value kind")
        if numeric_kind == (label_code is not None):
            raise ValueError("known value must contain exactly one value representation")
        if confidence_required != (confidence is not None):
            raise ValueError("confidence presence does not match projection kind")
        if (
            value_kind is MetricValueKind.FRACTION
            and numeric_value is not None
            and not 0 <= numeric_value <= 1
        ):
            raise ValueError("fraction values must remain within zero and one")
    elif any(value is not None for value in (numeric_value, label_code, confidence)):
        raise ValueError("unavailable values cannot claim a value or confidence")
    elif reason_code is None:
        raise ValueError("unavailable values require a safe reason code")


class ServedIdentityState(StrEnum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


class AttemptTerminalState(StrEnum):
    SUCCESS = "success"
    REFUSAL = "refusal"
    ERROR = "error"
    OOM = "oom"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    WORKER_LOST = "worker_lost"


class MeasurementState(StrEnum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class AttemptApprovalKind(StrEnum):
    NOT_REQUIRED_LOCAL = "not_required_local"
    FRESH_REDACTION_PREVIEW = "fresh_redaction_preview"
    MANUAL_IMPORT = "manual_import"
    SYNTHETIC_TEST = "synthetic_test"


class CalibrationValueState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSTAINED = "abstained"
    NOT_APPLICABLE = "not_applicable"


class HoldoutActorKind(StrEnum):
    CANDIDATE_RUNNER = "candidate_runner"
    DETERMINISTIC_BASELINE = "deterministic_baseline"
    INDEPENDENT_LABELER = "independent_labeler"
    ADJUDICATOR = "adjudicator"
    SYSTEM_AUDITOR = "system_auditor"


class HoldoutAccessKind(StrEnum):
    CASE_INPUT_READ = "case_input_read"
    CANDIDATE_OUTPUT_READ = "candidate_output_read"
    REFERENCE_TRUTH_READ = "reference_truth_read"
    OBJECTIVE_TRUTH_READ = "objective_truth_read"
    LABEL_WRITE = "label_write"


PROHIBITED_PRE_UNSEAL_ACCESS_KINDS = frozenset(
    {HoldoutAccessKind.REFERENCE_TRUTH_READ, HoldoutAccessKind.OBJECTIVE_TRUTH_READ}
)

AUTHORIZED_HOLDOUT_ACCESS_PAIRS = frozenset(
    {
        (HoldoutActorKind.CANDIDATE_RUNNER, HoldoutAccessKind.CASE_INPUT_READ),
        (HoldoutActorKind.DETERMINISTIC_BASELINE, HoldoutAccessKind.CASE_INPUT_READ),
        (HoldoutActorKind.INDEPENDENT_LABELER, HoldoutAccessKind.CASE_INPUT_READ),
        (HoldoutActorKind.INDEPENDENT_LABELER, HoldoutAccessKind.LABEL_WRITE),
        (HoldoutActorKind.ADJUDICATOR, HoldoutAccessKind.CASE_INPUT_READ),
        (HoldoutActorKind.ADJUDICATOR, HoldoutAccessKind.REFERENCE_TRUTH_READ),
        (HoldoutActorKind.ADJUDICATOR, HoldoutAccessKind.OBJECTIVE_TRUTH_READ),
        (HoldoutActorKind.ADJUDICATOR, HoldoutAccessKind.LABEL_WRITE),
        *((HoldoutActorKind.SYSTEM_AUDITOR, kind) for kind in HoldoutAccessKind),
    }
)


class PrivacyFindingCategory(StrEnum):
    PROMPT_TEXT = "prompt_text"
    EVIDENCE_TEXT = "evidence_text"
    MODEL_OUTPUT_TEXT = "model_output_text"
    REASONING_TRACE = "reasoning_trace"
    REVIEWER_PROSE = "reviewer_prose"
    FILESYSTEM_PATH = "filesystem_path"
    URI = "uri"
    CREDENTIAL = "credential"
    PERSONAL_DATA = "personal_data"
    PROVIDER_IDENTIFIER = "provider_identifier"


class ObjectiveTruthKind(StrEnum):
    TEST_RESULT = "test_result"
    ACCEPTANCE_ARTIFACT = "acceptance_artifact"
    PROVIDER_VERIFICATION = "provider_verification"
    HUMAN_VERIFIED_ARTIFACT = "human_verified_artifact"


class HumanParticipantKind(StrEnum):
    INDEPENDENT_ANNOTATOR = "independent_annotator"
    DOMAIN_EXPERT = "domain_expert"
    ADJUDICATOR = "adjudicator"


class BlindAdjudicationResolution(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class AttemptLaunchReceiptV1(StrictModel):
    """Immutable requested identity and reviewed runner boundary for one launch."""

    contract_version: Literal[ATTEMPT_LAUNCH_RECEIPT_V1] = (
        ATTEMPT_LAUNCH_RECEIPT_V1
    )
    launch_id: str
    campaign_id: str
    attempt_id: str
    execution_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    constellation_stage_fingerprint: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind
    stage_configuration_sha256: str
    model_artifact_fingerprint: str
    requested_source: ModelSource
    requested_model_id: str
    requested_revision: str
    requested_execution_mode: ModelExecutionMode
    runner_adapter_key: str
    runner_adapter_version: str
    runner_configuration_sha256: str
    response_schema_version: str
    destination: ExecutionDestination
    retention_class: RetentionClass
    approval_kind: AttemptApprovalKind
    approval_id: str | None = None
    redaction_preview_fingerprint: str | None = None
    approved_at: datetime | None = None
    launched_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "launch_id",
        "campaign_id",
        "attempt_id",
        "execution_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "constellation_stage_fingerprint",
        "stage_configuration_sha256",
        "model_artifact_fingerprint",
        "runner_configuration_sha256",
    )(_digest)
    _versions = field_validator(
        "requested_model_id",
        "requested_revision",
        "runner_adapter_key",
        "runner_adapter_version",
        "response_schema_version",
    )(_safe_version)
    _times = field_validator("approved_at", "launched_at")(
        lambda value: None if value is None else _utc(value)
    )

    @field_validator("approval_id", "redaction_preview_fingerprint")
    @classmethod
    def optional_digests(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def validate_launch(self) -> AttemptLaunchReceiptV1:
        if self.stage_kind not in MODEL_STAGE_KINDS:
            raise ValueError("attempt launch must name a model-bearing plan stage")
        if len(
            {
                self.launch_id,
                self.campaign_id,
                self.attempt_id,
                self.execution_id,
                self.case_id,
                self.plan_fingerprint,
                self.metric_question_fingerprint,
                self.evidence_packet_fingerprint,
            }
        ) != 8:
            raise ValueError("launch and lineage identifiers must be distinct")

        remote = self.destination in {
            ExecutionDestination.OPENAI_API,
            ExecutionDestination.ANTHROPIC_API,
            ExecutionDestination.CODEX_CLI,
            ExecutionDestination.CLAUDE_API,
        }
        approval_values = (
            self.approval_id,
            self.redaction_preview_fingerprint,
            self.approved_at,
        )
        if remote:
            if (
                self.approval_kind is not AttemptApprovalKind.FRESH_REDACTION_PREVIEW
                or any(value is None for value in approval_values)
                or self.retention_class
                in {
                    RetentionClass.LOCAL_EPHEMERAL,
                    RetentionClass.MANUAL_EXPORT,
                    RetentionClass.SYNTHETIC,
                }
            ):
                raise ValueError("remote attempts require a fresh preview approval")
            assert self.approved_at is not None
            if self.approved_at > self.launched_at:
                raise ValueError("attempt cannot launch before approval")
        elif self.destination is ExecutionDestination.LOCAL_DEVICE:
            if (
                self.approval_kind is not AttemptApprovalKind.NOT_REQUIRED_LOCAL
                or self.retention_class is not RetentionClass.LOCAL_EPHEMERAL
                or any(value is not None for value in approval_values)
            ):
                raise ValueError("local attempts require the local-only disclosure")
        elif self.destination is ExecutionDestination.SYNTHETIC_TEST:
            if (
                self.approval_kind is not AttemptApprovalKind.SYNTHETIC_TEST
                or self.retention_class is not RetentionClass.SYNTHETIC
                or any(value is not None for value in approval_values)
            ):
                raise ValueError("synthetic attempts require synthetic disclosure")
        elif (
            self.destination is not ExecutionDestination.MANUAL_IMPORT
            or self.approval_kind is not AttemptApprovalKind.MANUAL_IMPORT
            or self.retention_class is not RetentionClass.MANUAL_EXPORT
            or any(value is not None for value in approval_values)
        ):
            raise ValueError("manual imports require the manual-import disclosure")

        expected_destination_by_source = {
            ModelSource.LOCAL_WEIGHTS: {ExecutionDestination.LOCAL_DEVICE},
            ModelSource.OPENAI_API: {ExecutionDestination.OPENAI_API},
            ModelSource.ANTHROPIC_API: {
                ExecutionDestination.ANTHROPIC_API,
                ExecutionDestination.CLAUDE_API,
            },
            ModelSource.CODEX_CLI: {ExecutionDestination.CODEX_CLI},
            ModelSource.CLAUDE_CLI: {ExecutionDestination.MANUAL_IMPORT},
            ModelSource.SYNTHETIC: {ExecutionDestination.SYNTHETIC_TEST},
        }
        if self.destination not in expected_destination_by_source[self.requested_source]:
            raise ValueError("requested model source does not match execution destination")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ServedIdentityV1(StrictModel):
    """Exact served identity, or an explicit statement that it was unavailable."""

    contract_version: Literal[SERVED_IDENTITY_V1] = SERVED_IDENTITY_V1
    state: ServedIdentityState
    served_source: ModelSource | None = None
    served_model_id: str | None = None
    served_revision: str | None = None
    served_execution_mode: ModelExecutionMode | None = None
    fallback_used: bool | None = None
    fallback_reason_code: str | None = None
    unavailable_reason_code: str | None = None
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    @field_validator("served_model_id", "served_revision")
    @classmethod
    def optional_versions(cls, value: str | None) -> str | None:
        return None if value is None else _safe_version(value)

    _fallback_reason = field_validator("fallback_reason_code")(_optional_code)
    _unavailable_reason = field_validator("unavailable_reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_identity(self) -> ServedIdentityV1:
        exact_values = (
            self.served_source,
            self.served_model_id,
            self.served_revision,
            self.served_execution_mode,
            self.fallback_used,
        )
        if self.state is ServedIdentityState.OBSERVED:
            if any(value is None for value in exact_values):
                raise ValueError("observed served identity requires every exact field")
            if self.unavailable_reason_code is not None:
                raise ValueError("observed identity cannot claim unavailability")
            if self.fallback_used != (self.fallback_reason_code is not None):
                raise ValueError("fallback use requires exactly one safe reason code")
        elif (
            any(value is not None for value in exact_values)
            or self.fallback_reason_code is not None
            or self.unavailable_reason_code is None
        ):
            raise ValueError("unavailable served identity requires only a safe reason")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TokenUsageProvenanceV1(StrictModel):
    contract_version: Literal[TOKEN_USAGE_PROVENANCE_V1] = TOKEN_USAGE_PROVENANCE_V1
    state: MeasurementState
    collector_version: str
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None
    reason_code: str | None = None
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _version = field_validator("collector_version")(_safe_version)
    _reason = field_validator("reason_code")(_optional_code)

    @field_validator(
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
        mode="before",
    )
    @classmethod
    def bounded_counts(cls, value: Any) -> Any:
        if value is None:
            return None
        return _bounded_nonnegative_int(
            value, upper=MAX_TOKEN_COUNT, field_name="token count"
        )

    @model_validator(mode="after")
    def validate_usage(self) -> TokenUsageProvenanceV1:
        values = (
            self.input_tokens,
            self.cached_input_tokens,
            self.output_tokens,
            self.reasoning_output_tokens,
            self.total_tokens,
        )
        if self.state is MeasurementState.OBSERVED:
            if (
                self.input_tokens is None
                or self.output_tokens is None
                or self.total_tokens is None
                or self.reason_code is not None
            ):
                raise ValueError(
                    "observed billed usage requires input, output, and total counters"
                )
            if self.cached_input_tokens is not None and (
                self.cached_input_tokens > self.input_tokens
            ):
                raise ValueError("cached input tokens cannot exceed input tokens")
            if self.reasoning_output_tokens is not None and (
                self.reasoning_output_tokens > self.output_tokens
            ):
                raise ValueError("reasoning output tokens are a subset of output tokens")
            if self.total_tokens != self.input_tokens + self.output_tokens:
                raise ValueError("total billed tokens must equal input plus output tokens")
        elif any(value is not None for value in values) or self.reason_code is None:
            raise ValueError("unavailable usage requires only a safe reason")
        return self


class ResourceUsageProvenanceV1(StrictModel):
    contract_version: Literal[RESOURCE_USAGE_PROVENANCE_V1] = (
        RESOURCE_USAGE_PROVENANCE_V1
    )
    state: MeasurementState
    collector_version: str
    peak_ram_bytes: int | None = None
    peak_vram_bytes: int | None = None
    energy_millijoules: float | None = Field(default=None, allow_inf_nan=False)
    reason_code: str | None = None
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _version = field_validator("collector_version")(_safe_version)
    _reason = field_validator("reason_code")(_optional_code)

    @field_validator("peak_ram_bytes", "peak_vram_bytes", mode="before")
    @classmethod
    def bounded_bytes(cls, value: Any) -> Any:
        if value is None:
            return None
        return _bounded_nonnegative_int(
            value, upper=MAX_BYTE_COUNT, field_name="resource bytes"
        )

    @field_validator("energy_millijoules", mode="before")
    @classmethod
    def finite_energy(cls, value: Any) -> Any:
        if value is None:
            return None
        return _finite_nonnegative(value, field_name="energy")

    @model_validator(mode="after")
    def validate_resources(self) -> ResourceUsageProvenanceV1:
        values = (self.peak_ram_bytes, self.peak_vram_bytes, self.energy_millijoules)
        if self.state is MeasurementState.OBSERVED:
            if all(value is None for value in values) or self.reason_code is not None:
                raise ValueError("observed resources require measurements and no reason")
        elif any(value is not None for value in values) or self.reason_code is None:
            raise ValueError("unavailable resources require only a safe reason")
        return self


class CostProvenanceV1(StrictModel):
    contract_version: Literal[COST_PROVENANCE_V1] = COST_PROVENANCE_V1
    state: MeasurementState
    collector_version: str
    amount_microusd: int | None = None
    reason_code: str | None = None
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _version = field_validator("collector_version")(_safe_version)
    _reason = field_validator("reason_code")(_optional_code)

    @field_validator("amount_microusd", mode="before")
    @classmethod
    def bounded_cost(cls, value: Any) -> Any:
        if value is None:
            return None
        return _bounded_nonnegative_int(
            value, upper=MAX_COST_MICROUSD, field_name="API cost"
        )

    @model_validator(mode="after")
    def validate_cost(self) -> CostProvenanceV1:
        if self.state is MeasurementState.OBSERVED:
            if self.amount_microusd is None or self.reason_code is not None:
                raise ValueError("observed cost requires an amount and no reason")
        elif self.amount_microusd is not None or self.reason_code is None:
            raise ValueError("unavailable cost requires only a safe reason")
        return self


class QueueProvenanceV1(StrictModel):
    contract_version: Literal[QUEUE_PROVENANCE_V1] = QUEUE_PROVENANCE_V1
    queue_key: str
    queue_version: str
    worker_id: str
    enqueued_at: datetime
    dequeued_at: datetime
    wait_ms: int
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _key = field_validator("queue_key")(_safe_code)
    _version = field_validator("queue_version")(_safe_version)
    _worker = field_validator("worker_id")(_digest)
    _times = field_validator("enqueued_at", "dequeued_at")(_utc)

    @field_validator("wait_ms", mode="before")
    @classmethod
    def bounded_wait(cls, value: Any) -> int:
        return _bounded_nonnegative_int(
            value, upper=MAX_DURATION_MS, field_name="queue wait"
        )

    @model_validator(mode="after")
    def validate_queue(self) -> QueueProvenanceV1:
        if self.dequeued_at < self.enqueued_at:
            raise ValueError("queue timestamps must be chronological")
        expected = round((self.dequeued_at - self.enqueued_at).total_seconds() * 1000)
        if self.wait_ms != expected:
            raise ValueError("queue wait must match its timestamp interval")
        return self


class AttemptTerminalOutcomeV1(StrictModel):
    """One terminal attempt state with explicit unavailable measurements."""

    contract_version: Literal[ATTEMPT_TERMINAL_OUTCOME_V1] = (
        ATTEMPT_TERMINAL_OUTCOME_V1
    )
    outcome_id: str
    campaign_id: str
    attempt_id: str
    execution_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    state: AttemptTerminalState
    served_identity: ServedIdentityV1
    structured_output_fingerprint: str | None = None
    reason_code: str | None = None
    usage: TokenUsageProvenanceV1
    resources: ResourceUsageProvenanceV1
    cost: CostProvenanceV1
    queue: QueueProvenanceV1
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "outcome_id",
        "campaign_id",
        "attempt_id",
        "execution_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_digest)
    _reason = field_validator("reason_code")(_optional_code)
    _times = field_validator("started_at", "finished_at")(_utc)

    @field_validator("structured_output_fingerprint")
    @classmethod
    def optional_output_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("latency_ms", mode="before")
    @classmethod
    def bounded_latency(cls, value: Any) -> int:
        return _bounded_nonnegative_int(
            value, upper=MAX_DURATION_MS, field_name="attempt latency"
        )

    @model_validator(mode="after")
    def validate_outcome(self) -> AttemptTerminalOutcomeV1:
        if self.finished_at < self.started_at:
            raise ValueError("attempt timestamps must be chronological")
        expected = round((self.finished_at - self.started_at).total_seconds() * 1000)
        if self.latency_ms != expected:
            raise ValueError("attempt latency must match its timestamp interval")
        if self.queue.dequeued_at > self.started_at:
            raise ValueError("attempt cannot start before leaving the queue")
        if self.state is AttemptTerminalState.SUCCESS:
            if (
                self.served_identity.state is not ServedIdentityState.OBSERVED
                or self.structured_output_fingerprint is None
                or self.reason_code is not None
            ):
                raise ValueError(
                    "successful attempts require observed served identity and only an "
                    "output fingerprint"
                )
        elif self.structured_output_fingerprint is not None or self.reason_code is None:
            raise ValueError("non-success attempts require only a safe reason code")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ExpectedAttemptV2(StrictModel):
    contract_version: Literal[EXPECTED_ATTEMPT_V2] = EXPECTED_ATTEMPT_V2
    attempt_id: str
    execution_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    constellation_stage_fingerprint: str
    stage_configuration_sha256: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "attempt_id",
        "execution_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "constellation_stage_fingerprint",
        "stage_configuration_sha256",
    )(_digest)

    @model_validator(mode="after")
    def validate_expected(self) -> ExpectedAttemptV2:
        if self.stage_kind not in MODEL_STAGE_KINDS:
            raise ValueError("expected attempts are limited to model stages")
        return self


class ExpectedAttemptManifestV2(StrictModel):
    """Canonical execution set; its digest cannot be supplied by a caller."""

    contract_version: Literal[EXPECTED_ATTEMPT_MANIFEST_V2] = (
        EXPECTED_ATTEMPT_MANIFEST_V2
    )
    manifest_id: str
    campaign_id: str
    attempts: tuple[ExpectedAttemptV2, ...] = Field(
        min_length=1, max_length=MAX_ATTEMPTS
    )
    frozen_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("manifest_id", "campaign_id")(_digest)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_manifest(self) -> ExpectedAttemptManifestV2:
        keys = tuple(
            (item.case_id, item.stage_ordinal, item.execution_id, item.attempt_id)
            for item in self.attempts
        )
        if keys != tuple(sorted(keys)) or len(
            {item.attempt_id for item in self.attempts}
        ) != len(self.attempts):
            raise ValueError("expected attempts must be unique and canonically ordered")
        if len({item.plan_fingerprint for item in self.attempts}) != 1:
            raise ValueError("one expected-attempt manifest must bind one plan")
        return self

    @classmethod
    def from_launches(
        cls,
        *,
        manifest_id: str,
        campaign_id: str,
        launches: tuple[AttemptLaunchReceiptV1, ...],
        frozen_at: datetime,
    ) -> ExpectedAttemptManifestV2:
        attempts = tuple(
            sorted(
                (
                    ExpectedAttemptV2(
                        attempt_id=item.attempt_id,
                        execution_id=item.execution_id,
                        case_id=item.case_id,
                        plan_fingerprint=item.plan_fingerprint,
                        metric_question_fingerprint=item.metric_question_fingerprint,
                        evidence_packet_fingerprint=item.evidence_packet_fingerprint,
                        constellation_stage_fingerprint=(
                            item.constellation_stage_fingerprint
                        ),
                        stage_configuration_sha256=item.stage_configuration_sha256,
                        stage_ordinal=item.stage_ordinal,
                        stage_kind=item.stage_kind,
                    )
                    for item in launches
                ),
                key=lambda item: (
                    item.case_id,
                    item.stage_ordinal,
                    item.execution_id,
                    item.attempt_id,
                ),
            )
        )
        return cls(
            manifest_id=manifest_id,
            campaign_id=campaign_id,
            attempts=attempts,
            frozen_at=frozen_at,
        )

    @property
    def execution_set_fingerprint(self) -> str:
        return _canonical_payload_digest(
            [item.model_dump(mode="json") for item in self.attempts]
        )

    @property
    def plan_fingerprint(self) -> str:
        return self.attempts[0].plan_fingerprint

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class HoldoutAccessEventV1(StrictModel):
    contract_version: Literal[HOLDOUT_ACCESS_EVENT_V1] = HOLDOUT_ACCESS_EVENT_V1
    event_id: str
    campaign_id: str
    case_id: str
    actor_id: str
    actor_kind: HoldoutActorKind
    access_kind: HoldoutAccessKind
    occurred_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("event_id", "campaign_id", "case_id", "actor_id")(
        _digest
    )
    _occurred = field_validator("occurred_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class HoldoutAccessGapV1(StrictModel):
    contract_version: Literal[HOLDOUT_ACCESS_GAP_V1] = HOLDOUT_ACCESS_GAP_V1
    gap_id: str
    campaign_id: str
    reason_code: str
    started_at: datetime
    ended_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("gap_id", "campaign_id")(_digest)
    _reason = field_validator("reason_code")(_safe_code)
    _times = field_validator("started_at", "ended_at")(_utc)

    @model_validator(mode="after")
    def validate_gap(self) -> HoldoutAccessGapV1:
        if self.ended_at <= self.started_at:
            raise ValueError("access-audit gaps require a positive interval")
        return self


class HoldoutAccessManifestV1(StrictModel):
    contract_version: Literal[HOLDOUT_ACCESS_MANIFEST_V1] = (
        HOLDOUT_ACCESS_MANIFEST_V1
    )
    manifest_id: str
    campaign_id: str
    auditor_version: str
    coverage_started_at: datetime
    coverage_ended_at: datetime
    events: tuple[HoldoutAccessEventV1, ...] = Field(
        min_length=1, max_length=MAX_CASE_EVIDENCE
    )
    gaps: tuple[HoldoutAccessGapV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    frozen_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("manifest_id", "campaign_id")(_digest)
    _version = field_validator("auditor_version")(_safe_version)
    _times = field_validator(
        "coverage_started_at", "coverage_ended_at", "frozen_at"
    )(_utc)

    @model_validator(mode="after")
    def validate_manifest(self) -> HoldoutAccessManifestV1:
        if self.coverage_ended_at < self.coverage_started_at:
            raise ValueError("access coverage window must be chronological")
        if self.frozen_at < self.coverage_ended_at:
            raise ValueError("access manifest cannot freeze before coverage ends")
        event_keys = tuple((item.occurred_at, item.event_id) for item in self.events)
        if event_keys != tuple(sorted(event_keys)) or len(
            {item.event_id for item in self.events}
        ) != len(self.events):
            raise ValueError("access events must be unique and chronological")
        gap_keys = tuple((item.started_at, item.ended_at, item.gap_id) for item in self.gaps)
        if gap_keys != tuple(sorted(gap_keys)) or len(
            {item.gap_id for item in self.gaps}
        ) != len(self.gaps):
            raise ValueError("access gaps must be unique and chronological")
        if any(
            current.started_at < previous.ended_at
            for previous, current in zip(self.gaps, self.gaps[1:], strict=False)
        ):
            raise ValueError("access-audit gaps cannot overlap")
        for item in (*self.events, *self.gaps):
            if item.campaign_id != self.campaign_id:
                raise ValueError("access evidence must bind the manifest campaign")
        if any(
            not self.coverage_started_at <= item.occurred_at <= self.coverage_ended_at
            for item in self.events
        ) or any(
            item.started_at < self.coverage_started_at
            or item.ended_at > self.coverage_ended_at
            for item in self.gaps
        ):
            raise ValueError("access evidence must lie inside the coverage window")
        return self

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def event_set_fingerprint(self) -> str:
        return _canonical_payload_digest(
            [item.model_dump(mode="json") for item in self.events]
        )

    @property
    def gap_set_fingerprint(self) -> str:
        return _canonical_payload_digest(
            [item.model_dump(mode="json") for item in self.gaps]
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class HoldoutAccessAuditV1(StrictModel):
    contract_version: Literal[HOLDOUT_ACCESS_AUDIT_V1] = HOLDOUT_ACCESS_AUDIT_V1
    audit_id: str
    campaign_id: str
    manifest: HoldoutAccessManifestV1
    holdout_case_ids: tuple[str, ...]
    holdout_unsealed_at: datetime
    completed_at: datetime
    persistence_state: Literal["untrusted_until_sealed"] = "untrusted_until_sealed"
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("audit_id", "campaign_id")(_digest)
    _case_ids = field_validator("holdout_case_ids")(_canonical_digests)
    _times = field_validator("holdout_unsealed_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def validate_audit(self) -> HoldoutAccessAuditV1:
        if self.manifest.campaign_id != self.campaign_id:
            raise ValueError("holdout manifest must bind the audited campaign")
        if self.holdout_unsealed_at < self.manifest.coverage_started_at:
            raise ValueError("holdout unseal cannot predate audit coverage")
        if self.holdout_unsealed_at > self.manifest.coverage_ended_at:
            raise ValueError("holdout unseal must lie inside audit coverage")
        if self.completed_at < self.manifest.frozen_at:
            raise ValueError("holdout audit cannot complete before manifest freeze")
        holdout_cases = set(self.holdout_case_ids)
        if any(item.case_id not in holdout_cases for item in self.manifest.events):
            raise ValueError("holdout access event refers to a non-holdout case")
        return self

    @property
    def prohibited_pre_unseal_count(self) -> int:
        return sum(
            1
            for item in self.manifest.events
            if item.occurred_at < self.holdout_unsealed_at
            and item.access_kind in PROHIBITED_PRE_UNSEAL_ACCESS_KINDS
        )

    @property
    def unauthorized_access_count(self) -> int:
        return sum(
            1
            for item in self.manifest.events
            if (item.actor_kind, item.access_kind)
            not in AUTHORIZED_HOLDOUT_ACCESS_PAIRS
        )

    @property
    def passed(self) -> bool:
        return (
            self.manifest.gap_count == 0
            and self.prohibited_pre_unseal_count == 0
            and self.unauthorized_access_count == 0
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class PrivacyFindingV1(StrictModel):
    contract_version: Literal[PRIVACY_FINDING_V1] = PRIVACY_FINDING_V1
    finding_id: str
    campaign_id: str
    artifact_fingerprint: str
    detector_key: str
    detector_version: str
    category: PrivacyFindingCategory
    occurrence_count: int = Field(ge=1, le=1_000_000)
    detected_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "finding_id", "campaign_id", "artifact_fingerprint"
    )(_digest)
    _key = field_validator("detector_key")(_safe_code)
    _version = field_validator("detector_version")(_safe_version)
    _detected = field_validator("detected_at")(_utc)

    @field_validator("occurrence_count", mode="before")
    @classmethod
    def bounded_occurrences(cls, value: Any) -> int:
        return _bounded_nonnegative_int(
            value, upper=1_000_000, field_name="occurrence count"
        )

    @model_validator(mode="after")
    def positive_occurrences(self) -> PrivacyFindingV1:
        if self.occurrence_count == 0:
            raise ValueError("privacy findings require at least one occurrence")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class PrivacyScanManifestV1(StrictModel):
    contract_version: Literal[PRIVACY_SCAN_MANIFEST_V1] = PRIVACY_SCAN_MANIFEST_V1
    manifest_id: str
    campaign_id: str
    expected_artifact_fingerprints: tuple[str, ...]
    scanned_artifact_fingerprints: tuple[str, ...]
    findings: tuple[PrivacyFindingV1, ...] = Field(
        default=(), max_length=MAX_FINDINGS
    )
    frozen_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("manifest_id", "campaign_id")(_digest)
    _expected = field_validator("expected_artifact_fingerprints")(_canonical_digests)
    _scanned = field_validator("scanned_artifact_fingerprints")(_canonical_digests)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_manifest(self) -> PrivacyScanManifestV1:
        if not set(self.scanned_artifact_fingerprints).issubset(
            self.expected_artifact_fingerprints
        ):
            raise ValueError("scanned artifacts must belong to the expected set")
        keys = tuple(
            (item.artifact_fingerprint, item.category.value, item.finding_id)
            for item in self.findings
        )
        if keys != tuple(sorted(keys)) or len(
            {item.finding_id for item in self.findings}
        ) != len(self.findings):
            raise ValueError("privacy findings must be unique and canonically ordered")
        if any(
            item.campaign_id != self.campaign_id
            or item.artifact_fingerprint not in self.scanned_artifact_fingerprints
            or item.detected_at > self.frozen_at
            for item in self.findings
        ):
            raise ValueError("privacy findings must bind a scanned campaign artifact")
        return self

    @property
    def unscanned_artifact_count(self) -> int:
        return len(
            set(self.expected_artifact_fingerprints)
            - set(self.scanned_artifact_fingerprints)
        )

    @property
    def finding_count(self) -> int:
        return sum(item.occurrence_count for item in self.findings)

    @property
    def category_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (category.value, sum(
                item.occurrence_count for item in self.findings if item.category is category
            ))
            for category in PrivacyFindingCategory
            if any(item.category is category for item in self.findings)
        )

    @property
    def finding_set_fingerprint(self) -> str:
        return _canonical_payload_digest(
            [item.model_dump(mode="json") for item in self.findings]
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class PrivacyScanReceiptV1(StrictModel):
    contract_version: Literal[PRIVACY_SCAN_RECEIPT_V1] = PRIVACY_SCAN_RECEIPT_V1
    scan_id: str
    campaign_id: str
    scanner_version: str
    manifest: PrivacyScanManifestV1
    started_at: datetime
    completed_at: datetime
    persistence_state: Literal["untrusted_until_sealed"] = "untrusted_until_sealed"
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("scan_id", "campaign_id")(_digest)
    _version = field_validator("scanner_version")(_safe_version)
    _times = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def validate_scan(self) -> PrivacyScanReceiptV1:
        if self.manifest.campaign_id != self.campaign_id:
            raise ValueError("privacy manifest must bind the scanned campaign")
        if self.completed_at < self.started_at or self.completed_at < self.manifest.frozen_at:
            raise ValueError("privacy scan timestamps must be chronological")
        return self

    @property
    def finding_count(self) -> int:
        return self.manifest.finding_count

    @property
    def category_counts(self) -> tuple[tuple[str, int], ...]:
        return self.manifest.category_counts

    @property
    def passed(self) -> bool:
        return (
            self.manifest.unscanned_artifact_count == 0
            and self.manifest.finding_count == 0
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class _ProjectionValue(StrictModel):
    """Internal value shape shared by immutable content-free projections."""

    value_kind: MetricValueKind
    state: CalibrationValueState
    numeric_value: float | None = Field(default=None, allow_inf_nan=False)
    label_code: str | None = None
    confidence: float | None = Field(default=None, allow_inf_nan=False)
    reason_code: str | None = None

    _label = field_validator("label_code")(_optional_code)
    _reason = field_validator("reason_code")(_optional_code)

    @field_validator("numeric_value", mode="before")
    @classmethod
    def finite_numeric(cls, value: Any) -> Any:
        if value is None:
            return None
        return _finite_bounded(value, field_name="numeric value")

    @field_validator("confidence", mode="before")
    @classmethod
    def bounded_confidence(cls, value: Any) -> Any:
        if value is None:
            return None
        return _probability(value)


class StructuredEstimateReceiptV1(_ProjectionValue):
    """Runner-emitted structured value sealed later by persistence.

    Candidate selections and stability trials carry only a reference to this
    receipt. They cannot restate or alter its label, numeric value, or
    confidence. The receipt remains explicitly untrusted until the repository
    seals its exact successful-outcome lineage.
    """

    contract_version: Literal[STRUCTURED_ESTIMATE_RECEIPT_V1] = (
        STRUCTURED_ESTIMATE_RECEIPT_V1
    )
    receipt_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    attempt_id: str
    outcome_id: str
    outcome_fingerprint: str
    structured_output_fingerprint: str
    recorded_at: datetime
    persistence_state: Literal["untrusted_until_sealed"] = "untrusted_until_sealed"
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "receipt_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "attempt_id",
        "outcome_id",
        "outcome_fingerprint",
        "structured_output_fingerprint",
    )(_digest)
    _recorded = field_validator("recorded_at")(_utc)

    @model_validator(mode="after")
    def validate_estimate(self) -> StructuredEstimateReceiptV1:
        _validate_label_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            confidence=self.confidence,
            reason_code=self.reason_code,
            confidence_required=self.state is CalibrationValueState.KNOWN,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AuthoritativeCandidateProjectionV2(StrictModel):
    contract_version: Literal[AUTHORITATIVE_CANDIDATE_PROJECTION_V2] = (
        AUTHORITATIVE_CANDIDATE_PROJECTION_V2
    )
    projection_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    attempt_id: str
    outcome_id: str
    outcome_fingerprint: str
    estimate_receipt_id: str
    estimate_receipt_fingerprint: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind
    selected_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "projection_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "attempt_id",
        "outcome_id",
        "outcome_fingerprint",
        "estimate_receipt_id",
        "estimate_receipt_fingerprint",
    )(_digest)
    _selected = field_validator("selected_at")(_utc)

    @model_validator(mode="after")
    def validate_projection(self) -> AuthoritativeCandidateProjectionV2:
        if self.stage_kind not in {
            EstimatorStageKind.SPECIALIST,
            EstimatorStageKind.SECOND_OPINION,
        }:
            raise ValueError("candidate projection must select a specialist stage")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AuthoritativeDeterministicBaselineProjectionV1(_ProjectionValue):
    contract_version: Literal[AUTHORITATIVE_DETERMINISTIC_BASELINE_PROJECTION_V1] = (
        AUTHORITATIVE_DETERMINISTIC_BASELINE_PROJECTION_V1
    )
    projection_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    baseline_id: str
    baseline_version: str
    baseline_configuration_sha256: str
    final_estimate_fingerprint: str
    evaluated_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "projection_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "baseline_configuration_sha256",
        "final_estimate_fingerprint",
    )(_digest)
    _versions = field_validator("baseline_id", "baseline_version")(_safe_version)
    _evaluated = field_validator("evaluated_at")(_utc)

    @model_validator(mode="after")
    def validate_projection(self) -> AuthoritativeDeterministicBaselineProjectionV1:
        _validate_label_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            confidence=self.confidence,
            reason_code=self.reason_code,
            confidence_required=False,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ObjectiveTruthProjectionV1(_ProjectionValue):
    contract_version: Literal[OBJECTIVE_TRUTH_PROJECTION_V1] = (
        OBJECTIVE_TRUTH_PROJECTION_V1
    )
    projection_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    truth_kind: ObjectiveTruthKind
    objective_evidence_fingerprint: str
    verification_adapter_version: str
    observed_at: datetime
    persistence_state: Literal["untrusted_until_sealed"] = "untrusted_until_sealed"
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "projection_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "objective_evidence_fingerprint",
    )(_digest)
    _version = field_validator("verification_adapter_version")(_safe_version)
    _observed = field_validator("observed_at")(_utc)

    @model_validator(mode="after")
    def validate_projection(self) -> ObjectiveTruthProjectionV1:
        _validate_label_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            confidence=self.confidence,
            reason_code=self.reason_code,
            confidence_required=False,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class BlindHumanJudgmentInputV1(_ProjectionValue):
    contract_version: Literal[BLIND_HUMAN_JUDGMENT_INPUT_V1] = (
        BLIND_HUMAN_JUDGMENT_INPUT_V1
    )
    judgment_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    participant_id: str
    participant_kind: HumanParticipantKind
    annotation_protocol_version: str
    created_at: datetime
    blinded_to_candidate: Literal[True] = True
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "judgment_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "participant_id",
    )(_digest)
    _version = field_validator("annotation_protocol_version")(_safe_version)
    _created = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def validate_judgment(self) -> BlindHumanJudgmentInputV1:
        if self.participant_kind is HumanParticipantKind.ADJUDICATOR:
            raise ValueError("blind input judgments must come from annotators")
        _validate_label_shape(
            state=self.state,
            value_kind=self.value_kind,
            numeric_value=self.numeric_value,
            label_code=self.label_code,
            confidence=self.confidence,
            reason_code=self.reason_code,
            confidence_required=False,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class BlindHumanAdjudicationInputV1(_ProjectionValue):
    contract_version: Literal[BLIND_HUMAN_ADJUDICATION_INPUT_V1] = (
        BLIND_HUMAN_ADJUDICATION_INPUT_V1
    )
    adjudication_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    adjudicator_id: str
    adjudicator_kind: HumanParticipantKind
    resolution: BlindAdjudicationResolution
    judgment_ids: tuple[str, ...] = Field(min_length=2, max_length=32)
    annotation_protocol_version: str
    completed_at: datetime
    blinded_to_candidate: Literal[True] = True
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "adjudication_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "adjudicator_id",
    )(_digest)
    _judgment_ids = field_validator("judgment_ids")(_canonical_digests)
    _version = field_validator("annotation_protocol_version")(_safe_version)
    _completed = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def validate_adjudication(self) -> BlindHumanAdjudicationInputV1:
        if self.adjudicator_kind is not HumanParticipantKind.ADJUDICATOR:
            raise ValueError("adjudication requires an explicit adjudicator kind")
        if self.resolution is BlindAdjudicationResolution.RESOLVED:
            _validate_label_shape(
                state=self.state,
                value_kind=self.value_kind,
                numeric_value=self.numeric_value,
                label_code=self.label_code,
                confidence=self.confidence,
                reason_code=self.reason_code,
                confidence_required=False,
            )
            if self.state is not CalibrationValueState.KNOWN:
                raise ValueError("resolved adjudication requires a known final value")
        elif (
            self.state is not CalibrationValueState.UNKNOWN
            or any(value is not None for value in (self.numeric_value, self.label_code, self.confidence))
            or self.reason_code is None
        ):
            raise ValueError("unresolved adjudication requires only an unknown reason")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class StabilityTrialReceiptV1(StrictModel):
    contract_version: Literal[STABILITY_TRIAL_RECEIPT_V1] = (
        STABILITY_TRIAL_RECEIPT_V1
    )
    receipt_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    condition: StabilityCondition
    trial_ordinal: int = Field(ge=1, le=20)
    attempt_id: str
    outcome_id: str
    outcome_fingerprint: str
    estimate_receipt_id: str
    estimate_receipt_fingerprint: str
    recorded_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "receipt_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "attempt_id",
        "outcome_id",
        "outcome_fingerprint",
        "estimate_receipt_id",
        "estimate_receipt_fingerprint",
    )(_digest)
    _recorded = field_validator("recorded_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class StabilitySeriesManifestV1(StrictModel):
    contract_version: Literal[STABILITY_SERIES_MANIFEST_V1] = (
        STABILITY_SERIES_MANIFEST_V1
    )
    series_id: str
    campaign_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    condition: StabilityCondition
    trials: tuple[StabilityTrialReceiptV1, ...] = Field(min_length=2, max_length=20)
    frozen_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "series_id",
        "campaign_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_digest)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_series(self) -> StabilitySeriesManifestV1:
        if tuple(item.trial_ordinal for item in self.trials) != tuple(
            range(1, len(self.trials) + 1)
        ):
            raise ValueError("stability trials must be a contiguous ordered sequence")
        if len({item.attempt_id for item in self.trials}) != len(self.trials):
            raise ValueError("stability trials require distinct attempts")
        if any(
            item.campaign_id != self.campaign_id
            or item.case_id != self.case_id
            or item.plan_fingerprint != self.plan_fingerprint
            or item.metric_question_fingerprint != self.metric_question_fingerprint
            or item.evidence_packet_fingerprint != self.evidence_packet_fingerprint
            or item.condition is not self.condition
            or item.recorded_at > self.frozen_at
            for item in self.trials
        ):
            raise ValueError("stability trials must bind one frozen series")
        return self

    @property
    def trial_set_fingerprint(self) -> str:
        return _canonical_payload_digest(
            [item.model_dump(mode="json") for item in self.trials]
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CalibrationEvidenceSubmissionV1(StrictModel):
    """Dynamic campaign evidence only; this contract cannot activate a plan.

    ``campaign_holdout_case_ids`` is a persistence input, not a caller claim of
    integrity. The repository must reconstruct this model and exact-match that
    tuple to the sealed v16 calibration split before storing any evidence.
    """

    contract_version: Literal[CALIBRATION_EVIDENCE_SUBMISSION_V1] = (
        CALIBRATION_EVIDENCE_SUBMISSION_V1
    )
    submission_id: str
    campaign_id: str
    campaign_holdout_case_ids: tuple[str, ...]
    expected_attempt_manifest: ExpectedAttemptManifestV2
    attempt_launches: tuple[AttemptLaunchReceiptV1, ...] = Field(
        min_length=1, max_length=MAX_ATTEMPTS
    )
    attempt_outcomes: tuple[AttemptTerminalOutcomeV1, ...] = Field(
        min_length=1, max_length=MAX_ATTEMPTS
    )
    structured_estimate_receipts: tuple[StructuredEstimateReceiptV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    holdout_access_audit: HoldoutAccessAuditV1
    privacy_scan: PrivacyScanReceiptV1
    candidate_projections: tuple[AuthoritativeCandidateProjectionV2, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    deterministic_baseline_projections: tuple[
        AuthoritativeDeterministicBaselineProjectionV1, ...
    ] = Field(default=(), max_length=MAX_CASE_EVIDENCE)
    objective_truth_projections: tuple[ObjectiveTruthProjectionV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    blind_human_judgments: tuple[BlindHumanJudgmentInputV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    blind_human_adjudications: tuple[BlindHumanAdjudicationInputV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    stability_series: tuple[StabilitySeriesManifestV1, ...] = Field(
        default=(), max_length=MAX_CASE_EVIDENCE
    )
    submitted_at: datetime
    activation_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("submission_id", "campaign_id")(_digest)
    _holdout_ids = field_validator("campaign_holdout_case_ids")(_canonical_digests)
    _submitted = field_validator("submitted_at")(_utc)

    @model_validator(mode="after")
    def validate_submission(self) -> CalibrationEvidenceSubmissionV1:
        if self.expected_attempt_manifest.campaign_id != self.campaign_id:
            raise ValueError("expected attempts must bind the submission campaign")
        if (
            self.holdout_access_audit.campaign_id != self.campaign_id
            or self.privacy_scan.campaign_id != self.campaign_id
        ):
            raise ValueError("audits must bind the submission campaign")
        groups = (
            self.attempt_launches,
            self.attempt_outcomes,
            self.structured_estimate_receipts,
            self.candidate_projections,
            self.deterministic_baseline_projections,
            self.objective_truth_projections,
            self.blind_human_judgments,
            self.blind_human_adjudications,
            self.stability_series,
        )
        if any(
            getattr(item, "campaign_id") != self.campaign_id
            for group in groups
            for item in group
        ):
            raise ValueError("all dynamic evidence must bind the submission campaign")

        expected = {
            item.attempt_id: item for item in self.expected_attempt_manifest.attempts
        }
        launches = {item.attempt_id: item for item in self.attempt_launches}
        outcomes = {item.attempt_id: item for item in self.attempt_outcomes}
        if len(launches) != len(self.attempt_launches) or len(outcomes) != len(
            self.attempt_outcomes
        ):
            raise ValueError("attempt launch and outcome identifiers must be unique")
        if set(expected) != set(launches) or set(expected) != set(outcomes):
            raise ValueError("expected, launched, and terminal attempt sets must match")
        if tuple(item.attempt_id for item in self.attempt_launches) != tuple(
            sorted(launches)
        ) or tuple(item.attempt_id for item in self.attempt_outcomes) != tuple(
            sorted(outcomes)
        ):
            raise ValueError("launches and outcomes must be ordered by attempt_id")
        if any(
            self.expected_attempt_manifest.frozen_at > launch.launched_at
            or (
                expected[attempt_id].execution_id,
                expected[attempt_id].case_id,
                expected[attempt_id].plan_fingerprint,
                expected[attempt_id].metric_question_fingerprint,
                expected[attempt_id].evidence_packet_fingerprint,
                expected[attempt_id].constellation_stage_fingerprint,
                expected[attempt_id].stage_configuration_sha256,
                expected[attempt_id].stage_ordinal,
                expected[attempt_id].stage_kind,
            )
            != (
                launch.execution_id,
                launch.case_id,
                launch.plan_fingerprint,
                launch.metric_question_fingerprint,
                launch.evidence_packet_fingerprint,
                launch.constellation_stage_fingerprint,
                launch.stage_configuration_sha256,
                launch.stage_ordinal,
                launch.stage_kind,
            )
            for attempt_id, launch in launches.items()
        ):
            raise ValueError("attempt launches do not match the frozen execution set")
        for attempt_id, outcome in outcomes.items():
            launch = launches[attempt_id]
            if (
                outcome.execution_id != launch.execution_id
                or outcome.case_id != launch.case_id
                or outcome.plan_fingerprint != launch.plan_fingerprint
                or outcome.metric_question_fingerprint
                != launch.metric_question_fingerprint
                or outcome.evidence_packet_fingerprint
                != launch.evidence_packet_fingerprint
                or outcome.started_at != launch.launched_at
                or outcome.finished_at < launch.launched_at
            ):
                raise ValueError("terminal outcome does not match its launch lineage")
            served = outcome.served_identity
            if served.state is ServedIdentityState.OBSERVED:
                observed_fallback = (
                    served.served_source is not launch.requested_source
                    or served.served_model_id != launch.requested_model_id
                    or served.served_revision != launch.requested_revision
                    or served.served_execution_mode
                    is not launch.requested_execution_mode
                )
                if served.fallback_used != observed_fallback:
                    raise ValueError("served fallback flag must match requested identity")

        case_ids = {item.case_id for item in expected.values()}
        if self.holdout_access_audit.holdout_case_ids != self.campaign_holdout_case_ids:
            raise ValueError("holdout audit must exactly cover campaign holdout cases")
        if not set(self.campaign_holdout_case_ids).issubset(case_ids):
            raise ValueError("campaign holdout cases must belong to the execution set")
        plan_fingerprint = self.expected_attempt_manifest.plan_fingerprint
        expected_lineages = {
            (
                item.case_id,
                item.plan_fingerprint,
                item.metric_question_fingerprint,
                item.evidence_packet_fingerprint,
            )
            for item in expected.values()
        }

        estimates = {
            item.receipt_id: item for item in self.structured_estimate_receipts
        }
        estimate_keys = tuple(
            (item.recorded_at, item.receipt_id)
            for item in self.structured_estimate_receipts
        )
        if len(estimates) != len(self.structured_estimate_receipts) or estimate_keys != tuple(
            sorted(estimate_keys)
        ):
            raise ValueError("structured estimate receipts must be unique and chronological")
        for item in self.structured_estimate_receipts:
            outcome = outcomes.get(item.attempt_id)
            if (
                outcome is None
                or outcome.state is not AttemptTerminalState.SUCCESS
                or item.outcome_id != outcome.outcome_id
                or item.outcome_fingerprint != outcome.fingerprint
                or item.structured_output_fingerprint
                != outcome.structured_output_fingerprint
                or item.case_id != outcome.case_id
                or item.plan_fingerprint != outcome.plan_fingerprint
                or item.metric_question_fingerprint
                != outcome.metric_question_fingerprint
                or item.evidence_packet_fingerprint
                != outcome.evidence_packet_fingerprint
                or item.recorded_at < outcome.finished_at
            ):
                raise ValueError(
                    "structured estimate receipt must bind a successful immutable outcome"
                )

        projection_groups = (
            self.candidate_projections,
            self.deterministic_baseline_projections,
            self.objective_truth_projections,
        )
        if any(
            (
                item.case_id,
                item.plan_fingerprint,
                item.metric_question_fingerprint,
                item.evidence_packet_fingerprint,
            )
            not in expected_lineages
            for group in projection_groups
            for item in group
        ):
            raise ValueError("projection does not match an exact expected lineage")

        candidate_keys = tuple(
            (item.case_id, item.metric_question_fingerprint)
            for item in self.candidate_projections
        )
        if candidate_keys != tuple(sorted(candidate_keys)) or len(candidate_keys) != len(
            set(candidate_keys)
        ):
            raise ValueError("candidate projections must be unique and sorted")
        for item in self.candidate_projections:
            launch = launches.get(item.attempt_id)
            outcome = outcomes.get(item.attempt_id)
            estimate = estimates.get(item.estimate_receipt_id)
            if (
                launch is None
                or outcome is None
                or estimate is None
                or item.outcome_id != outcome.outcome_id
                or item.outcome_fingerprint != outcome.fingerprint
                or item.estimate_receipt_fingerprint != estimate.fingerprint
                or estimate.attempt_id != item.attempt_id
                or estimate.outcome_id != item.outcome_id
                or item.case_id != launch.case_id
                or item.plan_fingerprint != launch.plan_fingerprint
                or item.metric_question_fingerprint
                != launch.metric_question_fingerprint
                or item.evidence_packet_fingerprint
                != launch.evidence_packet_fingerprint
                or item.stage_ordinal != launch.stage_ordinal
                or item.stage_kind is not launch.stage_kind
                or item.selected_at < outcome.finished_at
                or item.selected_at < estimate.recorded_at
            ):
                raise ValueError("candidate projection must bind its authoritative outcome")

        for items, name in (
            (self.deterministic_baseline_projections, "baseline"),
            (self.objective_truth_projections, "objective truth"),
        ):
            keys = tuple((item.case_id, item.metric_question_fingerprint) for item in items)
            if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
                raise ValueError(f"{name} projections must be unique and sorted")

        judgments = {item.judgment_id: item for item in self.blind_human_judgments}
        judgment_keys = tuple(
            (item.created_at, item.judgment_id)
            for item in self.blind_human_judgments
        )
        if len(judgments) != len(self.blind_human_judgments) or judgment_keys != tuple(
            sorted(judgment_keys)
        ):
            raise ValueError("blind human judgments must be unique and chronological")
        if any(
            (
                item.case_id,
                item.plan_fingerprint,
                item.metric_question_fingerprint,
                item.evidence_packet_fingerprint,
            )
            not in expected_lineages
            for item in judgments.values()
        ):
            raise ValueError("blind human judgment does not match an exact lineage")
        adjudication_keys = tuple(
            (item.case_id, item.metric_question_fingerprint)
            for item in self.blind_human_adjudications
        )
        if adjudication_keys != tuple(sorted(adjudication_keys)) or len(
            adjudication_keys
        ) != len(set(adjudication_keys)):
            raise ValueError("blind adjudications must be unique and sorted")
        for item in self.blind_human_adjudications:
            selected = [judgments.get(identifier) for identifier in item.judgment_ids]
            if any(judgment is None for judgment in selected):
                raise ValueError("blind adjudication references an absent judgment")
            bound = [judgment for judgment in selected if judgment is not None]
            if (
                item.case_id not in case_ids
                or (
                    item.case_id,
                    item.plan_fingerprint,
                    item.metric_question_fingerprint,
                    item.evidence_packet_fingerprint,
                )
                not in expected_lineages
                or any(
                    judgment.case_id != item.case_id
                    or judgment.plan_fingerprint != item.plan_fingerprint
                    or judgment.metric_question_fingerprint
                    != item.metric_question_fingerprint
                    or judgment.evidence_packet_fingerprint
                    != item.evidence_packet_fingerprint
                    or judgment.annotation_protocol_version
                    != item.annotation_protocol_version
                    or judgment.created_at > item.completed_at
                    for judgment in bound
                )
                or len({judgment.participant_id for judgment in bound}) < 2
                or item.adjudicator_id
                in {judgment.participant_id for judgment in bound}
                or (
                    item.resolution is BlindAdjudicationResolution.RESOLVED
                    and not any(
                        judgment.state is CalibrationValueState.KNOWN
                        and judgment.value_kind is item.value_kind
                        and judgment.numeric_value == item.numeric_value
                        and judgment.label_code == item.label_code
                        for judgment in bound
                    )
                )
            ):
                raise ValueError("blind adjudication does not match independent inputs")

        series_keys = tuple(
            (item.case_id, item.condition.value, item.series_id)
            for item in self.stability_series
        )
        if series_keys != tuple(sorted(series_keys)) or len(
            {item.series_id for item in self.stability_series}
        ) != len(self.stability_series):
            raise ValueError("stability series must be unique and sorted")
        for series in self.stability_series:
            if (
                series.case_id,
                series.plan_fingerprint,
                series.metric_question_fingerprint,
                series.evidence_packet_fingerprint,
            ) not in expected_lineages:
                raise ValueError("stability series does not match an exact lineage")
            for trial in series.trials:
                launch = launches.get(trial.attempt_id)
                outcome = outcomes.get(trial.attempt_id)
                estimate = estimates.get(trial.estimate_receipt_id)
                if (
                    launch is None
                    or outcome is None
                    or estimate is None
                    or launch.stage_kind
                    not in {
                        EstimatorStageKind.SPECIALIST,
                        EstimatorStageKind.SECOND_OPINION,
                    }
                    or trial.outcome_id != outcome.outcome_id
                    or trial.outcome_fingerprint != outcome.fingerprint
                    or trial.estimate_receipt_fingerprint != estimate.fingerprint
                    or estimate.attempt_id != trial.attempt_id
                    or estimate.outcome_id != trial.outcome_id
                    or trial.case_id != outcome.case_id
                    or trial.metric_question_fingerprint
                    != outcome.metric_question_fingerprint
                    or trial.evidence_packet_fingerprint
                    != outcome.evidence_packet_fingerprint
                    or trial.recorded_at < outcome.finished_at
                    or trial.recorded_at < estimate.recorded_at
                ):
                    raise ValueError("stability trial must bind an immutable outcome")

        required_scan_artifacts = {
            item.structured_output_fingerprint
            for item in self.attempt_outcomes
            if item.structured_output_fingerprint is not None
        } | {
            item.final_estimate_fingerprint
            for item in self.deterministic_baseline_projections
        } | {
            item.objective_evidence_fingerprint for item in self.objective_truth_projections
        }
        if not required_scan_artifacts.issubset(
            self.privacy_scan.manifest.expected_artifact_fingerprints
        ):
            raise ValueError("privacy scan omits a dynamic evidence artifact")

        latest_times = [
            *(item.finished_at for item in self.attempt_outcomes),
            *(item.recorded_at for item in self.structured_estimate_receipts),
            *(item.selected_at for item in self.candidate_projections),
            *(item.evaluated_at for item in self.deterministic_baseline_projections),
            *(item.observed_at for item in self.objective_truth_projections),
            *(item.created_at for item in self.blind_human_judgments),
            *(item.completed_at for item in self.blind_human_adjudications),
            *(item.frozen_at for item in self.stability_series),
        ]
        holdout_ids = set(self.campaign_holdout_case_ids)
        earliest_holdout_activity = [
            *(item.queue.enqueued_at for item in self.attempt_outcomes if item.case_id in holdout_ids),
            *(item.evaluated_at for item in self.deterministic_baseline_projections if item.case_id in holdout_ids),
            *(item.observed_at for item in self.objective_truth_projections if item.case_id in holdout_ids),
            *(item.created_at for item in self.blind_human_judgments if item.case_id in holdout_ids),
        ]
        if (
            earliest_holdout_activity
            and self.holdout_access_audit.manifest.coverage_started_at
            > min(earliest_holdout_activity)
        ):
            raise ValueError(
                "holdout access audit must begin before all holdout activity"
            )
        if latest_times and self.holdout_access_audit.manifest.coverage_ended_at < max(
            latest_times
        ):
            raise ValueError("holdout access audit must cover all dynamic evidence")

        unsealed_at = self.holdout_access_audit.holdout_unsealed_at
        if any(
            item.case_id in holdout_ids
            and (
                item.selected_at >= unsealed_at
                or estimates[item.estimate_receipt_id].recorded_at >= unsealed_at
            )
            for item in self.candidate_projections
        ):
            raise ValueError("holdout candidate outputs must freeze before unseal")
        if any(
            item.case_id in holdout_ids and item.evaluated_at >= unsealed_at
            for item in self.deterministic_baseline_projections
        ):
            raise ValueError("holdout baseline outputs must freeze before unseal")
        if any(
            item.case_id in holdout_ids
            and (
                item.frozen_at >= unsealed_at
                or any(trial.recorded_at >= unsealed_at for trial in item.trials)
            )
            for item in self.stability_series
        ):
            raise ValueError("holdout stability outputs must freeze before unseal")
        if latest_times and self.privacy_scan.completed_at < max(latest_times):
            raise ValueError("privacy scan cannot complete before dynamic evidence exists")
        if (
            self.submitted_at < self.privacy_scan.completed_at
            or self.submitted_at < self.holdout_access_audit.completed_at
        ):
            raise ValueError("submission cannot predate its audits")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


_ContractT = TypeVar("_ContractT", bound=StrictModel)


def _plain_validation_payload(value: object) -> object:
    """Recursively discard preconstructed model instances before validation.

    Pydantic may otherwise trust a nested ``model_copy`` instance embedded in
    an ordinary mapping and skip that nested model's validators.  Persistence
    boundaries use this conversion so every level is reconstructed from plain
    values.
    """

    if isinstance(value, StrictModel):
        return _plain_validation_payload(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {key: _plain_validation_payload(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_plain_validation_payload(item) for item in value)
    if isinstance(value, list):
        return [_plain_validation_payload(item) for item in value]
    return value


def revalidate_content_free_contract(
    contract_type: type[_ContractT], value: _ContractT | dict[str, object]
) -> _ContractT:
    """Reconstruct a frozen contract so ``model_copy`` cannot bypass validators."""

    payload = _plain_validation_payload(value)
    return contract_type.model_validate(payload)


def revalidate_calibration_evidence_submission_v1(
    value: CalibrationEvidenceSubmissionV1 | dict[str, object],
) -> CalibrationEvidenceSubmissionV1:
    return revalidate_content_free_contract(CalibrationEvidenceSubmissionV1, value)


# Explicit aliases make the persistence vocabulary unambiguous without
# introducing a second implementation or a caller-controlled compatibility path.
AttemptOutcomeReceiptV1 = AttemptTerminalOutcomeV1
AuthoritativeDeterministicProjectionV1 = (
    AuthoritativeDeterministicBaselineProjectionV1
)
