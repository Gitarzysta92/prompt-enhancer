"""Authenticated private API for the continuous local ensemble watch."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Callable, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response
from pydantic import Field, field_validator, model_validator

from ...application.analysis.model_ensemble_watch import (
    MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    ModelEnsembleAttemptRecord,
    ModelEnsembleAttemptStageReceipt,
    ModelEnsembleCanonicalHead,
    ModelEnsembleWatchConflictError,
    ModelEnsembleWatchInputError,
    ModelEnsembleWatchNotFoundError,
    ModelEnsembleWatchRecord,
    ModelEnsembleWatchService,
    ModelEnsembleTrajectoryPage,
)
from ...application.analysis.session_model_ensemble import (
    ModelEnsembleCompatibilityError,
    ModelEnsembleConsentError,
    ModelEnsembleInputError,
    ModelEnsemblePersistenceError,
    ModelEnsembleSelectionError,
    SessionModelEnsembleRunRecord,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .model_ensemble_routes import ModelEnsembleRunDto
from .session_provider_contracts import SessionProviderFailureResponse


_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class ModelEnsembleWatchRequest(StrictModel):
    project_id: str
    max_messages: int = Field(default=100, ge=1, le=100)
    confirmation: Literal[MODEL_ENSEMBLE_WATCH_CONFIRMATION]

    @field_validator("project_id")
    @classmethod
    def safe_project(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("project selector is invalid")
        return value


class ModelEnsembleWatchDto(StrictModel):
    watch_id: str
    provider: Literal[Provider.CODEX, Provider.CLAUDE_CODE]
    project_id: str
    session_id: str
    max_messages: int = Field(ge=1, le=100)
    state: Literal["queued", "running", "idle", "failed", "disabled"]
    generation: int
    progress_completed: int
    progress_total: Literal[10]
    has_result: bool
    last_error_code: str | None
    # Older clients omitted this metadata. Unknown must not imply automatic
    # retry; current records always provide the authoritative boolean/reason.
    quarantined: bool | None = None
    quarantine_reason_code: str | None = Field(default=None, pattern=SAFE_VERSION_PATTERN.pattern)
    next_check_at: datetime
    updated_at: datetime
    serial_model_execution: Literal[True] = True
    process_isolated_model_release: Literal[True] = True
    cuda_resource_retry_on_cpu: Literal[True] = True
    content_persisted: Literal[False] = False
    calibrated_as_truth: Literal[False] = False

    @model_validator(mode="after")
    def matching_quarantine(self) -> "ModelEnsembleWatchDto":
        if (self.quarantined is True) != (self.quarantine_reason_code is not None):
            raise ValueError("watch quarantine and reason must agree")
        if self.quarantined is True and self.state not in {"failed", "disabled"}:
            raise ValueError("only a stopped watch may be quarantined")
        return self

    @classmethod
    def from_record(cls, record: ModelEnsembleWatchRecord) -> "ModelEnsembleWatchDto":
        return cls(
            watch_id=record.watch_id,
            provider=record.provider,
            project_id=record.project_id,
            session_id=record.session_id,
            max_messages=record.max_messages,
            state=record.state.value,
            generation=record.generation,
            progress_completed=record.progress_completed,
            progress_total=10,
            has_result=record.latest_run_id is not None,
            last_error_code=record.last_error_code,
            quarantined=record.quarantined,
            quarantine_reason_code=record.quarantine_reason_code,
            next_check_at=record.next_check_at,
            updated_at=record.updated_at,
        )


class ModelEnsembleWatchSnapshotDto(StrictModel):
    watch: ModelEnsembleWatchDto
    latest_run: ModelEnsembleRunDto | None


class ModelEnsembleAttemptDto(StrictModel):
    attempt_id: str
    watch_id: str
    generation: int
    state: Literal["running", "completed", "partial", "failed", "cancelled"]
    prior_head_run_id: str | None
    published_run_id: str | None
    progress_completed: int = Field(ge=0, le=32)
    progress_total: int = Field(ge=1, le=32)
    stage_count: int = Field(ge=0, le=32)
    warning_count: int = Field(ge=0, le=32)
    error_code: str | None
    requested_at: datetime
    started_at: datetime
    completed_at: datetime | None
    content_persisted: Literal[False] = False

    @classmethod
    def from_record(
        cls, value: ModelEnsembleAttemptRecord
    ) -> "ModelEnsembleAttemptDto":
        return cls(**value.model_dump(), content_persisted=False)


class ModelEnsembleAttemptStageDto(StrictModel):
    stage_ordinal: int = Field(ge=0, le=31)
    stage_key: str
    state: Literal[
        "completed", "unavailable", "resource_exhausted", "failed", "cancelled"
    ]
    model_key: str | None
    repository_id: str | None
    revision: str | None
    error_code: str | None
    device: Literal["cpu", "cuda", "mps"] | None
    quantization: Literal["none", "bitsandbytes_nf4"]
    inference_latency_ms: float | None = Field(default=None, ge=0)
    peak_accelerator_memory_mb: float | None = Field(default=None, ge=0)
    process_rss_mb: float | None = Field(default=None, ge=0)
    evaluated_case_count: int | None = Field(default=None, ge=0)
    contributed_case_count: int | None = Field(default=None, ge=0)
    unloaded_after_stage: bool | None
    completed_at: datetime

    @classmethod
    def from_record(
        cls, value: ModelEnsembleAttemptStageReceipt
    ) -> "ModelEnsembleAttemptStageDto":
        return cls.model_validate(value.model_dump(exclude={"attempt_id"}))


class ModelEnsembleAttemptSnapshotDto(StrictModel):
    attempt: ModelEnsembleAttemptDto
    stages: tuple[ModelEnsembleAttemptStageDto, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def exact_terminal_graph(self) -> "ModelEnsembleAttemptSnapshotDto":
        if self.attempt.state == "running":
            if self.stages:
                raise ValueError("running attempt snapshots cannot claim sealed stages")
        elif len(self.stages) != self.attempt.stage_count:
            raise ValueError("terminal attempt snapshot stage graph is incomplete")
        return self


class ModelEnsembleAttemptPageDto(StrictModel):
    watch_id: str
    attempts: tuple[ModelEnsembleAttemptDto, ...] = Field(max_length=60)
    content_persisted: Literal[False] = False


class ModelEnsembleCanonicalHeadDto(StrictModel):
    schema_version: Literal["analysis-snapshot-v2"] = "analysis-snapshot-v2"
    watch: ModelEnsembleWatchDto
    head_run_id: str | None
    head_generation: int | None
    latest_attempt: ModelEnsembleAttemptDto | None
    stages: tuple[ModelEnsembleAttemptStageDto, ...] = Field(max_length=32)
    content_persisted: Literal[False] = False

    @classmethod
    def from_record(
        cls, value: ModelEnsembleCanonicalHead
    ) -> "ModelEnsembleCanonicalHeadDto":
        return cls(
            watch=ModelEnsembleWatchDto.from_record(value.watch),
            head_run_id=value.head_run_id,
            head_generation=value.head_generation,
            latest_attempt=(
                None
                if value.latest_attempt is None
                else ModelEnsembleAttemptDto.from_record(value.latest_attempt)
            ),
            stages=tuple(
                ModelEnsembleAttemptStageDto.from_record(stage)
                for stage in value.stages
            ),
        )


class ModelEnsembleRunReader(Protocol):
    def get(self, run_id: str) -> SessionModelEnsembleRunRecord | None: ...


class ModelEnsembleWatchSelectionFailureDetail(StrictModel):
    code: Literal["session_not_in_safe_index"]
    message: Literal["selected session is not indexed"]


class ModelEnsembleWatchSelectionFailureResponse(StrictModel):
    detail: ModelEnsembleWatchSelectionFailureDetail


class ModelEnsembleWatchUnavailableFailureDetail(StrictModel):
    code: Literal["model_ensemble_persistence_failed"]
    message: Literal["model ensemble result is unavailable"]


class ModelEnsembleWatchUnavailableFailureResponse(StrictModel):
    detail: ModelEnsembleWatchUnavailableFailureDetail


def _watch_failure(error: Exception) -> HTTPException:
    if isinstance(error, ModelEnsembleConsentError):
        return HTTPException(403, detail={"code": error.code, "message": "redacted-content consent required"})
    if isinstance(error, ModelEnsembleSelectionError):
        return HTTPException(404, detail={"code": error.code, "message": "selected session is not indexed"})
    if isinstance(error, ModelEnsembleCompatibilityError):
        return HTTPException(409, detail={"code": error.code, "message": "provider compatibility is not verified"})
    if isinstance(error, ModelEnsembleWatchConflictError):
        return HTTPException(409, detail={"code": error.code, "message": "model ensemble watch conflicts with local state"})
    if isinstance(error, ModelEnsembleWatchNotFoundError):
        return HTTPException(404, detail={"code": error.code, "message": "model ensemble watch was not found"})
    if isinstance(error, (ModelEnsembleWatchInputError, ModelEnsembleInputError)):
        return HTTPException(422, detail={"code": error.code, "message": "model ensemble watch request is invalid"})
    if isinstance(error, ModelEnsemblePersistenceError):
        return HTTPException(503, detail={"code": error.code, "message": "model ensemble result is unavailable"})
    raise TypeError("unsupported model ensemble watch error")


def create_model_ensemble_watch_router(
    require_local_auth: Callable[..., None],
    service: ModelEnsembleWatchService,
    ensemble: ModelEnsembleRunReader,
    provider_resolver: Callable[[str], Provider],
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["local-model-ensemble-watch"],
        dependencies=[Depends(require_local_auth)],
    )
    v2 = APIRouter(
        prefix="/v2",
        tags=["local-model-ensemble-workspace"],
        dependencies=[Depends(require_local_auth)],
    )

    def snapshot(record: ModelEnsembleWatchRecord) -> ModelEnsembleWatchSnapshotDto:
        latest = None
        if record.latest_run_id is not None:
            try:
                latest = ensemble.get(record.latest_run_id)
            except (ModelEnsembleInputError, ModelEnsemblePersistenceError) as error:
                raise _watch_failure(error) from None
            if latest is None or latest.session_id != record.session_id:
                raise _watch_failure(
                    ModelEnsemblePersistenceError(
                        "watch result binding is unavailable"
                    )
                )
        return ModelEnsembleWatchSnapshotDto(
            watch=ModelEnsembleWatchDto.from_record(record),
            latest_run=None if latest is None else ModelEnsembleRunDto.from_record(latest),
        )

    @router.put(
        "/sessions/{session_id}/model-ensemble-watch",
        response_model=ModelEnsembleWatchSnapshotDto,
        responses={
            404: {
                "model": (
                    ModelEnsembleWatchSelectionFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            503: {
                "model": (
                    ModelEnsembleWatchUnavailableFailureResponse
                    | SessionProviderFailureResponse
                )
            },
        },
    )
    def enable_watch(
        payload: ModelEnsembleWatchRequest,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleWatchSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            record = service.enable(
                provider=provider_resolver(session_id),
                project_id=payload.project_id,
                session_id=session_id,
                max_messages=payload.max_messages,
                confirmation=payload.confirmation,
            )
        except (
            ModelEnsembleCompatibilityError,
            ModelEnsembleConsentError,
            ModelEnsembleInputError,
            ModelEnsembleSelectionError,
            ModelEnsembleWatchConflictError,
            ModelEnsembleWatchInputError,
        ) as error:
            raise _watch_failure(error) from None
        return snapshot(record)

    @router.get(
        "/model-ensemble-watch/active",
        response_model=ModelEnsembleWatchSnapshotDto,
    )
    def active_watch(response: Response) -> ModelEnsembleWatchSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        record = service.get_active()
        if record is None:
            raise HTTPException(404, detail="active model ensemble watch not found")
        return snapshot(record)

    @router.post(
        "/model-ensemble-watches/{watch_id}/refresh",
        response_model=ModelEnsembleWatchSnapshotDto,
    )
    def refresh_watch(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleWatchSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            record = service.refresh(watch_id)
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None
        return snapshot(record)

    @router.delete(
        "/model-ensemble-watches/{watch_id}",
        response_model=ModelEnsembleWatchSnapshotDto,
    )
    def disable_watch(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleWatchSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            record = service.disable(watch_id)
        except (ModelEnsembleWatchInputError, ModelEnsembleWatchNotFoundError) as error:
            raise _watch_failure(error) from None
        return snapshot(record)

    @router.get(
        "/model-ensemble-watches/{watch_id}/trajectory",
        response_model=ModelEnsembleTrajectoryPage,
    )
    def watch_trajectory(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=60)] = 12,
        before_generation: Annotated[
            int | None,
            Query(ge=1, le=1_000_000_000),
        ] = None,
    ) -> ModelEnsembleTrajectoryPage:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return service.trajectory(
                watch_id,
                before_generation=before_generation,
                limit=limit,
            )
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None

    @v2.get(
        "/model-ensemble-watch/active/head",
        response_model=ModelEnsembleCanonicalHeadDto,
    )
    def active_canonical_head(response: Response) -> ModelEnsembleCanonicalHeadDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return ModelEnsembleCanonicalHeadDto.from_record(
                service.canonical_head()
            )
        except ModelEnsembleWatchNotFoundError as error:
            raise _watch_failure(error) from None

    @v2.get(
        "/model-ensemble-watches/{watch_id}/head",
        response_model=ModelEnsembleCanonicalHeadDto,
    )
    def canonical_head(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleCanonicalHeadDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return ModelEnsembleCanonicalHeadDto.from_record(
                service.canonical_head(watch_id)
            )
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None

    @v2.get(
        "/sessions/{session_id}/model-ensemble-head",
        response_model=ModelEnsembleCanonicalHeadDto,
    )
    def session_canonical_head(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleCanonicalHeadDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return ModelEnsembleCanonicalHeadDto.from_record(
                service.canonical_head_for_session(session_id)
            )
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None

    @v2.post(
        "/model-ensemble-watches/{watch_id}/analysis",
        response_model=ModelEnsembleCanonicalHeadDto,
    )
    def enqueue_analysis(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleCanonicalHeadDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            service.refresh(watch_id)
            return ModelEnsembleCanonicalHeadDto.from_record(
                service.canonical_head(watch_id)
            )
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None

    @v2.delete(
        "/model-ensemble-watches/{watch_id}/attempts/active",
        response_model=ModelEnsembleCanonicalHeadDto,
    )
    def cancel_analysis(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleCanonicalHeadDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return ModelEnsembleCanonicalHeadDto.from_record(service.cancel(watch_id))
        except (
            ModelEnsembleWatchConflictError,
            ModelEnsembleWatchInputError,
        ) as error:
            raise _watch_failure(error) from None

    @v2.get(
        "/model-ensemble-watches/{watch_id}/attempts",
        response_model=ModelEnsembleAttemptPageDto,
    )
    def analysis_attempts(
        response: Response,
        watch_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=60)] = 12,
    ) -> ModelEnsembleAttemptPageDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            attempts = service.attempts(watch_id, limit=limit)
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None
        return ModelEnsembleAttemptPageDto(
            watch_id=watch_id,
            attempts=tuple(
                ModelEnsembleAttemptDto.from_record(item) for item in attempts
            ),
        )

    @v2.get(
        "/model-ensemble-attempts/{attempt_id}",
        response_model=ModelEnsembleAttemptSnapshotDto,
    )
    def analysis_attempt(
        response: Response,
        attempt_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelEnsembleAttemptSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            attempt, stages = service.attempt_snapshot(attempt_id)
        except (
            ModelEnsembleWatchInputError,
            ModelEnsembleWatchNotFoundError,
        ) as error:
            raise _watch_failure(error) from None
        return ModelEnsembleAttemptSnapshotDto(
            attempt=ModelEnsembleAttemptDto.from_record(attempt),
            stages=tuple(
                ModelEnsembleAttemptStageDto.from_record(stage) for stage in stages
            ),
        )

    @v2.get(
        "/model-ensemble-snapshots/{run_id}",
        response_model=ModelEnsembleRunDto,
    )
    def immutable_snapshot(
        response: Response,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        if_none_match: Annotated[str | None, Header()] = None,
    ) -> ModelEnsembleRunDto | Response:
        try:
            run = ensemble.get(run_id)
        except (ModelEnsembleInputError, ModelEnsemblePersistenceError) as error:
            raise _watch_failure(error) from None
        if run is None:
            raise HTTPException(
                404,
                detail={
                    "code": "model_ensemble_snapshot_not_found",
                    "message": "model ensemble snapshot was not found",
                },
            )
        etag = f'"{run_id}"'
        if if_none_match == etag:
            return Response(status_code=304, headers={**_PRIVATE_HEADERS, "ETag": etag})
        response.headers.update(_PRIVATE_HEADERS)
        response.headers["ETag"] = etag
        return ModelEnsembleRunDto.from_record(run)

    container = APIRouter()
    container.include_router(router)
    container.include_router(v2)
    return container


__all__ = [
    "ModelEnsembleWatchDto",
    "ModelEnsembleAttemptDto",
    "ModelEnsembleAttemptPageDto",
    "ModelEnsembleAttemptSnapshotDto",
    "ModelEnsembleAttemptStageDto",
    "ModelEnsembleCanonicalHeadDto",
    "ModelEnsembleWatchRequest",
    "ModelEnsembleWatchSnapshotDto",
    "create_model_ensemble_watch_router",
]
