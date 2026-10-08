"""Content-free aggregation of immutable selected-session quality snapshots.

This module is deliberately provider-neutral and read-only.  It never reads a
provider, persists a result, or accepts transcript content.  Fractions are
combined only as ``sum(numerator) / sum(denominator)`` within an exact
provenance cohort.  Incompatible cohorts remain visible and block the combined
value instead of being averaged, selected, or silently discarded.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
import re

from pydantic import Field, field_validator, model_validator

from ...domain import (
    DataTier,
    MetricSource,
    Provider,
    SAFE_VERSION_PATTERN,
    StrictModel,
)
from ..persistence import (
    MetricValueState,
    SessionAnalysisAggregationResultRecord,
    SessionAnalysisAggregationSnapshotRecord,
    SessionAnalysisRunRepository,
    SessionMetricAggregation,
    SessionMetricDirection,
    SessionMetricScopeState,
)
from .text_baselines import (
    DEFAULT_TEXT_METRIC_PACK_KEY,
    DEFAULT_TEXT_METRIC_PACK_VERSION,
    TEXT_METRIC_DEFINITIONS,
)
from .text_contracts import (
    TEXT_METRIC_SCHEMA_VERSION,
    TextMetricDefinition,
)
from .text_analysis_presets import STANDARD_ENGINEERING_V1


_PSEUDONYM = re.compile(r"^[a-f0-9]{64}$")


def _safe_id(value: str) -> str:
    if not _PSEUDONYM.fullmatch(value):
        raise ValueError("session selectors must be 64-character safe identifiers")
    return value


def _safe_code(value: str | None) -> str | None:
    if value is not None and not SAFE_VERSION_PATTERN.fullmatch(value):
        raise ValueError("compatibility provenance must use safe identifiers")
    return value


def _coverage(observed: int, eligible: int) -> float:
    return 0.0 if eligible == 0 else observed / eligible


class SessionQualityCompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    NO_RESULTS = "no_results"


class SessionQualityAggregateState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    ABSTAINED = "abstained"
    EXECUTION_ERROR = "execution_error"
    INCOMPATIBLE = "incompatible"


class SessionQualityIntegrityState(StrEnum):
    VALID = "valid"
    INCOMPATIBLE = "incompatible"


class SessionQualitySelection(StrictModel):
    """A bounded content-free selector; duplicate sessions are never weighted twice."""

    session_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    _validate_session_ids = field_validator("session_ids")(
        lambda values: tuple(_safe_id(value) for value in values)
    )

    @model_validator(mode="after")
    def reject_duplicates(self) -> SessionQualitySelection:
        if len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError("session selectors cannot contain duplicates")
        return self


class SessionQualityStateCounts(StrictModel):
    known: int = Field(ge=0)
    unknown: int = Field(ge=0)
    not_applicable: int = Field(ge=0)
    abstained: int = Field(ge=0)
    execution_error: int = Field(ge=0)

    @property
    def total(self) -> int:
        return (
            self.known
            + self.unknown
            + self.not_applicable
            + self.abstained
            + self.execution_error
        )


class SessionQualityCompatibilityKey(StrictModel):
    """Every provenance field that must match before fractions may combine."""

    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_scope_state: SessionMetricScopeState
    data_tier: DataTier
    consent_policy_version: str
    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    content_schema_version: str
    metric_engine_version: str
    redactor_version: str
    local_only: bool
    metric_key: str
    metric_version: int = Field(ge=1)
    metric_unit: str
    metric_source: MetricSource
    metric_direction: SessionMetricDirection
    aggregation_method: SessionMetricAggregation
    metric_schema_version: int = Field(ge=1)
    algorithm_id: str
    algorithm_version: str
    model_id: str | None = None
    model_revision: str | None = None
    model_license: str | None = None
    tokenizer_id: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None

    _validate_codes = field_validator(
        "analysis_profile_key",
        "metric_pack_key",
        "consent_policy_version",
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "metric_engine_version",
        "redactor_version",
        "metric_key",
        "metric_unit",
        "algorithm_id",
        "algorithm_version",
        "model_id",
        "model_revision",
        "model_license",
        "tokenizer_id",
        "prompt_version",
        "rubric_version",
    )(_safe_code)


class SessionQualityCompatibilityCohort(StrictModel):
    """One exact provenance cohort, retained even when the selection is mixed."""

    key: SessionQualityCompatibilityKey
    result_count: int = Field(ge=1)
    state_counts: SessionQualityStateCounts
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    numeric_value: float | None = Field(default=None, ge=0, le=1)
    analyzable_observed_count: int = Field(ge=0)
    analyzable_eligible_count: int = Field(ge=0)
    analyzable_coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_cohort(self) -> SessionQualityCompatibilityCohort:
        if self.state_counts.total != self.result_count:
            raise ValueError("cohort state counts must equal its result count")
        if self.analyzable_observed_count > self.analyzable_eligible_count:
            raise ValueError("analyzable observed count cannot exceed eligible count")
        expected_coverage = _coverage(
            self.analyzable_observed_count,
            self.analyzable_eligible_count,
        )
        if abs(self.analyzable_coverage - expected_coverage) > 1e-9:
            raise ValueError("coverage must use summed observed and eligible counts")

        has_fraction = (
            self.fraction_numerator is not None
            and self.fraction_denominator is not None
        )
        if (self.fraction_numerator is None) != (self.fraction_denominator is None):
            raise ValueError("aggregate fraction fields must be supplied together")
        if self.state_counts.known == 0:
            if has_fraction or self.numeric_value is not None:
                raise ValueError("a cohort without known results cannot claim a value")
        else:
            if not has_fraction or self.numeric_value is None:
                raise ValueError("known cohort results require a ratio-of-sums value")
            if self.fraction_numerator > self.fraction_denominator:
                raise ValueError("aggregate numerator cannot exceed denominator")
            expected_value = self.fraction_numerator / self.fraction_denominator
            if abs(self.numeric_value - expected_value) > 1e-9:
                raise ValueError("cohort value must equal ratio-of-sums")
        return self


class SessionQualityMetricAggregate(StrictModel):
    metric_key: str
    metric_version: int = Field(ge=1)
    metric_unit: str
    metric_direction: SessionMetricDirection
    aggregation_method: SessionMetricAggregation
    compatibility_state: SessionQualityCompatibilityState
    aggregate_state: SessionQualityAggregateState
    blocked_reason_codes: tuple[str, ...] = ()
    selected_session_count: int = Field(ge=1, le=100)
    completed_run_count: int = Field(ge=0)
    missing_run_count: int = Field(ge=0)
    not_selected_run_count: int = Field(ge=0)
    unknown_scope_run_count: int = Field(
        ge=0,
        description=(
            "Orthogonal count of completed legacy runs whose selected metric "
            "scope cannot be recovered; these runs may also be present or missing."
        ),
    )
    present_result_count: int = Field(ge=0)
    missing_result_count: int = Field(ge=0)
    invalid_result_session_count: int = Field(ge=0)
    invalid_result_record_count: int = Field(ge=0)
    state_counts: SessionQualityStateCounts
    compatibility_cohorts: tuple[SessionQualityCompatibilityCohort, ...] = ()
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    numeric_value: float | None = Field(default=None, ge=0, le=1)
    analyzable_observed_count: int | None = Field(default=None, ge=0)
    analyzable_eligible_count: int | None = Field(default=None, ge=0)
    analyzable_coverage: float | None = Field(default=None, ge=0, le=1)

    _validate_codes = field_validator("metric_key", "metric_unit")(_safe_code)
    _validate_reasons = field_validator("blocked_reason_codes")(
        lambda values: tuple(_safe_code(value) for value in values)
    )

    @model_validator(mode="after")
    def validate_metric_aggregate(self) -> SessionQualityMetricAggregate:
        if self.selected_session_count != (
            self.completed_run_count + self.missing_run_count
        ):
            raise ValueError("every selected session must be completed or missing")
        if self.unknown_scope_run_count > self.completed_run_count:
            raise ValueError("unknown metric scope cannot exceed completed runs")
        if self.completed_run_count != (
            self.present_result_count
            + self.not_selected_run_count
            + self.missing_result_count
            + self.invalid_result_session_count
        ):
            raise ValueError(
                "every completed run must contribute one present, not-selected, missing, or invalid result"
            )
        if self.present_result_count != self.state_counts.total:
            raise ValueError("metric state counts must equal present result count")
        if sum(cohort.result_count for cohort in self.compatibility_cohorts) != (
            self.present_result_count
        ):
            raise ValueError("compatibility cohorts must preserve every valid result")

        has_fraction = (
            self.fraction_numerator is not None
            and self.fraction_denominator is not None
        )
        if (self.fraction_numerator is None) != (self.fraction_denominator is None):
            raise ValueError("aggregate fraction fields must be supplied together")
        has_coverage = all(
            value is not None
            for value in (
                self.analyzable_observed_count,
                self.analyzable_eligible_count,
                self.analyzable_coverage,
            )
        )
        if any(
            value is not None
            for value in (
                self.analyzable_observed_count,
                self.analyzable_eligible_count,
                self.analyzable_coverage,
            )
        ) != has_coverage:
            raise ValueError("aggregate coverage fields must be supplied together")
        if (
            self.compatibility_state
            is not SessionQualityCompatibilityState.INCOMPATIBLE
            and self.blocked_reason_codes
        ):
            raise ValueError("only incompatible metrics may contain block reasons")

        if self.compatibility_state is SessionQualityCompatibilityState.NO_RESULTS:
            if self.compatibility_cohorts or self.present_result_count != 0:
                raise ValueError("no-results metrics cannot contain cohorts")
            if self.aggregate_state is not SessionQualityAggregateState.UNKNOWN:
                raise ValueError("a metric without results remains unknown")
        elif self.compatibility_state is SessionQualityCompatibilityState.COMPATIBLE:
            if len(self.compatibility_cohorts) != 1:
                raise ValueError("compatible metrics require exactly one cohort")
            cohort = self.compatibility_cohorts[0]
            if not has_coverage:
                raise ValueError("compatible metrics preserve analyzable coverage")
            if (
                self.analyzable_observed_count != cohort.analyzable_observed_count
                or self.analyzable_eligible_count != cohort.analyzable_eligible_count
                or abs(self.analyzable_coverage - cohort.analyzable_coverage) > 1e-9
            ):
                raise ValueError("compatible coverage must equal its exact cohort")
            if self.aggregate_state is SessionQualityAggregateState.KNOWN:
                if not has_fraction or self.numeric_value is None:
                    raise ValueError("known compatible metrics require a value")
                if (
                    self.fraction_numerator != cohort.fraction_numerator
                    or self.fraction_denominator != cohort.fraction_denominator
                    or abs(self.numeric_value - cohort.numeric_value) > 1e-9
                ):
                    raise ValueError("combined value must equal the exact cohort value")
            elif has_fraction or self.numeric_value is not None:
                raise ValueError("non-known aggregates cannot claim a value")
        else:
            if self.aggregate_state is not SessionQualityAggregateState.INCOMPATIBLE:
                raise ValueError("incompatible provenance must block the aggregate")
            if has_fraction or self.numeric_value is not None or has_coverage:
                raise ValueError("incompatible cohorts cannot be combined")
            if not self.blocked_reason_codes:
                raise ValueError("incompatible metrics require a safe reason code")

        if self.aggregate_state is SessionQualityAggregateState.KNOWN:
            if self.state_counts.known == 0:
                raise ValueError("known aggregate state requires known session results")
        elif self.aggregate_state is not SessionQualityAggregateState.INCOMPATIBLE:
            if has_fraction or self.numeric_value is not None:
                raise ValueError("unknown qualitative states cannot claim zero or a value")
        return self


class SessionQualityAggregate(StrictModel):
    """Content-free selected-session projection; selected IDs are intentionally absent."""

    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_schema_version: int = Field(ge=1)
    selected_session_count: int = Field(ge=1, le=100)
    completed_run_count: int = Field(ge=0)
    missing_run_count: int = Field(ge=0)
    integrity_state: SessionQualityIntegrityState
    unexpected_result_record_count: int = Field(ge=0)
    duplicate_result_record_count: int = Field(ge=0)
    metrics: tuple[SessionQualityMetricAggregate, ...]

    _validate_plan_codes = field_validator(
        "analysis_profile_key",
        "metric_pack_key",
    )(_safe_code)

    @model_validator(mode="after")
    def validate_selection(self) -> SessionQualityAggregate:
        if self.selected_session_count != (
            self.completed_run_count + self.missing_run_count
        ):
            raise ValueError("every selected session must contribute exactly once")
        metric_keys = tuple(metric.metric_key for metric in self.metrics)
        if len(set(metric_keys)) != len(metric_keys):
            raise ValueError("aggregate metrics cannot contain duplicate keys")
        incompatible = bool(
            self.unexpected_result_record_count
            or self.duplicate_result_record_count
            or any(
                metric.compatibility_state
                is SessionQualityCompatibilityState.INCOMPATIBLE
                for metric in self.metrics
            )
        )
        if incompatible != (
            self.integrity_state is SessionQualityIntegrityState.INCOMPATIBLE
        ):
            raise ValueError("selection integrity must reflect every incompatibility")
        return self


class SessionQualityAggregationService:
    """Aggregate latest immutable results without provider access or persistence."""

    def __init__(
        self,
        repository: SessionAnalysisRunRepository,
        *,
        definitions: tuple[TextMetricDefinition, ...] = TEXT_METRIC_DEFINITIONS,
        analysis_profile_key: str = STANDARD_ENGINEERING_V1.analysis_profile_key,
        analysis_profile_version: int = STANDARD_ENGINEERING_V1.analysis_profile_version,
        metric_pack_key: str = DEFAULT_TEXT_METRIC_PACK_KEY,
        metric_pack_version: int = DEFAULT_TEXT_METRIC_PACK_VERSION,
        metric_schema_version: int = TEXT_METRIC_SCHEMA_VERSION,
    ) -> None:
        if not definitions:
            raise ValueError("quality aggregation requires at least one definition")
        identities = tuple((item.key, item.version) for item in definitions)
        if len(set(identities)) != len(identities):
            raise ValueError("quality metric definitions cannot contain duplicates")
        if (
            not SAFE_VERSION_PATTERN.fullmatch(analysis_profile_key)
            or not SAFE_VERSION_PATTERN.fullmatch(metric_pack_key)
        ):
            raise ValueError("profile and metric pack keys must be safe identifiers")
        if (
            analysis_profile_version < 1
            or metric_pack_version < 1
            or metric_schema_version < 1
        ):
            raise ValueError("profile, metric pack and schema versions begin at one")
        self._repository = repository
        self._definitions = definitions
        self._definition_by_key = {item.key: item for item in definitions}
        self._analysis_profile_key = analysis_profile_key
        self._analysis_profile_version = analysis_profile_version
        self._metric_pack_key = metric_pack_key
        self._metric_pack_version = metric_pack_version
        self._metric_schema_version = metric_schema_version

    def aggregate(
        self, selection: SessionQualitySelection
    ) -> SessionQualityAggregate:
        latest = self._repository.get_latest_completed_for_aggregation(
            selection.session_ids,
            analysis_profile_key=self._analysis_profile_key,
            analysis_profile_version=self._analysis_profile_version,
            metric_pack_key=self._metric_pack_key,
            metric_pack_version=self._metric_pack_version,
        )
        returned_ids = tuple(snapshot.session_id for snapshot in latest)
        if (
            len(set(returned_ids)) != len(returned_ids)
            or not set(returned_ids).issubset(selection.session_ids)
        ):
            raise ValueError("aggregation repository returned an invalid selection")
        missing_run_count = len(selection.session_ids) - len(latest)
        unexpected_result_count = 0
        duplicate_result_count = 0
        for snapshot in latest:
            unexpected_result_count += sum(
                result.observation.key not in self._definition_by_key
                for result in snapshot.results
            )

        completed_run_count = len(latest)
        metrics: list[SessionQualityMetricAggregate] = []
        for definition in self._definitions:
            aggregate, duplicates = self._aggregate_metric(
                definition=definition,
                latest=tuple(latest),
                selected_session_count=len(selection.session_ids),
                missing_run_count=missing_run_count,
            )
            duplicate_result_count += duplicates
            metrics.append(aggregate)

        integrity = (
            SessionQualityIntegrityState.INCOMPATIBLE
            if unexpected_result_count
            or duplicate_result_count
            or any(
                metric.compatibility_state
                is SessionQualityCompatibilityState.INCOMPATIBLE
                for metric in metrics
            )
            else SessionQualityIntegrityState.VALID
        )
        return SessionQualityAggregate(
            analysis_profile_key=self._analysis_profile_key,
            analysis_profile_version=self._analysis_profile_version,
            metric_pack_key=self._metric_pack_key,
            metric_pack_version=self._metric_pack_version,
            metric_schema_version=self._metric_schema_version,
            selected_session_count=len(selection.session_ids),
            completed_run_count=completed_run_count,
            missing_run_count=missing_run_count,
            integrity_state=integrity,
            unexpected_result_record_count=unexpected_result_count,
            duplicate_result_record_count=duplicate_result_count,
            metrics=tuple(metrics),
        )

    def _aggregate_metric(
        self,
        *,
        definition: TextMetricDefinition,
        latest: tuple[SessionAnalysisAggregationSnapshotRecord, ...],
        selected_session_count: int,
        missing_run_count: int,
    ) -> tuple[SessionQualityMetricAggregate, int]:
        valid: list[
            tuple[
                SessionAnalysisAggregationSnapshotRecord,
                SessionAnalysisAggregationResultRecord,
            ]
        ] = []
        missing_result_count = 0
        not_selected_run_count = 0
        unknown_scope_run_count = sum(
            snapshot.metric_scope_state is SessionMetricScopeState.LEGACY_UNKNOWN
            for snapshot in latest
        )
        invalid_result_session_count = 0
        invalid_result_record_count = 0

        for snapshot in latest:
            if (
                snapshot.metric_scope_state is SessionMetricScopeState.EXACT
                and definition.key not in snapshot.selected_metric_keys
            ):
                not_selected_run_count += 1
                continue
            matches = tuple(
                result
                for result in snapshot.results
                if result.observation.key == definition.key
            )
            if not matches:
                missing_result_count += 1
            elif len(matches) == 1:
                valid.append((snapshot, matches[0]))
            else:
                invalid_result_session_count += 1
                invalid_result_record_count += len(matches)

        state_counts = _state_counts(tuple(result for _, result in valid))
        grouped: dict[
            SessionQualityCompatibilityKey,
            list[SessionAnalysisAggregationResultRecord],
        ] = defaultdict(list)
        for snapshot, result in valid:
            grouped[_compatibility_key(snapshot, result)].append(result)
        cohorts = tuple(
            _cohort(key, tuple(grouped[key]))
            for key in sorted(grouped, key=_compatibility_sort_key)
        )

        reasons: list[str] = []
        if invalid_result_session_count:
            reasons.append("duplicate_metric_records")
        if unknown_scope_run_count:
            reasons.append("metric_scope_unknown")
        if any(
            not self._matches_expected_contract(definition, cohort.key)
            for cohort in cohorts
        ):
            reasons.append("metric_contract_mismatch")
        if len(cohorts) > 1:
            reasons.append("mixed_provenance")

        if reasons:
            compatibility = SessionQualityCompatibilityState.INCOMPATIBLE
            aggregate_state = SessionQualityAggregateState.INCOMPATIBLE
            top = {}
        elif not cohorts:
            compatibility = SessionQualityCompatibilityState.NO_RESULTS
            aggregate_state = SessionQualityAggregateState.UNKNOWN
            top = {}
        else:
            compatibility = SessionQualityCompatibilityState.COMPATIBLE
            aggregate_state = _aggregate_state(
                state_counts=state_counts,
                missing_run_count=missing_run_count,
                missing_result_count=missing_result_count,
            )
            cohort = cohorts[0]
            top = {
                "analyzable_observed_count": cohort.analyzable_observed_count,
                "analyzable_eligible_count": cohort.analyzable_eligible_count,
                "analyzable_coverage": cohort.analyzable_coverage,
            }
            if aggregate_state is SessionQualityAggregateState.KNOWN:
                top.update(
                    fraction_numerator=cohort.fraction_numerator,
                    fraction_denominator=cohort.fraction_denominator,
                    numeric_value=cohort.numeric_value,
                )

        return (
            SessionQualityMetricAggregate(
                metric_key=definition.key,
                metric_version=definition.version,
                metric_unit=definition.unit,
                metric_direction=SessionMetricDirection(definition.direction.value),
                aggregation_method=SessionMetricAggregation(
                    definition.aggregation_method.value
                ),
                compatibility_state=compatibility,
                aggregate_state=aggregate_state,
                blocked_reason_codes=tuple(reasons),
                selected_session_count=selected_session_count,
                completed_run_count=len(latest),
                missing_run_count=missing_run_count,
                not_selected_run_count=not_selected_run_count,
                unknown_scope_run_count=unknown_scope_run_count,
                present_result_count=len(valid),
                missing_result_count=missing_result_count,
                invalid_result_session_count=invalid_result_session_count,
                invalid_result_record_count=invalid_result_record_count,
                state_counts=state_counts,
                compatibility_cohorts=cohorts,
                **top,
            ),
            invalid_result_record_count,
        )

    def _matches_expected_contract(
        self,
        definition: TextMetricDefinition,
        key: SessionQualityCompatibilityKey,
    ) -> bool:
        return (
            key.analysis_profile_key == self._analysis_profile_key
            and key.analysis_profile_version == self._analysis_profile_version
            and key.metric_pack_key == self._metric_pack_key
            and key.metric_pack_version == self._metric_pack_version
            and key.metric_scope_state is SessionMetricScopeState.EXACT
            and key.metric_key == definition.key
            and key.metric_version == definition.version
            and key.metric_unit == definition.unit
            and key.metric_direction.value == definition.direction.value
            and key.aggregation_method.value == definition.aggregation_method.value
            and key.metric_schema_version == self._metric_schema_version
            and key.data_tier is DataTier.REDACTED_CONTENT
            and key.local_only
        )


def _compatibility_key(
    snapshot: SessionAnalysisAggregationSnapshotRecord,
    result: SessionAnalysisAggregationResultRecord,
) -> SessionQualityCompatibilityKey:
    observation = result.observation
    return SessionQualityCompatibilityKey(
        analysis_profile_key=snapshot.analysis_profile_key,
        analysis_profile_version=snapshot.analysis_profile_version,
        metric_pack_key=snapshot.metric_pack_key,
        metric_pack_version=snapshot.metric_pack_version,
        metric_scope_state=snapshot.metric_scope_state,
        data_tier=snapshot.data_tier,
        consent_policy_version=snapshot.consent_policy_version,
        provider=snapshot.provider,
        provider_version=snapshot.provider_version,
        adapter_version=snapshot.adapter_version,
        source_schema_version=snapshot.source_schema_version,
        content_schema_version=snapshot.content_schema_version,
        metric_engine_version=snapshot.metric_engine_version,
        redactor_version=snapshot.redactor_version,
        local_only=snapshot.local_only,
        metric_key=observation.key,
        metric_version=observation.version,
        metric_unit=observation.unit,
        metric_source=observation.source,
        metric_direction=result.direction,
        aggregation_method=result.aggregation_method,
        metric_schema_version=result.metric_schema_version,
        algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version,
        model_id=result.model_id,
        model_revision=result.model_revision,
        model_license=result.model_license,
        tokenizer_id=result.tokenizer_id,
        prompt_version=result.prompt_version,
        rubric_version=result.rubric_version,
    )


def _compatibility_sort_key(key: SessionQualityCompatibilityKey) -> tuple[str, ...]:
    values = (
        key.analysis_profile_key,
        str(key.analysis_profile_version),
        key.metric_pack_key,
        str(key.metric_pack_version),
        key.metric_scope_state.value,
        key.data_tier.value,
        key.consent_policy_version,
        key.provider.value,
        key.provider_version,
        key.adapter_version,
        key.source_schema_version,
        key.content_schema_version,
        key.metric_engine_version,
        key.redactor_version,
        str(key.local_only),
        key.metric_key,
        str(key.metric_version),
        key.metric_unit,
        key.metric_source.value,
        key.metric_direction.value,
        key.aggregation_method.value,
        str(key.metric_schema_version),
        key.algorithm_id,
        key.algorithm_version,
        key.model_id or "",
        key.model_revision or "",
        key.model_license or "",
        key.tokenizer_id or "",
        key.prompt_version or "",
        key.rubric_version or "",
    )
    return values


def _cohort(
    key: SessionQualityCompatibilityKey,
    results: tuple[SessionAnalysisAggregationResultRecord, ...],
) -> SessionQualityCompatibilityCohort:
    counts = _state_counts(results)
    known = tuple(
        result for result in results if result.value_state is MetricValueState.KNOWN
    )
    numerator = (
        None
        if not known
        else sum(
            result.fraction_numerator
            for result in known
            if result.fraction_numerator is not None
        )
    )
    denominator = (
        None
        if not known
        else sum(
            result.fraction_denominator
            for result in known
            if result.fraction_denominator is not None
        )
    )
    numeric_value = None if denominator is None else numerator / denominator
    observed = sum(result.observation.observed_count for result in results)
    eligible = sum(result.observation.eligible_count for result in results)
    return SessionQualityCompatibilityCohort(
        key=key,
        result_count=len(results),
        state_counts=counts,
        fraction_numerator=numerator,
        fraction_denominator=denominator,
        numeric_value=numeric_value,
        analyzable_observed_count=observed,
        analyzable_eligible_count=eligible,
        analyzable_coverage=_coverage(observed, eligible),
    )


def _state_counts(
    results: tuple[SessionAnalysisAggregationResultRecord, ...],
) -> SessionQualityStateCounts:
    counts = {state: 0 for state in MetricValueState}
    for result in results:
        counts[result.value_state] += 1
    return SessionQualityStateCounts(
        known=counts[MetricValueState.KNOWN],
        unknown=counts[MetricValueState.UNKNOWN],
        not_applicable=counts[MetricValueState.NOT_APPLICABLE],
        abstained=counts[MetricValueState.ABSTAINED],
        execution_error=counts[MetricValueState.EXECUTION_ERROR],
    )


def _aggregate_state(
    *,
    state_counts: SessionQualityStateCounts,
    missing_run_count: int,
    missing_result_count: int,
) -> SessionQualityAggregateState:
    if state_counts.known:
        return SessionQualityAggregateState.KNOWN
    if missing_run_count or missing_result_count or state_counts.total == 0:
        return SessionQualityAggregateState.UNKNOWN
    populated = tuple(
        state
        for state, count in (
            (SessionQualityAggregateState.UNKNOWN, state_counts.unknown),
            (
                SessionQualityAggregateState.NOT_APPLICABLE,
                state_counts.not_applicable,
            ),
            (SessionQualityAggregateState.ABSTAINED, state_counts.abstained),
            (
                SessionQualityAggregateState.EXECUTION_ERROR,
                state_counts.execution_error,
            ),
        )
        if count
    )
    return populated[0] if len(populated) == 1 else SessionQualityAggregateState.UNKNOWN
