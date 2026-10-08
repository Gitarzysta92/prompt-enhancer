"""Project timeline: sessions and reviewed task windows over calendar time.

Content-free by construction: pseudonymous ids, display labels the catalog
already exposes, timestamps, providers, counts. A task window is the span of
its member sessions (start of the earliest to end of the latest); it carries
the task type and lifecycle state of the current accepted revision, never a
guess about what the work was.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import Field

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel


PROJECT_TIMELINE_CONTRACT_VERSION = "project-timeline.v1"
MAX_TIMELINE_SESSIONS = 500
MAX_TIMELINE_TASKS = 500
MAX_ACTIVITY_DAYS = 400


class TimelineSession(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    provider: Provider
    display_name: str | None = Field(default=None, max_length=160)
    started_at: datetime
    ended_at: datetime | None = None
    terminal_state: str | None = None
    events_complete: bool


class TimelineTask(StrictModel):
    task_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    revision: int = Field(ge=1)
    task_type: str
    lifecycle_state: str
    session_ids: tuple[str, ...]
    display_name: str | None = Field(default=None, max_length=160)
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ActivityDay(StrictModel):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sessions: int = Field(ge=0)


class ProjectTimeline(StrictModel):
    contract_version: Literal[PROJECT_TIMELINE_CONTRACT_VERSION] = PROJECT_TIMELINE_CONTRACT_VERSION
    project_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_display_name: str | None = Field(default=None, max_length=120)
    providers: tuple[Provider, ...]
    first_started_at: datetime | None = None
    last_ended_at: datetime | None = None
    sessions: tuple[TimelineSession, ...]
    tasks: tuple[TimelineTask, ...]
    activity: tuple[ActivityDay, ...]
    sessions_drawn: int = Field(ge=0)
    truncated: bool = False


def _parse(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def build_project_timeline(database, project_id: str, *, session_limit: int = MAX_TIMELINE_SESSIONS) -> ProjectTimeline | None:
    bounded = max(1, min(int(session_limit), MAX_TIMELINE_SESSIONS))
    rows: list[dict[str, object]] = []
    offset = 0
    while len(rows) < bounded:
        want = min(500, bounded - len(rows))
        page = database.list_sessions(limit=want, offset=offset, project_id=project_id)
        rows.extend(page)
        offset += len(page)
        if len(page) < want:
            break
    truncated = len(rows) >= bounded and bool(
        database.list_sessions(limit=1, offset=offset, project_id=project_id)
    )
    if not rows:
        return None
    sessions: list[TimelineSession] = []
    by_id: dict[str, TimelineSession] = {}
    activity: dict[str, int] = {}
    project_name: str | None = None
    providers: set[Provider] = set()
    for row in rows:
        started = _parse(row.get("started_at"))
        if started is None:
            continue
        session = TimelineSession(
            session_id=str(row["session_id"]),
            provider=Provider(str(row["provider"])),
            display_name=(str(row["session_display_name"])[:160] if row.get("session_display_name") else None),
            started_at=started,
            ended_at=_parse(row.get("ended_at")),
            terminal_state=(str(row["terminal_state"]) if row.get("terminal_state") else None),
            events_complete=bool(row.get("events_complete")),
        )
        sessions.append(session)
        by_id[session.session_id] = session
        providers.add(session.provider)
        day = started.date().isoformat()
        activity[day] = activity.get(day, 0) + 1
        if project_name is None and row.get("project_display_name"):
            project_name = str(row["project_display_name"])[:120]
    sessions.sort(key=lambda item: item.started_at)

    tasks: list[TimelineTask] = []
    try:
        revisions = database.task_repository().list_current_revisions_for_project(project_id, limit=MAX_TIMELINE_TASKS)
    except Exception:
        revisions = ()
    for revision in revisions:
        members = [by_id[sid] for sid in revision.session_ids if sid in by_id]
        starts = [m.started_at for m in members]
        ends = [(m.ended_at or m.started_at) for m in members]
        first = min(members, key=lambda m: m.started_at) if members else None
        tasks.append(
            TimelineTask(
                task_id=revision.task_id,
                revision=revision.revision,
                task_type=revision.task_type,
                lifecycle_state=revision.lifecycle_state,
                session_ids=tuple(revision.session_ids),
                display_name=first.display_name if first else None,
                started_at=min(starts) if starts else None,
                ended_at=max(ends) if ends else None,
            )
        )
    tasks.sort(key=lambda item: (item.started_at is None, item.started_at or datetime.max.replace(tzinfo=sessions[0].started_at.tzinfo)))

    days = sorted(activity.items())[-MAX_ACTIVITY_DAYS:]
    return ProjectTimeline(
        project_id=project_id,
        project_display_name=project_name,
        providers=tuple(sorted(providers, key=lambda item: item.value)),
        first_started_at=sessions[0].started_at if sessions else None,
        last_ended_at=max(((s.ended_at or s.started_at) for s in sessions), default=None),
        sessions=tuple(sessions),
        tasks=tuple(tasks),
        activity=tuple(ActivityDay(day=day, sessions=count) for day, count in days),
        sessions_drawn=len(sessions),
        truncated=truncated,
    )


def create_project_timeline_router(require_local_auth: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["project-timeline"], dependencies=[Depends(require_local_auth)])

    @router.get("/projects/{project_id}/timeline", response_model=ProjectTimeline)
    def project_timeline(
        request: Request,
        project_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=MAX_TIMELINE_SESSIONS)] = MAX_TIMELINE_SESSIONS,
    ) -> ProjectTimeline:
        timeline = build_project_timeline(request.app.state.database, project_id, session_limit=limit)
        if timeline is None:
            raise HTTPException(status_code=404, detail="project not found")
        return timeline

    return router


__all__ = ("PROJECT_TIMELINE_CONTRACT_VERSION", "ProjectTimeline", "build_project_timeline", "create_project_timeline_router")
