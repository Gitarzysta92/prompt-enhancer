"""Authenticated command route for deterministic task analysis."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path

from ...application.analysis import (
    TaskAnalysisConflictError,
    TaskAnalysisExecutionError,
    TaskAnalysisInputError,
    TaskAnalysisOutcome,
    TaskRevisionNotFoundError,
)
from ...domain import PSEUDONYM_PATTERN
from .analysis_dto import TaskAnalysisResponse
from .review_routes import IdempotencyKey


class TaskAnalysisCommandService(Protocol):
    """Narrow application port consumed by the HTTP command adapter."""

    def run(
        self,
        task_id: str,
        task_revision: int,
        *,
        idempotency_key: str,
    ) -> TaskAnalysisOutcome: ...


def create_task_analysis_router(
    require_local_token: Callable[..., None],
    service: TaskAnalysisCommandService,
) -> APIRouter:
    """Expose one bounded analysis command with sanitized error responses."""

    router = APIRouter(
        prefix="/v1/tasks",
        tags=["task-analysis"],
        dependencies=[Depends(require_local_token)],
    )

    @router.post(
        "/{task_id}/revisions/{revision}/analysis-runs",
        response_model=TaskAnalysisResponse,
    )
    def analyze_task_revision(
        task_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        revision: Annotated[int, Path(ge=1)],
        idempotency_key: IdempotencyKey,
    ) -> TaskAnalysisResponse:
        try:
            outcome = service.run(
                task_id,
                revision,
                idempotency_key=idempotency_key,
            )
        except TaskRevisionNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="task revision not found"
            ) from exc
        except TaskAnalysisConflictError as exc:
            raise HTTPException(
                status_code=409, detail="task analysis conflicts"
            ) from exc
        except TaskAnalysisInputError as exc:
            raise HTTPException(
                status_code=422, detail="task analysis input is unavailable"
            ) from exc
        except TaskAnalysisExecutionError as exc:
            raise HTTPException(
                status_code=500, detail="task analysis failed"
            ) from exc
        return TaskAnalysisResponse.from_outcome(outcome)

    return router
