"""First-run detection and one-consent onboarding for local sources."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from ...application.onboarding import (
    OnboardingAccept,
    OnboardingError,
    OnboardingResult,
    OnboardingService,
    OnboardingStatus,
)


def create_onboarding_router(
    require_local_auth: Callable[..., None],
    service: OnboardingService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/onboarding",
        tags=["onboarding"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("", response_model=OnboardingStatus)
    def status() -> OnboardingStatus:
        return service.status()

    @router.post("/accept", response_model=OnboardingResult)
    def accept(payload: OnboardingAccept) -> OnboardingResult:
        try:
            return service.accept(payload)
        except OnboardingError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": "onboarding request was not accepted"},
            ) from None

    @router.post("/refresh", response_model=OnboardingStatus)
    def refresh() -> OnboardingStatus:
        service.refresh()
        return service.status()

    return router


__all__ = ("create_onboarding_router",)
