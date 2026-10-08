"""Authenticated, content-free durable analysis job commands and queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from pydantic import Field, field_validator

from ...application.jobs import (
    AnalysisJobConflictError,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobNotFoundError,
    AnalysisJobRecord,
    AnalysisJobService,
    AnalysisJobState,
)
from ...domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    Provider,
    StrictModel,
)


class AnalysisJobCreateRequest(StrictModel):
    kind: AnalysisJobKind = AnalysisJobKind.SESSION_QUALITY
    provider: Provider
    project_id: str
    session_id: str
    input_fingerprint: str
    provenance_fingerprint: str
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=100)
    estimator_plan_version: str
    redactor_version: str
    provider_schema_version: str
    max_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("kind")
    @classmethod
    def public_kind(cls, value: AnalysisJobKind) -> AnalysisJobKind:
        if value is AnalysisJobKind.ESTIMATOR_EXECUTION:
            raise ValueError(
                "estimator execution requires the approved runtime launch boundary"
            )
        return value

    @field_validator(
        "project_id",
        "session_id",
        "input_fingerprint",
        "provenance_fingerprint",
    )
    @classmethod
    def safe_ids(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("identifier must be pseudonymous")
        return value

    @field_validator(
        "estimator_plan_version",
        "redactor_version",
        "provider_schema_version",
    )
    @classmethod
    def safe_versions(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("version must be content-free")
        return value

    @field_validator("metric_keys")
    @classmethod
    def canonical_metric_set(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("metric selection contains duplicates")
        for value in values:
            if SAFE_VERSION_PATTERN.fullmatch(value) is None:
                raise ValueError("metric key must be content-free")
        return tuple(sorted(values))

    def identity(self) -> AnalysisJobIdentity:
        return AnalysisJobIdentity(
            kind=self.kind,
            provider=self.provider,
            project_id=self.project_id,
            session_id=self.session_id,
            input_fingerprint=self.input_fingerprint,
            provenance_fingerprint=self.provenance_fingerprint,
            metric_keys=self.metric_keys,
            estimator_plan_version=self.estimator_plan_version,
            redactor_version=self.redactor_version,
            provider_schema_version=self.provider_schema_version,
            automation_grant_id=None,
            local_only=True,
        )


class AnalysisJobResponse(StrictModel):
    """Browser-safe queue state; worker lease credentials never cross HTTP."""

    job_id: str
    identity: AnalysisJobIdentity
    state: AnalysisJobState
    stage_number: int | None
    progress_completed: int
    progress_total: int
    attempt_count: int
    max_attempts: int
    available_at: datetime
    cancel_requested: bool
    last_error_code: str | None
    terminal_reason_code: str | None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None

    @classmethod
    def from_record(cls, record: AnalysisJobRecord) -> AnalysisJobResponse:
        return cls(
            job_id=record.job_id,
            identity=record.identity,
            state=record.state,
            stage_number=record.stage_number,
            progress_completed=record.progress_completed,
            progress_total=record.progress_total,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            available_at=record.available_at,
            cancel_requested=record.cancel_requested,
            last_error_code=record.last_error_code,
            terminal_reason_code=record.terminal_reason_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
            terminal_at=record.terminal_at,
        )


class AnalysisJobEnqueueResponse(StrictModel):
    job: AnalysisJobResponse
    created: bool


class AnalysisJobPageResponse(StrictModel):
    jobs: tuple[AnalysisJobResponse, ...]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


def create_analysis_job_router(
    require_local_auth: Callable[..., None],
    service: AnalysisJobService,
) -> APIRouter:
    def prevent_private_caching(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"

    router = APIRouter(
        prefix="/v1",
        tags=["analysis-jobs"],
        dependencies=[
            Depends(require_local_auth),
            Depends(prevent_private_caching),
        ],
    )

    @router.post(
        "/analysis-jobs",
        response_model=AnalysisJobEnqueueResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={409: {"description": "Job identity conflict"}},
    )
    def enqueue_job(
        payload: Annotated[AnalysisJobCreateRequest, Body()],
    ) -> AnalysisJobEnqueueResponse:
        try:
            outcome = service.enqueue(
                payload.identity(),
                max_attempts=payload.max_attempts,
            )
            return AnalysisJobEnqueueResponse(
                job=AnalysisJobResponse.from_record(outcome.job),
                created=outcome.created,
            )
        except AnalysisJobConflictError:
            raise HTTPException(
                status_code=409,
                detail={"code": "analysis_job_conflict"},
            ) from None

    @router.get("/analysis-jobs", response_model=AnalysisJobPageResponse)
    def list_jobs(
        state_filter: Annotated[AnalysisJobState | None, Query(alias="state")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AnalysisJobPageResponse:
        page = service.list(state=state_filter, limit=limit, offset=offset)
        return AnalysisJobPageResponse(
            jobs=tuple(AnalysisJobResponse.from_record(job) for job in page.jobs),
            limit=page.limit,
            offset=page.offset,
        )

    @router.get(
        "/analysis-jobs/{job_id}",
        response_model=AnalysisJobResponse,
        responses={404: {"description": "Job not found"}},
    )
    def get_job(
        job_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AnalysisJobResponse:
        try:
            return AnalysisJobResponse.from_record(service.get(job_id))
        except AnalysisJobNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={"code": "analysis_job_not_found"},
            ) from None

    @router.get(
        "/sessions/{session_id}/analysis-jobs/latest",
        response_model=AnalysisJobResponse,
        responses={404: {"description": "No job for the selected session"}},
    )
    def latest_session_job(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AnalysisJobResponse:
        try:
            job = service.latest_for_session(session_id)
        except AnalysisJobNotFoundError:
            job = None
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "analysis_job_not_found"},
            )
        return AnalysisJobResponse.from_record(job)

    @router.post(
        "/analysis-jobs/{job_id}/cancellation",
        response_model=AnalysisJobResponse,
        responses={404: {"description": "Job not found"}},
    )
    def cancel_job(
        job_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AnalysisJobResponse:
        try:
            return AnalysisJobResponse.from_record(service.cancel(job_id))
        except AnalysisJobNotFoundError:
            raise HTTPException(
                status_code=404,
                detail={"code": "analysis_job_not_found"},
            ) from None
        except AnalysisJobConflictError:
            raise HTTPException(
                status_code=409,
                detail={"code": "analysis_job_conflict"},
            ) from None

    return router


__all__ = [
    "AnalysisJobCreateRequest",
    "AnalysisJobEnqueueResponse",
    "AnalysisJobPageResponse",
    "AnalysisJobResponse",
    "create_analysis_job_router",
]
