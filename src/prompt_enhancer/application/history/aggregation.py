"""Pure, synthetic-only temporal raw-aggregation drafts.

The reducer in this module is deliberately below every product trust boundary.
It operates on already-constructed synthetic comparison-stratum drafts or on
structurally revalidated repository receipt graphs and returns a content-free
descriptive draft.  It neither enumerates repository history nor issues
repository, source, comparison, snapshot, recommendation, outcome, or
activation authority.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .comparison_strata import (
    ComparisonDimensionStateV1,
    ComparisonMatchReadinessV1,
    ComparisonTaskMixBucketV1,
    ComparisonTaskTypeStateV1,
    ComparisonTaskTypeV1,
    SealedComparisonStratumDraftV1,
)
from .comparison_strata_persistence import (
    RepositoryPreparedComparisonStratumV1,
    RepositorySealedComparisonStratumV1,
)
from .contracts import (
    CompatibilityDimension,
    CountExposureObservationValue,
    DistributionSampleObservationValue,
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    FractionObservationValue,
    MAX_COUNT,
    MAX_LAST_N,
    MetricComparisonIdentity,
    PersistenceRevalidatedModel,
    SampledProportionObservationValue,
    TemporalMetricObservationV2,
    TemporalSelectionState,
    TemporalSourceState,
    TemporalValueKind,
    TemporalValueState,
    TemporalWindowKind,
    TemporalWindowSpec,
)
from .persistence import RepositoryPreparedTemporalScopeV1


SYNTHETIC_RAW_AGGREGATION_VERSION = "synthetic-raw-aggregation-draft-v1"
REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION = (
    "repository-backed-synthetic-raw-aggregation-draft-v2"
)
RAW_AGGREGATION_POLICY_VERSION = "synthetic-raw-aggregation-policy-v1"
LAST_N_ORDER_VERSION = "session-revision-total-order-v1"
QUANTILE_METHOD_VERSION = (
    "hyndman-fan-type-7-p25-p50-p75-binary64-v1"
)
INTERVAL_METHOD_VERSION = "wilson-score-two-sided-95-v1"
WINDOW_TIME_BASIS = "session-revision-effective-at-v1"
MAX_SUPPLIED_STRATA = MAX_LAST_N
WILSON_CONFIDENCE_LEVEL = 0.95
WILSON_Z = 1.959963984540054

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


def _safe_code(value: str) -> str:
    if _SAFE_CODE.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a lowercase path-free content code")
    return value


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be canonical UTC")
    return value.astimezone(UTC)


def _finite(value: Any, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("aggregate value must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("aggregate value must be finite")
    if nonnegative and result < 0:
        raise ValueError("aggregate value must be non-negative")
    if result == 0:
        result = 0.0
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, dict):
        return {key: _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(nested) for nested in value]
    return value


def _canonical_digest(value: Any) -> str:
    payload = _jsonable(value)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _derived_id(role: str, payload: dict[str, Any]) -> str:
    return _canonical_digest({"role": role, "payload": payload})


def _safe_int_sum(values: list[int]) -> int:
    result = sum(values)
    if result > MAX_COUNT:
        raise ValueError("aggregate count exceeds the safe integer boundary")
    return result


def _safe_float_sum(values: list[float], *, nonnegative: bool = False) -> float:
    try:
        result = math.fsum(values)
    except OverflowError:
        raise ValueError("aggregate floating-point sum exceeds the finite range") from None
    return _finite(result, nonnegative=nonnegative)


class RawAggregationPopulationStateV1(StrEnum):
    SUPPLIED_SET_COMPLETENESS_UNKNOWN = "supplied_set_completeness_unknown"


class RawMatchReadinessV1(StrEnum):
    INSUFFICIENT_REQUIRED_STRATA = "insufficient_required_strata"


class RawTransitionKindV1(StrEnum):
    IDENTITY_CHANGE = "identity_change"
    IDENTITY_UNAVAILABLE_GAP = "identity_unavailable_gap"


class RawWindowCoverageStateV1(StrEnum):
    SUPPLIED_WINDOW = "supplied_window"
    LEFT_CENSORED_BY_PROSPECTIVE_FLOOR = "left_censored_by_prospective_floor"
    LAST_N_SHORTFALL = "last_n_shortfall"
    LEFT_CENSORED_AND_LAST_N_SHORTFALL = (
        "left_censored_and_last_n_shortfall"
    )
    NO_INCLUDED_REVISIONS = "no_included_revisions"


class RawStratumDispositionV1(StrEnum):
    INCLUDED = "included"
    LATE_SEAL = "late_seal"
    OUTSIDE_WINDOW = "outside_window"


class RawSuppliedStratumManifestEntryV1(PersistenceRevalidatedModel):
    fingerprint: str
    disposition: RawStratumDispositionV1

    _fingerprint = field_validator("fingerprint")(_digest)


class RepositoryBackedStratumManifestEntryV2(PersistenceRevalidatedModel):
    """Content-free commitment to one supplied repository receipt graph."""

    supplied_ordinal: int = Field(strict=True, ge=0, le=MAX_COUNT)
    prepared_stratum_id: str
    prepared_stratum_fingerprint: str
    sealed_stratum_id: str
    sealed_stratum_fingerprint: str
    analysis_run_id: str
    analysis_run_authority_sha256: str
    sealed_batch_id: str
    sealed_batch_sha256: str
    revision_id: str
    revision_fingerprint: str
    session_id: str
    revision_ordinal: int = Field(strict=True, ge=1, le=MAX_COUNT)
    effective_at: datetime
    sealed_at: datetime
    disposition: RawStratumDispositionV1

    _digests = field_validator(
        "prepared_stratum_id",
        "prepared_stratum_fingerprint",
        "sealed_stratum_id",
        "sealed_stratum_fingerprint",
        "analysis_run_id",
        "analysis_run_authority_sha256",
        "sealed_batch_id",
        "sealed_batch_sha256",
        "revision_id",
        "revision_fingerprint",
        "session_id",
    )(_digest)
    _times = field_validator("effective_at", "sealed_at")(_utc)

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class RawAggregationPolicyIdentityV1(PersistenceRevalidatedModel):
    contract_version: Literal[RAW_AGGREGATION_POLICY_VERSION] = (
        RAW_AGGREGATION_POLICY_VERSION
    )
    window_time_basis: Literal[WINDOW_TIME_BASIS] = WINDOW_TIME_BASIS
    window_boundary_semantics: Literal[
        "half_open_start_inclusive_end_exclusive"
    ] = "half_open_start_inclusive_end_exclusive"
    last_n_unit: Literal["session_revision"] = "session_revision"
    last_n_order_version: Literal[LAST_N_ORDER_VERSION] = LAST_N_ORDER_VERSION
    quantile_method_version: Literal[QUANTILE_METHOD_VERSION] = (
        QUANTILE_METHOD_VERSION
    )
    interval_method_version: Literal[INTERVAL_METHOD_VERSION] = (
        INTERVAL_METHOD_VERSION
    )
    interval_confidence_level: Literal[0.95] = WILSON_CONFIDENCE_LEVEL
    compatibility_segmentation: Literal["contiguous_full_identity_runs"] = (
        "contiguous_full_identity_runs"
    )
    task_bucket_pooling_allowed: Literal[False] = False
    missing_value_imputation_allowed: Literal[False] = False
    code_owned: Literal[True] = True
    caller_override_allowed: Literal[False] = False
    quantile_probabilities: tuple[float, float, float] = (0.25, 0.5, 0.75)
    interval_two_sided: Literal[True] = True
    interval_z: float = WILSON_Z
    finite_binary64_required: Literal[True] = True
    float_summation_method: Literal["math.fsum-v1"] = "math.fsum-v1"
    safe_integer_max: int = Field(default=MAX_COUNT, strict=True)
    noncontiguous_identity_rejoin_allowed: Literal[False] = False
    population_completeness_inferred: Literal[False] = False
    task_mix_policy_version: Literal["visible-untrusted-task-buckets-v1"] = (
        "visible-untrusted-task-buckets-v1"
    )

    @field_validator("quantile_probabilities", mode="before")
    @classmethod
    def exact_quantile_probabilities(cls, value: Any) -> tuple[float, ...]:
        if value != (0.25, 0.5, 0.75):
            raise ValueError("quantile probabilities are code-owned")
        return value

    @field_validator("interval_z", mode="before")
    @classmethod
    def exact_interval_z(cls, value: Any) -> float:
        result = _finite(value, nonnegative=True)
        if result != WILSON_Z:
            raise ValueError("Wilson z value is code-owned")
        return result

    @field_validator("safe_integer_max")
    @classmethod
    def exact_safe_integer_max(cls, value: int) -> int:
        if value != MAX_COUNT:
            raise ValueError("safe integer maximum is code-owned")
        return value

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def _aggregation_draft_id(fields: dict[str, Any]) -> str:
    return _derived_id("synthetic-raw-aggregation-draft-v1", fields)


def _repository_aggregation_draft_id(fields: dict[str, Any]) -> str:
    return _derived_id(
        "repository-backed-synthetic-raw-aggregation-draft-v2", fields
    )


class RawStateCountsV1(PersistenceRevalidatedModel):
    supplied_revision_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    selected_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    not_selected_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    selection_unknown_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_present_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_not_requested_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_no_post_floor_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_missing_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_failed_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    source_incompatible_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_known_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_unknown_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_abstained_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_not_applicable_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_failed_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    value_incompatible_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    identity_unavailable_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    evidence_eligible_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    evidence_not_eligible_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    evidence_eligibility_unknown_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    evidence_coverage_known_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    evidence_coverage_unknown_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    evidence_coverage_not_applicable_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )

    @model_validator(mode="after")
    def exact_axis_totals(self) -> RawStateCountsV1:
        selection_total = (
            self.selected_count
            + self.not_selected_count
            + self.selection_unknown_count
        )
        source_total = (
            self.source_present_count
            + self.source_not_requested_count
            + self.source_no_post_floor_count
            + self.source_missing_count
            + self.source_failed_count
            + self.source_incompatible_count
        )
        value_total = (
            self.value_known_count
            + self.value_unknown_count
            + self.value_abstained_count
            + self.value_not_applicable_count
            + self.value_failed_count
            + self.value_incompatible_count
        )
        if selection_total != self.supplied_revision_count:
            raise ValueError("selection-state counts must cover the supplied set")
        if source_total != self.supplied_revision_count:
            raise ValueError("source-state counts must cover the supplied set")
        if value_total != self.supplied_revision_count:
            raise ValueError("value-state counts must cover the supplied set")
        if self.identity_unavailable_count > self.supplied_revision_count:
            raise ValueError("identity-unavailable count exceeds the supplied set")
        eligibility_total = (
            self.evidence_eligible_count
            + self.evidence_not_eligible_count
            + self.evidence_eligibility_unknown_count
        )
        coverage_total = (
            self.evidence_coverage_known_count
            + self.evidence_coverage_unknown_count
            + self.evidence_coverage_not_applicable_count
        )
        if eligibility_total != self.supplied_revision_count:
            raise ValueError("evidence eligibility counts must cover the supplied set")
        if coverage_total != self.supplied_revision_count:
            raise ValueError("evidence coverage counts must cover the supplied set")
        return self


class RawEvidenceCoverageAggregateV1(PersistenceRevalidatedModel):
    known_eligible_observation_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    numerator_sum: int = Field(strict=True, ge=0, le=MAX_COUNT)
    denominator_sum: int = Field(strict=True, ge=0, le=MAX_COUNT)
    ratio: float | None = None

    @field_validator("ratio", mode="before")
    @classmethod
    def optional_ratio(cls, value: Any) -> float | None:
        if value is None:
            return None
        result = _finite(value, nonnegative=True)
        if result > 1:
            raise ValueError("evidence coverage ratio cannot exceed one")
        return result

    @model_validator(mode="after")
    def exact_coverage_ratio(self) -> RawEvidenceCoverageAggregateV1:
        if self.numerator_sum > self.denominator_sum:
            raise ValueError("evidence numerator cannot exceed denominator")
        expected = (
            None
            if self.denominator_sum == 0
            else self.numerator_sum / self.denominator_sum
        )
        if self.ratio != expected:
            raise ValueError("evidence ratio must preserve known zero over zero")
        return self


class RawFractionAggregateV1(PersistenceRevalidatedModel):
    kind: Literal[TemporalValueKind.FRACTION] = TemporalValueKind.FRACTION
    known_observation_count: int = Field(strict=True, ge=1, le=MAX_COUNT)
    numerator_sum: int = Field(strict=True, ge=0, le=MAX_COUNT)
    denominator_sum: int = Field(strict=True, ge=1, le=MAX_COUNT)
    ratio: float

    @field_validator("ratio", mode="before")
    @classmethod
    def finite_ratio(cls, value: Any) -> float:
        result = _finite(value, nonnegative=True)
        if result > 1:
            raise ValueError("fraction aggregate ratio cannot exceed one")
        return result

    @model_validator(mode="after")
    def exact_ratio(self) -> RawFractionAggregateV1:
        if self.numerator_sum > self.denominator_sum:
            raise ValueError("fraction numerator sum cannot exceed denominator sum")
        if self.ratio != self.numerator_sum / self.denominator_sum:
            raise ValueError("fraction ratio must be derived from exact sums")
        return self


class RawCountExposureAggregateV1(PersistenceRevalidatedModel):
    kind: Literal[TemporalValueKind.COUNT_WITH_EXPOSURE] = (
        TemporalValueKind.COUNT_WITH_EXPOSURE
    )
    known_observation_count: int = Field(strict=True, ge=1, le=MAX_COUNT)
    count_sum: int = Field(strict=True, ge=0, le=MAX_COUNT)
    exposure_sum: float
    exposure_unit_code: str
    rate: float

    _unit = field_validator("exposure_unit_code")(_safe_code)

    @field_validator("exposure_sum", "rate", mode="before")
    @classmethod
    def finite_nonnegative(cls, value: Any) -> float:
        return _finite(value, nonnegative=True)

    @model_validator(mode="after")
    def exact_rate(self) -> RawCountExposureAggregateV1:
        if self.exposure_sum <= 0:
            raise ValueError("exposure sum must be positive")
        if self.rate != self.count_sum / self.exposure_sum:
            raise ValueError("rate must be derived from exact count and exposure sums")
        return self


class RawDistributionAggregateV1(PersistenceRevalidatedModel):
    kind: Literal[TemporalValueKind.DISTRIBUTION_SAMPLE] = (
        TemporalValueKind.DISTRIBUTION_SAMPLE
    )
    known_observation_count: int = Field(strict=True, ge=1, le=MAX_COUNT)
    p25: float
    median: float
    p75: float
    quantile_method_version: Literal[QUANTILE_METHOD_VERSION] = (
        QUANTILE_METHOD_VERSION
    )

    @field_validator("p25", "median", "p75", mode="before")
    @classmethod
    def finite_quantile(cls, value: Any) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def ordered_quantiles(self) -> RawDistributionAggregateV1:
        if not self.p25 <= self.median <= self.p75:
            raise ValueError("distribution quantiles must be ordered")
        return self


class RawSampledProportionAggregateV1(PersistenceRevalidatedModel):
    kind: Literal[TemporalValueKind.SAMPLED_PROPORTION] = (
        TemporalValueKind.SAMPLED_PROPORTION
    )
    known_observation_count: int = Field(strict=True, ge=1, le=MAX_COUNT)
    successes_sum: int = Field(strict=True, ge=0, le=MAX_COUNT)
    trials_sum: int = Field(strict=True, ge=1, le=MAX_COUNT)
    proportion: float
    interval_lower: float
    interval_upper: float
    confidence_level: Literal[0.95] = WILSON_CONFIDENCE_LEVEL
    source_interval_method_version: str
    interval_method_version: Literal[INTERVAL_METHOD_VERSION] = (
        INTERVAL_METHOD_VERSION
    )

    _source_interval = field_validator("source_interval_method_version")(
        _safe_code
    )

    @field_validator("proportion", "interval_lower", "interval_upper", mode="before")
    @classmethod
    def probability(cls, value: Any) -> float:
        result = _finite(value, nonnegative=True)
        if result > 1:
            raise ValueError("proportion values must be between zero and one")
        return result

    @model_validator(mode="after")
    def exact_proportion(self) -> RawSampledProportionAggregateV1:
        if self.successes_sum > self.trials_sum:
            raise ValueError("successes cannot exceed trials")
        if self.proportion != self.successes_sum / self.trials_sum:
            raise ValueError("proportion must be derived from exact sums")
        expected_lower, expected_upper = _wilson_interval(
            self.successes_sum, self.trials_sum
        )
        if (
            self.interval_lower != expected_lower
            or self.interval_upper != expected_upper
        ):
            raise ValueError("interval must be the code-owned Wilson interval")
        return self


RawAggregateValueV1 = Annotated[
    RawFractionAggregateV1
    | RawCountExposureAggregateV1
    | RawDistributionAggregateV1
    | RawSampledProportionAggregateV1,
    Field(discriminator="kind"),
]


class RawTaskBucketSummaryV1(PersistenceRevalidatedModel):
    task_mix_bucket: ComparisonTaskMixBucketV1
    task_type_state: ComparisonTaskTypeStateV1
    task_type: ComparisonTaskTypeV1 | None = None
    language_state: Literal[ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED] = (
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    )
    complexity_state: Literal[ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED] = (
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    )
    agent_permission_state: Literal[
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    ] = ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    agent_model_state: Literal[ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED] = (
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    )
    match_readiness: Literal[
        RawMatchReadinessV1.INSUFFICIENT_REQUIRED_STRATA
    ] = RawMatchReadinessV1.INSUFFICIENT_REQUIRED_STRATA
    state_counts: RawStateCountsV1
    evidence_coverage: RawEvidenceCoverageAggregateV1 | None = None

    @model_validator(mode="after")
    def exact_task_shape(self) -> RawTaskBucketSummaryV1:
        known = self.task_type_state is ComparisonTaskTypeStateV1.KNOWN_REVIEWED
        if known != (self.task_type is not None):
            raise ValueError("task type is present exactly when reviewed and known")
        if (
            self.state_counts.evidence_coverage_known_count == 0
        ) != (self.evidence_coverage is None):
            raise ValueError(
                "coverage aggregate exists exactly for known eligible coverage"
            )
        if self.evidence_coverage is not None and (
            self.evidence_coverage.known_eligible_observation_count
            != self.state_counts.evidence_coverage_known_count
        ):
            raise ValueError("coverage aggregate count must match known coverage")
        return self


class RawTaskBucketAggregateV1(RawTaskBucketSummaryV1):
    aggregate_value: RawAggregateValueV1 | None = None

    @model_validator(mode="after")
    def aggregate_only_known_values(self) -> RawTaskBucketAggregateV1:
        known = self.state_counts.value_known_count
        if (known == 0) != (self.aggregate_value is None):
            raise ValueError("numeric aggregate exists exactly for known values")
        if self.aggregate_value is not None:
            if self.aggregate_value.known_observation_count != known:
                raise ValueError("aggregate count must match known state count")
        return self


class RawCompatibilityRunV1(PersistenceRevalidatedModel):
    run_ordinal: int = Field(strict=True, ge=0, le=MAX_COUNT)
    comparison_identity: MetricComparisonIdentity
    comparison_identity_fingerprint: str
    first_revision_id: str
    last_revision_id: str
    first_effective_at: datetime
    last_effective_at: datetime
    included_revision_count: int = Field(strict=True, ge=1, le=MAX_COUNT)
    state_counts: RawStateCountsV1
    task_buckets: tuple[RawTaskBucketAggregateV1, ...] = Field(
        min_length=1, max_length=MAX_SUPPLIED_STRATA
    )

    _digests = field_validator(
        "comparison_identity_fingerprint", "first_revision_id", "last_revision_id"
    )(_digest)
    _times = field_validator("first_effective_at", "last_effective_at")(_utc)

    @model_validator(mode="after")
    def exact_run(self) -> RawCompatibilityRunV1:
        if self.comparison_identity_fingerprint != self.comparison_identity.fingerprint:
            raise ValueError("run must bind the exact comparison identity")
        if self.first_effective_at > self.last_effective_at:
            raise ValueError("run revision interval must be ordered")
        if self.state_counts.supplied_revision_count != self.included_revision_count:
            raise ValueError("run state count must cover every included revision")
        if sum(
            bucket.state_counts.supplied_revision_count for bucket in self.task_buckets
        ) != self.included_revision_count:
            raise ValueError("task buckets must partition the run")
        if _sum_state_counts(
            [bucket.state_counts for bucket in self.task_buckets]
        ) != self.state_counts:
            raise ValueError("run task states must equal the run state counts")
        bucket_keys = tuple(
            _task_bucket_sort_key(bucket) for bucket in self.task_buckets
        )
        if bucket_keys != tuple(sorted(bucket_keys)) or len(set(bucket_keys)) != len(
            bucket_keys
        ):
            raise ValueError("task buckets must be unique and canonically ordered")
        for bucket in self.task_buckets:
            aggregate = bucket.aggregate_value
            if (
                aggregate is not None
                and aggregate.kind is not self.comparison_identity.value_kind
            ):
                raise ValueError("task aggregate kind must match the run identity")
            if (
                isinstance(aggregate, RawSampledProportionAggregateV1)
                and aggregate.source_interval_method_version
                != self.comparison_identity.interval_method_version
            ):
                raise ValueError(
                    "sampled aggregate must retain the source identity interval"
                )
        return self


class RawCompatibilityTransitionV1(PersistenceRevalidatedModel):
    transition_ordinal: int = Field(strict=True, ge=0, le=MAX_COUNT)
    kind: RawTransitionKindV1
    before_run_ordinal: int = Field(strict=True, ge=0, le=MAX_COUNT)
    after_run_ordinal: int = Field(strict=True, ge=1, le=MAX_COUNT)
    before_identity_fingerprint: str
    after_identity_fingerprint: str
    dimensions: tuple[CompatibilityDimension, ...] = Field(max_length=8)
    identity_unavailable_gap_count: int = Field(strict=True, ge=0, le=MAX_COUNT)

    _digests = field_validator(
        "before_identity_fingerprint", "after_identity_fingerprint"
    )(_digest)

    @model_validator(mode="after")
    def exact_transition(self) -> RawCompatibilityTransitionV1:
        if self.after_run_ordinal != self.before_run_ordinal + 1:
            raise ValueError("transitions must join adjacent run ordinals")
        if self.kind is RawTransitionKindV1.IDENTITY_CHANGE:
            if (
                self.before_identity_fingerprint == self.after_identity_fingerprint
                or not self.dimensions
                or self.identity_unavailable_gap_count != 0
            ):
                raise ValueError(
                    "identity changes require distinct identities and dimensions"
                )
        elif (
            self.dimensions
            or self.identity_unavailable_gap_count <= 0
        ):
            raise ValueError("identity-unavailable gaps require a positive empty gap")
        if self.dimensions != tuple(
            sorted(self.dimensions, key=lambda item: item.value)
        ):
            raise ValueError("compatibility dimensions must be canonically ordered")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("compatibility dimensions must be unique")
        return self


class SyntheticRawAggregationDraftV1(PersistenceRevalidatedModel):
    contract_version: Literal[SYNTHETIC_RAW_AGGREGATION_VERSION] = (
        SYNTHETIC_RAW_AGGREGATION_VERSION
    )
    aggregation_draft_id: str
    anchor_scope: RepositoryPreparedTemporalScopeV1
    anchor_prepared_scope_id: str
    anchor_prepared_scope_fingerprint: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    history_floor_at: datetime
    installation_id: str | None = None
    project_id: str
    provider: Provider | None = None
    metric_key: str
    window: TemporalWindowSpec
    as_of: datetime
    effective_window_start_at: datetime
    effective_window_end_at: datetime
    window_coverage_state: RawWindowCoverageStateV1
    floor_left_censored: bool = Field(strict=True)
    last_n_shortfall: bool = Field(strict=True)
    last_n_shortfall_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    supplied_strata_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    excluded_late_seal_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    excluded_outside_window_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    included_revision_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    leading_identity_unavailable_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    trailing_identity_unavailable_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    ordered_included_stratum_fingerprints: tuple[str, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    ordered_supplied_stratum_manifest: tuple[
        RawSuppliedStratumManifestEntryV1, ...
    ] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    population_state: Literal[
        RawAggregationPopulationStateV1.SUPPLIED_SET_COMPLETENESS_UNKNOWN
    ] = RawAggregationPopulationStateV1.SUPPLIED_SET_COMPLETENESS_UNKNOWN
    state_counts: RawStateCountsV1
    task_buckets: tuple[RawTaskBucketSummaryV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    compatibility_runs: tuple[RawCompatibilityRunV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    compatibility_transitions: tuple[RawCompatibilityTransitionV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    policy_identity: RawAggregationPolicyIdentityV1
    policy_identity_fingerprint: str
    matched_estimate: None = None
    matched_pair_count: None = None

    structurally_constructible_not_capability: Literal[True] = True
    synthetic_test_only: Literal[True] = True
    supplied_set_only: Literal[True] = True
    repository_verification_required: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_verified: Literal[False] = False
    collection_completeness_verified: Literal[False] = False
    sealed: Literal[False] = False
    source_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    comparison_allowed: Literal[False] = False
    pair_matching_allowed: Literal[False] = False
    aggregate_materialization_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_allowed: Literal[False] = False
    recommendation_outcome_evaluation_allowed: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_inference_allowed: Literal[False] = False
    backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "aggregation_draft_id",
        "anchor_prepared_scope_id",
        "anchor_prepared_scope_fingerprint",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "policy_identity_fingerprint",
    )(_digest)
    _metric = field_validator("metric_key")(_safe_code)
    _times = field_validator(
        "history_floor_at",
        "as_of",
        "effective_window_start_at",
        "effective_window_end_at",
    )(_utc)

    @field_validator("installation_id")
    @classmethod
    def optional_installation(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("project_id")
    @classmethod
    def project_digest(cls, value: str) -> str:
        return _digest(value)

    @field_validator("ordered_included_stratum_fingerprints")
    @classmethod
    def exact_included_fingerprints(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if len(checked) != len(set(checked)):
            raise ValueError("included stratum fingerprints must be unique")
        if checked != tuple(sorted(checked)):
            raise ValueError("included stratum fingerprints must be canonical")
        return checked

    @field_validator("ordered_supplied_stratum_manifest")
    @classmethod
    def exact_supplied_manifest(
        cls, values: tuple[RawSuppliedStratumManifestEntryV1, ...]
    ) -> tuple[RawSuppliedStratumManifestEntryV1, ...]:
        checked: list[RawSuppliedStratumManifestEntryV1] = []
        fingerprints: set[str] = set()
        for value in values:
            item = RawSuppliedStratumManifestEntryV1.revalidate_for_persistence(
                value
            )
            fingerprint = item.fingerprint
            if fingerprint in fingerprints:
                raise ValueError("supplied manifest fingerprints must be unique")
            fingerprints.add(fingerprint)
            checked.append(item)
        canonical = tuple(
            sorted(
                checked,
                key=lambda item: (item.fingerprint, item.disposition.value),
            )
        )
        if tuple(checked) != canonical:
            raise ValueError("supplied manifest must be canonically ordered")
        return canonical

    @model_validator(mode="after")
    def exact_draft(self) -> SyntheticRawAggregationDraftV1:
        if (
            self.anchor_prepared_scope_id != self.anchor_scope.prepared_scope_id
            or self.anchor_prepared_scope_fingerprint
            != self.anchor_scope.fingerprint
            or self.root_receipt_id
            != self.anchor_scope.history_root.root_receipt_id
            or self.root_receipt_fingerprint
            != self.anchor_scope.history_root.fingerprint
            or self.history_floor_at
            != self.anchor_scope.history_root.history_floor_at
            or self.project_id != self.anchor_scope.history_root.project_id
        ):
            raise ValueError("aggregation draft must bind the exact anchor scope")
        if self.policy_identity_fingerprint != self.policy_identity.fingerprint:
            raise ValueError("aggregation draft must bind its exact policy identity")
        if self.as_of < self.history_floor_at:
            raise ValueError("aggregation as-of cannot predate the prospective floor")
        expected_start, expected_end, expected_censored = (
            _effective_window_bounds(
                window=self.window,
                as_of=self.as_of,
                floor=self.history_floor_at,
            )
        )
        if (
            self.effective_window_start_at != expected_start
            or self.effective_window_end_at != expected_end
            or self.floor_left_censored != expected_censored
        ):
            raise ValueError("effective aggregation window must be exactly derived")
        if self.last_n_shortfall != (self.last_n_shortfall_count > 0):
            raise ValueError("last-N shortfall boolean must match the exact count")
        if self.window.kind is not TemporalWindowKind.LAST_N and (
            self.last_n_shortfall or self.last_n_shortfall_count
        ):
            raise ValueError("only last-N windows can have a last-N shortfall")
        if self.window.kind is TemporalWindowKind.LAST_N:
            assert self.window.last_n is not None
            expected_shortfall = max(
                0, self.window.last_n - self.included_revision_count
            )
            if self.last_n_shortfall_count != expected_shortfall:
                raise ValueError("last-N shortfall count must be exactly derived")
        expected_coverage = _coverage_state(
            included=self.included_revision_count,
            left_censored=self.floor_left_censored,
            shortfall=self.last_n_shortfall_count,
        )
        if self.window_coverage_state is not expected_coverage:
            raise ValueError("window coverage state must be exactly derived")
        if (self.installation_id is None) != (self.provider is None):
            raise ValueError("installation and provider scope travel together")
        if (self.supplied_strata_count == 0) != (self.installation_id is None):
            raise ValueError("non-empty supplied sets require exact source scope")
        if self.included_revision_count != self.state_counts.supplied_revision_count:
            raise ValueError("top-level states must cover included revisions")
        if self.included_revision_count != len(
            self.ordered_included_stratum_fingerprints
        ):
            raise ValueError("included stratum manifest must be exact")
        if (
            self.included_revision_count
            + self.excluded_late_seal_count
            + self.excluded_outside_window_count
            != self.supplied_strata_count
        ):
            raise ValueError("included and excluded counts must partition the input")
        if len(self.ordered_supplied_stratum_manifest) != self.supplied_strata_count:
            raise ValueError("supplied stratum manifest must cover the full input")
        manifest_counts = {
            disposition: sum(
                item.disposition.value == disposition
                for item in self.ordered_supplied_stratum_manifest
            )
            for disposition in ("included", "late_seal", "outside_window")
        }
        if (
            manifest_counts["included"] != self.included_revision_count
            or manifest_counts["late_seal"] != self.excluded_late_seal_count
            or manifest_counts["outside_window"]
            != self.excluded_outside_window_count
        ):
            raise ValueError("supplied manifest dispositions must match exact counts")
        if tuple(
            item.fingerprint
            for item in self.ordered_supplied_stratum_manifest
            if item.disposition is RawStratumDispositionV1.INCLUDED
        ) != tuple(sorted(self.ordered_included_stratum_fingerprints)):
            raise ValueError("included manifest and included fingerprints must agree")
        if sum(
            bucket.state_counts.supplied_revision_count for bucket in self.task_buckets
        ) != self.included_revision_count:
            raise ValueError("task summaries must partition included revisions")
        if self.task_buckets:
            summed_task_states = _sum_state_counts(
                [bucket.state_counts for bucket in self.task_buckets]
            )
            if summed_task_states != self.state_counts:
                raise ValueError("task summary states must equal top-level states")
        if tuple(run.run_ordinal for run in self.compatibility_runs) != tuple(
            range(len(self.compatibility_runs))
        ):
            raise ValueError("compatibility run ordinals must be contiguous")
        if tuple(
            transition.transition_ordinal
            for transition in self.compatibility_transitions
        ) != tuple(range(len(self.compatibility_transitions))):
            raise ValueError("transition ordinals must be contiguous")
        expected_transitions = max(0, len(self.compatibility_runs) - 1)
        if len(self.compatibility_transitions) != expected_transitions:
            raise ValueError("every adjacent compatibility run requires a transition")
        run_covered = sum(
            run.included_revision_count for run in self.compatibility_runs
        )
        if run_covered != (
            self.included_revision_count
            - self.state_counts.identity_unavailable_count
        ):
            raise ValueError("runs must cover every identity-known revision")
        run_states = _sum_state_counts(
            [run.state_counts for run in self.compatibility_runs]
        )
        if run_states != _without_identity_unavailable(self.state_counts):
            raise ValueError("run states must equal all identity-known top states")
        gap_total = (
            self.leading_identity_unavailable_count
            + self.trailing_identity_unavailable_count
            + sum(
                item.identity_unavailable_gap_count
                for item in self.compatibility_transitions
            )
        )
        if gap_total != self.state_counts.identity_unavailable_count:
            raise ValueError("identity gaps must account for every unavailable identity")
        for index, transition in enumerate(self.compatibility_transitions):
            before = self.compatibility_runs[index]
            after = self.compatibility_runs[index + 1]
            if (
                transition.before_identity_fingerprint
                != before.comparison_identity_fingerprint
                or transition.after_identity_fingerprint
                != after.comparison_identity_fingerprint
            ):
                raise ValueError("transition must bind its exact adjacent runs")
            if transition.kind is RawTransitionKindV1.IDENTITY_CHANGE:
                expected_dimensions = _compatibility_dimensions(
                    before.comparison_identity,
                    after.comparison_identity,
                )
                if transition.dimensions != expected_dimensions:
                    raise ValueError("transition dimensions must be exactly derived")
        if self.included_revision_count == 0 and (
            self.compatibility_runs or self.task_buckets
        ):
            raise ValueError(
                "an empty supplied window cannot emit runs or task buckets"
            )
        expected_id = _aggregation_draft_id(
            self.model_dump(mode="python", exclude={"aggregation_draft_id"})
        )
        if self.aggregation_draft_id != expected_id:
            raise ValueError(
                "aggregation draft identity must bind the exact input manifest and payload"
            )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class RepositoryBackedSyntheticRawAggregationDraftV2(
    PersistenceRevalidatedModel
):
    """Unsealed supplied-set draft over structurally revalidated V22 receipts.

    The repository receipts commit stronger input graph identities than the V1
    comparison drafts.  Their presence does not prove that the caller obtained
    them from a repository, enumerate a complete population, or authorize this
    derived aggregate for persistence or product use.
    """

    contract_version: Literal[
        REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION
    ] = REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION
    aggregation_draft_id: str
    anchor: RepositoryPreparedComparisonStratumV1
    anchor_prepared_stratum_id: str
    anchor_prepared_stratum_fingerprint: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    history_floor_at: datetime
    installation_id: str
    project_id: str
    provider: Provider
    metric_key: str
    window: TemporalWindowSpec
    as_of: datetime
    effective_window_start_at: datetime
    effective_window_end_at: datetime
    window_coverage_state: RawWindowCoverageStateV1
    floor_left_censored: bool = Field(strict=True)
    last_n_shortfall: bool = Field(strict=True)
    last_n_shortfall_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    supplied_strata_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    excluded_late_seal_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    excluded_outside_window_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    included_revision_count: int = Field(strict=True, ge=0, le=MAX_COUNT)
    leading_identity_unavailable_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    trailing_identity_unavailable_count: int = Field(
        strict=True, ge=0, le=MAX_COUNT
    )
    ordered_included_stratum_fingerprints: tuple[str, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    ordered_supplied_stratum_manifest: tuple[
        RepositoryBackedStratumManifestEntryV2, ...
    ] = Field(default=(), max_length=MAX_SUPPLIED_STRATA)
    population_state: Literal[
        RawAggregationPopulationStateV1.SUPPLIED_SET_COMPLETENESS_UNKNOWN
    ] = RawAggregationPopulationStateV1.SUPPLIED_SET_COMPLETENESS_UNKNOWN
    state_counts: RawStateCountsV1
    task_buckets: tuple[RawTaskBucketSummaryV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    compatibility_runs: tuple[RawCompatibilityRunV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    compatibility_transitions: tuple[RawCompatibilityTransitionV1, ...] = Field(
        default=(), max_length=MAX_SUPPLIED_STRATA
    )
    policy_identity: RawAggregationPolicyIdentityV1
    policy_identity_fingerprint: str
    matched_estimate: None = None
    matched_pair_count: None = None

    structurally_constructible_not_capability: Literal[True] = True
    synthetic_test_only: Literal[True] = True
    supplied_set_only: Literal[True] = True
    input_receipt_structure_revalidated: Literal[True] = True
    input_repository_return_provenance_verified: Literal[False] = False
    repository_enumeration_performed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_verified: Literal[False] = False
    collection_completeness_verified: Literal[False] = False
    comparison_stratum_complete: Literal[False] = False
    sealed: Literal[False] = False
    source_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    comparison_allowed: Literal[False] = False
    pair_matching_allowed: Literal[False] = False
    aggregate_materialization_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_allowed: Literal[False] = False
    recommendation_outcome_evaluation_allowed: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_inference_allowed: Literal[False] = False
    backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "aggregation_draft_id",
        "anchor_prepared_stratum_id",
        "anchor_prepared_stratum_fingerprint",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "installation_id",
        "project_id",
        "policy_identity_fingerprint",
    )(_digest)
    _metric = field_validator("metric_key")(_safe_code)
    _times = field_validator(
        "history_floor_at",
        "as_of",
        "effective_window_start_at",
        "effective_window_end_at",
    )(_utc)

    @field_validator("ordered_included_stratum_fingerprints")
    @classmethod
    def exact_included_fingerprints(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if len(checked) != len(set(checked)):
            raise ValueError("included stratum fingerprints must be unique")
        if checked != tuple(sorted(checked)):
            raise ValueError("included stratum fingerprints must be canonical")
        return checked

    @field_validator("ordered_supplied_stratum_manifest")
    @classmethod
    def exact_supplied_manifest(
        cls,
        values: tuple[RepositoryBackedStratumManifestEntryV2, ...],
    ) -> tuple[RepositoryBackedStratumManifestEntryV2, ...]:
        checked = tuple(
            RepositoryBackedStratumManifestEntryV2.revalidate_for_persistence(
                value
            )
            for value in values
        )
        if tuple(item.supplied_ordinal for item in checked) != tuple(
            range(len(checked))
        ):
            raise ValueError("repository manifest ordinals must be contiguous")
        canonical = tuple(
            sorted(
                checked,
                key=lambda item: (
                    item.effective_at,
                    item.session_id,
                    item.revision_ordinal,
                    item.revision_id,
                    item.sealed_stratum_id,
                ),
            )
        )
        if checked != canonical:
            raise ValueError("repository manifest must use the total revision order")
        unique_roles = {
            "prepared": [item.prepared_stratum_id for item in checked],
            "sealed": [item.sealed_stratum_id for item in checked],
            "run": [item.analysis_run_id for item in checked],
            "batch": [item.sealed_batch_id for item in checked],
            "revision": [item.revision_id for item in checked],
        }
        for role, identities in unique_roles.items():
            if len(identities) != len(set(identities)):
                raise ValueError(f"repository manifest has duplicate {role} identity")
        coordinates = tuple(
            (item.session_id, item.revision_ordinal) for item in checked
        )
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("repository manifest has a duplicate revision coordinate")
        return checked

    @model_validator(mode="after")
    def exact_draft(
        self,
    ) -> RepositoryBackedSyntheticRawAggregationDraftV2:
        anchor = RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            self.anchor
        )
        root = anchor.prepared_scope.history_root
        dimensions = anchor.dimensions
        if (
            self.anchor_prepared_stratum_id != anchor.prepared_stratum_id
            or self.anchor_prepared_stratum_fingerprint != anchor.fingerprint
            or self.root_receipt_id != root.root_receipt_id
            or self.root_receipt_fingerprint != root.fingerprint
            or self.history_floor_at != root.history_floor_at
            or self.installation_id != dimensions.installation_id
            or self.project_id != dimensions.project_id
            or self.project_id != root.project_id
            or self.provider is not dimensions.provider
        ):
            raise ValueError("aggregation draft must bind the exact prepared anchor")
        if self.policy_identity_fingerprint != self.policy_identity.fingerprint:
            raise ValueError("aggregation draft must bind its exact policy identity")
        if self.as_of < self.history_floor_at:
            raise ValueError("aggregation as-of cannot predate the prospective floor")
        expected_start, expected_end, expected_censored = _effective_window_bounds(
            window=self.window,
            as_of=self.as_of,
            floor=self.history_floor_at,
        )
        if (
            self.effective_window_start_at != expected_start
            or self.effective_window_end_at != expected_end
            or self.floor_left_censored != expected_censored
        ):
            raise ValueError("effective aggregation window must be exactly derived")
        if self.last_n_shortfall != (self.last_n_shortfall_count > 0):
            raise ValueError("last-N shortfall boolean must match the exact count")
        if self.window.kind is not TemporalWindowKind.LAST_N and (
            self.last_n_shortfall or self.last_n_shortfall_count
        ):
            raise ValueError("only last-N windows can have a last-N shortfall")
        if self.window.kind is TemporalWindowKind.LAST_N:
            assert self.window.last_n is not None
            expected_shortfall = max(
                0, self.window.last_n - self.included_revision_count
            )
            if self.last_n_shortfall_count != expected_shortfall:
                raise ValueError("last-N shortfall count must be exactly derived")
        expected_coverage = _coverage_state(
            included=self.included_revision_count,
            left_censored=self.floor_left_censored,
            shortfall=self.last_n_shortfall_count,
        )
        if self.window_coverage_state is not expected_coverage:
            raise ValueError("window coverage state must be exactly derived")
        if len(self.ordered_supplied_stratum_manifest) != self.supplied_strata_count:
            raise ValueError("repository manifest must cover the supplied set")
        expected_dispositions = _repository_manifest_dispositions(
            self.ordered_supplied_stratum_manifest,
            window=self.window,
            as_of=self.as_of,
            floor=self.history_floor_at,
        )
        if tuple(item.disposition for item in self.ordered_supplied_stratum_manifest) != (
            expected_dispositions
        ):
            raise ValueError("repository manifest dispositions must be exact")
        manifest_counts = {
            disposition: sum(
                item.disposition is disposition
                for item in self.ordered_supplied_stratum_manifest
            )
            for disposition in RawStratumDispositionV1
        }
        if (
            manifest_counts[RawStratumDispositionV1.INCLUDED]
            != self.included_revision_count
            or manifest_counts[RawStratumDispositionV1.LATE_SEAL]
            != self.excluded_late_seal_count
            or manifest_counts[RawStratumDispositionV1.OUTSIDE_WINDOW]
            != self.excluded_outside_window_count
            or self.included_revision_count
            + self.excluded_late_seal_count
            + self.excluded_outside_window_count
            != self.supplied_strata_count
        ):
            raise ValueError("included and excluded counts must partition the input")
        expected_included = tuple(
            sorted(
                item.sealed_stratum_fingerprint
                for item in self.ordered_supplied_stratum_manifest
                if item.disposition is RawStratumDispositionV1.INCLUDED
            )
        )
        if self.ordered_included_stratum_fingerprints != expected_included:
            raise ValueError("included fingerprints must match the exact manifest")
        if self.included_revision_count != self.state_counts.supplied_revision_count:
            raise ValueError("top-level states must cover included revisions")
        if sum(
            bucket.state_counts.supplied_revision_count for bucket in self.task_buckets
        ) != self.included_revision_count:
            raise ValueError("task summaries must partition included revisions")
        if self.task_buckets and _sum_state_counts(
            [bucket.state_counts for bucket in self.task_buckets]
        ) != self.state_counts:
            raise ValueError("task summary states must equal top-level states")
        if tuple(run.run_ordinal for run in self.compatibility_runs) != tuple(
            range(len(self.compatibility_runs))
        ):
            raise ValueError("compatibility run ordinals must be contiguous")
        if tuple(
            transition.transition_ordinal
            for transition in self.compatibility_transitions
        ) != tuple(range(len(self.compatibility_transitions))):
            raise ValueError("transition ordinals must be contiguous")
        if len(self.compatibility_transitions) != max(
            0, len(self.compatibility_runs) - 1
        ):
            raise ValueError("every adjacent compatibility run requires a transition")
        run_covered = sum(
            run.included_revision_count for run in self.compatibility_runs
        )
        if run_covered != (
            self.included_revision_count
            - self.state_counts.identity_unavailable_count
        ):
            raise ValueError("runs must cover every identity-known revision")
        if _sum_state_counts(
            [run.state_counts for run in self.compatibility_runs]
        ) != _without_identity_unavailable(self.state_counts):
            raise ValueError("run states must equal all identity-known top states")
        gap_total = (
            self.leading_identity_unavailable_count
            + self.trailing_identity_unavailable_count
            + sum(
                transition.identity_unavailable_gap_count
                for transition in self.compatibility_transitions
            )
        )
        if gap_total != self.state_counts.identity_unavailable_count:
            raise ValueError("identity gaps must account for every unavailable identity")
        for index, transition in enumerate(self.compatibility_transitions):
            before = self.compatibility_runs[index]
            after = self.compatibility_runs[index + 1]
            if (
                transition.before_identity_fingerprint
                != before.comparison_identity_fingerprint
                or transition.after_identity_fingerprint
                != after.comparison_identity_fingerprint
            ):
                raise ValueError("transition must bind its exact adjacent runs")
            if (
                transition.kind is RawTransitionKindV1.IDENTITY_CHANGE
                and transition.dimensions
                != _compatibility_dimensions(
                    before.comparison_identity, after.comparison_identity
                )
            ):
                raise ValueError("transition dimensions must be exactly derived")
        if self.included_revision_count == 0 and (
            self.compatibility_runs or self.task_buckets
        ):
            raise ValueError("an empty supplied window cannot emit descriptive groups")
        expected_id = _repository_aggregation_draft_id(
            self.model_dump(mode="python", exclude={"aggregation_draft_id"})
        )
        if self.aggregation_draft_id != expected_id:
            raise ValueError("aggregation draft identity must bind its exact payload")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


@dataclass(frozen=True, slots=True)
class _Entry:
    stratum: SealedComparisonStratumDraftV1 | RepositorySealedComparisonStratumV1
    stratum_fingerprint: str
    sealed_at: datetime
    revision_id: str
    session_id: str
    revision_ordinal: int
    effective_at: datetime
    sort_key: tuple[datetime, str, int, str]
    identity: MetricComparisonIdentity | None
    observation: TemporalMetricObservationV2 | None
    selection_state: TemporalSelectionState
    source_state: TemporalSourceState
    value_state: TemporalValueState
    evidence_coverage_eligibility: EvidenceCoverageEligibility
    evidence_coverage_state: EvidenceCoverageState
    evidence_numerator: int | None
    evidence_denominator: int | None
    task_mix_bucket: ComparisonTaskMixBucketV1
    task_type_state: ComparisonTaskTypeStateV1
    task_type: ComparisonTaskTypeV1 | None


def _task_key(entry: _Entry) -> tuple[str, str, str]:
    return (
        entry.task_mix_bucket.value,
        entry.task_type_state.value,
        "" if entry.task_type is None else entry.task_type.value,
    )


def _task_bucket_sort_key(
    bucket: RawTaskBucketSummaryV1,
) -> tuple[str, str, str]:
    return (
        bucket.task_mix_bucket.value,
        bucket.task_type_state.value,
        "" if bucket.task_type is None else bucket.task_type.value,
    )


def _state_counts(entries: list[_Entry]) -> RawStateCountsV1:
    def count(enum_value: Any, attribute: str) -> int:
        return sum(getattr(entry, attribute) is enum_value for entry in entries)

    return RawStateCountsV1(
        supplied_revision_count=len(entries),
        selected_count=count(TemporalSelectionState.SELECTED, "selection_state"),
        not_selected_count=count(
            TemporalSelectionState.NOT_SELECTED, "selection_state"
        ),
        selection_unknown_count=count(
            TemporalSelectionState.SELECTION_UNKNOWN, "selection_state"
        ),
        source_present_count=count(TemporalSourceState.PRESENT, "source_state"),
        source_not_requested_count=count(
            TemporalSourceState.NOT_REQUESTED, "source_state"
        ),
        source_no_post_floor_count=count(
            TemporalSourceState.NO_POST_FLOOR_SOURCE, "source_state"
        ),
        source_missing_count=count(
            TemporalSourceState.SOURCE_MISSING, "source_state"
        ),
        source_failed_count=count(
            TemporalSourceState.SOURCE_FAILED, "source_state"
        ),
        source_incompatible_count=count(
            TemporalSourceState.SOURCE_INCOMPATIBLE, "source_state"
        ),
        value_known_count=count(TemporalValueState.KNOWN, "value_state"),
        value_unknown_count=count(TemporalValueState.UNKNOWN, "value_state"),
        value_abstained_count=count(TemporalValueState.ABSTAINED, "value_state"),
        value_not_applicable_count=count(
            TemporalValueState.NOT_APPLICABLE, "value_state"
        ),
        value_failed_count=count(TemporalValueState.FAILED, "value_state"),
        value_incompatible_count=count(
            TemporalValueState.INCOMPATIBLE, "value_state"
        ),
        identity_unavailable_count=sum(entry.identity is None for entry in entries),
        evidence_eligible_count=count(
            EvidenceCoverageEligibility.ELIGIBLE,
            "evidence_coverage_eligibility",
        ),
        evidence_not_eligible_count=count(
            EvidenceCoverageEligibility.NOT_ELIGIBLE,
            "evidence_coverage_eligibility",
        ),
        evidence_eligibility_unknown_count=count(
            EvidenceCoverageEligibility.UNKNOWN,
            "evidence_coverage_eligibility",
        ),
        evidence_coverage_known_count=count(
            EvidenceCoverageState.KNOWN,
            "evidence_coverage_state",
        ),
        evidence_coverage_unknown_count=count(
            EvidenceCoverageState.UNKNOWN,
            "evidence_coverage_state",
        ),
        evidence_coverage_not_applicable_count=count(
            EvidenceCoverageState.NOT_APPLICABLE,
            "evidence_coverage_state",
        ),
    )


def _sum_state_counts(values: list[RawStateCountsV1]) -> RawStateCountsV1:
    return RawStateCountsV1(
        **{
            field_name: sum(getattr(value, field_name) for value in values)
            for field_name in RawStateCountsV1.model_fields
        }
    )


def _without_identity_unavailable(
    value: RawStateCountsV1,
) -> RawStateCountsV1:
    gap = value.identity_unavailable_count
    fields = value.model_dump(mode="python")
    fields["supplied_revision_count"] -= gap
    fields["not_selected_count"] -= gap
    fields["source_not_requested_count"] -= gap
    fields["value_unknown_count"] -= gap
    fields["evidence_eligibility_unknown_count"] -= gap
    fields["evidence_coverage_unknown_count"] -= gap
    fields["identity_unavailable_count"] = 0
    if any(isinstance(item, int) and item < 0 for item in fields.values()):
        raise ValueError("identity-unavailable state counts are inconsistent")
    return RawStateCountsV1(**fields)


def _aggregate_evidence_coverage(
    entries: list[_Entry],
) -> RawEvidenceCoverageAggregateV1 | None:
    known = [
        entry
        for entry in entries
        if entry.evidence_coverage_state is EvidenceCoverageState.KNOWN
    ]
    if not known:
        return None
    if any(
        entry.evidence_coverage_eligibility
        is not EvidenceCoverageEligibility.ELIGIBLE
        or entry.evidence_numerator is None
        or entry.evidence_denominator is None
        for entry in known
    ):
        raise ValueError("known evidence coverage requires exact eligible counts")
    numerator = _safe_int_sum(
        [int(entry.evidence_numerator) for entry in known]
    )
    denominator = _safe_int_sum(
        [int(entry.evidence_denominator) for entry in known]
    )
    return RawEvidenceCoverageAggregateV1(
        known_eligible_observation_count=len(known),
        numerator_sum=numerator,
        denominator_sum=denominator,
        ratio=None if denominator == 0 else numerator / denominator,
    )


def _type7(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("a quantile requires at least one sample")
    if len(ordered) == 1:
        return _finite(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    try:
        result = math.fsum(
            [ordered[lower] * (1.0 - fraction), ordered[upper] * fraction]
        )
    except OverflowError:
        raise ValueError("quantile interpolation exceeds the finite range") from None
    return _finite(result)


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    proportion = successes / trials
    z_squared = WILSON_Z * WILSON_Z
    denominator = 1.0 + z_squared / trials
    centre = (proportion + z_squared / (2.0 * trials)) / denominator
    margin = (
        WILSON_Z
        * math.sqrt(
            (proportion * (1.0 - proportion) + z_squared / (4.0 * trials))
            / trials
        )
        / denominator
    )
    lower = 0.0 if successes == 0 else max(0.0, centre - margin)
    upper = 1.0 if successes == trials else min(1.0, centre + margin)
    return lower, upper


def _aggregate_known(
    entries: list[_Entry], identity: MetricComparisonIdentity
) -> RawAggregateValueV1 | None:
    values = [
        entry.observation.value
        for entry in entries
        if entry.value_state is TemporalValueState.KNOWN
        and entry.observation is not None
        and entry.observation.value is not None
    ]
    if not values:
        return None
    if identity.value_kind is TemporalValueKind.FRACTION:
        if not all(isinstance(value, FractionObservationValue) for value in values):
            raise ValueError("fraction identity requires only fraction observations")
        numerator = _safe_int_sum([value.numerator for value in values])
        denominator = _safe_int_sum([value.denominator for value in values])
        return RawFractionAggregateV1(
            known_observation_count=len(values),
            numerator_sum=numerator,
            denominator_sum=denominator,
            ratio=numerator / denominator,
        )
    if identity.value_kind is TemporalValueKind.COUNT_WITH_EXPOSURE:
        if not all(
            isinstance(value, CountExposureObservationValue) for value in values
        ):
            raise ValueError("count identity requires only count/exposure observations")
        units = {value.exposure_unit_code for value in values}
        if units != {identity.exposure_unit_code}:
            raise ValueError("count exposures must match the identity unit")
        count_sum = _safe_int_sum([value.count for value in values])
        exposure_sum = _safe_float_sum(
            [value.exposure for value in values], nonnegative=True
        )
        return RawCountExposureAggregateV1(
            known_observation_count=len(values),
            count_sum=count_sum,
            exposure_sum=exposure_sum,
            exposure_unit_code=next(iter(units)),
            rate=count_sum / exposure_sum,
        )
    if identity.value_kind is TemporalValueKind.DISTRIBUTION_SAMPLE:
        if not all(
            isinstance(value, DistributionSampleObservationValue) for value in values
        ):
            raise ValueError("distribution identity requires only sample observations")
        samples = [value.sample for value in values]
        return RawDistributionAggregateV1(
            known_observation_count=len(values),
            p25=_type7(samples, 0.25),
            median=_type7(samples, 0.5),
            p75=_type7(samples, 0.75),
        )
    if not all(
        isinstance(value, SampledProportionObservationValue) for value in values
    ):
        raise ValueError("proportion identity requires only sampled proportions")
    successes = _safe_int_sum([value.successes for value in values])
    trials = _safe_int_sum([value.trials for value in values])
    lower, upper = _wilson_interval(successes, trials)
    return RawSampledProportionAggregateV1(
        known_observation_count=len(values),
        successes_sum=successes,
        trials_sum=trials,
        proportion=successes / trials,
        interval_lower=lower,
        interval_upper=upper,
        source_interval_method_version=identity.interval_method_version,
    )


_IDENTITY_DIMENSION_FIELDS: dict[CompatibilityDimension, tuple[str, ...]] = {
    CompatibilityDimension.METRIC_CONTRACT: (
        "metric_key",
        "metric_definition_version",
        "metric_definition_sha256",
        "metric_question_version",
        "metric_question_sha256",
        "observation_contract_version",
    ),
    CompatibilityDimension.VALUE_SEMANTICS: (
        "value_kind",
        "unit_code",
        "direction",
        "aggregation_semantics",
        "exposure_unit_code",
        "trend",
        "interval_method_version",
    ),
    CompatibilityDimension.EVIDENCE_CONTRACT: (
        "evidence_tier",
        "evidence_contract_version",
    ),
    CompatibilityDimension.ESTIMATOR_CONFIGURATION: (
        "estimator_kind",
        "estimator_plan_version",
        "estimator_plan_sha256",
        "estimator_lifecycle",
        "activation_receipt_sha256",
        "preprocessing_version",
        "preprocessing_sha256",
        "prompt_template_version",
        "prompt_template_sha256",
        "rubric_version",
        "rubric_sha256",
        "reasoning_effort",
        "router_version",
        "router_sha256",
    ),
    CompatibilityDimension.MODEL_IDENTITY: (
        "model_provider",
        "requested_model_key",
        "requested_model_revision",
        "served_model_key",
        "served_model_revision",
        "served_model_fallback",
        "model_weight_identity_state",
        "model_weight_set_sha256",
        "tokenizer_key",
        "tokenizer_revision",
        "tokenizer_identity_state",
        "tokenizer_sha256",
        "model_license_code",
    ),
    CompatibilityDimension.CALIBRATION: (
        "calibration_version",
        "calibration_sha256",
    ),
    CompatibilityDimension.PROVIDER_SCHEMA: (
        "provider",
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
    ),
    CompatibilityDimension.PRIVACY_REDACTOR: (
        "redactor_version",
        "redactor_sha256",
        "privacy_policy_version",
    ),
}


def _compatibility_dimensions(
    before: MetricComparisonIdentity, after: MetricComparisonIdentity
) -> tuple[CompatibilityDimension, ...]:
    changed = tuple(
        dimension
        for dimension, fields in _IDENTITY_DIMENSION_FIELDS.items()
        if any(getattr(before, field) != getattr(after, field) for field in fields)
    )
    if before.fingerprint != after.fingerprint and not changed:
        raise ValueError("comparison identity changed outside known dimensions")
    return tuple(sorted(changed, key=lambda item: item.value))


def _bucket_summaries(entries: list[_Entry]) -> tuple[RawTaskBucketSummaryV1, ...]:
    grouped: dict[tuple[str, str, str], list[_Entry]] = defaultdict(list)
    for entry in entries:
        grouped[_task_key(entry)].append(entry)
    result = []
    for key in sorted(grouped):
        group = grouped[key]
        sample = group[0]
        result.append(
            RawTaskBucketSummaryV1(
                task_mix_bucket=sample.task_mix_bucket,
                task_type_state=sample.task_type_state,
                task_type=sample.task_type,
                state_counts=_state_counts(group),
                evidence_coverage=_aggregate_evidence_coverage(group),
            )
        )
    return tuple(result)


def _bucket_aggregates(
    entries: list[_Entry], identity: MetricComparisonIdentity
) -> tuple[RawTaskBucketAggregateV1, ...]:
    grouped: dict[tuple[str, str, str], list[_Entry]] = defaultdict(list)
    for entry in entries:
        grouped[_task_key(entry)].append(entry)
    result = []
    for key in sorted(grouped):
        group = grouped[key]
        sample = group[0]
        result.append(
            RawTaskBucketAggregateV1(
                task_mix_bucket=sample.task_mix_bucket,
                task_type_state=sample.task_type_state,
                task_type=sample.task_type,
                state_counts=_state_counts(group),
                evidence_coverage=_aggregate_evidence_coverage(group),
                aggregate_value=_aggregate_known(group, identity),
            )
        )
    return tuple(result)


def _entry_for(
    stratum: SealedComparisonStratumDraftV1, metric_key: str
) -> _Entry:
    seal_draft = stratum.sealed_batch.seal_draft
    revision = seal_draft.session_revision
    batch = seal_draft.observation_batch
    dimensions = stratum.prepared_stratum.dimensions
    observation: TemporalMetricObservationV2 | None = None
    identity: MetricComparisonIdentity | None = None
    if metric_key in batch.selected_metric_keys:
        matches = tuple(
            candidate
            for candidate in batch.observations
            if candidate.comparison_identity.metric_key == metric_key
        )
        if len(matches) != 1:
            raise ValueError("selected metric must have one exact observation")
        observation = matches[0]
        identity = observation.comparison_identity
        selection_state = observation.selection_state
        source_state = observation.source_state
        value_state = observation.value_state
    else:
        selection_state = TemporalSelectionState.NOT_SELECTED
        source_state = TemporalSourceState.NOT_REQUESTED
        value_state = TemporalValueState.UNKNOWN
    if observation is None:
        evidence_eligibility = EvidenceCoverageEligibility.UNKNOWN
        evidence_state = EvidenceCoverageState.UNKNOWN
        evidence_numerator = None
        evidence_denominator = None
    else:
        evidence_eligibility = observation.evidence_coverage_eligibility
        evidence_state = observation.evidence_coverage_state
        evidence_numerator = observation.evidence_numerator
        evidence_denominator = observation.evidence_denominator
    return _Entry(
        stratum=stratum,
        stratum_fingerprint=stratum.fingerprint,
        sealed_at=stratum.sealed_at,
        revision_id=revision.revision_id,
        session_id=revision.session_id,
        revision_ordinal=revision.revision_ordinal,
        effective_at=revision.effective_at,
        sort_key=(
            revision.effective_at,
            revision.session_id,
            revision.revision_ordinal,
            revision.revision_id,
        ),
        identity=identity,
        observation=observation,
        selection_state=selection_state,
        source_state=source_state,
        value_state=value_state,
        evidence_coverage_eligibility=evidence_eligibility,
        evidence_coverage_state=evidence_state,
        evidence_numerator=evidence_numerator,
        evidence_denominator=evidence_denominator,
        task_mix_bucket=dimensions.task_mix_bucket,
        task_type_state=dimensions.task_type_state,
        task_type=dimensions.task_type,
    )


def _entry_for_repository_receipt(
    stratum: RepositorySealedComparisonStratumV1,
    metric_key: str,
) -> _Entry:
    seal_draft = stratum.sealed_batch.seal_draft
    revision = seal_draft.session_revision
    batch = seal_draft.observation_batch
    dimensions = stratum.prepared_receipt.dimensions
    observation: TemporalMetricObservationV2 | None = None
    identity: MetricComparisonIdentity | None = None
    if metric_key in batch.selected_metric_keys:
        matches = tuple(
            candidate
            for candidate in batch.observations
            if candidate.comparison_identity.metric_key == metric_key
        )
        if len(matches) != 1:
            raise ValueError("selected metric must have one exact observation")
        observation = matches[0]
        identity = observation.comparison_identity
        selection_state = observation.selection_state
        source_state = observation.source_state
        value_state = observation.value_state
    else:
        selection_state = TemporalSelectionState.NOT_SELECTED
        source_state = TemporalSourceState.NOT_REQUESTED
        value_state = TemporalValueState.UNKNOWN
    if observation is None:
        evidence_eligibility = EvidenceCoverageEligibility.UNKNOWN
        evidence_state = EvidenceCoverageState.UNKNOWN
        evidence_numerator = None
        evidence_denominator = None
    else:
        evidence_eligibility = observation.evidence_coverage_eligibility
        evidence_state = observation.evidence_coverage_state
        evidence_numerator = observation.evidence_numerator
        evidence_denominator = observation.evidence_denominator
    return _Entry(
        stratum=stratum,
        stratum_fingerprint=stratum.fingerprint,
        sealed_at=stratum.sealed_at,
        revision_id=revision.revision_id,
        session_id=revision.session_id,
        revision_ordinal=revision.revision_ordinal,
        effective_at=revision.effective_at,
        sort_key=(
            revision.effective_at,
            revision.session_id,
            revision.revision_ordinal,
            revision.revision_id,
        ),
        identity=identity,
        observation=observation,
        selection_state=selection_state,
        source_state=source_state,
        value_state=value_state,
        evidence_coverage_eligibility=evidence_eligibility,
        evidence_coverage_state=evidence_state,
        evidence_numerator=evidence_numerator,
        evidence_denominator=evidence_denominator,
        task_mix_bucket=dimensions.task_mix_bucket,
        task_type_state=dimensions.task_type_state,
        task_type=dimensions.task_type,
    )


def _effective_window_bounds(
    *,
    window: TemporalWindowSpec,
    as_of: datetime,
    floor: datetime,
) -> tuple[datetime, datetime, bool]:
    if window.kind is TemporalWindowKind.LAST_N:
        return floor, as_of, False
    if window.kind is TemporalWindowKind.ROLLING_DAYS:
        requested_start = as_of - timedelta(days=int(window.days))
        requested_end = as_of
    else:
        if window.end_at is None or window.start_at is None:
            raise ValueError("custom window is incomplete")
        if window.end_at > as_of:
            raise ValueError("custom window end cannot exceed aggregation as-of")
        requested_start = window.start_at
        requested_end = window.end_at
    left_censored = requested_start < floor
    if requested_end <= floor:
        return floor, floor, left_censored
    return max(requested_start, floor), requested_end, left_censored


def _repository_manifest_dispositions(
    manifest: tuple[RepositoryBackedStratumManifestEntryV2, ...],
    *,
    window: TemporalWindowSpec,
    as_of: datetime,
    floor: datetime,
) -> tuple[RawStratumDispositionV1, ...]:
    visible = tuple(
        item
        for item in manifest
        if item.sealed_at <= as_of and item.effective_at < as_of
    )
    if window.kind is TemporalWindowKind.LAST_N:
        assert window.last_n is not None
        selected = tuple(
            item for item in visible if item.effective_at >= floor
        )[-window.last_n :]
    else:
        start, end, _ = _effective_window_bounds(
            window=window, as_of=as_of, floor=floor
        )
        selected = tuple(
            item for item in visible if start <= item.effective_at < end
        )
    selected_ids = {item.sealed_stratum_id for item in selected}
    return tuple(
        (
            RawStratumDispositionV1.LATE_SEAL
            if item.sealed_at > as_of
            else (
                RawStratumDispositionV1.INCLUDED
                if item.sealed_stratum_id in selected_ids
                else RawStratumDispositionV1.OUTSIDE_WINDOW
            )
        )
        for item in manifest
    )


def _select_window(
    entries: list[_Entry],
    *,
    window: TemporalWindowSpec,
    as_of: datetime,
    floor: datetime,
) -> tuple[list[_Entry], datetime, datetime, bool, int, int]:
    late_count = sum(entry.sealed_at > as_of for entry in entries)
    visible = [
        entry
        for entry in entries
        if entry.sealed_at <= as_of and entry.effective_at < as_of
    ]
    visible.sort(key=lambda entry: entry.sort_key)
    left_censored = False
    shortfall = 0
    if window.kind is TemporalWindowKind.LAST_N:
        post_floor = [entry for entry in visible if entry.effective_at >= floor]
        selected = post_floor[-window.last_n :]  # type: ignore[index]
        shortfall = max(0, int(window.last_n) - len(selected))
        return selected, floor, as_of, False, shortfall, late_count
    effective_start, effective_end, left_censored = _effective_window_bounds(
        window=window, as_of=as_of, floor=floor
    )
    selected = [
        entry
        for entry in visible
        if effective_start <= entry.effective_at < effective_end
    ]
    return selected, effective_start, effective_end, left_censored, 0, late_count


def _coverage_state(
    *, included: int, left_censored: bool, shortfall: int
) -> RawWindowCoverageStateV1:
    if included == 0:
        return RawWindowCoverageStateV1.NO_INCLUDED_REVISIONS
    if left_censored and shortfall:
        return RawWindowCoverageStateV1.LEFT_CENSORED_AND_LAST_N_SHORTFALL
    if left_censored:
        return RawWindowCoverageStateV1.LEFT_CENSORED_BY_PROSPECTIVE_FLOOR
    if shortfall:
        return RawWindowCoverageStateV1.LAST_N_SHORTFALL
    return RawWindowCoverageStateV1.SUPPLIED_WINDOW


def _build_runs(
    entries: list[_Entry],
) -> tuple[
    tuple[RawCompatibilityRunV1, ...],
    tuple[RawCompatibilityTransitionV1, ...],
    int,
    int,
]:
    run_groups: list[list[_Entry]] = []
    pending_gap_before: list[int] = []
    gap_count = 0
    leading_gap_count = 0
    current: list[_Entry] = []
    current_fingerprint: str | None = None
    for entry in entries:
        if entry.identity is None:
            if current:
                run_groups.append(current)
                current = []
                current_fingerprint = None
                pending_gap_before.append(0)
            gap_count += 1
            continue
        fingerprint = entry.identity.fingerprint
        if current_fingerprint is None:
            if run_groups:
                pending_gap_before[-1] = gap_count
            else:
                leading_gap_count = gap_count
            gap_count = 0
            current = [entry]
            current_fingerprint = fingerprint
        elif fingerprint == current_fingerprint:
            current.append(entry)
        else:
            run_groups.append(current)
            pending_gap_before.append(0)
            current = [entry]
            current_fingerprint = fingerprint
    if current:
        run_groups.append(current)
    if not run_groups:
        leading_gap_count = gap_count
        trailing_gap_count = 0
    else:
        trailing_gap_count = gap_count
    runs: list[RawCompatibilityRunV1] = []
    for ordinal, group in enumerate(run_groups):
        identity = group[0].identity
        if identity is None:
            raise ValueError("compatibility run requires a known identity")
        runs.append(
            RawCompatibilityRunV1(
                run_ordinal=ordinal,
                comparison_identity=identity,
                comparison_identity_fingerprint=identity.fingerprint,
                first_revision_id=group[0].revision_id,
                last_revision_id=group[-1].revision_id,
                first_effective_at=group[0].effective_at,
                last_effective_at=group[-1].effective_at,
                included_revision_count=len(group),
                state_counts=_state_counts(group),
                task_buckets=_bucket_aggregates(group, identity),
            )
        )
    transitions: list[RawCompatibilityTransitionV1] = []
    for ordinal in range(max(0, len(runs) - 1)):
        before = runs[ordinal]
        after = runs[ordinal + 1]
        between_gap = (
            pending_gap_before[ordinal]
            if ordinal < len(pending_gap_before)
            else 0
        )
        if between_gap:
            kind = RawTransitionKindV1.IDENTITY_UNAVAILABLE_GAP
            dimensions: tuple[CompatibilityDimension, ...] = ()
        else:
            kind = RawTransitionKindV1.IDENTITY_CHANGE
            dimensions = _compatibility_dimensions(
                before.comparison_identity, after.comparison_identity
            )
        transitions.append(
            RawCompatibilityTransitionV1(
                transition_ordinal=ordinal,
                kind=kind,
                before_run_ordinal=ordinal,
                after_run_ordinal=ordinal + 1,
                before_identity_fingerprint=before.comparison_identity_fingerprint,
                after_identity_fingerprint=after.comparison_identity_fingerprint,
                dimensions=dimensions,
                identity_unavailable_gap_count=between_gap,
            )
        )
    return (
        tuple(runs),
        tuple(transitions),
        leading_gap_count,
        trailing_gap_count,
    )


def draft_synthetic_raw_aggregation(
    *,
    anchor_scope: RepositoryPreparedTemporalScopeV1,
    metric_key: str,
    window: TemporalWindowSpec,
    as_of: datetime,
    strata: tuple[SealedComparisonStratumDraftV1, ...],
) -> SyntheticRawAggregationDraftV1:
    """Derive a bounded, deterministic, non-authoritative raw aggregation.

    The tuple cardinality is checked before any stratum is accessed.  Every
    nested object is then recursively revalidated so a frozen ``model_copy``
    cannot promote trust flags or substitute lineage.
    """

    if not isinstance(strata, tuple):
        raise ValueError("strata must be a bounded immutable tuple")
    supplied_count = len(strata)
    if supplied_count > MAX_SUPPLIED_STRATA:
        raise ValueError("too many supplied comparison strata")
    anchor = RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(
        anchor_scope
    )
    requested_window = TemporalWindowSpec.model_validate(
        window.model_dump(mode="python")
    )
    checked_as_of = _utc(as_of)
    checked_metric = _safe_code(metric_key)
    floor = anchor.history_root.history_floor_at
    if checked_as_of < floor:
        raise ValueError("aggregation as-of cannot predate the prospective floor")
    checked_strata = tuple(
        SealedComparisonStratumDraftV1.revalidate_for_persistence(value)
        for value in strata
    )
    role_sets = {
        "stratum": [value.sealed_stratum_id for value in checked_strata],
        "batch": [value.sealed_batch.sealed_batch_id for value in checked_strata],
        "revision": [
            value.sealed_batch.seal_draft.session_revision.revision_id
            for value in checked_strata
        ],
        "run": [value.analysis_run.draft.run_id for value in checked_strata],
    }
    for role, values in role_sets.items():
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {role} identity in supplied strata")
    revision_coordinates = [
        (
            value.sealed_batch.seal_draft.session_revision.session_id,
            value.sealed_batch.seal_draft.session_revision.revision_ordinal,
        )
        for value in checked_strata
    ]
    if len(revision_coordinates) != len(set(revision_coordinates)):
        raise ValueError("duplicate session revision coordinate in supplied strata")
    installations: set[str] = set()
    providers: set[Provider] = set()
    entries: list[_Entry] = []
    for value in checked_strata:
        scope = value.prepared_stratum.prepared_scope
        root = scope.history_root
        dimensions = value.prepared_stratum.dimensions
        if (
            root.root_receipt_id != anchor.history_root.root_receipt_id
            or root.fingerprint != anchor.history_root.fingerprint
            or root.project_id != anchor.history_root.project_id
            or scope.selection_revision.project_id != anchor.history_root.project_id
        ):
            raise ValueError("all strata must descend from the exact anchor root")
        if dimensions.project_id != anchor.history_root.project_id:
            raise ValueError("comparison dimensions must match the anchor project")
        installations.add(dimensions.installation_id)
        providers.add(dimensions.provider)
        entries.append(_entry_for(value, checked_metric))
    if len(installations) > 1 or len(providers) > 1:
        raise ValueError("supplied strata disagree on installation or provider scope")
    entries.sort(key=lambda entry: entry.sort_key)
    selected, start, end, left_censored, shortfall, late_count = _select_window(
        entries,
        window=requested_window,
        as_of=checked_as_of,
        floor=floor,
    )
    outside_count = supplied_count - late_count - len(selected)
    runs, transitions, leading_gap, trailing_gap = _build_runs(selected)
    counts = _state_counts(selected)
    task_buckets = _bucket_summaries(selected)
    policy = RawAggregationPolicyIdentityV1()
    included_fingerprints = tuple(
        sorted(entry.stratum_fingerprint for entry in selected)
    )
    included_set = set(included_fingerprints)
    supplied_manifest = tuple(
        sorted(
            (
                RawSuppliedStratumManifestEntryV1(
                    fingerprint=entry.stratum_fingerprint,
                    disposition=(
                        RawStratumDispositionV1.LATE_SEAL
                        if entry.sealed_at > checked_as_of
                        else (
                            RawStratumDispositionV1.INCLUDED
                            if entry.stratum_fingerprint in included_set
                            else RawStratumDispositionV1.OUTSIDE_WINDOW
                        )
                    ),
                )
                for entry in entries
            ),
            key=lambda item: (item.fingerprint, item.disposition.value),
        )
    )
    result_fields: dict[str, Any] = {
        "anchor_scope": anchor,
        "anchor_prepared_scope_id": anchor.prepared_scope_id,
        "anchor_prepared_scope_fingerprint": anchor.fingerprint,
        "root_receipt_id": anchor.history_root.root_receipt_id,
        "root_receipt_fingerprint": anchor.history_root.fingerprint,
        "history_floor_at": floor,
        "installation_id": next(iter(installations)) if installations else None,
        "project_id": anchor.history_root.project_id,
        "provider": next(iter(providers)) if providers else None,
        "metric_key": checked_metric,
        "window": requested_window,
        "as_of": checked_as_of,
        "effective_window_start_at": start,
        "effective_window_end_at": end,
        "window_coverage_state": _coverage_state(
            included=len(selected),
            left_censored=left_censored,
            shortfall=shortfall,
        ),
        "floor_left_censored": left_censored,
        "last_n_shortfall": shortfall > 0,
        "last_n_shortfall_count": shortfall,
        "supplied_strata_count": supplied_count,
        "excluded_late_seal_count": late_count,
        "excluded_outside_window_count": outside_count,
        "included_revision_count": len(selected),
        "leading_identity_unavailable_count": leading_gap,
        "trailing_identity_unavailable_count": trailing_gap,
        "ordered_included_stratum_fingerprints": included_fingerprints,
        "ordered_supplied_stratum_manifest": supplied_manifest,
        "state_counts": counts,
        "task_buckets": task_buckets,
        "compatibility_runs": runs,
        "compatibility_transitions": transitions,
        "policy_identity": policy,
        "policy_identity_fingerprint": policy.fingerprint,
    }
    shell = SyntheticRawAggregationDraftV1.model_construct(
        aggregation_draft_id="0" * 64,
        **result_fields,
    )
    draft_id = _aggregation_draft_id(
        shell.model_dump(mode="python", exclude={"aggregation_draft_id"})
    )
    return SyntheticRawAggregationDraftV1(
        aggregation_draft_id=draft_id,
        **result_fields,
    )


def draft_repository_sealed_synthetic_raw_aggregation(
    *,
    anchor: RepositoryPreparedComparisonStratumV1,
    metric_key: str,
    window: TemporalWindowSpec,
    as_of: datetime,
    strata: tuple[RepositorySealedComparisonStratumV1, ...],
) -> RepositoryBackedSyntheticRawAggregationDraftV2:
    """Describe a caller-supplied set of repository-sealed synthetic graphs.

    This function revalidates the exact V22 receipt structures and retains
    their content-free authority commitments.  It does not prove repository
    return provenance, enumerate history, seal the output, or authorize a
    comparison, snapshot, recommendation, or product action.
    """

    if not isinstance(strata, tuple):
        raise ValueError("strata must be a bounded immutable tuple")
    supplied_count = len(strata)
    if supplied_count > MAX_SUPPLIED_STRATA:
        raise ValueError("too many supplied repository comparison strata")
    if not isinstance(anchor, RepositoryPreparedComparisonStratumV1):
        raise ValueError("anchor must be a repository prepared receipt")
    if any(
        not isinstance(value, RepositorySealedComparisonStratumV1)
        for value in strata
    ):
        raise ValueError("strata must contain only repository sealed receipts")
    checked_anchor = (
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(anchor)
    )
    requested_window = TemporalWindowSpec.model_validate(
        window.model_dump(mode="python")
    )
    checked_as_of = _utc(as_of)
    checked_metric = _safe_code(metric_key)
    root = checked_anchor.prepared_scope.history_root
    floor = root.history_floor_at
    if checked_as_of < floor:
        raise ValueError("aggregation as-of cannot predate the prospective floor")
    checked_strata = tuple(
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(value)
        for value in strata
    )
    role_sets = {
        "prepared": [
            value.prepared_receipt.prepared_stratum_id for value in checked_strata
        ],
        "sealed": [value.sealed_stratum_id for value in checked_strata],
        "run": [value.analysis_run.draft.run_id for value in checked_strata],
        "batch": [value.sealed_batch.sealed_batch_id for value in checked_strata],
        "revision": [
            value.sealed_batch.seal_draft.session_revision.revision_id
            for value in checked_strata
        ],
    }
    for role, identities in role_sets.items():
        if len(identities) != len(set(identities)):
            raise ValueError(f"duplicate {role} identity in supplied strata")
    revision_coordinates = tuple(
        (
            value.sealed_batch.seal_draft.session_revision.session_id,
            value.sealed_batch.seal_draft.session_revision.revision_ordinal,
        )
        for value in checked_strata
    )
    if len(revision_coordinates) != len(set(revision_coordinates)):
        raise ValueError("duplicate session revision coordinate in supplied strata")
    anchor_dimensions = checked_anchor.dimensions
    entries: list[_Entry] = []
    for value in checked_strata:
        prepared = value.prepared_receipt
        prepared_root = prepared.prepared_scope.history_root
        dimensions = prepared.dimensions
        if (
            prepared_root.root_receipt_id != root.root_receipt_id
            or prepared_root.fingerprint != root.fingerprint
            or prepared_root.project_id != root.project_id
            or prepared_root.history_floor_at != floor
        ):
            raise ValueError("all strata must descend from the exact anchor root")
        if (
            dimensions.project_id != anchor_dimensions.project_id
            or dimensions.installation_id != anchor_dimensions.installation_id
            or dimensions.provider is not anchor_dimensions.provider
        ):
            raise ValueError("all strata must match the exact anchor source scope")
        entries.append(_entry_for_repository_receipt(value, checked_metric))
    entries.sort(key=lambda entry: entry.sort_key)
    selected, start, end, left_censored, shortfall, late_count = _select_window(
        entries,
        window=requested_window,
        as_of=checked_as_of,
        floor=floor,
    )
    outside_count = supplied_count - late_count - len(selected)
    runs, transitions, leading_gap, trailing_gap = _build_runs(selected)
    counts = _state_counts(selected)
    task_buckets = _bucket_summaries(selected)
    policy = RawAggregationPolicyIdentityV1()
    included_fingerprints = tuple(
        sorted(entry.stratum_fingerprint for entry in selected)
    )
    included_ids = {
        entry.stratum.sealed_stratum_id
        for entry in selected
        if isinstance(entry.stratum, RepositorySealedComparisonStratumV1)
    }
    supplied_manifest = tuple(
        RepositoryBackedStratumManifestEntryV2(
            supplied_ordinal=ordinal,
            prepared_stratum_id=value.prepared_receipt.prepared_stratum_id,
            prepared_stratum_fingerprint=value.prepared_receipt.fingerprint,
            sealed_stratum_id=value.sealed_stratum_id,
            sealed_stratum_fingerprint=value.fingerprint,
            analysis_run_id=value.analysis_run.draft.run_id,
            analysis_run_authority_sha256=value.analysis_run_authority_sha256,
            sealed_batch_id=value.sealed_batch.sealed_batch_id,
            sealed_batch_sha256=value.sealed_batch_sha256,
            revision_id=value.sealed_batch.seal_draft.session_revision.revision_id,
            revision_fingerprint=(
                value.sealed_batch.seal_draft.session_revision.fingerprint
            ),
            session_id=value.sealed_batch.seal_draft.session_revision.session_id,
            revision_ordinal=(
                value.sealed_batch.seal_draft.session_revision.revision_ordinal
            ),
            effective_at=(
                value.sealed_batch.seal_draft.session_revision.effective_at
            ),
            sealed_at=value.sealed_at,
            disposition=(
                RawStratumDispositionV1.LATE_SEAL
                if value.sealed_at > checked_as_of
                else (
                    RawStratumDispositionV1.INCLUDED
                    if value.sealed_stratum_id in included_ids
                    else RawStratumDispositionV1.OUTSIDE_WINDOW
                )
            ),
        )
        for ordinal, entry in enumerate(entries)
        for value in (entry.stratum,)
        if isinstance(value, RepositorySealedComparisonStratumV1)
    )
    result_fields: dict[str, Any] = {
        "anchor": checked_anchor,
        "anchor_prepared_stratum_id": checked_anchor.prepared_stratum_id,
        "anchor_prepared_stratum_fingerprint": checked_anchor.fingerprint,
        "root_receipt_id": root.root_receipt_id,
        "root_receipt_fingerprint": root.fingerprint,
        "history_floor_at": floor,
        "installation_id": anchor_dimensions.installation_id,
        "project_id": anchor_dimensions.project_id,
        "provider": anchor_dimensions.provider,
        "metric_key": checked_metric,
        "window": requested_window,
        "as_of": checked_as_of,
        "effective_window_start_at": start,
        "effective_window_end_at": end,
        "window_coverage_state": _coverage_state(
            included=len(selected),
            left_censored=left_censored,
            shortfall=shortfall,
        ),
        "floor_left_censored": left_censored,
        "last_n_shortfall": shortfall > 0,
        "last_n_shortfall_count": shortfall,
        "supplied_strata_count": supplied_count,
        "excluded_late_seal_count": late_count,
        "excluded_outside_window_count": outside_count,
        "included_revision_count": len(selected),
        "leading_identity_unavailable_count": leading_gap,
        "trailing_identity_unavailable_count": trailing_gap,
        "ordered_included_stratum_fingerprints": included_fingerprints,
        "ordered_supplied_stratum_manifest": supplied_manifest,
        "state_counts": counts,
        "task_buckets": task_buckets,
        "compatibility_runs": runs,
        "compatibility_transitions": transitions,
        "policy_identity": policy,
        "policy_identity_fingerprint": policy.fingerprint,
    }
    shell = RepositoryBackedSyntheticRawAggregationDraftV2.model_construct(
        aggregation_draft_id="0" * 64,
        **result_fields,
    )
    draft_id = _repository_aggregation_draft_id(
        shell.model_dump(mode="python", exclude={"aggregation_draft_id"})
    )
    return RepositoryBackedSyntheticRawAggregationDraftV2(
        aggregation_draft_id=draft_id,
        **result_fields,
    )


__all__ = [
    "INTERVAL_METHOD_VERSION",
    "LAST_N_ORDER_VERSION",
    "MAX_SUPPLIED_STRATA",
    "QUANTILE_METHOD_VERSION",
    "RAW_AGGREGATION_POLICY_VERSION",
    "REPOSITORY_BACKED_SYNTHETIC_RAW_AGGREGATION_VERSION",
    "RepositoryBackedStratumManifestEntryV2",
    "RepositoryBackedSyntheticRawAggregationDraftV2",
    "RawAggregationPolicyIdentityV1",
    "RawAggregationPopulationStateV1",
    "RawCompatibilityRunV1",
    "RawCompatibilityTransitionV1",
    "RawCountExposureAggregateV1",
    "RawDistributionAggregateV1",
    "RawFractionAggregateV1",
    "RawMatchReadinessV1",
    "RawSampledProportionAggregateV1",
    "RawStateCountsV1",
    "RawTaskBucketAggregateV1",
    "RawTaskBucketSummaryV1",
    "RawTransitionKindV1",
    "RawWindowCoverageStateV1",
    "SYNTHETIC_RAW_AGGREGATION_VERSION",
    "SyntheticRawAggregationDraftV1",
    "draft_repository_sealed_synthetic_raw_aggregation",
    "draft_synthetic_raw_aggregation",
]
