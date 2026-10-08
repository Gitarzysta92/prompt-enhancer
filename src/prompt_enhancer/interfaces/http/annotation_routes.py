"""Annotation surfaces (ADR 0017): agent path under /v1/annotation, central server under /central/v1."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...application.annotation import (
    AllowanceState,
    AnnotationError,
    AnnotationService,
    CentralAnnotationServer,
    CentralBatch,
    CentralBatchResult,
    Metaprompt,
    RemoteAnnotationDisclosure,
    RemoteAnnotationClient,
    RemoteSubmitRequest,
    RemoteSubmitResult,
    SubmitAnnotation,
    SubmitResult,
    WorkList,
    WorkWindow,
    metaprompt,
)
from ...domain import PSEUDONYM_PATTERN


_STATUS = {
    "allowance_required": 403,
    "model_name_invalid": 422,
    "session_not_found": 404,
    "labels_invalid": 422,
    "consent_required": 403,
    "window_unavailable": 409,
    "window_fingerprint_invalid": 422,
    # The window moved on (session grew, or was re-read under a different run),
    # so labels describing the old one are refused rather than re-pointed.
    "window_fingerprint_mismatch": 409,
    "window_fingerprint_unavailable": 409,
    "window_session_mismatch": 409,
    "window_provider_mismatch": 409,
    "case_fingerprint_mismatch": 409,
    "no_central_model": 409,
}


def _failure(error: AnnotationError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code})


class AllowanceUpdate(AllowanceState):
    pass


def create_annotation_router(
    require_local_auth: Callable[..., None],
    service: AnnotationService,
    remote_client: RemoteAnnotationClient | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/annotation", tags=["annotation"], dependencies=[Depends(require_local_auth)])

    @router.get("/allowance", response_model=AllowanceState)
    def get_allowance() -> AllowanceState:
        return service.allowance()

    @router.post("/allowance", response_model=AllowanceState)
    def set_allowance(payload: AllowanceUpdate) -> AllowanceState:
        return service.set_allowance(payload.agent_allowed)

    @router.get("/metaprompt", response_model=Metaprompt)
    def get_metaprompt() -> Metaprompt:
        return metaprompt()

    @router.get("/work", response_model=WorkList)
    def work(model: Annotated[str, Query(min_length=1, max_length=120)], limit: Annotated[int, Query(ge=1, le=100)] = 25) -> WorkList:
        try:
            return service.work(model, limit)
        except AnnotationError as error:
            raise _failure(error) from None

    @router.get("/work/{session_id}", response_model=WorkWindow)
    def window(session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)]) -> WorkWindow:
        try:
            return service.window(session_id)
        except AnnotationError as error:
            raise _failure(error) from None

    @router.post("/annotations", response_model=SubmitResult, status_code=201)
    def submit(payload: SubmitAnnotation) -> SubmitResult:
        try:
            return service.submit(payload)
        except AnnotationError as error:
            raise _failure(error) from None

    if remote_client is not None:
        @router.get("/remote/disclosure", response_model=RemoteAnnotationDisclosure)
        def remote_disclosure() -> RemoteAnnotationDisclosure:
            """Read-only disclosure required before the first remote annotation batch."""

            return remote_client.disclosure()

        @router.post("/remote/submit", response_model=RemoteSubmitResult)
        def remote_submit(payload: RemoteSubmitRequest) -> RemoteSubmitResult:
            """Explicit 'annotate remotely': redacted windows + pseudonymous ids go to the central server."""

            try:
                return remote_client.submit_batch(payload)
            except AnnotationError as error:
                raise _failure(error) from None

    return router


def create_central_router(require_auth: Callable[..., None], server: CentralAnnotationServer) -> APIRouter:
    """The central server's routes - embedded locally today, the same code on the VPS beside login."""

    router = APIRouter(prefix="/central/v1", tags=["central-annotation"], dependencies=[Depends(require_auth)])

    @router.post("/annotations/batch", response_model=CentralBatchResult)
    def annotate(batch: CentralBatch) -> CentralBatchResult:
        try:
            return server.annotate_batch(batch)
        except AnnotationError as error:
            raise _failure(error) from None

    return router


__all__ = ("create_annotation_router", "create_central_router")
