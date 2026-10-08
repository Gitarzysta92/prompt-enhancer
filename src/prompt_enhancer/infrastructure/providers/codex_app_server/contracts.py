"""Content-minimizing wire DTOs for one versioned App Server schema family.

These models intentionally omit message text, reasoning, commands, patches,
tool arguments, tool output, previews, and repository metadata. The explicit
provider thread name is retained only as a secret in memory for consented local
display. Pydantic drops unknown fields at validation, so omitted values cannot
escape this package through the parsed DTOs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import math
import re
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)

from .errors import CodexCompatibilityError, CodexLimitError
from .limits import CodexReadLimits


SOURCE_SCHEMA_VERSION = "codex-app-server-v2"
ADAPTER_VERSION = "0.3.0"
LABEL_EXTRACTOR_VERSION = "codex-display-labels-v1"
UNKNOWN_VERSION = "unknown"
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$")


class RawModel(BaseModel):
    """A frozen DTO that discards every field not explicitly allowlisted."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )


class RawLifecycleStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    BLOCKED = "blocked"
    ACTIVE = "active"
    IDLE = "idle"
    UNKNOWN = "unknown"


class RawItemKind(StrEnum):
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    MCP = "mcp"
    WEB_SEARCH = "web_search"
    IMAGE_VIEW = "image_view"
    PLAN = "plan"
    COMPACTION = "compaction"
    SUBAGENT = "subagent"
    OTHER = "other"
    UNKNOWN = "unknown"


def _status_from_wire(value: Any) -> RawLifecycleStatus:
    if isinstance(value, dict):
        value = value.get("type") or value.get("status")
    if not isinstance(value, str) or len(value) > 128:
        return RawLifecycleStatus.UNKNOWN
    compact = re.sub(r"[^a-z]", "", value.casefold())
    return {
        "completed": RawLifecycleStatus.COMPLETED,
        "complete": RawLifecycleStatus.COMPLETED,
        "succeeded": RawLifecycleStatus.COMPLETED,
        "success": RawLifecycleStatus.COMPLETED,
        "failed": RawLifecycleStatus.FAILED,
        "error": RawLifecycleStatus.FAILED,
        "systemerror": RawLifecycleStatus.FAILED,
        "interrupted": RawLifecycleStatus.INTERRUPTED,
        "cancelled": RawLifecycleStatus.INTERRUPTED,
        "canceled": RawLifecycleStatus.INTERRUPTED,
        "blocked": RawLifecycleStatus.BLOCKED,
        "active": RawLifecycleStatus.ACTIVE,
        "inprogress": RawLifecycleStatus.ACTIVE,
        "running": RawLifecycleStatus.ACTIVE,
        "idle": RawLifecycleStatus.IDLE,
        "notloaded": RawLifecycleStatus.IDLE,
    }.get(compact, RawLifecycleStatus.UNKNOWN)


def _item_kind_from_wire(value: Any) -> RawItemKind:
    if not isinstance(value, str) or len(value) > 128:
        return RawItemKind.UNKNOWN
    compact = re.sub(r"[^a-z]", "", value.casefold())
    return {
        "command": RawItemKind.COMMAND,
        "commandexecution": RawItemKind.COMMAND,
        "terminalcommand": RawItemKind.COMMAND,
        "filechange": RawItemKind.FILE_CHANGE,
        "filechanges": RawItemKind.FILE_CHANGE,
        "patch": RawItemKind.FILE_CHANGE,
        "mcptoolcall": RawItemKind.MCP,
        "mcp": RawItemKind.MCP,
        "websearch": RawItemKind.WEB_SEARCH,
        "imageview": RawItemKind.IMAGE_VIEW,
        "viewimage": RawItemKind.IMAGE_VIEW,
        "plan": RawItemKind.PLAN,
        "compaction": RawItemKind.COMPACTION,
        "contextcompaction": RawItemKind.COMPACTION,
        "subagent": RawItemKind.SUBAGENT,
        "collabagent": RawItemKind.SUBAGENT,
    }.get(compact, RawItemKind.OTHER)


class RawUsage(RawModel):
    input_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("inputTokens", "input_tokens"),
    )
    cached_input_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("cachedInputTokens", "cached_input_tokens"),
    )
    cache_creation_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("cacheCreationTokens", "cache_creation_tokens"),
    )
    output_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("outputTokens", "output_tokens"),
    )
    reasoning_output_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            "reasoningOutputTokens", "reasoning_output_tokens"
        ),
    )
    total_tokens: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("totalTokens", "total_tokens"),
    )


class RawItem(RawModel):
    item_id: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("id", "itemId", "item_id"),
    )
    kind: RawItemKind = Field(
        default=RawItemKind.UNKNOWN,
        validation_alias=AliasChoices("type", "kind"),
    )
    status: RawLifecycleStatus = RawLifecycleStatus.UNKNOWN
    started_at: int | float | datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("startedAt", "started_at"),
    )
    completed_at: int | float | datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("completedAt", "completed_at"),
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("durationMs", "duration_ms"),
    )
    success: bool | None = None

    _normalize_kind = field_validator("kind", mode="before")(_item_kind_from_wire)
    _normalize_status = field_validator("status", mode="before")(_status_from_wire)


class RawTurn(RawModel):
    turn_id: SecretStr = Field(validation_alias=AliasChoices("id", "turnId", "turn_id"))
    status: RawLifecycleStatus = RawLifecycleStatus.UNKNOWN
    started_at: int | float | datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("startedAt", "started_at"),
    )
    completed_at: int | float | datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("completedAt", "completed_at"),
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("durationMs", "duration_ms"),
    )
    usage: RawUsage | None = None
    items: tuple[RawItem, ...] = ()

    _normalize_status = field_validator("status", mode="before")(_status_from_wire)

    @field_validator("items", mode="before")
    @classmethod
    def none_items_are_empty(cls, value: Any) -> Any:
        return () if value is None else value


class RawThread(RawModel):
    thread_id: SecretStr = Field(
        validation_alias=AliasChoices("id", "threadId", "thread_id")
    )
    cwd: SecretStr | None = None
    name: SecretStr | None = None
    created_at: int | float | datetime = Field(
        validation_alias=AliasChoices("createdAt", "created_at")
    )
    updated_at: int | float | datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("updatedAt", "updated_at"),
    )
    status: RawLifecycleStatus = RawLifecycleStatus.UNKNOWN
    usage: RawUsage | None = None
    turns: tuple[RawTurn, ...] = ()

    _normalize_status = field_validator("status", mode="before")(_status_from_wire)

    @field_validator("turns", mode="before")
    @classmethod
    def none_turns_are_empty(cls, value: Any) -> Any:
        return () if value is None else value


class RawThreadPage(RawModel):
    threads: tuple[RawThread, ...] = Field(
        validation_alias=AliasChoices("data", "threads")
    )
    next_cursor: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("nextCursor", "next_cursor"),
    )


class RawThreadRead(RawModel):
    thread: RawThread
class RawThreadLabelSummary(RawModel):
    """Minimal summary-only projection used by explicit label enrichment."""

    thread_id: SecretStr = Field(
        validation_alias=AliasChoices("id", "threadId", "thread_id")
    )
    cwd: SecretStr | None = None
    name: SecretStr | None = None

    @field_validator("thread_id", "cwd", "name", mode="before")
    @classmethod
    def require_bounded_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not value or len(value) > 4_096:
            raise ValueError("provider summary metadata is invalid")
        return value



def parse_provider_version(result: object) -> str:
    """Extract only a safe version token; arbitrary server strings are discarded."""

    candidates: list[object] = []
    if isinstance(result, dict):
        server_info = result.get("serverInfo")
        if isinstance(server_info, dict):
            candidates.append(server_info.get("version"))
        candidates.extend((result.get("version"), result.get("serverVersion")))
    for candidate in candidates:
        if isinstance(candidate, str) and _SAFE_VERSION.fullmatch(candidate):
            return candidate
    return UNKNOWN_VERSION


def parse_thread_page(result: object, limits: CodexReadLimits) -> RawThreadPage:
    if not isinstance(result, dict):
        raise CodexCompatibilityError("provider list response has an unsupported shape")
    candidate = result.get("data", result.get("threads"))
    if not isinstance(candidate, list):
        raise CodexCompatibilityError("provider list response has an unsupported shape")
    if len(candidate) > limits.max_page_size:
        raise CodexLimitError("provider list response exceeded the page bound")
    try:
        return RawThreadPage.model_validate(result)
    except Exception:
        raise CodexCompatibilityError(
            "provider list response does not match the supported schema"
        ) from None


def parse_thread_read(result: object, limits: CodexReadLimits) -> RawThreadRead:
    if not isinstance(result, dict):
        raise CodexCompatibilityError("provider read response has an unsupported shape")
    payload = result if "thread" in result else {"thread": result}
    thread = payload.get("thread")
    if not isinstance(thread, dict):
        raise CodexCompatibilityError("provider read response has an unsupported shape")
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise CodexCompatibilityError("provider turns have an unsupported shape")
    if len(turns) > limits.max_turns_per_session:
        raise CodexLimitError("provider read response exceeded the turn bound")
    for turn in turns:
        if not isinstance(turn, dict):
            raise CodexCompatibilityError("provider turn has an unsupported shape")
        items = turn.get("items")
        if not isinstance(items, list):
            raise CodexCompatibilityError("provider turn items have an unsupported shape")
        if len(items) > limits.max_items_per_turn:
            raise CodexLimitError("provider read response exceeded the item bound")
    try:
        return RawThreadRead.model_validate(payload)
    except Exception:
        raise CodexCompatibilityError(
            "provider read response does not match the supported schema"
        ) from None

def parse_thread_label_summary(result: object) -> RawThreadLabelSummary:
    """Parse a no-turn task summary and fail closed if content is returned."""

    if not isinstance(result, dict) or set(result) != {"thread"}:
        raise CodexCompatibilityError(
            "provider summary response has an unsupported shape"
        )
    thread = result.get("thread")
    if not isinstance(thread, dict):
        raise CodexCompatibilityError(
            "provider summary response has an unsupported shape"
        )
    turns = thread.get("turns")
    if turns not in (None, []):
        raise CodexCompatibilityError(
            "provider summary response unexpectedly included turns"
        )
    try:
        return RawThreadLabelSummary.model_validate(thread)
    except Exception:
        raise CodexCompatibilityError(
            "provider summary response does not match the supported schema"
        ) from None


def as_utc(value: int | float | datetime | None) -> datetime | None:
    """Parse documented numeric timestamps without inventing a missing value."""

    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise CodexCompatibilityError("provider timestamp omitted its timezone")
        return value.astimezone(UTC)
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise CodexCompatibilityError("provider timestamp is invalid")
    numeric = float(value)
    if abs(numeric) > 100_000_000_000:
        numeric /= 1_000.0
    try:
        return datetime.fromtimestamp(numeric, tz=UTC)
    except (OverflowError, OSError, ValueError):
        raise CodexCompatibilityError("provider timestamp is outside the supported range") from None
