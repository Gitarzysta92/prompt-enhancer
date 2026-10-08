"""Content-free HTTP commands for the hook-captured Claude Code source."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ...application.local_sources import (
    ClaudeCodeLocalSourceService,
    ClaudeCodeLocalSourceStatus,
)
from ...domain import StrictModel
from ...ingestion import ConsentRequiredError, IngestionError, IngestionReport


class ClaudeIndexRequest(StrictModel):
    max_sessions: int = Field(default=500, ge=1, le=1_000)


def create_claude_local_source_router(
    require_local_auth: Callable[..., None],
    service: ClaudeCodeLocalSourceService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/local-sources/claude-code",
        tags=["local-sources"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("")
    def status() -> ClaudeCodeLocalSourceStatus:
        return service.status()

    @router.post("/consents/local-history")
    def grant_consent() -> ClaudeCodeLocalSourceStatus:
        return service.grant_local_history()

    @router.delete("/consents/local-history")
    def revoke_consent() -> ClaudeCodeLocalSourceStatus:
        return service.revoke_local_history()

    @router.post("/index")
    def index(payload: ClaudeIndexRequest) -> IngestionReport:
        try:
            return service.index(max_sessions=payload.max_sessions)
        except ConsentRequiredError:
            raise HTTPException(
                status_code=403, detail="local-history consent required"
            ) from None
        except IngestionError:
            raise HTTPException(
                status_code=503, detail="local source unavailable"
            ) from None

    return router
