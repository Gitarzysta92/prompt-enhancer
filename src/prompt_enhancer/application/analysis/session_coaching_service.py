"""Read-only composition of one current Coaching Loop projection.

The immutable redacted-text analysis run remains the source record.  This
service adds the *current* reviewed task context and derives a small,
content-free coaching projection.  It never reads provider content, evidence
identifiers, labels, paths, or excerpts and it never mutates either source.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ...domain import StrictModel
from ..persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionAnalysisRunRepository,
    SessionMetricApplicability,
    SessionMetricDirection,
    TaskRepository,
)
from .coaching_baselines import (
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from .coaching_summary import (
    CoachingApplicabilityState,
    CoachingDenominatorKind,
    CoachingEvidenceBasisCode,
    CoachingEvidenceKind,
    CoachingEvidenceTier,
    CoachingSignalDirection,
    CoachingSignalReceipt,
    CoachingSignalState,
    CoachingSourceProvenance,
    CoachingSummary,
    CoachingSummaryInput,
    CoachingTaskType,
    build_coaching_summary,
)


SESSION_COACHING_PROJECTION_KEY = "coaching.loop.current"
SESSION_COACHING_PROJECTION_VERSION = 1


class CoachingTaskContextSource(StrEnum):
    REVIEWED_TASK = "reviewed_task"
    NOT_REVIEWED = "not_reviewed"
    AMBIGUOUS = "ambiguous"


class SessionCoachingProjection(StrictModel):
    """Content-free current projection; not an immutable historical run."""

    projection_key: str = SESSION_COACHING_PROJECTION_KEY
    projection_version: int = Field(default=SESSION_COACHING_PROJECTION_VERSION, ge=1)
    task_type: CoachingTaskType
    task_context_source: CoachingTaskContextSource
    summary: CoachingSummary


class SessionCoachingProjectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_REVIEWED_TASK_TYPES = {
    "feature_implementation": CoachingTaskType.IMPLEMENTATION,
    "bug_fix": CoachingTaskType.DIAGNOSIS,
    "research_design": CoachingTaskType.RESEARCH,
}


def _task_context(
    tasks: TaskRepository,
    session_id: str,
) -> tuple[CoachingTaskType, CoachingTaskContextSource]:
    revisions = tasks.list_current_revisions_for_session(session_id)
    if not revisions:
        return CoachingTaskType.UNKNOWN, CoachingTaskContextSource.NOT_REVIEWED
    if len(revisions) != 1:
        return CoachingTaskType.UNKNOWN, CoachingTaskContextSource.AMBIGUOUS
    task_type = _REVIEWED_TASK_TYPES.get(
        revisions[0].task_type,
        CoachingTaskType.UNKNOWN,
    )
    if task_type is CoachingTaskType.UNKNOWN:
        return CoachingTaskType.UNKNOWN, CoachingTaskContextSource.AMBIGUOUS
    return task_type, CoachingTaskContextSource.REVIEWED_TASK


def _signal_state(value: MetricValueState) -> CoachingSignalState:
    if value is MetricValueState.KNOWN:
        return CoachingSignalState.KNOWN
    if value is MetricValueState.NOT_APPLICABLE:
        return CoachingSignalState.NOT_APPLICABLE
    if value is MetricValueState.UNKNOWN:
        return CoachingSignalState.UNKNOWN
    return CoachingSignalState.ABSTAINED


def _applicability(
    value: SessionMetricApplicability,
) -> CoachingApplicabilityState:
    return CoachingApplicabilityState(value.value)


def _direction(value: SessionMetricDirection) -> CoachingSignalDirection:
    return CoachingSignalDirection(value.value)


def _evidence_basis(metric_code: str) -> CoachingEvidenceBasisCode:
    if metric_code == "collaboration.rework_candidate_rate":
        return CoachingEvidenceBasisCode.RULE_CORRECTION_COUNTS
    if metric_code.startswith(("collaboration.", "logic.")):
        return CoachingEvidenceBasisCode.RULE_LINK_COUNTS
    return CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS


_DENOMINATOR_KIND_BY_METRIC = {
    "prompt.acceptance_testability": CoachingDenominatorKind.EVENT_COUNT,
    "prompt.task_definition_coverage": CoachingDenominatorKind.RUBRIC_FACTOR,
    "prompt.context_sufficiency": CoachingDenominatorKind.RUBRIC_FACTOR,
    "prompt.constraint_precision": CoachingDenominatorKind.EVENT_COUNT,
    "prompt.deliverable_contract": CoachingDenominatorKind.EVENT_COUNT,
    "logic.decomposition_coverage": CoachingDenominatorKind.EVENT_COUNT,
    "logic.hypothesis_test_linkage": CoachingDenominatorKind.EVENT_COUNT,
    "collaboration.scope_change_discipline": CoachingDenominatorKind.EVENT_COUNT,
    "collaboration.clarification_yield": CoachingDenominatorKind.EVENT_COUNT,
    "collaboration.rework_candidate_rate": CoachingDenominatorKind.EVENT_COUNT,
}


def _candidate_receipt(
    result: SessionAnalysisResultRecord,
    *,
    pack_key: str,
    pack_version: int,
) -> CoachingSignalReceipt | None:
    # Model-assisted observations remain excluded until the separate
    # calibration gate is satisfied.  Omitting them is safer than relabeling a
    # model inference as a deterministic candidate.
    if result.model_id is not None:
        return None
    denominator_kind = _DENOMINATOR_KIND_BY_METRIC.get(result.observation.key)
    if denominator_kind is None:
        return None
    known = result.value_state is MetricValueState.KNOWN
    return CoachingSignalReceipt(
        metric_code=result.observation.key,
        metric_version=result.observation.version,
        state=_signal_state(result.value_state),
        applicability=_applicability(result.applicability),
        direction=_direction(result.direction),
        denominator_kind=denominator_kind,
        evidence_kind=CoachingEvidenceKind.DETERMINISTIC_CANDIDATE,
        evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
        evidence_basis=(_evidence_basis(result.observation.key),),
        numerator=result.fraction_numerator if known else None,
        denominator=result.fraction_denominator if known else None,
        coverage=result.observation.coverage,
        confidence=None,
        provenance=CoachingSourceProvenance(
            pack_key=pack_key,
            pack_version=pack_version,
            algorithm_id=result.algorithm_id,
            algorithm_version=result.algorithm_version,
        ),
    )


class SessionCoachingProjectionService:
    """Build a current projection from immutable results and reviewed context."""

    def __init__(
        self,
        analyses: SessionAnalysisRunRepository,
        tasks: TaskRepository,
    ) -> None:
        self._analyses = analyses
        self._tasks = tasks

    def get(self, run_id: str) -> SessionCoachingProjection | None:
        run = self._analyses.get(run_id)
        if run is None:
            return None
        if run.status is not AnalysisRunStatus.COMPLETED:
            raise SessionCoachingProjectionError("coaching_run_not_completed")
        draft = run.draft
        if (
            draft.metric_pack_key != COACHING_METRIC_PACK_KEY
            or draft.metric_pack_version != COACHING_METRIC_PACK_VERSION
            or draft.analysis_profile_key != "coaching_profile"
        ):
            raise SessionCoachingProjectionError("coaching_pack_unsupported")

        task_type, context_source = _task_context(self._tasks, draft.session_id)
        receipts = tuple(
            receipt
            for result in self._analyses.get_results(run_id)
            if (
                receipt := _candidate_receipt(
                    result,
                    pack_key=draft.metric_pack_key,
                    pack_version=draft.metric_pack_version,
                )
            )
            is not None
        )
        return SessionCoachingProjection(
            task_type=task_type,
            task_context_source=context_source,
            summary=build_coaching_summary(
                CoachingSummaryInput(task_type=task_type, signals=receipts)
            ),
        )


__all__ = [
    "CoachingTaskContextSource",
    "SESSION_COACHING_PROJECTION_KEY",
    "SESSION_COACHING_PROJECTION_VERSION",
    "SessionCoachingProjection",
    "SessionCoachingProjectionError",
    "SessionCoachingProjectionService",
]
