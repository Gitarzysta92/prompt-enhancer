"""Authenticated, content-free provider and metric-readiness queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...application.analysis.metric_readiness import (
    MetricReadinessPresetUnsupportedError,
    MetricReadinessSessionNotFoundError,
    ProviderCapabilityReport,
    SessionMetricReadinessReport,
)
from ...application.analysis.text_analysis_presets import TextAnalysisPresetId
from ...domain import PSEUDONYM_PATTERN, Provider


class MetricReadinessQuery(Protocol):
    def provider_capabilities(self, provider: Provider) -> ProviderCapabilityReport: ...

    def session_readiness(
        self,
        session_id: str,
        *,
        preset_id: TextAnalysisPresetId = TextAnalysisPresetId.COACHING_PROFILE_V1,
    ) -> SessionMetricReadinessReport: ...


def create_metric_readiness_router(
    require_local_auth: Callable[..., None],
    service: MetricReadinessQuery,
) -> APIRouter:
    """Expose cached/read-only readiness without initiating provider access."""

    router = APIRouter(
        prefix="/v1",
        tags=["metric-readiness"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(
        "/providers/{provider}/capabilities",
        response_model=ProviderCapabilityReport,
    )
    def provider_capabilities(provider: Provider) -> ProviderCapabilityReport:
        return service.provider_capabilities(provider)

    @router.get(
        "/sessions/{session_id}/metric-readiness",
        response_model=SessionMetricReadinessReport,
        responses={
            404: {"description": "Indexed session not found"},
            409: {"description": "Metric readiness preset unavailable"},
        },
    )
    def session_metric_readiness(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        preset_id: Annotated[
            TextAnalysisPresetId,
            Query(),
        ] = TextAnalysisPresetId.COACHING_PROFILE_V1,
    ) -> SessionMetricReadinessReport:
        try:
            return service.session_readiness(session_id, preset_id=preset_id)
        except MetricReadinessSessionNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="indexed session not found",
            ) from None
        except MetricReadinessPresetUnsupportedError:
            raise HTTPException(
                status_code=409,
                detail="metric readiness preset is unavailable",
            ) from None

    return router


__all__ = ["create_metric_readiness_router"]
