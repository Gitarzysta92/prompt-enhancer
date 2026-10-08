"""Strict, content-free DTOs for task-analysis commands."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ...application.analysis import TaskAnalysisOutcome
from ...application.persistence import AnalysisRunStatus
from ...domain import PSEUDONYM_PATTERN


Pseudonym = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
        strict=True,
    ),
]


class TaskAnalysisResponse(BaseModel):
    """Public command result; deliberately excludes task evidence and content."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )

    run_id: Pseudonym
    status: AnalysisRunStatus
    result_count: int = Field(ge=0)
    applied: bool

    @classmethod
    def from_outcome(cls, outcome: TaskAnalysisOutcome) -> TaskAnalysisResponse:
        return cls(
            run_id=outcome.run_id,
            status=outcome.status,
            result_count=outcome.result_count,
            applied=outcome.applied,
        )
