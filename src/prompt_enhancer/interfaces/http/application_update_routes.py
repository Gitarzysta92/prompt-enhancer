"""Authenticated, browser-gesture-only application update advisory routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, field_validator

from ...application.updates import ApplicationUpdateStatus, ApplicationUpdateSurface
from ...application.updates.status import UpdateActionConflict
from ...domain import StrictModel


class ApplicationUpdateActionRequest(StrictModel):
    expected_revision: int = Field(ge=0, le=9_007_199_254_740_991)
    expected_instance_id: str = Field(pattern=r"^[0-9a-f]{32}$")

    @field_validator("expected_revision", mode="before")
    @classmethod
    def reject_boolean_revision(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected revision requires a JSON integer")
        return value


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


def create_application_update_router(
    require_local_auth: Callable[..., None],
    require_browser_interaction: Callable[..., None],
    service: ApplicationUpdateSurface,
) -> APIRouter:
    """Read status locally; permit advisory egress only after a UI gesture."""

    router = APIRouter(prefix="/v1/application-updates",
                       tags=["application-updates"])

    @router.get(
        "/status",
        response_model=ApplicationUpdateStatus,
        dependencies=[Depends(require_local_auth)],
    )
    def status(response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return service.status()

    def _action(
            action: str, request: ApplicationUpdateActionRequest
    ) -> ApplicationUpdateStatus:
        try:
            if action == "check":
                method = service.check
            elif action == "stage":
                method = service.stage
            elif action == "cancel":
                method = service.cancel
            elif action == "retry":
                method = service.retry
            elif action == "verify":
                method = service.verify
            else:  # Literal endpoint functions are the only callers.
                raise UpdateActionConflict("update_action_refused")
            return method(
                expected_revision=request.expected_revision,
                expected_instance_id=request.expected_instance_id,
            )
        except UpdateActionConflict as error:
            raise HTTPException(
                status_code=409,
                detail="update action refused",
                headers={
                    "Cache-Control": "no-store, private",
                    "Pragma": "no-cache"
                },
            ) from error

    @router.post("/check",
                 response_model=ApplicationUpdateStatus,
                 dependencies=[Depends(require_browser_interaction)])
    def check(request: ApplicationUpdateActionRequest,
              response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return _action("check", request)

    @router.post("/stage",
                 response_model=ApplicationUpdateStatus,
                 dependencies=[Depends(require_browser_interaction)])
    def stage(request: ApplicationUpdateActionRequest,
              response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return _action("stage", request)

    @router.post("/cancel",
                 response_model=ApplicationUpdateStatus,
                 dependencies=[Depends(require_browser_interaction)])
    def cancel(request: ApplicationUpdateActionRequest,
               response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return _action("cancel", request)

    @router.post("/retry",
                 response_model=ApplicationUpdateStatus,
                 dependencies=[Depends(require_browser_interaction)])
    def retry(request: ApplicationUpdateActionRequest,
              response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return _action("retry", request)

    @router.post("/verify",
                 response_model=ApplicationUpdateStatus,
                 dependencies=[Depends(require_browser_interaction)])
    def verify(request: ApplicationUpdateActionRequest,
               response: Response) -> ApplicationUpdateStatus:
        _private(response)
        return _action("verify", request)

    return router


__all__ = ("create_application_update_router", )
