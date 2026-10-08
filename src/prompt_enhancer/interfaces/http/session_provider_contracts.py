"""Content-free HTTP failures for exact session-provider resolution."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import model_validator

from ...domain import StrictModel


class SessionProviderFailureCode(StrEnum):
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_CATALOG_UNAVAILABLE = "session_catalog_unavailable"


SessionProviderFailureMessage = Literal[
    "selected session is not indexed",
    "session catalog is unavailable",
]


_FAILURE_MESSAGES: dict[
    SessionProviderFailureCode,
    SessionProviderFailureMessage,
] = {
    SessionProviderFailureCode.SESSION_NOT_FOUND: "selected session is not indexed",
    SessionProviderFailureCode.SESSION_CATALOG_UNAVAILABLE: (
        "session catalog is unavailable"
    ),
}


class SessionProviderFailureDetail(StrictModel):
    code: SessionProviderFailureCode
    message: SessionProviderFailureMessage

    @model_validator(mode="after")
    def matching_message(self) -> SessionProviderFailureDetail:
        if self.message != _FAILURE_MESSAGES[self.code]:
            raise ValueError("session-provider failure code and message do not match")
        return self


class SessionProviderFailureResponse(StrictModel):
    detail: SessionProviderFailureDetail


def session_provider_failure_detail(
    code: SessionProviderFailureCode,
) -> dict[str, str]:
    """Build the one public detail body assigned to a provider failure code."""

    return SessionProviderFailureDetail(
        code=code,
        message=_FAILURE_MESSAGES[code],
    ).model_dump(mode="json")


__all__ = [
    "SessionProviderFailureCode",
    "SessionProviderFailureDetail",
    "SessionProviderFailureResponse",
    "session_provider_failure_detail",
]
