"""Pure mapping from minimized App Server DTOs to source-domain metadata."""

from __future__ import annotations

from datetime import datetime
import hashlib
import posixpath
import re

from pydantic import SecretStr

from ....display_labels import (
    PROJECT_DISPLAY_NAME_MAX_LENGTH,
    SESSION_DISPLAY_NAME_MAX_LENGTH,
    minimize_private_display_name,
)
from ....domain import (
    EventKind,
    EventTimeBasis,
    Provider,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionSnapshot,
    ToolCategory,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from .contracts import (
    ADAPTER_VERSION,
    SOURCE_SCHEMA_VERSION,
    RawItem,
    RawItemKind,
    RawLifecycleStatus,
    RawThread,
    RawThreadLabelSummary,
    RawTurn,
    RawUsage,
    as_utc,
)
from .errors import CodexCompatibilityError, CodexLimitError
from .limits import (
    CodexReadLimits,
    TURN_END_OFFSET,
    TURN_SEQUENCE_STRIDE,
    TURN_USAGE_OFFSET,
)

ThreadLabelMetadata = RawThread | RawThreadLabelSummary



_INSTALLATION_ID = SecretStr("codex-app-server-local")
_FINAL_TURN_STATUSES = frozenset(
    {
        RawLifecycleStatus.COMPLETED,
        RawLifecycleStatus.FAILED,
        RawLifecycleStatus.INTERRUPTED,
    }
)


def _lexical_cwd(value: str) -> str:
    """Normalize path syntax without filesystem access or symlink resolution."""

    portable = value.replace("\\", "/")
    normalized = posixpath.normpath(portable)
    drive_match = re.match(r"^([A-Za-z]):(/.*)?$", normalized)
    if drive_match:
        tail = drive_match.group(2) or "/"
        normalized = f"{drive_match.group(1).casefold()}:{tail}"
    return normalized


def _normalized_project_path(thread: ThreadLabelMetadata) -> str | None:
    if thread.cwd is None:
        return None
    cwd = thread.cwd.get_secret_value()
    if not cwd:
        return None
    normalized = _lexical_cwd(cwd)
    if normalized in ("", "."):
        return None
    if not (
        normalized.startswith("/")
        or re.match(r"^[a-z]:/", normalized) is not None
    ):
        return None
    return normalized


def _project_identity(thread: RawThread) -> SecretStr:
    normalized = _normalized_project_path(thread)
    if normalized is not None:
        return SecretStr(normalized)
    digest = hashlib.sha256(
        thread.thread_id.get_secret_value().encode("utf-8")
    ).hexdigest()
    return SecretStr(f"missing-cwd-{digest}")


def _project_display_name(thread: ThreadLabelMetadata) -> SecretStr | None:
    normalized = _normalized_project_path(thread)
    if normalized is None:
        return None
    trimmed = normalized.rstrip("/")
    if not trimmed or re.fullmatch(r"[a-z]:", trimmed) is not None:
        return None
    components = tuple(
        component for component in trimmed.split("/") if component
    )
    if (
        len(components) >= 2
        and components[-2].casefold() in {"home", "users"}
    ):
        return None
    minimized = minimize_private_display_name(
        posixpath.basename(trimmed),
        max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH,
    )
    return SecretStr(minimized) if minimized is not None else None


def _session_display_name(thread: ThreadLabelMetadata) -> SecretStr | None:
    if thread.name is None:
        return None
    minimized = minimize_private_display_name(
        thread.name.get_secret_value(),
        max_length=SESSION_DISPLAY_NAME_MAX_LENGTH,
    )
    return SecretStr(minimized) if minimized is not None else None


def _session_state(status: RawLifecycleStatus) -> SessionState:
    return {
        RawLifecycleStatus.COMPLETED: SessionState.COMPLETED,
        RawLifecycleStatus.FAILED: SessionState.FAILED,
        RawLifecycleStatus.INTERRUPTED: SessionState.INTERRUPTED,
        RawLifecycleStatus.BLOCKED: SessionState.BLOCKED,
    }.get(status, SessionState.UNKNOWN)


def _success(status: RawLifecycleStatus, explicit: bool | None) -> bool | None:
    if explicit is not None:
        return explicit
    if status is RawLifecycleStatus.COMPLETED:
        return True
    if status in (RawLifecycleStatus.FAILED, RawLifecycleStatus.INTERRUPTED):
        return False
    return None


def _duration_ms(
    explicit: int | None,
    started_at: datetime | None,
    completed_at: datetime | None,
) -> int | None:
    if explicit is not None:
        return explicit
    if started_at is None or completed_at is None:
        return None
    if completed_at < started_at:
        raise CodexCompatibilityError("provider event timestamps are inconsistent")
    return round((completed_at - started_at).total_seconds() * 1_000)


def _source_event_identity(*components: str) -> str:
    """Encode raw identity components injectively before local HMAC protection."""

    return "".join(f"{len(component)}:{component}" for component in components)


def _turn_is_final(turn: RawTurn) -> bool:
    return turn.status in _FINAL_TURN_STATUSES


def _usage_record(
    usage: RawUsage,
    *,
    counter_kind: UsageCounterKind,
    scope: UsageScope,
) -> UsageRecord:
    return UsageRecord(
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
        output_tokens=usage.output_tokens,
        reasoning_output_tokens=usage.reasoning_output_tokens,
        total_tokens=usage.total_tokens,
        model_id=None,
        provider_reported=True,
        counter_kind=counter_kind,
        scope=scope,
    )


def _item_semantics(item: RawItem) -> tuple[EventKind, ToolCategory | None]:
    return {
        RawItemKind.COMMAND: (EventKind.TOOL_END, ToolCategory.COMMAND),
        RawItemKind.FILE_CHANGE: (EventKind.TOOL_END, ToolCategory.FILE_WRITE),
        RawItemKind.MCP: (EventKind.TOOL_END, ToolCategory.MCP),
        RawItemKind.WEB_SEARCH: (EventKind.TOOL_END, ToolCategory.SEARCH),
        RawItemKind.IMAGE_VIEW: (EventKind.TOOL_END, ToolCategory.FILE_READ),
        RawItemKind.PLAN: (EventKind.PLAN, None),
        RawItemKind.COMPACTION: (EventKind.COMPACTION, None),
        RawItemKind.SUBAGENT: (EventKind.SUBAGENT_END, ToolCategory.SUBAGENT),
        RawItemKind.OTHER: (EventKind.UNKNOWN, None),
        RawItemKind.UNKNOWN: (EventKind.UNKNOWN, None),
    }[item.kind]


def _fallback_time(
    *,
    item: RawItem | None,
    turn: RawTurn,
    session_started_at: datetime,
) -> tuple[datetime, EventTimeBasis]:
    if item is not None:
        item_completed = as_utc(item.completed_at)
        if item_completed is not None:
            return item_completed, EventTimeBasis.PROVIDER_REPORTED
    turn_completed = as_utc(turn.completed_at)
    if turn_completed is not None:
        return turn_completed, EventTimeBasis.TURN_COMPLETED
    turn_started = as_utc(turn.started_at)
    if turn_started is not None:
        return turn_started, EventTimeBasis.TURN_STARTED
    return session_started_at, EventTimeBasis.SESSION_STARTED


class CodexThreadMapper:
    """Version-specific, content-free mapper for App Server v2 metadata."""

    def __init__(
        self,
        *,
        provider_version: str,
        limits: CodexReadLimits | None = None,
    ) -> None:
        self._provider_version = provider_version
        self._limits = limits or CodexReadLimits()

    def display_labels(
        self, thread: ThreadLabelMetadata
    ) -> tuple[SecretStr | None, SecretStr | None]:
        """Map labels only; never derive or change persistent identity."""

        return _project_display_name(thread), _session_display_name(thread)

    def session(self, thread: RawThread, *, events_complete: bool) -> SourceSession:
        started_at = as_utc(thread.created_at)
        if started_at is None:
            raise CodexCompatibilityError("provider session omitted its start time")
        source_activity_at = as_utc(thread.updated_at)
        terminal_state = _session_state(thread.status)
        ended_at = None
        # updatedAt records activity, not a documented end time. Preserve an
        # unknown cycle end until an exact provider observation exists.
        return SourceSession(
            provider=Provider.CODEX,
            source_installation_id=_INSTALLATION_ID,
            source_project_id=_project_identity(thread),
            source_session_id=thread.thread_id,
            source_project_display_name=_project_display_name(thread),
            source_session_display_name=_session_display_name(thread),
            provider_version=self._provider_version,
            adapter_version=ADAPTER_VERSION,
            source_schema_version=SOURCE_SCHEMA_VERSION,
            started_at=started_at,
            source_activity_at=source_activity_at,
            ended_at=ended_at,
            terminal_state=terminal_state,
            events_complete=events_complete,
        )

    def snapshot(self, thread: RawThread) -> SourceSessionSnapshot:
        # Codex threads are resumable, so finalized-turn evidence is useful but
        # the open-ended history is never claimed as complete.
        session = self.session(thread, events_complete=False)
        events = self._events(thread, session)
        return SourceSessionSnapshot(session=session, events=events)

    def _events(
        self,
        thread: RawThread,
        session: SourceSession,
    ) -> tuple[SourceEvent, ...]:
        source_session_id = thread.thread_id.get_secret_value()
        events: list[SourceEvent] = []

        def append(
            *,
            event_id: str,
            kind: EventKind,
            sequence: int,
            occurred_at: datetime,
            time_basis: EventTimeBasis,
            duration_ms: int | None = None,
            success: bool | None = None,
            tool_category: ToolCategory | None = None,
            usage: UsageRecord | None = None,
        ) -> None:
            if len(events) >= self._limits.max_events_per_session:
                raise CodexLimitError("provider read exceeded the event bound")
            events.append(
                SourceEvent(
                    source_event_id=SecretStr(event_id),
                    kind=kind,
                    sequence=sequence,
                    occurred_at=occurred_at,
                    time_basis=time_basis,
                    duration_ms=duration_ms,
                    success=success,
                    tool_category=tool_category,
                    usage=usage,
                )
            )

        append(
            event_id=_source_event_identity(source_session_id, "session", "start"),
            kind=EventKind.SESSION_START,
            sequence=0,
            occurred_at=session.started_at,
            time_basis=EventTimeBasis.PROVIDER_REPORTED,
        )
        for turn_index, turn in enumerate(thread.turns):
            turn_id = turn.turn_id.get_secret_value()
            if not _turn_is_final(turn):
                continue
            turn_sequence = 1 + (turn_index * TURN_SEQUENCE_STRIDE)

            turn_started = as_utc(turn.started_at)
            turn_completed = as_utc(turn.completed_at)
            if (
                turn_started is not None
                and turn_completed is not None
                and turn_completed < turn_started
            ):
                raise CodexCompatibilityError("provider turn timestamps are inconsistent")
            start_time = turn_started or session.started_at
            start_basis = (
                EventTimeBasis.PROVIDER_REPORTED
                if turn_started is not None
                else EventTimeBasis.SESSION_STARTED
            )
            append(
                event_id=_source_event_identity(
                    source_session_id, "turn", turn_id, "start"
                ),
                sequence=turn_sequence,
                kind=EventKind.TURN_START,
                occurred_at=start_time,
                time_basis=start_basis,
            )
            for item_index, item in enumerate(turn.items):
                occurred_at, basis = _fallback_time(
                    item=item,
                    turn=turn,
                    session_started_at=session.started_at,
                )
                item_started = as_utc(item.started_at)
                item_completed = as_utc(item.completed_at)
                kind, category = _item_semantics(item)
                if item.item_id is None:
                    raise CodexCompatibilityError(
                        "provider item omitted its stable identity"
                    )
                if item_index >= TURN_USAGE_OFFSET - 1:
                    raise CodexLimitError("provider turn exceeded sequence capacity")
                item_identifier = item.item_id.get_secret_value()
                append(
                    event_id=_source_event_identity(
                        source_session_id,
                        "turn",
                        turn_id,
                        "item",
                        item_identifier,
                    ),
                    kind=kind,
                    sequence=turn_sequence + 1 + item_index,
                    occurred_at=occurred_at,
                    time_basis=basis,
                    duration_ms=_duration_ms(
                        item.duration_ms, item_started, item_completed
                    ),
                    success=_success(item.status, item.success),
                    tool_category=category,
                )
            usage_time, usage_basis = _fallback_time(
                item=None,
                turn=turn,
                session_started_at=session.started_at,
            )
            if turn.usage is not None:
                append(
                    event_id=_source_event_identity(
                        source_session_id, "turn", turn_id, "usage"
                    ),
                    kind=EventKind.USAGE,
                    sequence=turn_sequence + TURN_USAGE_OFFSET,
                    occurred_at=usage_time,
                    time_basis=usage_basis,
                    usage=_usage_record(
                        turn.usage,
                        counter_kind=UsageCounterKind.DELTA,
                        scope=UsageScope.TURN,
                    ),
                )
            append(
                event_id=_source_event_identity(
                    source_session_id, "turn", turn_id, "end"
                ),
                kind=EventKind.TURN_END,
                sequence=turn_sequence + TURN_END_OFFSET,
                occurred_at=usage_time,
                time_basis=usage_basis,
                duration_ms=_duration_ms(
                    turn.duration_ms, turn_started, turn_completed
                ),
                success=_success(turn.status, None),
            )
        return tuple(events)
