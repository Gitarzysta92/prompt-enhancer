from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.session_quality_aggregation import (
    SessionQualityAggregateState,
    SessionQualityAggregationService,
    SessionQualityCompatibilityState,
    SessionQualityIntegrityState,
    SessionQualitySelection,
)
from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_PACK_KEY,
    DEFAULT_TEXT_METRIC_PACK_VERSION,
    TEXT_METRIC_ALGORITHM_ID,
    TEXT_METRIC_ALGORITHM_VERSION,
    TEXT_METRIC_DEFINITIONS,
    TEXT_METRIC_ENGINE_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    TEXT_METRIC_SCHEMA_VERSION,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisAggregationResultRecord,
    SessionAnalysisAggregationSnapshotRecord,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
)
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)


NOW = datetime(2042, 3, 4, 10, 0, tzinfo=UTC)
GOAL_KEY = "prompt.goal_definition"


class _Repository:
    def __init__(self) -> None:
        self.snapshots: dict[str, SessionAnalysisAggregationSnapshotRecord] = {}
        self.batch_calls = 0

    def add(
        self,
        session_id: str,
        run: SessionAnalysisRunRecord,
        results: tuple[SessionAnalysisResultRecord, ...],
    ) -> None:
        draft = run.draft
        self.snapshots[session_id] = SessionAnalysisAggregationSnapshotRecord(
            session_id=session_id,
            analysis_profile_key=draft.analysis_profile_key,
            analysis_profile_version=draft.analysis_profile_version,
            metric_pack_key=draft.metric_pack_key,
            metric_pack_version=draft.metric_pack_version,
            metric_scope_state=draft.metric_scope_state,
            selected_metric_keys=draft.selected_metric_keys,
            data_tier=draft.data_tier,
            consent_policy_version=draft.consent_policy_version,
            provider=draft.provider,
            provider_version=draft.provider_version,
            adapter_version=draft.adapter_version,
            source_schema_version=draft.source_schema_version,
            content_schema_version=draft.content_schema_version,
            metric_engine_version=draft.metric_engine_version,
            redactor_version=draft.redactor_version,
            model_plan_fingerprint=draft.model_plan_fingerprint,
            persistence_schema_version=draft.schema_version,
            local_only=draft.local_only,
            results=tuple(_project_result(result) for result in results),
        )

    def get_latest_completed_for_aggregation(
        self,
        session_ids: tuple[str, ...],
        *,
        analysis_profile_key: str,
        analysis_profile_version: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> tuple[SessionAnalysisAggregationSnapshotRecord, ...]:
        self.batch_calls += 1
        return tuple(
            self.snapshots[session_id]
            for session_id in session_ids
            if session_id in self.snapshots
            and self.snapshots[session_id].analysis_profile_key
            == analysis_profile_key
            and self.snapshots[session_id].analysis_profile_version
            == analysis_profile_version
            and self.snapshots[session_id].metric_pack_key == metric_pack_key
            and self.snapshots[session_id].metric_pack_version
            == metric_pack_version
        )


def _project_result(
    result: SessionAnalysisResultRecord,
) -> SessionAnalysisAggregationResultRecord:
    return SessionAnalysisAggregationResultRecord(
        observation=result.observation,
        value_state=result.value_state,
        direction=result.direction,
        applicability=result.applicability,
        aggregation_method=result.aggregation_method,
        metric_schema_version=result.metric_schema_version,
        fraction_numerator=result.fraction_numerator,
        fraction_denominator=result.fraction_denominator,
        algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version,
        model_id=result.model_id,
        model_revision=result.model_revision,
        model_license=result.model_license,
        tokenizer_id=result.tokenizer_id,
        prompt_version=result.prompt_version,
        rubric_version=result.rubric_version,
    )


def _run(
    session_id: str,
    run_id: str,
    **changes: Any,
) -> SessionAnalysisRunRecord:
    values: dict[str, Any] = {
        "run_id": run_id,
        "session_id": session_id,
        "request_fingerprint": "a" * 64,
        "input_fingerprint": run_id,
        "analysis_profile_key": "standard_engineering",
        "analysis_profile_version": 1,
        "metric_pack_key": DEFAULT_TEXT_METRIC_PACK_KEY,
        "metric_pack_version": DEFAULT_TEXT_METRIC_PACK_VERSION,
        "metric_scope_state": SessionMetricScopeState.EXACT,
        "selected_metric_keys": (GOAL_KEY,),
        "data_tier": DataTier.REDACTED_CONTENT,
        "consent_purpose": "text_analysis",
        "consent_policy_version": "explicit-session-text-analysis-v1",
        "provider": Provider.SYNTHETIC,
        "provider_version": "synthetic-v1",
        "adapter_version": "synthetic-adapter-v1",
        "source_schema_version": "synthetic-source-v1",
        "content_schema_version": "redacted-content-v1",
        "metric_engine_version": TEXT_METRIC_ENGINE_VERSION,
        "redactor_version": "deterministic-redactor-v1",
        "model_plan_fingerprint": "d" * 64,
        "schema_version": 8,
        "local_only": True,
        "started_at": NOW,
    }
    values.update(changes)
    return SessionAnalysisRunRecord(
        draft=SessionAnalysisRunDraft(**values),
        status=AnalysisRunStatus.COMPLETED,
        finished_at=NOW,
    )


def _result(
    *,
    numerator: int | None = 1,
    denominator: int | None = 2,
    state: MetricValueState = MetricValueState.KNOWN,
    observed: int = 1,
    eligible: int = 2,
    evidence_id: str | None = None,
    **changes: Any,
) -> SessionAnalysisResultRecord:
    known = state is MetricValueState.KNOWN
    applicability = (
        SessionMetricApplicability.NOT_APPLICABLE
        if state is MetricValueState.NOT_APPLICABLE
        else SessionMetricApplicability.APPLICABLE
    )
    observation_values: dict[str, Any] = {
        "key": GOAL_KEY,
        "version": 1,
        "numeric_value": numerator / denominator if known else None,
        "unit": "ratio",
        "source": MetricSource.DETERMINISTIC,
        "observed_count": observed,
        "eligible_count": eligible,
        "coverage": 0.0 if eligible == 0 else observed / eligible,
        "confidence": 0.8 if known else None,
    }
    result_values: dict[str, Any] = {
        "value_state": state,
        "direction": SessionMetricDirection.HIGHER_IS_BETTER,
        "applicability": applicability,
        "aggregation_method": SessionMetricAggregation.RATIO_OF_SUMS,
        "metric_schema_version": TEXT_METRIC_SCHEMA_VERSION,
        "evidence_data_tier": DataTier.REDACTED_CONTENT,
        "fraction_numerator": numerator if known else None,
        "fraction_denominator": denominator if known else None,
        "evidence": (
            ()
            if evidence_id is None
            else (
                SessionAnalysisEvidenceRecord(
                    message_id=evidence_id,
                    origin=SessionEvidenceOrigin.DIRECT,
                ),
            )
        ),
        "explanation_code": "synthetic_result",
        "error_code": (
            "synthetic_execution_error"
            if state is MetricValueState.EXECUTION_ERROR
            else None
        ),
        "algorithm_id": TEXT_METRIC_ALGORITHM_ID,
        "algorithm_version": TEXT_METRIC_ALGORITHM_VERSION,
        "rubric_version": "prompt-logic-rubric-1",
        "computed_at": NOW,
    }
    for name, value in changes.items():
        if name.startswith("observation__"):
            observation_values[name.removeprefix("observation__")] = value
        else:
            result_values[name] = value
    if known and "observation__numeric_value" not in changes:
        result_values_numerator = result_values.get("fraction_numerator")
        result_values_denominator = result_values.get("fraction_denominator")
        observation_values["numeric_value"] = (
            result_values_numerator / result_values_denominator
        )
    return SessionAnalysisResultRecord(
        observation=MetricObservation(**observation_values),
        **result_values,
    )


def _goal_metric(result):
    return next(metric for metric in result.metrics if metric.metric_key == GOAL_KEY)


def _metric(result, metric_key: str):
    return next(metric for metric in result.metrics if metric.metric_key == metric_key)


def test_selector_is_bounded_safe_and_rejects_duplicate_weighting() -> None:
    with pytest.raises(ValidationError):
        SessionQualitySelection(session_ids=())
    with pytest.raises(ValidationError):
        SessionQualitySelection(session_ids=("not-a-safe-id",))
    with pytest.raises(ValidationError):
        SessionQualitySelection(session_ids=tuple("a" * 64 for _ in range(2)))
    with pytest.raises(ValidationError):
        SessionQualitySelection(
            session_ids=tuple(f"{index:064x}" for index in range(101))
        )


def test_known_metrics_use_ratio_of_sums_and_summed_coverage() -> None:
    first_session, second_session = "1" * 64, "2" * 64
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (_result(numerator=1, denominator=1, observed=1, eligible=2),),
    )
    repository.add(
        second_session,
        _run(second_session, "b" * 64),
        (_result(numerator=0, denominator=9, observed=2, eligible=8),),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(first_session, second_session))
    )
    goal = _goal_metric(aggregate)

    assert repository.batch_calls == 1
    assert aggregate.completed_run_count == 2
    assert aggregate.missing_run_count == 0
    assert goal.aggregate_state is SessionQualityAggregateState.KNOWN
    assert goal.compatibility_state is SessionQualityCompatibilityState.COMPATIBLE
    assert (goal.fraction_numerator, goal.fraction_denominator) == (1, 10)
    assert goal.numeric_value == pytest.approx(0.1)
    assert goal.numeric_value != pytest.approx((1.0 + 0.0) / 2)
    assert (goal.analyzable_observed_count, goal.analyzable_eligible_count) == (
        3,
        10,
    )
    assert goal.analyzable_coverage == pytest.approx(0.3)

    invalid_output = goal.model_dump()
    invalid_output["fraction_denominator"] = 0
    with pytest.raises(ValidationError):
        goal.__class__.model_validate(invalid_output)


def test_overlapping_exact_scopes_combine_selected_metric_and_count_omission() -> None:
    first_session, second_session = "1" * 64, "2" * 64
    constraint_key = "prompt.constraint_resolution"
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (_result(numerator=1, denominator=2),),
    )
    repository.add(
        second_session,
        _run(
            second_session,
            "b" * 64,
            selected_metric_keys=tuple(sorted((GOAL_KEY, constraint_key))),
            model_plan_fingerprint="e" * 64,
            schema_version=13,
        ),
        (
            _result(numerator=1, denominator=2),
            _result(
                numerator=1,
                denominator=1,
                observation__key=constraint_key,
            ),
        ),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(first_session, second_session))
    )
    goal = _goal_metric(aggregate)
    constraint = _metric(aggregate, constraint_key)

    assert goal.compatibility_state is SessionQualityCompatibilityState.COMPATIBLE
    assert len(goal.compatibility_cohorts) == 1
    assert goal.compatibility_cohorts[0].result_count == 2
    assert goal.numeric_value == pytest.approx(0.5)
    assert constraint.compatibility_state is (
        SessionQualityCompatibilityState.COMPATIBLE
    )
    assert constraint.not_selected_run_count == 1
    assert constraint.missing_result_count == 0
    assert constraint.present_result_count == 1
    assert constraint.numeric_value == pytest.approx(1.0)


def test_sparse_legacy_scope_blocks_value_instead_of_zero_filling() -> None:
    first_session, second_session, absent_session = "1" * 64, "2" * 64, "3" * 64
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (
            _result(
                numerator=None,
                denominator=None,
                state=MetricValueState.NOT_APPLICABLE,
                observed=0,
                eligible=0,
            ),
        ),
    )
    repository.add(
        second_session,
        _run(
            second_session,
            "b" * 64,
            metric_scope_state=SessionMetricScopeState.LEGACY_UNKNOWN,
            selected_metric_keys=(),
        ),
        (),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(
            session_ids=(first_session, second_session, absent_session)
        )
    )
    goal = _goal_metric(aggregate)

    assert aggregate.selected_session_count == 3
    assert (aggregate.completed_run_count, aggregate.missing_run_count) == (2, 1)
    assert goal.present_result_count == 1
    assert goal.missing_result_count == 1
    assert goal.state_counts.not_applicable == 1
    assert goal.aggregate_state is SessionQualityAggregateState.INCOMPATIBLE
    assert goal.compatibility_state is SessionQualityCompatibilityState.INCOMPATIBLE
    assert goal.unknown_scope_run_count == 1
    assert goal.blocked_reason_codes == ("metric_scope_unknown",)
    assert goal.numeric_value is None
    assert goal.fraction_numerator is None
    assert goal.fraction_denominator is None


def test_unknown_scope_count_is_orthogonal_for_legacy_missing_results() -> None:
    exact_session, legacy_session = "1" * 64, "2" * 64
    repository = _Repository()
    repository.add(
        exact_session,
        _run(exact_session, "a" * 64),
        (_result(numerator=1, denominator=2),),
    )
    repository.add(
        legacy_session,
        _run(
            legacy_session,
            "b" * 64,
            metric_scope_state=SessionMetricScopeState.LEGACY_UNKNOWN,
            selected_metric_keys=(),
        ),
        (),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(exact_session, legacy_session))
    )
    goal = _goal_metric(aggregate)
    omitted = _metric(aggregate, "prompt.constraint_resolution")

    assert goal.completed_run_count == 2
    assert goal.present_result_count == 1
    assert goal.missing_result_count == 1
    assert goal.not_selected_run_count == 0
    assert goal.unknown_scope_run_count == 1
    assert goal.compatibility_state is SessionQualityCompatibilityState.INCOMPATIBLE
    assert goal.blocked_reason_codes == ("metric_scope_unknown",)
    assert omitted.present_result_count == 0
    assert omitted.not_selected_run_count == 1
    assert omitted.missing_result_count == 1
    assert omitted.unknown_scope_run_count == 1
    assert omitted.blocked_reason_codes == ("metric_scope_unknown",)

    invalid = goal.model_dump()
    invalid["unknown_scope_run_count"] = 3
    with pytest.raises(ValidationError, match="unknown metric scope"):
        goal.__class__.model_validate(invalid)


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        (MetricValueState.UNKNOWN, SessionQualityAggregateState.UNKNOWN),
        (
            MetricValueState.NOT_APPLICABLE,
            SessionQualityAggregateState.NOT_APPLICABLE,
        ),
        (MetricValueState.ABSTAINED, SessionQualityAggregateState.ABSTAINED),
        (
            MetricValueState.EXECUTION_ERROR,
            SessionQualityAggregateState.EXECUTION_ERROR,
        ),
    ),
)
def test_complete_non_known_cohort_preserves_defensible_typed_state(
    state: MetricValueState,
    expected: SessionQualityAggregateState,
) -> None:
    session_id = "1" * 64
    repository = _Repository()
    repository.add(
        session_id,
        _run(session_id, "a" * 64),
        (
            _result(
                numerator=None,
                denominator=None,
                state=state,
                observed=0,
                eligible=1,
            ),
        ),
    )

    goal = _goal_metric(
        SessionQualityAggregationService(repository).aggregate(
            SessionQualitySelection(session_ids=(session_id,))
        )
    )
    assert goal.aggregate_state is expected
    assert goal.numeric_value is None


@pytest.mark.parametrize(
    ("run_change", "result_change"),
    (
        ({"provider": Provider.CODEX}, {}),
        ({"provider_version": "alternate-provider-v2"}, {}),
        ({"adapter_version": "alternate-adapter-v2"}, {}),
        ({"source_schema_version": "alternate-source-v2"}, {}),
        ({"content_schema_version": "alternate-content-v2"}, {}),
        ({"metric_engine_version": "alternate-engine-v2"}, {}),
        ({"redactor_version": "alternate-redactor-v2"}, {}),
        ({"consent_policy_version": "alternate-consent-v2"}, {}),
        ({}, {"observation__version": 2}),
        ({}, {"observation__unit": "risk_ratio"}),
        ({}, {"observation__source": MetricSource.ESTIMATED}),
        ({}, {"direction": SessionMetricDirection.LOWER_IS_BETTER}),
        ({}, {"metric_schema_version": 3}),
        ({}, {"algorithm_id": "alternate.algorithm"}),
        ({}, {"algorithm_version": "3"}),
        ({}, {"rubric_version": "alternate-rubric-2"}),
        (
            {},
            {
                "model_id": "example/model",
                "model_revision": "revision-2",
                "model_license": "mit",
                "tokenizer_id": "example/tokenizer",
                "prompt_version": "prompt-2",
            },
        ),
    ),
)
def test_every_compatibility_dimension_blocks_mixed_provenance_without_a_winner(
    run_change: dict[str, Any],
    result_change: dict[str, Any],
) -> None:
    first_session, second_session = "1" * 64, "2" * 64
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (_result(numerator=1, denominator=2),),
    )
    repository.add(
        second_session,
        _run(second_session, "b" * 64, **run_change),
        (_result(numerator=2, denominator=3, **result_change),),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(first_session, second_session))
    )
    goal = _goal_metric(aggregate)

    assert aggregate.integrity_state is SessionQualityIntegrityState.INCOMPATIBLE
    assert goal.compatibility_state is SessionQualityCompatibilityState.INCOMPATIBLE
    assert goal.aggregate_state is SessionQualityAggregateState.INCOMPATIBLE
    assert goal.numeric_value is None
    assert goal.fraction_numerator is None
    assert goal.analyzable_coverage is None
    assert len(goal.compatibility_cohorts) == 2
    assert sum(cohort.result_count for cohort in goal.compatibility_cohorts) == 2
    assert sorted(
        cohort.numeric_value for cohort in goal.compatibility_cohorts
    ) == pytest.approx([1 / 2, 2 / 3])


@pytest.mark.parametrize(
    "run_change",
    (
        {"analysis_profile_key": "alternate_engineering"},
        {"analysis_profile_version": 2},
        {"metric_pack_key": "alternate.pack"},
        {"metric_pack_version": 2},
    ),
)
def test_different_profile_or_pack_is_missing_instead_of_invalid(
    run_change: dict[str, Any],
) -> None:
    first_session, second_session = "1" * 64, "2" * 64
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (_result(numerator=1, denominator=2),),
    )
    repository.add(
        second_session,
        _run(second_session, "b" * 64, **run_change),
        (_result(numerator=2, denominator=3),),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(first_session, second_session))
    )
    goal = _goal_metric(aggregate)

    assert aggregate.integrity_state is SessionQualityIntegrityState.VALID
    assert aggregate.completed_run_count == 1
    assert aggregate.missing_run_count == 1
    assert goal.compatibility_state is SessionQualityCompatibilityState.COMPATIBLE
    assert goal.aggregate_state is SessionQualityAggregateState.KNOWN
    assert goal.numeric_value == pytest.approx(1 / 2)
    assert len(goal.compatibility_cohorts) == 1


@pytest.mark.parametrize(
    ("field", "alternate"),
    (
        ("model_id", "example/alternate-model"),
        ("model_revision", "alternate-revision"),
        ("model_license", "apache-2.0"),
        ("tokenizer_id", "example/alternate-tokenizer"),
        ("prompt_version", "prompt-2"),
    ),
)
def test_each_pinned_model_provenance_field_is_an_exact_compatibility_dimension(
    field: str,
    alternate: str,
) -> None:
    first_session, second_session = "1" * 64, "2" * 64
    model = {
        "model_id": "example/model",
        "model_revision": "revision-1",
        "model_license": "mit",
        "tokenizer_id": "example/tokenizer",
        "prompt_version": "prompt-1",
    }
    alternate_model = {**model, field: alternate}
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64),
        (_result(**model),),
    )
    repository.add(
        second_session,
        _run(second_session, "b" * 64),
        (_result(**alternate_model),),
    )

    goal = _goal_metric(
        SessionQualityAggregationService(repository).aggregate(
            SessionQualitySelection(session_ids=(first_session, second_session))
        )
    )

    assert goal.compatibility_state is SessionQualityCompatibilityState.INCOMPATIBLE
    assert goal.aggregate_state is SessionQualityAggregateState.INCOMPATIBLE
    assert len(goal.compatibility_cohorts) == 2
    assert goal.numeric_value is None


def test_ratio_of_sums_property_holds_for_many_fraction_pairs() -> None:
    for first_denominator in range(1, 6):
        for second_denominator in range(1, 6):
            first_numerator = first_denominator // 2
            second_numerator = second_denominator // 3
            first_session, second_session = "1" * 64, "2" * 64
            repository = _Repository()
            repository.add(
                first_session,
                _run(first_session, "a" * 64),
                (
                    _result(
                        numerator=first_numerator,
                        denominator=first_denominator,
                    ),
                ),
            )
            repository.add(
                second_session,
                _run(second_session, "b" * 64),
                (
                    _result(
                        numerator=second_numerator,
                        denominator=second_denominator,
                    ),
                ),
            )
            goal = _goal_metric(
                SessionQualityAggregationService(repository).aggregate(
                    SessionQualitySelection(
                        session_ids=(first_session, second_session)
                    )
                )
            )
            assert goal.fraction_numerator == first_numerator + second_numerator
            assert goal.fraction_denominator == (
                first_denominator + second_denominator
            )
            assert goal.numeric_value == pytest.approx(
                (first_numerator + second_numerator)
                / (first_denominator + second_denominator)
            )


def test_output_order_is_deterministic_and_contains_no_ids_or_evidence_refs() -> None:
    first_session, second_session = "1" * 64, "2" * 64
    first_evidence, second_evidence = "e" * 64, "f" * 64
    repository = _Repository()
    repository.add(
        first_session,
        _run(first_session, "a" * 64, adapter_version="adapter-b"),
        (_result(evidence_id=first_evidence),),
    )
    repository.add(
        second_session,
        _run(second_session, "b" * 64, adapter_version="adapter-a"),
        (_result(evidence_id=second_evidence),),
    )
    service = SessionQualityAggregationService(repository)

    forward = service.aggregate(
        SessionQualitySelection(session_ids=(first_session, second_session))
    )
    reverse = service.aggregate(
        SessionQualitySelection(session_ids=(second_session, first_session))
    )

    assert forward == reverse
    assert tuple(metric.metric_key for metric in forward.metrics) == tuple(
        definition.key for definition in TEXT_METRIC_DEFINITIONS
    )
    serialized = forward.model_dump_json()
    for forbidden in (
        first_session,
        second_session,
        first_evidence,
        second_evidence,
        '"session_id"',
        '"run_id"',
        '"evidence"',
        '"text"',
        '"path"',
        '"explanation_code"',
        '"computed_at"',
    ):
        assert forbidden not in serialized


def test_duplicate_stored_metric_records_are_blocked_and_counted() -> None:
    session_id = "1" * 64
    repository = _Repository()
    repository.add(
        session_id,
        _run(session_id, "a" * 64),
        (
            _result(),
            _result(observation__version=2),
        ),
    )

    aggregate = SessionQualityAggregationService(repository).aggregate(
        SessionQualitySelection(session_ids=(session_id,))
    )
    goal = _goal_metric(aggregate)

    assert aggregate.duplicate_result_record_count == 2
    assert aggregate.integrity_state is SessionQualityIntegrityState.INCOMPATIBLE
    assert goal.compatibility_state is SessionQualityCompatibilityState.INCOMPATIBLE
    assert goal.invalid_result_session_count == 1
    assert goal.invalid_result_record_count == 2
    assert goal.compatibility_cohorts == ()
    assert goal.numeric_value is None
