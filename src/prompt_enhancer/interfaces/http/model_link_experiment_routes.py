"""Explicit local neural-link experiment commands and content-free queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import Field

from ...application.analysis.model_link_experiments import (
    MODEL_LINK_CONFIRMATION,
    MODEL_LINK_EXCERPT_CHARACTERS,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    ModelLinkAnnotationRecord,
    ModelLinkCompatibilityError,
    ModelLinkConflictError,
    ModelLinkConfirmationError,
    ModelLinkConsentError,
    ModelLinkExecutionError,
    ModelLinkExperimentOutcome,
    ModelLinkInputError,
    ModelLinkNoCandidatesError,
    ModelLinkPersistenceError,
    ModelLinkSelectionError,
    ModelLinkSourceError,
    ModelLinkStoredExperiment,
)
from ...application.analysis.text_source import TextSourceFailureReason
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .session_provider_contracts import SessionProviderFailureResponse


class ModelLinkExperimentCommand(Protocol):
    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        device: ModelExperimentDevice,
        idempotency_key: str,
    ) -> ModelLinkExperimentOutcome: ...

    def latest(self, session_id: str) -> ModelLinkStoredExperiment | None: ...

    def annotate(
        self,
        *,
        run_id: str,
        link_id: str,
        label: ModelLinkAnnotationLabel,
        expected_revision: int,
    ) -> ModelLinkAnnotationRecord: ...


class ModelLinkExperimentRequest(StrictModel):
    confirmation: Literal["compare_selected_redacted_text_with_local_models"]
    device: ModelExperimentDevice = ModelExperimentDevice.AUTO


class ModelLinkAnnotationRequest(StrictModel):
    label: ModelLinkAnnotationLabel
    expected_revision: int = Field(ge=0)


class ModelLinkModelDto(StrictModel):
    key: str
    repository_id: str
    revision: str
    license_spdx: str
    tokenizer_id: str
    backend_key: str


class ModelLinkRunDto(StrictModel):
    run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    experiment_key: str
    experiment_version: int = Field(ge=1)
    resolved_device: ModelExperimentDevice
    qwen_model: ModelLinkModelDto
    bge_model: ModelLinkModelDto
    query_count: int = Field(ge=1, le=8)
    link_count: int = Field(ge=1, le=16)
    agreement_count: int = Field(ge=0, le=8)
    started_at: datetime
    finished_at: datetime
    local_only: Literal[True]


class ModelLinkDto(StrictModel):
    link_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    candidate_kind: Literal["response", "plan"]
    qwen_score: float
    qwen_rank: int = Field(ge=1, le=8)
    bge_score: float
    bge_rank: int = Field(ge=1, le=8)
    recommended_by: Literal["qwen", "bge", "both"]


class ModelLinkAnnotationDto(StrictModel):
    link_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    revision: int = Field(ge=1)
    label: ModelLinkAnnotationLabel
    annotated_at: datetime

    @classmethod
    def from_record(cls, record: ModelLinkAnnotationRecord) -> ModelLinkAnnotationDto:
        return cls(
            link_id=record.link_id,
            revision=record.revision,
            label=record.label,
            annotated_at=record.annotated_at,
        )


class ModelLinkExperimentDto(StrictModel):
    run: ModelLinkRunDto
    links: tuple[ModelLinkDto, ...] = Field(max_length=16)
    annotations: tuple[ModelLinkAnnotationDto, ...] = Field(max_length=16)

    @classmethod
    def from_experiment(cls, experiment: ModelLinkStoredExperiment) -> ModelLinkExperimentDto:
        run = experiment.run
        current_annotations: dict[str, ModelLinkAnnotationRecord] = {}
        for annotation in experiment.annotations:
            previous = current_annotations.get(annotation.link_id)
            if previous is None or annotation.revision > previous.revision:
                current_annotations[annotation.link_id] = annotation
        return cls(
            run=ModelLinkRunDto(
                run_id=run.run_id,
                experiment_key=run.experiment_key,
                experiment_version=run.experiment_version,
                resolved_device=run.resolved_device,
                qwen_model=ModelLinkModelDto.model_validate(run.qwen_model.model_dump()),
                bge_model=ModelLinkModelDto.model_validate(run.bge_model.model_dump()),
                query_count=run.query_count,
                link_count=run.link_count,
                agreement_count=run.agreement_count,
                started_at=run.started_at,
                finished_at=run.finished_at,
                local_only=True,
            ),
            links=tuple(
                ModelLinkDto(
                    link_id=link.link_id,
                    candidate_kind=link.candidate_kind.value,
                    qwen_score=link.qwen_score,
                    qwen_rank=link.qwen_rank,
                    bge_score=link.bge_score,
                    bge_rank=link.bge_rank,
                    recommended_by=link.recommended_by.value,
                )
                for link in experiment.links
            ),
            annotations=tuple(
                ModelLinkAnnotationDto.from_record(current_annotations[link_id])
                for link_id in sorted(current_annotations)
            ),
        )


class ModelLinkSuggestionDto(StrictModel):
    link_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    query_excerpt: str = Field(min_length=1, max_length=MODEL_LINK_EXCERPT_CHARACTERS + 1)
    candidate_excerpt: str = Field(min_length=1, max_length=MODEL_LINK_EXCERPT_CHARACTERS + 1)


class ModelLinkExperimentCommandResponse(StrictModel):
    experiment: ModelLinkExperimentDto
    suggestions: tuple[ModelLinkSuggestionDto, ...] = Field(max_length=16)
    applied: bool

    @classmethod
    def from_outcome(cls, outcome: ModelLinkExperimentOutcome) -> ModelLinkExperimentCommandResponse:
        return cls(
            experiment=ModelLinkExperimentDto.from_experiment(outcome.experiment),
            suggestions=tuple(
                ModelLinkSuggestionDto(
                    link_id=suggestion.link.link_id,
                    query_excerpt=suggestion.query_excerpt.get_secret_value(),
                    candidate_excerpt=suggestion.candidate_excerpt.get_secret_value(),
                )
                for suggestion in outcome.suggestions
            ),
            applied=outcome.applied,
        )


class ModelLinkFailureCode(StrEnum):
    CONSENT_REQUIRED = ModelLinkConsentError.code
    SESSION_NOT_INDEXED = ModelLinkSelectionError.code
    COMPATIBILITY_BLOCKED = ModelLinkCompatibilityError.code
    INVALID_REQUEST = ModelLinkInputError.code
    CONFIRMATION_REQUIRED = ModelLinkConfirmationError.code
    NO_CANDIDATES = ModelLinkNoCandidatesError.code
    EXECUTION_FAILED = ModelLinkExecutionError.code
    PERSISTENCE_FAILED = ModelLinkPersistenceError.code
    REVISION_CONFLICT = ModelLinkConflictError.code
    EXPERIMENT_NOT_FOUND = "model_link_experiment_not_found"
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


class ModelLinkFailureDetail(StrictModel):
    code: ModelLinkFailureCode
    message: str = Field(min_length=1, max_length=128)


class ModelLinkFailureResponse(StrictModel):
    detail: ModelLinkFailureDetail


class SanitizedModelLinkValidationFailureResponse(StrictModel):
    detail: Literal["request validation failed"]


_SOURCE_FAILURE_HTTP: dict[TextSourceFailureReason, tuple[int, str]] = {
    TextSourceFailureReason.SCHEMA_UNSUPPORTED: (503, "local source schema is unsupported"),
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
        "selected focus message exceeds the local experiment window",
    ),
    TextSourceFailureReason.RESOURCE_LIMIT: (
        413,
        "local source exceeded an unspecified resource bound",
    ),
    TextSourceFailureReason.TIMEOUT: (504, "local source read timed out"),
    TextSourceFailureReason.PROVIDER_UNAVAILABLE: (503, "local source provider is unavailable"),
    TextSourceFailureReason.NO_ANALYZABLE_TEXT: (422, "selected session has no analyzable text"),
    TextSourceFailureReason.PROTOCOL_REJECTED: (503, "local provider rejected the bounded read protocol"),
}


def _failure(status_code: int, code: ModelLinkFailureCode, message: str) -> HTTPException:
    detail = ModelLinkFailureDetail(code=code, message=message)
    return HTTPException(status_code=status_code, detail=detail.model_dump(mode="json"))


def create_model_link_experiment_router(
    require_local_auth: Callable[..., None],
    service: ModelLinkExperimentCommand,
    provider_resolver: Callable[[str], Provider],
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["local-model-link-experiments"],
        dependencies=[Depends(require_local_auth)],
    )

    def provider_of(session_id: str) -> Provider:
        return provider_resolver(session_id)

    @router.post(
        "/sessions/{session_id}/model-link-experiments",
        response_model=ModelLinkExperimentCommandResponse,
        responses={
            **{
                status: {"model": ModelLinkFailureResponse}
                for status in (403, 409, 413, 504)
            },
            404: {
                "model": ModelLinkFailureResponse | SessionProviderFailureResponse
            },
            503: {
                "model": ModelLinkFailureResponse | SessionProviderFailureResponse
            },
            422: {
                "model": (
                    ModelLinkFailureResponse
                    | SanitizedModelLinkValidationFailureResponse
                )
            },
        },
    )
    def start_experiment(
        payload: ModelLinkExperimentRequest,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> ModelLinkExperimentCommandResponse:
        try:
            outcome = service.run(
                provider=provider_of(session_id),
                session_id=session_id,
                confirmation=payload.confirmation,
                device=payload.device,
                idempotency_key=idempotency_key,
            )
        except ModelLinkConsentError:
            raise _failure(403, ModelLinkFailureCode.CONSENT_REQUIRED, "redacted-content consent required") from None
        except ModelLinkSelectionError:
            raise _failure(404, ModelLinkFailureCode.SESSION_NOT_INDEXED, "selected session is not indexed") from None
        except ModelLinkCompatibilityError:
            raise _failure(409, ModelLinkFailureCode.COMPATIBILITY_BLOCKED, "provider compatibility is not verified") from None
        except ModelLinkSourceError as error:
            status, message = _SOURCE_FAILURE_HTTP[error.reason]
            raise _failure(status, ModelLinkFailureCode(error.reason.value), message) from None
        except ModelLinkNoCandidatesError:
            raise _failure(422, ModelLinkFailureCode.NO_CANDIDATES, "session has no request-response pairs to compare") from None
        except (ModelLinkInputError, ModelLinkConfirmationError) as error:
            raise _failure(422, ModelLinkFailureCode(error.code), "model comparison request is invalid") from None
        except ModelLinkExecutionError:
            raise _failure(503, ModelLinkFailureCode.EXECUTION_FAILED, "cached local models are unavailable") from None
        except ModelLinkPersistenceError:
            raise _failure(503, ModelLinkFailureCode.PERSISTENCE_FAILED, "local experiment persistence is unavailable") from None
        return ModelLinkExperimentCommandResponse.from_outcome(outcome)

    @router.get(
        "/sessions/{session_id}/model-link-experiments/latest",
        response_model=ModelLinkExperimentDto,
        responses={
            404: {"model": ModelLinkFailureResponse},
            422: {"model": SanitizedModelLinkValidationFailureResponse},
            503: {"model": ModelLinkFailureResponse},
        },
    )
    def latest_experiment(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelLinkExperimentDto:
        try:
            experiment = service.latest(session_id)
        except ModelLinkPersistenceError:
            raise _failure(503, ModelLinkFailureCode.PERSISTENCE_FAILED, "local experiment persistence is unavailable") from None
        if experiment is None:
            raise _failure(
                404,
                ModelLinkFailureCode.EXPERIMENT_NOT_FOUND,
                "model-link experiment not found",
            )
        return ModelLinkExperimentDto.from_experiment(experiment)

    @router.post(
        "/model-link-experiments/{run_id}/links/{link_id}/annotations",
        response_model=ModelLinkAnnotationDto,
        responses={
            409: {"model": ModelLinkFailureResponse},
            422: {
                "model": (
                    ModelLinkFailureResponse
                    | SanitizedModelLinkValidationFailureResponse
                )
            },
            503: {"model": ModelLinkFailureResponse},
        },
    )
    def annotate_link(
        payload: ModelLinkAnnotationRequest,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        link_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> ModelLinkAnnotationDto:
        try:
            annotation = service.annotate(
                run_id=run_id,
                link_id=link_id,
                label=payload.label,
                expected_revision=payload.expected_revision,
            )
        except ModelLinkConflictError:
            raise _failure(409, ModelLinkFailureCode.REVISION_CONFLICT, "annotation revision changed") from None
        except ModelLinkInputError:
            raise _failure(422, ModelLinkFailureCode.INVALID_REQUEST, "annotation request is invalid") from None
        except ModelLinkPersistenceError:
            raise _failure(503, ModelLinkFailureCode.PERSISTENCE_FAILED, "local experiment persistence is unavailable") from None
        return ModelLinkAnnotationDto.from_record(annotation)

    return router
