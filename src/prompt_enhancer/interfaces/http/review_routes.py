"""Authenticated task-review commands over one transactional service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException

from ...application.discovery import (
    CandidateNotFoundError,
    InvalidTaskReviewError,
    StaleCandidateError,
    TaskDecisionCommand,
    TaskReviewConflictError,
    TaskReviewResult,
)
from ...domain import SAFE_VERSION_PATTERN
from .review_dto import (
    AcceptTaskRequest,
    MergeTasksRequest,
    RejectTaskRequest,
    SplitTaskRequest,
    TaskReviewResponse,
)


IDEMPOTENCY_HEADER = "Idempotency-Key"
IdempotencyKey = Annotated[
    str,
    Header(
        alias=IDEMPOTENCY_HEADER,
        min_length=1,
        max_length=128,
        pattern=SAFE_VERSION_PATTERN.pattern,
    ),
]


class ReviewCommandService(Protocol):
    """Narrow application port consumed by the HTTP command adapter."""

    def apply(
        self,
        command: TaskDecisionCommand,
        *,
        idempotency_key: str,
    ) -> TaskReviewResult: ...


def create_task_review_router(
    require_local_token: Callable[..., None],
    service: ReviewCommandService,
) -> APIRouter:
    """Expose only explicit accept/reject/merge/split decision commands."""

    router = APIRouter(
        prefix="/v1/task-decisions",
        tags=["task-review"],
        dependencies=[Depends(require_local_token)],
    )

    def apply(
        command: TaskDecisionCommand,
        idempotency_key: str,
    ) -> TaskReviewResponse:
        try:
            result = service.apply(command, idempotency_key=idempotency_key)
        except CandidateNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate not found") from exc
        except StaleCandidateError as exc:
            raise HTTPException(status_code=409, detail="candidate version is stale") from exc
        except TaskReviewConflictError as exc:
            raise HTTPException(status_code=409, detail="task review conflicts") from exc
        except InvalidTaskReviewError as exc:
            raise HTTPException(status_code=422, detail="invalid task review") from exc
        return TaskReviewResponse.from_result(result)

    @router.post("/accept", response_model=TaskReviewResponse)
    def accept(
        request: AcceptTaskRequest,
        idempotency_key: IdempotencyKey,
    ) -> TaskReviewResponse:
        return apply(request.to_command(), idempotency_key)

    @router.post("/reject", response_model=TaskReviewResponse)
    def reject(
        request: RejectTaskRequest,
        idempotency_key: IdempotencyKey,
    ) -> TaskReviewResponse:
        return apply(request.to_command(), idempotency_key)

    @router.post("/merge", response_model=TaskReviewResponse)
    def merge(
        request: MergeTasksRequest,
        idempotency_key: IdempotencyKey,
    ) -> TaskReviewResponse:
        try:
            command = request.to_command()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid task review") from exc
        return apply(command, idempotency_key)

    @router.post("/split", response_model=TaskReviewResponse)
    def split(
        request: SplitTaskRequest,
        idempotency_key: IdempotencyKey,
    ) -> TaskReviewResponse:
        try:
            command = request.to_command()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid task review") from exc
        return apply(command, idempotency_key)

    return router
