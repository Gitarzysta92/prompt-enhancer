"""Prompt checks (ADR 0015): validate a prompt in context; history of metrics only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...application.prompt_check import (
    PromptCheckError,
    PromptCheckHistory,
    PromptCheckRecord,
    PromptCheckRequest,
    PromptCheckResult,
    PromptCheckService,
)
from ...domain import PSEUDONYM_PATTERN


_STATUS = {"check_not_found": 404}


def create_prompt_check_router(require_local_auth: Callable[..., None], service: PromptCheckService) -> APIRouter:
    router = APIRouter(prefix="/v1/prompt-checks", tags=["prompt-checks"], dependencies=[Depends(require_local_auth)])

    @router.post("", response_model=PromptCheckResult)
    def check(payload: PromptCheckRequest) -> PromptCheckResult:
        """Validate one prompt (optionally with the earlier turns); nothing but metrics is stored."""

        try:
            return service.check(payload)
        except PromptCheckError as error:
            raise HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code}) from None

    @router.get("", response_model=PromptCheckHistory)
    def history(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> PromptCheckHistory:
        return service.history(limit=limit, offset=offset)

    @router.get("/{check_id}", response_model=PromptCheckRecord)
    def stored(check_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)]) -> PromptCheckRecord:
        try:
            return service.get(check_id)
        except PromptCheckError as error:
            raise HTTPException(status_code=_STATUS.get(error.code, 500), detail={"code": error.code}) from None

    return router


__all__ = ("create_prompt_check_router",)
