"""Authenticated local boundary for reviewed requirement-to-action evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import Field, model_validator

from ...application.analysis.evidence_contracts import TypedEvidenceProvenance
from ...application.analysis.requirement_action_evidence import (
    MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES,
    MAX_REQUIREMENT_ACTION_CANDIDATES,
    MAX_REQUIREMENT_ACTION_PAGE_SIZE,
    MAX_REQUIREMENT_ACTION_REQUIREMENTS,
    REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION,
    REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION,
    REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
    REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION,
    ConfirmedRequirementActionLink,
    RequirementActionCandidate,
    RequirementActionConflictError,
    RequirementActionDecisionCommand,
    RequirementActionDecisionKind,
    RequirementActionDefinitionsOutOfDateError,
    RequirementActionEvidenceContract,
    RequirementActionEvidencePreview,
    RequirementActionInputError,
    RequirementActionNotFoundError,
    RequirementActionPersistenceError,
    RequirementActionProposalPageSnapshot,
    RequirementActionProposalReview,
    RequirementActionProposalStatus,
    RequirementActionProposalView,
    RequirementActionRequirement,
    RequirementActionStaleWindowError,
)
from ...application.analysis.requirement_plan_evidence import (
    RequirementPlanProducerReceipt,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel


REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.prompt-enhancer.requirement-action-evidence+json"
)
_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
_EVIDENCE_FILE_REQUEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE: {
                "schema": {
                    "type": "string",
                    "format": "binary",
                    "maxLength": MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES,
                }
            }
        },
    }
}


class RequirementActionEvidenceCommand(Protocol):
    def contract(self, session_id: str) -> RequirementActionEvidenceContract: ...

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> RequirementActionEvidencePreview: ...

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[RequirementActionProposalView, bool]: ...

    def review_proposal(
        self,
        *,
        session_id: str,
        proposal_id: str,
        expected_source_run_id: str,
    ) -> RequirementActionProposalReview: ...

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: RequirementActionDecisionCommand,
        idempotency_key: str,
    ) -> tuple[RequirementActionProposalView, bool]: ...

    def list_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementActionProposalView, ...],
        RequirementActionProposalPageSnapshot,
    ]: ...


class RequirementActionProposalDto(StrictModel):
    """Durable content-free proposal view; producer prose never crosses this wire."""

    proposal_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    source_run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    source_window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    requirement_plan_confirmation_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    requirement_plan_evidence_fingerprint: str = Field(
        pattern=PSEUDONYM_PATTERN.pattern
    )
    candidate_manifest_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    candidate_provenance: TypedEvidenceProvenance
    candidate_extraction_complete: bool
    candidate_enumeration_complete: bool
    expected_predecessor_confirmation_id: str | None = Field(
        default=None, pattern=PSEUDONYM_PATTERN.pattern
    )
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    producer_receipt: RequirementPlanProducerReceipt
    review_rubric_version: Literal[REQUIREMENT_ACTION_REVIEW_RUBRIC_VERSION]
    requirements: tuple[RequirementActionRequirement, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    candidates: tuple[RequirementActionCandidate, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    links: tuple[ConfirmedRequirementActionLink, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_REQUIREMENTS
    )
    created_at: datetime
    schema_version: Literal[REQUIREMENT_ACTION_EVIDENCE_SCHEMA_VERSION]
    policy_version: Literal[REQUIREMENT_ACTION_EVIDENCE_POLICY_VERSION]
    status: RequirementActionProposalStatus
    decision_id: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    decision: RequirementActionDecisionKind | None = None
    decided_at: datetime | None = None
    confirmation_authority: Literal["owned_native_user_presence"] | None = None
    local_only: Literal[True]
    content_persisted: Literal[False]

    @classmethod
    def from_view(
        cls, view: RequirementActionProposalView
    ) -> "RequirementActionProposalDto":
        proposal = view.proposal
        decision = view.decision
        return cls(
            proposal_id=proposal.proposal_id,
            session_id=proposal.session_id,
            source_run_id=proposal.source_run_id,
            source_window_fingerprint=proposal.source_window_fingerprint,
            requirement_plan_confirmation_id=(
                proposal.requirement_plan_confirmation_id
            ),
            requirement_plan_evidence_fingerprint=(
                proposal.requirement_plan_evidence_fingerprint
            ),
            candidate_manifest_fingerprint=proposal.candidate_manifest_fingerprint,
            candidate_provenance=proposal.candidate_provenance,
            candidate_extraction_complete=proposal.candidate_extraction_complete,
            candidate_enumeration_complete=proposal.candidate_enumeration_complete,
            expected_predecessor_confirmation_id=(
                proposal.expected_predecessor_confirmation_id
            ),
            payload_sha256=proposal.payload_sha256,
            producer_receipt=proposal.producer_receipt,
            review_rubric_version=proposal.review_rubric_version,
            requirements=proposal.requirements,
            candidates=proposal.candidates,
            links=proposal.links,
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


class RequirementActionImportDto(StrictModel):
    payload_sha256: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    proposal: RequirementActionProposalDto
    applied: bool
    creates_unconfirmed_proposal_only: Literal[True] = True
    native_confirmation_required_for_metric_authority: Literal[True] = True
    raw_payload_persisted: Literal[False] = False
    raw_producer_claim_persisted: Literal[False] = False


class RequirementActionProposalOutcomeDto(StrictModel):
    proposal: RequirementActionProposalDto
    applied: bool


class RequirementActionReviewCommand(StrictModel):
    expected_source_run_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    confirmation: Literal[REQUIREMENT_ACTION_REVIEW_CONFIRMATION]


class RequirementActionProposalPageDto(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    proposals: tuple[RequirementActionProposalDto, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_PAGE_SIZE
    )
    limit: int = Field(ge=1, le=MAX_REQUIREMENT_ACTION_PAGE_SIZE)
    offset: int = Field(ge=0, le=1_000_000)
    total: int = Field(ge=0, le=1_000_000)
    snapshot: RequirementActionProposalPageSnapshot
    next_offset: int | None = Field(default=None, ge=1, le=1_000_000)
    complete: bool

    @model_validator(mode="after")
    def exact_snapshot_page(self) -> "RequirementActionProposalPageDto":
        consumed = self.offset + len(self.proposals)
        expected_complete = consumed == self.total
        expected_next = None if expected_complete else consumed
        if (
            self.snapshot.total != self.total
            or consumed > self.total
            or self.complete != expected_complete
            or self.next_offset != expected_next
        ):
            raise ValueError("requirement-action page metadata is incoherent")
        return self

    @classmethod
    def from_page(
        cls,
        *,
        session_id: str,
        proposals: tuple[RequirementActionProposalView, ...],
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot,
    ) -> "RequirementActionProposalPageDto":
        consumed = offset + len(proposals)
        if consumed > snapshot.total:
            raise ValueError("requirement-action page exceeds its stable snapshot")
        complete = consumed == snapshot.total
        return cls(
            session_id=session_id,
            proposals=tuple(
                RequirementActionProposalDto.from_view(item) for item in proposals
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
        REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE
    ):
        raise HTTPException(
            415,
            detail={
                "code": "requirement_action_evidence_media_type_required",
                "message": (
                    "requirement-action evidence requires its exact local file media type"
                ),
            },
            headers=_PRIVATE_HEADERS,
        )
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES:
            raise HTTPException(
                413,
                detail={
                    "code": "requirement_action_evidence_too_large",
                    "message": "requirement-action evidence exceeds the local file limit",
                },
                headers=_PRIVATE_HEADERS,
            )
    return bytes(payload)


def _failure(error: Exception) -> HTTPException:
    if isinstance(error, RequirementActionDefinitionsOutOfDateError):
        status, message = 409, "requirement-action definitions are out of date"
    elif isinstance(error, RequirementActionInputError):
        status, message = 422, "requirement-action evidence is invalid"
    elif isinstance(error, RequirementActionNotFoundError):
        status, message = 404, "requirement-action evidence authority was not found"
    elif isinstance(
        error, (RequirementActionStaleWindowError, RequirementActionConflictError)
    ):
        status, message = 409, "requirement-action evidence binding changed"
    elif isinstance(error, RequirementActionPersistenceError):
        status, message = 503, "requirement-action evidence is unavailable"
    else:
        raise TypeError("unsupported requirement-action evidence error")
    return HTTPException(
        status,
        detail={"code": error.code, "message": message},
        headers=_PRIVATE_HEADERS,
    )


def create_requirement_action_evidence_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: RequirementActionEvidenceCommand,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["requirement-action-evidence"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(
        "/sessions/{session_id}/requirement-action-evidence/contract",
        response_model=RequirementActionEvidenceContract,
    )
    def contract(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementActionEvidenceContract:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return service.contract(session_id)
        except (
            RequirementActionDefinitionsOutOfDateError,
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/requirement-action-evidence/preview",
        response_model=RequirementActionEvidencePreview,
        openapi_extra=_EVIDENCE_FILE_REQUEST_BODY,
    )
    async def preview(
        request: Request,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementActionEvidencePreview:
        response.headers.update(_PRIVATE_HEADERS)
        payload = await _bounded_body(request)
        try:
            return service.preview(session_id=session_id, payload=payload)
        except (
            RequirementActionDefinitionsOutOfDateError,
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
            RequirementActionStaleWindowError,
            RequirementActionConflictError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/requirement-action-evidence/import",
        response_model=RequirementActionImportDto,
        responses={
            201: {
                "model": RequirementActionImportDto,
                "description": "A new inert requirement-action proposal was created.",
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
                alias="X-Requirement-Action-Payload-SHA256",
                pattern=PSEUDONYM_PATTERN.pattern,
            ),
        ],
        confirmation: Annotated[
            str,
            Header(alias="X-Requirement-Action-Confirmation", max_length=128),
        ],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> RequirementActionImportDto:
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
            RequirementActionDefinitionsOutOfDateError,
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
            RequirementActionStaleWindowError,
            RequirementActionConflictError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementActionImportDto(
            payload_sha256=view.proposal.payload_sha256,
            proposal=RequirementActionProposalDto.from_view(view),
            applied=applied,
        )

    @router.post(
        "/sessions/{session_id}/requirement-action-evidence/proposals/{proposal_id}/review",
        response_model=RequirementActionProposalReview,
        dependencies=[Depends(require_user_confirmation)],
    )
    def review_proposal(
        payload: RequirementActionReviewCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        proposal_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> RequirementActionProposalReview:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            return service.review_proposal(
                session_id=session_id,
                proposal_id=proposal_id,
                expected_source_run_id=payload.expected_source_run_id,
            )
        except (
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
            RequirementActionStaleWindowError,
            RequirementActionConflictError,
        ) as error:
            raise _failure(error) from None

    @router.post(
        "/sessions/{session_id}/requirement-action-evidence/proposals/{proposal_id}/decision",
        response_model=RequirementActionProposalOutcomeDto,
        responses={
            201: {
                "model": RequirementActionProposalOutcomeDto,
                "description": "A new owned-native decision was recorded.",
            }
        },
        dependencies=[Depends(require_user_confirmation)],
    )
    def decide(
        payload: RequirementActionDecisionCommand,
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        proposal_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", pattern=SAFE_VERSION_PATTERN.pattern),
        ],
    ) -> RequirementActionProposalOutcomeDto:
        response.headers.update(_PRIVATE_HEADERS)
        try:
            view, applied = service.decide(
                session_id=session_id,
                proposal_id=proposal_id,
                command=payload,
                idempotency_key=idempotency_key,
            )
        except (
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
            RequirementActionStaleWindowError,
            RequirementActionConflictError,
        ) as error:
            raise _failure(error) from None
        response.status_code = 201 if applied else 200
        return RequirementActionProposalOutcomeDto(
            proposal=RequirementActionProposalDto.from_view(view), applied=applied
        )

    @router.get(
        "/sessions/{session_id}/requirement-action-evidence/proposal-page",
        response_model=RequirementActionProposalPageDto,
    )
    def proposal_page(
        response: Response,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=MAX_REQUIREMENT_ACTION_PAGE_SIZE)] = 100,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        snapshot_id: Annotated[
            str | None, Query(pattern=PSEUDONYM_PATTERN.pattern)
        ] = None,
        snapshot_total: Annotated[int | None, Query(ge=0, le=1_000_000)] = None,
        snapshot_decision_count: Annotated[
            int | None, Query(ge=0, le=1_000_000)
        ] = None,
        snapshot_high_water_created_at: datetime | None = None,
        snapshot_high_water_proposal_id: Annotated[
            str | None, Query(pattern=PSEUDONYM_PATTERN.pattern)
        ] = None,
    ) -> RequirementActionProposalPageDto:
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
                    raise RequirementActionInputError(
                        "requirement-action page snapshot is incomplete"
                    )
                snapshot = RequirementActionProposalPageSnapshot(
                    snapshot_id=snapshot_id,
                    total=snapshot_total,
                    decision_count=snapshot_decision_count,
                    high_water_created_at=snapshot_high_water_created_at,
                    high_water_proposal_id=snapshot_high_water_proposal_id,
                )
            else:
                snapshot = None
            if offset > 0 and snapshot is None:
                raise RequirementActionInputError(
                    "a stable requirement-action page snapshot is required"
                )
            proposals, resolved_snapshot = service.list_page(
                session_id, limit=limit, offset=offset, snapshot=snapshot
            )
        except (
            ValueError,
            RequirementActionInputError,
            RequirementActionNotFoundError,
            RequirementActionPersistenceError,
            RequirementActionConflictError,
        ) as error:
            if isinstance(error, ValueError) and not isinstance(
                error, RequirementActionInputError
            ):
                error = RequirementActionInputError(
                    "requirement-action page snapshot is invalid"
                )
            raise _failure(error) from None
        return RequirementActionProposalPageDto.from_page(
            session_id=session_id,
            proposals=proposals,
            limit=limit,
            offset=offset,
            snapshot=resolved_snapshot,
        )

    return router


__all__ = (
    "REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE",
    "RequirementActionImportDto",
    "RequirementActionProposalDto",
    "RequirementActionProposalOutcomeDto",
    "RequirementActionProposalPageDto",
    "RequirementActionReviewCommand",
    "create_requirement_action_evidence_router",
)
