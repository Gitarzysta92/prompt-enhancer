"""Exact, in-memory context-preflight evidence bound to one Agent chat turn.

The receipt is intentionally not persisted. Recovered chats start unknown rather
than inheriting a token count that cannot be proven for their reconstructed
request body or currently served model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..domain import StrictModel
from .local_models import RuntimeContextStatus


AGENT_SESSION_CONTEXT_CONTRACT_VERSION = "agent-session-context.v1"

AgentSessionContextUnknownReason = Literal[
    "no_request_measured",
    "recovered_without_context_receipt",
    "turn_pending_preflight",
    "turn_ended_before_preflight",
    "turn_start_failed",
    "preflight_unavailable",
    "preflight_failed",
    "request_body_too_large",
    "model_changed",
]


class AgentSessionContextStatus(StrictModel):
    """One session-local context state with optional exact turn binding."""

    contract_version: Literal["agent-session-context.v1"] = (
        AGENT_SESSION_CONTEXT_CONTRACT_VERSION
    )
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    revision: int = Field(default=0, strict=True, ge=0)
    binding_state: Literal["unmeasured", "bound"] = "unmeasured"
    source: Literal["runtime_chat_template_preflight"] = (
        "runtime_chat_template_preflight"
    )
    unknown_reason: AgentSessionContextUnknownReason | None = "no_request_measured"
    turn_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    turn_number: int | None = Field(default=None, strict=True, ge=1)
    model_alias: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    observed_at: datetime | None = None
    context: RuntimeContextStatus | None = None

    @model_validator(mode="after")
    def coherent_binding(self) -> "AgentSessionContextStatus":
        turn_fields = (self.turn_id, self.turn_number, self.model_alias)
        if self.binding_state == "bound":
            if (
                self.unknown_reason is not None
                or any(value is None for value in turn_fields)
                or self.observed_at is None
                or self.context is None
            ):
                raise ValueError("bound session context requires complete turn evidence")
            return self
        if (
            self.unknown_reason is None
            or self.observed_at is not None
            or self.context is not None
            or (any(value is None for value in turn_fields) and any(
                value is not None for value in turn_fields
            ))
        ):
            raise ValueError("unmeasured session context is incoherent")
        return self


def unmeasured_session_context(
    session_id: str,
    *,
    reason: AgentSessionContextUnknownReason,
    revision: int = 0,
    turn_id: str | None = None,
    turn_number: int | None = None,
    model_alias: str | None = None,
) -> AgentSessionContextStatus:
    """Build an explicit unknown receipt without inventing token evidence."""

    return AgentSessionContextStatus(
        session_id=session_id,
        revision=revision,
        binding_state="unmeasured",
        unknown_reason=reason,
        turn_id=turn_id,
        turn_number=turn_number,
        model_alias=model_alias,
    )


__all__ = (
    "AGENT_SESSION_CONTEXT_CONTRACT_VERSION",
    "AgentSessionContextStatus",
    "AgentSessionContextUnknownReason",
    "unmeasured_session_context",
)
