"""Authenticated loopback routes for explicit task lifecycle receipts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...application.task_lifecycle import (
    InvalidTaskLifecycleTransitionError,
    TaskLifecycleCorrectionCommand,
    TaskLifecycleEventKind,
    TaskLifecycleEventRecord,
    TaskLifecycleIdempotencyError,
    TaskLifecycleNotFoundError,
    TaskLifecycleRepository,
    TaskLifecycleService,
    TaskLifecycleSnapshot,
    TaskLifecycleStaleHeadError,
    TaskLifecycleStaleRevisionError,
    TaskLifecycleState,
    TaskLifecycleTransitionCommand,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN


IDEMPOTENCY_HEADER = "Idempotency-Key"
Pseudonym = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=PSEUDONYM_PATTERN.pattern,
        strict=True,
    ),
]
IdempotencyKey = Annotated[
    str,
    Header(
        alias=IDEMPOTENCY_HEADER,
        min_length=1,
        max_length=128,
        pattern=SAFE_VERSION_PATTERN.pattern,
    ),
]


class LifecycleDto(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class TaskLifecycleEventDto(LifecycleDto):
    event_id: Pseudonym
    task_id: Pseudonym
    task_revision: int = Field(ge=1)
    sequence: int = Field(ge=1)
    event_kind: TaskLifecycleEventKind
    prior_state: TaskLifecycleState | None
    resulting_state: TaskLifecycleState | None
    previous_event_id: Pseudonym | None
    supersedes_event_id: Pseudonym | None
    task_input_fingerprint: Pseudonym
    command_schema_version: Literal["task-lifecycle-command-v1"]
    source: Literal["explicit_local_user"]
    actor_scope: Literal["local_user"]
    request_fingerprint: Pseudonym
    created_at: datetime

    @classmethod
    def from_record(cls, record: TaskLifecycleEventRecord) -> TaskLifecycleEventDto:
        return cls(
            event_id=record.event_id,
            task_id=record.task_id,
            task_revision=record.task_revision,
            sequence=record.sequence,
            event_kind=record.event_kind,
            prior_state=record.prior_state,
            resulting_state=record.resulting_state,
            previous_event_id=record.previous_event_id,
            supersedes_event_id=record.supersedes_event_id,
            task_input_fingerprint=record.task_input_fingerprint,
            command_schema_version="task-lifecycle-command-v1",
            source="explicit_local_user",
            actor_scope="local_user",
            request_fingerprint=record.request_fingerprint,
            created_at=record.created_at,
        )


class TaskLifecycleSnapshotDto(LifecycleDto):
    task_id: Pseudonym
    task_revision: int = Field(ge=1)
    current_task_revision: int = Field(ge=1)
    is_current_revision: bool
    current_state: TaskLifecycleState | None
    head_event_id: Pseudonym | None
    event_count: int = Field(ge=0)
    prior_revision_event_count: int = Field(ge=0)
    events: tuple[TaskLifecycleEventDto, ...]
    events_limit: int = Field(ge=1, le=100)
    events_offset: int = Field(ge=0)
    events_complete: bool

    @classmethod
    def from_record(cls, record: TaskLifecycleSnapshot) -> TaskLifecycleSnapshotDto:
        return cls(
            task_id=record.task_id,
            task_revision=record.task_revision,
            current_task_revision=record.current_task_revision,
            is_current_revision=record.is_current_revision,
            current_state=record.current_state,
            head_event_id=record.head_event_id,
            event_count=record.event_count,
            prior_revision_event_count=record.prior_revision_event_count,
            events=tuple(TaskLifecycleEventDto.from_record(item) for item in record.events),
            events_limit=record.events_limit,
            events_offset=record.events_offset,
            events_complete=(
                record.events_offset + len(record.events) >= record.event_count
            ),
        )


class TaskLifecycleListResponse(LifecycleDto):
    lifecycles: tuple[TaskLifecycleSnapshotDto, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class TaskLifecycleTransitionRequest(LifecycleDto):
    expected_head_event_id: Pseudonym | None
    state: TaskLifecycleState


class TaskLifecycleCorrectionRequest(LifecycleDto):
    expected_head_event_id: Pseudonym
    supersedes_event_id: Pseudonym


class TaskLifecycleMutationResponse(LifecycleDto):
    event: TaskLifecycleEventDto
    state: TaskLifecycleState | None
    head_event_id: Pseudonym

    @classmethod
    def from_event(
        cls, event: TaskLifecycleEventRecord
    ) -> TaskLifecycleMutationResponse:
        return cls(
            event=TaskLifecycleEventDto.from_record(event),
            state=event.resulting_state,
            head_event_id=event.event_id,
        )


class LifecycleQueryStore(Protocol):
    def task_lifecycle_repository(self) -> TaskLifecycleRepository: ...


def _repository(request: Request) -> TaskLifecycleRepository:
    store = cast(LifecycleQueryStore, request.app.state.database)
    return store.task_lifecycle_repository()


def create_task_lifecycle_router(
    require_local_token: Callable[..., None],
    service: TaskLifecycleService | None,
) -> APIRouter:
    """Mount read routes always and explicit mutation routes only when composed."""

    router = APIRouter(
        prefix="/v1",
        tags=["task-lifecycle"],
        dependencies=[Depends(require_local_token)],
    )

    @router.get("/task-lifecycles", response_model=TaskLifecycleListResponse)
    def lifecycle_list(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        event_limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> TaskLifecycleListResponse:
        records = _repository(request).list_current_snapshots(
            limit=limit,
            offset=offset,
            events_limit=event_limit,
        )
        return TaskLifecycleListResponse(
            lifecycles=tuple(TaskLifecycleSnapshotDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/tasks/{task_id}/revisions/{task_revision}/lifecycle",
        response_model=TaskLifecycleSnapshotDto,
    )
    def lifecycle_detail(
        request: Request,
        task_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        task_revision: Annotated[int, Path(ge=1)],
        event_limit: Annotated[int, Query(ge=1, le=100)] = 100,
        event_offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TaskLifecycleSnapshotDto:
        record = _repository(request).get_snapshot(
            task_id,
            task_revision,
            events_limit=event_limit,
            events_offset=event_offset,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="task revision not found")
        return TaskLifecycleSnapshotDto.from_record(record)

    if service is None:
        return router

    def apply_error(error: Exception) -> None:
        if isinstance(error, TaskLifecycleNotFoundError):
            raise HTTPException(status_code=404, detail="task revision not found") from error
        if isinstance(
            error,
            (
                TaskLifecycleStaleRevisionError,
                TaskLifecycleStaleHeadError,
                TaskLifecycleIdempotencyError,
            ),
        ):
            raise HTTPException(status_code=409, detail="task lifecycle conflicts") from error
        if isinstance(error, InvalidTaskLifecycleTransitionError):
            raise HTTPException(status_code=422, detail="invalid task lifecycle change") from error
        raise error

    @router.post(
        "/tasks/{task_id}/revisions/{task_revision}/lifecycle/transitions",
        response_model=TaskLifecycleMutationResponse,
        status_code=201,
    )
    def transition(
        payload: TaskLifecycleTransitionRequest,
        response: Response,
        task_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        task_revision: Annotated[int, Path(ge=1)],
        idempotency_key: IdempotencyKey,
    ) -> TaskLifecycleMutationResponse:
        """Append a user transition (201); an exact idempotent replay returns 200."""

        try:
            result = service.transition(
                TaskLifecycleTransitionCommand(
                    task_id=task_id,
                    task_revision=task_revision,
                    expected_head_event_id=payload.expected_head_event_id,
                    state=payload.state,
                ),
                idempotency_key=idempotency_key,
            )
        except Exception as error:
            apply_error(error)
            raise AssertionError("unreachable")
        response.status_code = 201 if result.applied else 200
        return TaskLifecycleMutationResponse.from_event(result.event)

    @router.post(
        "/tasks/{task_id}/revisions/{task_revision}/lifecycle/corrections",
        response_model=TaskLifecycleMutationResponse,
        status_code=201,
    )
    def correct(
        payload: TaskLifecycleCorrectionRequest,
        response: Response,
        task_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        task_revision: Annotated[int, Path(ge=1)],
        idempotency_key: IdempotencyKey,
    ) -> TaskLifecycleMutationResponse:
        """Append a user correction (201); an exact idempotent replay returns 200."""

        try:
            result = service.correct(
                TaskLifecycleCorrectionCommand(
                    task_id=task_id,
                    task_revision=task_revision,
                    expected_head_event_id=payload.expected_head_event_id,
                    supersedes_event_id=payload.supersedes_event_id,
                ),
                idempotency_key=idempotency_key,
            )
        except Exception as error:
            apply_error(error)
            raise AssertionError("unreachable")
        response.status_code = 201 if result.applied else 200
        return TaskLifecycleMutationResponse.from_event(result.event)

    return router
