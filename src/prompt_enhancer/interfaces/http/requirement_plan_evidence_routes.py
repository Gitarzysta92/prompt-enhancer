"""Authenticated local boundary for reviewed requirement-to-plan evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import Field, model_validator

from ...application.analysis.requirement_plan_evidence import (
    MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES,
    MAX_REQUIREMENT_PLAN_PAGE_SIZE,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ExcludedRequirementClause,
    PlanCoordinate,
    RequirementEvidenceEntry,
    RequirementPlanConflictError,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
    RequirementPlanDefinitionsOutOfDateError,
    RequirementPlanEvidenceContract,
    RequirementPlanEvidencePreview,
    RequirementPlanInputError,
    RequirementPlanNotFoundError,
    RequirementPlanPersistenceError,
    RequirementPlanProducerReceipt,
    RequirementPlanProposalStatus,
    RequirementPlanProposalPageSnapshot,
    RequirementPlanProposalReview,
    RequirementPlanProposalView,
    RequirementPlanStaleWindowError,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel


REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.prompt-enhancer.requirement-plan-evidence+json"
)
_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
_EVIDENCE_FILE_REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE: {
                "schema": {
                    "type": "string",
                    "format": "binary",
                    "maxLength": MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES,
                }
            }
        },
    }
}


class RequirementPlanEvidenceCommand(Protocol):
    def contract(self, session_id: str) -> RequirementPlanEvidenceContract: ...

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> RequirementPlanEvidencePreview: ...

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[RequirementPlanProposalView, bool]: ...

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: RequirementPlanDecisionCommand,
        idempotency_key: str,
    ) -> tuple[RequirementPlanProposalView, bool]: ...

    def review_proposal(
        self,
        *,
        session_id: str,
        proposal_id: str,
        expected_source_run_id: str,
    ) -> RequirementPlanProposalReview: ...

    def list_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementPlanProposalView, ...],
        RequirementPlanProposalPageSnapshot,
    ]: ...


class RequirementPlanProposalDto(StrictModel):
    proposal_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    source_run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    source_window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    expected_predecessor_confirmation_id: str | None = Field(
        default=None, pattern=PSEUDONYM_PATTERN.pattern
    )
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    producer_receipt: RequirementPlanProducerReceipt
    review_rubric_version: Literal[REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION]
    requirements: tuple[RequirementEvidenceEntry, ...]
    excluded_user_clauses: tuple[ExcludedRequirementClause, ...]
    plan_items: tuple[PlanCoordinate, ...]
    created_at: datetime
    schema_version: str
    policy_version: str
    status: RequirementPlanProposalStatus
    decision_id: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    decision: RequirementPlanDecisionKind | None = None
    decided_at: datetime | None = None
    confirmation_authority: Literal["owned_native_user_presence"] | None = None
    local_only: bool
    content_persisted: bool

    @classmethod
    def from_view(cls, view: RequirementPlanProposalView) -> "RequirementPlanProposalDto":
        proposal = view.proposal
        decision = view.decision
        return cls(
            proposal_id=proposal.proposal_id,
            session_id=proposal.session_id,
            source_run_id=proposal.source_run_id,
            source_window_fingerprint=proposal.source_window_fingerprint,
            expected_predecessor_confirmation_id=(
                proposal.expected_predecessor_confirmation_id
            ),
            payload_sha256=proposal.payload_sha256,
            producer_receipt=proposal.producer_receipt,
            review_rubric_version=proposal.review_rubric_version,
            requirements=proposal.requirements,
            excluded_user_clauses=proposal.excluded_user_clauses,
            plan_items=proposal.plan_items,
            created_at=proposal.created_at,
            schema_version=proposal.schema_version,
            policy_version=proposal.policy_version,
            status=view.status,
            decision_id=None if decision is None else decision.decision_id,
            decision=None if decision is None else decision.decision,
            decided_at=None if decision is None else decision.decided_at,
            confirmation_authority=(
                None if decision is None else decision.confirmation_authority
            ),
            local_only=proposal.local_only,
            content_persisted=proposal.content_persisted,
        )


class RequirementPlanImportDto(StrictModel):
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    proposal: RequirementPlanProposalDto
    applied: bool
    creates_unconfirmed_proposal_only: bool = True
    native_confirmation_required_for_metric_authority: bool = True
    raw_payload_persisted: bool = False


class RequirementPlanProposalOutcomeDto(StrictModel):
    proposal: RequirementPlanProposalDto
    applied: bool


class RequirementPlanReviewCommand(StrictModel):
    expected_source_run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    confirmation: Literal["open_exact_local_requirement_plan_clause_review"]


class RequirementPlanProposalPageDto(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    proposals: tuple[RequirementPlanProposalDto, ...] = Field(
        max_length=MAX_REQUIREMENT_PLAN_PAGE_SIZE
    )
    limit: int = Field(ge=1, le=MAX_REQUIREMENT_PLAN_PAGE_SIZE)
    offset: int = Field(ge=0, le=1_000_000)
    total: int = Field(ge=0, le=1_000_000)
    snapshot: RequirementPlanProposalPageSnapshot
    next_offset: int | None = Field(default=None, ge=1, le=1_000_000)
    complete: bool

    @model_validator(mode="after")
    def exact_snapshot_page(self) -> "RequirementPlanProposalPageDto":
        consumed = self.offset + len(self.proposals)
        expected_complete = consumed == self.total
        expected_next = None if expected_complete else consumed
        if (
            self.snapshot.total != self.total
            or consumed > self.total
            or self.complete != expected_complete
            or self.next_offset != expected_next
        ):
            raise ValueError("requirement-plan page metadata is incoherent")
        return self

    @classmethod
    def from_page(
        cls,
        *,
        session_id: str,
        proposals: tuple[RequirementPlanProposalView, ...],
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot,
    ) -> "RequirementPlanProposalPageDto":
        consumed = offset + len(proposals)
        if consumed > snapshot.total:
            raise ValueError("requirement-plan page exceeds its stable snapshot")
        complete = consumed == snapshot.total
        return cls(
            session_id=session_id,
            proposals=tuple(
                RequirementPlanProposalDto.from_view(item) for item in proposals
            ),
            limit=limit,
            offset=offset,
            total=snapshot.total,
            snapshot=snapshot,
            next_offset=None if complete else consumed,
            complete=complete,
        )


async def _bounded_body(request: Request) -> bytes:
    if request.headers.get("content-type", "").strip().lower() != (
        REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE
    ):
        raise HTTPException(
            415,
            detail={
                "code": "requirement_plan_evidence_media_type_required",
                "message": "requirement-plan evidence requires its exact local file media type",
            },
            headers=_PRIVATE_HEADERS,
        )
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_REQUIREMENT_PLAN_EVIDENCE_BYTES:
            raise HTTPException(
                413,
                detail={
                    "code": "requirement_plan_evidence_too_large",
                    "message": "requirement-plan evidence exceeds the local file limit",
                },
                headers=_PRIVATE_HEADERS,
            )
    return bytes(payload)


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, RequirementPlanDefinitionsOutOfDateError):
        status, message = 409, "requirement-plan definitions are out of date"
    elif isinstance(error, RequirementPlanInputError):
        status, message = 422, "requirement-plan evidence is invalid"
    elif isinstance(error, RequirementPlanNotFoundError):
        status, message = 404, "requirement-plan evidence authority was not found"
    elif isinstance(error, (RequirementPlanStaleWindowError, RequirementPlanConflictError)):
        status, message = 409, "requirement-plan evidence binding changed"
    elif isinstance(error, RequirementPlanPersistenceError):
        status, message = 503, "requirement-plan evidence is unavailable"
    else:
        raise TypeError("unsupported requirement-plan evidence error")
    return HTTPException(
        status,
        detail={"code": error.code, "message": message},
        headers=_PRIVATE_HEADERS,
    )


def create_requirement_plan_evidence_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: RequirementPlanEvidenceCommand,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["requirement-plan-evidence"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(
        "/sessions/{session_id}/requirement-plan-evidence/contract",
        response_model=RequirementPlanEvidenceContract,
    )
    def contract(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementPlanEvidenceContract:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return service.contract(session_id)
        except (
            RequirementPlanDefinitionsOutOfDateError,
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/requirement-plan-evidence/preview",
        response_model=RequirementPlanEvidencePreview,
        openapi_extra=_EVIDENCE_FILE_REQUEST_BODY,
    )
    async def preview(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementPlanEvidencePreview:
        response.headers.update(_PRIVATE_HEADERS)
        payload = await _bounded_body(request)
        try:
            return service.preview(session_id=session_id, payload=payload)
        except (
            RequirementPlanDefinitionsOutOfDateError,
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
            RequirementPlanStaleWindowError,
            RequirementPlanConflictError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/requirement-plan-evidence/import",
        response_model=RequirementPlanImportDto,
        responses={
            201: {
                "model": RequirementPlanImportDto,
                "description": "A new inert requirement-plan proposal was created.",
            }
        },
        openapi_extra=_EVIDENCE_FILE_REQUEST_BODY,
    )
    async def import_file(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        expected_payload_sha256: Annotated[
            str,
            Header(
                alias="X-Requirement-Plan-Payload-SHA256",
                pattern=PSEUDONYM_PATTERN.pattern,
            ),
        ],
        confirmation: Annotated[
            str,
            Header(alias="X-Requirement-Plan-Confirmation", max_length=128),
        ],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> RequirementPlanImportDto:
        response.headers.update(_PRIVATE_HEADERS)
        payload = await _bounded_body(request)
        try:
            view, applied = service.import_file(
                session_id=session_id,
                payload=payload,
                expected_payload_sha256=expected_payload_sha256,
                confirmation=confirmation,
                idempotency_key=idempotency_key,
            )
        except (
            RequirementPlanDefinitionsOutOfDateError,
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
            RequirementPlanStaleWindowError,
            RequirementPlanConflictError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementPlanImportDto(
            payload_sha256=view.proposal.payload_sha256,
            proposal=RequirementPlanProposalDto.from_view(view),
            applied=applied,
        )

    @router.post(
        "/sessions/{session_id}/requirement-plan-evidence/proposals/{proposal_id}/review",
        response_model=RequirementPlanProposalReview,
        dependencies=[Depends(require_user_confirmation)],
    )
    def review_proposal(
        payload: RequirementPlanReviewCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        proposal_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementPlanProposalReview:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            review = service.review_proposal(
                session_id=session_id,
                proposal_id=proposal_id,
                expected_source_run_id=payload.expected_source_run_id,
            )
        except (
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
            RequirementPlanStaleWindowError,
            RequirementPlanConflictError,
        ) as error:
            raise _failure(error) from None
        return review

    @router.post(
        "/sessions/{session_id}/requirement-plan-evidence/proposals/{proposal_id}/decision",
        response_model=RequirementPlanProposalOutcomeDto,
        responses={
            201: {
                "model": RequirementPlanProposalOutcomeDto,
                "description": "A new owned-native decision was recorded.",
            }
        },
        dependencies=[Depends(require_user_confirmation)],
    )
    def decide(
        payload: RequirementPlanDecisionCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        proposal_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> RequirementPlanProposalOutcomeDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            view, applied = service.decide(
                session_id=session_id,
                proposal_id=proposal_id,
                command=payload,
                idempotency_key=idempotency_key,
            )
        except (
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
            RequirementPlanStaleWindowError,
            RequirementPlanConflictError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementPlanProposalOutcomeDto(
            proposal=RequirementPlanProposalDto.from_view(view),
            applied=applied,
        )

    @router.get(
        "/sessions/{session_id}/requirement-plan-evidence/proposal-page",
        response_model=RequirementPlanProposalPageDto,
    )
    def proposal_page(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=MAX_REQUIREMENT_PLAN_PAGE_SIZE)] = 100,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        snapshot_id: Annotated[
            str | None, Query(pattern=PSEUDONYM_PATTERN.pattern)
        ] = None,
        snapshot_total: Annotated[
            int | None, Query(ge=0, le=1_000_000)
        ] = None,
        snapshot_decision_count: Annotated[
            int | None, Query(ge=0, le=1_000_000)
        ] = None,
        snapshot_high_water_created_at: datetime | None = None,
        snapshot_high_water_proposal_id: Annotated[
            str | None, Query(pattern=PSEUDONYM_PATTERN.pattern)
        ] = None,
    ) -> RequirementPlanProposalPageDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            snapshot_values = (
                snapshot_id,
                snapshot_total,
                snapshot_decision_count,
                snapshot_high_water_created_at,
                snapshot_high_water_proposal_id,
            )
            supplied_snapshot = any(value is not None for value in snapshot_values)
            if supplied_snapshot:
                if (
                    snapshot_id is None
                    or snapshot_total is None
                    or snapshot_decision_count is None
                ):
                    raise RequirementPlanInputError(
                        "requirement-plan page snapshot is incomplete"
                    )
                snapshot = RequirementPlanProposalPageSnapshot(
                    snapshot_id=snapshot_id,
                    total=snapshot_total,
                    decision_count=snapshot_decision_count,
                    high_water_created_at=snapshot_high_water_created_at,
                    high_water_proposal_id=snapshot_high_water_proposal_id,
                )
            else:
                snapshot = None
            if offset > 0 and snapshot is None:
                raise RequirementPlanInputError(
                    "a stable requirement-plan page snapshot is required"
                )
            proposals, resolved_snapshot = service.list_page(
                session_id, limit=limit, offset=offset, snapshot=snapshot
            )
        except (
            ValueError,
            RequirementPlanInputError,
            RequirementPlanNotFoundError,
            RequirementPlanPersistenceError,
            RequirementPlanConflictError,
        ) as error:
            if isinstance(error, ValueError) and not isinstance(
                error, RequirementPlanInputError
            ):
                error = RequirementPlanInputError(
                    "requirement-plan page snapshot is invalid"
                )
            raise _failure(error) from None
        return RequirementPlanProposalPageDto.from_page(
            session_id=session_id,
            proposals=proposals,
            limit=limit,
            offset=offset,
            snapshot=resolved_snapshot,
        )

    return router


__all__ = (
    "REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE",
    "RequirementPlanImportDto",
    "RequirementPlanProposalDto",
    "RequirementPlanProposalOutcomeDto",
    "RequirementPlanProposalPageDto",
    "RequirementPlanReviewCommand",
    "create_requirement_plan_evidence_router",
)
