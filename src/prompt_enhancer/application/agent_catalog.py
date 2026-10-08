"""Durable owner-authored Agent projects, chats, and bounded local history.

This bounded context is deliberately separate from imported provider analytics.
History is opt-in per chat. Durable events intentionally exclude approval
identifiers and event rows, raw tool arguments/results, and reusable workspace
authority. A content-free terminal execution receipt may retain only the
settled approval classification already reflected by the tool outcome. The
SQLite adapter is an append-only journal; application code deterministically
projects it back into the visible conversation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
import threading
import uuid

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .agent_attachment_contracts import (
    AgentMessageAttachment,
    MAX_AGENT_MESSAGE_ATTACHMENTS,
)
from .local_agent_receipts import (
    AgentMcpToolDescriptor,
    AgentMcpToolResultReceipt,
    AgentToolExecutionReceipt,
    AgentToolState,
    AgentTurnSummary,
    AgentWriteReceipt,
)


AGENT_CATALOG_CONTRACT_VERSION = "agent-catalog.v2"
AGENT_CATALOG_PAGE_CONTRACT_VERSION = "agent-catalog-page.v1"
AGENT_MESSAGE_SEARCH_CONTRACT_VERSION = "agent-message-search.v1"
AGENT_HISTORY_CONTRACT_VERSION = "agent-history.v1"
AGENT_SESSION_FORK_CONTRACT_VERSION = "agent-session-fork.v1"
AGENT_SESSION_LINEAGE_CONTRACT_VERSION = "agent-session-lineage.v1"
AGENT_PROJECT_ID_PATTERN = r"^[0-9a-f]{32}$"
AGENT_CATALOG_SESSION_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_AGENT_PROJECTS = 200
MAX_AGENT_CATALOG_SESSIONS = 2_000
MAX_AGENT_CATALOG_RESULTS = 200
MAX_AGENT_CATALOG_PAGE_SIZE = 100
MAX_AGENT_HISTORY_EVENTS = 4_000
MAX_AGENT_HISTORY_PAGE = 500
MAX_AGENT_HISTORY_EVENT_CHARS = 250_000
MAX_AGENT_MESSAGE_SEARCH_PAGE = 50
MAX_AGENT_MESSAGE_SEARCH_EXCERPT_CHARS = 240


class AgentCatalogError(ValueError):
    """Closed, content-free failure from the authored Agent catalog."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AgentHistoryState(StrEnum):
    """Truthful availability of conversation content for a catalog session."""

    MEMORY_ONLY = "memory_only"
    DURABLE_LOCAL = "durable_local"


class AgentRetentionPolicy(StrEnum):
    """Owner-selected local retention tier for one authored chat."""

    METADATA_ONLY = "metadata_only"
    LOCAL_HISTORY = "local_history"


class StoredAgentEvent(StrictModel):
    """Privacy-bounded event admitted to the durable append-only journal."""

    seq: int = Field(ge=1)
    at: datetime
    kind: Literal[
        "user",
        "assistant",
        "tool_call",
        "tool_result",
        "status",
        "error",
        "done",
    ]
    text: str | None = Field(default=None, max_length=120_000)
    attachments: tuple[AgentMessageAttachment, ...] = Field(
        default=(), max_length=MAX_AGENT_MESSAGE_ATTACHMENTS
    )
    reasoning: str | None = Field(default=None, max_length=120_000)
    stream_id: str | None = Field(default=None, pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    stream_status: Literal["complete", "stopped", "failed"] | None = None
    tool: str | None = Field(default=None, max_length=128)
    call_id: str | None = Field(default=None, max_length=256)
    ok: bool | None = None
    turn_id: str | None = Field(default=None, pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    turn_summary: AgentTurnSummary | None = None
    tool_state: AgentToolState | None = None
    write_receipt: AgentWriteReceipt | None = None
    execution_receipt: AgentToolExecutionReceipt | None = None
    mcp_tool: AgentMcpToolDescriptor | None = None
    mcp_result: AgentMcpToolResultReceipt | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> "StoredAgentEvent":
        if self.kind == "user" and not (self.text or self.attachments):
            raise ValueError("stored user events require text or attachments")
        if self.kind != "user" and self.attachments:
            raise ValueError("only stored user events may carry attachments")
        if len({item.attachment_id for item in self.attachments}) != len(self.attachments):
            raise ValueError("stored user attachment identities must be unique")
        if self.kind == "assistant":
            if not (self.text or self.reasoning):
                raise ValueError("stored assistant events require visible output")
            if (self.stream_id is None) is not (self.stream_status is None):
                raise ValueError("stored stream fields must be paired")
        elif self.reasoning is not None or self.stream_id is not None or self.stream_status is not None:
            raise ValueError("only stored assistant events may carry stream fields")
        if self.kind == "tool_call" and (self.tool is None or self.call_id is None):
            raise ValueError("stored tool calls require bounded identity")
        if self.kind == "tool_result":
            if self.tool is None or self.call_id is None or self.ok is None or self.tool_state is None:
                raise ValueError("stored tool results require a terminal receipt")
            if self.ok is not (self.tool_state == "succeeded"):
                raise ValueError("stored tool result state is inconsistent")
        elif (
            self.tool_state is not None
            or self.write_receipt is not None
            or self.execution_receipt is not None
            or self.mcp_tool is not None
            or self.mcp_result is not None
            or self.ok is not None
        ):
            raise ValueError("only stored tool results may carry tool receipts")
        if self.mcp_tool is not None and (
            self.kind != "tool_result"
            or self.tool != self.mcp_tool.model_alias
            or self.call_id is None
        ):
            raise ValueError("stored managed MCP identity is inconsistent")
        if self.mcp_result is not None and self.mcp_tool is None:
            raise ValueError("stored managed MCP result requires its tool identity")
        if self.write_receipt is not None and (
            self.kind != "tool_result"
            or self.tool != "write_file"
            or self.tool_state
            != ("succeeded" if self.write_receipt.state == "verified" else "unverified")
        ):
            raise ValueError("stored write receipt is inconsistent")
        if self.kind == "done":
            if self.turn_summary is None or self.turn_id != self.turn_summary.turn_id:
                raise ValueError("stored done events require their settled turn receipt")
        elif self.turn_summary is not None:
            raise ValueError("only stored done events may carry a turn receipt")
        if self.kind in {"status", "error"} and not self.text:
            raise ValueError("stored status events require text")
        return self


class AgentHistorySnapshot(StrictModel):
    """Internal deterministic projection source for one exact project/chat."""

    contract_version: Literal["agent-history.v1"] = AGENT_HISTORY_CONTRACT_VERSION
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    history_revision: int = Field(ge=0)
    first_seq: int = Field(ge=0)
    last_seq: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    interrupted: bool = False
    profile_json: str | None = Field(default=None, max_length=16_000)
    events: tuple[StoredAgentEvent, ...]


class ResumeAgentSession(StrictModel):
    """Revision-bound recovery request; authority is never restored by it."""

    expected_catalog_revision: int = Field(ge=1)
    expected_history_revision: int = Field(ge=0)


class ForkAgentSession(StrictModel):
    """Idempotent, revision-bound request to branch retained local history."""

    request_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    expected_catalog_revision: int = Field(ge=1)
    expected_history_revision: int = Field(ge=0)
    destination_project_id: str | None = Field(
        default=None,
        pattern=AGENT_PROJECT_ID_PATTERN,
    )
    through_event_seq: int | None = Field(default=None, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value)


class AgentHistoryExport(StrictModel):
    """Explicit local export; returned only from the owner-invoked endpoint."""

    contract_version: Literal["agent-history.v1"] = AGENT_HISTORY_CONTRACT_VERSION
    exported_at: datetime
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    workspace: str = Field(min_length=1, max_length=1024)
    model_alias: str | None = Field(default=None, max_length=64)
    history_revision: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    interrupted: bool = False
    events: tuple[StoredAgentEvent, ...]


def _trimmed(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("value must contain visible text")
    return normalized


class CreateAgentProject(StrictModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _trimmed(value)


class UpdateAgentProject(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateAgentProject":
        if self.name is None and self.pinned is None and self.archived is None:
            raise ValueError("at least one project field must change")
        return self


class UpdateAgentCatalogSession(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = Field(default=None, pattern=AGENT_PROJECT_ID_PATTERN)
    model_alias: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return None if value is None else _trimmed(value)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateAgentCatalogSession":
        if (
            self.title is None
            and self.project_id is None
            and self.model_alias is None
            and self.pinned is None
            and self.archived is None
        ):
            raise ValueError("at least one session field must change")
        return self


class AgentProjectRecord(StrictModel):
    contract_version: Literal["agent-catalog.v2"] = AGENT_CATALOG_CONTRACT_VERSION
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(ge=1)
    pinned: bool = False
    archived_at: datetime | None = None
    session_count: int = Field(default=0, ge=0)
    is_default: bool = False


class AgentSessionLineage(StrictModel):
    """Persistent, content-free provenance for one branched Agent chat."""

    contract_version: Literal["agent-session-lineage.v1"] = (
        AGENT_SESSION_LINEAGE_CONTRACT_VERSION
    )
    source_project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    source_session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    source_catalog_revision: int = Field(ge=1)
    source_history_revision: int = Field(ge=0)
    branch_event_seq: int = Field(ge=0)
    copied_event_count: int = Field(ge=0, le=MAX_AGENT_HISTORY_EVENTS)
    copied_turn_count: int = Field(ge=0)
    copied_attachment_count: int = Field(ge=0)
    created_at: datetime

    @model_validator(mode="after")
    def validate_counts(self) -> "AgentSessionLineage":
        if (
            self.copied_event_count != self.branch_event_seq
            or self.branch_event_seq > self.source_history_revision
            or self.copied_turn_count > self.copied_event_count
        ):
            raise ValueError("fork lineage counts are incoherent")
        return self


class AgentCatalogSessionRecord(StrictModel):
    contract_version: Literal["agent-catalog.v2"] = AGENT_CATALOG_CONTRACT_VERSION
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    workspace: str = Field(min_length=1, max_length=1024)
    model_alias: str | None = Field(default=None, max_length=64)
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime
    revision: int = Field(ge=1)
    pinned: bool = False
    archived_at: datetime | None = None
    history_state: AgentHistoryState
    retention_policy: AgentRetentionPolicy = AgentRetentionPolicy.METADATA_ONLY
    history_revision: int = Field(default=0, ge=0)
    last_event_seq: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    conversation_available: bool = False
    lineage: AgentSessionLineage | None

    @model_validator(mode="after")
    def validate_lineage(self) -> "AgentCatalogSessionRecord":
        if self.lineage is None:
            return self
        if (
            self.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY
            or self.history_state is not AgentHistoryState.DURABLE_LOCAL
            or self.lineage.source_session_id == self.session_id
            or self.lineage.copied_event_count != self.history_revision
            or self.lineage.branch_event_seq != self.last_event_seq
            or self.lineage.copied_turn_count != self.turn_count
            or self.lineage.created_at != self.created_at
        ):
            raise ValueError("fork session lineage is incoherent")
        return self


class AgentSessionForkReceipt(StrictModel):
    """Exact result of a retained-history fork; authority is always absent."""

    contract_version: Literal["agent-session-fork.v1"] = (
        AGENT_SESSION_FORK_CONTRACT_VERSION
    )
    request_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    idempotent_replay: bool = False
    session: AgentCatalogSessionRecord
    source_tail_omitted: bool
    approvals_copied: Literal[False] = False
    mutation_authority_copied: Literal[False] = False
    pending_tool_state_copied: Literal[False] = False
    staged_attachments_copied: Literal[False] = False
    artifacts_copied: Literal[False] = False

    @model_validator(mode="after")
    def require_lineage(self) -> "AgentSessionForkReceipt":
        lineage = self.session.lineage
        if lineage is None:
            raise ValueError("fork receipt requires persistent lineage")
        return self


class AgentProjectList(StrictModel):
    contract_version: Literal["agent-catalog.v2"] = AGENT_CATALOG_CONTRACT_VERSION
    projects: tuple[AgentProjectRecord, ...]


class AgentCatalogSessionList(StrictModel):
    contract_version: Literal["agent-catalog.v2"] = AGENT_CATALOG_CONTRACT_VERSION
    sessions: tuple[AgentCatalogSessionRecord, ...]


def _validate_page_shape(
    *,
    limit: int,
    offset: int,
    total: int,
    next_offset: int | None,
    complete: bool,
    item_count: int,
) -> None:
    if offset > total:
        raise ValueError("page offset exceeds total")
    expected_count = min(limit, total - offset)
    if item_count != expected_count:
        raise ValueError("page does not contain the exact requested slice")
    expected_next = offset + item_count if offset + item_count < total else None
    if next_offset != expected_next or complete != (expected_next is None):
        raise ValueError("page continuation metadata is incoherent")


class AgentProjectPage(StrictModel):
    contract_version: Literal["agent-catalog-page.v1"] = (
        AGENT_CATALOG_PAGE_CONTRACT_VERSION
    )
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    limit: int = Field(strict=True, ge=1, le=MAX_AGENT_CATALOG_PAGE_SIZE)
    offset: int = Field(strict=True, ge=0, le=MAX_AGENT_PROJECTS)
    total: int = Field(strict=True, ge=0, le=MAX_AGENT_PROJECTS)
    next_offset: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_PROJECTS)
    complete: bool
    projects: tuple[AgentProjectRecord, ...] = Field(
        max_length=MAX_AGENT_CATALOG_PAGE_SIZE
    )

    @model_validator(mode="after")
    def coherent_page(self) -> "AgentProjectPage":
        _validate_page_shape(
            limit=self.limit,
            offset=self.offset,
            total=self.total,
            next_offset=self.next_offset,
            complete=self.complete,
            item_count=len(self.projects),
        )
        if len({project.project_id for project in self.projects}) != len(self.projects):
            raise ValueError("project page contains duplicate identifiers")
        return self


class AgentCatalogSessionPage(StrictModel):
    contract_version: Literal["agent-catalog-page.v1"] = (
        AGENT_CATALOG_PAGE_CONTRACT_VERSION
    )
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    limit: int = Field(strict=True, ge=1, le=MAX_AGENT_CATALOG_PAGE_SIZE)
    offset: int = Field(strict=True, ge=0, le=MAX_AGENT_CATALOG_SESSIONS)
    total: int = Field(strict=True, ge=0, le=MAX_AGENT_CATALOG_SESSIONS)
    next_offset: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=MAX_AGENT_CATALOG_SESSIONS,
    )
    complete: bool
    sessions: tuple[AgentCatalogSessionRecord, ...] = Field(
        max_length=MAX_AGENT_CATALOG_PAGE_SIZE
    )

    @model_validator(mode="after")
    def coherent_page(self) -> "AgentCatalogSessionPage":
        _validate_page_shape(
            limit=self.limit,
            offset=self.offset,
            total=self.total,
            next_offset=self.next_offset,
            complete=self.complete,
            item_count=len(self.sessions),
        )
        if len({session.session_id for session in self.sessions}) != len(self.sessions):
            raise ValueError("session page contains duplicate identifiers")
        return self


class AgentMessageSearchRequest(StrictModel):
    """Owner-requested local search of opted-in visible messages only.

    The request is never durable state: callers must not put its query in a
    URL, log, export, or snapshot. Search is a case-insensitive Unicode-token
    phrase; punctuation and quotes are literal input, not FTS grammar.
    """

    query: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, pattern=AGENT_PROJECT_ID_PATTERN)
    include_archived: bool = False
    limit: int = Field(default=20, strict=True, ge=1, le=MAX_AGENT_MESSAGE_SEARCH_PAGE)
    offset: int = Field(default=0, strict=True, ge=0, le=MAX_AGENT_CATALOG_SESSIONS)
    snapshot: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return _trimmed(value)

    @model_validator(mode="after")
    def require_snapshot_after_first_page(self) -> "AgentMessageSearchRequest":
        if self.offset > 0 and self.snapshot is None:
            raise ValueError("message search snapshot required")
        return self


class AgentMessageSearchHit(StrictModel):
    """First visible-message match per chat; the query is never echoed."""

    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    project_name: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    match_event_seq: int = Field(strict=True, ge=1)
    history_revision: int = Field(strict=True, ge=1)
    role: Literal["user", "assistant"]
    excerpt: str = Field(min_length=1, max_length=MAX_AGENT_MESSAGE_SEARCH_EXCERPT_CHARS)


class AgentMessageSearchPage(StrictModel):
    contract_version: Literal["agent-message-search.v1"] = AGENT_MESSAGE_SEARCH_CONTRACT_VERSION
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    limit: int = Field(strict=True, ge=1, le=MAX_AGENT_MESSAGE_SEARCH_PAGE)
    offset: int = Field(strict=True, ge=0, le=MAX_AGENT_CATALOG_SESSIONS)
    total: int = Field(strict=True, ge=0, le=MAX_AGENT_CATALOG_SESSIONS)
    next_offset: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_CATALOG_SESSIONS)
    complete: bool
    matches: tuple[AgentMessageSearchHit, ...] = Field(max_length=MAX_AGENT_MESSAGE_SEARCH_PAGE)

    @model_validator(mode="after")
    def coherent_page(self) -> "AgentMessageSearchPage":
        _validate_page_shape(limit=self.limit, offset=self.offset, total=self.total,
                             next_offset=self.next_offset, complete=self.complete,
                             item_count=len(self.matches))
        if len({hit.session_id for hit in self.matches}) != len(self.matches):
            raise ValueError("message search page contains duplicate chats")
        return self


class AgentCatalogRepository(Protocol):
    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        created_at: datetime,
        is_default: bool = False,
    ) -> AgentProjectRecord: ...

    def get_or_create_default_project(
        self,
        *,
        project_id: str,
        name: str,
        created_at: datetime,
    ) -> AgentProjectRecord: ...

    def get_project(self, project_id: str) -> AgentProjectRecord | None: ...

    def list_projects(
        self,
        *,
        search: str | None,
        include_archived: bool,
        limit: int,
    ) -> tuple[AgentProjectRecord, ...]: ...

    def page_projects(
        self,
        *,
        search: str | None,
        include_archived: bool,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[tuple[AgentProjectRecord, ...], int, str]: ...

    def update_project(
        self,
        project_id: str,
        command: UpdateAgentProject,
        changed_at: datetime,
    ) -> AgentProjectRecord: ...

    def delete_project(self, project_id: str, expected_revision: int) -> None: ...

    def create_session(
        self,
        *,
        session_id: str,
        project_id: str,
        title: str,
        workspace: str,
        model_alias: str | None,
        retention_policy: AgentRetentionPolicy,
        profile_json: str | None,
        created_at: datetime,
    ) -> AgentCatalogSessionRecord: ...

    def get_session(self, session_id: str) -> AgentCatalogSessionRecord | None: ...

    def fork_session(
        self,
        *,
        source_project_id: str,
        source_session_id: str,
        new_session_id: str,
        command: ForkAgentSession,
        created_at: datetime,
    ) -> AgentSessionForkReceipt: ...

    def list_sessions(
        self,
        *,
        project_id: str | None,
        search: str | None,
        include_archived: bool,
        limit: int,
    ) -> tuple[AgentCatalogSessionRecord, ...]: ...

    def page_sessions(
        self,
        *,
        project_id: str | None,
        search: str | None,
        include_archived: bool,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[tuple[AgentCatalogSessionRecord, ...], int, str]: ...

    def search_messages(
        self, *, request: AgentMessageSearchRequest
    ) -> tuple[tuple[AgentMessageSearchHit, ...], int, str]: ...

    def update_session(
        self,
        session_id: str,
        command: UpdateAgentCatalogSession,
        changed_at: datetime,
    ) -> AgentCatalogSessionRecord: ...

    def delete_session(
        self,
        session_id: str,
        expected_catalog_revision: int,
        expected_history_revision: int,
        changed_at: datetime,
    ) -> None: ...

    def append_history_event(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_history_revision: int,
        event: StoredAgentEvent,
    ) -> int: ...

    def read_history(
        self,
        *,
        project_id: str,
        session_id: str,
        after: int,
        limit: int,
    ) -> AgentHistorySnapshot: ...


class AgentCatalogService:
    """Application service for durable Agent navigation metadata."""

    def __init__(
        self,
        repository: AgentCatalogRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._default_lock = threading.Lock()

    def create_project(self, command: CreateAgentProject) -> AgentProjectRecord:
        return self._repository.create_project(
            project_id=self._new_id(),
            name=command.name,
            created_at=self._clock(),
        )

    def list_projects(
        self,
        *,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = MAX_AGENT_CATALOG_RESULTS,
    ) -> AgentProjectList:
        return AgentProjectList(
            projects=self._repository.list_projects(
                search=self._search(search),
                include_archived=include_archived,
                limit=min(MAX_AGENT_CATALOG_RESULTS, max(1, limit)),
            )
        )

    def page_projects(
        self,
        *,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = MAX_AGENT_CATALOG_PAGE_SIZE,
        offset: int = 0,
        snapshot: str | None = None,
    ) -> AgentProjectPage:
        if limit < 1 or limit > MAX_AGENT_CATALOG_PAGE_SIZE:
            raise AgentCatalogError("agent_catalog_page_invalid")
        if offset < 0 or offset > MAX_AGENT_PROJECTS:
            raise AgentCatalogError("agent_catalog_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentCatalogError("agent_catalog_page_snapshot_required")
        projects, total, current_snapshot = self._repository.page_projects(
            search=self._search(search),
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            snapshot=snapshot,
        )
        next_offset = offset + len(projects) if offset + len(projects) < total else None
        return AgentProjectPage(
            snapshot=current_snapshot,
            limit=limit,
            offset=offset,
            total=total,
            next_offset=next_offset,
            complete=next_offset is None,
            projects=projects,
        )

    def get_project(self, project_id: str) -> AgentProjectRecord:
        project = self._repository.get_project(project_id)
        if project is None:
            raise AgentCatalogError("agent_project_not_found")
        return project

    def update_project(
        self,
        project_id: str,
        command: UpdateAgentProject,
    ) -> AgentProjectRecord:
        return self._repository.update_project(project_id, command, self._clock())

    def delete_project(self, project_id: str, *, expected_revision: int) -> None:
        self._repository.delete_project(project_id, expected_revision)

    def resolve_project(self, project_id: str | None) -> AgentProjectRecord:
        if project_id is not None:
            project = self.get_project(project_id)
            if project.archived_at is not None:
                raise AgentCatalogError("agent_project_archived")
            return project
        with self._default_lock:
            return self._repository.get_or_create_default_project(
                project_id=self._new_id(),
                name="Personal workspace",
                created_at=self._clock(),
            )

    def register_live_session(
        self,
        *,
        session_id: str,
        project_id: str,
        title: str,
        workspace: Path,
        model_alias: str | None,
        created_at: datetime,
        retention_policy: AgentRetentionPolicy = AgentRetentionPolicy.METADATA_ONLY,
        profile_json: str | None = None,
    ) -> AgentCatalogSessionRecord:
        return self._repository.create_session(
            session_id=session_id,
            project_id=project_id,
            title=_trimmed(title),
            workspace=str(workspace),
            model_alias=model_alias,
            retention_policy=retention_policy,
            profile_json=profile_json,
            created_at=created_at,
        )

    def get_session(self, session_id: str) -> AgentCatalogSessionRecord:
        session = self._repository.get_session(session_id)
        if session is None:
            raise AgentCatalogError("agent_catalog_session_not_found")
        return session

    def fork_session(
        self,
        *,
        source_project_id: str,
        source_session_id: str,
        command: ForkAgentSession,
    ) -> AgentSessionForkReceipt:
        """Branch one exact retained journal without replaying live authority."""

        return self._repository.fork_session(
            source_project_id=source_project_id,
            source_session_id=source_session_id,
            new_session_id=self._new_id(),
            command=command,
            created_at=self._clock(),
        )

    def list_sessions(
        self,
        *,
        project_id: str | None = None,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = MAX_AGENT_CATALOG_RESULTS,
    ) -> AgentCatalogSessionList:
        if project_id is not None:
            self.get_project(project_id)
        return AgentCatalogSessionList(
            sessions=self._repository.list_sessions(
                project_id=project_id,
                search=self._search(search),
                include_archived=include_archived,
                limit=min(MAX_AGENT_CATALOG_RESULTS, max(1, limit)),
            )
        )

    def page_sessions(
        self,
        *,
        project_id: str | None = None,
        search: str | None = None,
        include_archived: bool = False,
        limit: int = MAX_AGENT_CATALOG_PAGE_SIZE,
        offset: int = 0,
        snapshot: str | None = None,
    ) -> AgentCatalogSessionPage:
        if project_id is not None:
            self.get_project(project_id)
        if limit < 1 or limit > MAX_AGENT_CATALOG_PAGE_SIZE:
            raise AgentCatalogError("agent_catalog_page_invalid")
        if offset < 0 or offset > MAX_AGENT_CATALOG_SESSIONS:
            raise AgentCatalogError("agent_catalog_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentCatalogError("agent_catalog_page_snapshot_required")
        sessions, total, current_snapshot = self._repository.page_sessions(
            project_id=project_id,
            search=self._search(search),
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            snapshot=snapshot,
        )
        next_offset = offset + len(sessions) if offset + len(sessions) < total else None
        return AgentCatalogSessionPage(
            snapshot=current_snapshot,
            limit=limit,
            offset=offset,
            total=total,
            next_offset=next_offset,
            complete=next_offset is None,
            sessions=sessions,
        )

    def search_messages(self, *, request: AgentMessageSearchRequest) -> AgentMessageSearchPage:
        if request.project_id is not None:
            self.get_project(request.project_id)
        matches, total, snapshot = self._repository.search_messages(request=request)
        next_offset = request.offset + len(matches)
        return AgentMessageSearchPage(
            snapshot=snapshot,
            limit=request.limit,
            offset=request.offset,
            total=total,
            next_offset=next_offset if next_offset < total else None,
            complete=next_offset >= total,
            matches=matches,
        )

    def update_session(
        self,
        session_id: str,
        command: UpdateAgentCatalogSession,
    ) -> AgentCatalogSessionRecord:
        if command.project_id is not None:
            destination = self.get_project(command.project_id)
            if destination.archived_at is not None:
                raise AgentCatalogError("agent_project_archived")
        return self._repository.update_session(session_id, command, self._clock())

    def delete_session(
        self,
        session_id: str,
        *,
        expected_catalog_revision: int,
        expected_history_revision: int,
    ) -> None:
        self._repository.delete_session(
            session_id,
            expected_catalog_revision,
            expected_history_revision,
            self._clock(),
        )

    def append_history_event(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_history_revision: int,
        event: StoredAgentEvent,
    ) -> int:
        return self._repository.append_history_event(
            project_id=project_id,
            session_id=session_id,
            expected_history_revision=expected_history_revision,
            event=event,
        )

    def read_history(
        self,
        *,
        project_id: str,
        session_id: str,
        after: int = 0,
        limit: int = MAX_AGENT_HISTORY_PAGE,
    ) -> AgentHistorySnapshot:
        self.get_project(project_id)
        return self._repository.read_history(
            project_id=project_id,
            session_id=session_id,
            after=max(0, after),
            limit=min(MAX_AGENT_HISTORY_PAGE, max(1, limit)),
        )

    def load_history(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> AgentHistorySnapshot:
        """Load the bounded full journal for deterministic local recovery."""

        self.get_project(project_id)
        return self._repository.read_history(
            project_id=project_id,
            session_id=session_id,
            after=0,
            limit=MAX_AGENT_HISTORY_EVENTS,
        )

    def export_history(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_catalog_revision: int | None = None,
        expected_history_revision: int | None = None,
    ) -> AgentHistoryExport:
        record = self.get_session(session_id)
        if record.project_id != project_id:
            raise AgentCatalogError("agent_catalog_session_not_found")
        if (
            expected_catalog_revision is not None
            and record.revision != expected_catalog_revision
        ):
            raise AgentCatalogError("agent_catalog_session_revision_conflict")
        snapshot = self._repository.read_history(
            project_id=project_id,
            session_id=session_id,
            after=0,
            limit=MAX_AGENT_HISTORY_EVENTS,
        )
        if (
            expected_history_revision is not None
            and snapshot.history_revision != expected_history_revision
        ):
            raise AgentCatalogError("agent_history_revision_conflict")
        return AgentHistoryExport(
            exported_at=self._clock(),
            project_id=project_id,
            session_id=session_id,
            title=record.title,
            workspace=record.workspace,
            model_alias=record.model_alias,
            history_revision=snapshot.history_revision,
            turn_count=snapshot.turn_count,
            interrupted=snapshot.interrupted,
            events=snapshot.events,
        )

    def _new_id(self) -> str:
        value = self._id_factory()
        if len(value) != 32 or any(character not in "0123456789abcdef" for character in value):
            raise AgentCatalogError("agent_catalog_id_invalid")
        return value

    @staticmethod
    def _search(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized[:120] or None


__all__ = (
    "AGENT_CATALOG_CONTRACT_VERSION",
    "AGENT_CATALOG_PAGE_CONTRACT_VERSION",
    "AGENT_MESSAGE_SEARCH_CONTRACT_VERSION",
    "AGENT_HISTORY_CONTRACT_VERSION",
    "AGENT_SESSION_FORK_CONTRACT_VERSION",
    "AGENT_SESSION_LINEAGE_CONTRACT_VERSION",
    "AGENT_CATALOG_SESSION_ID_PATTERN",
    "AGENT_PROJECT_ID_PATTERN",
    "AgentCatalogError",
    "AgentCatalogRepository",
    "AgentCatalogService",
    "AgentCatalogSessionList",
    "AgentCatalogSessionPage",
    "AgentMessageSearchRequest",
    "AgentMessageSearchHit",
    "AgentMessageSearchPage",
    "AgentCatalogSessionRecord",
    "AgentHistoryState",
    "AgentHistorySnapshot",
    "AgentHistoryExport",
    "AgentSessionForkReceipt",
    "AgentSessionLineage",
    "AgentRetentionPolicy",
    "StoredAgentEvent",
    "ResumeAgentSession",
    "ForkAgentSession",
    "AgentProjectList",
    "AgentProjectPage",
    "AgentProjectRecord",
    "CreateAgentProject",
    "UpdateAgentCatalogSession",
    "UpdateAgentProject",
)
