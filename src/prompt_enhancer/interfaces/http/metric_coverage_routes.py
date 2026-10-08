"""Authenticated, identifier-free local metric-coverage queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...application.analysis.metric_coverage import (
    MetricCoverageProjectNotFoundError,
    MetricCoverageReport,
    MetricCoverageScope,
    MetricCoverageSelection,
)
from ...domain import PSEUDONYM_PATTERN, Provider


class MetricCoverageQuery(Protocol):
    def report(self, selection: MetricCoverageSelection) -> MetricCoverageReport: ...


def create_metric_coverage_router(
    require_local_auth: Callable[..., None],
    service: MetricCoverageQuery,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1",
        tags=["metric-coverage"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("/metric-coverage", response_model=MetricCoverageReport)
    def provider_metric_coverage(
        provider: Annotated[Provider, Query()] = Provider.CODEX,
    ) -> MetricCoverageReport:
        return service.report(
            MetricCoverageSelection(
                provider=provider,
                scope=MetricCoverageScope.PROVIDER_CATALOG,
            )
        )

    @router.get(
        "/projects/{project_id}/metric-coverage",
        response_model=MetricCoverageReport,
        responses={404: {"description": "Indexed project not found"}},
    )
    def project_metric_coverage(
        project_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        provider: Annotated[Provider, Query()] = Provider.CODEX,
    ) -> MetricCoverageReport:
        try:
            return service.report(
                MetricCoverageSelection(
                    provider=provider,
                    scope=MetricCoverageScope.ONE_PROJECT,
                    project_id=project_id,
                )
            )
        except MetricCoverageProjectNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="indexed project not found",
            ) from None

    return router


__all__ = ["create_metric_coverage_router"]
