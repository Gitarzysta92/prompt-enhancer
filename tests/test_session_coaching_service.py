from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.coaching_summary import (
    CoachingDecisionState,
    CoachingDenominatorKind,
    CoachingOutcomeStatus,
    CoachingTaskType,
)
from prompt_enhancer.application.analysis.session_coaching_service import (
    CoachingTaskContextSource,
    SessionCoachingProjectionError,
    SessionCoachingProjectionService,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    TaskRevisionRecord,
)
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
SESSION_ID = "a" * 64
RUN_ID = "b" * 64


class _AnalysisRepository:
    def __init__(
        self,
        run: SessionAnalysisRunRecord | None,
        results: tuple[SessionAnalysisResultRecord, ...] = (),
    ) -> None:
        self.run = run
        self.results = results

    def get(self, run_id: str) -> SessionAnalysisRunRecord | None:
        return self.run if self.run and self.run.draft.run_id == run_id else None

    def get_results(self, run_id: str) -> tuple[SessionAnalysisResultRecord, ...]:
        assert self.run is not None and self.run.draft.run_id == run_id
        return self.results


class _TaskRepository:
    def __init__(self, revisions: tuple[TaskRevisionRecord, ...] = ()) -> None:
        self.revisions = revisions

    def list_current_revisions_for_session(
        self, session_id: str
    ) -> tuple[TaskRevisionRecord, ...]:
        assert session_id == SESSION_ID
        return self.revisions


def _draft(*, pack_key: str = COACHING_METRIC_PACK_KEY) -> SessionAnalysisRunDraft:
    return SessionAnalysisRunDraft(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        request_fingerprint="c" * 64,
        input_fingerprint="d" * 64,
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=pack_key,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=tuple(
            sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
        ),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version="synthetic-consent-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-source-v1",
        content_schema_version="synthetic-content-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="synthetic-redactor-v1",
        model_plan_fingerprint="e" * 64,
        schema_version=1,
        started_at=NOW,
    )


def _run(*, pack_key: str = COACHING_METRIC_PACK_KEY) -> SessionAnalysisRunRecord:
    return SessionAnalysisRunRecord(
        draft=_draft(pack_key=pack_key),
        status=AnalysisRunStatus.COMPLETED,
        finished_at=NOW + timedelta(seconds=1),
    )


def _result(
    key: str,
    numerator: int,
    denominator: int,
    *,
    model: bool = False,
) -> SessionAnalysisResultRecord:
    metric_versions = {
        "prompt.task_definition_coverage": 2,
        "prompt.problem_evidence_quality": 2,
        "prompt.context_sufficiency": 2,
        "prompt.constraint_precision": 2,
        "prompt.acceptance_testability": 2,
        "prompt.deliverable_contract": 3,
        "collaboration.ambiguity_resolution": 2,
        "collaboration.clarification_yield": 2,
        "collaboration.exploration_conversion": 2,
        "collaboration.scope_change_discipline": 2,
        "collaboration.rework_candidate_rate": 2,
        "logic.decomposition_coverage": 2,
        "logic.hypothesis_test_linkage": 2,
        "logic.decision_rationale_coverage": 3,
        "logic.requirement_action_traceability": 3,
        "logic.open_loop_closure": 2,
        "outcome.agent_claim_grounding": 2,
        "outcome.verification_strategy_adequacy": 2,
        "outcome.first_pass_verification": 2,
        "outcome.verified_requirement_coverage": 2,
    }
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key=key,
            version=metric_versions[key],
            numeric_value=numerator / denominator,
            unit="ratio",
            source=MetricSource.DETERMINISTIC,
            observed_count=4,
            eligible_count=4,
            coverage=1.0,
            confidence=None,
        ),
        value_state=MetricValueState.KNOWN,
        direction=SessionMetricDirection.HIGHER_IS_BETTER,
        applicability=SessionMetricApplicability.APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=1,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=numerator,
        fraction_denominator=denominator,
        explanation_code="synthetic_result",
        algorithm_id=COACHING_METRIC_ALGORITHM_ID,
        algorithm_version=COACHING_METRIC_ALGORITHM_VERSION,
        model_id="synthetic-model" if model else None,
        model_revision="synthetic-revision" if model else None,
        model_license="mit" if model else None,
        tokenizer_id="synthetic-tokenizer" if model else None,
        rubric_version="synthetic-rubric-v1",
        computed_at=NOW,
    )


def _revision(
    *, task_id: str = "f" * 64, task_type: str = "feature_implementation"
) -> TaskRevisionRecord:
    return TaskRevisionRecord(
        task_id=task_id,
        revision=1,
        project_id="1" * 64,
        task_type=task_type,
        lifecycle_state="confirmed",
        session_ids=(SESSION_ID,),
        input_fingerprint="2" * 64,
        created_at=NOW,
    )


def test_reviewed_task_context_produces_only_candidate_coaching() -> None:
    service = SessionCoachingProjectionService(
        _AnalysisRepository(
            _run(),
            (
                _result("prompt.task_definition_coverage", 3, 3),
                _result("prompt.deliverable_contract", 12, 12),
                _result("prompt.acceptance_testability", 0, 12),
            ),
        ),
        _TaskRepository((_revision(),)),
    )

    projection = service.get(RUN_ID)

    assert projection is not None
    assert projection.task_type is CoachingTaskType.IMPLEMENTATION
    assert projection.task_context_source is CoachingTaskContextSource.REVIEWED_TASK
    assert projection.summary.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert projection.summary.strength.code == "strength.deliverable_contract"
    assert projection.summary.strength.decision_state is CoachingDecisionState.CANDIDATE
    assert (
        projection.summary.strength.denominator_kind
        is CoachingDenominatorKind.EVENT_COUNT
    )
    assert projection.summary.friction.code == (
        "friction.acceptance_before_implementation_unclear"
    )
    assert projection.summary.next_experiment.code == (
        "experiment.define_acceptance_before_implementation"
    )


@pytest.mark.parametrize(
    ("revisions", "source"),
    (
        ((), CoachingTaskContextSource.NOT_REVIEWED),
        (
            (_revision(), _revision(task_id="3" * 64)),
            CoachingTaskContextSource.AMBIGUOUS,
        ),
        (
            (_revision(task_type="unknown"),),
            CoachingTaskContextSource.AMBIGUOUS,
        ),
    ),
)
def test_missing_or_ambiguous_review_context_abstains(
    revisions: tuple[TaskRevisionRecord, ...],
    source: CoachingTaskContextSource,
) -> None:
    service = SessionCoachingProjectionService(
        _AnalysisRepository(
            _run(),
            (_result("prompt.task_definition_coverage", 4, 4),),
        ),
        _TaskRepository(revisions),
    )

    projection = service.get(RUN_ID)

    assert projection is not None
    assert projection.task_type is CoachingTaskType.UNKNOWN
    assert projection.task_context_source is source
    assert projection.summary.strength.abstention_code == "task_type_unknown"
    assert projection.summary.friction.abstention_code == "task_type_unknown"


def test_uncalibrated_model_result_is_not_relabelled_as_a_rule_candidate() -> None:
    service = SessionCoachingProjectionService(
        _AnalysisRepository(
            _run(),
            (_result("prompt.task_definition_coverage", 4, 4, model=True),),
        ),
        _TaskRepository((_revision(),)),
    )

    projection = service.get(RUN_ID)

    assert projection is not None
    assert projection.summary.strength.decision_state is CoachingDecisionState.ABSTAINED


def test_missing_and_unsupported_runs_fail_closed() -> None:
    assert SessionCoachingProjectionService(
        _AnalysisRepository(None), _TaskRepository()
    ).get(RUN_ID) is None

    service = SessionCoachingProjectionService(
        _AnalysisRepository(_run(pack_key="synthetic.other-pack")),
        _TaskRepository((_revision(),)),
    )
    with pytest.raises(SessionCoachingProjectionError) as exc:
        service.get(RUN_ID)
    assert exc.value.code == "coaching_pack_unsupported"
