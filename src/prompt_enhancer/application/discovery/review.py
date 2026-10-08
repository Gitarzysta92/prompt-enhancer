"""Transactional application service for explicit task-review decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ...domain import SAFE_VERSION_PATTERN
from ..persistence import (
    DecisionAction,
    DecisionRevisionLink,
    DecisionRevisionRole,
    PersistenceConflictError,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRepository,
    TaskRevisionRecord,
)
from .contracts import (
    AcceptCandidate,
    MergeCandidates,
    RejectCandidate,
    SplitCandidate,
    TaskCategory,
    TaskDecisionCommand,
)


DECISION_SCHEMA_VERSION = "task-review-v1"
CONFIRMED_LIFECYCLE_STATE = "confirmed"


class TaskReviewError(RuntimeError):
    """Sanitized base error for an invalid or conflicting review command."""


class CandidateNotFoundError(TaskReviewError):
    """A referenced local candidate no longer exists."""


class StaleCandidateError(TaskReviewError):
    """The caller reviewed a different discovery algorithm revision."""


class InvalidTaskReviewError(TaskReviewError):
    """The requested grouping is inconsistent with candidate evidence."""


class TaskReviewConflictError(TaskReviewError):
    """Stored review state changed or conflicts with this command."""


class ReviewArtifactIdFactory(Protocol):
    def decision_id(self, idempotency_key: str) -> str: ...

    def task_id(self, decision_id: str, output_ordinal: int) -> str: ...

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskReviewResult:
    decision_id: str
    action: DecisionAction
    output_revisions: tuple[tuple[str, int], ...]
    applied: bool


class TaskReviewService:
    """Translate a reviewed candidate command into one atomic persistence call."""

    def __init__(
        self,
        repository: TaskRepository,
        identifiers: ReviewArtifactIdFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._identifiers = identifiers
        self._clock = clock

    def apply(
        self,
        command: TaskDecisionCommand,
        *,
        idempotency_key: str,
        decision_source: str = "person",
    ) -> TaskReviewResult:
        if not SAFE_VERSION_PATTERN.fullmatch(idempotency_key):
            raise InvalidTaskReviewError(
                "idempotency key must be a short content-free identifier"
            )

        candidate_ids = self._candidate_ids(command)
        candidates = tuple(
            self._load_candidate(candidate_id, command.expected_discovery_version)
            for candidate_id in candidate_ids
        )
        self._require_one_scope(candidates)

        decision_id = self._identifiers.decision_id(idempotency_key)
        action, decision_code, partitions = self._decision_shape(command, candidates)
        decided_at = self._clock()
        categories = self._categories(command, len(partitions))

        output_revisions = tuple(
            self._build_output_revision(
                decision_id=decision_id,
                output_ordinal=ordinal,
                candidate=candidates[0],
                session_ids=session_ids,
                category=categories[ordinal],
                action=action,
                discovery_version=command.expected_discovery_version,
                created_at=decided_at,
            )
            for ordinal, session_ids in enumerate(partitions)
        )
        decision = TaskDecisionRecord(
            decision_id=decision_id,
            action=action,
            candidate_ids=candidate_ids,
            revision_links=tuple(
                DecisionRevisionLink(
                    task_id=revision.task_id,
                    revision=revision.revision,
                    role=DecisionRevisionRole.OUTPUT,
                )
                for revision in output_revisions
            ),
            decision_schema_version=DECISION_SCHEMA_VERSION,
            decision_source=decision_source,  # type: ignore[arg-type]
            decision_code=decision_code,
            decided_at=decided_at,
        )
        try:
            applied = self._repository.apply_review_decision(
                decision,
                output_revisions,
                expected_discovery_version=command.expected_discovery_version,
            )
        except PersistenceConflictError as exc:
            raise TaskReviewConflictError("task review state conflicts") from exc
        return TaskReviewResult(
            decision_id=decision_id,
            action=action,
            output_revisions=tuple(
                (revision.task_id, revision.revision)
                for revision in output_revisions
            ),
            applied=applied,
        )

    def _load_candidate(
        self, candidate_id: str, expected_discovery_version: str
    ) -> TaskCandidateRecord:
        candidate = self._repository.get_candidate(candidate_id)
        if candidate is None:
            raise CandidateNotFoundError("task candidate does not exist")
        if candidate.discovery_version != expected_discovery_version:
            raise StaleCandidateError("task candidate discovery version is stale")
        return candidate

    @staticmethod
    def _candidate_ids(command: TaskDecisionCommand) -> tuple[str, ...]:
        if isinstance(command, MergeCandidates):
            return tuple(sorted(command.candidate_ids))
        return (command.candidate_id,)

    @staticmethod
    def _require_one_scope(candidates: tuple[TaskCandidateRecord, ...]) -> None:
        scopes = {
            (candidate.provider, candidate.installation_id, candidate.project_id)
            for candidate in candidates
        }
        if len(scopes) != 1:
            raise InvalidTaskReviewError(
                "one review decision cannot cross provider or project boundaries"
            )

    @staticmethod
    def _decision_shape(
        command: TaskDecisionCommand,
        candidates: tuple[TaskCandidateRecord, ...],
    ) -> tuple[DecisionAction, str | None, tuple[tuple[str, ...], ...]]:
        if isinstance(command, RejectCandidate):
            return DecisionAction.REJECT, command.reason.value, ()
        if isinstance(command, AcceptCandidate):
            return DecisionAction.ACCEPT, None, (candidates[0].session_ids,)
        if isinstance(command, MergeCandidates):
            session_ids = tuple(
                session_id
                for candidate in candidates
                for session_id in candidate.session_ids
            )
            if len(set(session_ids)) != len(session_ids):
                raise InvalidTaskReviewError(
                    "merged candidates cannot contain overlapping sessions"
                )
            return DecisionAction.MERGE, None, (session_ids,)

        candidate_sessions = set(candidates[0].session_ids)
        partition_sessions = {
            session_id for partition in command.partitions for session_id in partition
        }
        if candidate_sessions != partition_sessions:
            raise InvalidTaskReviewError(
                "split partitions must exactly cover the candidate sessions"
            )
        return DecisionAction.SPLIT, None, command.partitions

    @staticmethod
    def _categories(
        command: TaskDecisionCommand, output_count: int
    ) -> tuple[TaskCategory, ...]:
        if isinstance(command, (AcceptCandidate, MergeCandidates)):
            return (command.task_category,)
        if isinstance(command, SplitCandidate):
            return command.task_categories or (
                (TaskCategory.UNKNOWN,) * output_count
            )
        return ()

    def _build_output_revision(
        self,
        *,
        decision_id: str,
        output_ordinal: int,
        candidate: TaskCandidateRecord,
        session_ids: tuple[str, ...],
        category: TaskCategory,
        action: DecisionAction,
        discovery_version: str,
        created_at: datetime,
    ) -> TaskRevisionRecord:
        task_id = self._identifiers.task_id(decision_id, output_ordinal)
        fingerprint = self._identifiers.fingerprint(
            "task-revision-v1",
            (
                action.value,
                discovery_version,
                category.value,
                candidate.project_id,
                *session_ids,
            ),
        )
        return TaskRevisionRecord(
            task_id=task_id,
            revision=1,
            project_id=candidate.project_id,
            task_type=category.value,
            lifecycle_state=CONFIRMED_LIFECYCLE_STATE,
            session_ids=session_ids,
            input_fingerprint=fingerprint,
            created_at=created_at,
        )
