"""Content-free quality aggregation over complete indexed project selections.

This use case resolves only the application's existing safe index.  It has no
provider port and therefore cannot refresh, enrich, or read provider history.
The first contract intentionally exposes one estimand and one aggregation
method; future weighting modes must be implemented as distinct, versioned
contracts rather than inferred from this response.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_METRIC_TEXT_PATTERN, StrictModel
from ..persistence import (
    SessionAnalysisRunRepository,
    SessionMetricAggregation,
    SessionMetricDirection,
)
from .session_quality_aggregation import (
    SessionQualityAggregate,
    SessionQualityAggregationService,
    SessionQualityAggregateState,
    SessionQualityCompatibilityState,
    SessionQualityIntegrityState,
    SessionQualitySelection,
    SessionQualityStateCounts,
)


MAX_PROJECT_QUALITY_PROJECTS = 25
MAX_PROJECT_QUALITY_SESSIONS = 100


def _safe_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    for value in values:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("selectors must be 64-character safe identifiers")
    return values


def _public_code(value: str) -> str:
    if SAFE_METRIC_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("public aggregate codes must use a path-free grammar")
    return value


def _compatibility_fingerprint(key: StrictModel) -> str:
    """Hash exact delegated provenance without serializing its raw values."""

    payload = json.dumps(
        key.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class ProjectQualitySelectionMode(StrEnum):
    ALL_ANALYZED_WORK = "all_analyzed_work"


class ProjectQualityEstimand(StrEnum):
    PER_ELIGIBLE_OPPORTUNITY = "per_eligible_opportunity"


class ProjectQualityAggregationError(RuntimeError):
    """Sanitized base error that never carries selectors or persistence data."""

    code = "project_quality_aggregation_unavailable"


class ProjectQualitySelectionIncompleteError(ProjectQualityAggregationError):
    code = "project_quality_selection_incomplete"


class ProjectQualitySelectionLimitError(ProjectQualityAggregationError):
    code = "project_quality_selection_limit"


class IndexedProjectSessions(StrictModel):
    """Internal complete resolution; identifiers never cross the HTTP response."""

    selected_project_count: int = Field(
        ge=1,
        le=MAX_PROJECT_QUALITY_PROJECTS,
    )
    session_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PROJECT_QUALITY_SESSIONS,
    )

    _validate_session_ids = field_validator("session_ids")(_safe_ids)

    @model_validator(mode="after")
    def reject_duplicate_sessions(self) -> IndexedProjectSessions:
        if len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError("resolved sessions cannot contain duplicates")
        return self


class IndexedProjectSessionResolver(Protocol):
    """Open one SQLite snapshot for scope resolution and metric aggregation."""

    def open_indexed_project_quality_snapshot(
        self,
        project_ids: tuple[str, ...],
        *,
        max_sessions: int,
    ) -> AbstractContextManager[IndexedProjectQualitySnapshot]: ...


@dataclass(frozen=True, slots=True)
class IndexedProjectQualitySnapshot:
    resolution: IndexedProjectSessions
    repository: SessionAnalysisRunRepository


def _selection_fingerprint(session_ids: tuple[str, ...]) -> str:
    payload = b"".join(
        len(value).to_bytes(2, "big") + value.encode("ascii")
        for value in sorted(session_ids)
    )
    return hashlib.sha256(payload).hexdigest()


class SessionQualityAggregationReceipt(StrictModel):
    selection_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
    )
    aggregate: SessionQualityAggregate


class SessionQualityAggregator(Protocol):
    def aggregate(
        self,
        selection: SessionQualitySelection,
    ) -> SessionQualityAggregationReceipt: ...


class SessionQualityAggregatorFactory(Protocol):
    def __call__(
        self,
        repository: SessionAnalysisRunRepository,
    ) -> SessionQualityAggregator: ...


class FingerprintedSessionQualityAggregator:
    """Attach an internal exact-selection receipt to the trusted core result."""

    def __init__(self, core: SessionQualityAggregationService) -> None:
        self._core = core

    def aggregate(
        self,
        selection: SessionQualitySelection,
    ) -> SessionQualityAggregationReceipt:
        return SessionQualityAggregationReceipt(
            selection_fingerprint=_selection_fingerprint(selection.session_ids),
            aggregate=self._core.aggregate(selection),
        )


class ProjectQualitySelection(StrictModel):
    project_ids: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_PROJECT_QUALITY_PROJECTS,
    )
    selection_mode: ProjectQualitySelectionMode = (
        ProjectQualitySelectionMode.ALL_ANALYZED_WORK
    )

    _validate_project_ids = field_validator("project_ids")(_safe_ids)

    @model_validator(mode="after")
    def reject_duplicate_projects(self) -> ProjectQualitySelection:
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("project selectors cannot contain duplicates")
        return self


class ProjectQualityCompatibilityCohort(StrictModel):
    """Path-free public projection of one exact core compatibility cohort."""

    compatibility_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
    )
    result_count: int = Field(ge=1)
    state_counts: SessionQualityStateCounts
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    numeric_value: float | None = Field(default=None, ge=0, le=1)
    analyzable_observed_count: int = Field(ge=0)
    analyzable_eligible_count: int = Field(ge=0)
    analyzable_coverage: float = Field(ge=0, le=1)


class ProjectQualityMetricAggregate(StrictModel):
    """Core metric outcome with raw compatibility provenance removed."""

    metric_key: str
    metric_version: int = Field(ge=1)
    metric_unit: str
    metric_direction: SessionMetricDirection
    aggregation_method: SessionMetricAggregation
    compatibility_state: SessionQualityCompatibilityState
    aggregate_state: SessionQualityAggregateState
    blocked_reason_codes: tuple[str, ...] = ()
    selected_session_count: int = Field(ge=1, le=MAX_PROJECT_QUALITY_SESSIONS)
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
    compatibility_cohorts: tuple[ProjectQualityCompatibilityCohort, ...] = ()
    fraction_numerator: int | None = Field(default=None, ge=0)
    fraction_denominator: int | None = Field(default=None, ge=1)
    numeric_value: float | None = Field(default=None, ge=0, le=1)
    analyzable_observed_count: int | None = Field(default=None, ge=0)
    analyzable_eligible_count: int | None = Field(default=None, ge=0)
    analyzable_coverage: float | None = Field(default=None, ge=0, le=1)

    _validate_codes = field_validator("metric_key", "metric_unit")(_public_code)
    _validate_reasons = field_validator("blocked_reason_codes")(
        lambda values: tuple(_public_code(value) for value in values)
    )

    @model_validator(mode="after")
    def validate_scope_counts(self) -> ProjectQualityMetricAggregate:
        if self.unknown_scope_run_count > self.completed_run_count:
            raise ValueError("unknown metric scope cannot exceed completed runs")
        if self.completed_run_count != (
            self.present_result_count
            + self.not_selected_run_count
            + self.missing_result_count
            + self.invalid_result_session_count
        ):
            raise ValueError("project metric run counts must preserve all completed runs")
        return self


class ProjectSessionQualityAggregate(StrictModel):
    """Path-free public mirror of the core selection-level outcome."""

    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    metric_schema_version: int = Field(ge=1)
    selected_session_count: int = Field(ge=1, le=MAX_PROJECT_QUALITY_SESSIONS)
    completed_run_count: int = Field(ge=0)
    missing_run_count: int = Field(ge=0)
    integrity_state: SessionQualityIntegrityState
    unexpected_result_record_count: int = Field(ge=0)
    duplicate_result_record_count: int = Field(ge=0)
    metrics: tuple[ProjectQualityMetricAggregate, ...]

    _validate_codes = field_validator(
        "analysis_profile_key",
        "metric_pack_key",
    )(_public_code)


def _public_session_quality(
    aggregate: SessionQualityAggregate,
) -> ProjectSessionQualityAggregate:
    metrics: list[ProjectQualityMetricAggregate] = []
    for metric in aggregate.metrics:
        cohorts = tuple(
            ProjectQualityCompatibilityCohort(
                **cohort.model_dump(exclude={"key"}, mode="python"),
                compatibility_fingerprint=_compatibility_fingerprint(cohort.key),
            )
            for cohort in metric.compatibility_cohorts
        )
        metrics.append(
            ProjectQualityMetricAggregate(
                **metric.model_dump(
                    exclude={"compatibility_cohorts"},
                    mode="python",
                ),
                compatibility_cohorts=cohorts,
            )
        )
    return ProjectSessionQualityAggregate(
        **aggregate.model_dump(exclude={"metrics"}, mode="python"),
        metrics=tuple(metrics),
    )


class ProjectQualityAggregate(StrictModel):
    """Identifier-free wrapper around the existing compatibility-safe aggregate."""

    selection_mode: ProjectQualitySelectionMode
    estimand: ProjectQualityEstimand
    aggregation_method: SessionMetricAggregation
    selected_project_count: int = Field(
        ge=1,
        le=MAX_PROJECT_QUALITY_PROJECTS,
    )
    session_quality: ProjectSessionQualityAggregate

    @model_validator(mode="after")
    def enforce_first_slice(self) -> ProjectQualityAggregate:
        if self.selection_mode is not ProjectQualitySelectionMode.ALL_ANALYZED_WORK:
            raise ValueError("unsupported project quality selection mode")
        if self.estimand is not ProjectQualityEstimand.PER_ELIGIBLE_OPPORTUNITY:
            raise ValueError("unsupported project quality estimand")
        if self.aggregation_method is not SessionMetricAggregation.RATIO_OF_SUMS:
            raise ValueError("unsupported project quality aggregation method")
        return self


class ProjectQualityAggregationService:
    """Resolve a complete safe-index scope, then reuse the immutable core."""

    def __init__(
        self,
        resolver: IndexedProjectSessionResolver,
        session_quality_factory: SessionQualityAggregatorFactory,
    ) -> None:
        self._resolver = resolver
        self._session_quality_factory = session_quality_factory

    def aggregate(
        self,
        selection: ProjectQualitySelection,
    ) -> ProjectQualityAggregate:
        with self._resolver.open_indexed_project_quality_snapshot(
            selection.project_ids,
            max_sessions=MAX_PROJECT_QUALITY_SESSIONS,
        ) as snapshot:
            resolved = snapshot.resolution
            if resolved.selected_project_count != len(selection.project_ids):
                raise ProjectQualitySelectionIncompleteError(
                    ProjectQualitySelectionIncompleteError.code
                )
            session_selection = SessionQualitySelection(
                session_ids=resolved.session_ids
            )
            receipt = self._session_quality_factory(snapshot.repository).aggregate(
                session_selection
            )
        if receipt.selection_fingerprint != _selection_fingerprint(
            resolved.session_ids
        ):
            raise ProjectQualityAggregationError(
                ProjectQualityAggregationError.code
            )
        aggregate = receipt.aggregate
        if aggregate.selected_session_count != len(resolved.session_ids):
            raise ProjectQualityAggregationError(
                ProjectQualityAggregationError.code
            )
        if any(
            metric.aggregation_method
            is not SessionMetricAggregation.RATIO_OF_SUMS
            or any(
                cohort.key.aggregation_method
                is not SessionMetricAggregation.RATIO_OF_SUMS
                for cohort in metric.compatibility_cohorts
            )
            for metric in aggregate.metrics
        ):
            raise ProjectQualityAggregationError(
                ProjectQualityAggregationError.code
            )

        return ProjectQualityAggregate(
            selection_mode=selection.selection_mode,
            estimand=ProjectQualityEstimand.PER_ELIGIBLE_OPPORTUNITY,
            aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
            selected_project_count=resolved.selected_project_count,
            session_quality=_public_session_quality(aggregate),
        )


def create_project_quality_aggregation_service(
    resolver: IndexedProjectSessionResolver,
    session_quality_factory: SessionQualityAggregatorFactory,
) -> ProjectQualityAggregationService:
    """Typed composition helper retained for bootstrap and schema-only adapters."""

    return ProjectQualityAggregationService(resolver, session_quality_factory)
