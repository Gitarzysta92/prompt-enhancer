"""Authenticated, on-demand, content-free Agent hardening diagnostics."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Response

from ...application.agent_hardening import (
    AgentNativeAcceptanceStartReceipt,
    AgentHardeningService,
    AgentHardeningSnapshot,
    BeginAgentNativeAcceptance,
)


def create_agent_hardening_router(
    require_local_auth: Callable[..., None],
    require_user_confirmation: Callable[..., None],
    service: AgentHardeningService,
) -> APIRouter:
    # This intentionally stays outside /v1/agent: it is a diagnostic surface,
    # not a controller operation and therefore does not change the v4
    # orchestration manifest or grant controllers new authority.
    router = APIRouter(
        prefix="/v1/diagnostics",
        tags=["agent-diagnostics"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get("/agent-hardening", response_model=AgentHardeningSnapshot)
    def agent_hardening(response: Response) -> AgentHardeningSnapshot:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return service.snapshot()

    @router.post(
        "/agent-native-acceptance/start",
        response_model=AgentNativeAcceptanceStartReceipt,
        dependencies=[Depends(require_user_confirmation)],
    )
    def begin_agent_native_acceptance(
        _payload: BeginAgentNativeAcceptance,
        response: Response,
    ) -> AgentNativeAcceptanceStartReceipt:
        """Arm only the page-local guide after owned-native confirmation."""

        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        return AgentNativeAcceptanceStartReceipt()

    return router


__all__ = ("create_agent_hardening_router",)
