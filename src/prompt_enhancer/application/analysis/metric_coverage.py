"""Content-free measurement coverage over the exact local SQLite index.

Coverage is deliberately not a metric score.  This module reports which
reviewed Coaching-v1 measurements are structurally supported and which
contract-compatible result states exist in one local-index snapshot.  It
cannot claim that the local index is complete provider history, and it never
substitutes an absent result with zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .coaching_baselines import COACHING_METRIC_DEFINITIONS
from .metric_readiness import (
    COACHING_METRIC_REQUIREMENTS,
    METRIC_READINESS_CATALOG_VERSION,
    MetricEvidenceCapability,
    ProviderCapabilityReport,
    ProviderMetricCapabilityReason,
)
from .text_analysis_presets import COACHING_PROFILE_V1


METRIC_COVERAGE_CONTRACT_VERSION = "metric-coverage-report-v1"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("metric coverage timestamps must be UTC")
    return value


class MetricCoverageScope(StrEnum):
    PROVIDER_CATALOG = "provider_catalog"
    ONE_PROJECT = "one_project"


class ProviderHistoryCompleteness(StrEnum):
    UNKNOWN = "unknown"


class ProviderSnapshotAuthority(StrEnum):
    UNAVAILABLE = "unavailable"


class MetricStructuralSupportState(StrEnum):
    ATTEMPTABLE = "attemptable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class MetricCoverageSelection(StrictModel):
    """Internal selector; the project pseudonym never enters the report."""

    provider: Provider
    scope: MetricCoverageScope
    project_id: str | None = Field(default=None, repr=False)

    @field_validator("project_id")
    @classmethod
    def safe_project_id(cls, value: str | None) -> str | None:
        if value is not None and PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("metric coverage project selector is invalid")
        return value

    @model_validator(mode="after")
    def exact_scope(self) -> MetricCoverageSelection:
        if (self.scope is MetricCoverageScope.ONE_PROJECT) != (
            self.project_id is not None
        ):
            raise ValueError("metric coverage scope and selector disagree")
        return self


class LatestProfileRunCounts(StrictModel):
    completed: int = Field(ge=0)
    running: int = Field(ge=0)
    failed: int = Field(ge=0)
    never_run: int = Field(ge=0)

    @property
    def run_count(self) -> int:
        return self.completed + self.running + self.failed


class MetricResultStateCounts(StrictModel):
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


class StoredMetricCoverage(StrictModel):
    """Repository counts for one exact metric definition.

    A persisted row is counted in ``contract_compatible_result_states`` only
    when it is the sole row for that selected metric and its definition-facing
    fields match the reviewed Coaching contract.  Compatibility across
    sessions is a separate axis: more than one provenance cohort must never be
    presented as one comparable measurement population.
    """

    metric_key: str
    metric_version: int = Field(ge=1)
    latest_completed_run_count: int = Field(ge=0)
    selected_run_count: int = Field(ge=0)
    not_selected_run_count: int = Field(ge=0)
    unknown_scope_run_count: int = Field(ge=0)
    completed_selected_run_count: int = Field(ge=0)
    contract_compatible_result_states: MetricResultStateCounts
    contract_incompatible_result_count: int = Field(ge=0)
    expected_result_absent_count: int = Field(ge=0)
    compatible_provenance_cohort_count: int = Field(ge=0)
    effective_automation_selected_project_count: int = Field(ge=0)

    @model_validator(mode="after")
    def preserve_axes(self) -> StoredMetricCoverage:
        if self.latest_completed_run_count != (
            self.selected_run_count
            + self.not_selected_run_count
            + self.unknown_scope_run_count
        ):
            raise ValueError("metric selection counts must preserve latest runs")
        if self.completed_selected_run_count != self.selected_run_count:
            raise ValueError(
                "completed selected counts must preserve selected snapshots"
            )
        compatible_count = self.contract_compatible_result_states.total
        if self.completed_selected_run_count != (
            compatible_count
            + self.contract_incompatible_result_count
            + self.expected_result_absent_count
        ):
            raise ValueError("metric result compatibility must preserve selections")
        if (
            self.compatible_provenance_cohort_count > compatible_count
            or (compatible_count == 0)
            != (self.compatible_provenance_cohort_count == 0)
        ):
            raise ValueError(
                "metric provenance cohorts must preserve compatible results"
            )
        return self


class MetricCoverageSnapshot(StrictModel):
    """One exact SQLite read snapshot, before cached capability projection."""

    scope: MetricCoverageScope
    provider: Provider
    generated_at: datetime
    indexed_project_count: int = Field(ge=0)
    indexed_session_count: int = Field(ge=0)
    latest_profile_runs: LatestProfileRunCounts
    latest_completed_snapshot_count: int = Field(ge=0)
    effective_automation_grant_count: int = Field(ge=0)
    effective_automation_project_count: int = Field(ge=0)
    unrecognized_result_record_count: int = Field(ge=0)
    metrics: tuple[StoredMetricCoverage, ...]

    _utc_generated = field_validator("generated_at")(_utc)

    @model_validator(mode="after")
    def exact_catalog(self) -> MetricCoverageSnapshot:
        if self.indexed_session_count != (
            self.latest_profile_runs.run_count + self.latest_profile_runs.never_run
        ):
            raise ValueError("latest-run counts must preserve indexed sessions")
        if self.latest_completed_snapshot_count > self.indexed_session_count:
            raise ValueError("completed snapshots cannot exceed indexed sessions")
        if self.latest_completed_snapshot_count > self.latest_profile_runs.run_count:
            raise ValueError("completed snapshots require matching profile attempts")
        if self.latest_profile_runs.completed > self.latest_completed_snapshot_count:
            raise ValueError("latest completed attempts require completed snapshots")
        if (
            self.scope is MetricCoverageScope.ONE_PROJECT
            and self.indexed_project_count != 1
        ):
            raise ValueError(
                "one-project coverage requires exactly one indexed project"
            )
        if self.effective_automation_project_count > self.indexed_project_count:
            raise ValueError("automation projects cannot exceed indexed projects")
        if (
            self.effective_automation_project_count
            > self.effective_automation_grant_count
        ):
            raise ValueError("automation projects cannot exceed effective grants")
        expected = tuple(
            (item.key, item.version) for item in COACHING_METRIC_DEFINITIONS
        )
        actual = tuple((item.metric_key, item.metric_version) for item in self.metrics)
        if actual != expected:
            raise ValueError(
                "metric coverage snapshot must use the exact catalog order"
            )
        if any(
            item.latest_completed_run_count
            != self.latest_completed_snapshot_count
            or item.effective_automation_selected_project_count
            > self.effective_automation_project_count
            for item in self.metrics
        ):
            raise ValueError("metric coverage counts exceed their snapshot scope")
        return self


class MetricCoverageRepository(Protocol):
    def snapshot(
        self,
        selection: MetricCoverageSelection,
        *,
        generated_at: datetime,
    ) -> MetricCoverageSnapshot: ...


class ProviderCapabilityQuery(Protocol):
    def provider_capabilities(self, provider: Provider) -> ProviderCapabilityReport: ...


class MetricCoverageProjectNotFoundError(LookupError):
    pass


class MetricCoverageMetric(StoredMetricCoverage):
    metric_key: str
    metric_version: int = Field(ge=1)
    dimension: str
    display_name: str
    structural_support: MetricStructuralSupportState
    required_evidence: tuple[tuple[MetricEvidenceCapability, ...], ...]

    @model_validator(mode="after")
    def bind_catalog_metadata(self) -> MetricCoverageMetric:
        definitions = {
            (item.key, item.version): item for item in COACHING_METRIC_DEFINITIONS
        }
        requirements = {
            (item.metric_key, item.metric_version): item
            for item in COACHING_METRIC_REQUIREMENTS
        }
        identity = (self.metric_key, self.metric_version)
        definition = definitions.get(identity)
        requirement = requirements.get(identity)
        if (
            definition is None
            or requirement is None
            or self.dimension != definition.dimension
            or self.display_name != definition.display_name
            or self.required_evidence != requirement.capability_groups
        ):
            raise ValueError("metric coverage metadata must bind the reviewed catalog")
        return self


class MetricCoverageReport(StrictModel):
    """Identifier-free coverage truth for one exact local-index snapshot."""

    contract_version: Literal[METRIC_COVERAGE_CONTRACT_VERSION] = (
        METRIC_COVERAGE_CONTRACT_VERSION
    )
    scope: MetricCoverageScope
    provider: Provider
    generated_at: datetime
    analysis_profile_key: Literal["coaching_profile"] = "coaching_profile"
    analysis_profile_version: Literal[1] = 1
    metric_pack_key: Literal["experimental.redacted-text.coaching"] = (
        "experimental.redacted-text.coaching"
    )
    metric_pack_version: Literal[3] = 3
    metric_catalog_version: Literal[METRIC_READINESS_CATALOG_VERSION] = (
        METRIC_READINESS_CATALOG_VERSION
    )
    indexed_project_count: int = Field(ge=0)
    indexed_session_count: int = Field(ge=0)
    latest_profile_runs: LatestProfileRunCounts
    latest_completed_snapshot_count: int = Field(ge=0)
    effective_automation_grant_count: int = Field(ge=0)
    effective_automation_project_count: int = Field(ge=0)
    unrecognized_result_record_count: int = Field(ge=0)
    automation_scheduling_scope: Literal["new_or_changed_newest_bounded"] = (
        "new_or_changed_newest_bounded"
    )
    metrics: tuple[MetricCoverageMetric, ...]
    capability_report: ProviderCapabilityReport
    local_index_snapshot_exact: Literal[True] = True
    provider_history_completeness: Literal[ProviderHistoryCompleteness.UNKNOWN] = (
        ProviderHistoryCompleteness.UNKNOWN
    )
    provider_snapshot_authority: Literal[ProviderSnapshotAuthority.UNAVAILABLE] = (
        ProviderSnapshotAuthority.UNAVAILABLE
    )
    stored_result_contract_validation_performed: Literal[True] = True
    provider_capability_snapshot_atomic: Literal[False] = False
    full_catalog_automation_coverage_guaranteed: Literal[False] = False
    metric_values_included: Literal[False] = False
    product_source_authority: Literal[False] = False
    population_completeness_verified: Literal[False] = False
    comparison_authority: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_authority: Literal[False] = False

    _utc_generated = field_validator("generated_at")(_utc)

    @model_validator(mode="after")
    def validate_report(self) -> MetricCoverageReport:
        if self.capability_report.provider is not self.provider:
            raise ValueError("coverage capability provider disagrees")
        if self.capability_report.catalog_version != self.metric_catalog_version:
            raise ValueError("coverage capability catalog disagrees")
        if self.indexed_session_count != (
            self.latest_profile_runs.run_count + self.latest_profile_runs.never_run
        ):
            raise ValueError("coverage run counts must preserve indexed sessions")
        if self.latest_completed_snapshot_count > self.indexed_session_count:
            raise ValueError("completed snapshots cannot exceed indexed sessions")
        if self.latest_completed_snapshot_count > self.latest_profile_runs.run_count:
            raise ValueError("completed snapshots require matching profile attempts")
        if self.latest_profile_runs.completed > self.latest_completed_snapshot_count:
            raise ValueError("latest completed attempts require completed snapshots")
        if (
            self.scope is MetricCoverageScope.ONE_PROJECT
            and self.indexed_project_count != 1
        ):
            raise ValueError(
                "one-project coverage requires exactly one indexed project"
            )
        if self.effective_automation_project_count > self.indexed_project_count:
            raise ValueError("automation projects cannot exceed indexed projects")
        if (
            self.effective_automation_project_count
            > self.effective_automation_grant_count
        ):
            raise ValueError("automation projects cannot exceed effective grants")
        expected = tuple(
            (item.key, item.version) for item in COACHING_METRIC_DEFINITIONS
        )
        actual = tuple((item.metric_key, item.metric_version) for item in self.metrics)
        if actual != expected:
            raise ValueError("coverage report must contain the exact metric catalog")
        requirements = {
            (item.metric_key, item.metric_version): item
            for item in COACHING_METRIC_REQUIREMENTS
        }
        if any(
            item.latest_completed_run_count
            != self.latest_completed_snapshot_count
            or item.effective_automation_selected_project_count
            > self.effective_automation_project_count
            or item.structural_support
            is not _structural_support(
                requirements[(item.metric_key, item.metric_version)],
                self.capability_report,
            )
            for item in self.metrics
        ):
            raise ValueError("metric coverage exceeds its report scope")
        support_counts = {
            state: sum(item.structural_support is state for item in self.metrics)
            for state in MetricStructuralSupportState
        }
        if (
            support_counts[MetricStructuralSupportState.ATTEMPTABLE]
            != self.capability_report.structurally_attemptable_metric_count
            or support_counts[MetricStructuralSupportState.UNSUPPORTED]
            != self.capability_report.structurally_unsupported_metric_count
            or support_counts[MetricStructuralSupportState.UNKNOWN]
            != self.capability_report.structurally_unknown_metric_count
        ):
            raise ValueError("metric structural support disagrees with capabilities")
        return self


def _structural_support(
    requirement,
    capability_report: ProviderCapabilityReport,
) -> MetricStructuralSupportState:
    by_capability = {
        item.capability: item for item in capability_report.capabilities
    }
    if capability_report.structurally_unknown_metric_count == len(
        COACHING_METRIC_DEFINITIONS
    ):
        return MetricStructuralSupportState.UNKNOWN
    declared = {
        capability
        for capability, item in by_capability.items()
        if item.reason_code
        not in {
            ProviderMetricCapabilityReason.NOT_DECLARED_BY_DECODER,
            ProviderMetricCapabilityReason.PROVIDER_ADAPTER_UNAVAILABLE,
        }
    }
    return (
        MetricStructuralSupportState.ATTEMPTABLE
        if all(
            any(item in declared for item in group)
            for group in requirement.capability_groups
        )
        else MetricStructuralSupportState.UNSUPPORTED
    )


class MetricCoverageService:
    def __init__(
        self,
        repository: MetricCoverageRepository,
        capabilities: ProviderCapabilityQuery,
        *,
        clock,
    ) -> None:
        self._repository = repository
        self._capabilities = capabilities
        self._clock = clock

    def report(self, selection: MetricCoverageSelection) -> MetricCoverageReport:
        generated_at = _utc(self._clock())
        snapshot = self._repository.snapshot(
            selection,
            generated_at=generated_at,
        )
        if (
            snapshot.scope is not selection.scope
            or snapshot.provider is not selection.provider
            or snapshot.generated_at != generated_at
        ):
            raise RuntimeError("metric coverage snapshot provenance mismatch")
        capability_report = self._capabilities.provider_capabilities(
            selection.provider
        )
        requirements = {
            (item.metric_key, item.metric_version): item
            for item in COACHING_METRIC_REQUIREMENTS
        }
        definitions = {
            (item.key, item.version): item for item in COACHING_METRIC_DEFINITIONS
        }
        metrics = tuple(
            MetricCoverageMetric(
                **stored.model_dump(mode="python"),
                dimension=definitions[
                    (stored.metric_key, stored.metric_version)
                ].dimension,
                display_name=definitions[
                    (stored.metric_key, stored.metric_version)
                ].display_name,
                structural_support=_structural_support(
                    requirements[(stored.metric_key, stored.metric_version)],
                    capability_report,
                ),
                required_evidence=requirements[
                    (stored.metric_key, stored.metric_version)
                ].capability_groups,
            )
            for stored in snapshot.metrics
        )
        return MetricCoverageReport(
            scope=snapshot.scope,
            provider=snapshot.provider,
            generated_at=snapshot.generated_at,
            analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
            analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
            indexed_project_count=snapshot.indexed_project_count,
            indexed_session_count=snapshot.indexed_session_count,
            latest_profile_runs=snapshot.latest_profile_runs,
            latest_completed_snapshot_count=(
                snapshot.latest_completed_snapshot_count
            ),
            effective_automation_grant_count=(
                snapshot.effective_automation_grant_count
            ),
            effective_automation_project_count=(
                snapshot.effective_automation_project_count
            ),
            unrecognized_result_record_count=(
                snapshot.unrecognized_result_record_count
            ),
            metrics=metrics,
            capability_report=capability_report,
        )


__all__ = [
    "METRIC_COVERAGE_CONTRACT_VERSION",
    "LatestProfileRunCounts",
    "MetricCoverageMetric",
    "MetricCoverageProjectNotFoundError",
    "MetricCoverageReport",
    "MetricCoverageRepository",
    "MetricCoverageScope",
    "MetricCoverageSelection",
    "MetricCoverageService",
    "MetricCoverageSnapshot",
    "MetricResultStateCounts",
    "MetricStructuralSupportState",
    "ProviderHistoryCompleteness",
    "ProviderSnapshotAuthority",
    "StoredMetricCoverage",
]
