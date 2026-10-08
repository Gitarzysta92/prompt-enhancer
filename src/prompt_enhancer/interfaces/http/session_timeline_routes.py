"""Deterministic session timeline from already-indexed safe events.

Content-free by construction: kinds, tool categories, outcomes, durations,
timestamps and token counts - never text, paths or identifiers beyond the
session's own pseudonym. Turns and tool spans are paired in order; test and
build tool ends with an exit status are the verification receipts (ADR 0012).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import Field

from ...domain import EventKind, PSEUDONYM_PATTERN, Provider, SafeEvent, StrictModel, ToolCategory


TIMELINE_CONTRACT_VERSION = "session-timeline.v1"
MAX_TIMELINE_EVENTS = 20_000
MAX_TIMELINE_ITEMS = 2_000


class TimelineTurn(StrictModel):
    index: int = Field(ge=0)
    started_at: datetime
    ended_at: datetime | None = None


class TimelineTool(StrictModel):
    started_at: datetime
    ended_at: datetime | None = None
    category: ToolCategory
    success: bool | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    verification: bool = False


class TimelineMarker(StrictModel):
    at: datetime
    kind: Literal["compaction", "subagent_start", "subagent_end", "approval", "permission_change", "session_end"]


class TimelineUsage(StrictModel):
    requests: int = Field(ge=0)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None


class TimelineCounts(StrictModel):
    events: int = Field(ge=0)
    turns: int = Field(ge=0)
    tools: int = Field(ge=0)
    verifications_passed: int = Field(ge=0)
    verifications_failed: int = Field(ge=0)
    verifications_unknown: int = Field(ge=0)
    tool_errors: int = Field(ge=0)


class SessionTimeline(StrictModel):
    contract_version: Literal[TIMELINE_CONTRACT_VERSION] = TIMELINE_CONTRACT_VERSION
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    provider: Provider
    project_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_display_name: str | None = None
    session_display_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    events_complete: bool
    truncated: bool = False
    turns: tuple[TimelineTurn, ...]
    tools: tuple[TimelineTool, ...]
    markers: tuple[TimelineMarker, ...]
    usage: TimelineUsage
    counts: TimelineCounts


_MARKER_KINDS: dict[EventKind, str] = {
    EventKind.COMPACTION: "compaction",
    EventKind.PLAN: "plan",
    EventKind.USER_FEEDBACK: "user_feedback",
    EventKind.SUBAGENT_START: "subagent_start",
    EventKind.SUBAGENT_END: "subagent_end",
    EventKind.APPROVAL: "approval",
    EventKind.PERMISSION_CHANGE: "permission_change",
    EventKind.SESSION_END: "session_end",
}


def build_timeline(session, events: tuple[SafeEvent, ...]) -> SessionTimeline:
    ordered = sorted(events, key=lambda item: (item.occurred_at, item.sequence))
    truncated = len(ordered) > MAX_TIMELINE_EVENTS
    ordered = ordered[:MAX_TIMELINE_EVENTS]

    turns: list[TimelineTurn] = []
    open_turn: TimelineTurn | None = None
    tools: list[TimelineTool] = []
    open_tools: dict[ToolCategory, list[int]] = {}
    markers: list[TimelineMarker] = []
    requests = 0
    input_tokens = output_tokens = cached = 0
    saw_input = saw_output = saw_cached = False
    passed = failed = unknown_outcome = errors = 0
    last_at: datetime | None = None

    for event in ordered:
        last_at = event.occurred_at
        kind = event.kind
        if kind is EventKind.TURN_START:
            if open_turn is not None:
                turns.append(open_turn)
            open_turn = TimelineTurn(index=len(turns), started_at=event.occurred_at)
        elif kind is EventKind.TURN_END:
            if open_turn is not None:
                turns.append(open_turn.model_copy(update={"ended_at": event.occurred_at}))
                open_turn = None
        elif kind is EventKind.TOOL_START:
            category = event.tool_category or ToolCategory.UNKNOWN
            tools.append(TimelineTool(started_at=event.occurred_at, category=category))
            open_tools.setdefault(category, []).append(len(tools) - 1)
        elif kind is EventKind.TOOL_END:
            category = event.tool_category or ToolCategory.UNKNOWN
            verification = category in {ToolCategory.TEST, ToolCategory.BUILD}
            stack = open_tools.get(category) or []
            if stack:
                index = stack.pop()
                tools[index] = tools[index].model_copy(
                    update={
                        "ended_at": event.occurred_at,
                        "success": event.success,
                        "duration_ms": event.duration_ms,
                        "verification": verification,
                    }
                )
            else:
                tools.append(
                    TimelineTool(
                        started_at=event.occurred_at,
                        ended_at=event.occurred_at,
                        category=category,
                        success=event.success,
                        duration_ms=event.duration_ms,
                        verification=verification,
                    )
                )
            if event.success is False:
                errors += 1
            if verification:
                if event.success is True:
                    passed += 1
                elif event.success is False:
                    failed += 1
                else:
                    unknown_outcome += 1
        elif kind is EventKind.VERIFICATION:
            tools.append(
                TimelineTool(
                    started_at=event.occurred_at,
                    ended_at=event.occurred_at,
                    category=event.tool_category or ToolCategory.OTHER,
                    success=event.success,
                    duration_ms=event.duration_ms,
                    verification=True,
                )
            )
            if event.success is True:
                passed += 1
            elif event.success is False:
                failed += 1
            else:
                unknown_outcome += 1
        elif kind is EventKind.USAGE and event.usage is not None:
            requests += 1
            usage = event.usage
            if usage.input_tokens is not None:
                input_tokens += usage.input_tokens
                saw_input = True
            if usage.output_tokens is not None:
                output_tokens += usage.output_tokens
                saw_output = True
            if usage.cached_input_tokens is not None:
                cached += usage.cached_input_tokens
                saw_cached = True
        elif kind in _MARKER_KINDS:
            markers.append(TimelineMarker(at=event.occurred_at, kind=_MARKER_KINDS[kind]))  # type: ignore[arg-type]
    if open_turn is not None:
        turns.append(open_turn)

    return SessionTimeline(
        session_id=session.session_id,
        provider=session.provider,
        project_id=session.project_id,
        project_display_name=session.project_display_name,
        session_display_name=session.session_display_name,
        started_at=session.started_at,
        ended_at=session.ended_at or last_at,
        events_complete=session.events_complete,
        truncated=truncated or len(turns) > MAX_TIMELINE_ITEMS or len(tools) > MAX_TIMELINE_ITEMS,
        turns=tuple(turns[:MAX_TIMELINE_ITEMS]),
        tools=tuple(tools[:MAX_TIMELINE_ITEMS]),
        markers=tuple(markers[:MAX_TIMELINE_ITEMS]),
        usage=TimelineUsage(
            requests=requests,
            input_tokens=input_tokens if saw_input else None,
            output_tokens=output_tokens if saw_output else None,
            cached_input_tokens=cached if saw_cached else None,
        ),
        counts=TimelineCounts(
            events=len(events),
            turns=len(turns),
            tools=len(tools),
            verifications_passed=passed,
            verifications_failed=failed,
            verifications_unknown=unknown_outcome,
            tool_errors=errors,
        ),
    )


def create_session_timeline_router(require_local_auth: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["session-timeline"], dependencies=[Depends(require_local_auth)])

    @router.get("/sessions/{session_id}/timeline", response_model=SessionTimeline)
    def session_timeline(
        request: Request,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionTimeline:
        database = request.app.state.database
        session = database.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return build_timeline(session, database.get_session_events(session_id))

    return router


__all__ = ("SessionTimeline", "build_timeline", "create_session_timeline_router", "TIMELINE_CONTRACT_VERSION")
