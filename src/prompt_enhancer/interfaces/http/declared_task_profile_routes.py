"""Task-profile declarations behind an explicit user-presence authority.

The HTTP surface carries only closed enum values, counts, pseudonyms and
server-issued provenance.  Reading may use the installation-local API token;
writing additionally requires both the same-origin browser boundary and an
independently injected user-presence dependency because a declaration changes
measurement authority.  Browser session plus CSRF is not itself proof of a
person, so the production composition fails closed when that second authority
is absent.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import Field

from ...application.analysis.declared_task_profiles import (
    DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY,
    DECLARED_TASK_PROFILE_POLICY_VERSION,
    DECLARED_TASK_PROFILE_SCHEMA_VERSION,
    DeclaredTaskProfileCommand,
    DeclaredTaskProfileConflictError,
    DeclaredTaskProfileInputError,
    DeclaredTaskProfileNotFoundError,
    DeclaredTaskProfilePersistenceError,
    DeclaredTaskProfileRecord,
    DeclaredTaskProfileStaleRevisionError,
)
from ...application.analysis.text_contracts import ConstraintKind, DeliverableSlot
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .session_provider_contracts import SessionProviderFailureResponse


_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class DeclaredTaskProfileCommandPort(Protocol):
    def save(
        self,
        *,
        provider: Provider,
        session_id: str,
        command: DeclaredTaskProfileCommand,
        idempotency_key: str,
    ) -> tuple[DeclaredTaskProfileRecord, bool]: ...

    def get_latest(
        self, *, provider: Provider, session_id: str
    ) -> DeclaredTaskProfileRecord | None: ...


class DeclaredTaskProfileDto(StrictModel):
    profile_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    provider: Provider
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    revision: int = Field(ge=1, le=1_000_000)
    previous_profile_id: str | None = Field(
        default=None, pattern=PSEUDONYM_PATTERN.pattern
    )
    constraint_kinds: tuple[ConstraintKind, ...] | None = None
    expected_outcome_count: int | None = Field(default=None, ge=1, le=100)
    deliverable_slots: tuple[DeliverableSlot, ...] | None = None
    profile_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    confirmed_at: datetime
    confirmation_authority: Literal[
        DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY
    ]
    schema_version: Literal[DECLARED_TASK_PROFILE_SCHEMA_VERSION]
    policy_version: Literal[DECLARED_TASK_PROFILE_POLICY_VERSION]
    local_only: Literal[True]
    content_persisted: Literal[False]

    @classmethod
    def from_record(cls, record: DeclaredTaskProfileRecord) -> "DeclaredTaskProfileDto":
        return cls.model_validate(
            record.model_dump(
                exclude={"idempotency_key_digest", "command_fingerprint"}
            )
        )


class DeclaredTaskProfileCurrentDto(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    profile: DeclaredTaskProfileDto | None
    confirmation_available: bool


class DeclaredTaskProfileOutcomeDto(StrictModel):
    profile: DeclaredTaskProfileDto
    applied: bool


class DeclaredTaskProfileNotFoundFailureDetail(StrictModel):
    code: Literal["declared_task_profile_session_not_found"]
    message: Literal["declared task profile session was not found"]


class DeclaredTaskProfileNotFoundFailureResponse(StrictModel):
    detail: DeclaredTaskProfileNotFoundFailureDetail


class DeclaredTaskProfileUnavailableFailureDetail(StrictModel):
    code: Literal["declared_task_profile_persistence_failed"]
    message: Literal["declared task profile is unavailable"]


class DeclaredTaskProfileUnavailableFailureResponse(StrictModel):
    detail: DeclaredTaskProfileUnavailableFailureDetail


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, DeclaredTaskProfileInputError):
        return HTTPException(
            422,
            detail={
                "code": error.code,
                "message": "declared task profile request is invalid",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(error, DeclaredTaskProfileNotFoundError):
        return HTTPException(
            404,
            detail={
                "code": error.code,
                "message": "declared task profile session was not found",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(
        error, (DeclaredTaskProfileStaleRevisionError, DeclaredTaskProfileConflictError)
    ):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "declared task profile authority changed",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(error, DeclaredTaskProfilePersistenceError):
        return HTTPException(
            503,
            detail={
                "code": error.code,
                "message": "declared task profile is unavailable",
            },
            headers=_PRIVATE_HEADERS,
        )
    raise TypeError("unsupported declared task profile error")


def create_declared_task_profile_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: DeclaredTaskProfileCommandPort,
    provider_resolver: Callable[[str], Provider],
    *,
    confirmation_available: bool,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["declared-task-profile"],
        dependencies=[Depends(require_local_auth)],
    )

    def provider_of(session_id: str) -> Provider:
        return provider_resolver(session_id)

    @router.get(
        "/sessions/{session_id}/declared-task-profile",
        response_model=DeclaredTaskProfileCurrentDto,
        responses={
            404: {"model": SessionProviderFailureResponse},
            503: {
                "model": (
                    DeclaredTaskProfileUnavailableFailureResponse
                    | SessionProviderFailureResponse
                )
            },
        },
    )
    def current_profile(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> DeclaredTaskProfileCurrentDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            profile = service.get_latest(
                provider=provider_of(session_id), session_id=session_id
            )
        except (
            DeclaredTaskProfileInputError,
            DeclaredTaskProfilePersistenceError,
        ) as error:
            raise _failure(error) from None
        return DeclaredTaskProfileCurrentDto(
            session_id=session_id,
            confirmation_available=confirmation_available,
            profile=(
                None if profile is None else DeclaredTaskProfileDto.from_record(profile)
            ),
        )

    @router.post(
        "/sessions/{session_id}/declared-task-profile",
        response_model=DeclaredTaskProfileOutcomeDto,
        dependencies=[Depends(require_user_confirmation)],
        responses={
            404: {
                "model": (
                    DeclaredTaskProfileNotFoundFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            503: {
                "model": (
                    DeclaredTaskProfileUnavailableFailureResponse
                    | SessionProviderFailureResponse
                )
            },
        },
    )
    def save_profile(
        payload: DeclaredTaskProfileCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> DeclaredTaskProfileOutcomeDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            profile, applied = service.save(
                provider=provider_of(session_id),
                session_id=session_id,
                command=payload,
                idempotency_key=idempotency_key,
            )
        except (
            DeclaredTaskProfileConflictError,
            DeclaredTaskProfileInputError,
            DeclaredTaskProfileNotFoundError,
            DeclaredTaskProfilePersistenceError,
            DeclaredTaskProfileStaleRevisionError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return DeclaredTaskProfileOutcomeDto(
            profile=DeclaredTaskProfileDto.from_record(profile),
            applied=applied,
        )

    return router


__all__ = [
    "DeclaredTaskProfileCurrentDto",
    "DeclaredTaskProfileDto",
    "DeclaredTaskProfileOutcomeDto",
    "create_declared_task_profile_router",
]
