"""Local agent workspace (ADR 0016): a chosen local model works inside one folder with tools.

The model reaches files and commands only through the tools defined here, every
tool is scoped to the workspace folder the person chose, and the tools that
change anything - writing a file, running a command, fetching a URL - pause the
run until the person approves that exact call in the dashboard (writes show a
diff first). Reads never leave the workspace. Each chat explicitly chooses
metadata-only or bounded local-history retention. Durable history never restores
approvals or mutation authority; recovered chats start read-only and use only
their visible conversation as model context.
The model is the app's own loopback runtime (ADR 0013) and speaks OpenAI tool
calls through the runtime's chat template.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Any, Literal, Protocol
import uuid

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .agent_artifacts import (
    AgentArtifact,
    AgentArtifactCapturePreview,
    AgentArtifactContent,
    AgentArtifactDetail,
    AgentArtifactError,
    AgentArtifactExport,
    AgentArtifactList,
    AgentArtifactListView,
    AgentArtifactPage,
    AgentArtifactService,
    AgentDocumentPreview,
    CaptureAgentArtifact,
    ExportAgentArtifact,
    PreviewAgentArtifactCapture,
    RemoveAgentArtifact,
    UpdateAgentArtifact,
)
from .agent_catalog import (
    AGENT_PROJECT_ID_PATTERN,
    AgentCatalogError,
    AgentCatalogSessionRecord,
    AgentCatalogService,
    AgentHistoryExport,
    AgentHistorySnapshot,
    AgentRetentionPolicy,
    ResumeAgentSession,
    StoredAgentEvent,
    UpdateAgentCatalogSession,
)
from .agent_attachment_contracts import (
    AgentAttachment,
    AgentAttachmentDocumentPreview,
    AgentAttachmentList,
    AgentMessageAttachment,
    MAX_AGENT_ATTACHMENT_MESSAGE_BYTES,
    MAX_AGENT_MESSAGE_ATTACHMENTS,
    StageAgentAttachment,
)
from .agent_attachments import (
    AgentAttachmentContent,
    AgentAttachmentError,
    AgentAttachmentService,
    PreparedAgentAttachments,
)
from .agent_hardening import AgentLiveHardeningFacts
from .agent_session_context import (
    AgentSessionContextStatus,
    AgentSessionContextUnknownReason,
    unmeasured_session_context,
)
from .local_agent_changes import (
    AgentChangeDiff,
    AgentChangeRestoreApplyCommand,
    AgentChangeRestoreApplyResult,
    AgentChangeRestorePreview,
    AgentChangeRestorePreviewCommand,
    AgentChangeSet,
    AgentChangeTracker,
)
from .local_agent_discovery import LocalAgentWorkspaceDiscovery, WorkspaceDiscovery
from .local_agent_editor import (
    LocalAgentWorkspaceEditor,
    WORKSPACE_APPLY_CONFIRMATION,
    WorkspaceApplyCommand,
    WorkspaceApplyResult,
    WorkspaceEditPreview,
    WorkspaceFile,
    WorkspaceLineEnding,
    WorkspacePreviewCommand,
    WorkspaceSearchResult,
    WorkspaceTree,
)
from .local_agent_file_lifecycle import (
    LocalAgentWorkspaceFileLifecycle,
    WORKSPACE_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
    WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
    WORKSPACE_FILE_TRASH_CONFIRMATION,
    WORKSPACE_MOVE_CONFIRMATION,
    WorkspaceCreateApplyCommand,
    WorkspaceCreateApplyResult,
    WorkspaceCreatePreview,
    WorkspaceCreatePreviewCommand,
    WorkspaceDirectoryCreateApplyCommand,
    WorkspaceDirectoryCreateApplyResult,
    WorkspaceDirectoryCreatePreview,
    WorkspaceDirectoryCreatePreviewCommand,
    WorkspaceDirectoryMoveApplyCommand,
    WorkspaceDirectoryMoveApplyResult,
    WorkspaceDirectoryMovePreview,
    WorkspaceDirectoryMovePreviewCommand,
    WorkspaceFileTrashApplyCommand,
    WorkspaceFileTrashApplyResult,
    WorkspaceFileTrashPreview,
    WorkspaceFileTrashPreviewCommand,
    WorkspaceMoveApplyCommand,
    WorkspaceMoveApplyResult,
    WorkspaceMovePreview,
    WorkspaceMovePreviewCommand,
)
from .local_agent_limits import (
    AGENT_CONTRACT_VERSION,
    APPROVAL_WAIT_SECONDS,
    DEFAULT_COMMAND_SECONDS,
    ID_PATTERN as _ID_PATTERN,
    LocalAgentError,
    MAX_AGENT_STREAM_BYTES,
    MAX_ASSISTANT_TEXT_CHARS,
    MAX_CALL_ID_CHARS,
    MAX_COMMAND_SECONDS,
    MAX_EVENTS,
    MAX_EVENT_PAGE,
    MAX_FILE_WRITE_BYTES,
    MAX_REVIEWABLE_COMMAND_CHARS,
    MAX_SESSIONS,
    MAX_STEPS_PER_TURN,
    MAX_STREAM_DELTA_EVENTS,
    MAX_TOOL_CALLS_PER_REPLY,
    MAX_TOOL_NAME_CHARS,
    MAX_TOOL_RESULT_CHARS,
    MAX_WORKSPACE_TRANSACTION_FILES,
    STREAM_EVENT_CHARS,
    STREAM_WAIT_SECONDS,
    WORKSPACE_INSPECTION_VERSION,
    WORKSPACE_WRITE_VERSION,
)
from .local_agent_transactions import (
    WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
    LocalAgentWorkspaceTransactionEditor,
    WorkspaceTransactionApplyChange,
    WorkspaceTransactionApplyCommand,
    WorkspaceTransactionApplyResult,
    WorkspaceTransactionChangeCommand,
    WorkspaceTransactionPreview,
    WorkspaceTransactionPreviewCommand,
)
from .local_agent_workspace import (
    PreparedWrite,
    ToolOutcome,
    WorkspaceTextSnapshot,
    WorkspaceTools,
    minimal_environment,
    run_with_tree_kill,
)
from .local_agent_receipts import (
    AgentMcpToolDescriptor,
    AgentMcpToolResultReceipt,
    AgentToolApprovalState,
    AgentToolEvidenceState,
    AgentToolExecutionReceipt,
    AgentToolState,
    AgentTurnSummary,
    AgentWriteReceipt,
    RuntimeUsage,
    ToolExecutionReceiptBuilder,
    TurnReceiptBuilder,
    runtime_usage,
)
from .mcp_managed_runtime import (
    MAX_MCP_MANAGED_ARGUMENT_BYTES,
    McpManagedRuntimeError,
    McpManagedRuntimeService,
)
from .model_reply import model_json_object
from .local_models import MAX_CHAT_BODY_BYTES, RuntimeCapabilities, RuntimeContextStatus
from .runtime_cancellation import RuntimeCooperativeStop, runtime_request_scope


class ToolName(StrEnum):
    READ_FILE = "read_file"
    LIST_DIR = "list_dir"
    SEARCH_TEXT = "search_text"
    WRITE_FILE = "write_file"
    CREATE_DIRECTORY = "create_directory"
    MOVE_DIRECTORY = "move_directory"
    MOVE_FILE = "move_file"
    TRASH_FILE = "trash_file"
    RUN_COMMAND = "run_command"
    FETCH_URL = "fetch_url"


def _tool_value(tool: ToolName | str) -> str:
    return tool.value if isinstance(tool, ToolName) else tool


class AgentStreamPhase(StrEnum):
    CONTENT = "content"
    REASONING = "reasoning"


class AgentStreamStatus(StrEnum):
    COMPLETE = "complete"
    STOPPED = "stopped"
    FAILED = "failed"


SAFE_TOOLS = frozenset({ToolName.READ_FILE, ToolName.LIST_DIR, ToolName.SEARCH_TEXT})
APPROVAL_TOOLS = frozenset(
    {
        ToolName.WRITE_FILE,
        ToolName.CREATE_DIRECTORY,
        ToolName.MOVE_DIRECTORY,
        ToolName.MOVE_FILE,
        ToolName.TRASH_FILE,
        ToolName.RUN_COMMAND,
        ToolName.FETCH_URL,
    }
)


class AgentModelParameters(StrictModel):
    """Sampling and budget knobs for the chosen model - one preset per session."""

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, gt=0.0, le=1.0)
    max_tokens: int = Field(default=1_400, ge=64, le=8_192)
    #: Reasoning/thinking mode where the model's chat template supports it.
    enable_thinking: bool = False


class AgentSettings(StrictModel):
    workspace: str = Field(min_length=1, max_length=1024)
    project_id: str | None = Field(default=None, pattern=AGENT_PROJECT_ID_PATTERN)
    model_alias: str | None = Field(default=None, max_length=64)
    parameters: AgentModelParameters = AgentModelParameters()
    #: Extra standing instructions folded into the system prompt for this session.
    instructions: str | None = Field(default=None, max_length=4_000)
    allow_writes: bool = True
    allow_commands: bool = True
    #: Web access is off unless the person turns it on; each fetch still needs approval.
    allow_web: bool = False
    max_steps: int = Field(default=10, ge=1, le=MAX_STEPS_PER_TURN)
    command_timeout_seconds: int = Field(default=DEFAULT_COMMAND_SECONDS, ge=5, le=MAX_COMMAND_SECONDS)
    title: str | None = Field(default=None, max_length=120)
    #: Privacy-preserving default for non-UI clients; the Agent UI asks explicitly.
    retention_policy: AgentRetentionPolicy = AgentRetentionPolicy.METADATA_ONLY


class AgentEvent(StrictModel):
    seq: int
    at: datetime
    kind: Literal["user", "assistant", "assistant_delta", "tool_call", "tool_result", "approval_required", "approval_resolved", "status", "error", "done"]
    text: str | None = Field(default=None, max_length=MAX_ASSISTANT_TEXT_CHARS)
    attachments: tuple[AgentMessageAttachment, ...] = Field(
        default=(), max_length=MAX_AGENT_MESSAGE_ATTACHMENTS
    )
    reasoning: str | None = Field(default=None, max_length=MAX_ASSISTANT_TEXT_CHARS)
    stream_id: str | None = None
    stream_phase: AgentStreamPhase | None = None
    stream_status: AgentStreamStatus | None = None
    tool: str | None = Field(default=None, max_length=MAX_TOOL_NAME_CHARS)
    arguments: dict[str, Any] | None = None
    call_id: str | None = Field(default=None, max_length=MAX_CALL_ID_CHARS)
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    ok: bool | None = None
    preview: str | None = Field(default=None, max_length=260_000)
    turn_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    turn_summary: AgentTurnSummary | None = None
    tool_state: AgentToolState | None = None
    write_receipt: AgentWriteReceipt | None = None
    execution_receipt: AgentToolExecutionReceipt | None = None
    mcp_tool: AgentMcpToolDescriptor | None = None
    mcp_result: AgentMcpToolResultReceipt | None = None

    @field_validator("stream_id")
    @classmethod
    def validate_stream_id(cls, value: str | None) -> str | None:
        if value is not None and _ID_PATTERN.fullmatch(value) is None:
            raise ValueError("agent stream id is invalid")
        return value

    @model_validator(mode="after")
    def validate_stream_fields(self) -> "AgentEvent":
        allowed_fields = {
            "user": {"text"},
            "assistant": {"text", "reasoning", "stream_id", "stream_status"},
            "assistant_delta": {"text", "stream_id", "stream_phase"},
            "tool_call": {"tool", "arguments", "call_id"},
            "tool_result": {
                "text",
                "tool",
                "call_id",
                "ok",
                "tool_state",
                "write_receipt",
                "execution_receipt",
                "mcp_tool",
                "mcp_result",
            },
            "approval_required": {
                "tool", "arguments", "call_id", "approval_id", "preview", "mcp_tool",
            },
            "approval_resolved": {
                "text", "tool", "call_id", "approval_id", "ok", "mcp_tool",
            },
            "status": {"text"},
            "error": {"text"},
            "done": {"turn_summary"},
        }[self.kind]
        optional_fields = (
            "text", "reasoning", "stream_id", "stream_phase", "stream_status",
            "tool", "arguments", "call_id", "approval_id", "ok", "preview",
            "turn_summary", "tool_state", "write_receipt", "execution_receipt",
            "mcp_tool", "mcp_result",
        )
        if any(getattr(self, field) is not None and field not in allowed_fields for field in optional_fields):
            raise ValueError("event payload fields do not match its kind")
        if self.kind == "user":
            if not (self.text or self.attachments):
                raise ValueError("user events require text or attachments")
            if len({item.attachment_id for item in self.attachments}) != len(self.attachments):
                raise ValueError("user attachment identities must be unique")
        elif self.attachments:
            raise ValueError("only user events may carry attachments")
        if self.kind in {"status", "error"} and not self.text:
            raise ValueError("status and error events require text")
        if self.kind in {"tool_call", "tool_result"} and not (self.tool and self.call_id):
            raise ValueError("tool events require a tool and call identity")
        if self.kind == "tool_result" and self.ok is None:
            raise ValueError("tool results require an outcome")
        if self.kind == "approval_required" and not (
            self.tool and self.arguments is not None and self.approval_id
        ):
            raise ValueError("approval requests require tool details and identity")
        if self.kind == "approval_resolved" and not (
            self.tool and self.approval_id and self.ok is not None
        ):
            raise ValueError("approval resolutions require tool details and outcome")
        if self.turn_summary is not None and (self.kind != "done" or self.turn_id != self.turn_summary.turn_id):
            raise ValueError("turn receipt requires its own done event")
        if self.tool_state is not None and (self.kind != "tool_result" or self.ok is not (self.tool_state == "succeeded")):
            raise ValueError("tool outcome metadata does not match its result")
        if self.write_receipt is not None and (
            self.kind != "tool_result" or self.tool != ToolName.WRITE_FILE.value
            or self.tool_state != ("succeeded" if self.write_receipt.state == "verified" else "unverified")
        ):
            raise ValueError("write effect requires a matching tool receipt")
        if self.execution_receipt is not None and self.kind != "tool_result":
            raise ValueError("execution receipts belong only to tool results")
        if self.mcp_tool is not None and (
            self.kind not in {"approval_required", "approval_resolved", "tool_result"}
            or self.tool != self.mcp_tool.model_alias
            or self.call_id is None
        ):
            raise ValueError("managed MCP identity does not match its event")
        if self.mcp_result is not None and (
            self.kind != "tool_result" or self.mcp_tool is None
        ):
            raise ValueError("managed MCP results require their terminal tool event")
        if self.kind == "assistant_delta":
            if self.stream_id is None or self.stream_phase is None or not self.text:
                raise ValueError("assistant deltas require stream identity, phase, and text")
            if self.reasoning is not None or self.stream_status is not None or len(self.text) > STREAM_EVENT_CHARS:
                raise ValueError("assistant delta payload is invalid")
        elif self.kind == "assistant":
            if self.stream_phase is not None:
                raise ValueError("completed assistant events cannot carry a stream phase")
            if (self.stream_id is None) is not (self.stream_status is None):
                raise ValueError("streamed assistant events require identity and terminal status")
        elif self.stream_id is not None or self.stream_phase is not None or self.stream_status is not None or self.reasoning is not None:
            raise ValueError("only assistant events may carry stream fields")
        return self


class AgentSessionView(StrictModel):
    contract_version: Literal[AGENT_CONTRACT_VERSION] = AGENT_CONTRACT_VERSION
    session_id: str
    settings: AgentSettings
    created_at: datetime
    running: bool
    closing: bool
    stopping: bool
    cleanup_unconfirmed: bool
    last_seq: int
    pending_approval_id: str | None = None
    model_alias: str | None = None
    turns: int
    history_revision: int = Field(default=0, ge=0)
    recovered: bool = False
    authority_revalidated: bool = True
    history_write_failed: bool = False
    recovery_state: Literal["current", "recovered", "interrupted"] = "current"


class AgentEvents(StrictModel):
    contract_version: Literal[AGENT_CONTRACT_VERSION] = AGENT_CONTRACT_VERSION
    session_id: str
    events: tuple[AgentEvent, ...]
    running: bool
    closing: bool
    stopping: bool
    cleanup_unconfirmed: bool
    pending_approval_id: str | None = None
    last_seq: int
    #: Oldest sequence number still kept; a client whose cursor is below it missed events.
    first_seq: int = 0


class SendMessage(StrictModel):
    text: str = Field(default="", max_length=40_000)
    attachment_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_AGENT_MESSAGE_ATTACHMENTS
    )

    @field_validator("attachment_ids")
    @classmethod
    def valid_attachment_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ID_PATTERN.fullmatch(item) is None for item in value):
            raise ValueError("attachment id is invalid")
        if len(set(value)) != len(value):
            raise ValueError("attachment ids must be unique")
        return value

    @model_validator(mode="after")
    def has_content(self) -> "SendMessage":
        if not self.text.strip() and not self.attachment_ids:
            raise ValueError("message requires text or an attachment")
        return self


AGENT_WRITE_PROPOSAL_CONTRACT_VERSION = "agent-write-proposal.v1"
AGENT_WRITE_TRANSACTION_PROPOSAL_CONTRACT_VERSION = (
    "agent-write-transaction-proposal.v2"
)
AGENT_LIFECYCLE_PROPOSAL_CONTRACT_VERSION = "agent-lifecycle-proposal.v1"
MAX_AGENT_WRITE_PROPOSAL_RECEIPTS = 64


class AgentWriteProposal(StrictModel):
    """One exact external-controller write offered for native review.

    The full proposed content is transient input.  Only its digest, the
    revision-bound diff, and the eventual write receipt may survive in the
    live session; the content is never appended to chat/model history.
    """

    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: Literal["create", "edit"]
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=MAX_FILE_WRITE_BYTES)
    expected_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def revision_matches_operation(self) -> "AgentWriteProposal":
        if self.operation == "create" and self.expected_revision is not None:
            raise ValueError("file creation must be bound to absence")
        if self.operation == "edit" and self.expected_revision is None:
            raise ValueError("file editing requires an exact source revision")
        return self


AgentWriteProposalState = Literal[
    "pending_native_review",
    "applied",
    "not_approved",
    "cancelled",
    "failed",
    "unverified",
]


class AgentWriteProposalReceipt(StrictModel):
    """Content-free lifecycle receipt for one idempotent write proposal."""

    contract_version: Literal[AGENT_WRITE_PROPOSAL_CONTRACT_VERSION] = (
        AGENT_WRITE_PROPOSAL_CONTRACT_VERSION
    )
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: Literal["create", "edit"]
    path: str = Field(min_length=1, max_length=1024)
    proposed_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: AgentWriteProposalState
    approval_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cursor: int = Field(ge=1)
    write_receipt: AgentWriteReceipt | None = None

    @model_validator(mode="after")
    def coherent_state(self) -> "AgentWriteProposalReceipt":
        if self.state == "pending_native_review":
            if self.approval_id is None or self.write_receipt is not None:
                raise ValueError("pending proposals require only native approval identity")
        elif self.approval_id is not None:
            raise ValueError("settled proposals cannot retain approval authority")
        if self.state == "applied" and (
            self.write_receipt is None or self.write_receipt.state != "verified"
        ):
            raise ValueError("applied proposals require a verified write receipt")
        if self.state == "unverified" and (
            self.write_receipt is None or self.write_receipt.state != "unverified"
        ):
            raise ValueError("unverified proposals require an unverified write receipt")
        if self.state not in {"applied", "unverified"} and self.write_receipt is not None:
            raise ValueError("only write outcomes may carry a write receipt")
        return self


class AgentWriteTransactionProposal(StrictModel):
    """One exact create/edit change set offered for one native review.

    Every member is revision-bound and the complete proposed text stays only
    in the live request/worker. The durable event journal never receives the
    proposal, its paths, diffs, or settlement events.
    """

    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    changes: tuple[WorkspaceTransactionChangeCommand, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )

    @model_validator(mode="after")
    def valid_transaction(self) -> "AgentWriteTransactionProposal":
        # Reuse the transaction command's case-insensitive uniqueness and
        # bounded cardinality checks at the public proposal boundary.
        WorkspaceTransactionPreviewCommand(changes=self.changes)
        return self


AgentWriteTransactionProposalState = Literal[
    "pending_native_review",
    "applied",
    "not_approved",
    "cancelled",
    "failed",
    "rolled_back",
    "unverified",
]


class AgentWriteTransactionProposalFile(StrictModel):
    """Content-free identity of one reviewed transaction member."""

    operation: Literal["create", "edit"]
    path: str = Field(min_length=1, max_length=1024)
    proposed_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentWriteTransactionProposalReceipt(StrictModel):
    """Bounded lifecycle receipt for an idempotent multi-file proposal."""

    contract_version: Literal[
        AGENT_WRITE_TRANSACTION_PROPOSAL_CONTRACT_VERSION
    ] = AGENT_WRITE_TRANSACTION_PROPOSAL_CONTRACT_VERSION
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    state: AgentWriteTransactionProposalState
    file_count: int = Field(
        strict=True,
        ge=2,
        le=MAX_WORKSPACE_TRANSACTION_FILES,
    )
    files: tuple[AgentWriteTransactionProposalFile, ...] = Field(
        min_length=2,
        max_length=MAX_WORKSPACE_TRANSACTION_FILES,
    )
    approval_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cursor: int = Field(ge=1)
    transaction_result: WorkspaceTransactionApplyResult | None = None

    @model_validator(mode="after")
    def coherent_state(self) -> "AgentWriteTransactionProposalReceipt":
        paths = [item.path for item in self.files]
        if (
            self.file_count != len(self.files)
            or paths != sorted(paths, key=lambda value: value.encode("utf-8"))
            or len({path.casefold() for path in paths}) != len(paths)
        ):
            raise ValueError("transaction proposal files are incoherent")
        if self.state == "pending_native_review":
            if self.approval_id is None or self.transaction_result is not None:
                raise ValueError(
                    "pending transaction proposals require only native approval identity"
                )
        elif self.approval_id is not None:
            raise ValueError("settled transaction proposals cannot retain approval authority")

        result = self.transaction_result
        if result is not None and (
            result.session_id != self.session_id
            or result.file_count != self.file_count
            or [item.path for item in result.files] != paths
        ):
            raise ValueError("transaction proposal result does not match its review")
        expected_result_state = {
            "applied": "committed",
            "rolled_back": "rolled_back",
            "unverified": "unverified",
        }.get(self.state)
        if expected_result_state is not None and (
            result is None or result.state != expected_result_state
        ):
            raise ValueError("transaction proposal outcome lacks matching evidence")
        if self.state in {"pending_native_review", "not_approved"} and result is not None:
            raise ValueError("unapplied transaction proposals cannot carry a result")
        if self.state == "failed" and result is not None and result.state != "rejected":
            raise ValueError("failed transaction proposals may carry only rejected evidence")
        if self.state == "cancelled" and result is not None and (
            result.state != "rejected" or result.reason != "tool_cancelled"
        ):
            raise ValueError("cancelled transaction proposal evidence is incoherent")
        if result is not None and result.state == "committed":
            proposed = {item.path: item.proposed_revision for item in self.files}
            if any(item.revision != proposed[item.path] for item in result.files):
                raise ValueError("committed transaction revisions do not match the review")
        return self


AgentLifecycleProposalOperation = Literal[
    "create_directory",
    "move_directory",
    "move_file",
    "trash_file",
]


class AgentLifecycleProposal(StrictModel):
    """One exact external workspace lifecycle action offered for native review.

    The controller can prepare a review but cannot apply it. File moves and
    recoverable trash are bound to the exact source revision observed by the
    caller. Directory operations remain no-overwrite and are rebound to a
    one-shot native preview before any effect.
    """

    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: AgentLifecycleProposalOperation
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    source_path: str | None = Field(default=None, min_length=1, max_length=1024)
    target_path: str | None = Field(default=None, min_length=1, max_length=1024)
    expected_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def exact_operation_shape(self) -> "AgentLifecycleProposal":
        single_path = self.operation in {"create_directory", "trash_file"}
        move_paths = self.operation in {"move_directory", "move_file"}
        revision_bound = self.operation in {"move_file", "trash_file"}
        if single_path is not (self.path is not None):
            raise ValueError("lifecycle operation path shape is invalid")
        if move_paths is not (
            self.source_path is not None and self.target_path is not None
        ):
            raise ValueError("lifecycle operation move shape is invalid")
        if not move_paths and (
            self.source_path is not None or self.target_path is not None
        ):
            raise ValueError("non-move lifecycle operation cannot carry move paths")
        if revision_bound is not (self.expected_revision is not None):
            raise ValueError("file lifecycle operation revision shape is invalid")
        return self


AgentLifecycleProposalState = Literal[
    "pending_native_review",
    "applied",
    "not_approved",
    "cancelled",
    "failed",
    "unverified",
]


class AgentLifecycleProposalReceipt(StrictModel):
    """Content-free receipt for one idempotent lifecycle proposal."""

    contract_version: Literal[AGENT_LIFECYCLE_PROPOSAL_CONTRACT_VERSION] = (
        AGENT_LIFECYCLE_PROPOSAL_CONTRACT_VERSION
    )
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation: AgentLifecycleProposalOperation
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    source_path: str | None = Field(default=None, min_length=1, max_length=1024)
    target_path: str | None = Field(default=None, min_length=1, max_length=1024)
    expected_revision: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    state: AgentLifecycleProposalState
    approval_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    cursor: int = Field(ge=1)
    verified: bool
    permanent: bool | None = None
    recovery: Literal["windows_recycle_bin"] | None = None

    @model_validator(mode="after")
    def coherent_state(self) -> "AgentLifecycleProposalReceipt":
        AgentLifecycleProposal(
            request_id=self.request_id,
            operation=self.operation,
            path=self.path,
            source_path=self.source_path,
            target_path=self.target_path,
            expected_revision=self.expected_revision,
        )
        if self.state == "pending_native_review":
            if self.approval_id is None or self.verified:
                raise ValueError("pending lifecycle proposals require native approval")
        elif self.approval_id is not None:
            raise ValueError("settled lifecycle proposals cannot retain approval authority")
        if self.verified is not (self.state == "applied"):
            raise ValueError("only applied lifecycle proposals are verified")
        if self.operation == "trash_file":
            if self.permanent is not False or self.recovery != "windows_recycle_bin":
                raise ValueError("trash proposals must remain explicitly recoverable")
        elif self.permanent is not None or self.recovery is not None:
            raise ValueError("non-trash lifecycle proposals cannot claim recovery")
        return self


class SwitchAgentSessionModel(StrictModel):
    """Revision-bound model rebinding for one idle, live Agent chat."""

    model_alias: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    expected_revision: int = Field(ge=1)


class RevalidateAgentAuthority(StrictModel):
    """Native-presence-gated capabilities for a recovered, idle chat."""

    expected_catalog_revision: int = Field(ge=1)
    allow_writes: bool = False
    allow_commands: bool = False
    allow_web: bool = False


class _RecoveredAgentProfile(StrictModel):
    parameters: AgentModelParameters = AgentModelParameters()
    instructions: str | None = Field(default=None, max_length=4_000)
    max_steps: int = Field(default=10, ge=1, le=MAX_STEPS_PER_TURN)
    command_timeout_seconds: int = Field(
        default=DEFAULT_COMMAND_SECONDS,
        ge=5,
        le=MAX_COMMAND_SECONDS,
    )


class ApprovalDecision(StrictModel):
    approved: bool


class AgentChatUpstream(Protocol):
    """Structural boundary to ADR 0013 without importing its runtime adapter."""

    status_code: int
    content_type: str
    body: bytes | None
    lines: Iterator[bytes] | None
    cancel: Callable[[], None] | None


@dataclass(slots=True)
class AgentModelReply:
    content: str
    reasoning: str
    tool_calls: list[dict[str, Any]]
    stream_id: str | None = None
    stream_status: AgentStreamStatus = AgentStreamStatus.COMPLETE
    failure_code: str | None = None
    tool_call_overflow: bool = False
    usage: RuntimeUsage = field(default_factory=RuntimeUsage)


def _completion_failure(finish_reason: object, *, saw_done: bool = False) -> str | None:
    """A terminal marker ends transport; it does not override a failed generation."""

    if finish_reason is None:
        return None if saw_done else "model_stream_incomplete"
    if not isinstance(finish_reason, str) or not finish_reason:
        return "model_reply_unusable"
    if finish_reason in {"stop", "tool_calls"}:
        return None
    return {
        "length": "model_response_limit",
        "content_filter": "model_response_filtered",
    }.get(finish_reason, "model_completion_unrecognized")


# ----- tool schemas the model sees -----


def tool_schemas(settings: AgentSettings) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {"type": "function", "function": {"name": ToolName.READ_FILE.value, "description": "Read a workspace text-file prefix (at most 96 KB read / 24,000 characters returned). Links/reparse points are never followed; truncation is explicit.",
                                          "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path relative to the workspace root"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": ToolName.LIST_DIR.value, "description": "List workspace files and folders (one or two levels, at most 400 shown). Incomplete results are not an empty-folder claim.",
                                          "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Relative folder, default '.'"}, "depth": {"type": "integer", "minimum": 1, "maximum": 2}}, "required": []}}},
        {"type": "function", "function": {"name": ToolName.SEARCH_TEXT.value, "description": "Bounded case-insensitive literal/regex search of UTF-8 files; returns path:line: text. Skips noisy folders/binary files, refuses links, and labels partial results. Limit/timeouts are not proof that no other matches exist.",
                                          "parameters": {"type": "object", "properties": {"query": {"type": "string", "maxLength": 1024}, "glob": {"type": "string", "maxLength": 1024, "description": "Root-relative glob: *.py searches the root; **/*.py includes nested folders. Default **/*."}, "regex": {"type": "boolean"}}, "required": ["query"]}}},
    ]
    if settings.allow_writes:
        tools.append({"type": "function", "function": {"name": ToolName.WRITE_FILE.value, "description": "Create or overwrite one workspace text file. The person approves an exact absence- or revision-bound diff; stale or unverified publication must be re-read, not retried. Two to eight write_file calls emitted in the same reply are reviewed once and applied as one rollback-capable create/edit transaction.",
                                                       "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}})
        tools.append({"type": "function", "function": {"name": ToolName.CREATE_DIRECTORY.value, "description": "Create exactly one workspace directory under an existing parent. The destination must remain absent and the person approves the exact path before publication.",
                                                       "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "New directory path relative to the workspace root; its parent must already exist"}}, "required": ["path"]}}})
        tools.append({"type": "function", "function": {"name": ToolName.MOVE_DIRECTORY.value, "description": "Rename or move one ordinary workspace directory without overwriting. The destination parent must already exist. This reviews path topology only; directory contents are moved but not enumerated or reviewed.",
                                                       "parameters": {"type": "object", "properties": {"source_path": {"type": "string"}, "target_path": {"type": "string"}}, "required": ["source_path", "target_path"]}}})
        tools.append({"type": "function", "function": {"name": ToolName.MOVE_FILE.value, "description": "Rename or move one existing workspace text file without overwriting. The destination parent must already exist; the person approves both exact paths and the reviewed source revision.",
                                                       "parameters": {"type": "object", "properties": {"source_path": {"type": "string"}, "target_path": {"type": "string"}}, "required": ["source_path", "target_path"]}}})
        tools.append({"type": "function", "function": {"name": ToolName.TRASH_FILE.value, "description": "Move one existing workspace text file to the Windows Recycle Bin after the person approves its exact path, revision, and byte size. This is recoverable and never a permanent deletion.",
                                                       "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Existing text-file path relative to the workspace root"}}, "required": ["path"]}}})
    if settings.allow_commands:
        tools.append({"type": "function", "function": {"name": ToolName.RUN_COMMAND.value, "description": "Run a shell command in the workspace (tests, builds, git status). The person must approve each command; output is returned (truncated).",
                                                       "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 5, "maximum": MAX_COMMAND_SECONDS}}, "required": ["command"]}}})
    if settings.allow_web:
        tools.append({"type": "function", "function": {"name": ToolName.FETCH_URL.value, "description": "Fetch a public web page (text only, truncated). The person must approve each fetch.",
                                                       "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}})
    return tools


SYSTEM_PROMPT = (
    "You are a careful local coding agent working inside one workspace folder on the person's machine. "
    "Inspect before changing: list and read files, search, then make small verifiable changes and run the relevant tests or build. "
    "Use the tools for every file access and command; never invent file contents. Paths are relative to the workspace root. "
    "Every enabled protected action pauses for the person's approval - if a call is denied, adapt instead of retrying it. "
    "Documents are ordinary files: write Markdown (.md), notes, plans and reports with write_file like any other change. "
    "When citing an existing workspace file in reply text, use a Markdown link such as [app.py](workspace:src/app.py) so the person can open it; use a relative forward-slash path and never an absolute path. "
    "Use create_directory for one new folder, move_directory for a no-overwrite folder rename or move, move_file for a no-overwrite file rename or move, and trash_file for a recoverable single-file removal; do not emulate those operations with shell commands. Never permanently delete a file or directory. "
    "When you are done, summarise what changed and how it was verified, briefly. Answer in the person's language."
)


def _system_prompt(settings: "AgentSettings", root: Path) -> str:
    shell = (
        "Commands run under PowerShell (Windows syntax: ; between commands, $env:VAR, backslash or forward-slash paths)."
        if platform.system() == "Windows"
        else "Commands run under bash."
    )
    inspection = (f"Inspection policy: {WORKSPACE_INSPECTION_VERSION}. "
                  "Incomplete or truncated tool results are not proof of full coverage. Narrow the glob or query when needed; "
                  "do not repeat an unchanged timed-out or refused inspection, and do not work around protected paths with commands.")
    publication = (f"Write policy: {WORKSPACE_WRITE_VERSION}. "
                   "Only the exact approved content may be published; after a stale, failed, or unverified write, inspect the file before proposing another change. "
                   "When two or more files must be created or edited together, emit their write_file calls in the same reply so they receive one failure-atomic review.")
    parts = [SYSTEM_PROMPT, shell, f"Workspace root: {root.name}/", inspection, publication]
    if settings.instructions:
        parts.append("Standing instructions from the person for this session: " + settings.instructions.strip())
    return " ".join(parts)


# ----- sessions and the run loop -----


@dataclass(slots=True)
class PendingApproval:
    approval_id: str
    tool: ToolName | str
    arguments: dict[str, Any]
    decided: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass(slots=True)
class _AgentWriteProposalRecord:
    request_id: str
    fingerprint: str
    operation: Literal["create", "edit"]
    path: str
    proposed_revision: str
    state: AgentWriteProposalState
    approval_id: str | None
    cursor: int
    write_receipt: AgentWriteReceipt | None = None


@dataclass(slots=True)
class _AgentWriteTransactionProposalRecord:
    request_id: str
    fingerprint: str
    files: tuple[AgentWriteTransactionProposalFile, ...]
    state: AgentWriteTransactionProposalState
    approval_id: str | None
    cursor: int
    transaction_result: WorkspaceTransactionApplyResult | None = None


@dataclass(slots=True)
class _AgentLifecycleProposalRecord:
    request_id: str
    fingerprint: str
    operation: AgentLifecycleProposalOperation
    path: str | None
    source_path: str | None
    target_path: str | None
    expected_revision: str | None
    state: AgentLifecycleProposalState
    approval_id: str | None
    cursor: int


@dataclass(slots=True)
class _PreparedAgentLifecycleProposal:
    tool: ToolName
    arguments: dict[str, Any]
    preview_text: str
    directory_create: WorkspaceDirectoryCreatePreview | None = None
    directory_move: WorkspaceDirectoryMovePreview | None = None
    file_move: WorkspaceMovePreview | None = None
    file_move_baseline: WorkspaceTextSnapshot | None = None
    file_trash: WorkspaceFileTrashPreview | None = None
    file_trash_baseline: WorkspaceTextSnapshot | None = None

    @property
    def preview_id(self) -> str:
        for item in (
            self.directory_create,
            self.directory_move,
            self.file_move,
            self.file_trash,
        ):
            if item is not None:
                return item.preview_id
        raise RuntimeError("lifecycle proposal preview is missing")


@dataclass(slots=True)
class AgentSession:
    session_id: str
    settings: AgentSettings
    created_at: datetime
    tools: WorkspaceTools
    context_status: AgentSessionContextStatus
    messages: list[dict[str, Any]] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    running: bool = False
    closing: bool = False
    stop_requested: bool = False
    cleanup_unconfirmed: bool = False
    pending: PendingApproval | None = None
    turns: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)
    event_ready: threading.Condition = field(init=False)
    thread: threading.Thread | None = None
    cancel_stream: Callable[[], None] | None = None
    active_turn: TurnReceiptBuilder | None = None
    request_cancelled: threading.Event = field(default_factory=threading.Event)
    changes: AgentChangeTracker = field(default_factory=AgentChangeTracker)
    history_revision: int = 0
    recovered: bool = False
    authority_revalidated: bool = True
    history_write_failed: bool = False
    recovery_interrupted: bool = False
    write_proposals: dict[str, _AgentWriteProposalRecord] = field(
        default_factory=dict
    )
    write_transaction_proposals: dict[
        str,
        _AgentWriteTransactionProposalRecord,
    ] = field(default_factory=dict)
    lifecycle_proposals: dict[str, _AgentLifecycleProposalRecord] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.event_ready = threading.Condition(self.lock)


class LocalAgentService:
    def __init__(
        self,
        *,
        chat: Callable[[str, bytes], tuple[int, bytes, str]],
        open_chat: Callable[[str, bytes], AgentChatUpstream] | None = None,
        active_model: Callable[[], str | None],
        model_ready: Callable[[str], bool] | None = None,
        allowed_roots: tuple[Path, ...] | None = None,
        forbidden_roots: tuple[Path, ...] = (),
        fetcher: Callable[[str], str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        approval_wait_seconds: float = APPROVAL_WAIT_SECONDS,
        catalog: AgentCatalogService | None = None,
        artifacts: AgentArtifactService | None = None,
        attachments: AgentAttachmentService | None = None,
        runtime_capabilities: Callable[[str], RuntimeCapabilities] | None = None,
        context_preflight: Callable[[str, bytes, int], RuntimeContextStatus] | None = None,
        mcp_managed_runtime: McpManagedRuntimeService | None = None,
    ) -> None:
        self._chat = chat
        self._open_chat = open_chat
        self._active_model = active_model
        self._model_ready = model_ready
        self._allowed_roots = tuple(root.resolve() for root in allowed_roots) if allowed_roots else None
        self._forbidden_roots = tuple(root.expanduser().resolve() for root in forbidden_roots)
        self._fetcher = fetcher
        self._runner = runner
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._editor = LocalAgentWorkspaceEditor(
            clock=self._clock,
            monotonic=monotonic,
        )
        self._file_lifecycle = LocalAgentWorkspaceFileLifecycle(
            clock=self._clock,
            monotonic=monotonic,
        )
        self._transactions = LocalAgentWorkspaceTransactionEditor(
            clock=self._clock,
            monotonic=monotonic,
        )
        self._approval_wait = approval_wait_seconds
        self._catalog = catalog
        self._artifacts = artifacts
        self._attachments = attachments
        self._runtime_capabilities = runtime_capabilities
        self._context_preflight = context_preflight
        self._mcp_managed_runtime = mcp_managed_runtime
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        # Resume and permanent catalog deletion must observe one serial lifecycle.
        # SQLite revisions protect the durable rows; this lock also prevents a
        # recovered live session from being published after its row was deleted.
        self._catalog_session_lifecycle = threading.Lock()
        self._shutting_down = False
        self._command_cleanup_unconfirmed = threading.Event()

    # -- sessions --

    @property
    def catalog(self) -> AgentCatalogService | None:
        return self._catalog

    @property
    def artifacts(self) -> AgentArtifactService | None:
        return self._artifacts

    @property
    def attachments(self) -> AgentAttachmentService | None:
        return self._attachments

    def bind_mcp_managed_runtime(
        self,
        runtime: McpManagedRuntimeService | None,
    ) -> None:
        """Bind the boot-owned runtime before any session can observe tools."""

        with self._lock:
            if self._sessions:
                if self._mcp_managed_runtime is not None:
                    # Rebuilding an in-process HTTP adapter must not swap the
                    # runtime beneath already-live sessions.
                    return
                raise LocalAgentError("mcp_managed_runtime_binding_too_late")
            self._mcp_managed_runtime = runtime

    def _attachment_runtime(self, session: AgentSession) -> tuple[str, RuntimeCapabilities]:
        alias = session.settings.model_alias or self._active_model()
        if alias is None:
            raise LocalAgentError("no_active_model")
        if not self._is_model_ready(alias):
            raise LocalAgentError("model_not_ready")
        if self._runtime_capabilities is None:
            raise LocalAgentError("agent_attachment_capabilities_unavailable")
        try:
            return alias, self._runtime_capabilities(alias)
        except Exception:
            raise LocalAgentError("agent_attachment_capabilities_unavailable") from None

    def stage_attachment(
        self,
        session_id: str,
        *,
        command: StageAgentAttachment,
        media_type: str,
        payload: bytes,
    ) -> AgentAttachment:
        service = self._attachments
        if service is None:
            raise LocalAgentError("agent_attachment_unavailable")
        session = self._session(session_id)
        with session.lock:
            if session.closing:
                raise LocalAgentError("session_closing")
            if session.running:
                raise LocalAgentError("turn_in_progress")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            alias, capabilities = self._attachment_runtime(session)
            try:
                return service.stage(
                    session_id=session_id,
                    model_alias=alias,
                    capabilities=capabilities,
                    command=command,
                    media_type=media_type,
                    payload=payload,
                )
            except AgentAttachmentError as error:
                raise LocalAgentError(error.code) from None

    def list_staged_attachments(self, session_id: str) -> AgentAttachmentList:
        service = self._attachments
        if service is None:
            raise LocalAgentError("agent_attachment_unavailable")
        self._session(session_id)
        try:
            return service.list_staged(session_id)
        except AgentAttachmentError as error:
            raise LocalAgentError(error.code) from None

    def delete_staged_attachment(self, session_id: str, attachment_id: str) -> None:
        service = self._attachments
        if service is None:
            raise LocalAgentError("agent_attachment_unavailable")
        session = self._session(session_id)
        with session.lock:
            if session.running:
                raise LocalAgentError("turn_in_progress")
        try:
            service.delete_staged(session_id, attachment_id)
        except AgentAttachmentError as error:
            raise LocalAgentError(error.code) from None

    def attachment_content(
        self, session_id: str, attachment_id: str
    ) -> AgentAttachmentContent:
        service = self._attachments
        if service is None:
            raise LocalAgentError("agent_attachment_unavailable")
        self._session(session_id)
        try:
            return service.content(session_id, attachment_id)
        except AgentAttachmentError as error:
            raise LocalAgentError(error.code) from None

    def attachment_document_preview(
        self,
        session_id: str,
        attachment_id: str,
    ) -> AgentAttachmentDocumentPreview:
        service = self._attachments
        if service is None:
            raise LocalAgentError("agent_attachment_unavailable")
        self._session(session_id)
        try:
            return service.document_preview(session_id, attachment_id)
        except AgentAttachmentError as error:
            raise LocalAgentError(error.code) from None

    def _artifact_workspace(self, *, project_id: str, session_id: str) -> Path:
        catalog = self._catalog
        if catalog is None or self._artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        try:
            record = catalog.get_session(session_id)
        except AgentCatalogError as error:
            raise LocalAgentError(error.code) from None
        if record.project_id != project_id:
            raise LocalAgentError("agent_catalog_session_not_found")
        settings = AgentSettings(
            workspace=record.workspace,
            project_id=record.project_id,
            model_alias=record.model_alias,
            allow_writes=False,
            allow_commands=False,
            allow_web=False,
            title=record.title,
            retention_policy=record.retention_policy,
        )
        _tools, root = self._workspace_tools(settings)
        return root

    def _relocate_artifact_after_move(
        self,
        session: AgentSession,
        result: WorkspaceMoveApplyResult,
    ) -> None:
        artifacts = self._artifacts
        project_id = session.settings.project_id
        if (
            artifacts is None
            or project_id is None
            or session.settings.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY
        ):
            return
        try:
            artifacts.relocate_reviewed_file(
                project_id=project_id,
                session_id=session.session_id,
                workspace=self._artifact_workspace(
                    project_id=project_id,
                    session_id=session.session_id,
                ),
                source_path=result.source_path,
                target_path=result.target_path,
                expected_sha256=result.revision,
                expected_byte_size=result.byte_size,
            )
        except AgentArtifactError as error:
            session.changes.mark_failed()
            raise LocalAgentError(error.code) from None

    def list_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
    ) -> AgentArtifactList:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.list_artifacts(
            project_id=project_id,
            session_id=session_id,
            view=view,
            limit=limit,
        )

    def page_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> AgentArtifactPage:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.page_artifacts(
            project_id=project_id,
            session_id=session_id,
            view=view,
            limit=limit,
            offset=offset,
            snapshot=snapshot,
        )

    def update_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: UpdateAgentArtifact,
    ) -> AgentArtifact:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.update_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            command=command,
        )

    def remove_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: RemoveAgentArtifact,
    ) -> AgentArtifact:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.remove_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            command=command,
        )

    def get_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
    ) -> AgentArtifactDetail:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.get_artifact(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
        )

    def capture_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        command: CaptureAgentArtifact,
    ) -> AgentArtifactDetail:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.capture(
            project_id=project_id,
            session_id=session_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
            command=command,
        )

    def preview_artifact_capture(
        self,
        *,
        project_id: str,
        session_id: str,
        command: PreviewAgentArtifactCapture,
    ) -> AgentArtifactCapturePreview:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.preview_capture(
            project_id=project_id,
            session_id=session_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
            command=command,
        )

    def artifact_content(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
        download: bool,
    ) -> AgentArtifactContent:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.content(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=version_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
            download=download,
        )

    def export_artifact_lineage(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: ExportAgentArtifact,
    ) -> AgentArtifactExport:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.export_lineage(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
            command=command,
        )

    def artifact_document_preview(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
    ) -> AgentDocumentPreview:
        artifacts = self._artifacts
        if artifacts is None:
            raise LocalAgentError("agent_artifact_unavailable")
        return artifacts.document_preview(
            project_id=project_id,
            session_id=session_id,
            artifact_id=artifact_id,
            version_id=version_id,
            workspace=self._artifact_workspace(
                project_id=project_id,
                session_id=session_id,
            ),
        )

    def catalog_session_availability(
        self,
        record: AgentCatalogSessionRecord,
    ) -> AgentCatalogSessionRecord:
        with self._lock:
            live = record.session_id in self._sessions
        available = live or record.retention_policy is AgentRetentionPolicy.LOCAL_HISTORY
        return record.model_copy(update={"conversation_available": available})

    def _workspace_tools(self, settings: AgentSettings) -> tuple[WorkspaceTools, Path]:
        if settings.allow_web and self._fetcher is None:
            raise LocalAgentError("web_fetch_unavailable")
        root = Path(settings.workspace).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise LocalAgentError("workspace_not_a_folder")
        tools = WorkspaceTools(
            root,
            command_timeout=settings.command_timeout_seconds,
            runner=self._runner,
            fetcher=self._fetcher if settings.allow_web else None,
        )
        root = tools.root
        if self._allowed_roots is not None and not any(
            root == allowed or allowed in root.parents for allowed in self._allowed_roots
        ):
            raise LocalAgentError("workspace_not_allowed")
        if any(
            root == forbidden
            or forbidden in root.parents
            or root in forbidden.parents
            for forbidden in self._forbidden_roots
        ):
            raise LocalAgentError("workspace_not_allowed")
        if root.anchor == str(root):
            raise LocalAgentError("workspace_is_a_drive_root")
        return tools, root

    @staticmethod
    def _history_profile(settings: AgentSettings) -> str | None:
        if settings.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY:
            return None
        return _RecoveredAgentProfile(
            parameters=settings.parameters,
            instructions=settings.instructions,
            max_steps=settings.max_steps,
            command_timeout_seconds=settings.command_timeout_seconds,
        ).model_dump_json()

    def delete_catalog_session(
        self,
        session_id: str,
        *,
        expected_catalog_revision: int,
        expected_history_revision: int,
    ) -> None:
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        with self._catalog_session_lifecycle:
            with self._lock:
                if session_id in self._sessions:
                    raise LocalAgentError("agent_catalog_session_live")
            try:
                catalog.delete_session(
                    session_id,
                    expected_catalog_revision=expected_catalog_revision,
                    expected_history_revision=expected_history_revision,
                )
            except AgentCatalogError as error:
                raise LocalAgentError(error.code) from None

    def update_catalog_session(
        self,
        session_id: str,
        command: UpdateAgentCatalogSession,
    ) -> AgentCatalogSessionRecord:
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        with self._catalog_session_lifecycle:
            with self._lock:
                live = self._sessions.get(session_id)
            if live is not None and (
                command.archived is True or command.model_alias is not None
            ):
                # A live chat must be closed before it can be hidden, and its
                # model must use the readiness-checked switch endpoint.
                raise LocalAgentError("agent_catalog_session_live")
            try:
                record = catalog.update_session(session_id, command)
            except AgentCatalogError as error:
                raise LocalAgentError(error.code) from None
            with self._lock:
                live = self._sessions.get(session_id)
                if live is not None:
                    with live.lock:
                        live.settings = live.settings.model_copy(update={
                            "project_id": record.project_id,
                            "title": record.title,
                        })
            return self.catalog_session_availability(record)

    @staticmethod
    def _event_from_stored(event: StoredAgentEvent) -> AgentEvent:
        return AgentEvent.model_validate(event.model_dump(mode="json", exclude_none=True))

    def _recovered_messages(
        self,
        settings: AgentSettings,
        root: Path,
        snapshot: AgentHistorySnapshot,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{
            "role": "system",
            "content": (
                _system_prompt(settings, root)
                + " This chat was recovered from its locally retained visible conversation. "
                "Earlier tool arguments and tool results were intentionally not restored. "
                "Reinspect the workspace before relying on prior file or command effects."
            ),
        }]
        for event in snapshot.events:
            if event.kind == "user" and (event.text or event.attachments):
                if event.attachments:
                    if self._attachments is None:
                        raise LocalAgentError("agent_attachment_unavailable")
                    try:
                        media_parts = self._attachments.recover_content_parts(
                            session_id=snapshot.session_id,
                            attachments=event.attachments,
                        )
                    except AgentAttachmentError as error:
                        raise LocalAgentError(error.code) from None
                    content: str | list[dict[str, object]] = [
                        *([{"type": "text", "text": event.text}] if event.text else []),
                        *media_parts,
                    ]
                else:
                    content = event.text or ""
                messages.append({"role": "user", "content": content})
            elif (
                event.kind == "assistant"
                and event.text
                and event.stream_status not in {"failed", "stopped"}
            ):
                messages.append({"role": "assistant", "content": event.text})
        return messages

    def catalog_events(
        self,
        *,
        project_id: str,
        session_id: str,
        after: int = 0,
        limit: int = MAX_EVENT_PAGE,
    ) -> AgentEvents:
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        try:
            snapshot = catalog.read_history(
                project_id=project_id,
                session_id=session_id,
                after=after,
                limit=limit,
            )
        except AgentCatalogError as error:
            raise LocalAgentError(error.code) from None
        return AgentEvents(
            session_id=session_id,
            events=tuple(self._event_from_stored(event) for event in snapshot.events),
            running=False,
            closing=False,
            stopping=False,
            cleanup_unconfirmed=False,
            pending_approval_id=None,
            last_seq=snapshot.last_seq,
            first_seq=snapshot.first_seq,
        )

    def resume(
        self,
        *,
        project_id: str,
        session_id: str,
        command: ResumeAgentSession,
    ) -> AgentSessionView:
        """Recover one durable chat without replaying authority or approvals."""

        with self._catalog_session_lifecycle:
            return self._resume_catalog_session(
                project_id=project_id,
                session_id=session_id,
                command=command,
            )

    def _resume_catalog_session(
        self,
        *,
        project_id: str,
        session_id: str,
        command: ResumeAgentSession,
    ) -> AgentSessionView:
        """Run the serialized half of durable chat recovery."""

        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        with self._lock:
            live = self._sessions.get(session_id)
        if live is not None:
            if live.settings.project_id != project_id:
                raise LocalAgentError("agent_catalog_session_not_found")
            return self._view(live)
        try:
            record = catalog.get_session(session_id)
            if record.project_id != project_id:
                raise AgentCatalogError("agent_catalog_session_not_found")
            if record.archived_at is not None:
                raise AgentCatalogError("agent_catalog_session_archived")
            if record.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY:
                raise AgentCatalogError("agent_history_not_retained")
            if record.revision != command.expected_catalog_revision:
                raise AgentCatalogError("agent_catalog_session_revision_conflict")
            snapshot = catalog.load_history(
                project_id=project_id,
                session_id=session_id,
            )
            if snapshot.history_revision != command.expected_history_revision:
                raise AgentCatalogError("agent_history_revision_conflict")
        except AgentCatalogError as error:
            raise LocalAgentError(error.code) from None
        try:
            profile = (
                _RecoveredAgentProfile()
                if snapshot.profile_json is None
                else _RecoveredAgentProfile.model_validate_json(snapshot.profile_json)
            )
        except ValueError:
            raise LocalAgentError("agent_history_corrupt") from None
        settings = AgentSettings(
            workspace=record.workspace,
            project_id=record.project_id,
            model_alias=record.model_alias,
            parameters=profile.parameters,
            instructions=profile.instructions,
            allow_writes=False,
            allow_commands=False,
            allow_web=False,
            max_steps=profile.max_steps,
            command_timeout_seconds=profile.command_timeout_seconds,
            title=record.title,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
        tools, root = self._workspace_tools(settings)
        session = AgentSession(
            session_id=session_id,
            settings=settings,
            created_at=record.created_at,
            tools=tools,
            context_status=unmeasured_session_context(
                session_id,
                reason="recovered_without_context_receipt",
            ),
            messages=self._recovered_messages(settings, root, snapshot),
            events=[self._event_from_stored(event) for event in snapshot.events],
            turns=snapshot.turn_count,
            history_revision=snapshot.history_revision,
            recovered=True,
            authority_revalidated=False,
            recovery_interrupted=snapshot.interrupted,
        )
        with self._lock:
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set():
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            if len(self._sessions) >= MAX_SESSIONS:
                raise LocalAgentError("too_many_sessions")
            concurrent = self._sessions.get(session_id)
            if concurrent is not None:
                return self._view(concurrent)
            self._sessions[session_id] = session
        return self._view(session)

    def export_history(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_catalog_revision: int | None = None,
        expected_history_revision: int | None = None,
    ) -> AgentHistoryExport:
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        try:
            return catalog.export_history(
                project_id=project_id,
                session_id=session_id,
                expected_catalog_revision=expected_catalog_revision,
                expected_history_revision=expected_history_revision,
            )
        except AgentCatalogError as error:
            raise LocalAgentError(error.code) from None

    def revalidate_authority(
        self,
        session_id: str,
        command: RevalidateAgentAuthority,
    ) -> AgentSessionView:
        """Revision-bind native authority revalidation to catalog lifecycle."""

        with self._catalog_session_lifecycle:
            return self._revalidate_authority(session_id, command)

    def _revalidate_authority(
        self,
        session_id: str,
        command: RevalidateAgentAuthority,
    ) -> AgentSessionView:
        """Recheck the exact workspace after native user-presence confirmation."""

        session = self._session(session_id)
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        try:
            record = catalog.get_session(session_id)
        except AgentCatalogError as error:
            raise LocalAgentError(error.code) from None
        if record.revision != command.expected_catalog_revision:
            raise LocalAgentError("agent_catalog_session_revision_conflict")
        if record.archived_at is not None:
            raise LocalAgentError("agent_catalog_session_archived")
        with self._lock, session.lock:
            if session.running or session.pending is not None:
                raise LocalAgentError("turn_in_progress")
            if session.closing:
                raise LocalAgentError("session_closing")
            next_settings = session.settings.model_copy(update={
                "allow_writes": command.allow_writes,
                "allow_commands": command.allow_commands,
                "allow_web": command.allow_web,
            })
            tools, _root = self._workspace_tools(next_settings)
            session.settings = next_settings
            session.tools = tools
            session.authority_revalidated = True
        return self._view(session)

    def create(self, settings: AgentSettings) -> AgentSessionView:
        with self._lock:
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set():
                raise LocalAgentError("command_cleanup_unconfirmed")
        tools, root = self._workspace_tools(settings)
        if settings.model_alias is not None and not self._is_model_ready(settings.model_alias):
            raise LocalAgentError("model_not_ready")
        if self._catalog is not None:
            try:
                project = self._catalog.resolve_project(settings.project_id)
            except AgentCatalogError as error:
                raise LocalAgentError(error.code) from None
            settings = settings.model_copy(update={"project_id": project.project_id})
        with self._lock:
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set():
                raise LocalAgentError("command_cleanup_unconfirmed")
            if len(self._sessions) >= MAX_SESSIONS:
                raise LocalAgentError("too_many_sessions")
            session_id = uuid.uuid4().hex
            session = AgentSession(
                session_id=session_id,
                settings=settings,
                created_at=self._clock(),
                tools=tools,
                context_status=unmeasured_session_context(
                    session_id,
                    reason="no_request_measured",
                ),
                messages=[{"role": "system", "content": _system_prompt(settings, root)}],
            )
            self._sessions[session_id] = session
        if self._catalog is not None:
            try:
                self._catalog.register_live_session(
                    session_id=session_id,
                    project_id=settings.project_id or "",
                    title=settings.title or root.name,
                    workspace=root,
                    model_alias=settings.model_alias,
                    created_at=session.created_at,
                    retention_policy=settings.retention_policy,
                    profile_json=self._history_profile(settings),
                )
            except AgentCatalogError as error:
                with self._lock:
                    self._sessions.pop(session_id, None)
                raise LocalAgentError(error.code) from None
        self._emit(session, "status", text=f"Session ready in {root.name}/ - reads are free; every enabled protected action waits for separate approval.")
        if session.history_write_failed:
            with self._lock:
                self._sessions.pop(session_id, None)
            try:
                if self._catalog is not None:
                    record = self._catalog.get_session(session_id)
                    self._catalog.delete_session(
                        session_id,
                        expected_catalog_revision=record.revision,
                        expected_history_revision=record.history_revision,
                    )
            except AgentCatalogError:
                pass
            raise LocalAgentError("agent_history_write_failed")
        return self._view(session)

    def list(self) -> tuple[AgentSessionView, ...]:
        with self._lock:
            sessions = list(self._sessions.values())
        return tuple(self._view(s) for s in sorted(sessions, key=lambda s: s.created_at, reverse=True))

    def hardening_facts(self) -> AgentLiveHardeningFacts:
        """Observe live recovery counters without probing a model or exposing content."""

        with self._lock:
            sessions = tuple(self._sessions.values())
            shutting_down = self._shutting_down
            process_cleanup_unconfirmed = self._command_cleanup_unconfirmed.is_set()
        running = closing = pending = cleanup = recovered = history_failed = 0
        for session in sessions:
            with session.lock:
                running += int(session.running)
                closing += int(session.closing)
                pending += int(session.pending is not None)
                cleanup += int(session.cleanup_unconfirmed)
                recovered += int(session.recovered and not session.authority_revalidated)
                history_failed += int(session.history_write_failed)
        return AgentLiveHardeningFacts(
            sessions=len(sessions),
            running_turns=running,
            closing_sessions=closing,
            pending_approvals=pending,
            cleanup_unconfirmed=cleanup,
            command_cleanup_quarantined=process_cleanup_unconfirmed,
            recovered_read_only=recovered,
            history_write_failures=history_failed,
            shutting_down=shutting_down,
        )

    def get(self, session_id: str) -> AgentSessionView:
        return self._view(self._session(session_id))

    def session_context(self, session_id: str) -> AgentSessionContextStatus:
        """Return the latest exact chat-bound preflight receipt or explicit unknown."""

        session = self._session(session_id)
        with session.lock:
            return session.context_status.model_copy(deep=True)

    @staticmethod
    def _set_context_unmeasured(
        session: AgentSession,
        reason: AgentSessionContextUnknownReason,
        *,
        turn: TurnReceiptBuilder | None = None,
    ) -> None:
        with session.lock:
            session.context_status = unmeasured_session_context(
                session.session_id,
                reason=reason,
                revision=session.context_status.revision + 1,
                turn_id=turn.turn_id if turn is not None else None,
                turn_number=turn.turn_number if turn is not None else None,
                model_alias=turn.model_alias if turn is not None else None,
            )

    def _bind_session_context(
        self,
        session: AgentSession,
        turn: TurnReceiptBuilder,
        context: RuntimeContextStatus,
    ) -> None:
        with session.lock:
            if session.active_turn is not turn:
                return
            session.context_status = AgentSessionContextStatus(
                session_id=session.session_id,
                revision=session.context_status.revision + 1,
                binding_state="bound",
                unknown_reason=None,
                turn_id=turn.turn_id,
                turn_number=turn.turn_number,
                model_alias=turn.model_alias,
                observed_at=self._clock(),
                context=context,
            )

    def switch_model(
        self,
        session_id: str,
        command: SwitchAgentSessionModel,
    ) -> AgentSessionView:
        """Serialize a live model binding with recovery and catalog updates."""

        with self._catalog_session_lifecycle:
            return self._switch_model(session_id, command)

    def _switch_model(
        self,
        session_id: str,
        command: SwitchAgentSessionModel,
    ) -> AgentSessionView:
        """Bind an idle chat to the exact globally served model.

        The durable catalog revision and in-memory settings change together
        while turn admission is closed by the same locks used by ``send``.
        Conversation messages and any unsent browser draft are untouched.
        """

        session = self._session(session_id)
        catalog = self._catalog
        if catalog is None:
            raise LocalAgentError("agent_catalog_unavailable")
        with self._lock, session.lock:
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.closing or self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_closing")
            if session.running or session.pending is not None:
                raise LocalAgentError("turn_in_progress")
            if not self._is_model_ready(command.model_alias):
                raise LocalAgentError("model_not_ready")
            try:
                record = catalog.update_session(
                    session_id,
                    UpdateAgentCatalogSession(
                        expected_revision=command.expected_revision,
                        model_alias=command.model_alias,
                    ),
                )
            except AgentCatalogError as error:
                raise LocalAgentError(error.code) from None
            previous_alias = session.settings.model_alias
            session.settings = session.settings.model_copy(
                update={
                    "project_id": record.project_id,
                    "title": record.title,
                    "model_alias": record.model_alias,
                }
            )
            if record.model_alias != previous_alias:
                self._set_context_unmeasured(session, "model_changed")
        return self._view(session)

    def delete(
        self,
        session_id: str,
        *,
        expected_project_id: str | None = None,
        expected_catalog_revision: int | None = None,
        expected_history_revision: int | None = None,
    ) -> None:
        session = self._session(session_id)
        exact_values = (
            expected_project_id,
            expected_catalog_revision,
            expected_history_revision,
        )
        exact_close = any(value is not None for value in exact_values)
        if exact_close and not all(value is not None for value in exact_values):
            raise LocalAgentError("agent_close_identity_incomplete")
        with self._lock, session.lock:
            if self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_not_found")
            if exact_close:
                catalog = self._catalog
                if catalog is None:
                    raise LocalAgentError("agent_catalog_unavailable")
                try:
                    record = catalog.get_session(session_id)
                except AgentCatalogError as error:
                    raise LocalAgentError(error.code) from None
                if (
                    record.project_id != expected_project_id
                    or session.settings.project_id != expected_project_id
                ):
                    raise LocalAgentError("agent_catalog_session_not_found")
                if record.revision != expected_catalog_revision:
                    raise LocalAgentError("agent_catalog_session_revision_conflict")
                if (
                    record.history_revision != expected_history_revision
                    or session.history_revision != expected_history_revision
                ):
                    raise LocalAgentError("agent_history_revision_conflict")
                if session.closing:
                    raise LocalAgentError("session_closing")
                if session.running or session.pending is not None:
                    raise LocalAgentError("turn_in_progress")
                if (
                    self._command_cleanup_unconfirmed.is_set()
                    or session.cleanup_unconfirmed
                ):
                    raise LocalAgentError("command_cleanup_unconfirmed")
            self._mark_closing(session)
        self.stop(session_id)
        thread = session.thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=15)
        if thread is not None and thread.is_alive():
            raise LocalAgentError("session_stop_timeout")
        if session.cleanup_unconfirmed:
            raise LocalAgentError("command_cleanup_unconfirmed")
        with self._lock:
            self._sessions.pop(session_id, None)
        self._editor.discard_session(session_id)
        self._file_lifecycle.discard_session(session_id)
        self._transactions.discard_session(session_id)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        """Close admission, deny pending actions, and verify owned turns exited.

        The application stops the local model runtime first so a stalled model
        read cannot hold shutdown open. Approved commands observe their turn's
        cancellation event. A surviving turn or uncertain command cleanup is
        reported, never silently dropped.
        """

        with self._lock:
            self._shutting_down = True
            sessions = tuple(self._sessions.values())
        failed = False
        for session in sessions:
            self._mark_closing(session)
            try:
                self.stop(session.session_id)
            except Exception:
                failed = True
        deadline = time.monotonic() + max(0.0, timeout)
        for session in sessions:
            thread = session.thread
            if thread is None:
                continue
            try:
                if thread is not threading.current_thread():
                    thread.join(timeout=max(0.0, deadline - time.monotonic()))
                failed = thread.is_alive() or failed
            except Exception:
                failed = True
        if failed or self._command_cleanup_unconfirmed.is_set():
            raise RuntimeError("agent_shutdown_incomplete")

    def workspace_tree(self, session_id: str, path: str = ".") -> WorkspaceTree:
        session = self._session(session_id)
        return self._editor.tree(session_id, session.tools, path)

    def workspace_discovery(self, session_id: str) -> WorkspaceDiscovery:
        session = self._session(session_id)
        snapshot = LocalAgentWorkspaceDiscovery().snapshot(session_id, session.tools)
        if "command_cleanup_unconfirmed" in snapshot.git_reasons:
            self._quarantine_commands()
        return snapshot

    def workspace_file(self, session_id: str, path: str) -> WorkspaceFile:
        session = self._session(session_id)
        return self._editor.read(session_id, session.tools, path)

    def workspace_search(
        self,
        session_id: str,
        query: str,
        glob: str = "**/*",
        regex: bool = False,
    ) -> WorkspaceSearchResult:
        session = self._session(session_id)
        return self._editor.search(session_id, session.tools, query, glob, regex)

    def change_set(self, session_id: str) -> AgentChangeSet:
        session = self._session(session_id)
        with session.lock:
            settled = (
                not session.running
                and not session.closing
                and not session.cleanup_unconfirmed
                and session.pending is None
                and not self._command_cleanup_unconfirmed.is_set()
            )
            # Keep turn admission and lifecycle changes closed while the
            # reviewed-path snapshot is assembled. The result is therefore a
            # coherent point-in-time claim, rather than an idle check followed
            # by a snapshot that a newly admitted turn can race.
            return session.changes.snapshot(
                session_id,
                session.tools,
                settled=settled,
            )

    def change_diff(self, session_id: str, path: str) -> AgentChangeDiff:
        session = self._session(session_id)
        return session.changes.diff(session_id, path, session.tools)

    def preview_change_restore(
        self,
        session_id: str,
        command: AgentChangeRestorePreviewCommand,
    ) -> AgentChangeRestorePreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        plan = session.changes.restore_plan(command.path, session.tools)
        if plan.operation == "edit":
            if (
                plan.content is None
                or plan.line_ending is None
                or plan.expected_revision is None
                or plan.restored_revision is None
            ):
                session.changes.mark_failed()
                raise LocalAgentError("change_restore_baseline_unavailable")
            inner = self.preview_workspace_edit(
                session_id,
                WorkspacePreviewCommand(
                    path=plan.path,
                    content=plan.content,
                    expected_revision=plan.expected_revision,
                    line_ending=WorkspaceLineEnding(plan.line_ending),
                ),
                _allow_retained_line_ending_change=True,
            )
            coherent = (
                inner.path == plan.path
                and inner.expected_revision == plan.expected_revision
                and inner.proposed_revision == plan.restored_revision
                and inner.line_ending.value == plan.line_ending
            )
        elif plan.operation == "recreate":
            if (
                plan.content is None
                or plan.line_ending is None
                or plan.restored_revision is None
            ):
                session.changes.mark_failed()
                raise LocalAgentError("change_restore_baseline_unavailable")
            inner = self.preview_workspace_create(
                session_id,
                WorkspaceCreatePreviewCommand(
                    path=plan.path,
                    content=plan.content,
                    line_ending=WorkspaceLineEnding(plan.line_ending),
                ),
            )
            coherent = (
                inner.path == plan.path
                and inner.proposed_revision == plan.restored_revision
                and inner.line_ending.value == plan.line_ending
            )
        else:
            if plan.expected_revision is None:
                session.changes.mark_failed()
                raise LocalAgentError("change_restore_unavailable")
            inner = self.preview_workspace_file_trash(
                session_id,
                WorkspaceFileTrashPreviewCommand(
                    path=plan.path,
                    expected_revision=plan.expected_revision,
                ),
            )
            coherent = (
                inner.path == plan.path
                and inner.expected_revision == plan.expected_revision
            )
        if not coherent:
            session.changes.discard_manual_preview(inner.preview_id)
            session.changes.mark_failed()
            raise LocalAgentError("change_restore_mismatch")
        return AgentChangeRestorePreview(
            session_id=session_id,
            preview_id=inner.preview_id,
            path=plan.path,
            operation=plan.operation,
            baseline_state=plan.baseline_state,
            expected_revision=plan.expected_revision,
            restored_revision=plan.restored_revision,
            restored_byte_size=plan.restored_byte_size,
            line_ending=plan.line_ending,
            diff_state=plan.diff_state,
            diff=plan.diff,
            added_lines=plan.added_lines,
            removed_lines=plan.removed_lines,
            recovery=plan.recovery,
            expires_at=inner.expires_at,
        )

    def apply_change_restore(
        self,
        session_id: str,
        preview_id: str,
        command: AgentChangeRestoreApplyCommand,
    ) -> AgentChangeRestoreApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        plan = session.changes.restore_plan(command.path, session.tools)
        if (
            plan.operation != command.operation
            or plan.expected_revision != command.expected_revision
            or plan.restored_revision != command.restored_revision
        ):
            raise LocalAgentError("change_restore_mismatch")

        if plan.operation == "edit":
            if (
                plan.content is None
                or plan.line_ending is None
                or plan.expected_revision is None
                or plan.restored_revision is None
            ):
                raise LocalAgentError("change_restore_baseline_unavailable")
            applied = self.apply_workspace_edit(
                session_id,
                preview_id,
                WorkspaceApplyCommand(
                    path=plan.path,
                    content=plan.content,
                    expected_revision=plan.expected_revision,
                    proposed_revision=plan.restored_revision,
                    line_ending=WorkspaceLineEnding(plan.line_ending),
                    confirmation=WORKSPACE_APPLY_CONFIRMATION,
                ),
            )
            current_revision = applied.revision
            current_byte_size = applied.byte_size
        elif plan.operation == "recreate":
            if (
                plan.content is None
                or plan.line_ending is None
                or plan.restored_revision is None
            ):
                raise LocalAgentError("change_restore_baseline_unavailable")
            applied_create = self.apply_workspace_create(
                session_id,
                preview_id,
                WorkspaceCreateApplyCommand(
                    path=plan.path,
                    content=plan.content,
                    proposed_revision=plan.restored_revision,
                    line_ending=WorkspaceLineEnding(plan.line_ending),
                    confirmation=WORKSPACE_CREATE_CONFIRMATION,
                ),
            )
            current_revision = applied_create.revision
            current_byte_size = applied_create.byte_size
        else:
            if plan.expected_revision is None:
                raise LocalAgentError("change_restore_unavailable")
            self.apply_workspace_file_trash(
                session_id,
                preview_id,
                WorkspaceFileTrashApplyCommand(
                    path=plan.path,
                    expected_revision=plan.expected_revision,
                    confirmation=WORKSPACE_FILE_TRASH_CONFIRMATION,
                ),
            )
            current_revision = None
            current_byte_size = None

        if plan.baseline_state == "present":
            try:
                observed = session.tools.read_text_snapshot(plan.path)
            except Exception:
                raise LocalAgentError("change_restore_verification_failed") from None
            if (
                observed.path != plan.path
                or observed.revision != plan.restored_revision
                or observed.byte_size != plan.restored_byte_size
                or current_revision != observed.revision
                or current_byte_size != observed.byte_size
            ):
                raise LocalAgentError("change_restore_verification_failed")
        else:
            try:
                session.tools.read_text_snapshot(plan.path)
            except LocalAgentError as error:
                if error.code != "workspace_path_not_found":
                    raise LocalAgentError("change_restore_verification_failed") from None
            except Exception:
                raise LocalAgentError("change_restore_verification_failed") from None
            else:
                raise LocalAgentError("change_restore_verification_failed")

        change_set_verification: Any = "tracking_unavailable"
        change_set_reason: Any = "tracking_failed"
        try:
            restored = self.change_set(session_id)
            summary = next((item for item in restored.files if item.path == plan.path), None)
            if summary is not None and summary.net_effect == "reverted":
                change_set_verification = summary.verification
                change_set_reason = summary.reason
            else:
                session.changes.mark_failed()
        except Exception:
            session.changes.mark_failed()
        return AgentChangeRestoreApplyResult(
            session_id=session_id,
            path=plan.path,
            operation=plan.operation,
            baseline_state=plan.baseline_state,
            current_revision=current_revision,
            current_byte_size=current_byte_size,
            recovery=plan.recovery,
            change_set_verification=change_set_verification,
            change_set_reason=change_set_reason,
        )

    def preview_workspace_create(
        self,
        session_id: str,
        command: WorkspaceCreatePreviewCommand,
    ) -> WorkspaceCreatePreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        preview = self._file_lifecycle.preview_create(session_id, session.tools, command)
        try:
            session.changes.stage_manual_create(preview.preview_id, preview.path)
        except Exception:
            session.changes.mark_failed()
        return preview

    def apply_workspace_create(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceCreateApplyCommand,
    ) -> WorkspaceCreateApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        try:
            result = self._file_lifecycle.apply_create(
                session_id, preview_id, session.tools, command
            )
        except LocalAgentError as error:
            try:
                if error.code == "workspace_verification_failed":
                    session.changes.observe_manual_create_unverified(
                        preview_id,
                        path=command.path,
                    )
                else:
                    session.changes.discard_manual_preview(preview_id)
            except Exception:
                session.changes.mark_failed()
            raise
        try:
            session.changes.observe_manual_created(preview_id, result)
        except Exception:
            session.changes.mark_failed()
        return result

    def preview_workspace_move(
        self,
        session_id: str,
        command: WorkspaceMovePreviewCommand,
    ) -> WorkspaceMovePreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        baseline = session.tools.read_text_snapshot(command.source_path)
        preview = self._file_lifecycle.preview_move(session_id, session.tools, command)
        try:
            if baseline.path != preview.source_path or baseline.revision != preview.expected_revision:
                session.changes.mark_failed()
            else:
                session.changes.stage_manual_preview(preview.preview_id, baseline)
        except Exception:
            session.changes.mark_failed()
        return preview

    def preview_workspace_file_trash(
        self,
        session_id: str,
        command: WorkspaceFileTrashPreviewCommand,
    ) -> WorkspaceFileTrashPreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        baseline = session.tools.read_text_snapshot(command.path)
        preview = self._file_lifecycle.preview_file_trash(
            session_id, session.tools, command
        )
        try:
            if baseline.path != preview.path or baseline.revision != preview.expected_revision:
                session.changes.mark_failed()
            else:
                session.changes.stage_manual_preview(preview.preview_id, baseline)
        except Exception:
            session.changes.mark_failed()
        return preview

    def preview_workspace_directory_create(
        self,
        session_id: str,
        command: WorkspaceDirectoryCreatePreviewCommand,
    ) -> WorkspaceDirectoryCreatePreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        return self._file_lifecycle.preview_directory_create(
            session_id, session.tools, command
        )

    def apply_workspace_directory_create(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceDirectoryCreateApplyCommand,
    ) -> WorkspaceDirectoryCreateApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        return self._file_lifecycle.apply_directory_create(
            session_id, preview_id, session.tools, command
        )

    def preview_workspace_directory_move(
        self,
        session_id: str,
        command: WorkspaceDirectoryMovePreviewCommand,
    ) -> WorkspaceDirectoryMovePreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        return self._file_lifecycle.preview_directory_move(
            session_id, session.tools, command
        )

    def apply_workspace_directory_move(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceDirectoryMoveApplyCommand,
    ) -> WorkspaceDirectoryMoveApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        return self._file_lifecycle.apply_directory_move(
            session_id, preview_id, session.tools, command
        )

    def apply_workspace_move(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceMoveApplyCommand,
    ) -> WorkspaceMoveApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        try:
            result = self._file_lifecycle.apply_move(
                session_id, preview_id, session.tools, command
            )
        except LocalAgentError as error:
            try:
                if error.code == "workspace_move_unverified":
                    session.changes.observe_manual_move_unverified(
                        preview_id,
                        source_path=command.source_path,
                        target_path=command.target_path,
                        expected_revision=command.expected_revision,
                    )
                else:
                    session.changes.discard_manual_preview(preview_id)
            except Exception:
                session.changes.mark_failed()
            raise
        try:
            session.changes.observe_manual_moved(preview_id, result)
        except Exception:
            session.changes.mark_failed()
        self._relocate_artifact_after_move(session, result)
        return result

    def apply_workspace_file_trash(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceFileTrashApplyCommand,
    ) -> WorkspaceFileTrashApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        try:
            result = self._file_lifecycle.apply_file_trash(
                session_id, preview_id, session.tools, command
            )
        except LocalAgentError as error:
            try:
                if error.code == "workspace_file_trash_unverified":
                    session.changes.observe_manual_trash_unverified(
                        preview_id,
                        path=command.path,
                        expected_revision=command.expected_revision,
                    )
                else:
                    session.changes.discard_manual_preview(preview_id)
            except Exception:
                session.changes.mark_failed()
            raise
        try:
            session.changes.observe_manual_trashed(preview_id, result)
        except Exception:
            session.changes.mark_failed()
        return result

    def preview_workspace_edit(
        self,
        session_id: str,
        command: WorkspacePreviewCommand,
        *,
        _allow_retained_line_ending_change: bool = False,
    ) -> WorkspaceEditPreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        baseline = session.tools.read_text_snapshot(command.path)
        preview = self._editor.preview(
            session_id,
            session.tools,
            command,
            allow_line_ending_change=_allow_retained_line_ending_change,
        )
        try:
            if baseline.path != preview.path or baseline.revision != preview.expected_revision:
                session.changes.mark_failed()
            else:
                session.changes.stage_manual_preview(preview.preview_id, baseline)
        except Exception:
            session.changes.mark_failed()
        return preview

    def apply_workspace_edit(
        self,
        session_id: str,
        preview_id: str,
        command: WorkspaceApplyCommand,
    ) -> WorkspaceApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        try:
            result = self._editor.apply(session_id, preview_id, session.tools, command)
        except LocalAgentError as error:
            try:
                if error.code == "workspace_verification_failed":
                    session.changes.observe_manual_unverified(
                        preview_id,
                        path=command.path,
                        expected_revision=command.expected_revision,
                    )
                else:
                    session.changes.discard_manual_preview(preview_id)
            except Exception:
                session.changes.mark_failed()
            raise
        try:
            session.changes.observe_manual_applied(
                preview_id,
                result,
                expected_revision=command.expected_revision,
            )
        except Exception:
            session.changes.mark_failed()
        return result

    @staticmethod
    def _transaction_stage_id(plan_id: str, path: str) -> str:
        return f"{plan_id}:{path}"

    def preview_workspace_transaction(
        self,
        session_id: str,
        command: WorkspaceTransactionPreviewCommand,
    ) -> WorkspaceTransactionPreview:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        baselines = {
            change.path: session.tools.read_text_snapshot(change.path)
            for change in command.changes
        }
        preview = self._transactions.preview(session_id, session.tools, command)
        try:
            for item in preview.files:
                baseline = baselines.get(item.path)
                if baseline is None or baseline.revision != item.expected_revision:
                    session.changes.mark_failed()
                    continue
                session.changes.stage_manual_preview(
                    self._transaction_stage_id(preview.plan_id, item.path),
                    baseline,
                )
        except Exception:
            session.changes.mark_failed()
        return preview

    def apply_workspace_transaction(
        self,
        session_id: str,
        plan_id: str,
        command: WorkspaceTransactionApplyCommand,
    ) -> WorkspaceTransactionApplyResult:
        session = self._session(session_id)
        if self._command_cleanup_unconfirmed.is_set():
            raise LocalAgentError("command_cleanup_unconfirmed")
        submitted = {change.path: change for change in command.changes}
        try:
            result = self._transactions.apply(session_id, plan_id, session.tools, command)
        except Exception:
            session.changes.discard_manual_plan(plan_id)
            raise
        try:
            for item in result.files:
                stage_id = self._transaction_stage_id(plan_id, item.path)
                change = submitted.get(item.path)
                if change is None:
                    session.changes.discard_manual_preview(stage_id)
                    session.changes.mark_failed()
                    continue
                if result.state == "committed" and item.revision is not None and item.byte_size is not None:
                    session.changes.observe_manual_applied(
                        stage_id,
                        WorkspaceApplyResult(
                            session_id=session_id,
                            path=item.path,
                            revision=item.revision,
                            byte_size=item.byte_size,
                        ),
                        expected_revision=change.expected_revision,
                    )
                elif item.state == "unverified":
                    session.changes.observe_manual_unverified(
                        stage_id,
                        path=item.path,
                        expected_revision=change.expected_revision,
                    )
                else:
                    session.changes.discard_manual_preview(stage_id)
        except Exception:
            session.changes.mark_failed()
        finally:
            session.changes.discard_manual_plan(plan_id)
        return result

    def events(self, session_id: str, after: int = 0, limit: int = MAX_EVENT_PAGE) -> AgentEvents:
        session = self._session(session_id)
        limit = max(1, min(int(limit), MAX_EVENT_PAGE))
        with session.lock:
            return self._events_locked(session, after=after, limit=limit)

    def wait_events(
        self,
        session_id: str,
        after: int = 0,
        limit: int = MAX_EVENT_PAGE,
        timeout: float = STREAM_WAIT_SECONDS,
    ) -> AgentEvents:
        """Wait for a cursor advance without busy-polling.

        This is an in-process notification only. The HTTP adapter may expose it
        as a private loopback SSE stream; it never opens a socket itself.
        """

        session = self._session(session_id)
        limit = max(1, min(int(limit), MAX_EVENT_PAGE))
        timeout = max(0.0, min(float(timeout), STREAM_WAIT_SECONDS))
        with session.event_ready:
            if not any(event.seq > after for event in session.events):
                session.event_ready.wait(timeout=timeout)
            return self._events_locked(session, after=after, limit=limit)

    @staticmethod
    def _events_locked(session: AgentSession, *, after: int, limit: int) -> AgentEvents:
        items = tuple(event for event in session.events if event.seq > after)[:limit]
        return AgentEvents(
            session_id=session.session_id,
            events=items,
            running=session.running,
            closing=session.closing,
            stopping=session.running and session.stop_requested,
            cleanup_unconfirmed=session.cleanup_unconfirmed,
            pending_approval_id=session.pending.approval_id if session.pending else None,
            last_seq=session.events[-1].seq if session.events else 0,
            first_seq=session.events[0].seq if session.events else 0,
        )

    # -- externally orchestrated, natively reviewed file proposals --

    @staticmethod
    def _write_proposal_fingerprint(command: AgentWriteProposal) -> str:
        try:
            content_sha256 = hashlib.sha256(
                command.content.encode("utf-8", errors="strict")
            ).hexdigest()
        except UnicodeEncodeError as error:
            raise LocalAgentError("workspace_text_invalid") from error
        payload = {
            "operation": command.operation,
            "path": command.path,
            "expected_revision": command.expected_revision,
            "content_sha256": content_sha256,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _write_proposal_receipt(
        session_id: str,
        record: _AgentWriteProposalRecord,
    ) -> AgentWriteProposalReceipt:
        return AgentWriteProposalReceipt(
            request_id=record.request_id,
            session_id=session_id,
            operation=record.operation,
            path=record.path,
            proposed_revision=record.proposed_revision,
            state=record.state,
            approval_id=record.approval_id,
            cursor=record.cursor,
            write_receipt=record.write_receipt,
        )

    @staticmethod
    def _write_proposal_state(outcome: ToolOutcome) -> AgentWriteProposalState:
        if outcome.write_receipt is not None:
            return (
                "applied"
                if outcome.ok and outcome.write_receipt.state == "verified"
                else "unverified"
            )
        if outcome.code == "approval_not_granted":
            return "not_approved"
        if outcome.code == "tool_cancelled":
            return "cancelled"
        return "failed"

    @staticmethod
    def _retain_external_write_receipt(outcome: ToolOutcome) -> bool:
        """Retain only verified file evidence in owner-selected local history.

        Proposal text, diffs, approval identities, and failed/denied attempts
        remain live-only.  The bounded write receipt is the same evidence used
        by native reviewed writes, so retaining it lets generated output cards
        survive restart without retaining the controller's content payload.
        """

        return bool(
            outcome.ok
            and outcome.write_receipt is not None
            and outcome.write_receipt.state == "verified"
        )

    @staticmethod
    def _write_proposal_status(state: AgentWriteProposalState) -> str:
        return {
            "applied": "External file proposal applied after native approval.",
            "not_approved": "External file proposal was not approved; the workspace was unchanged.",
            "cancelled": "External file proposal was cancelled before publication.",
            "unverified": "External file proposal ended with an unverified workspace effect; inspect the reviewed path.",
            "failed": "External file proposal failed without a verified workspace effect.",
            "pending_native_review": "External file proposal is waiting for native review.",
        }[state]

    def _prune_write_proposal_receipts(self, session: AgentSession) -> None:
        while (
            len(session.write_proposals)
            + len(session.write_transaction_proposals)
            + len(session.lifecycle_proposals)
            >= MAX_AGENT_WRITE_PROPOSAL_RECEIPTS
        ):
            settled = [
                (item.cursor, "single", request_id)
                for request_id, item in session.write_proposals.items()
                if item.state != "pending_native_review"
            ] + [
                (item.cursor, "transaction", request_id)
                for request_id, item in session.write_transaction_proposals.items()
                if item.state != "pending_native_review"
            ] + [
                (item.cursor, "lifecycle", request_id)
                for request_id, item in session.lifecycle_proposals.items()
                if item.state != "pending_native_review"
            ]
            if not settled:
                raise LocalAgentError("agent_write_proposal_limit_reached")
            _cursor, kind, request_id = min(settled)
            if kind == "single":
                session.write_proposals.pop(request_id, None)
            elif kind == "transaction":
                session.write_transaction_proposals.pop(request_id, None)
            else:
                session.lifecycle_proposals.pop(request_id, None)

    def propose_write(
        self,
        session_id: str,
        command: AgentWriteProposal,
    ) -> AgentWriteProposalReceipt:
        """Place one exact external write in the existing native approval card.

        This endpoint never publishes the file itself.  It retains the prepared
        bytes only in the live worker closure until native approval, denial,
        Stop, shutdown, or timeout settles the proposal.
        """

        session = self._session(session_id)
        fingerprint = self._write_proposal_fingerprint(command)
        with self._lock, session.lock:
            if (
                command.request_id in session.write_transaction_proposals
                or command.request_id in session.lifecycle_proposals
            ):
                raise LocalAgentError("agent_write_proposal_request_conflict")
            existing = session.write_proposals.get(command.request_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise LocalAgentError("agent_write_proposal_request_conflict")
                return self._write_proposal_receipt(session_id, existing)
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            if session.closing or self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_closing")
            if session.running or session.pending is not None:
                raise LocalAgentError("turn_in_progress")
            if not session.authority_revalidated or not session.settings.allow_writes:
                raise LocalAgentError("agent_write_proposal_not_allowed")

            prepared = session.tools.prepare_write(command.path, command.content)
            if command.operation == "create" and prepared.existed:
                raise LocalAgentError("workspace_lifecycle_target_exists")
            if command.operation == "edit" and not prepared.existed:
                raise LocalAgentError("workspace_existing_file_required")
            if (
                command.operation == "edit"
                and prepared.base_sha256 != command.expected_revision
            ):
                raise LocalAgentError("workspace_revision_changed")
            if prepared.existed and prepared.base_sha256 == prepared.proposed_sha256:
                raise LocalAgentError("workspace_no_change")

            self._prune_write_proposal_receipts(session)
            pending = PendingApproval(
                approval_id=uuid.uuid4().hex,
                tool=ToolName.WRITE_FILE,
                arguments={
                    "path": prepared.path,
                    "operation": command.operation,
                    "source": "external_controller",
                },
            )
            record = _AgentWriteProposalRecord(
                request_id=command.request_id,
                fingerprint=fingerprint,
                operation=command.operation,
                path=prepared.path,
                proposed_revision=prepared.proposed_sha256,
                state="pending_native_review",
                approval_id=pending.approval_id,
                cursor=max(1, session.events[-1].seq if session.events else 1),
            )
            session.write_proposals[command.request_id] = record
            session.running = True
            session.stop_requested = False
            session.request_cancelled = threading.Event()
            session.pending = pending
            timer = ToolExecutionReceiptBuilder(monotonic=self._monotonic)
            call_event = self._emit(
                session,
                "tool_call",
                persist=False,
                tool=ToolName.WRITE_FILE.value,
                arguments=dict(pending.arguments),
                call_id=command.request_id,
            )
            if session.history_write_failed:
                session.pending = None
                session.running = False
                session.write_proposals.pop(command.request_id, None)
                raise LocalAgentError("agent_history_write_failed")
            approval_event = self._emit(
                session,
                "approval_required",
                persist=False,
                tool=ToolName.WRITE_FILE.value,
                arguments=dict(pending.arguments),
                approval_id=pending.approval_id,
                preview=prepared.preview,
            )
            record.cursor = approval_event.seq
            try:
                thread = threading.Thread(
                    target=self._run_write_proposal,
                    args=(session, pending, prepared, command.request_id, timer),
                    name=f"local-agent-proposal-{session_id[:8]}",
                    daemon=True,
                )
                session.thread = thread
                thread.start()
            except Exception:
                session.pending = None
                session.running = False
                session.thread = None
                record.state = "failed"
                record.approval_id = None
                record.cursor = call_event.seq
                pending.approved = False
                pending.decided.set()
                self._emit(
                    session,
                    "approval_resolved",
                    persist=False,
                    tool=ToolName.WRITE_FILE.value,
                    approval_id=pending.approval_id,
                    ok=False,
                    text="proposal worker did not start",
                )
                result = self._emit(
                    session,
                    "tool_result",
                    persist=False,
                    tool=ToolName.WRITE_FILE.value,
                    call_id=command.request_id,
                    ok=False,
                    tool_state="failed",
                    execution_receipt=timer.finish(
                        approval_state="cancelled_before_decision",
                        evidence_state="no_effect",
                    ),
                    text="external file proposal could not start",
                )
                record.cursor = result.seq
                raise LocalAgentError("agent_write_proposal_start_failed")
            return self._write_proposal_receipt(session_id, record)

    def _run_write_proposal(
        self,
        session: AgentSession,
        pending: PendingApproval,
        prepared: PreparedWrite,
        request_id: str,
        timer: ToolExecutionReceiptBuilder,
    ) -> None:
        decided = pending.decided.wait(self._approval_wait)
        with session.lock:
            if session.pending is pending:
                session.pending = None
            approved = bool(
                decided and pending.approved and not session.stop_requested
            )
        self._emit(
            session,
            "approval_resolved",
            persist=False,
            tool=ToolName.WRITE_FILE.value,
            approval_id=pending.approval_id,
            ok=bool(decided and pending.approved),
            text=None if decided else "no decision in time; treated as denied",
        )

        approval_state: AgentToolApprovalState = (
            "timed_out"
            if not decided
            else "approved"
            if pending.approved
            else "cancelled_before_decision"
            if session.stop_requested
            else "denied"
        )

        if not decided:
            outcome = ToolOutcome(
                False,
                "native review timed out; the workspace was unchanged",
                "approval_not_granted",
            )
        elif not approved:
            outcome = ToolOutcome(
                False,
                "denied by the person; the workspace was unchanged",
                "tool_cancelled" if session.stop_requested else "approval_not_granted",
            )
        elif self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
            outcome = ToolOutcome(
                False,
                "Command cleanup is unconfirmed; the proposal was not published.",
                "command_cleanup_unconfirmed",
            )
        elif session.stop_requested:
            outcome = ToolOutcome(
                False,
                "cancelled before publication",
                "tool_cancelled",
            )
        else:
            try:
                outcome = self._apply_reviewed_write(session, prepared)
            except RuntimeCooperativeStop:
                outcome = ToolOutcome(
                    False,
                    "cancelled before a verified result",
                    "tool_cancelled",
                )
            except LocalAgentError as error:
                outcome = ToolOutcome(
                    False,
                    error.code.replace("_", " "),
                    error.code,
                )
            except Exception:
                outcome = ToolOutcome(
                    False,
                    "external file proposal failed",
                    "workspace_write_failed",
                )

        outcome = replace(outcome, approval_state=approval_state)
        state = self._write_proposal_state(outcome)
        tool_state = self._tool_state_for_outcome(outcome)
        with session.event_ready:
            result = self._emit(
                session,
                "tool_result",
                persist=self._retain_external_write_receipt(outcome),
                tool=ToolName.WRITE_FILE.value,
                call_id=request_id,
                ok=outcome.ok,
                tool_state=tool_state,
                write_receipt=outcome.write_receipt,
                execution_receipt=timer.finish(
                    approval_state=outcome.approval_state,
                    evidence_state=self._evidence_state_for_outcome(
                        ToolName.WRITE_FILE.value, outcome, tool_state
                    ),
                ),
                text=outcome.text[:MAX_TOOL_RESULT_CHARS],
            )
            record = session.write_proposals.get(request_id)
            if record is not None:
                record.state = state
                record.approval_id = None
                record.write_receipt = outcome.write_receipt
                record.cursor = result.seq
            session.running = False
            status = self._emit(
                session,
                "status",
                persist=False,
                text=self._write_proposal_status(state),
            )
            if record is not None:
                record.cursor = status.seq
            session.event_ready.notify_all()

    @staticmethod
    def _write_transaction_proposal_fingerprint(
        command: AgentWriteTransactionProposal,
    ) -> str:
        changes: list[dict[str, str | None]] = []
        for change in sorted(
            command.changes,
            key=lambda item: item.path.encode("utf-8"),
        ):
            try:
                content_sha256 = hashlib.sha256(
                    change.content.encode("utf-8", errors="strict")
                ).hexdigest()
            except UnicodeEncodeError as error:
                raise LocalAgentError("workspace_text_invalid") from error
            changes.append(
                {
                    "operation": change.operation,
                    "path": change.path,
                    "expected_revision": change.expected_revision,
                    "proposed_content_sha256": content_sha256,
                    "line_ending": change.line_ending.value,
                }
            )
        return hashlib.sha256(
            json.dumps(
                {"changes": changes},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _write_transaction_proposal_receipt(
        session_id: str,
        record: _AgentWriteTransactionProposalRecord,
    ) -> AgentWriteTransactionProposalReceipt:
        return AgentWriteTransactionProposalReceipt(
            request_id=record.request_id,
            session_id=session_id,
            state=record.state,
            file_count=len(record.files),
            files=record.files,
            approval_id=record.approval_id,
            cursor=record.cursor,
            transaction_result=record.transaction_result,
        )

    @staticmethod
    def _write_transaction_proposal_status(
        state: AgentWriteTransactionProposalState,
    ) -> str:
        return {
            "applied": "External change set applied atomically after native approval.",
            "not_approved": "External change set was not approved; the workspace was unchanged.",
            "cancelled": "External change set was cancelled before a verified publication.",
            "failed": "External change set failed without a verified workspace effect.",
            "rolled_back": "External change set did not commit; every published member was verified restored or removed.",
            "unverified": "External change set ended with an unverified workspace effect; inspect every reviewed path.",
            "pending_native_review": "External change set is waiting for native review.",
        }[state]

    @staticmethod
    def _same_transaction_review(
        left: WorkspaceTransactionPreview,
        right: WorkspaceTransactionPreview,
    ) -> bool:
        return (
            left.session_id == right.session_id
            and left.file_count == right.file_count
            and left.total_byte_size == right.total_byte_size
            and left.added_lines == right.added_lines
            and left.removed_lines == right.removed_lines
            and left.files == right.files
        )

    @staticmethod
    def _combined_transaction_preview(preview: WorkspaceTransactionPreview) -> str:
        return "\n\n".join(
            f"Transaction file {index + 1}/{preview.file_count} [{item.operation}]: {item.path}\n{item.diff}"
            for index, item in enumerate(preview.files)
        )

    def _transaction_tool_outcomes(
        self,
        session: AgentSession,
        preview: WorkspaceTransactionPreview,
        result: WorkspaceTransactionApplyResult,
        prepared_by_path: Mapping[str, PreparedWrite],
    ) -> tuple[ToolOutcome, ...]:
        """Project one atomic result into per-file, receipt-bearing events."""

        result_by_path = {item.path: item for item in result.files}
        outcomes: list[ToolOutcome] = []
        for reviewed in preview.files:
            represented = result_by_path.get(reviewed.path)
            prepared = prepared_by_path.get(reviewed.path)
            if represented is None or prepared is None:
                session.changes.mark_failed()
                outcomes.append(
                    ToolOutcome(
                        False,
                        "transaction result did not match the reviewed path",
                        "workspace_transaction_unverified",
                    )
                )
                continue
            if result.state == "committed":
                receipt = AgentWriteReceipt(
                    path=reviewed.path,
                    state="verified",
                    operation=(
                        "created" if reviewed.operation == "create" else "modified"
                    ),
                    before_sha256=reviewed.expected_revision,
                    after_sha256=reviewed.proposed_revision,
                    added_lines=reviewed.added_lines,
                    removed_lines=reviewed.removed_lines,
                    byte_size=reviewed.proposed_byte_size,
                )
                try:
                    if not session.changes.observe_agent_write(prepared, receipt):
                        session.changes.mark_failed()
                except Exception:
                    session.changes.mark_failed()
                outcomes.append(
                    ToolOutcome(
                        True,
                        f"transaction committed {preview.file_count} reviewed files; {reviewed.path} is verified",
                        write_receipt=receipt,
                    )
                )
                continue
            if represented.state == "unverified":
                receipt = AgentWriteReceipt(
                    path=reviewed.path,
                    state="unverified",
                    before_sha256=reviewed.expected_revision,
                )
                try:
                    session.changes.observe_agent_write(prepared, receipt)
                except Exception:
                    session.changes.mark_failed()
                outcomes.append(
                    ToolOutcome(
                        False,
                        f"transaction outcome is unverified for {reviewed.path}; inspect it before another write",
                        "workspace_transaction_unverified",
                        write_receipt=receipt,
                    )
                )
                continue
            code = (
                "tool_cancelled"
                if result.reason == "tool_cancelled"
                else "workspace_transaction_rolled_back"
                if result.state == "rolled_back"
                else result.reason or "workspace_write_failed"
            )
            state_text = {
                "restored": "restored",
                "removed": "removed",
                "not_applied": "not applied",
            }.get(represented.state, "not applied")
            outcomes.append(
                ToolOutcome(
                    False,
                    f"transaction did not commit; {reviewed.path} was {state_text}",
                    code,
                )
            )
        return tuple(outcomes)

    def propose_write_transaction(
        self,
        session_id: str,
        command: AgentWriteTransactionProposal,
    ) -> AgentWriteTransactionProposalReceipt:
        """Offer one exact create/edit transaction for one native decision."""

        session = self._session(session_id)
        fingerprint = self._write_transaction_proposal_fingerprint(command)
        with self._lock, session.lock:
            if (
                command.request_id in session.write_proposals
                or command.request_id in session.lifecycle_proposals
            ):
                raise LocalAgentError("agent_write_proposal_request_conflict")
            existing = session.write_transaction_proposals.get(command.request_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise LocalAgentError("agent_write_proposal_request_conflict")
                return self._write_transaction_proposal_receipt(session_id, existing)
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            if session.closing or self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_closing")
            if session.running or session.pending is not None:
                raise LocalAgentError("turn_in_progress")
            if not session.authority_revalidated or not session.settings.allow_writes:
                raise LocalAgentError("agent_write_proposal_not_allowed")

            tools = session.tools
            normalized_by_path: dict[str, str] = {}
            prepared_by_path: dict[str, PreparedWrite] = {}
            for change in command.changes:
                disk_content = (
                    change.content.replace("\n", "\r\n")
                    if change.line_ending is WorkspaceLineEnding.CRLF
                    else change.content
                )
                if change.operation == "edit":
                    try:
                        current = tools.read_text_snapshot(change.path)
                    except LocalAgentError as error:
                        if error.code == "workspace_path_not_found":
                            raise LocalAgentError(
                                "workspace_existing_file_required"
                            ) from None
                        raise
                    if (
                        current.revision != change.expected_revision
                        or WorkspaceLineEnding(current.line_ending)
                        is not change.line_ending
                    ):
                        raise LocalAgentError("workspace_transaction_changed")
                    prepared = tools.prepare_write(current.path, disk_content)
                else:
                    prepared = tools.prepare_write(change.path, disk_content)
                    if prepared.existed:
                        raise LocalAgentError("workspace_transaction_changed")
                normalized_by_path[prepared.path] = change.content
                prepared_by_path[prepared.path] = prepared

            preview_command = WorkspaceTransactionPreviewCommand(
                changes=command.changes
            )
            preview = self._transactions.preview(
                session_id,
                tools,
                preview_command,
            )
            files = tuple(
                AgentWriteTransactionProposalFile(
                    operation=item.operation,
                    path=item.path,
                    proposed_revision=item.proposed_revision,
                )
                for item in preview.files
            )
            self._prune_write_proposal_receipts(session)
            pending = PendingApproval(
                approval_id=uuid.uuid4().hex,
                tool=ToolName.WRITE_FILE,
                arguments={
                    "file_count": preview.file_count,
                    "create_count": sum(
                        item.operation == "create" for item in preview.files
                    ),
                    "edit_count": sum(
                        item.operation == "edit" for item in preview.files
                    ),
                    "paths": [item.path for item in preview.files],
                    "transaction": "failure_atomic_create_edit",
                    "source": "external_controller",
                },
            )
            record = _AgentWriteTransactionProposalRecord(
                request_id=command.request_id,
                fingerprint=fingerprint,
                files=files,
                state="pending_native_review",
                approval_id=pending.approval_id,
                cursor=max(1, session.events[-1].seq if session.events else 1),
            )
            session.write_transaction_proposals[command.request_id] = record
            session.running = True
            session.stop_requested = False
            session.request_cancelled = threading.Event()
            session.pending = pending
            timer = ToolExecutionReceiptBuilder(monotonic=self._monotonic)
            call_event = self._emit(
                session,
                "tool_call",
                persist=False,
                tool=ToolName.WRITE_FILE.value,
                arguments=dict(pending.arguments),
                call_id=command.request_id,
            )
            if session.history_write_failed:
                session.pending = None
                session.running = False
                session.write_transaction_proposals.pop(command.request_id, None)
                self._transactions.discard(session_id, preview.plan_id)
                raise LocalAgentError("agent_history_write_failed")
            approval_event = self._emit(
                session,
                "approval_required",
                persist=False,
                tool=ToolName.WRITE_FILE.value,
                arguments=dict(pending.arguments),
                approval_id=pending.approval_id,
                preview=self._combined_transaction_preview(preview),
            )
            record.cursor = approval_event.seq
            try:
                thread = threading.Thread(
                    target=self._run_write_transaction_proposal,
                    args=(
                        session,
                        pending,
                        preview,
                        preview_command,
                        normalized_by_path,
                        prepared_by_path,
                        command.request_id,
                        timer,
                    ),
                    name=f"local-agent-transaction-proposal-{session_id[:8]}",
                    daemon=True,
                )
                session.thread = thread
                thread.start()
            except Exception:
                self._transactions.discard(session_id, preview.plan_id)
                session.pending = None
                session.running = False
                session.thread = None
                record.state = "failed"
                record.approval_id = None
                record.cursor = call_event.seq
                pending.approved = False
                pending.decided.set()
                self._emit(
                    session,
                    "approval_resolved",
                    persist=False,
                    tool=ToolName.WRITE_FILE.value,
                    approval_id=pending.approval_id,
                    ok=False,
                    text="proposal worker did not start",
                )
                result_event = self._emit(
                    session,
                    "tool_result",
                    persist=False,
                    tool=ToolName.WRITE_FILE.value,
                    call_id=command.request_id,
                    ok=False,
                    tool_state="failed",
                    execution_receipt=timer.finish(
                        approval_state="cancelled_before_decision",
                        evidence_state="no_effect",
                    ),
                    text="external change-set proposal could not start",
                )
                record.cursor = result_event.seq
                raise LocalAgentError("agent_write_proposal_start_failed")
            return self._write_transaction_proposal_receipt(session_id, record)

    def _run_write_transaction_proposal(
        self,
        session: AgentSession,
        pending: PendingApproval,
        reviewed_preview: WorkspaceTransactionPreview,
        preview_command: WorkspaceTransactionPreviewCommand,
        normalized_by_path: Mapping[str, str],
        prepared_by_path: Mapping[str, PreparedWrite],
        request_id: str,
        timer: ToolExecutionReceiptBuilder,
    ) -> None:
        decided = pending.decided.wait(self._approval_wait)
        with session.lock:
            if session.pending is pending:
                session.pending = None
            approved = bool(
                decided and pending.approved and not session.stop_requested
            )
        self._emit(
            session,
            "approval_resolved",
            persist=False,
            tool=ToolName.WRITE_FILE.value,
            approval_id=pending.approval_id,
            ok=bool(decided and pending.approved),
            text=None if decided else "no decision in time; treated as denied",
        )

        approval_state: AgentToolApprovalState = (
            "timed_out"
            if not decided
            else "approved"
            if pending.approved
            else "cancelled_before_decision"
            if session.stop_requested
            else "denied"
        )

        result: WorkspaceTransactionApplyResult | None = None
        refreshed: WorkspaceTransactionPreview | None = None
        if not decided:
            state: AgentWriteTransactionProposalState = "not_approved"
            failure = ToolOutcome(
                False,
                "native review timed out; the workspace was unchanged",
                "approval_not_granted",
            )
        elif not approved:
            state = "cancelled" if session.stop_requested else "not_approved"
            failure = ToolOutcome(
                False,
                "cancelled before publication"
                if session.stop_requested
                else "denied by the person; the workspace was unchanged",
                "tool_cancelled" if session.stop_requested else "approval_not_granted",
            )
        elif self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
            state = "failed"
            failure = ToolOutcome(
                False,
                "Command cleanup is unconfirmed; the change set was not published.",
                "command_cleanup_unconfirmed",
            )
        elif session.stop_requested:
            state = "cancelled"
            failure = ToolOutcome(
                False,
                "cancelled before transaction publication",
                "tool_cancelled",
            )
        else:
            failure = ToolOutcome(
                False,
                "external change-set proposal failed",
                "workspace_write_failed",
            )
            state = "failed"
            try:
                # The manual-review capability is intentionally short-lived.
                # Rebuild it after the decision and require an identical review
                # before publication, so a long human pause cannot turn expiry
                # into either an unsafe apply or a false success.
                self._transactions.discard(
                    session.session_id,
                    reviewed_preview.plan_id,
                )
                with runtime_request_scope(session.request_cancelled):
                    refreshed = self._transactions.preview(
                        session.session_id,
                        session.tools,
                        preview_command,
                    )
                    if not self._same_transaction_review(
                        reviewed_preview,
                        refreshed,
                    ):
                        raise LocalAgentError("workspace_transaction_changed")
                    apply_command = WorkspaceTransactionApplyCommand(
                        changes=tuple(
                            WorkspaceTransactionApplyChange(
                                operation=item.operation,
                                path=item.path,
                                content=normalized_by_path[item.path],
                                expected_revision=item.expected_revision,
                                proposed_revision=item.proposed_revision,
                                line_ending=item.line_ending,
                            )
                            for item in refreshed.files
                        ),
                        confirmation=WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
                    )
                    result = self._transactions.apply(
                        session.session_id,
                        refreshed.plan_id,
                        session.tools,
                        apply_command,
                    )
                state = {
                    "committed": "applied",
                    "rolled_back": "rolled_back",
                    "unverified": "unverified",
                    "rejected": (
                        "cancelled"
                        if result.reason == "tool_cancelled"
                        else "failed"
                    ),
                }[result.state]
            except RuntimeCooperativeStop:
                state = "cancelled"
                failure = ToolOutcome(
                    False,
                    "cancelled before a verified transaction result",
                    "tool_cancelled",
                )
            except LocalAgentError as error:
                failure = ToolOutcome(
                    False,
                    error.code.replace("_", " "),
                    error.code,
                )
            except Exception:
                failure = ToolOutcome(
                    False,
                    "external change-set proposal failed",
                    "workspace_write_failed",
                )
            finally:
                if refreshed is not None:
                    self._transactions.discard(
                        session.session_id,
                        refreshed.plan_id,
                    )

        self._transactions.discard(
            session.session_id,
            reviewed_preview.plan_id,
        )
        outcomes = (
            self._transaction_tool_outcomes(
                session,
                reviewed_preview,
                result,
                prepared_by_path,
            )
            if result is not None
            else tuple(failure for _item in reviewed_preview.files)
        )
        outcomes = tuple(
            replace(outcome, approval_state=approval_state)
            for outcome in outcomes
        )
        with session.event_ready:
            cursor = reviewed_preview.file_count
            for index, outcome in enumerate(outcomes):
                tool_state = self._tool_state_for_outcome(outcome)
                event = self._emit(
                    session,
                    "tool_result",
                    persist=self._retain_external_write_receipt(outcome),
                    tool=ToolName.WRITE_FILE.value,
                    call_id=f"{request_id}:{index + 1}",
                    ok=outcome.ok,
                    tool_state=tool_state,
                    write_receipt=outcome.write_receipt,
                    execution_receipt=timer.finish(
                        approval_state=outcome.approval_state,
                        evidence_state=self._evidence_state_for_outcome(
                            ToolName.WRITE_FILE.value,
                            outcome,
                            tool_state,
                        ),
                    ),
                    text=outcome.text[:MAX_TOOL_RESULT_CHARS],
                )
                cursor = event.seq
            record = session.write_transaction_proposals.get(request_id)
            if record is not None:
                record.state = state
                record.approval_id = None
                record.transaction_result = result
                record.cursor = cursor
            session.running = False
            status = self._emit(
                session,
                "status",
                persist=False,
                text=self._write_transaction_proposal_status(state),
            )
            if record is not None:
                record.cursor = status.seq
            session.event_ready.notify_all()

    @staticmethod
    def _lifecycle_proposal_fingerprint(command: AgentLifecycleProposal) -> str:
        payload = command.model_dump(mode="json", exclude={"request_id"})
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _lifecycle_proposal_receipt(
        session_id: str,
        record: _AgentLifecycleProposalRecord,
    ) -> AgentLifecycleProposalReceipt:
        recoverable = record.operation == "trash_file"
        return AgentLifecycleProposalReceipt(
            request_id=record.request_id,
            session_id=session_id,
            operation=record.operation,
            path=record.path,
            source_path=record.source_path,
            target_path=record.target_path,
            expected_revision=record.expected_revision,
            state=record.state,
            approval_id=record.approval_id,
            cursor=record.cursor,
            verified=record.state == "applied",
            permanent=False if recoverable else None,
            recovery="windows_recycle_bin" if recoverable else None,
        )

    @staticmethod
    def _lifecycle_proposal_state(
        outcome: ToolOutcome,
    ) -> AgentLifecycleProposalState:
        if outcome.ok:
            return "applied"
        if outcome.code == "approval_not_granted":
            return "not_approved"
        if outcome.code == "tool_cancelled":
            return "cancelled"
        if outcome.code in {
            "workspace_lifecycle_unverified",
            "workspace_directory_create_unverified",
            "workspace_directory_move_unverified",
            "workspace_move_unverified",
            "workspace_file_trash_unverified",
            "workspace_verification_failed",
            "agent_artifact_relocation_unverified",
            "agent_artifact_relocation_conflict",
            "agent_artifact_relocation_target_conflict",
        }:
            return "unverified"
        return "failed"

    @staticmethod
    def _lifecycle_proposal_status(state: AgentLifecycleProposalState) -> str:
        return {
            "applied": "External lifecycle proposal applied after native approval.",
            "not_approved": "External lifecycle proposal was not approved; the workspace was unchanged.",
            "cancelled": "External lifecycle proposal was cancelled before a verified effect.",
            "failed": "External lifecycle proposal failed without a verified workspace effect.",
            "unverified": "External lifecycle proposal ended with an unverified workspace effect; inspect every reviewed path.",
            "pending_native_review": "External lifecycle proposal is waiting for native review.",
        }[state]

    def _prepare_agent_lifecycle_proposal(
        self,
        session: AgentSession,
        command: AgentLifecycleProposal,
    ) -> _PreparedAgentLifecycleProposal:
        tools = session.tools
        if command.operation == "create_directory":
            assert command.path is not None
            reviewed = self._file_lifecycle.preview_directory_create(
                session.session_id,
                tools,
                WorkspaceDirectoryCreatePreviewCommand(path=command.path),
            )
            return _PreparedAgentLifecycleProposal(
                tool=ToolName.CREATE_DIRECTORY,
                arguments={
                    "path": reviewed.path,
                    "operation": command.operation,
                    "source": "external_controller",
                },
                preview_text=(
                    "Create directory\n"
                    f"Path: {reviewed.path}\n"
                    "The parent must already exist. Nothing may be overwritten."
                ),
                directory_create=reviewed,
            )
        if command.operation == "move_directory":
            assert command.source_path is not None
            assert command.target_path is not None
            reviewed = self._file_lifecycle.preview_directory_move(
                session.session_id,
                tools,
                WorkspaceDirectoryMovePreviewCommand(
                    source_path=command.source_path,
                    target_path=command.target_path,
                ),
            )
            return _PreparedAgentLifecycleProposal(
                tool=ToolName.MOVE_DIRECTORY,
                arguments={
                    "source_path": reviewed.source_path,
                    "target_path": reviewed.target_path,
                    "operation": command.operation,
                    "source": "external_controller",
                },
                preview_text=(
                    "Move directory without overwrite\n"
                    f"From: {reviewed.source_path}\n"
                    f"To: {reviewed.target_path}\n"
                    "Path topology only: contents are moved but are not enumerated or reviewed."
                ),
                directory_move=reviewed,
            )
        if command.operation == "move_file":
            assert command.source_path is not None
            assert command.target_path is not None
            assert command.expected_revision is not None
            baseline = tools.read_text_snapshot(command.source_path)
            if baseline.revision != command.expected_revision:
                raise LocalAgentError("workspace_revision_changed")
            reviewed = self._file_lifecycle.preview_move(
                session.session_id,
                tools,
                WorkspaceMovePreviewCommand(
                    source_path=baseline.path,
                    target_path=command.target_path,
                    expected_revision=baseline.revision,
                ),
            )
            return _PreparedAgentLifecycleProposal(
                tool=ToolName.MOVE_FILE,
                arguments={
                    "source_path": reviewed.source_path,
                    "target_path": reviewed.target_path,
                    "expected_revision": reviewed.expected_revision,
                    "operation": command.operation,
                    "source": "external_controller",
                },
                preview_text=(
                    "Move file without overwrite\n"
                    f"From: {reviewed.source_path}\n"
                    f"To: {reviewed.target_path}\n"
                    f"Reviewed bytes: {reviewed.byte_size}\n"
                    f"Revision: {reviewed.expected_revision}"
                ),
                file_move=reviewed,
                file_move_baseline=baseline,
            )
        assert command.operation == "trash_file"
        assert command.path is not None
        assert command.expected_revision is not None
        baseline = tools.read_text_snapshot(command.path)
        if baseline.revision != command.expected_revision:
            raise LocalAgentError("workspace_revision_changed")
        reviewed = self._file_lifecycle.preview_file_trash(
            session.session_id,
            tools,
            WorkspaceFileTrashPreviewCommand(
                path=baseline.path,
                expected_revision=baseline.revision,
            ),
        )
        return _PreparedAgentLifecycleProposal(
            tool=ToolName.TRASH_FILE,
            arguments={
                "path": reviewed.path,
                "expected_revision": reviewed.expected_revision,
                "operation": command.operation,
                "source": "external_controller",
            },
            preview_text=(
                "Move file to Windows Recycle Bin\n"
                f"Path: {reviewed.path}\n"
                f"Reviewed bytes: {reviewed.byte_size}\n"
                f"Revision: {reviewed.expected_revision}\n"
                "Permanent deletion: no. Recovery is through Windows Recycle Bin."
            ),
            file_trash=reviewed,
            file_trash_baseline=baseline,
        )

    @staticmethod
    def _same_lifecycle_review(
        left: _PreparedAgentLifecycleProposal,
        right: _PreparedAgentLifecycleProposal,
    ) -> bool:
        return (
            left.tool is right.tool
            and left.arguments == right.arguments
            and (
                left.directory_create.path if left.directory_create else None
            )
            == (right.directory_create.path if right.directory_create else None)
            and (
                (
                    left.directory_move.source_path,
                    left.directory_move.target_path,
                    left.directory_move.contents_reviewed,
                )
                if left.directory_move
                else None
            )
            == (
                (
                    right.directory_move.source_path,
                    right.directory_move.target_path,
                    right.directory_move.contents_reviewed,
                )
                if right.directory_move
                else None
            )
            and (
                (
                    left.file_move.source_path,
                    left.file_move.target_path,
                    left.file_move.expected_revision,
                    left.file_move.byte_size,
                )
                if left.file_move
                else None
            )
            == (
                (
                    right.file_move.source_path,
                    right.file_move.target_path,
                    right.file_move.expected_revision,
                    right.file_move.byte_size,
                )
                if right.file_move
                else None
            )
            and (
                (
                    left.file_trash.path,
                    left.file_trash.expected_revision,
                    left.file_trash.byte_size,
                    left.file_trash.recovery,
                    left.file_trash.permanent,
                )
                if left.file_trash
                else None
            )
            == (
                (
                    right.file_trash.path,
                    right.file_trash.expected_revision,
                    right.file_trash.byte_size,
                    right.file_trash.recovery,
                    right.file_trash.permanent,
                )
                if right.file_trash
                else None
            )
        )

    def _discard_lifecycle_proposal_preview(
        self,
        session: AgentSession,
        prepared: _PreparedAgentLifecycleProposal,
    ) -> None:
        self._file_lifecycle.discard_preview(
            session.session_id,
            prepared.preview_id,
        )

    def _apply_agent_lifecycle_proposal(
        self,
        session: AgentSession,
        prepared: _PreparedAgentLifecycleProposal,
    ) -> ToolOutcome:
        tools = session.tools
        if prepared.tool is ToolName.CREATE_DIRECTORY:
            reviewed = prepared.directory_create
            if reviewed is None:
                return ToolOutcome(False, "directory review was unavailable")
            with runtime_request_scope(session.request_cancelled):
                result = self._file_lifecycle.apply_directory_create(
                    session.session_id,
                    reviewed.preview_id,
                    tools,
                    WorkspaceDirectoryCreateApplyCommand(
                        path=reviewed.path,
                        confirmation=WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
                    ),
                )
            return ToolOutcome(True, f"created directory {result.path}")
        if prepared.tool is ToolName.MOVE_DIRECTORY:
            reviewed = prepared.directory_move
            if reviewed is None:
                return ToolOutcome(False, "directory move review was unavailable")
            with runtime_request_scope(session.request_cancelled):
                result = self._file_lifecycle.apply_directory_move(
                    session.session_id,
                    reviewed.preview_id,
                    tools,
                    WorkspaceDirectoryMoveApplyCommand(
                        source_path=reviewed.source_path,
                        target_path=reviewed.target_path,
                        confirmation=WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
                    ),
                )
            return ToolOutcome(
                True,
                f"moved directory {result.source_path} to {result.target_path}; contents were not reviewed",
            )
        if prepared.tool is ToolName.MOVE_FILE:
            reviewed = prepared.file_move
            baseline = prepared.file_move_baseline
            if reviewed is None or baseline is None:
                return ToolOutcome(False, "move review was unavailable")
            try:
                with runtime_request_scope(session.request_cancelled):
                    result = self._file_lifecycle.apply_move(
                        session.session_id,
                        reviewed.preview_id,
                        tools,
                        WorkspaceMoveApplyCommand(
                            source_path=reviewed.source_path,
                            target_path=reviewed.target_path,
                            expected_revision=reviewed.expected_revision,
                            confirmation=WORKSPACE_MOVE_CONFIRMATION,
                        ),
                    )
            except LocalAgentError as error:
                if error.code == "workspace_move_unverified":
                    try:
                        session.changes.observe_agent_move_unverified(
                            baseline,
                            source_path=reviewed.source_path,
                            target_path=reviewed.target_path,
                        )
                    except Exception:
                        session.changes.mark_failed()
                raise
            try:
                coherent = session.changes.observe_agent_moved(baseline, result)
            except Exception:
                session.changes.mark_failed()
                coherent = False
            if not coherent:
                return ToolOutcome(
                    False,
                    "move verification receipt did not match the reviewed change",
                    "workspace_verification_failed",
                )
            self._relocate_artifact_after_move(session, result)
            return ToolOutcome(
                True,
                f"moved {result.source_path} to {result.target_path} without overwrite",
            )
        reviewed = prepared.file_trash
        baseline = prepared.file_trash_baseline
        if reviewed is None or baseline is None:
            return ToolOutcome(False, "Recycle Bin review was unavailable")
        try:
            with runtime_request_scope(session.request_cancelled):
                result = self._file_lifecycle.apply_file_trash(
                    session.session_id,
                    reviewed.preview_id,
                    tools,
                    WorkspaceFileTrashApplyCommand(
                        path=reviewed.path,
                        expected_revision=reviewed.expected_revision,
                        confirmation=WORKSPACE_FILE_TRASH_CONFIRMATION,
                    ),
                )
        except LocalAgentError as error:
            if error.code == "workspace_file_trash_unverified":
                try:
                    session.changes.observe_agent_trash_unverified(
                        baseline,
                        path=reviewed.path,
                    )
                except Exception:
                    session.changes.mark_failed()
            raise
        try:
            coherent = session.changes.observe_agent_trashed(baseline, result)
        except Exception:
            session.changes.mark_failed()
            coherent = False
        if not coherent:
            return ToolOutcome(
                False,
                "Recycle Bin receipt did not match the reviewed file",
                "workspace_file_trash_unverified",
            )
        return ToolOutcome(
            True,
            f"moved {result.path} to Windows Recycle Bin; permanent deletion was not used",
        )

    def propose_lifecycle(
        self,
        session_id: str,
        command: AgentLifecycleProposal,
    ) -> AgentLifecycleProposalReceipt:
        """Offer one path lifecycle action to the existing native approval card."""

        session = self._session(session_id)
        fingerprint = self._lifecycle_proposal_fingerprint(command)
        with self._lock, session.lock:
            if (
                command.request_id in session.write_proposals
                or command.request_id in session.write_transaction_proposals
            ):
                raise LocalAgentError("agent_write_proposal_request_conflict")
            existing = session.lifecycle_proposals.get(command.request_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise LocalAgentError("agent_write_proposal_request_conflict")
                return self._lifecycle_proposal_receipt(session_id, existing)
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            if session.closing or self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_closing")
            if session.running or session.pending is not None:
                raise LocalAgentError("turn_in_progress")
            if not session.authority_revalidated or not session.settings.allow_writes:
                raise LocalAgentError("agent_write_proposal_not_allowed")

            prepared = self._prepare_agent_lifecycle_proposal(session, command)
            self._prune_write_proposal_receipts(session)
            pending = PendingApproval(
                approval_id=uuid.uuid4().hex,
                tool=prepared.tool,
                arguments=dict(prepared.arguments),
            )
            record = _AgentLifecycleProposalRecord(
                request_id=command.request_id,
                fingerprint=fingerprint,
                operation=command.operation,
                path=(
                    prepared.directory_create.path
                    if prepared.directory_create
                    else prepared.file_trash.path
                    if prepared.file_trash
                    else None
                ),
                source_path=(
                    prepared.directory_move.source_path
                    if prepared.directory_move
                    else prepared.file_move.source_path
                    if prepared.file_move
                    else None
                ),
                target_path=(
                    prepared.directory_move.target_path
                    if prepared.directory_move
                    else prepared.file_move.target_path
                    if prepared.file_move
                    else None
                ),
                expected_revision=(
                    prepared.file_move.expected_revision
                    if prepared.file_move
                    else prepared.file_trash.expected_revision
                    if prepared.file_trash
                    else None
                ),
                state="pending_native_review",
                approval_id=pending.approval_id,
                cursor=max(1, session.events[-1].seq if session.events else 1),
            )
            session.lifecycle_proposals[command.request_id] = record
            session.running = True
            session.stop_requested = False
            session.request_cancelled = threading.Event()
            session.pending = pending
            timer = ToolExecutionReceiptBuilder(monotonic=self._monotonic)
            call_event = self._emit(
                session,
                "tool_call",
                persist=False,
                tool=prepared.tool.value,
                arguments=dict(prepared.arguments),
                call_id=command.request_id,
            )
            approval_event = self._emit(
                session,
                "approval_required",
                persist=False,
                tool=prepared.tool.value,
                arguments=dict(prepared.arguments),
                approval_id=pending.approval_id,
                preview=prepared.preview_text,
            )
            record.cursor = approval_event.seq
            try:
                thread = threading.Thread(
                    target=self._run_lifecycle_proposal,
                    args=(
                        session,
                        pending,
                        prepared,
                        command,
                        command.request_id,
                        timer,
                    ),
                    name=f"local-agent-lifecycle-proposal-{session_id[:8]}",
                    daemon=True,
                )
                session.thread = thread
                thread.start()
            except Exception:
                self._discard_lifecycle_proposal_preview(session, prepared)
                session.pending = None
                session.running = False
                session.thread = None
                record.state = "failed"
                record.approval_id = None
                record.cursor = call_event.seq
                pending.approved = False
                pending.decided.set()
                self._emit(
                    session,
                    "approval_resolved",
                    persist=False,
                    tool=prepared.tool.value,
                    approval_id=pending.approval_id,
                    ok=False,
                    text="proposal worker did not start",
                )
                result_event = self._emit(
                    session,
                    "tool_result",
                    persist=False,
                    tool=prepared.tool.value,
                    call_id=command.request_id,
                    ok=False,
                    tool_state="failed",
                    execution_receipt=timer.finish(
                        approval_state="cancelled_before_decision",
                        evidence_state="no_effect",
                    ),
                    text="external lifecycle proposal could not start",
                )
                record.cursor = result_event.seq
                raise LocalAgentError("agent_write_proposal_start_failed")
            return self._lifecycle_proposal_receipt(session_id, record)

    def _run_lifecycle_proposal(
        self,
        session: AgentSession,
        pending: PendingApproval,
        reviewed: _PreparedAgentLifecycleProposal,
        command: AgentLifecycleProposal,
        request_id: str,
        timer: ToolExecutionReceiptBuilder,
    ) -> None:
        decided = pending.decided.wait(self._approval_wait)
        with session.lock:
            if session.pending is pending:
                session.pending = None
            approved = bool(decided and pending.approved and not session.stop_requested)
        self._emit(
            session,
            "approval_resolved",
            persist=False,
            tool=_tool_value(pending.tool),
            approval_id=pending.approval_id,
            ok=bool(decided and pending.approved),
            text=None if decided else "no decision in time; treated as denied",
        )

        approval_state: AgentToolApprovalState = (
            "timed_out"
            if not decided
            else "approved"
            if pending.approved
            else "cancelled_before_decision"
            if session.stop_requested
            else "denied"
        )

        refreshed: _PreparedAgentLifecycleProposal | None = None
        if not decided:
            outcome = ToolOutcome(
                False,
                "native review timed out; the workspace was unchanged",
                "approval_not_granted",
            )
        elif not approved:
            outcome = ToolOutcome(
                False,
                "cancelled before publication"
                if session.stop_requested
                else "denied by the person; the workspace was unchanged",
                "tool_cancelled" if session.stop_requested else "approval_not_granted",
            )
        elif self._command_cleanup_unconfirmed.is_set() or session.cleanup_unconfirmed:
            outcome = ToolOutcome(
                False,
                "Command cleanup is unconfirmed; the lifecycle proposal was not applied.",
                "command_cleanup_unconfirmed",
            )
        elif session.stop_requested:
            outcome = ToolOutcome(False, "cancelled before publication", "tool_cancelled")
        else:
            try:
                # Lifecycle previews expire before the maximum human review
                # window. Rebind the same exact review after approval and
                # require its public identity to remain unchanged.
                self._discard_lifecycle_proposal_preview(session, reviewed)
                refreshed = self._prepare_agent_lifecycle_proposal(session, command)
                if not self._same_lifecycle_review(reviewed, refreshed):
                    self._discard_lifecycle_proposal_preview(session, refreshed)
                    refreshed = None
                    raise LocalAgentError("workspace_lifecycle_preview_mismatch")
                outcome = self._apply_agent_lifecycle_proposal(session, refreshed)
            except RuntimeCooperativeStop:
                outcome = ToolOutcome(
                    False,
                    "cancelled before a verified lifecycle result",
                    "tool_cancelled",
                )
            except LocalAgentError as error:
                outcome = ToolOutcome(False, error.code.replace("_", " "), error.code)
            except Exception:
                outcome = ToolOutcome(
                    False,
                    "external lifecycle proposal failed",
                    "workspace_lifecycle_failed",
                )

        self._discard_lifecycle_proposal_preview(session, reviewed)
        if refreshed is not None:
            self._discard_lifecycle_proposal_preview(session, refreshed)
        outcome = replace(outcome, approval_state=approval_state)
        state = self._lifecycle_proposal_state(outcome)
        with session.event_ready:
            tool_state = self._tool_state_for_outcome(outcome)
            result_event = self._emit(
                session,
                "tool_result",
                persist=False,
                tool=_tool_value(pending.tool),
                call_id=request_id,
                ok=outcome.ok,
                tool_state=tool_state,
                execution_receipt=timer.finish(
                    approval_state=outcome.approval_state,
                    evidence_state=self._evidence_state_for_outcome(
                        _tool_value(pending.tool), outcome, tool_state
                    ),
                ),
                text=outcome.text[:MAX_TOOL_RESULT_CHARS],
            )
            record = session.lifecycle_proposals.get(request_id)
            if record is not None:
                record.state = state
                record.approval_id = None
                record.cursor = result_event.seq
            session.running = False
            status = self._emit(
                session,
                "status",
                persist=False,
                text=self._lifecycle_proposal_status(state),
            )
            if record is not None:
                record.cursor = status.seq
            session.event_ready.notify_all()

    # -- turns --

    def send(self, session_id: str, message: SendMessage) -> AgentSessionView:
        session = self._session(session_id)
        configured_alias = session.settings.model_alias
        if configured_alias is not None:
            if not self._is_model_ready(configured_alias):
                raise LocalAgentError("model_not_ready")
            alias = configured_alias
        else:
            alias = self._active_model()
            if alias is not None and not self._is_model_ready(alias):
                raise LocalAgentError("model_not_ready")
        with self._lock, session.lock:
            if self._shutting_down:
                raise LocalAgentError("runtime_shutdown_in_progress")
            if self._command_cleanup_unconfirmed.is_set():
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.history_write_failed:
                raise LocalAgentError("agent_history_write_failed")
            if session.closing or self._sessions.get(session_id) is not session:
                raise LocalAgentError("session_closing")
            if session.running:
                raise LocalAgentError("turn_in_progress")
            if alias is None:
                raise LocalAgentError("no_active_model")
            prepared = PreparedAgentAttachments(attachments=(), content_parts=())
            if message.attachment_ids:
                if self._attachments is None:
                    raise LocalAgentError("agent_attachment_unavailable")
                if self._runtime_capabilities is None:
                    raise LocalAgentError("agent_attachment_capabilities_unavailable")
                try:
                    capabilities = self._runtime_capabilities(alias)
                    prepared = self._attachments.prepare(
                        session_id=session_id,
                        attachment_ids=message.attachment_ids,
                        model_alias=alias,
                        capabilities=capabilities,
                    )
                except AgentAttachmentError as error:
                    raise LocalAgentError(error.code) from None
                except Exception:
                    raise LocalAgentError("agent_attachment_capabilities_unavailable") from None
            if prepared.content_parts:
                content: str | list[dict[str, object]] = [
                    *([{"type": "text", "text": message.text}] if message.text.strip() else []),
                    *prepared.content_parts,
                ]
            else:
                content = message.text
            session.running = True
            session.stop_requested = False
            session.request_cancelled = threading.Event()
            session.active_turn = TurnReceiptBuilder(
                turn_id=uuid.uuid4().hex, turn_number=session.turns + 1,
                model_alias=alias, started_at=self._clock(), monotonic=self._monotonic,
            )
            turn = session.active_turn
            self._set_context_unmeasured(session, "turn_pending_preflight", turn=turn)
            start_failed = False
            durable = session.settings.retention_policy is AgentRetentionPolicy.LOCAL_HISTORY
            if durable:
                user_event = self._emit(
                    session,
                    "user",
                    text=message.text if message.text.strip() else None,
                    attachments=prepared.attachments,
                )
                if session.history_write_failed:
                    session.running = False
                    self._set_context_unmeasured(session, "turn_start_failed", turn=turn)
                    session.active_turn = None
                    raise LocalAgentError("agent_history_write_failed")
                if message.attachment_ids:
                    try:
                        assert self._attachments is not None
                        self._attachments.settle_sent(
                            session_id=session_id,
                            attachment_ids=message.attachment_ids,
                            event_seq=user_event.seq,
                            retention="local_history",
                        )
                    except AgentAttachmentError as error:
                        session.running = False
                        self._set_context_unmeasured(session, "turn_start_failed", turn=turn)
                        session.active_turn = None
                        raise LocalAgentError(error.code) from None
                session.messages.append({"role": "user", "content": content})
            elif message.attachment_ids:
                try:
                    assert self._attachments is not None
                    self._attachments.settle_sent(
                        session_id=session_id,
                        attachment_ids=message.attachment_ids,
                        event_seq=1,
                        retention="memory_only",
                    )
                except AgentAttachmentError as error:
                    session.running = False
                    self._set_context_unmeasured(session, "turn_start_failed", turn=turn)
                    session.active_turn = None
                    raise LocalAgentError(error.code) from None
            try:
                thread = threading.Thread(target=self._run_turn, args=(session, alias), name=f"local-agent-{session_id[:8]}", daemon=True)
                session.thread = thread
                thread.start()
            except Exception:
                session.running = False
                session.thread = None
                start_failed = True
            if start_failed:
                self._set_context_unmeasured(session, "turn_start_failed", turn=turn)
                if durable:
                    session.turns += 1
                    self._emit(session, "error", text="The agent response could not start.")
                    self._emit(
                        session,
                        "done",
                        turn_summary=turn.finish(
                            status="failed",
                            reason="turn_failed",
                            finished_at=self._clock(),
                        ),
                    )
                    session.active_turn = None
                else:
                    session.active_turn = None
                raise LocalAgentError("turn_start_failed")
            session.turns += 1
            if not durable:
                self._emit(
                    session,
                    "user",
                    text=message.text if message.text.strip() else None,
                    attachments=prepared.attachments,
                )
                session.messages.append({"role": "user", "content": content})
        return self._view(session)

    def _is_model_ready(self, alias: str) -> bool:
        """Fail closed unless the requested alias is running at this instant.

        The injected readiness boundary lets the application check the exact
        selected alias instead of treating a registered model as a live model.
        Lightweight adapters that only provide ``active_model`` retain the
        same invariant by requiring an exact alias match.
        """

        try:
            if self._model_ready is not None:
                return bool(self._model_ready(alias))
            return self._active_model() == alias
        except Exception:  # noqa: BLE001 - readiness uncertainty must deny the turn
            return False

    def stop(self, session_id: str) -> AgentSessionView:
        session = self._session(session_id)
        with session.lock:
            first_request = session.running and not session.stop_requested
            external_proposal = any(
                item.state == "pending_native_review"
                for item in session.write_proposals.values()
            ) or any(
                item.state == "pending_native_review"
                for item in session.write_transaction_proposals.values()
            )
            session.stop_requested = True
            session.request_cancelled.set()
            pending = session.pending
            if pending is not None and not pending.decided.is_set():
                pending.approved = False
                pending.decided.set()
            cancel_stream = session.cancel_stream if first_request else None
            if first_request:
                self._emit(
                    session,
                    "status",
                    persist=not external_proposal,
                    text="Stopping response; waiting for the active operation to end.",
                )
        if cancel_stream is not None:
            cancel_stream()
        return self._view(session)

    def approve(self, session_id: str, approval_id: str, decision: ApprovalDecision) -> AgentSessionView:
        session = self._session(session_id)
        with session.lock:
            if session.cleanup_unconfirmed:
                raise LocalAgentError("command_cleanup_unconfirmed")
            if session.closing:
                raise LocalAgentError("session_closing")
            pending = session.pending
            if pending is None or pending.approval_id != approval_id:
                raise LocalAgentError("approval_not_pending")
            if pending.decided.is_set():
                raise LocalAgentError("approval_already_settled")
            pending.approved = decision.approved
            pending.decided.set()
        return self._view(session)

    # -- internals --

    def _quarantine_commands(self) -> None:
        """Retain unsafe command ownership even when its turn thread exits."""

        with self._lock:
            self._command_cleanup_unconfirmed.set()
            sessions = tuple(self._sessions.values())
        for session in sessions:
            with session.event_ready:
                if session.cleanup_unconfirmed:
                    continue
                session.cleanup_unconfirmed = True
                session.closing = True
                session.stop_requested = True
                session.request_cancelled.set()
                if session.pending is not None:
                    session.pending.approved = False
                    session.pending.decided.set()
                    session.pending = None
                self._emit(session, "error", text=(
                    "Agent paused: command process cleanup is unconfirmed. Inspect the command processes "
                    "before restarting the app. Earlier command effects were not undone."
                ))

    def _mark_closing(self, session: AgentSession) -> None:
        with session.lock:
            if session.closing:
                return
            session.closing = True
            # Publish one cursor advance so already-connected windows learn the
            # admission state even when the current turn has no further output.
            self._emit(session, "status", text="Session closing; no new messages are accepted.")

    def _session(self, session_id: str) -> AgentSession:
        if not _ID_PATTERN.fullmatch(session_id or ""):
            raise LocalAgentError("session_not_found")
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise LocalAgentError("session_not_found")
        return session

    def _view(self, session: AgentSession) -> AgentSessionView:
        alias = session.settings.model_alias or self._active_model()  # may probe hardware; never under the lock
        with session.lock:
            return AgentSessionView(
                session_id=session.session_id,
                settings=session.settings,
                created_at=session.created_at,
                running=session.running,
                closing=session.closing,
                stopping=session.running and session.stop_requested,
                cleanup_unconfirmed=session.cleanup_unconfirmed,
                last_seq=session.events[-1].seq if session.events else 0,
                pending_approval_id=session.pending.approval_id if session.pending else None,
                model_alias=alias,
                turns=session.turns,
                history_revision=session.history_revision,
                recovered=session.recovered,
                authority_revalidated=session.authority_revalidated,
                history_write_failed=session.history_write_failed,
                recovery_state=(
                    "interrupted"
                    if session.recovery_interrupted
                    else "recovered"
                    if session.recovered
                    else "current"
                ),
            )

    @staticmethod
    def _stored_event(event: AgentEvent) -> StoredAgentEvent | None:
        if event.kind in {"assistant_delta", "approval_required", "approval_resolved"}:
            return None
        if event.kind == "status" and event.text == "Session closing; no new messages are accepted.":
            return None
        include = {
            "seq",
            "at",
            "kind",
            "text",
            "attachments",
            "reasoning",
            "stream_id",
            "stream_status",
            "tool",
            "call_id",
            "ok",
            "turn_id",
            "turn_summary",
            "tool_state",
            "write_receipt",
            "execution_receipt",
            "mcp_tool",
            "mcp_result",
        }
        payload = event.model_dump(mode="json", include=include, exclude_none=True)
        # Raw tool output can contain source, command output, or fetched text.
        if event.kind == "tool_result":
            payload.pop("text", None)
        return StoredAgentEvent.model_validate(payload)

    def _emit(
        self,
        session: AgentSession,
        kind: str,
        *,
        persist: bool = True,
        **fields: Any,
    ) -> AgentEvent:
        with session.event_ready:
            seq = (session.events[-1].seq if session.events else 0) + 1
            event = AgentEvent(seq=seq, at=self._clock(), kind=kind,
                               turn_id=session.active_turn.turn_id if session.active_turn else None,
                               **fields)  # type: ignore[arg-type]
            if persist and session.settings.retention_policy is AgentRetentionPolicy.LOCAL_HISTORY:
                try:
                    stored = self._stored_event(event)
                    if stored is not None:
                        if self._catalog is None or session.settings.project_id is None:
                            raise AgentCatalogError("agent_history_storage_unavailable")
                        session.history_revision = self._catalog.append_history_event(
                            project_id=session.settings.project_id,
                            session_id=session.session_id,
                            expected_history_revision=session.history_revision,
                            event=stored,
                        )
                except (AgentCatalogError, ValueError):
                    session.history_write_failed = True
            session.events.append(event)
            if len(session.events) > MAX_EVENTS:
                delta_index = next(
                    (index for index, item in enumerate(session.events) if item.kind == "assistant_delta"),
                    0,
                )
                del session.events[delta_index]
            session.event_ready.notify_all()
        return event

    @staticmethod
    def _whole_model_reply(payload: bytes) -> AgentModelReply:
        if len(payload) > MAX_AGENT_STREAM_BYTES:
            raise LocalAgentError("model_reply_too_large")
        try:
            decoded = payload.decode("utf-8")
            reply = model_json_object(decoded, max_characters=MAX_AGENT_STREAM_BYTES) if decoded.lstrip().startswith("{") else None
        except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError):
            raise LocalAgentError("model_reply_unusable") from None
        if not isinstance(reply, dict) or not isinstance(reply.get("choices"), list) or len(reply["choices"]) != 1:
            raise LocalAgentError("model_reply_unusable")
        choice = reply["choices"][0]
        if not isinstance(choice, dict):
            raise LocalAgentError("model_reply_unusable")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LocalAgentError("model_reply_unusable")
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            tool_calls = []
        if content is not None and not isinstance(content, str):
            raise LocalAgentError("model_reply_unusable")
        if reasoning is not None and not isinstance(reasoning, str):
            raise LocalAgentError("model_reply_unusable")
        if not isinstance(tool_calls, list) or not all(isinstance(call, dict) for call in tool_calls):
            raise LocalAgentError("model_reply_unusable")
        if len(content or "") > MAX_ASSISTANT_TEXT_CHARS or len(reasoning or "") > MAX_ASSISTANT_TEXT_CHARS:
            raise LocalAgentError("model_reply_too_large")
        failure_code = _completion_failure(choice.get("finish_reason"))
        return AgentModelReply(
            content=(content or "").strip(),
            reasoning=(reasoning or "").strip(),
            tool_calls=tool_calls,
            # Whole-response fallbacks need the same visible interrupted state.
            stream_id=uuid.uuid4().hex if failure_code else None,
            stream_status=AgentStreamStatus.FAILED if failure_code else AgentStreamStatus.COMPLETE,
            failure_code=failure_code,
            usage=runtime_usage(reply.get("usage")),
        )

    @staticmethod
    def _prune_completed_deltas(session: AgentSession) -> None:
        """Keep deltas only for the newest live stream, never as transcript history."""

        with session.event_ready:
            completed = {
                event.stream_id
                for event in session.events
                if event.kind == "assistant" and event.stream_id is not None
            }
            if completed:
                session.events[:] = [
                    event
                    for event in session.events
                    if not (event.kind == "assistant_delta" and event.stream_id in completed)
                ]

    def _stream_model_reply(
        self,
        session: AgentSession,
        alias: str,
        body: bytes,
    ) -> tuple[int, AgentModelReply | None]:
        """Consume one OpenAI-compatible SSE response and emit bounded chunks.

        Tool-call deltas are reassembled before the existing approval/tool loop
        sees them. Partial assistant text is display-only until the final
        assistant event is emitted; it is never inserted into model history as
        separate messages.
        """

        if self._open_chat is None:
            status, payload, _ = self._chat(alias, body)
            return status, self._whole_model_reply(payload) if status == 200 else None

        self._prune_completed_deltas(session)
        request = json.loads(body.decode("utf-8"))
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}
        upstream = self._open_chat(alias, json.dumps(request).encode("utf-8"))
        if upstream.status_code != 200:
            return upstream.status_code, None
        if upstream.lines is None:
            if upstream.body is None:
                raise LocalAgentError("model_reply_unusable")
            reply = self._whole_model_reply(upstream.body)
            reply.stream_id = uuid.uuid4().hex
            return upstream.status_code, reply

        stream_id = uuid.uuid4().hex
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        pending = {
            AgentStreamPhase.CONTENT: "",
            AgentStreamPhase.REASONING: "",
        }
        text_lengths = {
            AgentStreamPhase.CONTENT: 0,
            AgentStreamPhase.REASONING: 0,
        }
        last_delta_at = {
            AgentStreamPhase.CONTENT: 0.0,
            AgentStreamPhase.REASONING: 0.0,
        }
        emitted_delta_count = 0
        tool_parts: dict[int, dict[str, str]] = {}
        buffered = b""
        received = 0
        saw_choice = False
        saw_done = False
        finish_reason: str | None = None
        stopped = False
        failure_code: str | None = None
        malformed_tool_delta = False
        tool_call_overflow = False
        usage = RuntimeUsage()

        def emit_delta(phase: AgentStreamPhase, chunk: str) -> None:
            nonlocal emitted_delta_count
            if not chunk or emitted_delta_count >= MAX_STREAM_DELTA_EVENTS:
                return
            self._emit(
                session,
                "assistant_delta",
                text=chunk,
                stream_id=stream_id,
                stream_phase=phase,
            )
            emitted_delta_count += 1
            last_delta_at[phase] = time.monotonic()

        def emit_text(phase: AgentStreamPhase, value: str) -> None:
            if not value:
                return
            if session.active_turn is not None:
                session.active_turn.observe_text()
            if text_lengths[phase] + len(value) > MAX_ASSISTANT_TEXT_CHARS:
                raise LocalAgentError("model_reply_too_large")
            target = content_parts if phase is AgentStreamPhase.CONTENT else reasoning_parts
            target.append(value)
            text_lengths[phase] += len(value)
            pending[phase] += value
            while len(pending[phase]) >= STREAM_EVENT_CHARS:
                chunk = pending[phase][:STREAM_EVENT_CHARS]
                pending[phase] = pending[phase][STREAM_EVENT_CHARS:]
                emit_delta(phase, chunk)
            if pending[phase] and time.monotonic() - last_delta_at[phase] >= 0.1:
                chunk = pending[phase]
                pending[phase] = ""
                emit_delta(phase, chunk)

        def consume_line(raw_line: bytes) -> bool:
            nonlocal malformed_tool_delta, saw_choice, saw_done, finish_reason, tool_call_overflow, usage
            line = raw_line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                return False
            data = line[5:].strip()
            if data == b"[DONE]":
                saw_done = True
                return True
            try:
                decoded = data.decode("utf-8")
                event = model_json_object(decoded, max_characters=MAX_AGENT_STREAM_BYTES) if decoded.lstrip().startswith("{") else None
            except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise LocalAgentError("model_reply_unusable") from None
            if not isinstance(event, dict) or not isinstance(event.get("choices"), list):
                raise LocalAgentError("model_reply_unusable")
            choices = event["choices"]
            if not choices and "usage" in event:
                if not usage.invalid:
                    usage = runtime_usage(event["usage"])
                return False
            if len(choices) != 1 or not isinstance(choices[0], dict):
                raise LocalAgentError("model_reply_unusable")
            choice = choices[0]
            delta = choice.get("delta")
            if delta is None:
                delta = {}
            if not isinstance(delta, dict):
                raise LocalAgentError("model_reply_unusable")
            saw_choice = True
            finish = choice.get("finish_reason")
            if finish is not None:
                if not isinstance(finish, str) or not finish:
                    raise LocalAgentError("model_reply_unusable")
                finish_reason = finish
                if "usage" in event and event["usage"] is not None and not usage.invalid:
                    usage = runtime_usage(event["usage"])
            content = delta.get("content")
            reasoning = delta.get("reasoning_content")
            if content is not None and not isinstance(content, str):
                raise LocalAgentError("model_reply_unusable")
            if reasoning is not None and not isinstance(reasoning, str):
                raise LocalAgentError("model_reply_unusable")
            if isinstance(content, str):
                emit_text(AgentStreamPhase.CONTENT, content)
            if session.settings.parameters.enable_thinking and isinstance(reasoning, str):
                emit_text(AgentStreamPhase.REASONING, reasoning)
            calls = delta.get("tool_calls")
            if calls is None:
                calls = []
            if not isinstance(calls, list):
                raise LocalAgentError("model_reply_unusable")
            if isinstance(calls, list):
                for raw_call in calls:
                    if not isinstance(raw_call, dict):
                        malformed_tool_delta = True
                        continue
                    index = raw_call.get("index", 0)
                    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                        malformed_tool_delta = True
                        continue
                    if index >= MAX_TOOL_CALLS_PER_REPLY:
                        tool_call_overflow = True
                        continue
                    current = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    call_id = raw_call.get("id")
                    function = raw_call.get("function")
                    if function is None:
                        function = {}
                    if call_id is not None and not isinstance(call_id, str):
                        malformed_tool_delta = True
                    if not isinstance(function, dict):
                        malformed_tool_delta = True
                    if isinstance(call_id, str) and call_id:
                        current["id"] = call_id
                    if isinstance(function, dict):
                        name = function.get("name")
                        arguments = function.get("arguments")
                        if name is not None and not isinstance(name, str):
                            malformed_tool_delta = True
                        if arguments is not None and not isinstance(arguments, str):
                            malformed_tool_delta = True
                        if isinstance(name, str) and name:
                            if not current["name"] or name.startswith(current["name"]):
                                current["name"] = name
                            elif name != current["name"]:
                                current["name"] += name
                        if isinstance(arguments, str):
                            current["arguments"] += arguments
            # A finish receipt is terminal on its own. Do not wait indefinitely
            # for a redundant DONE marker or consume later unsolicited deltas.
            return finish_reason is not None

        lines = upstream.lines
        cancel_stream = getattr(upstream, "cancel", None)
        with session.lock:
            session.cancel_stream = cancel_stream if callable(cancel_stream) else None
        try:
            for chunk in lines:
                if session.stop_requested:
                    stopped = True
                    break
                if not isinstance(chunk, bytes):
                    raise LocalAgentError("model_reply_unusable")
                received += len(chunk)
                if received > MAX_AGENT_STREAM_BYTES:
                    raise LocalAgentError("model_reply_too_large")
                buffered += chunk
                while b"\n" in buffered:
                    raw_line, buffered = buffered.split(b"\n", 1)
                    if consume_line(raw_line):
                        buffered = b""
                        break
                else:
                    continue
                break
            if buffered and not stopped:
                consume_line(buffered)
            # The owned runtime may expose a deadline-bounded metadata-only
            # trailer reader. Generic iterators still stop at the finish receipt;
            # no further assistant/tool deltas are consumed or admitted.
            tail = getattr(upstream, "read_usage_tail", None)
            if finish_reason is not None and not stopped and not usage.complete and not usage.invalid and callable(tail):
                try:
                    trailing_usage = tail()
                    if trailing_usage is not None:
                        usage = runtime_usage(trailing_usage)
                except Exception:
                    pass  # a missing telemetry trailer does not undo a completed answer
        except LocalAgentError as error:
            failure_code = error.code
        except Exception:  # noqa: BLE001 - the terminal event carries a fixed safe failure
            failure_code = "model_stream_failed"
        finally:
            with session.lock:
                session.cancel_stream = None
            close = getattr(lines, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - failure is represented below
                    failure_code = failure_code or "model_stream_failed"

        if session.stop_requested:
            stopped = True

        for phase in (AgentStreamPhase.REASONING, AgentStreamPhase.CONTENT):
            if pending[phase]:
                emit_delta(phase, pending[phase])
        tool_calls = [
            {
                "id": item["id"],
                "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"] or "{}"},
            }
            for _, item in sorted(tool_parts.items())
            if item["name"]
        ]
        if any(
            not item["name"]
            or len(item["name"]) > MAX_TOOL_NAME_CHARS
            for item in tool_parts.values()
        ):
            malformed_tool_delta = True
        content = "".join(content_parts).strip()
        reasoning = "".join(reasoning_parts).strip()
        if stopped:
            stream_status = AgentStreamStatus.STOPPED
        else:
            if failure_code is None:
                failure_code = _completion_failure(finish_reason, saw_done=saw_done)
            if failure_code is None and (not saw_choice or malformed_tool_delta):
                failure_code = "model_reply_unusable"
            if failure_code is None and not (content or reasoning or tool_calls):
                failure_code = "model_reply_unusable"
            stream_status = AgentStreamStatus.FAILED if failure_code else AgentStreamStatus.COMPLETE
        return upstream.status_code, AgentModelReply(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            stream_id=stream_id,
            stream_status=stream_status,
            failure_code=failure_code,
            tool_call_overflow=tool_call_overflow,
            usage=usage,
        )

    def _request_body(self, session: AgentSession) -> bytes:
        parameters = session.settings.parameters
        tools = tool_schemas(session.settings)
        if (
            self._mcp_managed_runtime is not None
            and session.settings.project_id is not None
        ):
            try:
                tools.extend(
                    self._mcp_managed_runtime.model_tool_schemas(
                        session.settings.project_id
                    )
                )
            except McpManagedRuntimeError as error:
                raise LocalAgentError(error.code) from None
        return json.dumps({
            "messages": session.messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": parameters.temperature,
            "top_p": parameters.top_p,
            "max_tokens": parameters.max_tokens,
            "chat_template_kwargs": {"enable_thinking": parameters.enable_thinking},
        }).encode("utf-8")

    def _admit_request_context(self, session: AgentSession, alias: str) -> bytes:
        """Fit one request using exact runtime evidence, never an estimated tokenizer.

        The system message, tool schema, current user turn, and its attachments
        are immutable admission inputs. Only whole older conversation units can
        be removed, and every removal is published in the visible event stream.
        """

        with session.lock:
            turn = session.active_turn
        assert turn is not None
        media_omitted = _trim_media_history(session.messages)
        omitted_messages = 0
        body = self._request_body(session)
        # This is a byte-safety boundary, not a token estimate. It protects the
        # authenticated proxy even when an older runtime has no input counter.
        while len(body) > MAX_CHAT_BODY_BYTES:
            removed = _drop_oldest_context_unit(session.messages)
            if removed == 0:
                self._set_context_unmeasured(
                    session,
                    "request_body_too_large",
                    turn=turn,
                )
                raise LocalAgentError("context_window_exceeded")
            omitted_messages += removed
            body = self._request_body(session)

        preflight = self._context_preflight
        if preflight is None:
            self._set_context_unmeasured(
                session,
                "preflight_unavailable",
                turn=turn,
            )
        else:
            while True:
                try:
                    context = preflight(alias, body, omitted_messages)
                except Exception as error:  # noqa: BLE001 - normalize the service seam
                    self._set_context_unmeasured(
                        session,
                        "preflight_failed",
                        turn=turn,
                    )
                    code = getattr(error, "code", None)
                    raise LocalAgentError(
                        code if isinstance(code, str) else "context_preflight_unavailable"
                    ) from None
                self._bind_session_context(session, turn, context)
                if context.state != "known" or context.policy != "exact_refused":
                    break
                removed = _drop_oldest_context_unit(session.messages)
                if removed == 0:
                    raise LocalAgentError("context_window_exceeded")
                omitted_messages += removed
                body = self._request_body(session)

        if omitted_messages:
            self._emit(
                session,
                "status",
                text=(
                    f"Context preflight omitted {omitted_messages} earlier conversation "
                    f"message{'s' if omitted_messages != 1 else ''}; system instructions, "
                    "tool definitions, and the current request were preserved."
                ),
            )
        if media_omitted:
            self._emit(
                session,
                "status",
                text=(
                    f"The bounded media-context policy omitted {media_omitted} earlier "
                    f"attachment{'s' if media_omitted != 1 else ''}; the current request was preserved."
                ),
            )
        return body

    def _run_turn(self, session: AgentSession, alias: str) -> None:
        # Admission publishes the user message only after Thread.start succeeds.
        # Do not let the new thread consume history before that publication.
        with session.lock:
            turn = session.active_turn
            cancellation = session.request_cancelled
        assert turn is not None
        termination, reason = "failed", "turn_failed"
        try:
            for _ in range(session.settings.max_steps):
                if session.stop_requested:
                    termination, reason = "stopped", "stop_requested"
                    self._emit(session, "status", text="Stopped.")
                    break
                parameters = session.settings.parameters
                try:
                    body = self._admit_request_context(session, alias)
                except LocalAgentError as error:
                    if error.code == "context_window_exceeded":
                        reason = "context_window_exceeded"
                        self._emit(
                            session,
                            "error",
                            text=(
                                "This request cannot fit the served model's context window without "
                                "removing the system instructions or your current request. Increase "
                                "the context limit, lower the response-token budget, or start a new chat."
                            ),
                        )
                    else:
                        reason = "runtime_unreachable"
                        self._emit(
                            session,
                            "error",
                            text="The local runtime could not verify this request's context. Retry after refreshing the model runtime.",
                        )
                    break
                reply = None
                turn.begin_request()
                try:
                    with runtime_request_scope(cancellation):
                        status, reply = self._stream_model_reply(session, alias, body)
                except LocalAgentError as error:
                    if session.stop_requested:
                        termination, reason = "stopped", "stop_requested"
                        self._emit(session, "status", text="Stopped.")
                        break
                    reason = "model_reply_too_large" if error.code == "model_reply_too_large" else "runtime_unreachable" if error.code in {"model_not_active", "model_not_ready", "runtime_unreachable"} else "model_reply_unusable"
                    text = (
                        "model reply exceeded the local safety limit"
                        if error.code == "model_reply_too_large"
                        else (
                            "The local model stopped or became unreachable. "
                            "Start the session model, then send the request again."
                            if error.code in {"model_not_active", "model_not_ready", "runtime_unreachable"}
                            else "model reply was not usable"
                        )
                    )
                    self._emit(session, "error", text=text)
                    break
                except Exception as error:  # noqa: BLE001 - reported as an event
                    if session.stop_requested:
                        termination, reason = "stopped", "stop_requested"
                        self._emit(session, "status", text="Stopped.")
                        break
                    reason = "runtime_unreachable"
                    code = getattr(error, "code", None)
                    text = (
                        "The local model stopped or became unreachable. "
                        "Start the session model, then send the request again."
                        if code in {"model_not_active", "model_not_ready", "runtime_unreachable"}
                        else "The local model became unreachable. Check its runtime, then send the request again."
                    )
                    self._emit(session, "error", text=text)
                    break
                finally:
                    turn.end_request(reply.usage if reply is not None else None)
                if session.stop_requested and (status != 200 or reply is None):
                    termination, reason = "stopped", "stop_requested"
                    self._emit(session, "status", text="Stopped.")
                    break
                if status != 200:
                    reason = "runtime_http_error"
                    self._emit(session, "error", text=f"model error (HTTP {status})")
                    break
                if reply is None:
                    reason = "model_reply_unusable"
                    self._emit(session, "error", text="model reply was not usable")
                    break
                if len(reply.tool_calls) > MAX_TOOL_CALLS_PER_REPLY:
                    reply.tool_call_overflow = True
                tool_calls = _normalized_tool_calls(reply.tool_calls)
                content = reply.content
                reasoning = reply.reasoning if parameters.enable_thinking else ""
                # Stop also owns whole-response fallbacks that settle after the
                # request. A reasoning-only generation is not a final answer.
                if session.stop_requested:
                    reply.stream_status = AgentStreamStatus.STOPPED
                    reply.stream_id = reply.stream_id or uuid.uuid4().hex
                elif reply.stream_status is AgentStreamStatus.COMPLETE and not content and not tool_calls:
                    reply.stream_status = AgentStreamStatus.FAILED
                    reply.stream_id = reply.stream_id or uuid.uuid4().hex
                    reply.failure_code = "model_answer_missing" if reasoning else "model_reply_unusable"
                if reply.stream_id is not None:
                    self._emit(
                        session,
                        "assistant",
                        text=content or None,
                        reasoning=reasoning or None,
                        stream_id=reply.stream_id,
                        stream_status=reply.stream_status,
                    )
                elif content or reasoning:
                    self._emit(session, "assistant", text=content or None, reasoning=reasoning or None)
                if reply.stream_status is AgentStreamStatus.STOPPED:
                    termination, reason = "stopped", "stop_requested"
                    self._emit(session, "status", text="Stopped.")
                    break
                if reply.stream_status is AgentStreamStatus.FAILED:
                    reason = reply.failure_code if reply.failure_code in {
                        "model_reply_too_large", "model_stream_incomplete", "model_reply_unusable",
                        "model_answer_missing", "model_response_limit", "model_response_filtered",
                        "model_completion_unrecognized", "model_stream_failed",
                    } else "model_stream_failed"
                    failure_text = {
                        "model_reply_too_large": "model reply exceeded the local safety limit",
                        "model_stream_incomplete": "model stream ended before completion",
                        "model_reply_unusable": "model reply was not usable",
                        "model_answer_missing": (
                            "The model returned reasoning but no final answer or tool request. This turn is "
                            "incomplete. Ask for a smaller step, or start a session with a larger response token budget."
                        ),
                        "model_response_limit": (
                            "The model reached its response token limit before finishing. "
                            "Partial output was not used for tool actions or conversation history. "
                            "Ask for a smaller step, or start a session with a larger response token budget."
                        ),
                        "model_response_filtered": (
                            "The local runtime filtered the response. Partial output was not used for "
                            "tool actions or conversation history. You can revise your request."
                        ),
                        "model_completion_unrecognized": (
                            "The runtime returned an unrecognized completion reason. Partial output was not "
                            "used for tool actions or conversation history. Check the runtime before retrying."
                        ),
                    }.get(reply.failure_code, "model stream failed")
                    self._emit(session, "error", text=failure_text)
                    break
                if not (content or reasoning or tool_calls):
                    reason = "model_reply_unusable"
                    self._emit(session, "error", text="model reply was not usable")
                    break
                if content or tool_calls:
                    session.messages.append({"role": "assistant", "content": content or None, **({"tool_calls": tool_calls} if tool_calls else {})})
                if not tool_calls:
                    termination, reason = "completed", "answer_complete"
                    break
                if reply.tool_call_overflow:
                    self._emit(session, "status", text=f"The model asked for more than {MAX_TOOL_CALLS_PER_REPLY} tool calls at once; only the first {MAX_TOOL_CALLS_PER_REPLY} run.")
                limited_calls = tool_calls[:MAX_TOOL_CALLS_PER_REPLY]
                position = 0
                while position < len(limited_calls):
                    if session.stop_requested:
                        remaining = limited_calls[position:]
                        for skipped in remaining:
                            skipped_id, skipped_name, skipped_arguments, _ = _tool_call_parts(skipped)
                            timer = ToolExecutionReceiptBuilder(
                                monotonic=self._monotonic
                            )
                            self._emit(session, "tool_call", tool=skipped_name, arguments=_safe_arguments(skipped_arguments), call_id=skipped_id)
                            self._record_tool_outcome(
                                session,
                                turn,
                                skipped_id,
                                skipped_name,
                                ToolOutcome(
                                    False,
                                    "cancelled before execution",
                                    "tool_cancelled",
                                ),
                                timer,
                            )
                        break
                    call_id, name, arguments, malformed_arguments = _tool_call_parts(limited_calls[position])
                    if name == ToolName.WRITE_FILE.value and not malformed_arguments:
                        grouped: list[tuple[str, Mapping[str, Any]]] = []
                        cursor = position
                        while cursor < len(limited_calls):
                            grouped_id, grouped_name, grouped_arguments, grouped_malformed = _tool_call_parts(limited_calls[cursor])
                            if grouped_name != ToolName.WRITE_FILE.value or grouped_malformed:
                                break
                            grouped.append((grouped_id, grouped_arguments))
                            cursor += 1
                        if len(grouped) >= 2:
                            grouped_timers: dict[str, ToolExecutionReceiptBuilder] = {}
                            for grouped_id, grouped_arguments in grouped:
                                grouped_timers[grouped_id] = ToolExecutionReceiptBuilder(
                                    monotonic=self._monotonic
                                )
                                self._emit(
                                    session,
                                    "tool_call",
                                    tool=ToolName.WRITE_FILE.value,
                                    arguments=_safe_arguments(grouped_arguments),
                                    call_id=grouped_id,
                                )
                            outcomes = self._execute_write_batch(
                                session,
                                tuple(arguments for _call_id, arguments in grouped),
                            )
                            for (grouped_id, _grouped_arguments), outcome in zip(grouped, outcomes, strict=True):
                                self._record_tool_outcome(
                                    session,
                                    turn,
                                    grouped_id,
                                    ToolName.WRITE_FILE.value,
                                    outcome,
                                    grouped_timers[grouped_id],
                                )
                            position = cursor
                            continue
                    timer = ToolExecutionReceiptBuilder(monotonic=self._monotonic)
                    self._emit(session, "tool_call", tool=name, arguments=_safe_arguments(arguments), call_id=call_id)
                    outcome = (
                        ToolOutcome(False, "model supplied invalid tool arguments")
                        if malformed_arguments
                        else self._execute(
                            session,
                            name,
                            arguments,
                            event_call_id=call_id,
                        )
                    )
                    self._record_tool_outcome(
                        session, turn, call_id, name, outcome, timer
                    )
                    position += 1
                if session.cleanup_unconfirmed:
                    termination, reason = "failed", "command_cleanup_unconfirmed"
                    break
            else:
                if session.stop_requested:
                    termination, reason = "stopped", "stop_requested"
                    self._emit(session, "status", text="Stopped.")
                else:
                    termination, reason = "step_limit", "step_limit"
                    self._emit(session, "status", text="Step limit reached for this turn; send another message to continue.")
        except Exception:
            termination, reason = "failed", "turn_failed"
            self._emit(session, "error", text="The agent turn could not finish. Review the tool receipts before retrying.")
        finally:
            with session.event_ready:
                if session.cleanup_unconfirmed:
                    termination, reason = "failed", "command_cleanup_unconfirmed"
                session.running = False
                session.pending = None
                if (
                    session.context_status.binding_state == "unmeasured"
                    and session.context_status.turn_id == turn.turn_id
                    and session.context_status.unknown_reason == "turn_pending_preflight"
                ):
                    self._set_context_unmeasured(
                        session,
                        "turn_ended_before_preflight",
                        turn=turn,
                    )
                self._emit(session, "done", turn_summary=turn.finish(status=termination, reason=reason, finished_at=self._clock()))
                if not session.history_write_failed:
                    session.recovery_interrupted = False
                session.active_turn = None

    @staticmethod
    def _tool_state_for_outcome(outcome: ToolOutcome) -> AgentToolState:
        return (
            "unverified"
            if (outcome.code or "").endswith("_unverified")
            or outcome.code in {
                "command_cleanup_unconfirmed",
                "mcp_host_cleanup_unconfirmed",
                "mcp_tool_receipt_unavailable",
                "workspace_verification_failed",
                "workspace_transaction_unverified",
                "agent_artifact_relocation_unverified",
                "agent_artifact_relocation_conflict",
                "agent_artifact_relocation_target_conflict",
            }
            or outcome.write_receipt is not None
            and outcome.write_receipt.state == "unverified"
            else "succeeded"
            if outcome.ok
            else "not_approved"
            if outcome.code == "approval_not_granted"
            else "cancelled"
            if outcome.code == "tool_cancelled"
            else "failed"
        )

    @staticmethod
    def _evidence_state_for_outcome(
        name: str,
        outcome: ToolOutcome,
        tool_state: AgentToolState,
    ) -> AgentToolEvidenceState:
        if outcome.approval_state in {
            "not_requested",
            "denied",
            "timed_out",
            "cancelled_before_decision",
        }:
            return "no_effect"
        if name in {
            ToolName.READ_FILE.value,
            ToolName.LIST_DIR.value,
            ToolName.SEARCH_TEXT.value,
        }:
            return "read_only_observation" if outcome.ok else "no_effect"
        if outcome.untracked_command or (
            name == ToolName.FETCH_URL.value
            and outcome.approval_state == "approved"
        ):
            return "untracked_external_effect"
        if name.startswith("mcp_") and outcome.approval_state == "approved":
            # A remote/local MCP call may have changed state even when it timed
            # out, was cancelled, or returned an error. Never infer no effect.
            return "untracked_external_effect"
        if outcome.write_receipt is not None:
            return (
                "verified_workspace_effect"
                if outcome.write_receipt.state == "verified"
                else "unverified_workspace_effect"
            )
        if tool_state == "unverified":
            return "unverified_workspace_effect"
        if outcome.ok and name in {
            ToolName.CREATE_DIRECTORY.value,
            ToolName.MOVE_DIRECTORY.value,
            ToolName.MOVE_FILE.value,
            ToolName.TRASH_FILE.value,
        }:
            return "verified_workspace_effect"
        return "unknown" if outcome.approval_state == "approved" else "no_effect"

    @staticmethod
    def _normalized_approval_state(
        value: AgentToolApprovalState | bool,
    ) -> AgentToolApprovalState:
        # Retain the narrow Boolean fault seam used by transaction tests and
        # older in-process integrations while all public events use the typed
        # state contract.
        if value is True:
            return "approved"
        if value is False:
            return "denied"
        return value

    def _apply_reviewed_write(
        self,
        session: AgentSession,
        prepared: PreparedWrite,
    ) -> ToolOutcome:
        with runtime_request_scope(session.request_cancelled):
            outcome = session.tools.apply_prepared_write(prepared)
        if outcome.write_receipt is not None:
            try:
                coherent = session.changes.observe_agent_write(
                    prepared,
                    outcome.write_receipt,
                )
            except Exception:
                session.changes.mark_failed()
            else:
                if not coherent:
                    return ToolOutcome(
                        False,
                        "write verification receipt did not match the reviewed change",
                        "workspace_verification_failed",
                    )
        elif outcome.ok or outcome.code == "workspace_verification_failed":
            session.changes.mark_failed()
            if outcome.ok:
                return ToolOutcome(
                    False,
                    "write verification receipt was unavailable",
                    "workspace_verification_failed",
                )
        return outcome

    def _record_tool_outcome(
        self,
        session: AgentSession,
        turn: TurnReceiptBuilder,
        call_id: str,
        name: str,
        outcome: ToolOutcome,
        timer: ToolExecutionReceiptBuilder,
    ) -> None:
        tool_state = self._tool_state_for_outcome(outcome)
        execution_receipt = timer.finish(
            approval_state=outcome.approval_state,
            evidence_state=self._evidence_state_for_outcome(
                name, outcome, tool_state
            ),
        )
        turn.tool(tool_state, outcome.write_receipt, outcome.untracked_command)
        self._emit(
            session,
            "tool_result",
            tool=name,
            call_id=call_id,
            ok=outcome.ok,
            tool_state=tool_state,
            write_receipt=outcome.write_receipt,
            execution_receipt=execution_receipt,
            mcp_tool=outcome.mcp_tool,
            mcp_result=outcome.mcp_result,
            text=outcome.text[:MAX_TOOL_RESULT_CHARS],
        )
        session.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": outcome.text[:MAX_TOOL_RESULT_CHARS],
            }
        )

    def _execute_write_batch(
        self,
        session: AgentSession,
        arguments_list: tuple[Mapping[str, Any], ...],
    ) -> tuple[ToolOutcome, ...]:
        """Review consecutive file creates and edits once and publish as a unit."""

        count = len(arguments_list)
        approval_state: AgentToolApprovalState = "not_requested"

        def every(text: str, code: str | None = None) -> tuple[ToolOutcome, ...]:
            return tuple(
                ToolOutcome(
                    False,
                    text,
                    code,
                    approval_state=approval_state,
                )
                for _item in arguments_list
            )

        if not session.settings.allow_writes:
            return every("writes are disabled in this session")
        if self._command_cleanup_unconfirmed.is_set():
            return every(
                "Command cleanup is unconfirmed; further work is blocked.",
                "command_cleanup_unconfirmed",
            )
        if session.stop_requested:
            return every("cancelled before execution", "tool_cancelled")

        tools = session.tools
        normalized_by_path: dict[str, str] = {}
        prepared_by_path: dict[str, PreparedWrite] = {}
        canonical_paths: list[str] = []
        try:
            changes: list[WorkspaceTransactionChangeCommand] = []
            for arguments in arguments_list:
                path = str(arguments.get("path") or "")
                content = str(arguments.get("content") or "")
                normalized = content.replace("\r\n", "\n")
                if "\r" in normalized:
                    raise LocalAgentError("workspace_text_invalid")
                try:
                    current = tools.read_text_snapshot(path)
                except LocalAgentError as error:
                    if error.code != "workspace_path_not_found":
                        raise
                    line_ending = WorkspaceLineEnding.LF
                    disk_content = normalized
                    prepared = tools.prepare_write(path, disk_content)
                    if prepared.existed:
                        raise LocalAgentError("workspace_revision_changed")
                    canonical_path = prepared.path
                    change = WorkspaceTransactionChangeCommand(
                        operation="create",
                        path=canonical_path,
                        content=normalized,
                        line_ending=line_ending,
                    )
                else:
                    line_ending = WorkspaceLineEnding(current.line_ending)
                    disk_content = (
                        normalized.replace("\n", "\r\n")
                        if line_ending is WorkspaceLineEnding.CRLF
                        else normalized
                    )
                    prepared = tools.prepare_write(current.path, disk_content)
                    if (
                        not prepared.existed
                        or prepared.base_sha256 != current.revision
                    ):
                        raise LocalAgentError("workspace_revision_changed")
                    canonical_path = current.path
                    change = WorkspaceTransactionChangeCommand(
                        operation="edit",
                        path=canonical_path,
                        content=normalized,
                        expected_revision=current.revision,
                        line_ending=line_ending,
                    )
                changes.append(change)
                canonical_paths.append(canonical_path)
                normalized_by_path[canonical_path] = normalized
                prepared_by_path[canonical_path] = prepared
            preview_command = WorkspaceTransactionPreviewCommand(
                changes=tuple(changes)
            )
            preview = self._transactions.preview(
                session.session_id,
                tools,
                preview_command,
            )
        except LocalAgentError as error:
            return every(error.code.replace("_", " "), error.code)
        except ValueError:
            return every("workspace transaction arguments are invalid", "workspace_transaction_invalid")
        except Exception:
            return every("workspace transaction preview failed", "workspace_write_failed")

        combined_preview = self._combined_transaction_preview(preview)
        approval_arguments: dict[str, Any] = {
            "file_count": preview.file_count,
            "create_count": sum(item.operation == "create" for item in preview.files),
            "edit_count": sum(item.operation == "edit" for item in preview.files),
            "paths": [item.path for item in preview.files],
            "transaction": "failure_atomic_create_edit",
        }
        approval_state = self._normalized_approval_state(
            self._await_approval(
                session,
                ToolName.WRITE_FILE,
                approval_arguments,
                combined_preview,
            )
        )
        if approval_state != "approved":
            self._transactions.discard(session.session_id, preview.plan_id)
            return every(
                (
                    "native review timed out - the transaction changed no reviewed file"
                    if approval_state == "timed_out"
                    else "cancelled before transaction publication"
                    if approval_state == "cancelled_before_decision"
                    else "denied by the person - the transaction changed no reviewed file"
                ),
                "tool_cancelled"
                if approval_state == "cancelled_before_decision"
                else "approval_not_granted",
            )
        if self._command_cleanup_unconfirmed.is_set():
            self._transactions.discard(session.session_id, preview.plan_id)
            return every(
                "Command cleanup is unconfirmed; the transaction was not started.",
                "command_cleanup_unconfirmed",
            )
        if session.stop_requested:
            self._transactions.discard(session.session_id, preview.plan_id)
            return every("cancelled before transaction publication", "tool_cancelled")

        # Approval can legitimately take longer than the short-lived manual
        # preview capability. Recreate it from the same transient draft and
        # require the full review to be identical before any publication.
        self._transactions.discard(session.session_id, preview.plan_id)
        try:
            refreshed = self._transactions.preview(
                session.session_id,
                tools,
                preview_command,
            )
        except LocalAgentError as error:
            return every(error.code.replace("_", " "), error.code)
        except Exception:
            return every("workspace transaction preview failed", "workspace_write_failed")
        if not self._same_transaction_review(preview, refreshed):
            self._transactions.discard(session.session_id, refreshed.plan_id)
            return every(
                "workspace transaction changed after review",
                "workspace_transaction_changed",
            )
        preview = refreshed

        apply_command = WorkspaceTransactionApplyCommand(
            changes=tuple(
                WorkspaceTransactionApplyChange(
                    operation=item.operation,
                    path=item.path,
                    content=normalized_by_path[item.path],
                    expected_revision=item.expected_revision,
                    proposed_revision=item.proposed_revision,
                    line_ending=item.line_ending,
                )
                for item in preview.files
            ),
            confirmation=WORKSPACE_TRANSACTION_APPLY_CONFIRMATION,
        )
        try:
            with runtime_request_scope(session.request_cancelled):
                result = self._transactions.apply(
                    session.session_id,
                    preview.plan_id,
                    tools,
                    apply_command,
                )
        except RuntimeCooperativeStop:
            return every("transaction cancelled before a verified result", "tool_cancelled")
        except LocalAgentError as error:
            return every(error.code.replace("_", " "), error.code)
        except Exception:
            return every("workspace transaction failed", "workspace_write_failed")

        sorted_outcomes = self._transaction_tool_outcomes(
            session,
            preview,
            result,
            prepared_by_path,
        )
        outcome_by_path = {
            item.path: outcome
            for item, outcome in zip(preview.files, sorted_outcomes, strict=True)
        }
        outcomes = tuple(outcome_by_path[path] for path in canonical_paths)
        if len(outcomes) != count:
            return every("transaction result count was invalid", "workspace_transaction_unverified")
        return tuple(
            replace(outcome, approval_state=approval_state)
            for outcome in outcomes
        )

    def _execute_managed_mcp(
        self,
        session: AgentSession,
        name: str,
        arguments: Mapping[str, Any],
        *,
        event_call_id: str,
    ) -> ToolOutcome:
        runtime = self._mcp_managed_runtime
        project_id = session.settings.project_id
        turn = session.active_turn
        if runtime is None or project_id is None or turn is None:
            return ToolOutcome(False, f"unknown tool: {name}")
        approval_state: AgentToolApprovalState = "not_requested"
        descriptor: AgentMcpToolDescriptor | None = None
        try:
            prepared = runtime.prepare_tool_call(
                project_id=project_id,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                model_alias=name,
                arguments=arguments,
            )
            descriptor = AgentMcpToolDescriptor(
                server_title=prepared.server_title,
                tool_name=prepared.tool.name,
                tool_title=prepared.tool.title,
                model_alias=name,
            )
            approval_state = self._normalized_approval_state(
                self._await_approval(
                    session,
                    name,
                    {},
                    prepared.preview,
                    event_call_id=event_call_id,
                    mcp_tool=descriptor,
                    approval_id=prepared.approval_id,
                )
            )
            projection = runtime.settle_tool_call(
                prepared,
                approval_state=approval_state,
                cancelled=session.request_cancelled,
            )
        except McpManagedRuntimeError as error:
            return ToolOutcome(
                False,
                error.code.replace("_", " "),
                error.code,
                approval_state=approval_state,
                mcp_tool=descriptor,
            )
        except Exception:
            return ToolOutcome(
                False,
                "managed MCP runtime unavailable",
                "mcp_managed_runtime_unavailable",
                approval_state=approval_state,
                mcp_tool=descriptor,
            )

        result_receipt = AgentMcpToolResultReceipt(
            managed_call_id=projection.call_id,
            outcome=(
                "not_invoked"
                if approval_state != "approved"
                else projection.outcome
            ),
            content_mode=(
                "none"
                if approval_state != "approved"
                else projection.content_mode
            ),
            result_bytes=(
                0 if approval_state != "approved" else projection.result_bytes
            ),
            result_digest=(
                None
                if approval_state != "approved"
                else projection.result_digest
            ),
            error_code=(
                None
                if approval_state != "approved"
                else projection.error_code
            ),
            cleanup_verified=(
                True
                if approval_state != "approved"
                else projection.cleanup_verified
            ),
        )

        if approval_state != "approved":
            code = (
                "tool_cancelled"
                if approval_state == "cancelled_before_decision"
                else "approval_not_granted"
            )
            return ToolOutcome(
                False,
                projection.text,
                code,
                approval_state=approval_state,
                mcp_tool=descriptor,
                mcp_result=result_receipt,
            )
        code = (
            None
            if projection.outcome == "succeeded"
            else "mcp_tool_reported_error"
            if projection.outcome == "tool_error"
            else "tool_cancelled"
            if projection.outcome == "cancelled"
            else projection.error_code or "mcp_tool_call_failed"
        )
        return ToolOutcome(
            projection.outcome == "succeeded",
            projection.text,
            code,
            approval_state=approval_state,
            mcp_tool=descriptor,
            mcp_result=result_receipt,
        )

    def _execute(
        self,
        session: AgentSession,
        name: str,
        arguments: Mapping[str, Any],
        *,
        event_call_id: str | None = None,
    ) -> ToolOutcome:
        approval_state: AgentToolApprovalState = "not_requested"

        def settled(outcome: ToolOutcome) -> ToolOutcome:
            return replace(outcome, approval_state=approval_state)

        try:
            tool = ToolName(name)
        except ValueError:
            if event_call_id is None:
                return ToolOutcome(
                    False,
                    "managed MCP call identity is unavailable",
                    "mcp_tool_activity_invalid",
                )
            return self._execute_managed_mcp(
                session,
                name,
                arguments,
                event_call_id=event_call_id,
            )
        tools = session.tools
        command_started = False
        try:
            if tool in {ToolName.READ_FILE, ToolName.LIST_DIR, ToolName.SEARCH_TEXT}:
                approval_state = "not_required"
                with runtime_request_scope(session.request_cancelled):
                    if tool is ToolName.READ_FILE:
                        return settled(
                            tools.read_file(str(arguments.get("path") or ""))
                        )
                    if tool is ToolName.LIST_DIR:
                        return settled(
                            tools.list_dir(
                                str(arguments.get("path") or "."),
                                int(arguments.get("depth") or 1),
                            )
                        )
                    return settled(
                        tools.search_text(
                            str(arguments.get("query") or ""),
                            str(arguments.get("glob") or "**/*"),
                            bool(arguments.get("regex")),
                        )
                    )
            if tool in {
                ToolName.WRITE_FILE,
                ToolName.CREATE_DIRECTORY,
                ToolName.MOVE_DIRECTORY,
                ToolName.MOVE_FILE,
                ToolName.TRASH_FILE,
            } and not session.settings.allow_writes:
                return settled(
                    ToolOutcome(False, "writes are disabled in this session")
                )
            if tool is ToolName.RUN_COMMAND and not session.settings.allow_commands:
                return settled(
                    ToolOutcome(False, "commands are disabled in this session")
                )
            if tool is ToolName.FETCH_URL and not session.settings.allow_web:
                return settled(
                    ToolOutcome(False, "web access is disabled in this session")
                )
            preview = None
            prepared_write: PreparedWrite | None = None
            directory_preview: WorkspaceDirectoryCreatePreview | None = None
            directory_move_preview: WorkspaceDirectoryMovePreview | None = None
            move_preview: WorkspaceMovePreview | None = None
            move_baseline: WorkspaceTextSnapshot | None = None
            trash_preview: WorkspaceFileTrashPreview | None = None
            trash_baseline: WorkspaceTextSnapshot | None = None
            if tool is ToolName.WRITE_FILE:
                prepared_write = tools.prepare_write(
                    str(arguments.get("path") or ""),
                    str(arguments.get("content") or ""),
                )
                preview = prepared_write.preview
            elif tool is ToolName.CREATE_DIRECTORY:
                directory_preview = self._file_lifecycle.preview_directory_create(
                    session.session_id,
                    tools,
                    WorkspaceDirectoryCreatePreviewCommand(
                        path=str(arguments.get("path") or "")
                    ),
                )
                preview = (
                    "Create directory\n"
                    f"Path: {directory_preview.path}\n"
                    "The parent must already exist. Nothing may be overwritten."
                )
            elif tool is ToolName.MOVE_DIRECTORY:
                directory_move_preview = self._file_lifecycle.preview_directory_move(
                    session.session_id,
                    tools,
                    WorkspaceDirectoryMovePreviewCommand(
                        source_path=str(arguments.get("source_path") or ""),
                        target_path=str(arguments.get("target_path") or ""),
                    ),
                )
                preview = (
                    "Move directory without overwrite\n"
                    f"From: {directory_move_preview.source_path}\n"
                    f"To: {directory_move_preview.target_path}\n"
                    "Path topology only: contents are moved but are not enumerated or reviewed."
                )
            elif tool is ToolName.MOVE_FILE:
                source_path = str(arguments.get("source_path") or "")
                target_path = str(arguments.get("target_path") or "")
                move_baseline = tools.read_text_snapshot(source_path)
                move_preview = self._file_lifecycle.preview_move(
                    session.session_id,
                    tools,
                    WorkspaceMovePreviewCommand(
                        source_path=source_path,
                        target_path=target_path,
                        expected_revision=move_baseline.revision,
                    ),
                )
                preview = (
                    "Move file without overwrite\n"
                    f"From: {move_preview.source_path}\n"
                    f"To: {move_preview.target_path}\n"
                    f"Reviewed bytes: {move_preview.byte_size}\n"
                    f"Revision: {move_preview.expected_revision}"
                )
            elif tool is ToolName.TRASH_FILE:
                path = str(arguments.get("path") or "")
                trash_baseline = tools.read_text_snapshot(path)
                trash_preview = self._file_lifecycle.preview_file_trash(
                    session.session_id,
                    tools,
                    WorkspaceFileTrashPreviewCommand(
                        path=path,
                        expected_revision=trash_baseline.revision,
                    ),
                )
                preview = (
                    "Move file to Windows Recycle Bin\n"
                    f"Path: {trash_preview.path}\n"
                    f"Reviewed bytes: {trash_preview.byte_size}\n"
                    f"Revision: {trash_preview.expected_revision}\n"
                    "Permanent deletion: no. Recovery is through Windows Recycle Bin."
                )
            if tool is ToolName.RUN_COMMAND and len(str(arguments.get("command") or "")) > MAX_REVIEWABLE_COMMAND_CHARS:
                return settled(
                    ToolOutcome(
                        False,
                        "command too long to review; split it into smaller commands",
                    )
                )
            approval_state = self._normalized_approval_state(
                self._await_approval(session, tool, arguments, preview)
            )
            if approval_state != "approved":
                for pending_preview in (
                    directory_preview,
                    directory_move_preview,
                    move_preview,
                    trash_preview,
                ):
                    if pending_preview is not None:
                        self._file_lifecycle.discard_preview(
                            session.session_id, pending_preview.preview_id
                        )
                message = {
                    "timed_out": (
                        "native review timed out - do not retry this call without "
                        "a new request"
                    ),
                    "cancelled_before_decision": "cancelled before execution",
                }.get(
                    approval_state,
                    "denied by the person - do not retry this call; explain or choose another approach",
                )
                return settled(
                    ToolOutcome(
                        False,
                        message,
                        "tool_cancelled"
                        if approval_state == "cancelled_before_decision"
                        else "approval_not_granted",
                    )
                )
            if self._command_cleanup_unconfirmed.is_set():
                for pending_preview in (
                    directory_preview,
                    directory_move_preview,
                    move_preview,
                    trash_preview,
                ):
                    if pending_preview is not None:
                        self._file_lifecycle.discard_preview(
                            session.session_id, pending_preview.preview_id
                        )
                return settled(
                    ToolOutcome(
                        False,
                        "Command cleanup is unconfirmed; further work is blocked.",
                        "command_cleanup_unconfirmed",
                    )
                )
            if session.stop_requested:
                for pending_preview in (
                    directory_preview,
                    directory_move_preview,
                    move_preview,
                    trash_preview,
                ):
                    if pending_preview is not None:
                        self._file_lifecycle.discard_preview(
                            session.session_id, pending_preview.preview_id
                        )
                return settled(
                    ToolOutcome(False, "cancelled before execution", "tool_cancelled")
                )
            if tool is ToolName.WRITE_FILE:
                if prepared_write is None:
                    return settled(
                        ToolOutcome(False, "write preview was unavailable")
                    )
                return settled(self._apply_reviewed_write(session, prepared_write))
            if tool is ToolName.CREATE_DIRECTORY:
                if directory_preview is None:
                    return settled(
                        ToolOutcome(False, "directory review was unavailable")
                    )
                with runtime_request_scope(session.request_cancelled):
                    result = self._file_lifecycle.apply_directory_create(
                        session.session_id,
                        directory_preview.preview_id,
                        tools,
                        WorkspaceDirectoryCreateApplyCommand(
                            path=directory_preview.path,
                            confirmation=WORKSPACE_DIRECTORY_CREATE_CONFIRMATION,
                        ),
                    )
                return settled(
                    ToolOutcome(True, f"created directory {result.path}")
                )
            if tool is ToolName.MOVE_DIRECTORY:
                if directory_move_preview is None:
                    return settled(
                        ToolOutcome(False, "directory move review was unavailable")
                    )
                with runtime_request_scope(session.request_cancelled):
                    result = self._file_lifecycle.apply_directory_move(
                        session.session_id,
                        directory_move_preview.preview_id,
                        tools,
                        WorkspaceDirectoryMoveApplyCommand(
                            source_path=directory_move_preview.source_path,
                            target_path=directory_move_preview.target_path,
                            confirmation=WORKSPACE_DIRECTORY_MOVE_CONFIRMATION,
                        ),
                    )
                return settled(
                    ToolOutcome(
                        True,
                        f"moved directory {result.source_path} to {result.target_path}; contents were not reviewed",
                    )
                )
            if tool is ToolName.MOVE_FILE:
                if move_preview is None or move_baseline is None:
                    return settled(
                        ToolOutcome(False, "move review was unavailable")
                    )
                try:
                    with runtime_request_scope(session.request_cancelled):
                        result = self._file_lifecycle.apply_move(
                            session.session_id,
                            move_preview.preview_id,
                            tools,
                            WorkspaceMoveApplyCommand(
                                source_path=move_preview.source_path,
                                target_path=move_preview.target_path,
                                expected_revision=move_preview.expected_revision,
                                confirmation=WORKSPACE_MOVE_CONFIRMATION,
                            ),
                        )
                except LocalAgentError as error:
                    if error.code == "workspace_move_unverified":
                        try:
                            session.changes.observe_agent_move_unverified(
                                move_baseline,
                                source_path=move_preview.source_path,
                                target_path=move_preview.target_path,
                            )
                        except Exception:
                            session.changes.mark_failed()
                    raise
                try:
                    coherent = session.changes.observe_agent_moved(
                        move_baseline, result
                    )
                except Exception:
                    session.changes.mark_failed()
                    coherent = False
                if not coherent:
                    return settled(
                        ToolOutcome(
                            False,
                            "move verification receipt did not match the reviewed change",
                            "workspace_verification_failed",
                        )
                    )
                self._relocate_artifact_after_move(session, result)
                return settled(
                    ToolOutcome(
                        True,
                        f"moved {result.source_path} to {result.target_path} without overwrite",
                    )
                )
            if tool is ToolName.TRASH_FILE:
                if trash_preview is None or trash_baseline is None:
                    return settled(
                        ToolOutcome(False, "Recycle Bin review was unavailable")
                    )
                try:
                    with runtime_request_scope(session.request_cancelled):
                        result = self._file_lifecycle.apply_file_trash(
                            session.session_id,
                            trash_preview.preview_id,
                            tools,
                            WorkspaceFileTrashApplyCommand(
                                path=trash_preview.path,
                                expected_revision=trash_preview.expected_revision,
                                confirmation=WORKSPACE_FILE_TRASH_CONFIRMATION,
                            ),
                        )
                except LocalAgentError as error:
                    if error.code == "workspace_file_trash_unverified":
                        try:
                            session.changes.observe_agent_trash_unverified(
                                trash_baseline,
                                path=trash_preview.path,
                            )
                        except Exception:
                            session.changes.mark_failed()
                    raise
                try:
                    coherent = session.changes.observe_agent_trashed(
                        trash_baseline, result
                    )
                except Exception:
                    session.changes.mark_failed()
                    coherent = False
                if not coherent:
                    return settled(
                        ToolOutcome(
                            False,
                            "Recycle Bin receipt did not match the reviewed file",
                            "workspace_file_trash_unverified",
                        )
                    )
                return settled(
                    ToolOutcome(
                        True,
                        f"moved {result.path} to Windows Recycle Bin; permanent deletion was not used",
                    )
                )
            if tool is ToolName.RUN_COMMAND:
                command_started = True
                with runtime_request_scope(session.request_cancelled):
                    outcome = tools.run_command(str(arguments.get("command") or ""), arguments.get("timeout_seconds"))
                if outcome.code == "command_cleanup_unconfirmed":
                    self._quarantine_commands()
                if outcome.untracked_command:
                    session.changes.observe_command()
                return settled(outcome)
            return settled(tools.fetch_url(str(arguments.get("url") or "")))
        except RuntimeCooperativeStop:
            return settled(
                ToolOutcome(
                    False, "workspace inspection cancelled", "tool_cancelled"
                )
            )
        except LocalAgentError as error:
            outcome = ToolOutcome(False, error.code.replace("_", " "), error.code, untracked_command=command_started)
            if outcome.untracked_command:
                session.changes.observe_command()
            return settled(outcome)
        except Exception as error:  # noqa: BLE001 - the loop must survive any tool failure
            outcome = ToolOutcome(False, f"tool failed: {error.__class__.__name__}", untracked_command=command_started)
            if outcome.untracked_command:
                session.changes.observe_command()
            return settled(outcome)

    def _await_approval(
        self,
        session: AgentSession,
        tool: ToolName | str,
        arguments: Mapping[str, Any],
        preview: str | None,
        *,
        event_call_id: str | None = None,
        mcp_tool: AgentMcpToolDescriptor | None = None,
        approval_id: str | None = None,
    ) -> AgentToolApprovalState:
        identifier = approval_id or uuid.uuid4().hex
        if len(identifier) != 32 or any(
            character not in "0123456789abcdef" for character in identifier
        ):
            raise LocalAgentError("approval_identity_invalid")
        approval = PendingApproval(
            approval_id=identifier,
            tool=tool,
            arguments=dict(arguments),
        )
        with session.lock:
            if session.stop_requested:
                return "cancelled_before_decision"
            session.pending = approval
        tool_name = _tool_value(tool)
        self._emit(
            session,
            "approval_required",
            tool=tool_name,
            arguments=_safe_arguments(arguments),
            call_id=event_call_id,
            approval_id=approval.approval_id,
            preview=preview,
            mcp_tool=mcp_tool,
        )
        decided = approval.decided.wait(self._approval_wait)
        with session.lock:
            session.pending = None
        decision_approved = bool(decided and approval.approved)
        self._emit(
            session,
            "approval_resolved",
            tool=tool_name,
            call_id=event_call_id,
            approval_id=approval.approval_id,
            ok=decision_approved,
            text=None if decided else "no decision in time; treated as denied",
            mcp_tool=mcp_tool,
        )
        if not decided:
            return "timed_out"
        if approval.approved:
            return "approved"
        if session.stop_requested:
            return "cancelled_before_decision"
        return "denied"


def _drop_oldest_context_unit(messages: list[dict[str, Any]]) -> int:
    """Remove one whole completed unit while preserving system/current request.

    Conversation units are bounded by user messages. This keeps assistant tool
    calls adjacent to all of their tool results and never removes the newest
    user message or anything after it.
    """

    if len(messages) < 3 or messages[0].get("role") != "system":
        return 0
    protected_prefix = 1
    while (
        protected_prefix < len(messages)
        and messages[protected_prefix].get("role") == "system"
    ):
        protected_prefix += 1
    user_indexes = [
        index for index, message in enumerate(messages[protected_prefix:], start=protected_prefix)
        if message.get("role") == "user"
    ]
    if len(user_indexes) < 2:
        return 0
    boundary = user_indexes[1]
    if boundary <= protected_prefix or boundary > user_indexes[-1]:
        return 0
    removed = boundary - protected_prefix
    del messages[protected_prefix:boundary]
    return removed


def _trim_media_history(messages: list[dict[str, Any]]) -> int:
    """Keep the newest bounded media context and replace older payloads honestly."""

    encoded_budget = (MAX_AGENT_ATTACHMENT_MESSAGE_BYTES * 4 // 3) + 262_144
    used = 0
    omitted = 0
    for message in reversed(messages[1:]):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        bounded: list[dict[str, object]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            encoded: str | None = None
            if kind == "image_url":
                image = part.get("image_url")
                if isinstance(image, dict) and isinstance(image.get("url"), str):
                    encoded = image["url"]
            elif kind == "input_audio":
                audio = part.get("input_audio")
                if isinstance(audio, dict) and isinstance(audio.get("data"), str):
                    encoded = audio["data"]
            if encoded is None:
                bounded.append(part)
                continue
            if used + len(encoded) <= encoded_budget:
                used += len(encoded)
                bounded.append(part)
            else:
                label = "image" if kind == "image_url" else "audio"
                omitted += 1
                bounded.append({
                    "type": "text",
                    "text": f"[Earlier local {label} attachment omitted from this request by the bounded media-context policy.]",
                })
        message["content"] = bounded
    return omitted


def _safe_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Arguments for the event stream: strings bounded so a huge file write does not flood the UI."""

    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 4_000:
            out[str(key)] = value[:4_000] + f"… ({len(value)} chars)"
        else:
            out[str(key)] = value
    return out


def _normalized_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every model-emitted call one stable ID before it enters history."""

    normalized: list[dict[str, Any]] = []
    for call in calls[:MAX_TOOL_CALLS_PER_REPLY]:
        copied = dict(call)
        call_id = copied.get("id")
        if not isinstance(call_id, str) or not call_id or len(call_id) > MAX_CALL_ID_CHARS or not call_id.isprintable():
            call_id = hashlib.md5(json.dumps(copied, sort_keys=True, default=str).encode()).hexdigest()[:12]  # noqa: S324
        copied["id"] = call_id
        function = copied.get("function")
        if isinstance(function, Mapping):
            normalized_function = dict(function)
            name = normalized_function.get("name")
            if not isinstance(name, str) or len(name) > MAX_TOOL_NAME_CHARS or not name.isprintable():
                normalized_function["name"] = ""
            copied["function"] = normalized_function
        normalized.append(copied)
    return normalized


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = child
    return value


def _reject_nonfinite_json(_value: str) -> Any:
    raise ValueError("non-finite JSON number")


def _tool_call_parts(call: Mapping[str, Any]) -> tuple[str, str, dict[str, Any], bool]:
    call_id = str(call.get("id") or "")
    function = call.get("function")
    if not isinstance(function, Mapping):
        return call_id, "", {}, True
    name = function.get("name")
    raw_arguments = function.get("arguments")
    malformed = (
        not isinstance(name, str)
        or not name
        or len(name) > MAX_TOOL_NAME_CHARS
        or not name.isprintable()
        or not isinstance(raw_arguments, str)
    )
    if (
        isinstance(name, str)
        and name.startswith("mcp_")
        and isinstance(raw_arguments, str)
    ):
        try:
            malformed = malformed or (
                len(raw_arguments.encode("utf-8")) > MAX_MCP_MANAGED_ARGUMENT_BYTES
            )
        except UnicodeEncodeError:
            malformed = True
    try:
        arguments = (
            json.loads(
                raw_arguments or "{}",
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_nonfinite_json,
            )
            if isinstance(raw_arguments, str) and not malformed
            else {}
        )
        if not isinstance(arguments, dict):
            malformed = True
            arguments = {}
    except (TypeError, ValueError):
        malformed = True
        arguments = {}
    return call_id, str(name or ""), arguments, malformed


__all__ = (
    "AGENT_CONTRACT_VERSION",
    "AGENT_LIFECYCLE_PROPOSAL_CONTRACT_VERSION",
    "AGENT_WRITE_PROPOSAL_CONTRACT_VERSION",
    "AGENT_WRITE_TRANSACTION_PROPOSAL_CONTRACT_VERSION",
    "APPROVAL_TOOLS",
    "SAFE_TOOLS",
    "AgentEvent",
    "AgentModelParameters",
    "AgentEvents",
    "AgentLifecycleProposal",
    "AgentLifecycleProposalOperation",
    "AgentLifecycleProposalReceipt",
    "AgentLifecycleProposalState",
    "AgentSessionView",
    "AgentSettings",
    "AgentWriteProposal",
    "AgentWriteProposalReceipt",
    "AgentWriteProposalState",
    "AgentWriteTransactionProposal",
    "AgentWriteTransactionProposalFile",
    "AgentWriteTransactionProposalReceipt",
    "AgentWriteTransactionProposalState",
    "ApprovalDecision",
    "LocalAgentError",
    "LocalAgentService",
    "RevalidateAgentAuthority",
    "SendMessage",
    "SwitchAgentSessionModel",
    "ToolName",
    "WorkspaceTools",
    "minimal_environment",
    "run_with_tree_kill",
    "tool_schemas",
)
