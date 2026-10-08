"""Content-free contracts for an untrusted calibration-report foundation.

These contracts deliberately have no activation decision or runtime-enable
surface.  The in-memory derivation service accepts caller-constructed hydrated
domain objects, so its output is explicitly an ``untrusted_projection``.  A
later persistence migration must read sealed rows, apply a repository clock,
rehydrate the complete report, and reproduce its fingerprint before any
comparison or activation evaluator may consume it.

Only opaque identifiers, closed codes, bounded scalar measurements, counts,
and aggregate calibration receipts belong here.  Prompts, evidence bodies,
model output, rationales, paths, URIs, and reviewer prose are forbidden.
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

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel


CALIBRATION_REPORT_DEFINITION_V1 = "calibration-report-definition-v1"
CALIBRATION_COMPARISON_IDENTITY_V1 = "calibration-comparison-identity-v1"
CALIBRATION_REPORT_SCOPE_V1 = "calibration-report-scope-v1"
CALIBRATION_MEASUREMENT_SPEC_V1 = "calibration-measurement-spec-v1"
CALIBRATION_MEASUREMENT_V1 = "calibration-measurement-v1"
CALIBRATION_CONFUSION_CELL_V1 = "calibration-confusion-cell-v1"
CALIBRATION_CLASS_RECEIPT_V1 = "calibration-class-receipt-v1"
CALIBRATION_RELIABILITY_BIN_V1 = "calibration-reliability-bin-v1"
CALIBRATION_SELECTIVE_POINT_V1 = "calibration-selective-point-v1"
CALIBRATION_AGREEMENT_RECEIPT_V1 = "calibration-agreement-receipt-v1"
CALIBRATION_STABILITY_RECEIPT_V1 = "calibration-stability-receipt-v1"
CALIBRATION_RESOURCE_RECEIPT_V1 = "calibration-resource-receipt-v1"
CALIBRATION_MISSINGNESS_RECEIPT_V1 = "calibration-missingness-receipt-v1"
CALIBRATION_METRIC_REPORT_V1 = "calibration-metric-report-v1"
UNTRUSTED_CALIBRATION_REPORT_V1 = "untrusted-calibration-report-v1"
MODEL_LAB_CALIBRATION_REPORT_SUMMARY_V1 = (
    "model-lab-calibration-report-summary-v1"
)
MODEL_LAB_CALIBRATION_INVENTORY_V1 = "model-lab-calibration-inventory-v1"

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_METRIC_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


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
    return value


def _optional_code(value: str | None) -> str | None:
    return None if value is None else _safe_code(value)


def _safe_metric(value: str) -> str:
    if _SAFE_METRIC_PATTERN.fullmatch(value) is None:
        raise ValueError("metric key must be a lowercase content-free identifier")
    return value


def _safe_version(value: str) -> str:
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _finite(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError("measurement values must be finite numbers")
    return float(value)


def _probability(value: float) -> float:
    number = _finite(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("probability must be between zero and one")
    return number


class CalibrationReportState(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    INSUFFICIENT_DATA = "insufficient_data"


class CalibrationMeasurementState(StrEnum):
    KNOWN = "known"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not_applicable"
    INCOMPATIBLE = "incompatible"


class CalibrationMeasurementFamily(StrEnum):
    COVERAGE = "coverage"
    CLASSIFICATION = "classification"
    CALIBRATION = "calibration"
    AGREEMENT = "agreement"
    STABILITY = "stability"
    RESOURCE = "resource"
    RETRIEVAL = "retrieval"
    CASCADE = "cascade"
    NUMERIC = "numeric"


class CalibrationMeasurementShape(StrEnum):
    COUNT = "count"
    SCALAR = "scalar"
    RATE = "rate"


class CalibrationScopeDimension(StrEnum):
    OVERALL = "overall"
    TASK = "task"
    LANGUAGE = "language"
    PROVIDER = "provider"
    PROJECT = "project"
    TIME = "time"
    EVIDENCE_AVAILABILITY = "evidence_availability"


class CalibrationTruthSource(StrEnum):
    OBJECTIVE = "objective"
    RESOLVED_INDEPENDENT_HUMAN = "resolved_independent_human"
    UNAVAILABLE = "unavailable"


class CalibrationAgreementKind(StrEnum):
    HUMAN_HUMAN = "human_human"
    MODEL_HUMAN = "model_human"


class CalibrationStabilityCondition(StrEnum):
    REPEAT = "repeat"
    ORDER = "order"
    FORMAT = "format"
    INJECTION = "injection"


class CalibrationReportDefinitionV1(StrictModel):
    """Code-owned report math and missingness policy."""

    contract_version: Literal[CALIBRATION_REPORT_DEFINITION_V1] = (
        CALIBRATION_REPORT_DEFINITION_V1
    )
    definition_version: Literal["calibration-report-math-v1"] = (
        "calibration-report-math-v1"
    )
    classification_version: Literal["registered-vocabulary-classification-v1"] = (
        "registered-vocabulary-classification-v1"
    )
    confidence_calibration_version: Literal["selected-confidence-calibration-v1"] = (
        "selected-confidence-calibration-v1"
    )
    truth_resolution_version: Literal["objective-then-independent-human-v1"] = (
        "objective-then-independent-human-v1"
    )
    human_pairing_version: Literal["all-unordered-independent-pairs-v1"] = (
        "all-unordered-independent-pairs-v1"
    )
    slice_version: Literal["frozen-assignment-slices-v1"] = (
        "frozen-assignment-slices-v1"
    )
    time_bucket_version: Literal["utc-calendar-month-v1"] = (
        "utc-calendar-month-v1"
    )
    quantile_version: Literal["linear-interpolation-v1"] = (
        "linear-interpolation-v1"
    )
    reliability_bin_count: Literal[10] = 10
    selective_thresholds: tuple[float, ...] = (0.0, 0.5, 0.75, 0.9, 0.95)
    retrieval_ks: tuple[int, ...] = (1, 3, 5, 10)
    full_probability_vector_required: Literal[True] = True
    false_confidence_threshold_source: Literal["campaign_policy"] = (
        "campaign_policy"
    )
    minimum_slice_size_source: Literal["campaign_policy"] = "campaign_policy"
    activation_allowed: Literal[False] = False

    @field_validator("selective_thresholds")
    @classmethod
    def canonical_thresholds(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        checked = tuple(_probability(value) for value in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("selective thresholds must be unique and increasing")
        return checked

    @field_validator("retrieval_ks")
    @classmethod
    def canonical_ks(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if (
            not values
            or any(type(value) is not int or value <= 0 for value in values)
            or values != tuple(sorted(set(values)))
        ):
            raise ValueError("retrieval k values must be unique positive integers")
        return values

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


FIXED_CALIBRATION_REPORT_DEFINITION = CalibrationReportDefinitionV1()


class CalibrationComparisonIdentityV1(StrictModel):
    contract_version: Literal[CALIBRATION_COMPARISON_IDENTITY_V1] = (
        CALIBRATION_COMPARISON_IDENTITY_V1
    )
    metric_key: str
    metric_semantics_fingerprint: str
    evidence_scope_fingerprint: str
    pipeline_fingerprint: str
    gate_policy_fingerprint: str
    threshold_policy_fingerprint: str
    split_fingerprint: str
    submission_fingerprint: str
    served_runtime_identity_fingerprint: str
    measurement_provenance_fingerprint: str
    report_definition_fingerprint: str
    estimator_configuration_fingerprint: str
    constellation_fingerprint: str
    comparison_allowed: Literal[False] = False

    _metric = field_validator("metric_key")(_safe_metric)
    _digests = field_validator(
        "metric_semantics_fingerprint",
        "evidence_scope_fingerprint",
        "pipeline_fingerprint",
        "gate_policy_fingerprint",
        "threshold_policy_fingerprint",
        "split_fingerprint",
        "submission_fingerprint",
        "served_runtime_identity_fingerprint",
        "measurement_provenance_fingerprint",
        "report_definition_fingerprint",
        "estimator_configuration_fingerprint",
        "constellation_fingerprint",
    )(_digest)

    @property
    def comparison_family_fingerprint(self) -> str:
        return _canonical_payload_digest(
            {
                "metric_key": self.metric_key,
                "metric_semantics_fingerprint": self.metric_semantics_fingerprint,
                "evidence_scope_fingerprint": self.evidence_scope_fingerprint,
                "pipeline_fingerprint": self.pipeline_fingerprint,
                "gate_policy_fingerprint": self.gate_policy_fingerprint,
                "threshold_policy_fingerprint": self.threshold_policy_fingerprint,
                "split_fingerprint": self.split_fingerprint,
                "report_definition_fingerprint": self.report_definition_fingerprint,
            }
        )

    @property
    def observation_identity_fingerprint(self) -> str:
        return _canonical_digest(self)

    @property
    def observation_source_fingerprint(self) -> str:
        return _canonical_payload_digest(
            {
                "split_fingerprint": self.split_fingerprint,
                "submission_fingerprint": self.submission_fingerprint,
                "served_runtime_identity_fingerprint": (
                    self.served_runtime_identity_fingerprint
                ),
                "measurement_provenance_fingerprint": (
                    self.measurement_provenance_fingerprint
                ),
            }
        )


class CalibrationReportScopeV1(StrictModel):
    contract_version: Literal[CALIBRATION_REPORT_SCOPE_V1] = (
        CALIBRATION_REPORT_SCOPE_V1
    )
    scope_id: str
    metric_key: str
    dimension: CalibrationScopeDimension
    bucket_code: str
    case_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    minimum_required_count: int = Field(ge=1, le=_MAX_SAFE_INTEGER)
    state: CalibrationMeasurementState
    reason_code: str | None = None

    _id = field_validator("scope_id")(_digest)
    _metric = field_validator("metric_key")(_safe_metric)
    _bucket = field_validator("bucket_code")(_safe_code)
    _reason = field_validator("reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_scope_state(self) -> CalibrationReportScopeV1:
        ready = self.case_count >= self.minimum_required_count
        if self.state is CalibrationMeasurementState.KNOWN:
            if not ready or self.reason_code is not None:
                raise ValueError("known scope requires enough cases and no reason")
        elif self.state is CalibrationMeasurementState.INSUFFICIENT_DATA:
            if ready or self.reason_code is None:
                raise ValueError("insufficient scope requires a shortfall reason")
        else:
            raise ValueError("scope state must be known or insufficient_data")
        if self.dimension is CalibrationScopeDimension.OVERALL and (
            self.bucket_code != "overall"
        ):
            raise ValueError("overall scope requires the overall bucket")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CalibrationMeasurementSpecV1(StrictModel):
    contract_version: Literal[CALIBRATION_MEASUREMENT_SPEC_V1] = (
        CALIBRATION_MEASUREMENT_SPEC_V1
    )
    measurement_key: str
    family: CalibrationMeasurementFamily
    shape: CalibrationMeasurementShape
    unit_code: str

    _key = field_validator("measurement_key", "unit_code")(_safe_code)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def _spec(
    key: str,
    family: CalibrationMeasurementFamily,
    shape: CalibrationMeasurementShape,
    unit: str,
) -> CalibrationMeasurementSpecV1:
    return CalibrationMeasurementSpecV1(
        measurement_key=key,
        family=family,
        shape=shape,
        unit_code=unit,
    )


CALIBRATION_MEASUREMENT_SPECS: tuple[CalibrationMeasurementSpecV1, ...] = tuple(
    sorted(
        (
            _spec("coverage.holdout_cases", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.private_holdout_cases", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.truth_known", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.objective_truth", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.resolved_human_truth", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.candidate_known", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.baseline_known", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.human_adjudicated", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "cases"),
            _spec("coverage.privacy_findings", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "findings"),
            _spec("coverage.unscanned_artifacts", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "artifacts"),
            _spec("coverage.access_gaps", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "gaps"),
            _spec("coverage.unauthorized_access", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "events"),
            _spec("coverage.fallback_attempts", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "attempts"),
            _spec("coverage.served_identity_unavailable", CalibrationMeasurementFamily.COVERAGE, CalibrationMeasurementShape.COUNT, "attempts"),
            _spec("classification.accuracy", CalibrationMeasurementFamily.CLASSIFICATION, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("classification.macro_precision", CalibrationMeasurementFamily.CLASSIFICATION, CalibrationMeasurementShape.SCALAR, "ratio"),
            _spec("classification.macro_recall", CalibrationMeasurementFamily.CLASSIFICATION, CalibrationMeasurementShape.SCALAR, "ratio"),
            _spec("classification.macro_f1", CalibrationMeasurementFamily.CLASSIFICATION, CalibrationMeasurementShape.SCALAR, "ratio"),
            _spec("calibration.selected_confidence_ece", CalibrationMeasurementFamily.CALIBRATION, CalibrationMeasurementShape.SCALAR, "ratio"),
            _spec("calibration.false_confident_error_rate", CalibrationMeasurementFamily.CALIBRATION, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("calibration.brier_score", CalibrationMeasurementFamily.CALIBRATION, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("calibration.log_loss", CalibrationMeasurementFamily.CALIBRATION, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("calibration.slope", CalibrationMeasurementFamily.CALIBRATION, CalibrationMeasurementShape.SCALAR, "slope"),
            _spec("agreement.human_human_observed", CalibrationMeasurementFamily.AGREEMENT, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("agreement.human_human_kappa", CalibrationMeasurementFamily.AGREEMENT, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("agreement.model_human_observed", CalibrationMeasurementFamily.AGREEMENT, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("agreement.model_human_kappa", CalibrationMeasurementFamily.AGREEMENT, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("stability.repeat", CalibrationMeasurementFamily.STABILITY, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("stability.order", CalibrationMeasurementFamily.STABILITY, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("stability.format", CalibrationMeasurementFamily.STABILITY, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("stability.injection", CalibrationMeasurementFamily.STABILITY, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.attempt_count", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.COUNT, "attempts"),
            _spec("resource.latency_p50_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.latency_p95_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.queue_p50_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.queue_p95_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.peak_ram_bytes", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "bytes"),
            _spec("resource.peak_vram_bytes", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "bytes"),
            _spec("resource.energy_total_millijoules", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "millijoules"),
            _spec("resource.cost_total_microusd", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "microusd"),
            _spec("resource.token_total", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "tokens"),
            _spec("resource.oom_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.error_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.refusal_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.timeout_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.cancelled_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.worker_lost_rate", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("resource.cold_latency_p95_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.warm_latency_p95_ms", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "milliseconds"),
            _spec("resource.throughput_per_second", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "items_per_second"),
            _spec("resource.disk_bytes", CalibrationMeasurementFamily.RESOURCE, CalibrationMeasurementShape.SCALAR, "bytes"),
            _spec("retrieval.mean_reciprocal_rank", CalibrationMeasurementFamily.RETRIEVAL, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("retrieval.link_precision", CalibrationMeasurementFamily.RETRIEVAL, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("retrieval.recall_at_k", CalibrationMeasurementFamily.RETRIEVAL, CalibrationMeasurementShape.SCALAR, "ratio"),
            _spec("retrieval.ndcg_at_k", CalibrationMeasurementFamily.RETRIEVAL, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("cascade.stop_rate", CalibrationMeasurementFamily.CASCADE, CalibrationMeasurementShape.RATE, "ratio"),
            _spec("cascade.incremental_value", CalibrationMeasurementFamily.CASCADE, CalibrationMeasurementShape.SCALAR, "score"),
            _spec("numeric.mean_absolute_error", CalibrationMeasurementFamily.NUMERIC, CalibrationMeasurementShape.SCALAR, "error"),
            _spec("numeric.root_mean_squared_error", CalibrationMeasurementFamily.NUMERIC, CalibrationMeasurementShape.SCALAR, "error"),
            _spec("numeric.within_tolerance_rate", CalibrationMeasurementFamily.NUMERIC, CalibrationMeasurementShape.RATE, "ratio"),
        ),
        key=lambda item: item.measurement_key,
    )
)

CALIBRATION_MEASUREMENT_SPEC_BY_KEY = {
    item.measurement_key: item for item in CALIBRATION_MEASUREMENT_SPECS
}


class CalibrationMeasurementV1(StrictModel):
    contract_version: Literal[CALIBRATION_MEASUREMENT_V1] = (
        CALIBRATION_MEASUREMENT_V1
    )
    scope_id: str
    measurement_key: str
    family: CalibrationMeasurementFamily
    shape: CalibrationMeasurementShape
    unit_code: str
    state: CalibrationMeasurementState
    scalar_value: float | None = Field(default=None, allow_inf_nan=False)
    integer_value: int | None = Field(default=None, ge=0, le=_MAX_SAFE_INTEGER)
    numerator: int | None = Field(default=None, ge=0, le=_MAX_SAFE_INTEGER)
    denominator: int | None = Field(default=None, ge=0, le=_MAX_SAFE_INTEGER)
    sample_count: int = Field(default=0, ge=0, le=_MAX_SAFE_INTEGER)
    reason_code: str | None = None

    _scope = field_validator("scope_id")(_digest)
    _keys = field_validator("measurement_key", "unit_code")(_safe_code)
    _reason = field_validator("reason_code")(_optional_code)
    _scalar = field_validator("scalar_value")(
        lambda value: None if value is None else _finite(value)
    )

    @model_validator(mode="after")
    def validate_measurement_shape(self) -> CalibrationMeasurementV1:
        spec = CALIBRATION_MEASUREMENT_SPEC_BY_KEY.get(self.measurement_key)
        if spec is None or (
            self.family is not spec.family
            or self.shape is not spec.shape
            or self.unit_code != spec.unit_code
        ):
            raise ValueError("measurement does not match the fixed specification")

        values = (self.scalar_value, self.integer_value, self.numerator, self.denominator)
        if self.state is CalibrationMeasurementState.KNOWN:
            if self.reason_code is not None:
                raise ValueError("known measurements cannot carry a reason")
            if self.shape is CalibrationMeasurementShape.COUNT:
                if self.integer_value is None or any(
                    value is not None
                    for value in (self.scalar_value, self.numerator, self.denominator)
                ):
                    raise ValueError("known count requires only an integer value")
            elif self.shape is CalibrationMeasurementShape.SCALAR:
                if self.scalar_value is None or any(
                    value is not None
                    for value in (self.integer_value, self.numerator, self.denominator)
                ):
                    raise ValueError("known scalar requires only a scalar value")
                if self.sample_count == 0:
                    raise ValueError("known scalar requires a positive sample count")
            else:
                if (
                    self.scalar_value is None
                    or self.numerator is None
                    or self.denominator is None
                    or self.denominator == 0
                    or self.numerator > self.denominator
                    or self.integer_value is not None
                    or not math.isclose(
                        self.scalar_value,
                        self.numerator / self.denominator,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                ):
                    raise ValueError("known rate requires exact consistent counts")
        else:
            if self.reason_code is None:
                raise ValueError("non-known measurements require a safe reason")
            if self.scalar_value is not None or self.integer_value is not None:
                raise ValueError("non-known measurements cannot claim a value")
            if (
                self.shape is not CalibrationMeasurementShape.RATE
                and self.family is not CalibrationMeasurementFamily.RESOURCE
                and (self.numerator is not None or self.denominator is not None)
            ):
                raise ValueError(
                    "only unavailable rates or resource measures retain coverage counts"
                )
            if (self.numerator is None) != (self.denominator is None):
                raise ValueError("rate counts must be present together")
            if (
                self.numerator is not None
                and self.denominator is not None
                and self.numerator > self.denominator
            ):
                raise ValueError("rate counts are inconsistent")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class CalibrationConfusionCellV1(StrictModel):
    contract_version: Literal[CALIBRATION_CONFUSION_CELL_V1] = (
        CALIBRATION_CONFUSION_CELL_V1
    )
    scope_id: str
    truth_label: str
    predicted_label: str
    count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)

    _scope = field_validator("scope_id")(_digest)
    _labels = field_validator("truth_label", "predicted_label")(_safe_code)


class CalibrationClassReceiptV1(StrictModel):
    contract_version: Literal[CALIBRATION_CLASS_RECEIPT_V1] = (
        CALIBRATION_CLASS_RECEIPT_V1
    )
    scope_id: str
    label_code: str
    support: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    predicted_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    true_positive: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    false_positive: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    false_negative: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    precision: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    recall: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    f1: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    _scope = field_validator("scope_id")(_digest)
    _label = field_validator("label_code")(_safe_code)


class CalibrationReliabilityBinV1(StrictModel):
    contract_version: Literal[CALIBRATION_RELIABILITY_BIN_V1] = (
        CALIBRATION_RELIABILITY_BIN_V1
    )
    scope_id: str
    bin_index: int = Field(ge=0, le=99)
    lower_bound: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    upper_bound: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    mean_confidence: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    absolute_gap: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)

    _scope = field_validator("scope_id")(_digest)

    @model_validator(mode="after")
    def validate_bin(self) -> CalibrationReliabilityBinV1:
        if self.upper_bound <= self.lower_bound:
            raise ValueError("reliability bin bounds must increase")
        summaries = (self.mean_confidence, self.accuracy, self.absolute_gap)
        if self.count == 0:
            if any(item is not None for item in summaries):
                raise ValueError("empty reliability bin cannot claim summaries")
        elif any(item is None for item in summaries):
            raise ValueError("non-empty reliability bin requires every summary")
        elif not math.isclose(
            self.absolute_gap or 0.0,
            abs((self.mean_confidence or 0.0) - (self.accuracy or 0.0)),
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("reliability gap must match confidence and accuracy")
        return self


class CalibrationSelectivePointV1(StrictModel):
    contract_version: Literal[CALIBRATION_SELECTIVE_POINT_V1] = (
        CALIBRATION_SELECTIVE_POINT_V1
    )
    scope_id: str
    threshold: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    state: CalibrationMeasurementState
    coverage_numerator: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    coverage_denominator: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    risk_numerator: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    risk_denominator: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    reason_code: str | None = None

    _scope = field_validator("scope_id")(_digest)
    _reason = field_validator("reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_counts(self) -> CalibrationSelectivePointV1:
        if (
            self.coverage_numerator > self.coverage_denominator
            or self.risk_numerator > self.risk_denominator
            or self.risk_denominator != self.coverage_numerator
        ):
            raise ValueError("selective-risk counts are inconsistent")
        ready = self.coverage_denominator > 0 and self.risk_denominator > 0
        if self.state is CalibrationMeasurementState.KNOWN:
            if not ready or self.reason_code is not None:
                raise ValueError("known selective point requires nonzero denominators")
        elif self.state is CalibrationMeasurementState.INSUFFICIENT_DATA:
            if self.reason_code is None:
                raise ValueError("insufficient selective point requires a reason")
        else:
            raise ValueError("selective point state must be known or insufficient")
        return self


class CalibrationAgreementReceiptV1(StrictModel):
    contract_version: Literal[CALIBRATION_AGREEMENT_RECEIPT_V1] = (
        CALIBRATION_AGREEMENT_RECEIPT_V1
    )
    metric_key: str
    kind: CalibrationAgreementKind
    state: CalibrationMeasurementState
    case_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    pair_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    match_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    observed_agreement: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    cohen_kappa: float | None = Field(default=None, ge=-1.0, le=1.0, allow_inf_nan=False)
    reason_code: str | None = None

    _metric = field_validator("metric_key")(_safe_metric)
    _reason = field_validator("reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_agreement(self) -> CalibrationAgreementReceiptV1:
        if self.match_count > self.pair_count:
            raise ValueError("agreement matches cannot exceed pairs")
        if self.state is CalibrationMeasurementState.KNOWN:
            if (
                self.pair_count == 0
                or self.observed_agreement is None
                or self.reason_code is not None
                or not math.isclose(
                    self.observed_agreement,
                    self.match_count / self.pair_count,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("known agreement requires consistent pairs")
        elif (
            self.observed_agreement is not None
            or self.cohen_kappa is not None
            or self.reason_code is None
        ):
            raise ValueError("unavailable agreement requires only counts and reason")
        return self


class CalibrationStabilityReceiptV1(StrictModel):
    contract_version: Literal[CALIBRATION_STABILITY_RECEIPT_V1] = (
        CALIBRATION_STABILITY_RECEIPT_V1
    )
    metric_key: str
    condition: CalibrationStabilityCondition
    state: CalibrationMeasurementState
    case_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    pair_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    match_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    stability: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    reason_code: str | None = None

    _metric = field_validator("metric_key")(_safe_metric)
    _reason = field_validator("reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_stability(self) -> CalibrationStabilityReceiptV1:
        if self.match_count > self.pair_count:
            raise ValueError("stability matches cannot exceed pairs")
        if self.state is CalibrationMeasurementState.KNOWN:
            if (
                self.pair_count == 0
                or self.stability is None
                or self.reason_code is not None
                or not math.isclose(
                    self.stability,
                    self.match_count / self.pair_count,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("known stability requires consistent pairs")
        elif self.stability is not None or self.reason_code is None:
            raise ValueError("unavailable stability requires only counts and reason")
        return self


class CalibrationResourceReceiptV1(StrictModel):
    contract_version: Literal[CALIBRATION_RESOURCE_RECEIPT_V1] = (
        CALIBRATION_RESOURCE_RECEIPT_V1
    )
    metric_key: str
    attempt_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    observed_usage_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    observed_resource_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    observed_cost_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    terminal_state_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    measurement_keys: tuple[str, ...]

    _metric = field_validator("metric_key")(_safe_metric)

    @field_validator("measurement_keys")
    @classmethod
    def canonical_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_safe_code(item) for item in values)
        if checked != tuple(sorted(set(checked))):
            raise ValueError("resource measurement keys must be unique and sorted")
        return checked

    @model_validator(mode="after")
    def validate_counts(self) -> CalibrationResourceReceiptV1:
        if any(
            value > self.attempt_count
            for value in (
                self.observed_usage_count,
                self.observed_resource_count,
                self.observed_cost_count,
                self.terminal_state_count,
            )
        ):
            raise ValueError("resource receipt counts exceed attempts")
        return self


class CalibrationMissingnessReceiptV1(StrictModel):
    contract_version: Literal[CALIBRATION_MISSINGNESS_RECEIPT_V1] = (
        CALIBRATION_MISSINGNESS_RECEIPT_V1
    )
    metric_key: str
    measurement_key: str
    state: Literal[
        CalibrationMeasurementState.INSUFFICIENT_DATA,
        CalibrationMeasurementState.UNSUPPORTED,
        CalibrationMeasurementState.NOT_APPLICABLE,
        CalibrationMeasurementState.INCOMPATIBLE,
    ]
    affected_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    reason_code: str

    _metric = field_validator("metric_key")(_safe_metric)
    _keys = field_validator("measurement_key", "reason_code")(_safe_code)


class CalibrationMetricReportV1(StrictModel):
    contract_version: Literal[CALIBRATION_METRIC_REPORT_V1] = (
        CALIBRATION_METRIC_REPORT_V1
    )
    metric_key: str
    value_kind: Literal["continuous", "fraction", "binary", "categorical"]
    label_vocabulary: tuple[str, ...]
    comparison_identity: CalibrationComparisonIdentityV1
    state: CalibrationReportState
    scopes: tuple[CalibrationReportScopeV1, ...]
    measurements: tuple[CalibrationMeasurementV1, ...]
    confusion_cells: tuple[CalibrationConfusionCellV1, ...] = ()
    class_receipts: tuple[CalibrationClassReceiptV1, ...] = ()
    reliability_bins: tuple[CalibrationReliabilityBinV1, ...] = ()
    selective_points: tuple[CalibrationSelectivePointV1, ...] = ()
    agreement_receipts: tuple[CalibrationAgreementReceiptV1, ...]
    stability_receipts: tuple[CalibrationStabilityReceiptV1, ...]
    resource_receipt: CalibrationResourceReceiptV1
    missingness: tuple[CalibrationMissingnessReceiptV1, ...]
    comparison_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _metric = field_validator("metric_key")(_safe_metric)

    @field_validator("label_vocabulary")
    @classmethod
    def canonical_vocabulary(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_safe_code(item) for item in values)
        if checked and (checked != tuple(sorted(set(checked))) or len(checked) < 2):
            raise ValueError("label vocabulary must be empty or canonical with two labels")
        return checked

    @model_validator(mode="after")
    def validate_metric_report(self) -> CalibrationMetricReportV1:
        if self.comparison_identity.metric_key != self.metric_key:
            raise ValueError("comparison identity must bind the metric")
        if self.value_kind in {"binary", "categorical"}:
            if len(self.label_vocabulary) < 2:
                raise ValueError("classification metric requires registered labels")
        elif self.label_vocabulary:
            raise ValueError("numeric metric cannot carry classification labels")

        scope_keys = tuple(
            (item.dimension.value, item.bucket_code, item.scope_id)
            for item in self.scopes
        )
        if scope_keys != tuple(sorted(scope_keys)) or len(
            {item[2] for item in scope_keys}
        ) != len(scope_keys):
            raise ValueError("report scopes must be unique and canonically ordered")
        overall = tuple(
            item
            for item in self.scopes
            if item.dimension is CalibrationScopeDimension.OVERALL
        )
        if len(overall) != 1:
            raise ValueError("metric report requires exactly one overall scope")
        scope_ids = {item.scope_id for item in self.scopes}

        measurement_keys = tuple(
            (item.scope_id, item.measurement_key) for item in self.measurements
        )
        if measurement_keys != tuple(sorted(measurement_keys)) or len(
            set(measurement_keys)
        ) != len(measurement_keys):
            raise ValueError("measurements must be unique and canonically ordered")
        if any(item.scope_id not in scope_ids for item in self.measurements):
            raise ValueError("measurement references an absent scope")
        insufficient_scope_ids = {
            item.scope_id
            for item in self.scopes
            if item.state is CalibrationMeasurementState.INSUFFICIENT_DATA
        }
        if any(
            item.scope_id in insufficient_scope_ids
            and item.state is CalibrationMeasurementState.KNOWN
            for item in self.measurements
        ):
            raise ValueError("insufficient scopes cannot claim known measurements")
        overall_measurements = {
            item.measurement_key
            for item in self.measurements
            if item.scope_id == overall[0].scope_id
        }
        if overall_measurements != set(CALIBRATION_MEASUREMENT_SPEC_BY_KEY):
            raise ValueError("overall scope must explicitly represent every measurement")

        for rows, key in (
            (self.confusion_cells, lambda item: (item.scope_id, item.truth_label, item.predicted_label)),
            (self.class_receipts, lambda item: (item.scope_id, item.label_code)),
            (self.reliability_bins, lambda item: (item.scope_id, item.bin_index)),
            (self.selective_points, lambda item: (item.scope_id, item.threshold)),
        ):
            keys = tuple(key(item) for item in rows)
            if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
                raise ValueError("detail receipts must be unique and canonically ordered")
            if any(item.scope_id not in scope_ids for item in rows):
                raise ValueError("detail receipt references an absent scope")
            if any(
                next(scope for scope in self.scopes if scope.scope_id == item.scope_id).state
                is not CalibrationMeasurementState.KNOWN
                for item in rows
            ):
                raise ValueError("insufficient scopes cannot expose numeric detail")

        agreement_keys = tuple(item.kind.value for item in self.agreement_receipts)
        if agreement_keys != tuple(sorted(agreement_keys)) or set(agreement_keys) != {
            item.value for item in CalibrationAgreementKind
        }:
            raise ValueError("agreement receipts must cover both registered kinds")
        stability_keys = tuple(item.condition.value for item in self.stability_receipts)
        if stability_keys != tuple(sorted(stability_keys)) or set(stability_keys) != {
            item.value for item in CalibrationStabilityCondition
        }:
            raise ValueError("stability receipts must cover every condition")
        if (
            any(item.metric_key != self.metric_key for item in self.agreement_receipts)
            or any(item.metric_key != self.metric_key for item in self.stability_receipts)
            or self.resource_receipt.metric_key != self.metric_key
            or any(item.metric_key != self.metric_key for item in self.missingness)
        ):
            raise ValueError("nested receipts must bind the metric")

        missing_keys = tuple(
            (item.measurement_key, item.state.value, item.reason_code)
            for item in self.missingness
        )
        if missing_keys != tuple(sorted(missing_keys)) or len(
            {item[0] for item in missing_keys}
        ) != len(missing_keys):
            raise ValueError("missingness must be unique and canonically ordered")
        expected_missing = {
            item.measurement_key
            for item in self.measurements
            if item.scope_id == overall[0].scope_id
            and item.state is not CalibrationMeasurementState.KNOWN
        }
        if expected_missing != {item.measurement_key for item in self.missingness}:
            raise ValueError("overall non-known measurements require missingness receipts")

        known_count = sum(
            item.state is CalibrationMeasurementState.KNOWN
            for item in self.measurements
            if item.scope_id == overall[0].scope_id
        )
        missing_count = len(CALIBRATION_MEASUREMENT_SPECS) - known_count
        expected_state = (
            CalibrationReportState.INSUFFICIENT_DATA
            if known_count == 0
            else CalibrationReportState.READY
            if missing_count == 0
            else CalibrationReportState.PARTIAL
        )
        if self.state is not expected_state:
            raise ValueError("metric report state must be derived from measurements")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class UntrustedCalibrationReportV1(StrictModel):
    """Caller-derived report foundation; never a repository-derived receipt."""

    contract_version: Literal[UNTRUSTED_CALIBRATION_REPORT_V1] = (
        UNTRUSTED_CALIBRATION_REPORT_V1
    )
    report_id: str
    campaign_id: str
    campaign_fingerprint: str
    submission_id: str
    submission_fingerprint: str
    stored_plan_fingerprint: str
    policy_fingerprint: str
    assignment_manifest_fingerprint: str
    split_fingerprint: str
    preregistration_fingerprint: str
    preregistration_v2_fingerprint: str
    constellation_fingerprint: str
    source_bundle_fingerprint: str
    definition: CalibrationReportDefinitionV1
    state: CalibrationReportState
    metric_reports: tuple[CalibrationMetricReportV1, ...]
    source_observed_at: datetime
    derived_at: None = None
    repository_owned: Literal[False] = False
    persistence_state: Literal["untrusted_projection"] = "untrusted_projection"
    comparison_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "report_id",
        "campaign_id",
        "campaign_fingerprint",
        "submission_id",
        "submission_fingerprint",
        "stored_plan_fingerprint",
        "policy_fingerprint",
        "assignment_manifest_fingerprint",
        "split_fingerprint",
        "preregistration_fingerprint",
        "preregistration_v2_fingerprint",
        "constellation_fingerprint",
        "source_bundle_fingerprint",
    )(_digest)
    _observed = field_validator("source_observed_at")(_utc)

    @model_validator(mode="after")
    def validate_report(self) -> UntrustedCalibrationReportV1:
        keys = tuple(item.metric_key for item in self.metric_reports)
        if not keys or keys != tuple(sorted(set(keys))):
            raise ValueError("metric reports must be non-empty and canonically ordered")
        if self.definition != FIXED_CALIBRATION_REPORT_DEFINITION:
            raise ValueError("report must use the fixed code-owned definition")
        states = {item.state for item in self.metric_reports}
        expected = (
            CalibrationReportState.INSUFFICIENT_DATA
            if states == {CalibrationReportState.INSUFFICIENT_DATA}
            else CalibrationReportState.READY
            if states == {CalibrationReportState.READY}
            else CalibrationReportState.PARTIAL
        )
        if self.state is not expected:
            raise ValueError("report state must be derived from metric reports")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ModelLabCalibrationMetricSummaryV1(StrictModel):
    metric_key: str
    state: CalibrationReportState
    comparison_family_fingerprint: str
    holdout_case_count: int = Field(ge=0, le=_MAX_SAFE_INTEGER)
    known_measurement_count: int = Field(ge=0, le=len(CALIBRATION_MEASUREMENT_SPECS))
    missing_measurement_count: int = Field(ge=0, le=len(CALIBRATION_MEASUREMENT_SPECS))
    comparison_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _metric = field_validator("metric_key")(_safe_metric)
    _comparison = field_validator("comparison_family_fingerprint")(_digest)

    @model_validator(mode="after")
    def validate_counts(self) -> ModelLabCalibrationMetricSummaryV1:
        if self.known_measurement_count + self.missing_measurement_count != len(
            CALIBRATION_MEASUREMENT_SPECS
        ):
            raise ValueError("metric summary measurement counts are incomplete")
        return self


class ModelLabCalibrationReportSummaryV1(StrictModel):
    contract_version: Literal[MODEL_LAB_CALIBRATION_REPORT_SUMMARY_V1] = (
        MODEL_LAB_CALIBRATION_REPORT_SUMMARY_V1
    )
    report_id: str
    report_fingerprint: str
    stored_plan_fingerprint: str
    definition_fingerprint: str
    state: CalibrationReportState
    source_observed_at: datetime
    derived_at: None = None
    metrics: tuple[ModelLabCalibrationMetricSummaryV1, ...]
    repository_sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    product_activation_allowed: Literal[False] = False

    _ids = field_validator(
        "report_id",
        "report_fingerprint",
        "stored_plan_fingerprint",
        "definition_fingerprint",
    )(_digest)
    _observed = field_validator("source_observed_at")(_utc)

    @model_validator(mode="after")
    def canonical_metrics(self) -> ModelLabCalibrationReportSummaryV1:
        keys = tuple(item.metric_key for item in self.metrics)
        if keys != tuple(sorted(set(keys))) or not keys:
            raise ValueError("summary metrics must be unique and sorted")
        return self


class ModelLabCalibrationInventoryV1(StrictModel):
    contract_version: Literal[MODEL_LAB_CALIBRATION_INVENTORY_V1] = (
        MODEL_LAB_CALIBRATION_INVENTORY_V1
    )
    scope: Literal["local_untrusted_calibration_reports"] = (
        "local_untrusted_calibration_reports"
    )
    raw_private_evidence_returned: Literal[False] = False
    sensitive_local_aggregate_returned: Literal[True] = True
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    product_activation_allowed: Literal[False] = False
    reports: tuple[ModelLabCalibrationReportSummaryV1, ...]

    @model_validator(mode="after")
    def canonical_reports(self) -> ModelLabCalibrationInventoryV1:
        keys = tuple((item.source_observed_at, item.report_id) for item in self.reports)
        if keys != tuple(sorted(keys)) or len({item[1] for item in keys}) != len(keys):
            raise ValueError("inventory reports must be unique and chronological")
        return self


__all__ = [
    "CALIBRATION_MEASUREMENT_SPECS",
    "CALIBRATION_MEASUREMENT_SPEC_BY_KEY",
    "FIXED_CALIBRATION_REPORT_DEFINITION",
    "CalibrationAgreementKind",
    "CalibrationAgreementReceiptV1",
    "CalibrationClassReceiptV1",
    "CalibrationComparisonIdentityV1",
    "CalibrationConfusionCellV1",
    "CalibrationMeasurementFamily",
    "CalibrationMeasurementShape",
    "CalibrationMeasurementSpecV1",
    "CalibrationMeasurementState",
    "CalibrationMeasurementV1",
    "CalibrationMetricReportV1",
    "CalibrationMissingnessReceiptV1",
    "CalibrationReliabilityBinV1",
    "CalibrationReportDefinitionV1",
    "CalibrationReportScopeV1",
    "CalibrationReportState",
    "CalibrationResourceReceiptV1",
    "CalibrationScopeDimension",
    "CalibrationSelectivePointV1",
    "CalibrationStabilityCondition",
    "CalibrationStabilityReceiptV1",
    "CalibrationTruthSource",
    "ModelLabCalibrationInventoryV1",
    "ModelLabCalibrationMetricSummaryV1",
    "ModelLabCalibrationReportSummaryV1",
    "UntrustedCalibrationReportV1",
]
