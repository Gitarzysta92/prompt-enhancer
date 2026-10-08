"""Explicit, content-free HTTP command for one local quality-analysis run."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import Field

from ...application.analysis.redaction_preview import (
    REDACTION_PREVIEW_CONFIRMATION,
    AnalysisApproval,
    RedactionPreviewBinding,
    RedactionPreviewCapacityError,
    RedactionPreviewConsumedError,
    RedactionPreviewExpiredError,
    RedactionPreviewInspection,
    RedactionPreviewMessage,
    RedactionPreviewMismatchError,
    RedactionPreviewNotFoundError,
)
from ...application.analysis.session_text_service import (
    SESSION_TEXT_ANALYSIS_CONFIRMATION,
    SessionTextAnalysisConfirmationError,
    SessionTextAnalysisConflictError,
    SessionTextAnalysisCompatibilityError,
    SessionTextAnalysisConsentError,
    SessionTextAnalysisExecutionError,
    SessionTextAnalysisInputError,
    SessionTextAnalysisOutcome,
    SessionTextAnalysisPersistenceError,
    SessionTextAnalysisSelectionError,
    SessionTextAnalysisSourceError,
)
from ...application.analysis.text_analysis_presets import TextAnalysisPresetId
from ...application.analysis.text_contracts import (
    MAX_REDACTED_MESSAGE_CHARACTERS,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from ...application.analysis.text_source import TextSourceFailureReason
from ...application.persistence import AnalysisRunStatus
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .session_provider_contracts import SessionProviderFailureResponse


_PRIVATE_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
}


class SessionTextAnalysisCommand(Protocol):
    def prepare_preset_preview(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
    ) -> RedactionPreviewInspection: ...

    def approve_preview(
        self,
        approval: AnalysisApproval,
    ) -> SessionTextAnalysisOutcome: ...

    def run_preset(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
        confirmation: str,
        idempotency_key: str,
    ) -> SessionTextAnalysisOutcome: ...


class SessionTextAnalysisRequest(StrictModel):
    """A named server-owned scope. The API never accepts profile or transcript text."""

    confirmation: Literal["analyze_selected_redacted_text"]
    preset_id: TextAnalysisPresetId


class SessionTextAnalysisPreviewRequest(StrictModel):
    """Only a server-owned preset may select preview content and metrics."""

    preset_id: TextAnalysisPresetId


class SessionTextAnalysisPreviewMessageResponse(StrictModel):
    role: TextRole
    kind: TextMessageKind
    language: TextLanguage
    text: str = Field(
        min_length=1,
        max_length=MAX_REDACTED_MESSAGE_CHARACTERS,
        repr=False,
    )

    @classmethod
    def from_message(
        cls,
        message: RedactionPreviewMessage,
    ) -> SessionTextAnalysisPreviewMessageResponse:
        return cls(
            role=message.role,
            kind=message.kind,
            language=message.language,
            text=message.text.get_secret_value(),
        )


class SessionTextAnalysisPreviewResponse(StrictModel):
    preview_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    created_at: datetime
    expires_at: datetime
    binding: RedactionPreviewBinding
    messages: tuple[SessionTextAnalysisPreviewMessageResponse, ...]

    @classmethod
    def from_inspection(
        cls,
        inspection: RedactionPreviewInspection,
    ) -> SessionTextAnalysisPreviewResponse:
        receipt = inspection.receipt
        return cls(
            preview_id=receipt.preview_id,
            created_at=receipt.created_at,
            expires_at=receipt.expires_at,
            binding=receipt.binding,
            messages=tuple(
                SessionTextAnalysisPreviewMessageResponse.from_message(message)
                for message in inspection.messages
            ),
        )


class SessionTextAnalysisPreviewApprovalRequest(StrictModel):
    confirmation: Literal["approve_exact_redacted_preview"]
    expected_binding: RedactionPreviewBinding


class SessionTextAnalysisCommandResponse(StrictModel):
    run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    status: AnalysisRunStatus
    result_count: int = Field(ge=0, le=100)
    applied: bool
    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)

    @classmethod
    def from_outcome(
        cls, outcome: SessionTextAnalysisOutcome
    ) -> SessionTextAnalysisCommandResponse:
        return cls(
            run_id=outcome.run_id,
            status=outcome.status,
            result_count=outcome.result_count,
            applied=outcome.applied,
            analysis_profile_key=outcome.analysis_profile_key,
            analysis_profile_version=outcome.analysis_profile_version,
        )


class SessionTextAnalysisFailureCode(StrEnum):
    """Closed HTTP error vocabulary; values never contain provider data."""

    CONSENT_REQUIRED = SessionTextAnalysisConsentError.code
    SESSION_NOT_INDEXED = SessionTextAnalysisSelectionError.code
    IDEMPOTENCY_CONFLICT = SessionTextAnalysisConflictError.code
    INVALID_REQUEST = SessionTextAnalysisInputError.code
    CONFIRMATION_REQUIRED = SessionTextAnalysisConfirmationError.code
    SCHEMA_UNSUPPORTED = TextSourceFailureReason.SCHEMA_UNSUPPORTED.value
    SELECTION_SNAPSHOT_MISS = TextSourceFailureReason.SELECTION_SNAPSHOT_MISS.value
    SELECTION_LIMIT = TextSourceFailureReason.SELECTION_LIMIT.value
    PROVIDER_RESPONSE_LIMIT = TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT.value
    THREAD_STRUCTURE_LIMIT = TextSourceFailureReason.THREAD_STRUCTURE_LIMIT.value
    PREVIEW_WINDOW_LIMIT = TextSourceFailureReason.PREVIEW_WINDOW_LIMIT.value
    RESOURCE_LIMIT = TextSourceFailureReason.RESOURCE_LIMIT.value
    TIMEOUT = TextSourceFailureReason.TIMEOUT.value
    PROVIDER_UNAVAILABLE = TextSourceFailureReason.PROVIDER_UNAVAILABLE.value
    NO_ANALYZABLE_TEXT = TextSourceFailureReason.NO_ANALYZABLE_TEXT.value
    PROTOCOL_REJECTED = TextSourceFailureReason.PROTOCOL_REJECTED.value
    COMPATIBILITY_BLOCKED = SessionTextAnalysisCompatibilityError.code
    PERSISTENCE_FAILED = SessionTextAnalysisPersistenceError.code
    EXECUTION_FAILED = SessionTextAnalysisExecutionError.code
    PREVIEW_NOT_FOUND = "redaction_preview_not_found"
    PREVIEW_EXPIRED = "redaction_preview_expired"
    PREVIEW_CONSUMED = "redaction_preview_consumed"
    PREVIEW_MISMATCH = "redaction_preview_binding_mismatch"
    PREVIEW_CAPACITY = "redaction_preview_capacity_reached"


class SessionTextAnalysisFailureDetail(StrictModel):
    code: SessionTextAnalysisFailureCode
    message: str = Field(min_length=1, max_length=128)


class SessionTextAnalysisFailureResponse(StrictModel):
    detail: SessionTextAnalysisFailureDetail


class SanitizedRequestValidationFailureResponse(StrictModel):
    detail: Literal["request validation failed"]


_SOURCE_FAILURE_HTTP: dict[TextSourceFailureReason, tuple[int, str]] = {
    TextSourceFailureReason.SCHEMA_UNSUPPORTED: (
        503,
        "local source schema is unsupported",
    ),
    TextSourceFailureReason.SELECTION_SNAPSHOT_MISS: (
        409,
        "selected session is absent from the current provider snapshot",
    ),
    TextSourceFailureReason.SELECTION_LIMIT: (
        413,
        "provider session selection exceeds the local scan bounds",
    ),
    TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT: (
        413,
        "local provider response exceeds the transport bound",
    ),
    TextSourceFailureReason.THREAD_STRUCTURE_LIMIT: (
        413,
        "selected session structure exceeds the local parser bounds",
    ),
    TextSourceFailureReason.PREVIEW_WINDOW_LIMIT: (
        413,
        "selected focus message exceeds the local preview bound",
    ),
    TextSourceFailureReason.RESOURCE_LIMIT: (
        413,
        "local source exceeded an unspecified resource bound",
    ),
    TextSourceFailureReason.TIMEOUT: (504, "local source read timed out"),
    TextSourceFailureReason.PROVIDER_UNAVAILABLE: (
        503,
        "local source provider is unavailable",
    ),
    TextSourceFailureReason.NO_ANALYZABLE_TEXT: (
        422,
        "selected session has no analyzable text",
    ),
    TextSourceFailureReason.PROTOCOL_REJECTED: (
        503,
        "local provider rejected the bounded read protocol",
    ),
}


def _failure(
    status_code: int,
    code: SessionTextAnalysisFailureCode,
    message: str,
) -> HTTPException:
    detail = SessionTextAnalysisFailureDetail(code=code, message=message)
    return HTTPException(
        status_code=status_code,
        detail=detail.model_dump(mode="json"),
        headers=_PRIVATE_NO_STORE_HEADERS,
    )


def _preview_failure(error: Exception) -> HTTPException:
    if isinstance(error, RedactionPreviewNotFoundError):
        return _failure(
            404,
            SessionTextAnalysisFailureCode.PREVIEW_NOT_FOUND,
            "redaction preview is unavailable",
        )
    if isinstance(error, RedactionPreviewExpiredError):
        return _failure(
            410,
            SessionTextAnalysisFailureCode.PREVIEW_EXPIRED,
            "redaction preview expired",
        )
    if isinstance(error, RedactionPreviewConsumedError):
        return _failure(
            409,
            SessionTextAnalysisFailureCode.PREVIEW_CONSUMED,
            "redaction preview was already consumed",
        )
    if isinstance(error, RedactionPreviewMismatchError):
        return _failure(
            409,
            SessionTextAnalysisFailureCode.PREVIEW_MISMATCH,
            "redaction preview binding does not match",
        )
    if isinstance(error, RedactionPreviewCapacityError):
        return _failure(
            503,
            SessionTextAnalysisFailureCode.PREVIEW_CAPACITY,
            "redaction preview capacity is unavailable",
        )
    raise TypeError("unsupported preview error")


def _analysis_failure(error: Exception) -> HTTPException:
    if isinstance(error, SessionTextAnalysisConsentError):
        return _failure(
            403,
            SessionTextAnalysisFailureCode.CONSENT_REQUIRED,
            "redacted-content consent required",
        )
    if isinstance(error, SessionTextAnalysisSelectionError):
        return _failure(
            404,
            SessionTextAnalysisFailureCode.SESSION_NOT_INDEXED,
            "selected session is not indexed",
        )
    if isinstance(error, SessionTextAnalysisCompatibilityError):
        return _failure(
            409,
            SessionTextAnalysisFailureCode.COMPATIBILITY_BLOCKED,
            "provider compatibility is not verified",
        )
    if isinstance(error, SessionTextAnalysisConflictError):
        return _failure(
            409,
            SessionTextAnalysisFailureCode.IDEMPOTENCY_CONFLICT,
            "analysis idempotency conflict",
        )
    if isinstance(
        error,
        (SessionTextAnalysisInputError, SessionTextAnalysisConfirmationError),
    ):
        return _failure(
            422,
            SessionTextAnalysisFailureCode(error.code),
            "quality analysis request is invalid",
        )
    if isinstance(error, SessionTextAnalysisSourceError):
        status, message = _SOURCE_FAILURE_HTTP[error.reason]
        return _failure(
            status,
            SessionTextAnalysisFailureCode(error.reason.value),
            message,
        )
    if isinstance(error, SessionTextAnalysisPersistenceError):
        return _failure(
            503,
            SessionTextAnalysisFailureCode.PERSISTENCE_FAILED,
            "local analysis persistence is unavailable",
        )
    if isinstance(error, SessionTextAnalysisExecutionError):
        return _failure(
            503,
            SessionTextAnalysisFailureCode.EXECUTION_FAILED,
            "local metric execution is unavailable",
        )
    raise TypeError("unsupported session-analysis error")


def create_session_analysis_command_router(
    require_local_auth: Callable[..., None],
    service: SessionTextAnalysisCommand,
    provider_resolver: Callable[[str], Provider],
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["session-quality-analysis"],
        dependencies=[Depends(require_local_auth)],
    )

    def provider_of(session_id: str) -> Provider:
        # The exact catalog row decides which local text source is read.
        return provider_resolver(session_id)

    @router.post(
        "/sessions/{session_id}/quality-analysis-previews",
        response_model=SessionTextAnalysisPreviewResponse,
        responses={
            **{
                status: {"model": SessionTextAnalysisFailureResponse}
                for status in (403, 409, 413, 504)
            },
            404: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            503: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            422: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SanitizedRequestValidationFailureResponse
                )
            },
        },
    )
    def prepare_session_analysis_preview(
        payload: SessionTextAnalysisPreviewRequest,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionTextAnalysisPreviewResponse:
        response.headers.update(_PRIVATE_NO_STORE_HEADERS)
        try:
            inspection = service.prepare_preset_preview(
                provider=provider_of(session_id),
                session_id=session_id,
                preset_id=payload.preset_id,
            )
        except RedactionPreviewCapacityError as error:
            raise _preview_failure(error) from None
        except (
            SessionTextAnalysisConsentError,
            SessionTextAnalysisSelectionError,
            SessionTextAnalysisCompatibilityError,
            SessionTextAnalysisInputError,
            SessionTextAnalysisSourceError,
        ) as error:
            raise _analysis_failure(error) from None
        return SessionTextAnalysisPreviewResponse.from_inspection(inspection)

    @router.post(
        "/quality-analysis-previews/{preview_id}/approval",
        response_model=SessionTextAnalysisCommandResponse,
        responses={
            **{
                status: {"model": SessionTextAnalysisFailureResponse}
                for status in (403, 404, 409, 410, 503)
            },
            422: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SanitizedRequestValidationFailureResponse
                )
            },
        },
    )
    def approve_session_analysis_preview(
        payload: SessionTextAnalysisPreviewApprovalRequest,
        response: Response,
        preview_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=SAFE_VERSION_PATTERN.pattern,
            ),
        ],
    ) -> SessionTextAnalysisCommandResponse:
        response.headers.update(_PRIVATE_NO_STORE_HEADERS)
        approval = AnalysisApproval(
            preview_id=preview_id,
            confirmation=REDACTION_PREVIEW_CONFIRMATION,
            idempotency_key=idempotency_key,
            expected_binding=payload.expected_binding,
        )
        try:
            outcome = service.approve_preview(approval)
        except (
            RedactionPreviewNotFoundError,
            RedactionPreviewExpiredError,
            RedactionPreviewConsumedError,
            RedactionPreviewMismatchError,
            RedactionPreviewCapacityError,
        ) as error:
            raise _preview_failure(error) from None
        except (
            SessionTextAnalysisConsentError,
            SessionTextAnalysisSelectionError,
            SessionTextAnalysisCompatibilityError,
            SessionTextAnalysisConflictError,
            SessionTextAnalysisInputError,
            SessionTextAnalysisConfirmationError,
            SessionTextAnalysisSourceError,
            SessionTextAnalysisPersistenceError,
            SessionTextAnalysisExecutionError,
        ) as error:
            raise _analysis_failure(error) from None
        return SessionTextAnalysisCommandResponse.from_outcome(outcome)

    @router.post(
        "/sessions/{session_id}/quality-analysis-runs",
        response_model=SessionTextAnalysisCommandResponse,
        responses={
            **{
                status: {"model": SessionTextAnalysisFailureResponse}
                for status in (403, 409, 413, 504)
            },
            404: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            503: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SessionProviderFailureResponse
                )
            },
            422: {
                "model": (
                    SessionTextAnalysisFailureResponse
                    | SanitizedRequestValidationFailureResponse
                )
            },
        },
    )
    def start_session_analysis(
        payload: SessionTextAnalysisRequest,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=SAFE_VERSION_PATTERN.pattern,
            ),
        ],
    ) -> SessionTextAnalysisCommandResponse:
        try:
            outcome = service.run_preset(
                provider=provider_of(session_id),
                session_id=session_id,
                preset_id=payload.preset_id,
                confirmation=payload.confirmation,
                idempotency_key=idempotency_key,
            )
        except SessionTextAnalysisConsentError:
            raise _failure(
                403,
                SessionTextAnalysisFailureCode.CONSENT_REQUIRED,
                "redacted-content consent required",
            ) from None
        except SessionTextAnalysisSelectionError:
            raise _failure(
                404,
                SessionTextAnalysisFailureCode.SESSION_NOT_INDEXED,
                "selected session is not indexed",
            ) from None
        except SessionTextAnalysisCompatibilityError:
            raise _failure(
                409,
                SessionTextAnalysisFailureCode.COMPATIBILITY_BLOCKED,
                "provider compatibility is not verified",
            ) from None
        except SessionTextAnalysisConflictError:
            raise _failure(
                409,
                SessionTextAnalysisFailureCode.IDEMPOTENCY_CONFLICT,
                "analysis idempotency conflict",
            ) from None
        except (
            SessionTextAnalysisInputError,
            SessionTextAnalysisConfirmationError,
        ) as error:
            raise _failure(
                422,
                SessionTextAnalysisFailureCode(error.code),
                "quality analysis request is invalid",
            ) from None
        except SessionTextAnalysisSourceError as error:
            status, message = _SOURCE_FAILURE_HTTP[error.reason]
            raise _failure(
                status,
                SessionTextAnalysisFailureCode(error.reason.value),
                message,
            ) from None
        except SessionTextAnalysisPersistenceError:
            raise _failure(
                503,
                SessionTextAnalysisFailureCode.PERSISTENCE_FAILED,
                "local analysis persistence is unavailable",
            ) from None
        except SessionTextAnalysisExecutionError:
            raise _failure(
                503,
                SessionTextAnalysisFailureCode.EXECUTION_FAILED,
                "local metric execution is unavailable",
            ) from None
        return SessionTextAnalysisCommandResponse.from_outcome(outcome)

    return router
