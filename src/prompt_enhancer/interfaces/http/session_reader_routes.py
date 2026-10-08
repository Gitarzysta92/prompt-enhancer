"""Owner-authorized on-demand session reading (ADR 0011)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from ...application.analysis.session_reader import (
    SessionReadError,
    SessionReadFailure,
    SessionReaderService,
    SessionTranscript,
)
from ...domain import PSEUDONYM_PATTERN


_STATUS = {
    SessionReadFailure.READER_DISABLED: 404,
    SessionReadFailure.CONSENT_REQUIRED: 403,
    SessionReadFailure.SESSION_UNKNOWN: 404,
    SessionReadFailure.PROVIDER_UNSUPPORTED: 404,
    SessionReadFailure.SOURCE_UNAVAILABLE: 503,
    SessionReadFailure.SESSION_NOT_FOUND: 404,
    SessionReadFailure.FORMAT_UNRECOGNIZED: 422,
    SessionReadFailure.LIMIT_EXCEEDED: 413,
}


def create_session_reader_router(
    require_local_auth: Callable[..., None],
    service: SessionReaderService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/sessions",
        tags=["session-reader"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("/{session_id}/transcript", response_model=SessionTranscript)
    def read_transcript(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        response: Response,
    ) -> SessionTranscript:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.read(session_id)
        except SessionReadError as error:
            raise HTTPException(
                status_code=_STATUS[error.reason],
                detail={"code": error.reason.value, "message": "session read unavailable"},
            ) from None

    return router


__all__ = ("create_session_reader_router",)
