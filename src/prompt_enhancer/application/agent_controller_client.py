"""Bounded provider-neutral client for the loopback Agent controller API.

The client owns and spawns no process. It never starts Prompt Enhancer, Codex,
Claude, another agent, or a shell. An explicit runtime request can ask the
already-running Prompt Enhancer service to switch or stop its one owned model
runtime. Native review gates remain unavailable to the controller.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import time
from typing import Any, Literal, Protocol
from urllib.parse import quote

from pydantic import Field, ValidationError, field_validator, model_validator

from ..domain import StrictModel
from .agent_orchestration import (
    AgentOrchestrationEndpoint,
    AgentOrchestrationManifest,
)
from .agent_attachment_contracts import (
    MAX_AGENT_ATTACHMENT_BASE64_CHARS,
    AgentAttachment,
    StageInlineAgentAttachment,
)
from .agent_catalog import (
    MAX_AGENT_HISTORY_EVENTS,
    AgentCatalogSessionRecord,
    AgentHistoryExport,
    AgentProjectRecord,
    AgentRetentionPolicy,
    CreateAgentProject,
    AgentSessionForkReceipt,
    ForkAgentSession,
    ResumeAgentSession,
    StoredAgentEvent,
)
from .local_agent import (
    AgentEvent,
    AgentEvents,
    AgentLifecycleProposal,
    AgentLifecycleProposalReceipt,
    AgentSessionView,
    AgentSettings,
    AgentWriteProposal,
    AgentWriteProposalReceipt,
    AgentWriteTransactionProposal,
    AgentWriteTransactionProposalReceipt,
    SendMessage,
)
from .local_models import (
    DeviceMode,
    LocalRuntimeCoordinatorStatus,
    MAX_CONTEXT_SIZE,
    RuntimeCleanupState,
    RuntimeCoordinatorState,
    StopLocalRuntime,
    SwitchLocalRuntime,
)


AGENT_CONTROLLER_CLI_CONTRACT = "prompt-enhancer-agent-controller-cli.v5"
AGENT_CONTROLLER_CLOSE_CONTRACT = "prompt-enhancer-agent-controller-close.v1"
AGENT_CONTROLLER_EXPORT_CONTRACT = "prompt-enhancer-agent-controller-export.v1"
AGENT_CONTROLLER_FORK_CONTRACT = "prompt-enhancer-agent-controller-fork.v1"
AGENT_CONTROLLER_OPEN_CONTRACT = "prompt-enhancer-agent-controller-open.v1"
AGENT_CONTROLLER_RESUME_CONTRACT = "prompt-enhancer-agent-controller-resume.v1"
AGENT_CONTROLLER_RUNTIME_CONTRACT = "prompt-enhancer-agent-controller-runtime.v1"
AGENT_CONTROLLER_TURN_CONTRACT = "prompt-enhancer-agent-controller-turn.v2"
AGENT_CONTROLLER_STOP_CONTRACT = "prompt-enhancer-agent-controller-stop.v1"
MAX_CONTROLLER_REQUEST_BYTES = 4 * 1024 * 1024
MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES = MAX_AGENT_ATTACHMENT_BASE64_CHARS + 4_096
MAX_CONTROLLER_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_CONTROLLER_TURN_EVENTS = 2_000
_PATH_PARAMETER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_QUERY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class AgentControllerError(RuntimeError):
    """A content-free controller failure safe to expose to a caller."""

    def __init__(
        self,
        code: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable


class AgentControllerTransportUnavailable(AgentControllerError):
    """The loopback exchange ended without a trustworthy HTTP response."""

    def __init__(self) -> None:
        super().__init__("controller_transport_unavailable", retryable=True)


@dataclass(frozen=True, slots=True)
class AgentControllerHttpResponse:
    status_code: int
    content_type: str | None
    body: bytes


class AgentControllerTransport(Protocol):
    """Minimal transport boundary, replaceable by synthetic fixtures."""

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | int | bool] | None = None,
        json_body: Any | None = None,
        max_request_bytes: int = MAX_CONTROLLER_REQUEST_BYTES,
    ) -> AgentControllerHttpResponse: ...


class AgentControllerInvokeRequest(StrictModel):
    operation: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    path_parameters: dict[str, str] = Field(default_factory=dict, max_length=12)
    query: dict[str, str | int | bool] = Field(default_factory=dict, max_length=32)
    body: dict[str, Any] | None = None

    @field_validator("path_parameters")
    @classmethod
    def validate_path_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if _QUERY_KEY.fullmatch(key) is None:
                raise ValueError("controller path-parameter key is invalid")
            if (
                not item
                or len(item) > 1_024
                or any(character in item for character in ("/", "\\", "?", "#", "\r", "\n", "\x00"))
            ):
                raise ValueError("controller path-parameter value is invalid")
        return value

    @field_validator("query")
    @classmethod
    def validate_query(
        cls, value: dict[str, str | int | bool]
    ) -> dict[str, str | int | bool]:
        for key, item in value.items():
            if _QUERY_KEY.fullmatch(key) is None:
                raise ValueError("controller query key is invalid")
            if isinstance(item, str) and (
                len(item) > 4_096
                or any(character in item for character in ("\r", "\n", "\x00"))
            ):
                raise ValueError("controller query value is invalid")
        return value

    @model_validator(mode="after")
    def validate_serialized_size(self) -> "AgentControllerInvokeRequest":
        try:
            serialized = json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("controller request is not JSON serializable") from error
        if len(serialized) > MAX_CONTROLLER_REQUEST_BYTES:
            raise ValueError("controller request is too large")
        return self


class AgentControllerInvocationResult(StrictModel):
    operation: str
    status_code: int = Field(ge=100, le=599)
    response: Any | None = None


class AgentControllerAttachmentStageRequest(StrictModel):
    """Stage one caller-owned media payload into one exact project/chat."""

    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    attachment: StageInlineAgentAttachment


class AgentControllerTurnRequest(StrictModel):
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    message: SendMessage


class AgentControllerWriteProposalRequest(StrictModel):
    """Submit one caller-authored write for native diff review, never apply."""

    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    proposal: AgentWriteProposal


class AgentControllerWriteTransactionProposalRequest(StrictModel):
    """Submit one existing-file change set for native review, never apply."""

    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    proposal: AgentWriteTransactionProposal


class AgentControllerLifecycleProposalRequest(StrictModel):
    """Submit one path lifecycle proposal for native review, never apply."""

    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    proposal: AgentLifecycleProposal


class AgentControllerWaitRequest(StrictModel):
    """Observe one already-submitted turn without sending or stopping it."""

    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    after: int = Field(strict=True, ge=0)


class AgentControllerStopRequest(StrictModel):
    """Stop or reconcile one exact live turn from a caller-owned cursor."""

    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    after: int = Field(strict=True, ge=0)


class AgentControllerOpenChatRequest(StrictModel):
    """Open one live chat in an existing or newly created durable project."""

    project_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    project_name: str | None = Field(default=None, min_length=1, max_length=120)
    settings: AgentSettings

    @field_validator("project_name")
    @classmethod
    def normalize_project_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("project name must contain visible text")
        return normalized

    @model_validator(mode="after")
    def validate_project_source(self) -> "AgentControllerOpenChatRequest":
        if (self.project_id is None) is (self.project_name is None):
            raise ValueError("exactly one project source is required")
        if self.settings.project_id is not None:
            raise ValueError("settings project identity is injected by the controller")
        return self


class AgentControllerResumeChatRequest(StrictModel):
    """Revision-bound durable-chat recovery without protected authority."""

    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_catalog_revision: int = Field(strict=True, ge=1)
    expected_history_revision: int = Field(strict=True, ge=0)


class AgentControllerForkChatRequest(StrictModel):
    """Idempotent, revision-bound retained-history branch request."""

    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_catalog_revision: int = Field(strict=True, ge=1)
    expected_history_revision: int = Field(strict=True, ge=0)
    destination_project_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )
    through_event_seq: int | None = Field(default=None, strict=True, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("fork title must contain visible text")
        return normalized

    def command(self) -> ForkAgentSession:
        return ForkAgentSession(
            request_id=self.request_id,
            expected_catalog_revision=self.expected_catalog_revision,
            expected_history_revision=self.expected_history_revision,
            destination_project_id=self.destination_project_id,
            through_event_seq=self.through_event_seq,
            title=self.title,
        )


class AgentControllerExportChatRequest(StrictModel):
    """Exact-revision bounded retained-history export request."""

    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_catalog_revision: int = Field(strict=True, ge=1)
    expected_history_revision: int = Field(strict=True, ge=0)
    max_events: int = Field(
        default=1_000,
        strict=True,
        ge=0,
        le=MAX_AGENT_HISTORY_EVENTS,
    )


class AgentControllerCloseChatRequest(StrictModel):
    """Close one exact idle live chat without deleting its durable record."""

    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_catalog_revision: int = Field(strict=True, ge=1)
    expected_history_revision: int = Field(strict=True, ge=0)


ControllerOpenOutcome = Literal[
    "ready",
    "session_creation_uncertain",
    "project_cleanup_unconfirmed",
]


class AgentControllerOpenChatResult(StrictModel):
    contract_version: Literal["prompt-enhancer-agent-controller-open.v1"] = (
        AGENT_CONTROLLER_OPEN_CONTRACT
    )
    outcome: ControllerOpenOutcome
    project: AgentProjectRecord
    project_created: bool
    session: AgentSessionView | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "AgentControllerOpenChatResult":
        if (self.outcome == "ready") is (self.session is None):
            raise ValueError("only a ready open-chat result carries a session")
        if self.outcome == "project_cleanup_unconfirmed" and not self.project_created:
            raise ValueError("cleanup uncertainty requires a newly created project")
        return self


ControllerResumeOutcome = Literal[
    "resumed",
    "already_live",
    "resumed_reconciled",
    "resume_uncertain",
    "cleanup_unconfirmed",
]
ControllerResumeMutationState = Literal[
    "not_attempted",
    "accepted",
    "reconciled",
    "uncertain",
]


class AgentControllerResumeChatResult(StrictModel):
    """Identity-bound outcome for one at-most-once retained-chat resume."""

    contract_version: Literal["prompt-enhancer-agent-controller-resume.v1"] = (
        AGENT_CONTROLLER_RESUME_CONTRACT
    )
    outcome: ControllerResumeOutcome
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    mutation_state: ControllerResumeMutationState
    session: AgentSessionView | None = None

    @model_validator(mode="after")
    def coherent_outcome(self) -> "AgentControllerResumeChatResult":
        if self.outcome == "resume_uncertain":
            if self.mutation_state != "uncertain" or self.session is not None:
                raise ValueError("uncertain resume cannot claim a live session")
            return self
        if self.session is None:
            raise ValueError("observed resume outcome requires a live session")
        if (
            self.session.session_id != self.session_id
            or self.session.settings.project_id != self.project_id
        ):
            raise ValueError("resume result identity is incoherent")
        if self.outcome == "already_live" and self.mutation_state != "not_attempted":
            raise ValueError("already-live resume cannot include a mutation")
        if self.outcome == "resumed" and self.mutation_state != "accepted":
            raise ValueError("resumed outcome requires an accepted mutation")
        if (
            self.outcome == "resumed_reconciled"
            and self.mutation_state != "reconciled"
        ):
            raise ValueError("reconciled resume requires reconciled mutation evidence")
        if self.outcome == "cleanup_unconfirmed":
            if not self.session.cleanup_unconfirmed:
                raise ValueError("cleanup outcome lacks cleanup uncertainty")
            return self
        if self.session.cleanup_unconfirmed:
            raise ValueError("ready resume outcome cannot hide cleanup uncertainty")
        if self.outcome in {"resumed", "resumed_reconciled"} and (
            not self.session.recovered
            or self.session.authority_revalidated
            or self.session.settings.allow_writes
            or self.session.settings.allow_commands
            or self.session.settings.allow_web
        ):
            raise ValueError("retained resume restored protected authority")
        return self


ControllerForkOutcome = Literal[
    "forked",
    "idempotent_replay",
    "forked_reconciled",
    "fork_uncertain",
]
ControllerForkMutationState = Literal[
    "accepted",
    "idempotent_replay",
    "reconciled",
    "uncertain",
]


class AgentControllerForkChatResult(StrictModel):
    """Identity- and lineage-bound result for one idempotent fork request."""

    contract_version: Literal["prompt-enhancer-agent-controller-fork.v1"] = (
        AGENT_CONTROLLER_FORK_CONTRACT
    )
    outcome: ControllerForkOutcome
    source_project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_catalog_revision: int = Field(strict=True, ge=1)
    source_history_revision: int = Field(strict=True, ge=0)
    destination_project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    through_event_seq: int | None = Field(default=None, strict=True, ge=0)
    attempts: Literal[1, 2]
    mutation_state: ControllerForkMutationState
    receipt: AgentSessionForkReceipt | None = None

    @model_validator(mode="after")
    def coherent_outcome(self) -> "AgentControllerForkChatResult":
        if self.outcome == "fork_uncertain":
            if (
                self.mutation_state != "uncertain"
                or self.attempts != 2
                or self.receipt is not None
            ):
                raise ValueError("uncertain fork cannot claim a branch receipt")
            return self
        if self.receipt is None:
            raise ValueError("settled fork result requires a branch receipt")
        lineage = self.receipt.session.lineage
        if (
            self.receipt.request_id != self.request_id
            or self.receipt.session.session_id == self.source_session_id
            or self.receipt.session.project_id != self.destination_project_id
            or lineage is None
            or lineage.source_project_id != self.source_project_id
            or lineage.source_session_id != self.source_session_id
            or lineage.source_catalog_revision != self.source_catalog_revision
            or lineage.source_history_revision != self.source_history_revision
            or (
                self.through_event_seq is not None
                and lineage.branch_event_seq != self.through_event_seq
            )
        ):
            raise ValueError("fork result identity or lineage is incoherent")
        if self.outcome == "forked" and (
            self.mutation_state != "accepted"
            or self.attempts != 1
            or self.receipt.idempotent_replay
        ):
            raise ValueError("new fork outcome is incoherent")
        if self.outcome == "idempotent_replay" and (
            self.mutation_state != "idempotent_replay"
            or self.attempts != 1
            or not self.receipt.idempotent_replay
        ):
            raise ValueError("fork replay outcome is incoherent")
        if self.outcome == "forked_reconciled" and (
            self.mutation_state != "reconciled" or self.attempts != 2
        ):
            raise ValueError("reconciled fork outcome is incoherent")
        return self


class AgentControllerExportChatResult(StrictModel):
    """Path-free complete retained-history projection for external agents."""

    contract_version: Literal["prompt-enhancer-agent-controller-export.v1"] = (
        AGENT_CONTROLLER_EXPORT_CONTRACT
    )
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    catalog_revision: int = Field(strict=True, ge=1)
    history_revision: int = Field(strict=True, ge=0)
    exported_at: datetime
    title: str = Field(min_length=1, max_length=120)
    model_alias: str | None = Field(default=None, max_length=64)
    event_count: int = Field(strict=True, ge=0, le=MAX_AGENT_HISTORY_EVENTS)
    turn_count: int = Field(strict=True, ge=0)
    interrupted: bool = Field(default=False, strict=True)
    events: tuple[StoredAgentEvent, ...]
    complete: Literal[True] = True
    workspace_path_included: Literal[False] = False
    attachment_bytes_included: Literal[False] = False
    live_approval_state_included: Literal[False] = False
    raw_tool_payloads_included: Literal[False] = False
    mutation_authority_included: Literal[False] = False

    @model_validator(mode="after")
    def coherent_export(self) -> "AgentControllerExportChatResult":
        sequences = [event.seq for event in self.events]
        if (
            self.event_count != len(self.events)
            or self.history_revision != self.event_count
            or sequences != list(range(1, self.history_revision + 1))
            or self.turn_count != sum(event.kind == "done" for event in self.events)
        ):
            raise ValueError("retained export event coverage is incoherent")
        return self


ControllerCloseOutcome = Literal[
    "already_closed",
    "closed",
    "closed_reconciled",
    "close_uncertain",
]
ControllerCloseMutationState = Literal[
    "not_attempted",
    "accepted",
    "reconciled",
    "uncertain",
]


class AgentControllerCloseChatResult(StrictModel):
    """Path-free evidence for one at-most-once live-chat close."""

    contract_version: Literal["prompt-enhancer-agent-controller-close.v1"] = (
        AGENT_CONTROLLER_CLOSE_CONTRACT
    )
    outcome: ControllerCloseOutcome
    project_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    catalog_revision_checked: int = Field(strict=True, ge=1)
    history_revision_checked: int = Field(strict=True, ge=0)
    mutation_state: ControllerCloseMutationState
    live_session_present: bool | None = Field(default=None, strict=True)
    catalog_session_retained: bool | None = Field(default=None, strict=True)
    permanent_delete_requested: Literal[False] = False
    retained_history_delete_requested: Literal[False] = False
    protected_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_outcome(self) -> "AgentControllerCloseChatResult":
        expected_state = {
            "already_closed": "not_attempted",
            "closed": "accepted",
            "closed_reconciled": "reconciled",
            "close_uncertain": "uncertain",
        }[self.outcome]
        if self.mutation_state != expected_state:
            raise ValueError("close outcome and mutation state are incoherent")
        if self.outcome == "close_uncertain":
            if (
                self.live_session_present is False
                and self.catalog_session_retained is True
            ):
                raise ValueError("settled close evidence cannot remain uncertain")
            return self
        if self.live_session_present is not False:
            raise ValueError("settled close result requires the live chat to be absent")
        if self.catalog_session_retained is not True:
            raise ValueError("settled close result requires the durable chat to remain")
        return self


class AgentControllerRuntimeRequest(StrictModel):
    """Ensure one exact registered model is ready, or stop that exact model."""

    desired_state: Literal["ready", "stopped"]
    alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    device: DeviceMode | None = None
    gpu_layers: int | None = Field(default=None, ge=0, le=4096)
    context_size: int | None = Field(default=None, ge=512, le=MAX_CONTEXT_SIZE)

    @model_validator(mode="after")
    def stopped_has_no_activation_settings(self) -> "AgentControllerRuntimeRequest":
        if self.desired_state == "stopped" and any(
            value is not None
            for value in (self.device, self.gpu_layers, self.context_size)
        ):
            raise ValueError("a stop request cannot carry activation settings")
        return self


ControllerRuntimeOutcome = Literal[
    "ready",
    "ready_reconciled",
    "stopped",
    "stopped_reconciled",
    "activation_uncertain",
    "stop_uncertain",
    "cleanup_unconfirmed",
]


class AgentControllerRuntimeResult(StrictModel):
    contract_version: Literal["prompt-enhancer-agent-controller-runtime.v1"] = (
        AGENT_CONTROLLER_RUNTIME_CONTRACT
    )
    desired_state: Literal["ready", "stopped"]
    alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    outcome: ControllerRuntimeOutcome
    mutation_attempted: bool
    status: LocalRuntimeCoordinatorStatus | None = None

    @model_validator(mode="after")
    def coherent_result(self) -> "AgentControllerRuntimeResult":
        ready = self.outcome in {"ready", "ready_reconciled"}
        stopped = self.outcome in {"stopped", "stopped_reconciled"}
        reconciled = self.outcome in {"ready_reconciled", "stopped_reconciled"}
        uncertain = self.outcome in {"activation_uncertain", "stop_uncertain"}
        if ready and self.desired_state != "ready":
            raise ValueError("ready outcome contradicts the requested state")
        if stopped and self.desired_state != "stopped":
            raise ValueError("stopped outcome contradicts the requested state")
        if reconciled and not self.mutation_attempted:
            raise ValueError("reconciled outcome requires one mutation attempt")
        if uncertain and not self.mutation_attempted:
            raise ValueError("uncertain outcome requires one mutation attempt")
        if (ready or stopped or self.outcome == "cleanup_unconfirmed") and self.status is None:
            raise ValueError("observed runtime outcome requires coordinator status")
        status = self.status
        if status is None:
            return self
        cleanup_unconfirmed = (
            status.state in {
                RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                RuntimeCoordinatorState.QUARANTINED,
            }
            or status.cleanup.state in {
                RuntimeCleanupState.UNKNOWN,
                RuntimeCleanupState.FAILED,
            }
            or not status.cleanup.process_exit_confirmed
        )
        ready_status = (
            status.state is RuntimeCoordinatorState.READY
            and status.requested is not None
            and status.served is not None
            and status.requested.alias == self.alias
            and status.served.alias == self.alias
            and status.requested.device is status.served.device
            and status.requested.gpu_layers == status.served.gpu_layers
            and status.requested.context_size == status.served.context_size
            and not cleanup_unconfirmed
        )
        stopped_status = (
            status.state is RuntimeCoordinatorState.IDLE
            and status.requested is None
            and status.served is None
            and status.active_requests == 0
            and not cleanup_unconfirmed
        )
        if ready and not ready_status:
            raise ValueError("ready outcome lacks exact served runtime evidence")
        if stopped and not stopped_status:
            raise ValueError("stopped outcome lacks clean idle runtime evidence")
        if self.outcome == "cleanup_unconfirmed" and not cleanup_unconfirmed:
            raise ValueError("cleanup outcome lacks uncertain cleanup evidence")
        if uncertain and (
            cleanup_unconfirmed
            or self.desired_state == "ready" and ready_status
            or self.desired_state == "stopped" and stopped_status
        ):
            raise ValueError("uncertain outcome contradicts observed runtime evidence")
        return self


ControllerTurnOutcome = Literal[
    "settled",
    "needs_native_approval",
    "submission_uncertain",
    "stopped",
    "cleanup_unconfirmed",
    "incomplete",
]
ControllerSubmissionState = Literal[
    "not_attempted",
    "accepted",
    "reconciled",
    "uncertain",
]


class AgentControllerTurnResult(StrictModel):
    contract_version: Literal["prompt-enhancer-agent-controller-turn.v2"] = (
        AGENT_CONTROLLER_TURN_CONTRACT
    )
    outcome: ControllerTurnOutcome
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    submission_state: ControllerSubmissionState
    stop_requested: bool = False
    cursor: int = Field(ge=0)
    last_seq: int = Field(ge=0)
    pending_approval_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )
    events: tuple[AgentEvent, ...] = Field(
        default=(),
        max_length=MAX_CONTROLLER_TURN_EVENTS,
    )


ControllerStopOutcome = Literal[
    "already_settled",
    "stopped",
    "stop_uncertain",
    "cleanup_unconfirmed",
    "incomplete",
]
ControllerStopRequestState = Literal[
    "not_attempted",
    "accepted",
    "reconciled",
    "uncertain",
]


class AgentControllerStopResult(StrictModel):
    """Evidence-backed outcome for one bounded, at-most-once Stop request."""

    contract_version: Literal["prompt-enhancer-agent-controller-stop.v1"] = (
        AGENT_CONTROLLER_STOP_CONTRACT
    )
    outcome: ControllerStopOutcome
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    stop_request_state: ControllerStopRequestState
    cursor: int = Field(ge=0)
    last_seq: int = Field(ge=0)
    pending_approval_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )
    events: tuple[AgentEvent, ...] = Field(
        default=(),
        max_length=MAX_CONTROLLER_TURN_EVENTS,
    )

    @model_validator(mode="after")
    def coherent_outcome(self) -> "AgentControllerStopResult":
        if self.cursor > self.last_seq:
            raise ValueError("stop cursor cannot exceed the observed sequence")
        if self.outcome == "already_settled" and self.stop_request_state != "not_attempted":
            raise ValueError("an already-settled result cannot include a Stop request")
        if self.outcome == "stop_uncertain" and self.stop_request_state != "uncertain":
            raise ValueError("an uncertain outcome requires an uncertain Stop request")
        if self.stop_request_state == "reconciled" and self.outcome != "stopped":
            raise ValueError("a reconciled Stop request requires terminal evidence")
        if self.outcome in {"already_settled", "stopped"} and (
            self.cursor != self.last_seq or self.pending_approval_id is not None
        ):
            raise ValueError("a terminal Stop outcome requires complete terminal evidence")
        return self


def _is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.partition(";")[0].strip().casefold()
    return media_type == "application/json" or media_type.endswith("+json")


def _retryable_http_status(status: int) -> bool:
    return status in {408, 425, 429, 500, 502, 503, 504}


class AgentControllerClient:
    """Discover, bootstrap, invoke, and run one finite local Agent turn."""

    def __init__(
        self,
        transport: AgentControllerTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._sleep = sleeper
        self._manifest: AgentOrchestrationManifest | None = None

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: frozenset[int],
        query: Mapping[str, str | int | bool] | None = None,
        json_body: Any | None = None,
        max_request_bytes: int = MAX_CONTROLLER_REQUEST_BYTES,
    ) -> tuple[int, Any | None]:
        if max_request_bytes == MAX_CONTROLLER_REQUEST_BYTES:
            response = self._transport.request(
                method,
                path,
                query=query,
                json_body=json_body,
            )
        else:
            response = self._transport.request(
                method,
                path,
                query=query,
                json_body=json_body,
                max_request_bytes=max_request_bytes,
            )
        if response.status_code not in expected_statuses:
            raise AgentControllerError(
                "controller_http_error",
                http_status=response.status_code,
                retryable=_retryable_http_status(response.status_code),
            )
        if len(response.body) > MAX_CONTROLLER_RESPONSE_BYTES:
            raise AgentControllerError("controller_response_too_large")
        if response.status_code == 204:
            if response.body:
                raise AgentControllerError("controller_response_invalid")
            return response.status_code, None
        if not _is_json_content_type(response.content_type):
            raise AgentControllerError("controller_response_media_invalid")
        try:
            return response.status_code, json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AgentControllerError("controller_response_invalid") from None

    def discover(self, *, refresh: bool = False) -> AgentOrchestrationManifest:
        if self._manifest is not None and not refresh:
            return self._manifest
        _, payload = self._request_json(
            "GET",
            "/v1/agent/orchestration",
            expected_statuses=frozenset({200}),
        )
        try:
            manifest = AgentOrchestrationManifest.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_contract_invalid") from None
        self._manifest = manifest
        return manifest

    @staticmethod
    def _resolve_endpoint_path(
        endpoint: AgentOrchestrationEndpoint,
        request: AgentControllerInvokeRequest,
    ) -> str:
        path_template, separator, template_query = endpoint.path_template.partition("?")
        required = set(_PATH_PARAMETER.findall(path_template))
        if set(request.path_parameters) != required:
            raise AgentControllerError("controller_path_parameters_invalid")
        path = path_template
        for key in sorted(required):
            path = path.replace(
                "{" + key + "}",
                quote(request.path_parameters[key], safe=""),
            )
        if "{" in path or "}" in path:
            raise AgentControllerError("controller_path_parameters_invalid")
        if separator:
            for requirement in template_query.split("&"):
                query_key, equals, query_value = requirement.partition("=")
                if (
                    equals != "="
                    or not query_key
                    or not query_value.startswith("{")
                    or not query_value.endswith("}")
                ):
                    raise AgentControllerError("controller_contract_invalid")
                if query_key not in request.query:
                    raise AgentControllerError("controller_query_parameters_invalid")
        return path

    def invoke(
        self,
        request: AgentControllerInvokeRequest,
    ) -> AgentControllerInvocationResult:
        manifest = self.discover()
        endpoint = next(
            (item for item in manifest.endpoints if item.operation == request.operation),
            None,
        )
        if endpoint is None:
            raise AgentControllerError("controller_operation_unknown")
        if endpoint.operation in {
            "close_live_session",
            "propose_file_transaction",
            "propose_file_write",
            "propose_workspace_lifecycle",
            "stage_attachment_inline",
            "switch_local_runtime",
            "stop_local_runtime",
        }:
            raise AgentControllerError("controller_specialized_operation_required")
        if endpoint.access == "native_user_presence_only":
            raise AgentControllerError("controller_native_review_required")
        if endpoint.response in {"binary", "sse"}:
            raise AgentControllerError("controller_response_mode_unsupported")
        path = self._resolve_endpoint_path(endpoint, request)
        if endpoint.method in {"GET", "DELETE"} and request.body is not None:
            raise AgentControllerError("controller_body_not_allowed")
        expected = {
            "GET": frozenset({200}),
            "POST": frozenset({200, 201, 202}),
            "PATCH": frozenset({200}),
            "DELETE": frozenset({200, 204}),
        }[endpoint.method]
        status, payload = self._request_json(
            endpoint.method,
            path,
            expected_statuses=expected,
            query=request.query,
            json_body=request.body,
        )
        return AgentControllerInvocationResult(
            operation=endpoint.operation,
            status_code=status,
            response=payload,
        )

    def stage_attachment(
        self,
        request: AgentControllerAttachmentStageRequest,
    ) -> AgentAttachment:
        """Submit one bounded inline payload exactly once and validate identity."""

        manifest = self.discover()
        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "stage_attachment_inline"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={
                    "project_id": request.project_id,
                    "session_id": request.session_id,
                },
            ),
        )
        _, payload = self._request_json(
            "POST",
            path,
            expected_statuses=frozenset({201}),
            json_body=request.attachment.model_dump(mode="json"),
            max_request_bytes=MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES,
        )
        try:
            attachment = AgentAttachment.model_validate(payload)
        except ValidationError:
            raise AgentControllerError(
                "controller_attachment_response_invalid"
            ) from None
        declared = request.attachment
        if (
            attachment.session_id != request.session_id
            or attachment.state != "staged"
            or attachment.source != "external_agent"
            or attachment.display_name != declared.display_name
            or attachment.media_type != declared.media_type
            or attachment.byte_size != declared.byte_size
            or attachment.sha256 != declared.sha256
        ):
            raise AgentControllerError("controller_attachment_response_invalid")
        return attachment

    def propose_write(
        self,
        request: AgentControllerWriteProposalRequest,
    ) -> AgentWriteProposalReceipt:
        """Submit exactly once and validate the native-review handoff receipt."""

        manifest = self.discover()
        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "propose_file_write"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={"session_id": request.session_id},
            ),
        )
        _, payload = self._request_json(
            "POST",
            path,
            expected_statuses=frozenset({202}),
            json_body=request.proposal.model_dump(mode="json"),
        )
        try:
            receipt = AgentWriteProposalReceipt.model_validate(payload)
        except ValidationError:
            raise AgentControllerError(
                "controller_write_proposal_response_invalid"
            ) from None
        if (
            receipt.session_id != request.session_id
            or receipt.request_id != request.proposal.request_id
            or receipt.operation != request.proposal.operation
        ):
            raise AgentControllerError("controller_write_proposal_response_invalid")
        return receipt

    def propose_write_transaction(
        self,
        request: AgentControllerWriteTransactionProposalRequest,
    ) -> AgentWriteTransactionProposalReceipt:
        """Submit one atomic proposal exactly once and revalidate its receipt."""

        manifest = self.discover()
        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "propose_file_transaction"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={"session_id": request.session_id},
            ),
        )
        _, payload = self._request_json(
            "POST",
            path,
            expected_statuses=frozenset({202}),
            json_body=request.proposal.model_dump(mode="json"),
        )
        try:
            receipt = AgentWriteTransactionProposalReceipt.model_validate(payload)
        except ValidationError:
            raise AgentControllerError(
                "controller_write_transaction_proposal_response_invalid"
            ) from None

        expected_files = sorted(
            (
                (
                    change.operation,
                    change.path,
                    hashlib.sha256(
                        (
                            change.content.replace("\n", "\r\n")
                            if change.line_ending.value == "crlf"
                            else change.content
                        ).encode("utf-8", errors="strict")
                    ).hexdigest(),
                )
                for change in request.proposal.changes
            ),
            key=lambda item: item[1].encode("utf-8"),
        )
        returned_files = [
            (item.operation, item.path, item.proposed_revision)
            for item in receipt.files
        ]
        if (
            receipt.session_id != request.session_id
            or receipt.request_id != request.proposal.request_id
            or receipt.file_count != len(request.proposal.changes)
            or returned_files != expected_files
        ):
            raise AgentControllerError(
                "controller_write_transaction_proposal_response_invalid"
            )
        return receipt

    def propose_lifecycle(
        self,
        request: AgentControllerLifecycleProposalRequest,
    ) -> AgentLifecycleProposalReceipt:
        """Submit one lifecycle proposal once and validate its inert receipt."""

        manifest = self.discover()
        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "propose_workspace_lifecycle"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={"session_id": request.session_id},
            ),
        )
        _, payload = self._request_json(
            "POST",
            path,
            expected_statuses=frozenset({202}),
            json_body=request.proposal.model_dump(mode="json"),
        )
        try:
            receipt = AgentLifecycleProposalReceipt.model_validate(payload)
        except ValidationError:
            raise AgentControllerError(
                "controller_lifecycle_proposal_response_invalid"
            ) from None
        proposal = request.proposal
        if (
            receipt.session_id != request.session_id
            or receipt.request_id != proposal.request_id
            or receipt.operation != proposal.operation
            or receipt.path != proposal.path
            or receipt.source_path != proposal.source_path
            or receipt.target_path != proposal.target_path
            or receipt.expected_revision != proposal.expected_revision
        ):
            raise AgentControllerError(
                "controller_lifecycle_proposal_response_invalid"
            )
        return receipt

    @staticmethod
    def _runtime_status(payload: Any) -> LocalRuntimeCoordinatorStatus:
        try:
            return LocalRuntimeCoordinatorStatus.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_runtime_response_invalid") from None

    def _get_runtime(self) -> LocalRuntimeCoordinatorStatus:
        _, payload = self._request_json(
            "GET",
            "/v1/local-models/runtime",
            expected_statuses=frozenset({200}),
        )
        return self._runtime_status(payload)

    @staticmethod
    def _runtime_cleanup_unconfirmed(
        status: LocalRuntimeCoordinatorStatus,
    ) -> bool:
        return (
            status.state in {
                RuntimeCoordinatorState.CLEANUP_UNKNOWN,
                RuntimeCoordinatorState.QUARANTINED,
            }
            or status.cleanup.state in {
                RuntimeCleanupState.UNKNOWN,
                RuntimeCleanupState.FAILED,
            }
            or not status.cleanup.process_exit_confirmed
        )

    @staticmethod
    def _runtime_ready_matches(
        status: LocalRuntimeCoordinatorStatus,
        request: AgentControllerRuntimeRequest,
    ) -> bool:
        requested = status.requested
        served = status.served
        if (
            request.desired_state != "ready"
            or status.state is not RuntimeCoordinatorState.READY
            or requested is None
            or served is None
            or requested.alias != request.alias
            or served.alias != request.alias
            or requested.device is not served.device
            or requested.gpu_layers != served.gpu_layers
            or requested.context_size != served.context_size
        ):
            return False
        return (
            (request.device is None or served.device is request.device)
            and (
                request.gpu_layers is None
                or served.gpu_layers == request.gpu_layers
            )
            and (
                request.context_size is None
                or served.context_size == request.context_size
            )
        )

    @classmethod
    def _runtime_stopped_matches(
        cls,
        status: LocalRuntimeCoordinatorStatus,
    ) -> bool:
        return (
            status.state is RuntimeCoordinatorState.IDLE
            and status.requested is None
            and status.served is None
            and status.active_requests == 0
            and not cls._runtime_cleanup_unconfirmed(status)
        )

    @classmethod
    def _runtime_result(
        cls,
        request: AgentControllerRuntimeRequest,
        status: LocalRuntimeCoordinatorStatus | None,
        *,
        mutation_attempted: bool,
        reconciled: bool = False,
    ) -> AgentControllerRuntimeResult:
        if status is not None and cls._runtime_cleanup_unconfirmed(status):
            outcome: ControllerRuntimeOutcome = "cleanup_unconfirmed"
        elif status is not None and cls._runtime_ready_matches(status, request):
            outcome = "ready_reconciled" if reconciled else "ready"
        elif (
            request.desired_state == "stopped"
            and status is not None
            and cls._runtime_stopped_matches(status)
        ):
            outcome = "stopped_reconciled" if reconciled else "stopped"
        else:
            outcome = (
                "activation_uncertain"
                if request.desired_state == "ready"
                else "stop_uncertain"
            )
        return AgentControllerRuntimeResult(
            desired_state=request.desired_state,
            alias=request.alias,
            outcome=outcome,
            mutation_attempted=mutation_attempted,
            status=status,
        )

    def coordinate_runtime(
        self,
        request: AgentControllerRuntimeRequest,
    ) -> AgentControllerRuntimeResult:
        """Reach one runtime state with one revision-bound mutation at most.

        A response lost after mutation is reconciled with one GET. The mutation
        is never repeated automatically. Cleanup uncertainty is terminal for
        this command and is returned as evidence rather than hidden by retry.
        """

        self.discover()
        before = self._get_runtime()
        if (
            self._runtime_cleanup_unconfirmed(before)
            or self._runtime_ready_matches(before, request)
            or request.desired_state == "stopped"
            and self._runtime_stopped_matches(before)
        ):
            return self._runtime_result(
                request,
                before,
                mutation_attempted=False,
            )
        if request.desired_state == "stopped":
            selected_alias = (
                before.served.alias
                if before.served is not None
                else before.requested.alias
                if before.requested is not None
                else None
            )
            if selected_alias is not None and selected_alias != request.alias:
                raise AgentControllerError("controller_runtime_alias_mismatch")
            body = StopLocalRuntime(
                alias=request.alias,
                expected_revision=before.revision,
            ).model_dump(mode="json")
            path = "/v1/local-models/runtime/stop"
        else:
            body = SwitchLocalRuntime(
                alias=request.alias,
                expected_revision=before.revision,
                device=request.device,
                gpu_layers=request.gpu_layers,
                context_size=request.context_size,
                remember=False,
                fast_attention=True,
                tool_calling=True,
            ).model_dump(mode="json")
            path = "/v1/local-models/runtime/switch"
        try:
            _, payload = self._request_json(
                "POST",
                path,
                expected_statuses=frozenset({200}),
                json_body=body,
            )
            status = self._runtime_status(payload)
            return self._runtime_result(
                request,
                status,
                mutation_attempted=True,
            )
        except AgentControllerError as error:
            if error.http_status is not None and 400 <= error.http_status < 500:
                raise
        try:
            reconciled = self._get_runtime()
        except AgentControllerError:
            reconciled = None
        return self._runtime_result(
            request,
            reconciled,
            mutation_attempted=True,
            reconciled=True,
        )

    @staticmethod
    def _project_response(
        payload: Any,
        *,
        uncertain_on_invalid: bool,
    ) -> AgentProjectRecord:
        try:
            return AgentProjectRecord.model_validate(payload)
        except ValidationError:
            code = (
                "controller_project_creation_uncertain"
                if uncertain_on_invalid
                else "controller_project_response_invalid"
            )
            raise AgentControllerError(code) from None

    @staticmethod
    def _creation_is_uncertain(error: AgentControllerError) -> bool:
        return error.http_status is None or not 400 <= error.http_status < 500

    @staticmethod
    def _resume_authority_safe(session: AgentSessionView) -> bool:
        return (
            session.recovered
            and not session.authority_revalidated
            and not session.settings.allow_writes
            and not session.settings.allow_commands
            and not session.settings.allow_web
        )

    @staticmethod
    def _fork_receipt(
        request: AgentControllerForkChatRequest,
        payload: Any,
    ) -> AgentSessionForkReceipt:
        try:
            receipt = AgentSessionForkReceipt.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_fork_response_invalid") from None
        lineage = receipt.session.lineage
        destination = request.destination_project_id or request.project_id
        if (
            receipt.request_id != request.request_id
            or receipt.session.session_id == request.session_id
            or receipt.session.project_id != destination
            or receipt.session.archived_at is not None
            or receipt.session.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY
            or not receipt.session.conversation_available
            or lineage is None
            or lineage.source_project_id != request.project_id
            or lineage.source_session_id != request.session_id
            or lineage.source_catalog_revision != request.expected_catalog_revision
            or lineage.source_history_revision != request.expected_history_revision
            or (
                request.through_event_seq is not None
                and lineage.branch_event_seq != request.through_event_seq
            )
        ):
            raise AgentControllerError("controller_fork_response_invalid")
        return receipt

    def _live_session_if_present(self, session_id: str) -> AgentSessionView | None:
        status, payload = self._request_json(
            "GET",
            f"/v1/agent/sessions/{session_id}",
            expected_statuses=frozenset({200, 404}),
        )
        if status == 404:
            return None
        try:
            session = AgentSessionView.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_session_response_invalid") from None
        if session.session_id != session_id:
            raise AgentControllerError("controller_session_response_invalid")
        return session

    def live_session(self, session_id: str) -> AgentSessionView | None:
        """Read one exact live session without creating or resuming it."""

        self.discover()
        return self._live_session_if_present(session_id)

    def _catalog_session_if_present(
        self,
        session_id: str,
    ) -> AgentCatalogSessionRecord | None:
        status, payload = self._request_json(
            "GET",
            f"/v1/agent/catalog/sessions/{session_id}",
            expected_statuses=frozenset({200, 404}),
        )
        if status == 404:
            return None
        try:
            record = AgentCatalogSessionRecord.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_catalog_response_invalid") from None
        if record.session_id != session_id:
            raise AgentControllerError("controller_catalog_response_invalid")
        return record

    def fork_chat(
        self,
        request: AgentControllerForkChatRequest,
    ) -> AgentControllerForkChatResult:
        """Fork one retained history with one bounded idempotent retry.

        The caller owns the request ID. Only a byte-identical second POST is
        allowed after an ambiguous first exchange, so the durable repository's
        idempotency binding can reconcile the result without creating a second
        child chat.
        """

        manifest = self.discover()
        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "fork_retained_session"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={
                    "project_id": request.project_id,
                    "session_id": request.session_id,
                },
            ),
        )
        body = request.command().model_dump(mode="json")
        destination = request.destination_project_id or request.project_id

        for attempt in (1, 2):
            try:
                _, payload = self._request_json(
                    "POST",
                    path,
                    expected_statuses=frozenset({200}),
                    json_body=body,
                )
                receipt = self._fork_receipt(request, payload)
                if attempt == 2:
                    return AgentControllerForkChatResult(
                        outcome="forked_reconciled",
                        source_project_id=request.project_id,
                        source_session_id=request.session_id,
                        request_id=request.request_id,
                        source_catalog_revision=request.expected_catalog_revision,
                        source_history_revision=request.expected_history_revision,
                        destination_project_id=destination,
                        through_event_seq=request.through_event_seq,
                        attempts=2,
                        mutation_state="reconciled",
                        receipt=receipt,
                    )
                return AgentControllerForkChatResult(
                    outcome=(
                        "idempotent_replay"
                        if receipt.idempotent_replay
                        else "forked"
                    ),
                    source_project_id=request.project_id,
                    source_session_id=request.session_id,
                    request_id=request.request_id,
                    source_catalog_revision=request.expected_catalog_revision,
                    source_history_revision=request.expected_history_revision,
                    destination_project_id=destination,
                    through_event_seq=request.through_event_seq,
                    attempts=1,
                    mutation_state=(
                        "idempotent_replay"
                        if receipt.idempotent_replay
                        else "accepted"
                    ),
                    receipt=receipt,
                )
            except AgentControllerError as error:
                if (
                    attempt == 1
                    and error.http_status is not None
                    and 400 <= error.http_status < 500
                ):
                    raise

        return AgentControllerForkChatResult(
            outcome="fork_uncertain",
            source_project_id=request.project_id,
            source_session_id=request.session_id,
            request_id=request.request_id,
            source_catalog_revision=request.expected_catalog_revision,
            source_history_revision=request.expected_history_revision,
            destination_project_id=destination,
            through_event_seq=request.through_event_seq,
            attempts=2,
            mutation_state="uncertain",
        )

    def export_chat(
        self,
        request: AgentControllerExportChatRequest,
    ) -> AgentControllerExportChatResult:
        """Return one complete exact-revision history without its workspace path."""

        manifest = self.discover()
        catalog_result = self.invoke(
            AgentControllerInvokeRequest(
                operation="get_catalog_session",
                path_parameters={"session_id": request.session_id},
            )
        )
        try:
            record = AgentCatalogSessionRecord.model_validate(catalog_result.response)
        except ValidationError:
            raise AgentControllerError("controller_catalog_response_invalid") from None
        if record.session_id != request.session_id or record.project_id != request.project_id:
            raise AgentControllerError("controller_catalog_response_invalid")
        if (
            record.revision != request.expected_catalog_revision
            or record.history_revision != request.expected_history_revision
        ):
            raise AgentControllerError("controller_export_revision_mismatch")
        if (
            record.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY
            or not record.conversation_available
        ):
            raise AgentControllerError("controller_export_unavailable")
        if record.history_revision > request.max_events:
            raise AgentControllerError("controller_export_limit_exceeded")

        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "export_retained_history"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "GET"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={
                    "project_id": request.project_id,
                    "session_id": request.session_id,
                },
            ),
        )
        _, payload = self._request_json(
            "GET",
            path,
            expected_statuses=frozenset({200}),
            query={
                "expected_catalog_revision": request.expected_catalog_revision,
                "expected_history_revision": request.expected_history_revision,
            },
        )
        try:
            exported = AgentHistoryExport.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_export_response_invalid") from None
        if (
            exported.project_id != request.project_id
            or exported.session_id != request.session_id
            or exported.title != record.title
            or exported.workspace != record.workspace
            or exported.model_alias != record.model_alias
            or exported.history_revision != request.expected_history_revision
            or exported.turn_count != record.turn_count
            or len(exported.events) > request.max_events
        ):
            raise AgentControllerError("controller_export_response_invalid")
        try:
            return AgentControllerExportChatResult(
                project_id=request.project_id,
                session_id=request.session_id,
                catalog_revision=request.expected_catalog_revision,
                history_revision=exported.history_revision,
                exported_at=exported.exported_at,
                title=exported.title,
                model_alias=exported.model_alias,
                event_count=len(exported.events),
                turn_count=exported.turn_count,
                interrupted=exported.interrupted,
                events=exported.events,
            )
        except ValidationError:
            raise AgentControllerError("controller_export_response_invalid") from None

    def close_chat(
        self,
        request: AgentControllerCloseChatRequest,
    ) -> AgentControllerCloseChatResult:
        """Close one exact idle live chat once and retain its durable record.

        The catalog and live history revisions are checked before mutation. A
        close is never repeated after an ambiguous exchange; one read-only
        live/catalog observation may reconcile it.
        """

        manifest = self.discover()
        catalog_result = self.invoke(
            AgentControllerInvokeRequest(
                operation="get_catalog_session",
                path_parameters={"session_id": request.session_id},
            )
        )
        try:
            record = AgentCatalogSessionRecord.model_validate(catalog_result.response)
        except ValidationError:
            raise AgentControllerError("controller_catalog_response_invalid") from None
        if record.session_id != request.session_id or record.project_id != request.project_id:
            raise AgentControllerError("controller_catalog_response_invalid")
        if (
            record.revision != request.expected_catalog_revision
            or record.history_revision != request.expected_history_revision
        ):
            raise AgentControllerError("controller_close_revision_mismatch")

        live = self._live_session_if_present(request.session_id)
        if live is None:
            return AgentControllerCloseChatResult(
                outcome="already_closed",
                project_id=request.project_id,
                session_id=request.session_id,
                catalog_revision_checked=request.expected_catalog_revision,
                history_revision_checked=request.expected_history_revision,
                mutation_state="not_attempted",
                live_session_present=False,
                catalog_session_retained=True,
            )
        if (
            live.settings.project_id != request.project_id
            or live.history_revision != request.expected_history_revision
        ):
            raise AgentControllerError("controller_close_revision_mismatch")
        if live.cleanup_unconfirmed:
            raise AgentControllerError("controller_close_cleanup_unconfirmed")
        if (
            live.running
            or live.closing
            or live.stopping
            or live.pending_approval_id is not None
        ):
            raise AgentControllerError("controller_close_not_idle")

        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "close_live_session"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "DELETE"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "no_content"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={"session_id": request.session_id},
            ),
        )
        try:
            self._request_json(
                "DELETE",
                path,
                expected_statuses=frozenset({204}),
                query={
                    "expected_project_id": request.project_id,
                    "expected_catalog_revision": request.expected_catalog_revision,
                    "expected_history_revision": request.expected_history_revision,
                },
            )
        except AgentControllerError as error:
            if error.http_status is not None and 400 <= error.http_status < 500:
                raise
            live_present: bool | None = None
            catalog_retained: bool | None = None
            try:
                observed_live = self._live_session_if_present(request.session_id)
                live_present = observed_live is not None
            except AgentControllerError:
                observed_live = None
            try:
                observed_record = self._catalog_session_if_present(request.session_id)
                catalog_retained = bool(
                    observed_record is not None
                    and observed_record.project_id == request.project_id
                    and observed_record.revision >= request.expected_catalog_revision
                    and observed_record.history_revision
                    >= request.expected_history_revision
                    and observed_record.retention_policy is record.retention_policy
                    and (
                        not record.conversation_available
                        or observed_record.conversation_available
                    )
                )
            except AgentControllerError:
                observed_record = None
            if live_present is False and catalog_retained is True:
                return AgentControllerCloseChatResult(
                    outcome="closed_reconciled",
                    project_id=request.project_id,
                    session_id=request.session_id,
                    catalog_revision_checked=request.expected_catalog_revision,
                    history_revision_checked=request.expected_history_revision,
                    mutation_state="reconciled",
                    live_session_present=False,
                    catalog_session_retained=True,
                )
            return AgentControllerCloseChatResult(
                outcome="close_uncertain",
                project_id=request.project_id,
                session_id=request.session_id,
                catalog_revision_checked=request.expected_catalog_revision,
                history_revision_checked=request.expected_history_revision,
                mutation_state="uncertain",
                live_session_present=live_present,
                catalog_session_retained=catalog_retained,
            )

        return AgentControllerCloseChatResult(
            outcome="closed",
            project_id=request.project_id,
            session_id=request.session_id,
            catalog_revision_checked=request.expected_catalog_revision,
            history_revision_checked=request.expected_history_revision,
            mutation_state="accepted",
            live_session_present=False,
            catalog_session_retained=True,
        )

    def resume_chat(
        self,
        request: AgentControllerResumeChatRequest,
    ) -> AgentControllerResumeChatResult:
        """Resume one retained chat once, restoring no protected authority.

        Catalog and history revisions are checked before mutation. A lost
        response is reconciled with one live-session read and is never retried.
        """

        manifest = self.discover()
        catalog_result = self.invoke(
            AgentControllerInvokeRequest(
                operation="get_catalog_session",
                path_parameters={"session_id": request.session_id},
            )
        )
        try:
            record = AgentCatalogSessionRecord.model_validate(catalog_result.response)
        except ValidationError:
            raise AgentControllerError("controller_catalog_response_invalid") from None
        if record.session_id != request.session_id or record.project_id != request.project_id:
            raise AgentControllerError("controller_catalog_response_invalid")
        if (
            record.revision != request.expected_catalog_revision
            or record.history_revision != request.expected_history_revision
        ):
            raise AgentControllerError("controller_resume_revision_mismatch")
        if (
            record.archived_at is not None
            or record.retention_policy is not AgentRetentionPolicy.LOCAL_HISTORY
            or not record.conversation_available
        ):
            raise AgentControllerError("controller_resume_unavailable")

        live = self._live_session_if_present(request.session_id)
        if live is not None:
            if live.settings.project_id != request.project_id:
                raise AgentControllerError("controller_session_response_invalid")
            return AgentControllerResumeChatResult(
                outcome=(
                    "cleanup_unconfirmed"
                    if live.cleanup_unconfirmed
                    else "already_live"
                ),
                project_id=request.project_id,
                session_id=request.session_id,
                mutation_state="not_attempted",
                session=live,
            )

        endpoint = next(
            (
                item
                for item in manifest.endpoints
                if item.operation == "resume_retained_session"
            ),
            None,
        )
        if (
            endpoint is None
            or endpoint.method != "POST"
            or endpoint.access != "token_authenticated"
            or endpoint.response != "json"
        ):
            raise AgentControllerError("controller_contract_invalid")
        path = self._resolve_endpoint_path(
            endpoint,
            AgentControllerInvokeRequest(
                operation=endpoint.operation,
                path_parameters={
                    "project_id": request.project_id,
                    "session_id": request.session_id,
                },
            ),
        )
        mutation = ResumeAgentSession(
            expected_catalog_revision=request.expected_catalog_revision,
            expected_history_revision=request.expected_history_revision,
        )
        try:
            _, payload = self._request_json(
                "POST",
                path,
                expected_statuses=frozenset({200}),
                json_body=mutation.model_dump(mode="json"),
            )
            try:
                resumed = AgentSessionView.model_validate(payload)
            except ValidationError:
                raise AgentControllerError("controller_resume_response_invalid") from None
            if (
                resumed.session_id != request.session_id
                or resumed.settings.project_id != request.project_id
                or not self._resume_authority_safe(resumed)
            ):
                raise AgentControllerError("controller_resume_response_invalid")
            return AgentControllerResumeChatResult(
                outcome=(
                    "cleanup_unconfirmed"
                    if resumed.cleanup_unconfirmed
                    else "resumed"
                ),
                project_id=request.project_id,
                session_id=request.session_id,
                mutation_state="accepted",
                session=resumed,
            )
        except AgentControllerError as error:
            if error.http_status is not None and 400 <= error.http_status < 500:
                raise

        try:
            reconciled = self._live_session_if_present(request.session_id)
        except AgentControllerError:
            reconciled = None
        if (
            reconciled is not None
            and reconciled.settings.project_id == request.project_id
            and self._resume_authority_safe(reconciled)
        ):
            return AgentControllerResumeChatResult(
                outcome=(
                    "cleanup_unconfirmed"
                    if reconciled.cleanup_unconfirmed
                    else "resumed_reconciled"
                ),
                project_id=request.project_id,
                session_id=request.session_id,
                mutation_state="reconciled",
                session=reconciled,
            )
        return AgentControllerResumeChatResult(
            outcome="resume_uncertain",
            project_id=request.project_id,
            session_id=request.session_id,
            mutation_state="uncertain",
        )

    def open_chat(
        self,
        request: AgentControllerOpenChatRequest,
    ) -> AgentControllerOpenChatResult:
        """Create or select a project, then open exactly one live chat.

        Creation requests are never retried. If the session exchange becomes
        ambiguous after the project identity is known, the result carries that
        project so a caller can reconcile its chat list instead of submitting a
        duplicate create. A newly created empty project is removed only after a
        trustworthy 4xx session rejection.
        """

        self.discover()
        project_created = False
        if request.project_id is not None:
            _, payload = self._request_json(
                "GET",
                f"/v1/agent/projects/{request.project_id}",
                expected_statuses=frozenset({200}),
            )
            project = self._project_response(
                payload,
                uncertain_on_invalid=False,
            )
            if project.project_id != request.project_id:
                raise AgentControllerError("controller_project_response_invalid")
        else:
            try:
                _, payload = self._request_json(
                    "POST",
                    "/v1/agent/projects",
                    expected_statuses=frozenset({201}),
                    json_body=CreateAgentProject(
                        name=request.project_name or "",
                    ).model_dump(mode="json"),
                )
            except AgentControllerError as error:
                if self._creation_is_uncertain(error):
                    raise AgentControllerError(
                        "controller_project_creation_uncertain"
                    ) from None
                raise
            project = self._project_response(
                payload,
                uncertain_on_invalid=True,
            )
            project_created = True

        settings = request.settings.model_copy(
            update={"project_id": project.project_id}
        )
        try:
            _, payload = self._request_json(
                "POST",
                "/v1/agent/sessions",
                expected_statuses=frozenset({201}),
                json_body=settings.model_dump(mode="json"),
            )
        except AgentControllerError as error:
            if self._creation_is_uncertain(error):
                return AgentControllerOpenChatResult(
                    outcome="session_creation_uncertain",
                    project=project,
                    project_created=project_created,
                )
            if not project_created:
                raise
            try:
                self._request_json(
                    "DELETE",
                    f"/v1/agent/projects/{project.project_id}",
                    expected_statuses=frozenset({204}),
                )
            except AgentControllerError:
                return AgentControllerOpenChatResult(
                    outcome="project_cleanup_unconfirmed",
                    project=project,
                    project_created=True,
                )
            raise

        try:
            session = AgentSessionView.model_validate(payload)
        except ValidationError:
            return AgentControllerOpenChatResult(
                outcome="session_creation_uncertain",
                project=project,
                project_created=project_created,
            )
        if session.settings.project_id != project.project_id:
            return AgentControllerOpenChatResult(
                outcome="session_creation_uncertain",
                project=project,
                project_created=project_created,
            )
        return AgentControllerOpenChatResult(
            outcome="ready",
            project=project,
            project_created=project_created,
            session=session,
        )

    def _session(self, session_id: str) -> AgentSessionView:
        _, payload = self._request_json(
            "GET",
            f"/v1/agent/sessions/{session_id}",
            expected_statuses=frozenset({200}),
        )
        try:
            return AgentSessionView.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_session_response_invalid") from None

    def _events(self, session_id: str, after: int) -> AgentEvents:
        _, payload = self._request_json(
            "GET",
            f"/v1/agent/sessions/{session_id}/events",
            expected_statuses=frozenset({200}),
            query={"after": after, "limit": 500},
        )
        try:
            page = AgentEvents.model_validate(payload)
        except ValidationError:
            raise AgentControllerError("controller_event_response_invalid") from None
        if page.session_id != session_id:
            raise AgentControllerError("controller_event_session_mismatch")
        return page

    @staticmethod
    def _absorb_page(
        page: AgentEvents,
        *,
        cursor: int,
        observed: list[AgentEvent],
    ) -> int:
        if page.first_seq > cursor + 1:
            raise AgentControllerError("controller_event_cursor_gap")
        sequences = [event.seq for event in page.events]
        if (
            sequences != sorted(set(sequences))
            or any(sequence <= cursor for sequence in sequences)
        ):
            raise AgentControllerError("controller_event_sequence_invalid")
        if page.last_seq < cursor or (sequences and page.last_seq < sequences[-1]):
            raise AgentControllerError("controller_event_sequence_invalid")
        if not sequences and page.last_seq > cursor:
            raise AgentControllerError("controller_event_page_incomplete")
        if len(observed) + len(page.events) > MAX_CONTROLLER_TURN_EVENTS:
            raise AgentControllerError("controller_turn_event_limit")
        observed.extend(page.events)
        return sequences[-1] if sequences else cursor

    @staticmethod
    def _message_was_observed(
        events: list[AgentEvent],
        message: SendMessage,
    ) -> bool:
        expected_attachments = tuple(message.attachment_ids)
        for event in events:
            if event.kind != "user" or event.text != message.text:
                continue
            actual_attachments = tuple(
                attachment.attachment_id for attachment in event.attachments
            )
            if actual_attachments == expected_attachments:
                return True
        return False

    @staticmethod
    def _terminal(page: AgentEvents, cursor: int) -> bool:
        return (
            not page.running
            and not page.closing
            and not page.stopping
            and not page.cleanup_unconfirmed
            and page.pending_approval_id is None
            and cursor >= page.last_seq
        )

    @staticmethod
    def _validate_polling_options(
        *,
        deadline_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        if not 0.05 <= deadline_seconds <= 3_600:
            raise AgentControllerError("controller_deadline_invalid")
        if not 0.01 <= poll_interval_seconds <= 5:
            raise AgentControllerError("controller_poll_interval_invalid")

    @staticmethod
    def _turn_result(
        *,
        outcome: ControllerTurnOutcome,
        session_id: str,
        submission_state: ControllerSubmissionState,
        stop_requested: bool,
        cursor: int,
        last_seq: int,
        pending_approval_id: str | None,
        observed: list[AgentEvent],
    ) -> AgentControllerTurnResult:
        return AgentControllerTurnResult(
            outcome=outcome,
            session_id=session_id,
            submission_state=submission_state,
            stop_requested=stop_requested,
            cursor=cursor,
            last_seq=last_seq,
            pending_approval_id=pending_approval_id,
            events=tuple(observed),
        )

    @staticmethod
    def _stop_result(
        *,
        outcome: ControllerStopOutcome,
        session_id: str,
        stop_request_state: ControllerStopRequestState,
        cursor: int,
        last_seq: int,
        pending_approval_id: str | None,
        observed: list[AgentEvent],
    ) -> AgentControllerStopResult:
        return AgentControllerStopResult(
            outcome=outcome,
            session_id=session_id,
            stop_request_state=stop_request_state,
            cursor=cursor,
            last_seq=last_seq,
            pending_approval_id=pending_approval_id,
            events=tuple(observed),
        )

    def run_turn(
        self,
        request: AgentControllerTurnRequest,
        *,
        deadline_seconds: float = 120.0,
        poll_interval_seconds: float = 0.1,
        drain_timeout_seconds: float = 5.0,
    ) -> AgentControllerTurnResult:
        self._validate_polling_options(
            deadline_seconds=deadline_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        if not 0.1 <= drain_timeout_seconds <= 30:
            raise AgentControllerError("controller_drain_timeout_invalid")

        self.discover()
        session = self._session(request.session_id)
        observed: list[AgentEvent] = []
        cursor = session.last_seq
        if session.cleanup_unconfirmed:
            return self._turn_result(
                outcome="cleanup_unconfirmed",
                session_id=request.session_id,
                submission_state="not_attempted",
                stop_requested=False,
                cursor=cursor,
                last_seq=session.last_seq,
                pending_approval_id=session.pending_approval_id,
                observed=observed,
            )
        if session.pending_approval_id is not None:
            return self._turn_result(
                outcome="needs_native_approval",
                session_id=request.session_id,
                submission_state="not_attempted",
                stop_requested=False,
                cursor=cursor,
                last_seq=session.last_seq,
                pending_approval_id=session.pending_approval_id,
                observed=observed,
            )
        if (
            session.running
            or session.closing
            or session.stopping
        ):
            raise AgentControllerError("controller_session_not_idle")

        deadline = self._clock() + deadline_seconds
        submission_state: ControllerSubmissionState = "accepted"
        try:
            _, submitted_payload = self._request_json(
                "POST",
                f"/v1/agent/sessions/{request.session_id}/messages",
                expected_statuses=frozenset({202}),
                json_body=request.message.model_dump(mode="json"),
            )
            try:
                submitted = AgentSessionView.model_validate(submitted_payload)
            except ValidationError:
                raise AgentControllerError(
                    "controller_session_response_invalid"
                ) from None
            if submitted.session_id != request.session_id:
                raise AgentControllerError("controller_session_response_invalid")
        except AgentControllerTransportUnavailable:
            submission_state = "uncertain"
            try:
                page = self._events(request.session_id, cursor)
            except AgentControllerTransportUnavailable:
                return self._turn_result(
                    outcome="submission_uncertain",
                    session_id=request.session_id,
                    submission_state="uncertain",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=cursor,
                    pending_approval_id=None,
                    observed=observed,
                )
            cursor = self._absorb_page(page, cursor=cursor, observed=observed)
            if not self._message_was_observed(observed, request.message):
                return self._turn_result(
                    outcome="submission_uncertain",
                    session_id=request.session_id,
                    submission_state="uncertain",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            submission_state = "reconciled"

        last_seq = cursor
        while self._clock() < deadline:
            try:
                page = self._events(request.session_id, cursor)
            except AgentControllerTransportUnavailable:
                return self._turn_result(
                    outcome="incomplete",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            cursor = self._absorb_page(page, cursor=cursor, observed=observed)
            last_seq = page.last_seq
            if page.cleanup_unconfirmed:
                return self._turn_result(
                    outcome="cleanup_unconfirmed",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if page.pending_approval_id is not None:
                return self._turn_result(
                    outcome="needs_native_approval",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if self._terminal(page, cursor):
                return self._turn_result(
                    outcome="settled",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleep(min(poll_interval_seconds, remaining))

        stop_requested = True
        try:
            self._request_json(
                "POST",
                f"/v1/agent/sessions/{request.session_id}/stop",
                expected_statuses=frozenset({200}),
            )
        except (AgentControllerError, AgentControllerTransportUnavailable):
            # A stop request is also non-idempotent from the client's point of
            # view.  Never repeat it; perform only bounded observation below.
            pass

        drain_deadline = self._clock() + drain_timeout_seconds
        while self._clock() < drain_deadline:
            try:
                page = self._events(request.session_id, cursor)
            except AgentControllerTransportUnavailable:
                break
            cursor = self._absorb_page(page, cursor=cursor, observed=observed)
            last_seq = page.last_seq
            if page.cleanup_unconfirmed:
                return self._turn_result(
                    outcome="cleanup_unconfirmed",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=stop_requested,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if page.pending_approval_id is not None:
                return self._turn_result(
                    outcome="needs_native_approval",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=stop_requested,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if self._terminal(page, cursor):
                return self._turn_result(
                    outcome="stopped",
                    session_id=request.session_id,
                    submission_state=submission_state,
                    stop_requested=stop_requested,
                    cursor=cursor,
                    last_seq=page.last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            remaining = drain_deadline - self._clock()
            if remaining > 0:
                self._sleep(min(poll_interval_seconds, remaining))

        return self._turn_result(
            outcome="incomplete",
            session_id=request.session_id,
            submission_state=submission_state,
            stop_requested=stop_requested,
            cursor=cursor,
            last_seq=last_seq,
            pending_approval_id=None,
            observed=observed,
        )

    def wait_turn(
        self,
        request: AgentControllerWaitRequest,
        *,
        deadline_seconds: float = 120.0,
        poll_interval_seconds: float = 0.1,
    ) -> AgentControllerTurnResult:
        """Boundedly observe an existing turn without submitting or stopping.

        This is the safe continuation path after ``run_turn`` returns
        ``needs_native_approval``. The native owner resolves the approval, then
        the controller resumes from the returned cursor. A deadline never
        mutates the session: it returns ``incomplete`` and the caller may wait
        again with the new cursor.
        """

        self._validate_polling_options(
            deadline_seconds=deadline_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        self.discover()
        session = self._session(request.session_id)
        if request.after > session.last_seq:
            raise AgentControllerError("controller_event_cursor_invalid")

        observed: list[AgentEvent] = []
        cursor = request.after
        last_seq = session.last_seq
        if session.cleanup_unconfirmed:
            return self._turn_result(
                outcome="cleanup_unconfirmed",
                session_id=request.session_id,
                submission_state="not_attempted",
                stop_requested=False,
                cursor=cursor,
                last_seq=last_seq,
                pending_approval_id=session.pending_approval_id,
                observed=observed,
            )

        deadline = self._clock() + deadline_seconds
        while self._clock() < deadline:
            try:
                page = self._events(request.session_id, cursor)
            except AgentControllerTransportUnavailable:
                return self._turn_result(
                    outcome="incomplete",
                    session_id=request.session_id,
                    submission_state="not_attempted",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            cursor = self._absorb_page(page, cursor=cursor, observed=observed)
            last_seq = page.last_seq
            if page.cleanup_unconfirmed:
                return self._turn_result(
                    outcome="cleanup_unconfirmed",
                    session_id=request.session_id,
                    submission_state="not_attempted",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if page.pending_approval_id is not None:
                return self._turn_result(
                    outcome="needs_native_approval",
                    session_id=request.session_id,
                    submission_state="not_attempted",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if self._terminal(page, cursor):
                return self._turn_result(
                    outcome="settled",
                    session_id=request.session_id,
                    submission_state="not_attempted",
                    stop_requested=False,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleep(min(poll_interval_seconds, remaining))

        return self._turn_result(
            outcome="incomplete",
            session_id=request.session_id,
            submission_state="not_attempted",
            stop_requested=False,
            cursor=cursor,
            last_seq=last_seq,
            pending_approval_id=None,
            observed=observed,
        )

    def stop_turn(
        self,
        request: AgentControllerStopRequest,
        *,
        drain_timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
    ) -> AgentControllerStopResult:
        """Request Stop at most once and require bounded terminal evidence.

        An already-idle session is only observed, and an already-stopping
        session is never sent a duplicate request. A transport-ambiguous Stop
        is likewise never retried; observation may still reconcile it.
        """

        if not 0.1 <= drain_timeout_seconds <= 30:
            raise AgentControllerError("controller_drain_timeout_invalid")
        if not 0.01 <= poll_interval_seconds <= 5:
            raise AgentControllerError("controller_poll_interval_invalid")

        self.discover()
        session = self._session(request.session_id)
        if request.after > session.last_seq:
            raise AgentControllerError("controller_event_cursor_invalid")

        observed: list[AgentEvent] = []
        cursor = request.after
        last_seq = session.last_seq
        pending_approval_id = session.pending_approval_id
        stop_request_state: ControllerStopRequestState = "not_attempted"
        initially_active = bool(
            session.running
            or session.closing
            or session.stopping
            or session.pending_approval_id is not None
        )
        if session.cleanup_unconfirmed:
            return self._stop_result(
                outcome="cleanup_unconfirmed",
                session_id=request.session_id,
                stop_request_state=stop_request_state,
                cursor=cursor,
                last_seq=last_seq,
                pending_approval_id=session.pending_approval_id,
                observed=observed,
            )

        if initially_active and not session.stopping:
            stop_request_state = "accepted"
            try:
                _, stopped_payload = self._request_json(
                    "POST",
                    f"/v1/agent/sessions/{request.session_id}/stop",
                    expected_statuses=frozenset({200}),
                )
            except AgentControllerTransportUnavailable:
                stop_request_state = "uncertain"
            else:
                try:
                    stopped = AgentSessionView.model_validate(stopped_payload)
                except ValidationError:
                    stop_request_state = "uncertain"
                else:
                    if stopped.session_id != request.session_id:
                        stop_request_state = "uncertain"
                    else:
                        last_seq = max(last_seq, stopped.last_seq)
                        pending_approval_id = stopped.pending_approval_id
                        if stopped.cleanup_unconfirmed:
                            return self._stop_result(
                                outcome="cleanup_unconfirmed",
                                session_id=request.session_id,
                                stop_request_state=stop_request_state,
                                cursor=cursor,
                                last_seq=last_seq,
                                pending_approval_id=stopped.pending_approval_id,
                                observed=observed,
                            )

        deadline = self._clock() + drain_timeout_seconds
        while self._clock() < deadline:
            try:
                page = self._events(request.session_id, cursor)
            except AgentControllerTransportUnavailable:
                return self._stop_result(
                    outcome=(
                        "stop_uncertain"
                        if stop_request_state == "uncertain"
                        else "incomplete"
                    ),
                    session_id=request.session_id,
                    stop_request_state=stop_request_state,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=pending_approval_id,
                    observed=observed,
                )
            cursor = self._absorb_page(page, cursor=cursor, observed=observed)
            last_seq = page.last_seq
            pending_approval_id = page.pending_approval_id
            if page.cleanup_unconfirmed:
                return self._stop_result(
                    outcome="cleanup_unconfirmed",
                    session_id=request.session_id,
                    stop_request_state=stop_request_state,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=page.pending_approval_id,
                    observed=observed,
                )
            if self._terminal(page, cursor):
                if stop_request_state == "uncertain":
                    stop_request_state = "reconciled"
                return self._stop_result(
                    outcome=("stopped" if initially_active else "already_settled"),
                    session_id=request.session_id,
                    stop_request_state=stop_request_state,
                    cursor=cursor,
                    last_seq=last_seq,
                    pending_approval_id=None,
                    observed=observed,
                )
            remaining = deadline - self._clock()
            if remaining > 0:
                self._sleep(min(poll_interval_seconds, remaining))

        return self._stop_result(
            outcome=(
                "stop_uncertain"
                if stop_request_state == "uncertain"
                else "incomplete"
            ),
            session_id=request.session_id,
            stop_request_state=stop_request_state,
            cursor=cursor,
            last_seq=last_seq,
            pending_approval_id=pending_approval_id,
            observed=observed,
        )


__all__ = (
    "AGENT_CONTROLLER_CLI_CONTRACT",
    "AGENT_CONTROLLER_CLOSE_CONTRACT",
    "AGENT_CONTROLLER_EXPORT_CONTRACT",
    "AGENT_CONTROLLER_FORK_CONTRACT",
    "AGENT_CONTROLLER_OPEN_CONTRACT",
    "AGENT_CONTROLLER_RESUME_CONTRACT",
    "AGENT_CONTROLLER_RUNTIME_CONTRACT",
    "AGENT_CONTROLLER_STOP_CONTRACT",
    "AGENT_CONTROLLER_TURN_CONTRACT",
    "AgentControllerAttachmentStageRequest",
    "AgentControllerClient",
    "AgentControllerCloseChatRequest",
    "AgentControllerCloseChatResult",
    "AgentControllerError",
    "AgentControllerExportChatRequest",
    "AgentControllerExportChatResult",
    "AgentControllerForkChatRequest",
    "AgentControllerForkChatResult",
    "AgentControllerHttpResponse",
    "AgentControllerInvocationResult",
    "AgentControllerInvokeRequest",
    "AgentControllerLifecycleProposalRequest",
    "AgentControllerOpenChatRequest",
    "AgentControllerOpenChatResult",
    "AgentControllerRuntimeRequest",
    "AgentControllerRuntimeResult",
    "AgentControllerResumeChatRequest",
    "AgentControllerResumeChatResult",
    "AgentControllerStopRequest",
    "AgentControllerStopResult",
    "AgentControllerTransport",
    "AgentControllerTransportUnavailable",
    "AgentControllerTurnRequest",
    "AgentControllerTurnResult",
    "AgentControllerWaitRequest",
    "AgentControllerWriteProposalRequest",
    "AgentControllerWriteTransactionProposalRequest",
    "MAX_CONTROLLER_REQUEST_BYTES",
    "MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES",
    "MAX_CONTROLLER_RESPONSE_BYTES",
)
