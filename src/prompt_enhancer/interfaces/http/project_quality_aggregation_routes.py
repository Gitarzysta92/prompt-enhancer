"""Authenticated, identifier-free multi-project quality aggregation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator

from ...application.analysis.project_quality_aggregation import (
    ProjectQualityAggregate,
    ProjectQualityAggregationError,
    ProjectQualityAggregationService,
    ProjectQualitySelection,
    ProjectQualitySelectionIncompleteError,
    ProjectQualitySelectionLimitError,
    ProjectQualitySelectionMode,
)
from .dto import HttpDto, Pseudonym


class ProjectQualityAggregateRequest(HttpDto):
    """Complete safe-index project scope; raw data is never accepted here."""

    project_ids: list[Pseudonym] = Field(min_length=1, max_length=25)
    selection_mode: Literal["all_analyzed_work"] = "all_analyzed_work"

    @model_validator(mode="after")
    def reject_duplicates(self) -> ProjectQualityAggregateRequest:
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("project selectors cannot contain duplicates")
        return self


def create_project_quality_aggregation_router(
    require_local_token: Callable[..., None],
    service: ProjectQualityAggregationService,
) -> APIRouter:
    """Expose one bounded local query with no provider-access dependency."""

    router = APIRouter(
        prefix="/v1",
        tags=["project-quality-analysis"],
        dependencies=[Depends(require_local_token)],
    )

    @router.post(
        "/quality-analysis/aggregate-projects",
        response_model=ProjectQualityAggregate,
    )
    def aggregate_selected_project_quality(
        payload: ProjectQualityAggregateRequest,
    ) -> ProjectQualityAggregate:
        selection = ProjectQualitySelection(
            project_ids=tuple(payload.project_ids),
            selection_mode=ProjectQualitySelectionMode(payload.selection_mode),
        )
        try:
            return service.aggregate(selection)
        except ProjectQualitySelectionLimitError as error:
            raise HTTPException(
                status_code=422,
                detail="project quality selection exceeds the local session limit",
            ) from error
        except ProjectQualitySelectionIncompleteError as error:
            raise HTTPException(
                status_code=409,
                detail="project quality selection is incomplete",
            ) from error
        except (
            ProjectQualityAggregationError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            raise HTTPException(
                status_code=503,
                detail="project quality aggregation is unavailable",
            ) from error

    return router
