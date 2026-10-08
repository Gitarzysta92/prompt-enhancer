"""Authenticated content-free aggregation over selected immutable session runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from ...application.analysis.session_quality_aggregation import (
    SessionQualityAggregate,
    SessionQualityAggregationService,
    SessionQualitySelection,
)
from ...application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from ...application.analysis.text_analysis_presets import COACHING_PROFILE_V1
from ...application.persistence import SessionAnalysisRunRepository
from .dto import HttpDto, Pseudonym


class SessionQualityAggregateRequest(HttpDto):
    """A bounded selection kept in the request body rather than the URL."""

    session_ids: list[Pseudonym] = Field(min_length=1, max_length=100)


class SessionQualityAggregationStore(Protocol):
    def session_analysis_run_repository(self) -> SessionAnalysisRunRepository: ...


def create_session_quality_aggregation_router(
    require_local_token: Callable[..., None],
) -> APIRouter:
    """Compute a read-only ratio-of-sums projection without provider access."""

    router = APIRouter(
        prefix="/v1",
        tags=["session-quality-analysis"],
        dependencies=[Depends(require_local_token)],
    )

    @router.post(
        "/quality-analysis/aggregate",
        response_model=SessionQualityAggregate,
    )
    def aggregate_selected_session_quality(
        request: Request,
        payload: SessionQualityAggregateRequest,
    ) -> SessionQualityAggregate:
        try:
            selection = SessionQualitySelection(session_ids=tuple(payload.session_ids))
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="quality analysis selection is invalid",
            ) from error
        try:
            store = cast(SessionQualityAggregationStore, request.app.state.database)
            return SessionQualityAggregationService(
                store.session_analysis_run_repository(),
                definitions=COACHING_METRIC_DEFINITIONS,
                analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
                analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
                metric_pack_key=COACHING_METRIC_PACK_KEY,
                metric_pack_version=COACHING_METRIC_PACK_VERSION,
            ).aggregate(selection)
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(
                status_code=503,
                detail="quality analysis aggregation is unavailable",
            ) from error

    return router
