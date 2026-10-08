"""Immutable, content-free manifests for estimator activation decisions.

The gate deliberately has no caller-supplied eligibility, holdout-integrity, or
privacy booleans.  It derives those facts from fingerprint-linked case, split,
audit, and scan receipts.  These contracts contain only opaque identifiers,
enumerations, counts, timestamps, labels, and bounded measurements; prompt or
evidence bodies cannot cross this boundary.
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
    SAFE_METRIC_TEXT_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    StrictModel,
)


ESTIMATOR_CASE_CONTRACT_VERSION = "estimator-case-v1"
CASE_ASSIGNMENT_CONTRACT_VERSION = "case-assignment-v1"
CASE_ASSIGNMENT_MANIFEST_CONTRACT_VERSION = "case-assignment-manifest-v1"
CALIBRATION_COHORT_CONTRACT_VERSION = "calibration-cohort-v1"
CALIBRATION_SPLIT_CONTRACT_VERSION = "calibration-split-v1"
ESTIMATOR_IDENTITY_RECEIPT_VERSION = "estimator-identity-receipt-v1"
GATE_PREREGISTRATION_CONTRACT_VERSION = "gate-preregistration-v1"
HOLDOUT_ACCESS_AUDIT_RECEIPT_VERSION = "holdout-access-audit-v1"
STABILITY_RECEIPT_CONTRACT_VERSION = "stability-receipt-v1"
CALIBRATION_EVIDENCE_BUNDLE_VERSION = "calibration-evidence-bundle-v1"
PRIVACY_SCAN_RECEIPT_VERSION = "privacy-scan-receipt-v1"
CALIBRATION_REPORT_CONTRACT_VERSION = "calibration-report-v1"
GATE_POLICY_CONTRACT_VERSION = "gate-policy-v1"
ACTIVATION_GATE_DECISION_VERSION = "activation-gate-decision-v1"

ACTIVE_LEARNING_MINIMUM = 100
ACTIVE_LEARNING_MAXIMUM = 200

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _canonical_digest(model: StrictModel) -> str:
    return _canonical_payload_digest(model.model_dump(mode="json"))


def _canonical_payload_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 pseudonym")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _safe_metric_key(value: str) -> str:
    if SAFE_METRIC_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("metric key must be a lowercase content-free identifier")
    return value


def _safe_label(value: str) -> str:
    if SAFE_METRIC_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("label must be a lowercase content-free identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _finite_nonnegative(value: float, *, field: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def _bounded_probability(value: float, *, field: str) -> float:
    number = _finite_nonnegative(value, field=field)
    if number > 1:
        raise ValueError(f"{field} must be between zero and one")
    return number


def _canonical_ids(values: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not allow_empty and not values:
        raise ValueError("identifier set may not be empty")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("identifiers must be unique and sorted")
    return tuple(_pseudonym(value) for value in values)


class CalibrationTaskStratum(StrEnum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    CODE_REVIEW = "code_review"
    RESEARCH_DESIGN = "research_design"


class CalibrationLanguage(StrEnum):
    EN = "en"
    PL = "pl"


class CaseOrigin(StrEnum):
    PRIVATE_REPRESENTATIVE = "private_representative"
    PUBLIC_BENCHMARK = "public_benchmark"
    SYNTHETIC = "synthetic"


class ReferenceTruthSource(StrEnum):
    OBJECTIVE_CHECK = "objective_check"
    HUMAN_ADJUDICATED = "human_adjudicated"
    INDEPENDENT_HUMAN = "independent_human"
    MODEL_CONSENSUS = "model_consensus"
    SELF_REPORTED_COMPLETION = "self_reported_completion"


class EvidenceTier(StrEnum):
    OBJECTIVE = "objective"
    HUMAN = "human"
    INFERRED = "inferred"


class EstimatorSource(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_WEIGHTS = "local_weights"
    OPENAI_API = "openai_api"
    ANTHROPIC_API = "anthropic_api"
    CODEX_CLI = "codex_cli"
    MANUAL_IMPORT = "manual_import"
    SYNTHETIC = "synthetic"


class EstimatorExecutionMode(StrEnum):
    STANDARD = "standard"
    PRO = "pro"


class CaseRunState(StrEnum):
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    OOM = "oom"
    ERROR = "error"
    REFUSAL = "refusal"


class LatencyClass(StrEnum):
    COLD = "cold"
    WARM = "warm"


class StabilityCondition(StrEnum):
    REPEAT = "repeat"
    ORDER = "order"
    FORMAT = "format"
    INJECTION = "injection"


class MetricRiskTier(StrEnum):
    STANDARD = "standard"
    HIGH = "high"


class SubgroupDimension(StrEnum):
    TASK_STRATUM = "task_stratum"
    LANGUAGE = "language"
    PROVIDER = "provider"
    EVIDENCE_TIER = "evidence_tier"


class GateCheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"


class ActivationOutcome(StrEnum):
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"


class CaseAssignment(StrictModel):
    """Static case projection that may be frozen before estimator execution."""

    contract_version: Literal[CASE_ASSIGNMENT_CONTRACT_VERSION] = (
        CASE_ASSIGNMENT_CONTRACT_VERSION
    )
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

    _validate_ids = field_validator(
        "case_id", "project_id", "session_revision_id"
    )(_pseudonym)
    _validate_metric = field_validator("metric_key")(_safe_metric_key)
    _validate_time = field_validator("observed_at")(_utc)

    @classmethod
    def from_case(cls, case: EstimatorCase) -> CaseAssignment:
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
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CaseAssignmentManifest(StrictModel):
    """Immutable case membership and slice assignment, frozen pre-evaluation."""

    contract_version: Literal[CASE_ASSIGNMENT_MANIFEST_CONTRACT_VERSION] = (
        CASE_ASSIGNMENT_MANIFEST_CONTRACT_VERSION
    )
    manifest_id: str
    frozen_at: datetime
    assignments: tuple[CaseAssignment, ...]

    _validate_id = field_validator("manifest_id")(_pseudonym)
    _validate_time = field_validator("frozen_at")(_utc)

    @model_validator(mode="after")
    def _validate_assignments(self) -> CaseAssignmentManifest:
        if not self.assignments:
            raise ValueError("case assignment manifest requires assignments")
        ids = tuple(item.case_id for item in self.assignments)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("case assignments must be unique and sorted by case_id")
        if any(item.observed_at > self.frozen_at for item in self.assignments):
            raise ValueError("case assignment may not predate its observation")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorCase(StrictModel):
    """One immutable, content-free judgment and execution receipt."""

    contract_version: Literal[ESTIMATOR_CASE_CONTRACT_VERSION] = (
        ESTIMATOR_CASE_CONTRACT_VERSION
    )
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
    evaluated_at: datetime
    truth_source: ReferenceTruthSource
    truth_receipt_id: str | None
    reference_label: str
    candidate_label: str | None
    candidate_confidence: float | None
    baseline_label: str | None
    human_baseline_label: str | None
    human_adjudication_receipt_id: str | None
    run_state: CaseRunState
    latency_class: LatencyClass
    latency_ms: float | None

    _validate_ids = field_validator(
        "case_id", "project_id", "session_revision_id"
    )(_pseudonym)
    _validate_optional_receipts = field_validator(
        "truth_receipt_id", "human_adjudication_receipt_id"
    )(lambda value: None if value is None else _pseudonym(value))
    _validate_metric = field_validator("metric_key")(_safe_metric_key)
    _validate_required_label = field_validator("reference_label")(_safe_label)
    _validate_optional_labels = field_validator(
        "candidate_label", "baseline_label", "human_baseline_label"
    )(lambda value: None if value is None else _safe_label(value))
    _validate_times = field_validator("observed_at", "evaluated_at")(_utc)
    _validate_confidence = field_validator("candidate_confidence")(
        lambda value: None
        if value is None
        else _bounded_probability(value, field="candidate_confidence")
    )
    _validate_latency = field_validator("latency_ms")(
        lambda value: None
        if value is None
        else _finite_nonnegative(value, field="latency_ms")
    )

    @model_validator(mode="after")
    def _validate_execution_shape(self) -> EstimatorCase:
        if self.evaluated_at < self.observed_at:
            raise ValueError("evaluated_at may not precede observed_at")
        if self.truth_source in {
            ReferenceTruthSource.OBJECTIVE_CHECK,
            ReferenceTruthSource.HUMAN_ADJUDICATED,
            ReferenceTruthSource.INDEPENDENT_HUMAN,
        } and self.truth_receipt_id is None:
            raise ValueError("supported truth requires an opaque truth receipt")
        if self.run_state is CaseRunState.COMPLETED:
            if self.candidate_label is None or self.candidate_confidence is None:
                raise ValueError("completed run requires label and confidence")
        elif self.candidate_label is not None or self.candidate_confidence is not None:
            raise ValueError("non-completed run may not carry a candidate judgment")
        if self.latency_ms is None:
            raise ValueError("each attempted run requires a latency measurement")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)

class CalibrationCohort(StrictModel):
    contract_version: Literal[CALIBRATION_COHORT_CONTRACT_VERSION] = (
        CALIBRATION_COHORT_CONTRACT_VERSION
    )
    cohort_id: str
    completed_at: datetime
    cases: tuple[EstimatorCase, ...]

    _validate_id = field_validator("cohort_id")(_pseudonym)
    _validate_time = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def _validate_cases(self) -> CalibrationCohort:
        if not self.cases:
            raise ValueError("cohort requires cases")
        ids = tuple(case.case_id for case in self.cases)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("cohort cases must be unique and sorted by case_id")
        if any(case.evaluated_at > self.completed_at for case in self.cases):
            raise ValueError("case evaluations must exist before cohort completion")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)

class CalibrationSplit(StrictModel):
    contract_version: Literal[CALIBRATION_SPLIT_CONTRACT_VERSION] = (
        CALIBRATION_SPLIT_CONTRACT_VERSION
    )
    split_id: str
    assignment_manifest_fingerprint: str
    frozen_at: datetime
    development_case_ids: tuple[str, ...]
    active_learning_case_ids: tuple[str, ...]
    holdout_case_ids: tuple[str, ...]

    _validate_id = field_validator("split_id")(_pseudonym)
    _validate_manifest = field_validator("assignment_manifest_fingerprint")(_pseudonym)
    _validate_time = field_validator("frozen_at")(_utc)
    _validate_development = field_validator("development_case_ids")(
        lambda values: _canonical_ids(values, allow_empty=True)
    )
    _validate_active = field_validator("active_learning_case_ids")(_canonical_ids)
    _validate_holdout = field_validator("holdout_case_ids")(_canonical_ids)

    @model_validator(mode="after")
    def _validate_partitions(self) -> CalibrationSplit:
        partitions = (
            self.development_case_ids,
            self.active_learning_case_ids,
            self.holdout_case_ids,
        )
        flattened = tuple(item for partition in partitions for item in partition)
        if len(flattened) != len(set(flattened)):
            raise ValueError("calibration split partitions must be disjoint")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class EstimatorIdentityReceipt(StrictModel):
    contract_version: Literal[ESTIMATOR_IDENTITY_RECEIPT_VERSION] = (
        ESTIMATOR_IDENTITY_RECEIPT_VERSION
    )
    identity_id: str
    source: EstimatorSource
    plan_fingerprint: str
    requested_model_id: str
    served_model_id: str
    requested_model_revision: str
    served_model_revision: str
    requested_execution_mode: EstimatorExecutionMode
    served_execution_mode: EstimatorExecutionMode
    configuration_fingerprint: str
    frozen_at: datetime

    _validate_id = field_validator("identity_id")(_pseudonym)
    _validate_digests = field_validator(
        "plan_fingerprint", "configuration_fingerprint"
    )(_pseudonym)
    _validate_models = field_validator(
        "requested_model_id",
        "served_model_id",
        "requested_model_revision",
        "served_model_revision",
    )(_safe_version)
    _validate_time = field_validator("frozen_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class MetricGateSpec(StrictModel):
    metric_key: str
    label_vocabulary: tuple[str, ...]
    risk_tier: MetricRiskTier
    positive_label: str | None = None

    _validate_metric = field_validator("metric_key")(_safe_metric_key)

    @field_validator("label_vocabulary")
    @classmethod
    def _validate_vocabulary(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) < 2 or values != tuple(sorted(values)) or len(values) != len(set(values)):
            raise ValueError("label vocabulary must contain at least two unique sorted labels")
        return tuple(_safe_label(value) for value in values)

    _validate_positive = field_validator("positive_label")(
        lambda value: None if value is None else _safe_label(value)
    )

    @model_validator(mode="after")
    def _validate_risk_shape(self) -> MetricGateSpec:
        if self.risk_tier is MetricRiskTier.HIGH:
            if self.positive_label is None:
                raise ValueError("high-risk metric requires a registered positive label")
            if self.positive_label not in self.label_vocabulary:
                raise ValueError("positive label must belong to the label vocabulary")
        elif self.positive_label is not None:
            raise ValueError("standard metric may not declare a high-risk positive label")
        return self


class GatePreregistration(StrictModel):
    contract_version: Literal[GATE_PREREGISTRATION_CONTRACT_VERSION] = (
        GATE_PREREGISTRATION_CONTRACT_VERSION
    )
    preregistration_id: str
    policy_fingerprint: str
    assignment_manifest_fingerprint: str
    split_fingerprint: str
    estimator_identity_fingerprint: str
    registered_at: datetime
    metric_specs: tuple[MetricGateSpec, ...]

    _validate_id = field_validator("preregistration_id")(_pseudonym)
    _validate_fingerprints = field_validator(
        "policy_fingerprint",
        "assignment_manifest_fingerprint",
        "split_fingerprint",
        "estimator_identity_fingerprint",
    )(_pseudonym)
    _validate_time = field_validator("registered_at")(_utc)

    @model_validator(mode="after")
    def _validate_metrics(self) -> GatePreregistration:
        if not self.metric_specs:
            raise ValueError("preregistration requires at least one metric")
        keys = tuple(spec.metric_key for spec in self.metric_specs)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("metric specs must be unique and sorted by metric_key")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class HoldoutAccessAuditReceipt(StrictModel):
    contract_version: Literal[HOLDOUT_ACCESS_AUDIT_RECEIPT_VERSION] = (
        HOLDOUT_ACCESS_AUDIT_RECEIPT_VERSION
    )
    audit_id: str
    split_fingerprint: str
    auditor_version: str
    access_log_fingerprint: str
    coverage_started_at: datetime
    coverage_ended_at: datetime
    unauthorized_access_count: int = Field(ge=0)
    missing_event_count: int = Field(ge=0)

    _validate_id = field_validator("audit_id")(_pseudonym)
    _validate_digests = field_validator(
        "split_fingerprint", "access_log_fingerprint"
    )(_pseudonym)
    _validate_version = field_validator("auditor_version")(_safe_version)
    _validate_times = field_validator("coverage_started_at", "coverage_ended_at")(_utc)

    @model_validator(mode="after")
    def _validate_window(self) -> HoldoutAccessAuditReceipt:
        if self.coverage_ended_at < self.coverage_started_at:
            raise ValueError("access-audit window must be chronological")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class StabilityReceipt(StrictModel):
    contract_version: Literal[STABILITY_RECEIPT_CONTRACT_VERSION] = (
        STABILITY_RECEIPT_CONTRACT_VERSION
    )
    receipt_id: str
    case_id: str
    condition: StabilityCondition
    trial_labels: tuple[str | None, ...]
    observed_at: datetime

    _validate_ids = field_validator("receipt_id", "case_id")(_pseudonym)
    _validate_time = field_validator("observed_at")(_utc)

    @field_validator("trial_labels")
    @classmethod
    def _validate_labels(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        if len(values) < 2 or len(values) > 20:
            raise ValueError("stability receipt requires between two and twenty trials")
        return tuple(None if value is None else _safe_label(value) for value in values)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CalibrationEvidenceBundle(StrictModel):
    contract_version: Literal[CALIBRATION_EVIDENCE_BUNDLE_VERSION] = (
        CALIBRATION_EVIDENCE_BUNDLE_VERSION
    )
    estimator_identity: EstimatorIdentityReceipt
    assignment_manifest: CaseAssignmentManifest
    cohort: CalibrationCohort
    split: CalibrationSplit
    preregistration: GatePreregistration
    holdout_access_audit: HoldoutAccessAuditReceipt | None
    stability_receipts: tuple[StabilityReceipt, ...]
    completed_at: datetime

    _validate_time = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def _validate_stability_order(self) -> CalibrationEvidenceBundle:
        pairs = tuple(
            (receipt.case_id, receipt.condition.value)
            for receipt in self.stability_receipts
        )
        if pairs != tuple(sorted(pairs)) or len(pairs) != len(set(pairs)):
            raise ValueError(
                "stability receipts must be unique per case/condition and canonically sorted"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class PrivacyScanReceipt(StrictModel):
    contract_version: Literal[PRIVACY_SCAN_RECEIPT_VERSION] = PRIVACY_SCAN_RECEIPT_VERSION
    scan_id: str
    scanned_bundle_fingerprint: str
    scanner_version: str
    completed_at: datetime
    pii_finding_count: int = Field(ge=0)
    secret_finding_count: int = Field(ge=0)
    private_content_finding_count: int = Field(ge=0)

    _validate_id = field_validator("scan_id")(_pseudonym)
    _validate_digest = field_validator("scanned_bundle_fingerprint")(_pseudonym)
    _validate_version = field_validator("scanner_version")(_safe_version)
    _validate_time = field_validator("completed_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CalibrationReport(StrictModel):
    contract_version: Literal[CALIBRATION_REPORT_CONTRACT_VERSION] = (
        CALIBRATION_REPORT_CONTRACT_VERSION
    )
    report_id: str
    evidence_bundle: CalibrationEvidenceBundle
    privacy_scan: PrivacyScanReceipt | None
    emitted_at: datetime

    _validate_id = field_validator("report_id")(_pseudonym)
    _validate_time = field_validator("emitted_at")(_utc)

    @model_validator(mode="after")
    def _validate_chronology(self) -> CalibrationReport:
        if self.emitted_at < self.evidence_bundle.completed_at:
            raise ValueError("report may not precede evidence-bundle completion")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class HighRiskPrecisionRule(StrictModel):
    metric_key: str
    minimum_precision: float
    minimum_positive_predictions: int = Field(gt=0)

    _validate_metric = field_validator("metric_key")(_safe_metric_key)
    _validate_precision = field_validator("minimum_precision")(
        lambda value: _bounded_probability(value, field="minimum_precision")
    )


class GatePolicy(StrictModel):
    """Preregistered thresholds; none is an observed eligibility fact."""

    contract_version: Literal[GATE_POLICY_CONTRACT_VERSION] = GATE_POLICY_CONTRACT_VERSION
    policy_id: str
    minimum_active_learning_count: int = Field(
        default=ACTIVE_LEARNING_MINIMUM, ge=ACTIVE_LEARNING_MINIMUM
    )
    maximum_active_learning_count: int = Field(
        default=ACTIVE_LEARNING_MAXIMUM, le=ACTIVE_LEARNING_MAXIMUM
    )
    minimum_holdout_count: int = Field(gt=0)
    minimum_holdout_per_metric: int = Field(gt=0)
    minimum_holdout_per_stratum: int = Field(gt=0)
    minimum_holdout_per_language: int = Field(gt=0)
    minimum_operational_samples_per_latency_class: int = Field(gt=0)
    minimum_subgroup_size: int = Field(gt=0)
    minimum_baseline_margin: float
    maximum_human_gap: float = 0.05
    maximum_ece: float = 0.05
    minimum_repeat_stability: float = 0.95
    minimum_selective_coverage: float
    maximum_selective_risk: float
    false_confidence_threshold: float
    maximum_false_confident_error_rate: float
    maximum_cold_p95_latency_ms: float
    maximum_warm_p95_latency_ms: float
    maximum_oom_rate: float
    maximum_error_rate: float
    maximum_refusal_rate: float
    maximum_material_subgroup_regression: float
    required_strata: tuple[CalibrationTaskStratum, ...] = tuple(CalibrationTaskStratum)
    required_languages: tuple[CalibrationLanguage, ...] = tuple(CalibrationLanguage)
    subgroup_dimensions: tuple[SubgroupDimension, ...] = tuple(
        sorted(SubgroupDimension, key=lambda item: item.value)
    )
    high_risk_precision_rules: tuple[HighRiskPrecisionRule, ...] = ()

    _validate_id = field_validator("policy_id")(_pseudonym)
    _validate_probabilities = field_validator(
        "maximum_human_gap",
        "maximum_ece",
        "minimum_repeat_stability",
        "minimum_selective_coverage",
        "maximum_selective_risk",
        "false_confidence_threshold",
        "maximum_false_confident_error_rate",
        "maximum_oom_rate",
        "maximum_error_rate",
        "maximum_refusal_rate",
        "maximum_material_subgroup_regression",
    )(lambda value, info: _bounded_probability(value, field=info.field_name))
    _validate_margin = field_validator("minimum_baseline_margin")(
        lambda value: _finite_nonnegative(value, field="minimum_baseline_margin")
    )
    _validate_latencies = field_validator(
        "maximum_cold_p95_latency_ms", "maximum_warm_p95_latency_ms"
    )(lambda value, info: _finite_nonnegative(value, field=info.field_name))

    @model_validator(mode="after")
    def _validate_policy(self) -> GatePolicy:
        if self.minimum_active_learning_count > self.maximum_active_learning_count:
            raise ValueError("active-learning bounds are inverted")
        if self.required_strata != tuple(CalibrationTaskStratum):
            raise ValueError("the first release gate requires all four task strata")
        if self.required_languages != tuple(CalibrationLanguage):
            raise ValueError("the first release gate requires EN and PL")
        if (
            not self.subgroup_dimensions
            or self.subgroup_dimensions
            != tuple(sorted(self.subgroup_dimensions, key=lambda item: item.value))
            or len(self.subgroup_dimensions) != len(set(self.subgroup_dimensions))
        ):
            raise ValueError("subgroup dimensions must be unique and sorted")
        keys = tuple(rule.metric_key for rule in self.high_risk_precision_rules)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("high-risk rules must be unique and sorted by metric_key")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ActivationGateCheck(StrictModel):
    check_key: str
    outcome: GateCheckOutcome
    actual: float | int | None
    threshold: float | int | None
    reason_code: str | None = None

    _validate_key = field_validator("check_key")(_safe_code)
    _validate_reason = field_validator("reason_code")(
        lambda value: None if value is None else _safe_code(value)
    )

    @field_validator("actual", "threshold")
    @classmethod
    def _validate_measurement(cls, value: float | int | None) -> float | int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("gate measurement must be finite numeric data")
        return value


class ActivationGateDecision(StrictModel):
    contract_version: Literal[ACTIVATION_GATE_DECISION_VERSION] = (
        ACTIVATION_GATE_DECISION_VERSION
    )
    decision_id: str
    report_fingerprint: str
    policy_fingerprint: str
    preregistration_fingerprint: str
    outcome: ActivationOutcome
    checks: tuple[ActivationGateCheck, ...]
    derived_at: datetime

    _validate_id = field_validator("decision_id")(_pseudonym)
    _validate_fingerprints = field_validator(
        "report_fingerprint", "policy_fingerprint", "preregistration_fingerprint"
    )(_pseudonym)
    _validate_time = field_validator("derived_at")(_utc)

    @model_validator(mode="after")
    def _validate_checks(self) -> ActivationGateDecision:
        if not self.checks:
            raise ValueError("activation decision requires checks")
        keys = tuple(check.check_key for check in self.checks)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("gate checks must be unique and sorted by check_key")
        outcomes = {check.outcome for check in self.checks}
        expected = (
            ActivationOutcome.REJECTED
            if GateCheckOutcome.FAIL in outcomes
            else ActivationOutcome.INSUFFICIENT_DATA
            if GateCheckOutcome.INSUFFICIENT_DATA in outcomes
            else ActivationOutcome.ELIGIBLE
        )
        if self.outcome is not expected:
            raise ValueError("decision outcome must be derived from its checks")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)
