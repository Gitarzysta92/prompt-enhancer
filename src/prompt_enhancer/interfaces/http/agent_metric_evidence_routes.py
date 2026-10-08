"""Authenticated loopback upload boundary for content-free agent evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from pydantic import Field

from ...application.analysis.agent_metric_evidence import (
    MAX_AGENT_METRIC_EVIDENCE_BYTES,
    AgentMetricEvidenceAnyFileContract,
    AgentMetricEvidenceDefinitionsOutOfDateError,
    AgentMetricEvidenceFileError,
    AgentMetricEvidenceImportResult,
    AgentMetricEvidencePreview,
    AgentMetricEvidenceProducer,
)
from ...application.analysis.metric_lifecycle_evidence import (
    MetricLifecycleConflictError,
    MetricLifecycleFamily,
    MetricLifecycleInputError,
    MetricLifecycleNotFoundError,
    MetricLifecyclePersistenceError,
    MetricLifecycleStaleWindowError,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from .metric_lifecycle_evidence_routes import MetricLifecycleProposalDto


AGENT_METRIC_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.prompt-enhancer.agent-metric-evidence+json"
)
_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class AgentMetricEvidenceCommand(Protocol):
    def contract(self, session_id: str) -> AgentMetricEvidenceAnyFileContract: ...

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> AgentMetricEvidencePreview: ...

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> AgentMetricEvidenceImportResult: ...


class AgentMetricEvidencePreviewDto(StrictModel):
    schema_version: str
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    expected_source_run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    source_window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    metric_key: MetricLifecycleFamily
    proposal_kind: str
    expires_at: datetime
    producer: AgentMetricEvidenceProducer
    creates_unconfirmed_proposal_only: bool
    requires_authenticated_local_user_confirmation: bool
    can_set_numeric_metric: bool
    objective_receipt_claims_accepted: bool
    raw_payload_persisted: bool


class AgentMetricEvidenceImportDto(StrictModel):
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    proposal: MetricLifecycleProposalDto
    applied: bool
    producer_claim_persisted: bool
    raw_payload_persisted: bool
    requires_authenticated_local_user_confirmation: bool


async def _bounded_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").strip().lower()
    if content_type != AGENT_METRIC_EVIDENCE_MEDIA_TYPE:
        raise HTTPException(
            415,
            detail={
                "code": "agent_metric_evidence_media_type_required",
                "message": "agent evidence requires its exact local file media type",
            },
        )
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_AGENT_METRIC_EVIDENCE_BYTES:
            raise HTTPException(
                413,
                detail={
                    "code": "agent_metric_evidence_too_large",
                    "message": "agent evidence exceeds the local file limit",
                },
            )
    return bytes(payload)


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, AgentMetricEvidenceDefinitionsOutOfDateError):
        return HTTPException(
            409,
            detail={
                "code": error.code,
                "message": "agent metric evidence definitions are out of date",
            },
        )
    if isinstance(error, (AgentMetricEvidenceFileError, MetricLifecycleInputError)):
        return HTTPException(
            422,
            detail={
                "code": getattr(error, "code", "invalid_agent_metric_evidence_file"),
                "message": "agent metric evidence is invalid",
            },
        )
    if isinstance(error, MetricLifecycleNotFoundError):
        return HTTPException(
            404,
            detail={
                "code": error.code,
                "message": "agent metric evidence authority was not found",
            },
        )
    if isinstance(error, (MetricLifecycleStaleWindowError, MetricLifecycleConflictError)):
        return HTTPException(
            409,
            detail={"code": error.code, "message": "agent metric evidence binding changed"},
        )
    if isinstance(error, MetricLifecyclePersistenceError):
        return HTTPException(
            503,
            detail={"code": error.code, "message": "agent metric evidence is unavailable"},
        )
    raise TypeError("unsupported agent metric evidence error")


def create_agent_metric_evidence_router(
    require_local_auth: Callable[..., None],
    service: AgentMetricEvidenceCommand,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["agent-metric-evidence"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(
        "/sessions/{session_id}/agent-metric-evidence/contract",
        response_model=AgentMetricEvidenceAnyFileContract,
    )
    def contract(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AgentMetricEvidenceAnyFileContract:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return service.contract(session_id)
        except (
            AgentMetricEvidenceDefinitionsOutOfDateError,
            MetricLifecycleInputError,
            MetricLifecycleNotFoundError,
            MetricLifecyclePersistenceError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/agent-metric-evidence/preview",
        response_model=AgentMetricEvidencePreviewDto,
    )
    async def preview(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AgentMetricEvidencePreviewDto:
        response.headers.update(_PRIVATE_HEADERS)
        payload = await _bounded_body(request)
        try:
            result = service.preview(session_id=session_id, payload=payload)
        except (
            AgentMetricEvidenceDefinitionsOutOfDateError,
            AgentMetricEvidenceFileError,
            MetricLifecycleInputError,
            MetricLifecycleNotFoundError,
            MetricLifecyclePersistenceError,
            MetricLifecycleStaleWindowError,
        ) as error:
            raise _failure(error) from None
        return AgentMetricEvidencePreviewDto.model_validate(result.model_dump())

    @router.post(
        "/sessions/{session_id}/agent-metric-evidence/import",
        response_model=AgentMetricEvidenceImportDto,
    )
    async def import_file(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        expected_payload_sha256: Annotated[
            str,
            Header(
                alias="X-Agent-Evidence-Payload-SHA256",
                pattern=PSEUDONYM_PATTERN.pattern,
            ),
        ],
        confirmation: Annotated[
            str,
            Header(alias="X-Agent-Evidence-Confirmation", max_length=128),
        ],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> AgentMetricEvidenceImportDto:
        response.headers.update(_PRIVATE_HEADERS)
        payload = await _bounded_body(request)
        try:
            result = service.import_file(
                session_id=session_id,
                payload=payload,
                expected_payload_sha256=expected_payload_sha256,
                confirmation=confirmation,
                idempotency_key=idempotency_key,
            )
        except (
            AgentMetricEvidenceDefinitionsOutOfDateError,
            AgentMetricEvidenceFileError,
            MetricLifecycleConflictError,
            MetricLifecycleInputError,
            MetricLifecycleNotFoundError,
            MetricLifecyclePersistenceError,
            MetricLifecycleStaleWindowError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if result.applied else 200
        return AgentMetricEvidenceImportDto(
            payload_sha256=result.payload_sha256,
            proposal=MetricLifecycleProposalDto.from_view(result.proposal),
            applied=result.applied,
            producer_claim_persisted=result.producer_claim_persisted,
            raw_payload_persisted=result.raw_payload_persisted,
            requires_authenticated_local_user_confirmation=(
                result.requires_authenticated_local_user_confirmation
            ),
        )

    return router


__all__ = (
    "AGENT_METRIC_EVIDENCE_MEDIA_TYPE",
    "AgentMetricEvidenceImportDto",
    "AgentMetricEvidencePreviewDto",
    "create_agent_metric_evidence_router",
)
