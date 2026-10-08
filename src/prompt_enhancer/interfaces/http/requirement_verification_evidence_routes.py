"""Authenticated, content-free requirement-verification evidence routes.

Objective-verifier results arrive only as complete app-issued keyed records.
Explicit acceptance is a separate measurement authority and therefore also
requires the owned native browser user-presence dependency supplied by the
composition root.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response
from pydantic import Field

from ...application.analysis.requirement_verification_evidence import (
    RequirementVerificationEvidenceSet,
)
from ...application.analysis.requirement_verification_persistence import (
    MAX_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
    MAX_REQUIREMENT_VERIFICATION_REVISIONS,
    MIN_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
    REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION,
    RequirementAcceptanceAppendCommand,
    RequirementVerificationAuthorityHead,
    RequirementVerificationConflictError,
    RequirementVerificationDefinitionsOutOfDateError,
    RequirementVerificationEvidenceSnapshot,
    RequirementVerificationInputError,
    RequirementVerificationNotFoundError,
    RequirementVerificationPersistenceError,
    RequirementVerificationResultAppendCommand,
    RequirementVerificationStaleWindowError,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from .browser_session import BROWSER_SESSION_COOKIE, CSRF_HEADER
from .user_presence import USER_PRESENCE_HEADER


_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class RequirementVerificationEvidenceCommand(Protocol):
    def issue_current_opportunities(
        self, session_id: str
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]: ...

    def snapshot(
        self,
        session_id: str,
        opportunity_set_fingerprint: str,
        *,
        through_revision: int | None = None,
    ) -> RequirementVerificationEvidenceSnapshot: ...

    def append_objective_result(
        self,
        *,
        session_id: str,
        command: RequirementVerificationResultAppendCommand,
        idempotency_key: str,
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]: ...

    def append_acceptance(
        self,
        *,
        session_id: str,
        command: RequirementAcceptanceAppendCommand,
        idempotency_key: str,
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]: ...


class RequirementVerificationEvidenceSnapshotDto(StrictModel):
    """Public snapshot with no persistence command or raw-content fields."""

    evidence: RequirementVerificationEvidenceSet
    revision: int = Field(ge=0, le=MAX_REQUIREMENT_VERIFICATION_REVISIONS)
    authority_heads: tuple[RequirementVerificationAuthorityHead, ...]
    persistence_schema_version: Literal[
        REQUIREMENT_VERIFICATION_PERSISTENCE_SCHEMA_VERSION
    ]
    local_only: Literal[True]
    content_persisted: Literal[False]

    @classmethod
    def from_snapshot(
        cls, snapshot: RequirementVerificationEvidenceSnapshot
    ) -> "RequirementVerificationEvidenceSnapshotDto":
        return cls(
            evidence=snapshot.evidence,
            revision=snapshot.revision,
            authority_heads=snapshot.authority_heads,
            persistence_schema_version=snapshot.persistence_schema_version,
            local_only=snapshot.local_only,
            content_persisted=snapshot.content_persisted,
        )


class RequirementVerificationEvidenceMutationDto(StrictModel):
    snapshot: RequirementVerificationEvidenceSnapshotDto
    applied: bool


class RequirementVerificationServiceErrorDetailDto(StrictModel):
    code: Literal[
        "requirement_verification_evidence_definitions_out_of_date",
        "invalid_requirement_verification_evidence",
        "requirement_verification_evidence_not_found",
        "requirement_verification_source_window_stale",
        "requirement_verification_evidence_conflict",
        "requirement_verification_evidence_persistence_failed",
    ]
    message: Literal[
        "requirement-verification definitions are out of date",
        "requirement-verification evidence is invalid",
        "requirement-verification evidence was not found",
        "requirement-verification authority changed",
        "requirement-verification evidence is unavailable",
    ]


class RequirementVerificationServiceErrorDto(StrictModel):
    detail: RequirementVerificationServiceErrorDetailDto


class RequirementVerificationMessageErrorDto(StrictModel):
    detail: Literal[
        "authentication required",
        "browser session required",
        "origin not allowed",
        "owned native confirmation required",
        "same-origin mutation required",
        "same-origin confirmation required",
        "CSRF validation failed",
        "user-presence confirmation is unavailable",
        "native user-presence confirmation required",
        "request validation failed",
    ]


_MIXED_ERROR_MODEL = (
    RequirementVerificationMessageErrorDto | RequirementVerificationServiceErrorDto
)


def _read_error_responses() -> dict[int, dict[str, object]]:
    return {
        401: {
            "model": RequirementVerificationMessageErrorDto,
            "description": "Local authentication is required.",
        },
        404: {
            "model": RequirementVerificationServiceErrorDto,
            "description": "The exact evidence authority was not found.",
        },
        409: {
            "model": RequirementVerificationServiceErrorDto,
            "description": "The definitions, source window, or authority changed.",
        },
        422: {
            "model": _MIXED_ERROR_MODEL,
            "description": "The bounded request or evidence command is invalid.",
        },
        503: {
            "model": RequirementVerificationServiceErrorDto,
            "description": "The local evidence authority is unavailable.",
        },
    }


def _local_mutation_error_responses() -> dict[int, dict[str, object]]:
    responses = _read_error_responses()
    responses[403] = {
        "model": RequirementVerificationMessageErrorDto,
        "description": "The browser mutation proof is invalid.",
    }
    return responses


def _native_acceptance_error_responses() -> dict[int, dict[str, object]]:
    responses = _local_mutation_error_responses()
    responses[401] = {
        "model": RequirementVerificationMessageErrorDto,
        "description": "An ephemeral browser session is required.",
    }
    responses[403] = {
        "model": RequirementVerificationMessageErrorDto,
        "description": "Same-origin, CSRF, or body-bound native proof failed.",
    }
    responses[503] = {
        "model": _MIXED_ERROR_MODEL,
        "description": "Native user presence or local evidence is unavailable.",
    }
    return responses


_NATIVE_ACCEPTANCE_OPENAPI_EXTRA = {
    "security": [],
    "parameters": [
        {
            "name": BROWSER_SESSION_COOKIE,
            "in": "cookie",
            "required": True,
            "description": (
                "Ephemeral same-origin browser session; API tokens and Bearer "
                "credentials are rejected."
            ),
            "schema": {"type": "string"},
        },
        {
            "name": "Origin",
            "in": "header",
            "required": True,
            "description": "Exact same-origin browser mutation origin.",
            "schema": {"type": "string", "format": "uri"},
        },
        {
            "name": CSRF_HEADER,
            "in": "header",
            "required": True,
            "description": "CSRF proof bound to the ephemeral browser session.",
            "schema": {"type": "string"},
        },
        {
            "name": USER_PRESENCE_HEADER,
            "in": "header",
            "required": True,
            "description": (
                "One-shot native capability bound to this POST path and the exact "
                "request-body SHA-256."
            ),
            "schema": {"type": "string"},
        },
    ],
}


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, RequirementVerificationDefinitionsOutOfDateError):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "requirement-verification definitions are out of date",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(error, RequirementVerificationInputError):
        return HTTPException(
            422,
            detail={
                "code": error.code,
                "message": "requirement-verification evidence is invalid",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(error, RequirementVerificationNotFoundError):
        return HTTPException(
            404,
            detail={
                "code": error.code,
                "message": "requirement-verification evidence was not found",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(
        error,
        (RequirementVerificationStaleWindowError, RequirementVerificationConflictError),
    ):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "requirement-verification authority changed",
            },
            headers=_PRIVATE_HEADERS,
        )
    if isinstance(error, RequirementVerificationPersistenceError):
        return HTTPException(
            503,
            detail={
                "code": error.code,
                "message": "requirement-verification evidence is unavailable",
            },
            headers=_PRIVATE_HEADERS,
        )
    raise TypeError("unsupported requirement-verification evidence error")


def create_requirement_verification_evidence_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: RequirementVerificationEvidenceCommand,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["requirement-verification-evidence"],
        dependencies=[Depends(require_local_auth)],
    )
    native_router = APIRouter(
        prefix="/v1",
        tags=["requirement-verification-evidence"],
    )

    @router.post(
        "/sessions/{session_id}/requirement-verification-evidence/"
        "opportunity-sets/current",
        response_model=RequirementVerificationEvidenceMutationDto,
        responses={
            201: {"model": RequirementVerificationEvidenceMutationDto},
            **_local_mutation_error_responses(),
        },
    )
    def issue_current_opportunities(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementVerificationEvidenceMutationDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            snapshot, applied = service.issue_current_opportunities(session_id)
        except (
            RequirementVerificationConflictError,
            RequirementVerificationDefinitionsOutOfDateError,
            RequirementVerificationInputError,
            RequirementVerificationNotFoundError,
            RequirementVerificationPersistenceError,
            RequirementVerificationStaleWindowError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementVerificationEvidenceMutationDto(
            snapshot=RequirementVerificationEvidenceSnapshotDto.from_snapshot(snapshot),
            applied=applied,
        )

    @router.get(
        "/sessions/{session_id}/requirement-verification-evidence/"
        "opportunity-sets/{opportunity_set_fingerprint}",
        response_model=RequirementVerificationEvidenceSnapshotDto,
        responses=_read_error_responses(),
    )
    def snapshot(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        opportunity_set_fingerprint: Annotated[
            str, Path(pattern=PSEUDONYM_PATTERN.pattern)
        ],
        through_revision: Annotated[
            int | None,
            Query(ge=0, le=MAX_REQUIREMENT_VERIFICATION_REVISIONS),
        ] = None,
    ) -> RequirementVerificationEvidenceSnapshotDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            result = service.snapshot(
                session_id,
                opportunity_set_fingerprint,
                through_revision=through_revision,
            )
        except (
            RequirementVerificationConflictError,
            RequirementVerificationDefinitionsOutOfDateError,
            RequirementVerificationInputError,
            RequirementVerificationNotFoundError,
            RequirementVerificationPersistenceError,
            RequirementVerificationStaleWindowError,
        ) as error:
            raise _failure(error) from None
        return RequirementVerificationEvidenceSnapshotDto.from_snapshot(result)

    @router.post(
        "/sessions/{session_id}/requirement-verification-evidence/objective-results",
        response_model=RequirementVerificationEvidenceMutationDto,
        responses={
            201: {"model": RequirementVerificationEvidenceMutationDto},
            **_local_mutation_error_responses(),
        },
    )
    def append_objective_result(
        command: RequirementVerificationResultAppendCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=MIN_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
                max_length=MAX_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
                pattern=SAFE_VERSION_PATTERN.pattern,
            ),
        ],
    ) -> RequirementVerificationEvidenceMutationDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            result, applied = service.append_objective_result(
                session_id=session_id,
                command=command,
                idempotency_key=idempotency_key,
            )
        except (
            RequirementVerificationConflictError,
            RequirementVerificationDefinitionsOutOfDateError,
            RequirementVerificationInputError,
            RequirementVerificationNotFoundError,
            RequirementVerificationPersistenceError,
            RequirementVerificationStaleWindowError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementVerificationEvidenceMutationDto(
            snapshot=RequirementVerificationEvidenceSnapshotDto.from_snapshot(result),
            applied=applied,
        )

    @native_router.post(
        "/sessions/{session_id}/requirement-verification-evidence/acceptances",
        response_model=RequirementVerificationEvidenceMutationDto,
        responses={
            201: {"model": RequirementVerificationEvidenceMutationDto},
            **_native_acceptance_error_responses(),
        },
        dependencies=[Depends(require_user_confirmation)],
        openapi_extra=_NATIVE_ACCEPTANCE_OPENAPI_EXTRA,
    )
    def append_acceptance(
        command: RequirementAcceptanceAppendCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=MIN_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
                max_length=MAX_REQUIREMENT_VERIFICATION_IDEMPOTENCY_KEY_LENGTH,
                pattern=SAFE_VERSION_PATTERN.pattern,
            ),
        ],
    ) -> RequirementVerificationEvidenceMutationDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            result, applied = service.append_acceptance(
                session_id=session_id,
                command=command,
                idempotency_key=idempotency_key,
            )
        except (
            RequirementVerificationConflictError,
            RequirementVerificationDefinitionsOutOfDateError,
            RequirementVerificationInputError,
            RequirementVerificationNotFoundError,
            RequirementVerificationPersistenceError,
            RequirementVerificationStaleWindowError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementVerificationEvidenceMutationDto(
            snapshot=RequirementVerificationEvidenceSnapshotDto.from_snapshot(result),
            applied=applied,
        )

    container = APIRouter()
    container.include_router(router)
    container.include_router(native_router)
    return container


__all__ = (
    "RequirementVerificationEvidenceMutationDto",
    "RequirementVerificationMessageErrorDto",
    "RequirementVerificationServiceErrorDetailDto",
    "RequirementVerificationServiceErrorDto",
    "RequirementVerificationEvidenceSnapshotDto",
    "create_requirement_verification_evidence_router",
)
