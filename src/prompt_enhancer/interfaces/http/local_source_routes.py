"""Content-free HTTP commands for explicitly authorized local sources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from ...application.display_labels import (
    DisplayLabelError,
    DisplayLabelSelectionError,
    LabelEnrichmentReport,
    MAX_LABEL_ENRICHMENT_SELECTORS,
    MAX_LABEL_ENRICHMENT_SESSIONS,
)
from ...application.local_sources import (
    CodexLocalSourceService,
    CodexLocalSourceStatus,
    LocalSourceSelectionError,
    MAX_LOCAL_SOURCE_SELECTORS,
)
from ...domain import PSEUDONYM_PATTERN, StrictModel
from ...ingestion import ConsentRequiredError, IngestionError, IngestionReport


Pseudonym = Annotated[str, Field(pattern=PSEUDONYM_PATTERN.pattern)]


class CodexIndexRequest(StrictModel):
    max_sessions: int = Field(default=500, ge=1, le=1_000)


class CodexAnalysisRequest(StrictModel):
    project_ids: frozenset[Pseudonym] = Field(
        default_factory=frozenset, max_length=MAX_LOCAL_SOURCE_SELECTORS
    )
    session_ids: frozenset[Pseudonym] = Field(
        default_factory=frozenset, max_length=MAX_LOCAL_SOURCE_SELECTORS
    )
    max_sessions: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def require_selection(self) -> CodexAnalysisRequest:
        if not self.project_ids and not self.session_ids:
            raise ValueError("a safe project or session selection is required")
        if (
            len(self.project_ids) + len(self.session_ids)
            > MAX_LOCAL_SOURCE_SELECTORS
        ):
            raise ValueError("local-source selection exceeds the safe bound")
        return self


class CodexLabelEnrichmentRequest(StrictModel):
    project_ids: frozenset[Pseudonym] = Field(
        default_factory=frozenset, max_length=MAX_LABEL_ENRICHMENT_SELECTORS
    )
    session_ids: frozenset[Pseudonym] = Field(
        default_factory=frozenset, max_length=MAX_LABEL_ENRICHMENT_SELECTORS
    )
    max_sessions: int = Field(
        default=10, ge=1, le=MAX_LABEL_ENRICHMENT_SESSIONS
    )

    @model_validator(mode="after")
    def require_selection(self) -> CodexLabelEnrichmentRequest:
        if not self.project_ids and not self.session_ids:
            raise ValueError("a safe project or session selection is required")
        if (
            len(self.project_ids) + len(self.session_ids)
            > MAX_LABEL_ENRICHMENT_SELECTORS
        ):
            raise ValueError("label selection exceeds the safe bound")
        return self


def create_local_source_router(
    require_local_auth: Callable[..., None],
    service: CodexLocalSourceService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/local-sources/codex",
        tags=["local-sources"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("")
    def status() -> CodexLocalSourceStatus:
        return service.status()

    @router.post("/consents/local-history")
    def grant_consent() -> CodexLocalSourceStatus:
        return service.grant_local_history()

    @router.delete("/consents/local-history")
    def revoke_consent() -> CodexLocalSourceStatus:
        return service.revoke_local_history()

    @router.post("/index")
    def index(payload: CodexIndexRequest) -> IngestionReport:
        return _ingest(lambda: service.index(max_sessions=payload.max_sessions))

    @router.post("/analysis")
    def analyze(payload: CodexAnalysisRequest) -> IngestionReport:
        return _ingest(
            lambda: service.analyze(
                project_ids=payload.project_ids,
                session_ids=payload.session_ids,
                max_sessions=payload.max_sessions,
            )
        )

    @router.post("/display-labels/enrich")
    def enrich_labels(
        payload: CodexLabelEnrichmentRequest,
    ) -> LabelEnrichmentReport:
        return _enrich(
            lambda: service.enrich_labels(
                project_ids=payload.project_ids,
                session_ids=payload.session_ids,
                max_sessions=payload.max_sessions,
            )
        )

    return router


def _ingest(operation: Callable[[], IngestionReport]) -> IngestionReport:
    try:
        return operation()
    except ConsentRequiredError:
        raise HTTPException(
            status_code=403, detail="local-history consent required"
        ) from None
    except LocalSourceSelectionError:
        raise HTTPException(
            status_code=404, detail="selected local source is not indexed"
        ) from None
    except IngestionError:
        raise HTTPException(
            status_code=503, detail="local source unavailable"
        ) from None


def _enrich(
    operation: Callable[[], LabelEnrichmentReport],
) -> LabelEnrichmentReport:
    try:
        return operation()
    except ConsentRequiredError:
        raise HTTPException(
            status_code=403, detail="local-history consent required"
        ) from None
    except DisplayLabelSelectionError:
        raise HTTPException(
            status_code=404, detail="selected local source is not indexed"
        ) from None
    except (DisplayLabelError, IngestionError):
        raise HTTPException(
            status_code=503, detail="local label source unavailable"
        ) from None
