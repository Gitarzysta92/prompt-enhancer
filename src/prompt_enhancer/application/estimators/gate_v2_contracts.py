"""Content-free v2 contracts for a full estimator-constellation gate.

Version one represented an evaluated estimator with one model identity and
stability labels that were not linked to executions.  These additive contracts
close those identity gaps without changing or adapting the v1 records.  They
contain only safe codes, opaque SHA-256 identifiers, bounded counts, and UTC
timestamps.  No prompt, evidence body, model output, or reviewer prose belongs
in this module.
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

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .contracts import (
    MODEL_STAGE_KINDS,
    EstimatorPlan,
    EstimatorStage,
    EstimatorStageKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelSource,
)
from .gate_contracts import (
    ActivationGateCheck,
    ActivationOutcome,
    CalibrationCohort,
    CalibrationLanguage,
    CalibrationSplit,
    CalibrationTaskStratum,
    CaseOrigin,
    CaseRunState,
    EstimatorCase,
    EvidenceTier,
    GateCheckOutcome,
    GatePreregistration,
    HoldoutAccessAuditReceipt,
    PrivacyScanReceipt,
    LatencyClass,
    StabilityCondition,
)


CASE_ASSIGNMENT_V2 = "case-assignment-v2"
CASE_ASSIGNMENT_MANIFEST_V2 = "case-assignment-manifest-v2"
CONSTELLATION_STAGE_IDENTITY_V1 = "constellation-stage-identity-v1"
CONSTELLATION_IDENTITY_RECEIPT_V1 = "constellation-identity-receipt-v1"
ATTEMPT_IDENTITY_RECEIPT_V1 = "attempt-identity-receipt-v1"
ATTEMPT_OUTCOME_RECEIPT_V1 = "attempt-outcome-receipt-v1"
EXPECTED_ATTEMPT_MANIFEST_V1 = "expected-attempt-manifest-v1"
AUTHORITATIVE_CANDIDATE_PROJECTION_V1 = "authoritative-candidate-projection-v1"
EXECUTION_IDENTITY_AUDIT_V1 = "execution-identity-audit-v1"
STABILITY_TRIAL_V2 = "stability-trial-v2"
STABILITY_RECEIPT_V2 = "stability-receipt-v2"
BLIND_CALIBRATION_JUDGMENT_V1 = "blind-calibration-judgment-v1"
BLIND_CALIBRATION_ADJUDICATION_V1 = "blind-calibration-adjudication-v1"
GATE_EVIDENCE_V2 = "gate-evidence-v2"
GATE_PREREGISTRATION_V2 = "gate-preregistration-v2"
ACTIVATION_GATE_DECISION_V2 = "activation-gate-decision-v2"

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


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


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 pseudonym")
    return value


def _safe_version(value: str) -> str:
    """Accept safe identifiers, but never a filesystem path or URI."""

    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", value) is not None
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value) is not None
        or "\\" in value
        or "://" in value
        or ".." in value.split("/")
        or SAFE_VERSION_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("version identifiers cannot encode paths or URIs")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _optional_code(value: str | None) -> str | None:
    return None if value is None else _safe_code(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


class BlindCalibrationSource(StrEnum):
    REFERENCE_TRUTH = "reference_truth"
    HUMAN_BASELINE = "human_baseline"


class BlindCalibrationResolution(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class CaseAssignmentV2(StrictModel):
    """Static case identity frozen before any candidate attempt is observed."""

    contract_version: Literal[CASE_ASSIGNMENT_V2] = CASE_ASSIGNMENT_V2
    case_id: str
    project_id: str
    session_revision_id: str
    metric_key: str
    provider: Provider
    origin: CaseOrigin
    task_stratum: CalibrationTaskStratum
    language: CalibrationLanguage
    evidence_tier: EvidenceTier
    observed_at: datetime
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str

    _ids = field_validator(
        "case_id",
        "project_id",
        "session_revision_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_pseudonym)
    _metric = field_validator("metric_key")(_safe_code)
    _observed = field_validator("observed_at")(_utc)

    @classmethod
    def from_case(
        cls,
        case: EstimatorCase,
        *,
        plan_fingerprint: str,
        metric_question_fingerprint: str,
        evidence_packet_fingerprint: str,
    ) -> CaseAssignmentV2:
        return cls(
            case_id=case.case_id,
            project_id=case.project_id,
            session_revision_id=case.session_revision_id,
            metric_key=case.metric_key,
            provider=case.provider,
            origin=case.origin,
            task_stratum=case.task_stratum,
            language=case.language,
            evidence_tier=case.evidence_tier,
            observed_at=case.observed_at,
            plan_fingerprint=plan_fingerprint,
            metric_question_fingerprint=metric_question_fingerprint,
            evidence_packet_fingerprint=evidence_packet_fingerprint,
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CaseAssignmentManifestV2(StrictModel):
    contract_version: Literal[CASE_ASSIGNMENT_MANIFEST_V2] = (
        CASE_ASSIGNMENT_MANIFEST_V2
    )
    manifest_id: str
    plan_fingerprint: str
    frozen_at: datetime
    assignments: tuple[CaseAssignmentV2, ...]

    _ids = field_validator("manifest_id", "plan_fingerprint")(_pseudonym)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_manifest(self) -> CaseAssignmentManifestV2:
        if not self.assignments:
            raise ValueError("case assignment manifest requires assignments")
        ids = tuple(item.case_id for item in self.assignments)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("assignments must be unique and sorted by case_id")
        if any(item.plan_fingerprint != self.plan_fingerprint for item in self.assignments):
            raise ValueError("every assignment must bind the manifest plan")
        if any(item.observed_at > self.frozen_at for item in self.assignments):
            raise ValueError("assignment manifest may not predate an observation")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ConstellationStageIdentity(StrictModel):
    """Fingerprint projection of one complete model-bearing stored-plan stage."""

    contract_version: Literal[CONSTELLATION_STAGE_IDENTITY_V1] = (
        CONSTELLATION_STAGE_IDENTITY_V1
    )
    ordinal: int = Field(ge=1, le=7)
    kind: EstimatorStageKind
    source: ModelSource
    stage_fingerprint: str
    model_artifact_fingerprint: str
    stage_configuration_sha256: str
    component_version: str
    output_schema_version: str

    _digests = field_validator(
        "stage_fingerprint",
        "model_artifact_fingerprint",
        "stage_configuration_sha256",
    )(_pseudonym)
    _versions = field_validator("component_version", "output_schema_version")(
        _safe_version
    )

    @model_validator(mode="after")
    def validate_model_stage(self) -> ConstellationStageIdentity:
        if self.kind not in MODEL_STAGE_KINDS:
            raise ValueError("constellation identities are limited to model stages")
        return self

    @classmethod
    def from_stage(cls, stage: EstimatorStage) -> ConstellationStageIdentity:
        if stage.model_artifact is None:
            raise ValueError("a constellation stage requires a model artifact")
        return cls(
            ordinal=stage.ordinal,
            kind=stage.kind,
            source=stage.model_artifact.source,
            stage_fingerprint=_canonical_payload_digest(stage.model_dump(mode="json")),
            model_artifact_fingerprint=stage.model_artifact.canonical_fingerprint,
            stage_configuration_sha256=stage.configuration_sha256,
            component_version=stage.component_version,
            output_schema_version=stage.output_schema_version,
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ConstellationIdentityReceipt(StrictModel):
    contract_version: Literal[CONSTELLATION_IDENTITY_RECEIPT_V1] = (
        CONSTELLATION_IDENTITY_RECEIPT_V1
    )
    constellation_id: str
    plan_fingerprint: str
    stages: tuple[ConstellationStageIdentity, ...]
    frozen_at: datetime

    _ids = field_validator("constellation_id", "plan_fingerprint")(_pseudonym)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_stages(self) -> ConstellationIdentityReceipt:
        if not self.stages:
            raise ValueError("constellation requires every model stage")
        keys = tuple((item.ordinal, item.kind.value) for item in self.stages)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("constellation stages must be unique and ordinal-sorted")
        return self

    @classmethod
    def from_plan(
        cls,
        plan: EstimatorPlan,
        *,
        constellation_id: str,
        frozen_at: datetime,
    ) -> ConstellationIdentityReceipt:
        return cls(
            constellation_id=constellation_id,
            plan_fingerprint=plan.canonical_fingerprint,
            stages=tuple(
                ConstellationStageIdentity.from_stage(stage)
                for stage in plan.stages
                if stage.model_artifact is not None
            ),
            frozen_at=frozen_at,
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AttemptIdentityReceipt(StrictModel):
    """Exact requested/served identity for one candidate or stability attempt."""

    contract_version: Literal[ATTEMPT_IDENTITY_RECEIPT_V1] = (
        ATTEMPT_IDENTITY_RECEIPT_V1
    )
    attempt_id: str
    execution_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    constellation_stage_fingerprint: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind
    source: ModelSource
    model_artifact_fingerprint: str
    stage_configuration_sha256: str
    requested_model_id: str
    served_model_id: str
    requested_revision: str
    served_revision: str
    requested_execution_mode: ModelExecutionMode
    served_execution_mode: ModelExecutionMode
    fallback_used: bool
    fallback_reason_code: str | None = None
    attempted_at: datetime

    _ids = field_validator(
        "attempt_id",
        "execution_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "constellation_stage_fingerprint",
        "model_artifact_fingerprint",
        "stage_configuration_sha256",
    )(_pseudonym)
    _versions = field_validator(
        "requested_model_id",
        "served_model_id",
        "requested_revision",
        "served_revision",
    )(_safe_version)
    _reason = field_validator("fallback_reason_code")(_optional_code)
    _attempted = field_validator("attempted_at")(_utc)

    @model_validator(mode="after")
    def validate_exact_identity_shape(self) -> AttemptIdentityReceipt:
        if self.stage_kind not in MODEL_STAGE_KINDS:
            raise ValueError("attempt identity must name a model stage")
        fallback_observed = (
            self.requested_model_id != self.served_model_id
            or self.requested_revision != self.served_revision
            or self.requested_execution_mode is not self.served_execution_mode
        )
        if self.fallback_used != fallback_observed:
            raise ValueError("fallback flag must match requested and served identity")
        if self.fallback_used != (self.fallback_reason_code is not None):
            raise ValueError("fallback use requires exactly one safe reason code")
        return self

    @classmethod
    def from_artifact(
        cls,
        *,
        attempt_id: str,
        execution_id: str,
        case_id: str,
        plan_fingerprint: str,
        metric_question_fingerprint: str,
        evidence_packet_fingerprint: str,
        constellation_stage: ConstellationStageIdentity,
        artifact: ModelArtifactIdentity,
        fallback_used: bool,
        fallback_reason_code: str | None,
        attempted_at: datetime,
    ) -> AttemptIdentityReceipt:
        return cls(
            attempt_id=attempt_id,
            execution_id=execution_id,
            case_id=case_id,
            plan_fingerprint=plan_fingerprint,
            metric_question_fingerprint=metric_question_fingerprint,
            evidence_packet_fingerprint=evidence_packet_fingerprint,
            constellation_stage_fingerprint=constellation_stage.fingerprint,
            stage_ordinal=constellation_stage.ordinal,
            stage_kind=constellation_stage.kind,
            source=artifact.source,
            model_artifact_fingerprint=artifact.canonical_fingerprint,
            stage_configuration_sha256=constellation_stage.stage_configuration_sha256,
            requested_model_id=artifact.requested_model_id,
            served_model_id=artifact.served_model_id,
            requested_revision=artifact.requested_revision,
            served_revision=artifact.served_revision,
            requested_execution_mode=artifact.requested_execution_mode,
            served_execution_mode=artifact.served_execution_mode,
            fallback_used=fallback_used,
            fallback_reason_code=fallback_reason_code,
            attempted_at=attempted_at,
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AttemptOutcomeReceipt(StrictModel):
    """Immutable, content-free result projection emitted with one attempt.

    The output fingerprint commits the structured result before any stability
    projection is assembled. It is not a model-output body and cannot be
    exported or team-shared.
    """

    contract_version: Literal[ATTEMPT_OUTCOME_RECEIPT_V1] = (
        ATTEMPT_OUTCOME_RECEIPT_V1
    )
    outcome_id: str
    attempt_id: str
    execution_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    structured_output_fingerprint: str
    run_state: CaseRunState
    candidate_label: str | None = None
    candidate_confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    latency_class: LatencyClass
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    outcome_reason_code: str | None = None
    completed_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "outcome_id",
        "attempt_id",
        "execution_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "structured_output_fingerprint",
    )(_pseudonym)
    _label = field_validator("candidate_label")(_optional_code)
    _reason = field_validator("outcome_reason_code")(_optional_code)
    _completed = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def validate_outcome(self) -> AttemptOutcomeReceipt:
        if self.run_state is CaseRunState.COMPLETED:
            if (
                self.candidate_label is None
                or self.candidate_confidence is None
                or self.outcome_reason_code is not None
            ):
                raise ValueError("completed attempt outcome requires label and confidence")
        elif (
            self.candidate_label is not None
            or self.candidate_confidence is not None
            or self.outcome_reason_code is None
        ):
            raise ValueError("unavailable attempt outcome requires only a safe reason")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ExpectedAttempt(StrictModel):
    """One execution-stage attempt declared by an immutable execution manifest."""

    attempt_id: str
    execution_id: str
    case_id: str
    stage_ordinal: int = Field(ge=1, le=7)
    stage_kind: EstimatorStageKind

    _ids = field_validator("attempt_id", "execution_id", "case_id")(_pseudonym)

    @model_validator(mode="after")
    def validate_model_stage(self) -> ExpectedAttempt:
        if self.stage_kind not in MODEL_STAGE_KINDS:
            raise ValueError("expected attempts are limited to model stages")
        return self


class ExpectedAttemptManifest(StrictModel):
    """Fingerprint of the complete persisted execution/stage-receipt attempt set."""

    contract_version: Literal[EXPECTED_ATTEMPT_MANIFEST_V1] = (
        EXPECTED_ATTEMPT_MANIFEST_V1
    )
    manifest_id: str
    plan_fingerprint: str
    execution_set_fingerprint: str
    attempts: tuple[ExpectedAttempt, ...]
    frozen_at: datetime

    _ids = field_validator(
        "manifest_id", "plan_fingerprint", "execution_set_fingerprint"
    )(_pseudonym)
    _frozen = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def validate_complete_set(self) -> ExpectedAttemptManifest:
        if not self.attempts:
            raise ValueError("expected-attempt manifest requires persisted attempts")
        ids = tuple(item.attempt_id for item in self.attempts)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("expected attempts must be unique and sorted by attempt_id")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AuthoritativeCandidateProjection(StrictModel):
    """Repository-selected final candidate projection for one case.

    This explicit link avoids choosing a specialist/repeat attempt by incidental
    identifier order. A later persistence service will seal these projections;
    until then the pure evaluator remains non-authoritative.
    """

    contract_version: Literal[AUTHORITATIVE_CANDIDATE_PROJECTION_V1] = (
        AUTHORITATIVE_CANDIDATE_PROJECTION_V1
    )
    projection_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    authoritative_attempt_id: str
    authoritative_outcome_id: str
    authoritative_outcome_fingerprint: str
    final_estimate_fingerprint: str
    selected_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "projection_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
        "authoritative_attempt_id",
        "authoritative_outcome_id",
        "authoritative_outcome_fingerprint",
        "final_estimate_fingerprint",
    )(_pseudonym)
    _selected = field_validator("selected_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ExecutionIdentityAudit(StrictModel):
    contract_version: Literal[EXECUTION_IDENTITY_AUDIT_V1] = (
        EXECUTION_IDENTITY_AUDIT_V1
    )
    audit_id: str
    plan_fingerprint: str
    constellation_fingerprint: str
    expected_attempt_manifest_fingerprint: str
    auditor_version: str
    attempts: tuple[AttemptIdentityReceipt, ...]
    outcomes: tuple[AttemptOutcomeReceipt, ...]
    candidate_projections: tuple[AuthoritativeCandidateProjection, ...]
    coverage_started_at: datetime
    coverage_ended_at: datetime
    completed_at: datetime

    _ids = field_validator(
        "audit_id",
        "plan_fingerprint",
        "constellation_fingerprint",
        "expected_attempt_manifest_fingerprint",
    )(_pseudonym)
    _version = field_validator("auditor_version")(_safe_version)
    _times = field_validator(
        "coverage_started_at", "coverage_ended_at", "completed_at"
    )(_utc)

    @model_validator(mode="after")
    def validate_audit(self) -> ExecutionIdentityAudit:
        if self.coverage_ended_at < self.coverage_started_at:
            raise ValueError("identity-audit coverage window must be chronological")
        if self.completed_at < self.coverage_ended_at:
            raise ValueError("identity audit cannot complete before its coverage window")
        ids = tuple(item.attempt_id for item in self.attempts)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("attempt identities must be unique and sorted by attempt_id")
        if any(item.plan_fingerprint != self.plan_fingerprint for item in self.attempts):
            raise ValueError("every audited attempt must bind the audited plan")
        if any(
            not self.coverage_started_at <= item.attempted_at <= self.coverage_ended_at
            for item in self.attempts
        ):
            raise ValueError("every audited attempt must lie inside the coverage window")
        outcome_ids = tuple(item.attempt_id for item in self.outcomes)
        if outcome_ids != tuple(sorted(outcome_ids)) or len(outcome_ids) != len(
            set(outcome_ids)
        ):
            raise ValueError("attempt outcomes must be unique and sorted by attempt_id")
        if set(outcome_ids) != set(ids):
            raise ValueError("every audited attempt requires exactly one immutable outcome")
        attempts = {item.attempt_id: item for item in self.attempts}
        if any(
            outcome.execution_id != attempts[outcome.attempt_id].execution_id
            or outcome.case_id != attempts[outcome.attempt_id].case_id
            or outcome.plan_fingerprint != attempts[outcome.attempt_id].plan_fingerprint
            or outcome.metric_question_fingerprint
            != attempts[outcome.attempt_id].metric_question_fingerprint
            or outcome.evidence_packet_fingerprint
            != attempts[outcome.attempt_id].evidence_packet_fingerprint
            or outcome.completed_at < attempts[outcome.attempt_id].attempted_at
            or outcome.completed_at > self.coverage_ended_at
            for outcome in self.outcomes
        ):
            raise ValueError("attempt outcome lineage must match its identity receipt")
        projection_cases = tuple(item.case_id for item in self.candidate_projections)
        if projection_cases != tuple(sorted(projection_cases)) or len(
            projection_cases
        ) != len(set(projection_cases)):
            raise ValueError("candidate projections must be unique and sorted by case_id")
        outcomes = {item.attempt_id: item for item in self.outcomes}
        if any(
            item.authoritative_attempt_id not in attempts
            or item.authoritative_attempt_id not in outcomes
            or attempts[item.authoritative_attempt_id].stage_kind
            not in {
                EstimatorStageKind.SPECIALIST,
                EstimatorStageKind.SECOND_OPINION,
            }
            or item.authoritative_outcome_id
            != outcomes[item.authoritative_attempt_id].outcome_id
            or item.authoritative_outcome_fingerprint
            != outcomes[item.authoritative_attempt_id].fingerprint
            or item.case_id != attempts[item.authoritative_attempt_id].case_id
            or item.plan_fingerprint != attempts[item.authoritative_attempt_id].plan_fingerprint
            or item.metric_question_fingerprint
            != attempts[item.authoritative_attempt_id].metric_question_fingerprint
            or item.evidence_packet_fingerprint
            != attempts[item.authoritative_attempt_id].evidence_packet_fingerprint
            or item.selected_at < outcomes[item.authoritative_attempt_id].completed_at
            or item.selected_at > self.coverage_ended_at
            for item in self.candidate_projections
        ):
            raise ValueError("candidate projection must bind an audited immutable outcome")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class StabilityTrialV2(StrictModel):
    contract_version: Literal[STABILITY_TRIAL_V2] = STABILITY_TRIAL_V2
    trial_ordinal: int = Field(ge=1, le=20)
    attempt_id: str
    outcome_receipt_id: str
    outcome_fingerprint: str
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "attempt_id", "outcome_receipt_id", "outcome_fingerprint"
    )(_pseudonym)


class StabilityReceiptV2(StrictModel):
    contract_version: Literal[STABILITY_RECEIPT_V2] = STABILITY_RECEIPT_V2
    receipt_id: str
    case_id: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    condition: StabilityCondition
    trials: tuple[StabilityTrialV2, ...] = Field(min_length=2, max_length=20)
    observed_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "receipt_id",
        "case_id",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_pseudonym)
    _observed = field_validator("observed_at")(_utc)

    @model_validator(mode="after")
    def validate_trials(self) -> StabilityReceiptV2:
        ordinals = tuple(item.trial_ordinal for item in self.trials)
        if ordinals != tuple(range(1, len(self.trials) + 1)):
            raise ValueError("stability trials must be a contiguous ordered sequence")
        attempts = tuple(item.attempt_id for item in self.trials)
        if len(attempts) != len(set(attempts)):
            raise ValueError("stability trials must reference distinct attempts")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class BlindCalibrationJudgment(StrictModel):
    contract_version: Literal[BLIND_CALIBRATION_JUDGMENT_V1] = (
        BLIND_CALIBRATION_JUDGMENT_V1
    )
    judgment_id: str
    adjudicator_id: str
    case_id: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    label_code: str
    annotation_protocol_version: str
    created_at: datetime
    blinded_to_candidate: Literal[True] = True
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "judgment_id",
        "adjudicator_id",
        "case_id",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_pseudonym)
    _label = field_validator("label_code")(_safe_code)
    _version = field_validator("annotation_protocol_version")(_safe_version)
    _created = field_validator("created_at")(_utc)


class BlindCalibrationAdjudication(StrictModel):
    contract_version: Literal[BLIND_CALIBRATION_ADJUDICATION_V1] = (
        BLIND_CALIBRATION_ADJUDICATION_V1
    )
    adjudication_id: str
    case_id: str
    plan_fingerprint: str
    metric_question_fingerprint: str
    evidence_packet_fingerprint: str
    source: BlindCalibrationSource
    resolution: BlindCalibrationResolution
    judgments: tuple[BlindCalibrationJudgment, ...] = Field(min_length=1, max_length=32)
    resolved_label_code: str | None = None
    unresolved_reason_code: str | None = None
    completed_at: datetime
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "adjudication_id",
        "case_id",
        "plan_fingerprint",
        "metric_question_fingerprint",
        "evidence_packet_fingerprint",
    )(_pseudonym)
    _label = field_validator("resolved_label_code")(_optional_code)
    _reason = field_validator("unresolved_reason_code")(_optional_code)
    _completed = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def validate_blind_adjudication(self) -> BlindCalibrationAdjudication:
        keys = tuple((item.created_at, item.judgment_id) for item in self.judgments)
        if keys != tuple(sorted(keys)) or len(
            {item.judgment_id for item in self.judgments}
        ) != len(self.judgments):
            raise ValueError("blind judgments must be unique and chronologically sorted")
        if any(
            item.case_id != self.case_id
            or item.metric_question_fingerprint != self.metric_question_fingerprint
            or item.evidence_packet_fingerprint != self.evidence_packet_fingerprint
            or item.created_at > self.completed_at
            for item in self.judgments
        ):
            raise ValueError("blind judgments must match the adjudicated case and lineage")
        if self.resolution is BlindCalibrationResolution.RESOLVED:
            if self.resolved_label_code is None or self.unresolved_reason_code is not None:
                raise ValueError("resolved adjudication requires only a final label")
            if len({item.adjudicator_id for item in self.judgments}) < 2:
                raise ValueError("resolved calibration requires two distinct humans")
            if self.resolved_label_code not in {
                item.label_code for item in self.judgments
            }:
                raise ValueError("resolved label must be supported by a blind judgment")
        elif self.resolved_label_code is not None or self.unresolved_reason_code is None:
            raise ValueError("unresolved adjudication requires only a safe reason")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class GatePreregistrationV2(StrictModel):
    """Pre-holdout commitment to the stored plan and its exact constellation."""

    contract_version: Literal[GATE_PREREGISTRATION_V2] = GATE_PREREGISTRATION_V2
    preregistration_id: str
    policy_fingerprint: str
    assignment_manifest_fingerprint: str
    split_fingerprint: str
    stored_plan_fingerprint: str
    constellation_fingerprint: str
    legacy_preregistration_fingerprint: str
    registered_at: datetime

    _ids = field_validator(
        "preregistration_id",
        "policy_fingerprint",
        "assignment_manifest_fingerprint",
        "split_fingerprint",
        "stored_plan_fingerprint",
        "constellation_fingerprint",
        "legacy_preregistration_fingerprint",
    )(_pseudonym)
    _registered = field_validator("registered_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class GateEvidenceV2(StrictModel):
    """All v2 gate evidence; it carries no eligibility or activation hint."""

    contract_version: Literal[GATE_EVIDENCE_V2] = GATE_EVIDENCE_V2
    evidence_id: str
    stored_plan_fingerprint: str
    assignment_manifest: CaseAssignmentManifestV2
    cohort: CalibrationCohort
    split: CalibrationSplit
    preregistration: GatePreregistration
    preregistration_v2: GatePreregistrationV2 | None
    constellation_identity: ConstellationIdentityReceipt | None
    expected_attempt_manifest: ExpectedAttemptManifest | None
    execution_identity_audit: ExecutionIdentityAudit | None
    holdout_access_audit: HoldoutAccessAuditReceipt | None
    stability_receipts: tuple[StabilityReceiptV2, ...] = ()
    blind_adjudications: tuple[BlindCalibrationAdjudication, ...] = ()
    privacy_scan: PrivacyScanReceipt | None = None
    completed_at: datetime
    sensitive_label_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("evidence_id", "stored_plan_fingerprint")(_pseudonym)
    _completed = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def validate_canonical_children(self) -> GateEvidenceV2:
        stability_keys = tuple(
            (item.case_id, item.condition.value) for item in self.stability_receipts
        )
        if stability_keys != tuple(sorted(stability_keys)) or len(stability_keys) != len(
            set(stability_keys)
        ):
            raise ValueError("stability receipts must be unique and canonically sorted")
        blind_keys = tuple(
            (item.case_id, item.source.value) for item in self.blind_adjudications
        )
        if blind_keys != tuple(sorted(blind_keys)) or len(blind_keys) != len(
            set(blind_keys)
        ):
            raise ValueError("blind adjudications must be unique and canonically sorted")
        if self.constellation_identity is not None and (
            self.constellation_identity.frozen_at > self.completed_at
        ):
            raise ValueError("constellation identity must precede evidence completion")
        if self.execution_identity_audit is not None and (
            self.execution_identity_audit.completed_at > self.completed_at
        ):
            raise ValueError("identity audit must precede evidence completion")
        if any(item.observed_at > self.completed_at for item in self.stability_receipts):
            raise ValueError("stability observations must precede evidence completion")
        if any(item.completed_at > self.completed_at for item in self.blind_adjudications):
            raise ValueError("blind adjudications must precede evidence completion")
        return self

    @property
    def scannable_fingerprint(self) -> str:
        """Fingerprint the complete payload other than its scan receipt."""

        return _canonical_payload_digest(
            self.model_dump(mode="json", exclude={"privacy_scan"})
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ActivationGateDecisionV2(StrictModel):
    contract_version: Literal[ACTIVATION_GATE_DECISION_V2] = (
        ACTIVATION_GATE_DECISION_V2
    )
    decision_id: str
    stored_plan_fingerprint: str
    evidence_fingerprint: str
    policy_fingerprint: str
    preregistration_fingerprint: str
    preregistration_v2_fingerprint: str | None
    outcome: ActivationOutcome
    authoritative: Literal[False] = False
    checks: tuple[ActivationGateCheck, ...]
    derived_at: datetime

    _ids = field_validator(
        "decision_id",
        "stored_plan_fingerprint",
        "evidence_fingerprint",
        "policy_fingerprint",
        "preregistration_fingerprint",
    )(_pseudonym)
    _optional_preregistration = field_validator("preregistration_v2_fingerprint")(
        lambda value: None if value is None else _pseudonym(value)
    )
    _derived = field_validator("derived_at")(_utc)

    @model_validator(mode="after")
    def validate_derived_outcome(self) -> ActivationGateDecisionV2:
        if not self.checks:
            raise ValueError("activation decision requires derived checks")
        keys = tuple(item.check_key for item in self.checks)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("activation checks must be unique and sorted")
        outcomes = {item.outcome for item in self.checks}
        expected = (
            ActivationOutcome.REJECTED
            if GateCheckOutcome.FAIL in outcomes
            else ActivationOutcome.INSUFFICIENT_DATA
            if GateCheckOutcome.INSUFFICIENT_DATA in outcomes
            else ActivationOutcome.ELIGIBLE
        )
        if self.outcome is not expected:
            raise ValueError("decision outcome must be derived from its checks")
        if self.outcome is ActivationOutcome.ELIGIBLE:
            raise ValueError(
                "unsealed v2 gate decisions cannot authorize activation"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def finite_measurement(value: float | int | None) -> float | int | None:
    """Shared defensive validator hook for derived evaluator measurements."""

    if value is not None and (
        isinstance(value, bool) or not math.isfinite(float(value))
    ):
        raise ValueError("gate measurements must be finite numeric data")
    return value
