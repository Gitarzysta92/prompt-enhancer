from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.project_quality_aggregation import (
    FingerprintedSessionQualityAggregator,
    IndexedProjectQualitySnapshot,
    IndexedProjectSessions,
    ProjectQualityAggregationError,
    ProjectQualityAggregationService,
    ProjectQualityEstimand,
    ProjectQualitySelection,
    ProjectQualitySelectionIncompleteError,
    ProjectQualitySelectionMode,
    SessionQualityAggregationReceipt,
)
from prompt_enhancer.application.analysis.session_quality_aggregation import (
    SessionQualityAggregate,
    SessionQualityAggregateState,
    SessionQualityCompatibilityCohort,
    SessionQualityCompatibilityKey,
    SessionQualityCompatibilityState,
    SessionQualityIntegrityState,
    SessionQualityMetricAggregate,
    SessionQualityStateCounts,
)
from prompt_enhancer.application.persistence import (
    SessionMetricAggregation,
    SessionMetricDirection,
    SessionMetricScopeState,
)
from prompt_enhancer.domain import DataTier, MetricSource, Provider


def _empty_aggregate(selected_session_count: int) -> SessionQualityAggregate:
    return SessionQualityAggregate(
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key="coaching.session-quality",
        metric_pack_version=1,
        metric_schema_version=2,
        selected_session_count=selected_session_count,
        completed_run_count=0,
        missing_run_count=selected_session_count,
        integrity_state=SessionQualityIntegrityState.VALID,
        unexpected_result_record_count=0,
        duplicate_result_record_count=0,
        metrics=(),
    )


class _Resolver:
    def __init__(self, resolved: IndexedProjectSessions) -> None:
        self.resolved = resolved
        self.calls: list[tuple[tuple[str, ...], int]] = []

    @contextmanager
    def open_indexed_project_quality_snapshot(
        self,
        project_ids: tuple[str, ...],
        *,
        max_sessions: int,
    ):
        self.calls.append((project_ids, max_sessions))
        yield IndexedProjectQualitySnapshot(
            resolution=self.resolved,
            repository=object(),  # type: ignore[arg-type]
        )


class _SessionAggregator:
    def __init__(self, selected_session_count: int) -> None:
        self.selected_session_count = selected_session_count
        self.selections: list[Any] = []

    def aggregate(self, selection: Any) -> SessionQualityAggregate:
        self.selections.append(selection)
        return _empty_aggregate(self.selected_session_count)


class _ReturningSessionAggregator:
    def __init__(self, aggregate: SessionQualityAggregate) -> None:
        self.aggregate_result = aggregate

    def aggregate(self, _selection: Any) -> SessionQualityAggregate:
        return self.aggregate_result


def _factory(core):
    return lambda _repository: FingerprintedSessionQualityAggregator(core)


def test_project_selection_is_safe_unique_and_bounded() -> None:
    with pytest.raises(ValidationError):
        ProjectQualitySelection(project_ids=())
    with pytest.raises(ValidationError):
        ProjectQualitySelection(project_ids=("not-safe",))
    with pytest.raises(ValidationError):
        ProjectQualitySelection(project_ids=("1" * 64, "1" * 64))
    with pytest.raises(ValidationError):
        ProjectQualitySelection(
            project_ids=tuple(f"{index:064x}" for index in range(26))
        )
    with pytest.raises(ValidationError):
        ProjectQualitySelection.model_validate(
            {
                "project_ids": ["1" * 64],
                "selection_mode": "typical_project",
            }
        )


def test_service_resolves_once_and_exposes_only_the_closed_first_estimand() -> None:
    project_ids = ("1" * 64, "2" * 64)
    session_ids = ("a" * 64, "b" * 64, "c" * 64)
    resolver = _Resolver(
        IndexedProjectSessions(
            selected_project_count=2,
            session_ids=session_ids,
        )
    )
    session_quality = _SessionAggregator(selected_session_count=3)

    result = ProjectQualityAggregationService(
        resolver,
        _factory(session_quality),
    ).aggregate(ProjectQualitySelection(project_ids=project_ids))

    assert resolver.calls == [(project_ids, 100)]
    assert len(session_quality.selections) == 1
    assert session_quality.selections[0].session_ids == session_ids
    assert result.selection_mode is ProjectQualitySelectionMode.ALL_ANALYZED_WORK
    assert result.estimand is ProjectQualityEstimand.PER_ELIGIBLE_OPPORTUNITY
    assert result.aggregation_method is SessionMetricAggregation.RATIO_OF_SUMS
    assert result.selected_project_count == 2
    assert result.session_quality.selected_session_count == 3

    serialized = result.model_dump_json()
    for forbidden in (*project_ids, *session_ids, "project_ids", "session_ids"):
        assert forbidden not in serialized


def test_incomplete_resolution_stops_before_session_aggregation() -> None:
    resolver = _Resolver(
        IndexedProjectSessions(
            selected_project_count=1,
            session_ids=("a" * 64,),
        )
    )
    session_quality = _SessionAggregator(selected_session_count=1)

    with pytest.raises(ProjectQualitySelectionIncompleteError):
        ProjectQualityAggregationService(
            resolver,
            _factory(session_quality),
        ).aggregate(
            ProjectQualitySelection(project_ids=("1" * 64, "2" * 64))
        )

    assert session_quality.selections == []


def test_nested_aggregate_must_match_the_complete_resolved_session_count() -> None:
    resolver = _Resolver(
        IndexedProjectSessions(
            selected_project_count=1,
            session_ids=("a" * 64, "b" * 64),
        )
    )
    session_quality = _SessionAggregator(selected_session_count=1)

    with pytest.raises(ProjectQualityAggregationError):
        ProjectQualityAggregationService(
            resolver,
            _factory(session_quality),
        ).aggregate(
            ProjectQualitySelection(project_ids=("1" * 64,))
        )


def test_public_projection_hashes_path_capable_provenance_values() -> None:
    private_shaped_value = "C:/example/private/model"
    url_shaped_value = "https://example.invalid/private"
    arbitrary_marker = "synthetic_private_marker"
    state_counts = SessionQualityStateCounts(
        known=1,
        unknown=0,
        not_applicable=0,
        abstained=0,
        execution_error=0,
    )
    compatibility_key = SessionQualityCompatibilityKey(
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key="coaching.session-quality",
        metric_pack_version=1,
        metric_scope_state=SessionMetricScopeState.EXACT,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_policy_version="consent-v1",
        provider=Provider.SYNTHETIC,
        provider_version=private_shaped_value,
        adapter_version=url_shaped_value,
        source_schema_version="source-v1",
        content_schema_version="content-v1",
        metric_engine_version="engine-v1",
        redactor_version="redactor-v1",
        local_only=True,
        metric_key="goal_definition_coverage",
        metric_version=1,
        metric_unit="ratio",
        metric_source=MetricSource.DETERMINISTIC,
        metric_direction=SessionMetricDirection.HIGHER_IS_BETTER,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=2,
        algorithm_id="rules.metric",
        algorithm_version="1",
        model_id=arbitrary_marker,
    )
    cohort = SessionQualityCompatibilityCohort(
        key=compatibility_key,
        result_count=1,
        state_counts=state_counts,
        fraction_numerator=1,
        fraction_denominator=2,
        numeric_value=0.5,
        analyzable_observed_count=1,
        analyzable_eligible_count=2,
        analyzable_coverage=0.5,
    )
    metric = SessionQualityMetricAggregate(
        metric_key="goal_definition_coverage",
        metric_version=1,
        metric_unit="ratio",
        metric_direction=SessionMetricDirection.HIGHER_IS_BETTER,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        compatibility_state=SessionQualityCompatibilityState.COMPATIBLE,
        aggregate_state=SessionQualityAggregateState.KNOWN,
        selected_session_count=1,
        completed_run_count=1,
        missing_run_count=0,
        not_selected_run_count=0,
        unknown_scope_run_count=0,
        present_result_count=1,
        missing_result_count=0,
        invalid_result_session_count=0,
        invalid_result_record_count=0,
        state_counts=state_counts,
        compatibility_cohorts=(cohort,),
        fraction_numerator=1,
        fraction_denominator=2,
        numeric_value=0.5,
        analyzable_observed_count=1,
        analyzable_eligible_count=2,
        analyzable_coverage=0.5,
    )
    core = SessionQualityAggregate(
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key="coaching.session-quality",
        metric_pack_version=1,
        metric_schema_version=2,
        selected_session_count=1,
        completed_run_count=1,
        missing_run_count=0,
        integrity_state=SessionQualityIntegrityState.VALID,
        unexpected_result_record_count=0,
        duplicate_result_record_count=0,
        metrics=(metric,),
    )
    resolver = _Resolver(
        IndexedProjectSessions(
            selected_project_count=1,
            session_ids=("a" * 64,),
        )
    )

    result = ProjectQualityAggregationService(
        resolver,
        _factory(_ReturningSessionAggregator(core)),
    ).aggregate(ProjectQualitySelection(project_ids=("1" * 64,)))

    serialized = result.model_dump_json()
    for private_value in (
        private_shaped_value,
        url_shaped_value,
        arbitrary_marker,
    ):
        assert private_value not in serialized
    assert "provider_version" not in serialized
    assert "model_id" not in serialized
    fingerprint = result.session_quality.metrics[0].compatibility_cohorts[
        0
    ].compatibility_fingerprint
    assert result.session_quality.metrics[0].unknown_scope_run_count == 0
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")


class _WrongFingerprintAggregator:
    def aggregate(self, _selection: Any) -> SessionQualityAggregationReceipt:
        return SessionQualityAggregationReceipt(
            selection_fingerprint="f" * 64,
            aggregate=_empty_aggregate(1),
        )


def test_same_cardinality_with_wrong_internal_selection_receipt_is_rejected() -> None:
    resolver = _Resolver(
        IndexedProjectSessions(
            selected_project_count=1,
            session_ids=("a" * 64,),
        )
    )

    with pytest.raises(ProjectQualityAggregationError):
        ProjectQualityAggregationService(
            resolver,
            lambda _repository: _WrongFingerprintAggregator(),
        ).aggregate(ProjectQualitySelection(project_ids=("1" * 64,)))
