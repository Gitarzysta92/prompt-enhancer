"""Authenticated, read-only projection of synthetic Model Lab inventory."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, field_validator, model_validator

from ...application.estimators import (
    MAX_MODEL_LAB_PLANS,
    MODEL_LAB_INVENTORY_VERSION,
    EstimatorRepository,
    ModelLabInventory,
)
from .dto import HttpDto


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class ModelLabPlanSummaryDto(HttpDto):
    plan_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_key: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{0,127}$")
    plan_version: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$"
    )
    route: Literal["fast", "balanced", "deep"]
    metric_question_count: int = Field(ge=1, le=100)
    synthetic_execution_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    model_run_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    model_vote_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    metric_estimate_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    activation_outcome: Literal["synthetic_or_insufficient"]
    activation_allowed: Literal[False]

    @field_validator("plan_version")
    @classmethod
    def content_free_version(cls, value: str) -> str:
        if (
            value.startswith(("/", "\\"))
            or re.match(r"^[A-Za-z]:[/\\]", value) is not None
            or "\\" in value
            or "://" in value
            or ".." in value.split("/")
        ):
            raise ValueError("plan version cannot encode a path or URI")
        return value


class ModelLabInventoryDto(HttpDto):
    contract_version: Literal[MODEL_LAB_INVENTORY_VERSION]
    scope: Literal["synthetic_only"]
    session_data_read: Literal[False]
    private_evidence_returned: Literal[False]
    registered_plan_count: int = Field(ge=0, le=MAX_MODEL_LAB_PLANS)
    synthetic_execution_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    model_run_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    model_vote_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    metric_estimate_count: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    activation_outcome: Literal["synthetic_or_insufficient"]
    activation_allowed: Literal[False]
    plans: tuple[ModelLabPlanSummaryDto, ...] = Field(
        max_length=MAX_MODEL_LAB_PLANS
    )

    @model_validator(mode="after")
    def validate_canonical_totals(self) -> ModelLabInventoryDto:
        order = tuple(
            (plan.plan_key, plan.plan_version, plan.plan_fingerprint)
            for plan in self.plans
        )
        if order != tuple(sorted(order)) or len({item[2] for item in order}) != len(
            order
        ):
            raise ValueError("plans must be unique and canonically ordered")
        expected = (
            len(self.plans),
            sum(plan.synthetic_execution_count for plan in self.plans),
            sum(plan.model_run_count for plan in self.plans),
            sum(plan.model_vote_count for plan in self.plans),
            sum(plan.metric_estimate_count for plan in self.plans),
        )
        actual = (
            self.registered_plan_count,
            self.synthetic_execution_count,
            self.model_run_count,
            self.model_vote_count,
            self.metric_estimate_count,
        )
        if actual != expected:
            raise ValueError("aggregate counts must equal plan totals")
        return self


def _inventory_dto(inventory: ModelLabInventory) -> ModelLabInventoryDto:
    return ModelLabInventoryDto(
        contract_version=inventory.contract_version,
        scope=inventory.scope,
        session_data_read=False,
        private_evidence_returned=False,
        registered_plan_count=inventory.registered_plan_count,
        synthetic_execution_count=inventory.synthetic_execution_count,
        model_run_count=inventory.model_run_count,
        model_vote_count=inventory.model_vote_count,
        metric_estimate_count=inventory.metric_estimate_count,
        activation_outcome=inventory.activation_outcome.value,
        activation_allowed=False,
        plans=tuple(
            ModelLabPlanSummaryDto(
                plan_fingerprint=plan.plan_fingerprint,
                plan_key=plan.plan_key,
                plan_version=plan.plan_version,
                route=plan.route.value,
                metric_question_count=plan.metric_question_count,
                synthetic_execution_count=plan.synthetic_execution_count,
                model_run_count=plan.model_run_count,
                model_vote_count=plan.model_vote_count,
                metric_estimate_count=plan.metric_estimate_count,
                activation_outcome=plan.activation_outcome.value,
                activation_allowed=False,
            )
            for plan in inventory.plans
        ),
    )


def create_estimator_router(
    require_local_auth: Callable[..., None],
    repository: EstimatorRepository,
) -> APIRouter:
    def prevent_private_caching(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"

    router = APIRouter(
        prefix="/v1/estimators",
        tags=["estimators"],
        dependencies=[
            Depends(require_local_auth),
            Depends(prevent_private_caching),
        ],
    )

    @router.get("/plans", response_model=ModelLabInventoryDto)
    def list_estimator_plans() -> ModelLabInventoryDto:
        try:
            return _inventory_dto(repository.model_lab_inventory())
        except Exception:
            raise HTTPException(
                status_code=503,
                detail={"code": "model_lab_inventory_unavailable"},
                headers={
                    "Cache-Control": "no-store, private",
                    "Pragma": "no-cache",
                },
            ) from None

    return router
