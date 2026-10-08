"""Strict HTTP command DTOs for explicit, local task-review decisions."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ...application.discovery import (
    AcceptCandidate,
    MergeCandidates,
    RejectCandidate,
    RejectionReason,
    SplitCandidate,
    TaskCategory,
    TaskReviewResult,
)
from ...application.persistence import DecisionAction
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN


Pseudonym = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
        strict=True,
    ),
]
SafeVersion = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=SAFE_VERSION_PATTERN.pattern,
        strict=True,
    ),
]
CandidateSet = Annotated[tuple[Pseudonym, ...], Field(min_length=2, max_length=100)]
Partition = Annotated[tuple[Pseudonym, ...], Field(min_length=1, max_length=100)]
PartitionSet = Annotated[tuple[Partition, ...], Field(min_length=2, max_length=100)]


class CommandDto(BaseModel):
    """Reject unexpected fields while accepting JSON enum string values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class AcceptTaskRequest(CommandDto):
    candidate_id: Pseudonym
    expected_discovery_version: SafeVersion
    task_category: TaskCategory = TaskCategory.UNKNOWN

    def to_command(self) -> AcceptCandidate:
        return AcceptCandidate(
            candidate_id=self.candidate_id,
            expected_discovery_version=self.expected_discovery_version,
            task_category=self.task_category,
        )


class RejectTaskRequest(CommandDto):
    candidate_id: Pseudonym
    expected_discovery_version: SafeVersion
    reason: RejectionReason

    def to_command(self) -> RejectCandidate:
        return RejectCandidate(
            candidate_id=self.candidate_id,
            expected_discovery_version=self.expected_discovery_version,
            reason=self.reason,
        )


class MergeTasksRequest(CommandDto):
    candidate_ids: CandidateSet
    expected_discovery_version: SafeVersion
    task_category: TaskCategory = TaskCategory.UNKNOWN

    def to_command(self) -> MergeCandidates:
        return MergeCandidates(
            candidate_ids=self.candidate_ids,
            expected_discovery_version=self.expected_discovery_version,
            task_category=self.task_category,
        )


class SplitTaskRequest(CommandDto):
    candidate_id: Pseudonym
    partitions: PartitionSet
    expected_discovery_version: SafeVersion
    task_categories: tuple[TaskCategory, ...] = ()

    def to_command(self) -> SplitCandidate:
        return SplitCandidate(
            candidate_id=self.candidate_id,
            partitions=self.partitions,
            expected_discovery_version=self.expected_discovery_version,
            task_categories=self.task_categories,
        )


class OutputRevisionDto(CommandDto):
    task_id: Pseudonym
    revision: int = Field(ge=1)


class TaskReviewResponse(CommandDto):
    decision_id: Pseudonym
    action: DecisionAction
    output_revisions: tuple[OutputRevisionDto, ...]
    applied: bool

    @classmethod
    def from_result(cls, result: TaskReviewResult) -> TaskReviewResponse:
        return cls(
            decision_id=result.decision_id,
            action=result.action,
            output_revisions=tuple(
                OutputRevisionDto(task_id=task_id, revision=revision)
                for task_id, revision in result.output_revisions
            ),
            applied=result.applied,
        )
