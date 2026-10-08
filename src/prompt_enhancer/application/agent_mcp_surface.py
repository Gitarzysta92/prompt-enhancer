"""Provider-neutral MCP tools for the already-running local Agent service.

This surface is intentionally separate from the read-only analytics MCP
surface.  It owns no process and cannot approve protected actions.  Sensitive
tools require a task-specific egress receipt on every call; runtime lifecycle
is both server-opt-in and per-call opt-in.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ..domain import StrictModel
from .agent_controller_client import (
    AgentControllerAttachmentStageRequest,
    AgentControllerClient,
    AgentControllerCloseChatRequest,
    AgentControllerError,
    AgentControllerExportChatRequest,
    AgentControllerForkChatRequest,
    AgentControllerInvokeRequest,
    AgentControllerLifecycleProposalRequest,
    AgentControllerOpenChatRequest,
    AgentControllerResumeChatRequest,
    AgentControllerRuntimeRequest,
    AgentControllerStopRequest,
    AgentControllerStopResult,
    AgentControllerTurnRequest,
    AgentControllerTurnResult,
    AgentControllerWaitRequest,
    AgentControllerWriteProposalRequest,
    AgentControllerWriteTransactionProposalRequest,
)
from .agent_controller_ownership import (
    AcceptAgentControllerHandoff,
    AgentControllerOperation,
    AgentControllerOwnership,
    AgentControllerOwnershipError,
    AgentControllerOwnershipService,
    OfferAgentControllerHandoff,
)
from .agent_artifacts import (
    MAX_AGENT_ARTIFACT_LIST,
    AgentArtifactCapturePreview,
    AgentArtifactDetail,
    AgentArtifactExport,
    AgentArtifactList,
    ExportAgentArtifact,
    PreviewAgentArtifactCapture,
)
from .agent_attachment_contracts import (
    AGENT_DOCUMENT_MEDIA_TYPES,
    MAX_AGENT_ATTACHMENT_MESSAGE_BYTES,
    MAX_AGENT_ATTACHMENT_SESSION_BYTES,
    MAX_AGENT_AUDIO_BYTES,
    MAX_AGENT_AUDIO_DURATION_MS,
    MAX_AGENT_DOCUMENT_BYTES,
    MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS,
    MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS,
    MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS,
    MAX_AGENT_IMAGE_BYTES,
    MAX_AGENT_IMAGE_DIMENSION,
    MAX_AGENT_IMAGE_PIXELS,
    MAX_AGENT_MESSAGE_ATTACHMENTS,
    MAX_AGENT_STAGED_ATTACHMENTS,
    MAX_AGENT_TEXT_DOCUMENT_BYTES,
    AgentAttachment,
    AgentAttachmentDocumentFormat,
    AgentAttachmentKind,
    AgentAttachmentList,
    AgentAttachmentMediaType,
    AgentAttachmentOmittedFeature,
    AgentAttachmentRouting,
    StageInlineAgentAttachment,
)
from .agent_catalog import (
    AGENT_CATALOG_SESSION_ID_PATTERN,
    AGENT_PROJECT_ID_PATTERN,
    AgentCatalogSessionList,
    AgentCatalogSessionRecord,
    AgentProjectList,
    AgentProjectRecord,
    AgentRetentionPolicy,
    CreateAgentProject,
    UpdateAgentCatalogSession,
    UpdateAgentProject,
)
from .agent_surface import AgentSurfaceError, ToolSpec
from .agent_session_context import AgentSessionContextStatus
from .local_agent import (
    AgentEvents,
    AgentLifecycleProposalReceipt,
    AgentModelParameters,
    AgentSessionView,
    AgentWriteProposalReceipt,
    AgentWriteTransactionProposalReceipt,
)
from .local_agent_changes import AgentChangeDiff, AgentChangeSet
from .local_agent_discovery import WorkspaceDiscovery
from .local_agent_editor import WorkspaceFile, WorkspaceSearchResult, WorkspaceTree
from .local_models import (
    DeviceMode,
    LocalModelCompatibilityCatalog,
    LocalModelCompatibilityReason,
    LocalModelCompatibilityState,
    LocalRuntimeSelection,
    RuntimeCapabilities,
    RuntimeCleanupState,
    RuntimeContextStatus,
    RuntimeCoordinatorState,
    LocalRuntimeCoordinatorStatus,
)


AGENT_MCP_CONTRACT_VERSION = "prompt-enhancer-agent-mcp.v24"
MAX_AGENT_MCP_DEADLINE_SECONDS = 300.0
MAX_AGENT_MCP_CONTEXT_MODELS = 200
AGENT_MCP_CONTEXT_CONTRACT_VERSION = "agent-mcp-context.v3"
_RETAINED_EVENT_KINDS = frozenset(
    {"user", "assistant", "tool_call", "tool_result", "status", "error", "done"}
)


class AgentMcpEgressAuthorization(StrictModel):
    """Task-specific confirmation before sensitive values enter a model context."""

    task_authorized: Literal[True]
    redaction_previewed: Literal[True]
    destination: Literal["local_controller", "model_context"]

    @field_validator("task_authorized", "redaction_previewed", mode="before")
    @classmethod
    def require_exact_true(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("authorization receipt must contain exact true")
        return value


class AgentMcpDiscoverInput(StrictModel):
    refresh: bool = Field(default=False, strict=True)


class AgentMcpInvokeInput(StrictModel):
    egress: AgentMcpEgressAuthorization
    request: AgentControllerInvokeRequest
    mutation_authorized: bool = Field(default=False, strict=True)


class AgentMcpOpenInput(StrictModel):
    egress: AgentMcpEgressAuthorization
    request: AgentControllerOpenChatRequest


class AgentMcpResumeInput(StrictModel):
    """Resume one revision-bound retained chat without restoring authority."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerResumeChatRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("chat resume authorization must be exact true")
        return value


class AgentMcpForkInput(StrictModel):
    """Create or reconcile one idempotent retained-history branch."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerForkChatRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("chat fork authorization must be exact true")
        return value


class AgentMcpExportInput(StrictModel):
    """Export one complete exact-revision retained history without local paths."""

    egress: AgentMcpEgressAuthorization
    request: AgentControllerExportChatRequest


class AgentMcpCloseInput(StrictModel):
    """Close one exact idle live chat while retaining its durable record."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerCloseChatRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("chat close authorization must be exact true")
        return value


def _normalized_catalog_text(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError("catalog text must contain visible characters")
    return normalized


class AgentMcpCatalogListProjectsRequest(StrictModel):
    action: Literal["list_projects"]
    search: str | None = Field(default=None, min_length=1, max_length=120)
    include_archived: bool = Field(default=False, strict=True)
    limit: int = Field(default=200, ge=1, le=200, strict=True)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        return None if value is None else _normalized_catalog_text(value)


class AgentMcpCatalogGetProjectRequest(StrictModel):
    action: Literal["get_project"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)


class AgentMcpCatalogCreateProjectRequest(StrictModel):
    action: Literal["create_project"]
    mutation_authorized: Literal[True]
    name: str = Field(min_length=1, max_length=120)

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("catalog mutation authorization must be exact true")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalized_catalog_text(value)


class AgentMcpCatalogUpdateProjectRequest(StrictModel):
    action: Literal["update_project"]
    mutation_authorized: Literal[True]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    expected_revision: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = Field(default=None, strict=True)
    archived: bool | None = Field(default=None, strict=True)

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("catalog mutation authorization must be exact true")
        return value

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _normalized_catalog_text(value)

    @model_validator(mode="after")
    def require_update(self) -> "AgentMcpCatalogUpdateProjectRequest":
        UpdateAgentProject(
            expected_revision=self.expected_revision,
            name=self.name,
            pinned=self.pinned,
            archived=self.archived,
        )
        return self


class AgentMcpCatalogListChatsRequest(StrictModel):
    action: Literal["list_chats"]
    project_id: str | None = Field(default=None, pattern=AGENT_PROJECT_ID_PATTERN)
    search: str | None = Field(default=None, min_length=1, max_length=120)
    include_archived: bool = Field(default=False, strict=True)
    limit: int = Field(default=200, ge=1, le=200, strict=True)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        return None if value is None else _normalized_catalog_text(value)


class AgentMcpCatalogGetChatRequest(StrictModel):
    action: Literal["get_chat"]
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)


class AgentMcpCatalogUpdateChatRequest(StrictModel):
    action: Literal["update_chat"]
    mutation_authorized: Literal[True]
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    expected_revision: int = Field(ge=1, strict=True)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = Field(default=None, pattern=AGENT_PROJECT_ID_PATTERN)
    model_alias: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    pinned: bool | None = Field(default=None, strict=True)
    archived: bool | None = Field(default=None, strict=True)

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("catalog mutation authorization must be exact true")
        return value

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return None if value is None else _normalized_catalog_text(value)

    @model_validator(mode="after")
    def require_update(self) -> "AgentMcpCatalogUpdateChatRequest":
        UpdateAgentCatalogSession(
            expected_revision=self.expected_revision,
            title=self.title,
            project_id=self.project_id,
            model_alias=self.model_alias,
            pinned=self.pinned,
            archived=self.archived,
        )
        return self


AgentMcpCatalogRequest = Annotated[
    AgentMcpCatalogListProjectsRequest
    | AgentMcpCatalogGetProjectRequest
    | AgentMcpCatalogCreateProjectRequest
    | AgentMcpCatalogUpdateProjectRequest
    | AgentMcpCatalogListChatsRequest
    | AgentMcpCatalogGetChatRequest
    | AgentMcpCatalogUpdateChatRequest,
    Field(discriminator="action"),
]


class AgentMcpCatalogInput(StrictModel):
    """Browse and manage durable project/chat metadata without deletion authority."""

    egress: AgentMcpEgressAuthorization
    request: AgentMcpCatalogRequest


class AgentMcpHistoryInput(StrictModel):
    """Read one bounded page from an exact retained local conversation."""

    egress: AgentMcpEgressAuthorization
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    after: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=200, ge=1, le=500, strict=True)


class AgentMcpArtifactsListRequest(StrictModel):
    action: Literal["list"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    limit: int = Field(
        default=MAX_AGENT_ARTIFACT_LIST,
        ge=1,
        le=MAX_AGENT_ARTIFACT_LIST,
        strict=True,
    )


class AgentMcpArtifactsGetRequest(StrictModel):
    action: Literal["get"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class AgentMcpArtifactsPreviewCaptureRequest(PreviewAgentArtifactCapture):
    action: Literal["preview_capture"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)


class AgentMcpArtifactsExportRequest(ExportAgentArtifact):
    action: Literal["export"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    artifact_id: str = Field(pattern=r"^[0-9a-f]{32}$")


AgentMcpArtifactsRequest = Annotated[
    AgentMcpArtifactsListRequest
    | AgentMcpArtifactsGetRequest
    | AgentMcpArtifactsPreviewCaptureRequest
    | AgentMcpArtifactsExportRequest,
    Field(discriminator="action"),
]


class AgentMcpArtifactsInput(StrictModel):
    """Read or export artifact metadata, or inspect capture, without file bytes."""

    egress: AgentMcpEgressAuthorization
    request: AgentMcpArtifactsRequest


class AgentMcpStageAttachmentInput(StrictModel):
    """Stage caller-supplied media without granting local path authority."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    attachment: StageInlineAgentAttachment

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("attachment staging authorization must be exact true")
        return value


class AgentMcpProposeInput(StrictModel):
    """Offer an exact write for native review without apply authority."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerWriteProposalRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("write proposal authorization must be exact true")
        return value


class AgentMcpProposeTransactionInput(StrictModel):
    """Offer an exact create/edit change set for one native review."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerWriteTransactionProposalRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("transaction proposal authorization must be exact true")
        return value


class AgentMcpProposeLifecycleInput(StrictModel):
    """Offer one move/folder/recoverable-trash action for native review."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerLifecycleProposalRequest

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("lifecycle proposal authorization must be exact true")
        return value


class AgentMcpContextRuntimeRequest(StrictModel):
    action: Literal["runtime"]


class AgentMcpContextChatRequest(StrictModel):
    action: Literal["chat"]
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)


AgentMcpContextRequest = Annotated[
    AgentMcpContextRuntimeRequest | AgentMcpContextChatRequest,
    Field(discriminator="action"),
]


class AgentMcpContextInput(StrictModel):
    """Read a sanitized sequential snapshot of runtime and optional live-chat truth."""

    egress: AgentMcpEgressAuthorization
    request: AgentMcpContextRequest


class AgentMcpModelCompatibilityView(StrictModel):
    """Path-free compatibility facts needed to choose a registered model."""

    alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    state: LocalModelCompatibilityState
    reason_code: LocalModelCompatibilityReason
    architecture: str | None = Field(default=None, min_length=1, max_length=120)
    tokenizer_model: str | None = Field(default=None, min_length=1, max_length=120)
    training_context_size: int | None = Field(default=None, ge=1, le=16_777_216)
    execution_state: Literal["verified", "failed", "not_run"]
    context_counter_state: Literal["verified", "unsupported", "failed", "not_run"]


class AgentMcpRuntimeAdapterView(StrictModel):
    adapter_id: str = Field(min_length=1, max_length=64)
    adapter_version: str = Field(min_length=1, max_length=64)
    runtime_version: str | None = Field(default=None, max_length=120)
    runtime_identity_state: Literal["verified", "unknown"]
    capability_probe_version: str = Field(min_length=1, max_length=64)


class AgentMcpModelCatalogView(StrictModel):
    adapter: AgentMcpRuntimeAdapterView
    installed_count: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=MAX_AGENT_MCP_CONTEXT_MODELS)
    truncated: bool
    models: tuple[AgentMcpModelCompatibilityView, ...] = Field(
        max_length=MAX_AGENT_MCP_CONTEXT_MODELS
    )

    @model_validator(mode="after")
    def coherent_counts(self) -> "AgentMcpModelCatalogView":
        if (
            self.returned_count != len(self.models)
            or self.truncated is not (self.installed_count > self.returned_count)
            or self.returned_count > self.installed_count
        ):
            raise ValueError("MCP model catalog counts are incoherent")
        return self


class AgentMcpRuntimeView(StrictModel):
    revision: int = Field(ge=0)
    state: RuntimeCoordinatorState
    requested: LocalRuntimeSelection | None = None
    served: LocalRuntimeSelection | None = None
    cleanup_state: RuntimeCleanupState
    process_exit_confirmed: bool
    capabilities: RuntimeCapabilities
    context: RuntimeContextStatus
    context_binding: Literal["runtime_global_last_request"] = (
        "runtime_global_last_request"
    )
    active_requests: int = Field(ge=0)
    last_error_code: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    accepted_placements: tuple[DeviceMode, ...] = (
        DeviceMode.GPU,
        DeviceMode.SPLIT,
        DeviceMode.CPU,
    )

    @model_validator(mode="after")
    def coherent_served_runtime(self) -> "AgentMcpRuntimeView":
        if self.accepted_placements != (
            DeviceMode.GPU,
            DeviceMode.SPLIT,
            DeviceMode.CPU,
        ):
            raise ValueError("MCP placement vocabulary is incomplete")
        if self.state is RuntimeCoordinatorState.READY and self.served is None:
            raise ValueError("ready MCP runtime requires a served selection")
        return self


class AgentMcpAttachmentCapabilityView(StrictModel):
    image_input: bool
    audio_input: bool
    document_input: bool
    microphone_recording: bool
    image_media_types: tuple[Literal["image/png", "image/jpeg"], ...]
    audio_media_types: tuple[Literal["audio/wav"], ...]
    document_media_types: tuple[AgentAttachmentMediaType, ...]
    document_formats: tuple[AgentAttachmentDocumentFormat, ...]
    document_routing: Literal["local_text_projection"] = "local_text_projection"
    pdf_input: Literal[False] = False
    original_document_bytes_to_model: Literal[False] = False
    max_message_attachments: int = Field(ge=1)
    max_staged_attachments: int = Field(ge=1)
    max_message_bytes: int = Field(ge=1)
    max_session_bytes: int = Field(ge=1)
    max_image_bytes: int = Field(ge=1)
    max_image_dimension: int = Field(ge=1)
    max_image_pixels: int = Field(ge=1)
    max_audio_bytes: int = Field(ge=1)
    max_audio_duration_ms: int = Field(ge=1)
    max_document_bytes: int = Field(ge=1)
    max_text_document_bytes: int = Field(ge=1)
    max_document_projection_characters: int = Field(ge=1)
    max_document_preview_characters: int = Field(ge=1)
    max_document_message_characters: int = Field(ge=1)

    @model_validator(mode="after")
    def coherent_modalities(self) -> "AgentMcpAttachmentCapabilityView":
        if self.microphone_recording and not self.audio_input:
            raise ValueError("recording requires verified audio input")
        if bool(self.image_media_types) is not self.image_input:
            raise ValueError("image formats require verified image input")
        if bool(self.audio_media_types) is not self.audio_input:
            raise ValueError("audio formats require verified audio input")
        expected_document_formats = (
            tuple(AGENT_DOCUMENT_MEDIA_TYPES)
            if self.document_input
            else ()
        )
        expected_document_media_types = (
            tuple(AGENT_DOCUMENT_MEDIA_TYPES.values())
            if self.document_input
            else ()
        )
        if (
            self.document_formats != expected_document_formats
            or self.document_media_types != expected_document_media_types
        ):
            raise ValueError("document formats require verified text input")
        return self


class AgentMcpStagedAttachmentView(StrictModel):
    attachment_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    model_alias: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    kind: AgentAttachmentKind
    media_type: AgentAttachmentMediaType
    display_name: str = Field(min_length=1, max_length=120)
    byte_size: int = Field(strict=True, ge=1, le=MAX_AGENT_AUDIO_BYTES)
    width: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_IMAGE_DIMENSION)
    height: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_IMAGE_DIMENSION)
    duration_ms: int | None = Field(default=None, strict=True, ge=1, le=MAX_AGENT_AUDIO_DURATION_MS)
    sample_rate_hz: int | None = Field(default=None, strict=True, ge=8_000, le=48_000)
    channels: int | None = Field(default=None, strict=True, ge=1, le=2)
    routing: AgentAttachmentRouting
    document_format: AgentAttachmentDocumentFormat | None = None
    projected_characters: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS,
    )
    projection_truncated: bool | None = None
    omitted_features: tuple[AgentAttachmentOmittedFeature, ...] = Field(
        default=(),
        max_length=6,
    )
    source: Literal["file", "microphone", "external_agent"]
    expires_at: datetime

    @model_validator(mode="after")
    def coherent_attachment_metadata(self) -> "AgentMcpStagedAttachmentView":
        image_metadata = (self.width, self.height)
        audio_metadata = (self.duration_ms, self.sample_rate_hz, self.channels)
        document_metadata = (
            self.document_format,
            self.projected_characters,
            self.projection_truncated,
        )
        if self.kind == "image":
            coherent = (
                self.media_type in {"image/png", "image/jpeg"}
                and all(value is not None for value in image_metadata)
                and all(value is None for value in audio_metadata)
                and self.routing == "native_multimodal"
                and all(value is None for value in document_metadata)
                and not self.omitted_features
            )
        elif self.kind == "audio":
            coherent = (
                self.media_type == "audio/wav"
                and all(value is None for value in image_metadata)
                and all(value is not None for value in audio_metadata)
                and self.routing == "native_multimodal"
                and all(value is None for value in document_metadata)
                and not self.omitted_features
            )
        else:
            coherent = (
                self.document_format is not None
                and self.media_type in set(AGENT_DOCUMENT_MEDIA_TYPES.values())
                and AGENT_DOCUMENT_MEDIA_TYPES.get(self.document_format)
                == self.media_type
                and all(value is None for value in (*image_metadata, *audio_metadata))
                and self.routing == "local_text_projection"
                and self.projected_characters is not None
                and self.projection_truncated is not None
                and tuple(dict.fromkeys(self.omitted_features))
                == self.omitted_features
                and (
                    self.document_format
                    not in {"plain_text", "markdown", "json", "csv", "tsv"}
                    or not self.omitted_features
                )
            )
        if not coherent:
            raise ValueError("MCP staged attachment metadata is inconsistent")
        return self


class AgentMcpChatContextView(StrictModel):
    project_id: str = Field(pattern=AGENT_PROJECT_ID_PATTERN)
    session_id: str = Field(pattern=AGENT_CATALOG_SESSION_ID_PATTERN)
    configured_model_alias: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    effective_model_alias: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    )
    selected_model_ready: bool
    parameters: AgentModelParameters
    retention_policy: AgentRetentionPolicy
    allow_writes: bool
    allow_commands: bool
    allow_web: bool
    max_steps: int = Field(ge=1)
    command_timeout_seconds: int = Field(ge=1)
    running: bool
    closing: bool
    stopping: bool
    cleanup_unconfirmed: bool
    approval_pending: bool
    turns: int = Field(ge=0)
    history_revision: int = Field(ge=0)
    recovery_state: Literal["current", "recovered", "interrupted"]
    authority_revalidated: bool
    history_write_failed: bool
    context: AgentSessionContextStatus
    selected_chat_context_proven: bool
    staged_attachments: tuple[AgentMcpStagedAttachmentView, ...] = Field(
        max_length=MAX_AGENT_STAGED_ATTACHMENTS
    )

    @model_validator(mode="after")
    def coherent_context_binding(self) -> "AgentMcpChatContextView":
        if (
            self.context.session_id != self.session_id
            or self.selected_chat_context_proven
            is not (self.context.binding_state == "bound")
            or (
                self.context.binding_state == "bound"
                and self.effective_model_alias is not None
                and self.context.model_alias != self.effective_model_alias
            )
        ):
            raise ValueError("MCP chat context binding is incoherent")
        return self


class AgentMcpContextView(StrictModel):
    contract_version: Literal["agent-mcp-context.v3"] = (
        AGENT_MCP_CONTEXT_CONTRACT_VERSION
    )
    snapshot_consistency: Literal["sequential_non_atomic"] = "sequential_non_atomic"
    runtime: AgentMcpRuntimeView
    models: AgentMcpModelCatalogView
    attachments: AgentMcpAttachmentCapabilityView
    chat: AgentMcpChatContextView | None = None


AgentMcpWorkspaceAction = Literal[
    "inspect",
    "list",
    "search",
    "read",
    "changes",
    "diff",
]


class AgentMcpWorkspaceInput(StrictModel):
    """Read one bounded workspace view without creating mutation authority."""

    egress: AgentMcpEgressAuthorization
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    action: AgentMcpWorkspaceAction
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    query: str | None = Field(default=None, min_length=1, max_length=1024)
    glob: str | None = Field(default=None, min_length=1, max_length=1024)
    regex: bool = Field(default=False, strict=True)

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str | None) -> str | None:
        if value is None or value == ".":
            return value
        parts = value.split("/")
        if (
            value.startswith("/")
            or "\\" in value
            or ":" in value
            or "?" in value
            or "#" in value
            or any(part in {"", ".", ".."} for part in parts)
            or any(
                ord(character) < 32
                or ord(character) == 127
                or 0xD800 <= ord(character) <= 0xDFFF
                for character in value
            )
        ):
            raise ValueError("workspace MCP path must stay relative")
        return value

    @field_validator("query")
    @classmethod
    def safe_search_query(cls, value: str | None) -> str | None:
        if value is not None and any(
            character in {"\x00", "\r", "\n"}
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        ):
            raise ValueError("workspace MCP search query was invalid")
        return value

    @field_validator("glob")
    @classmethod
    def safe_search_glob(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if (
            value.startswith("/")
            or value.endswith("/")
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in parts)
            or any("**" in part and part != "**" for part in parts)
            or any(
                ord(character) < 32
                or ord(character) == 127
                or 0xD800 <= ord(character) <= 0xDFFF
                for character in value
            )
        ):
            raise ValueError("workspace MCP search glob must stay relative")
        return value

    @model_validator(mode="after")
    def coherent_action(self) -> "AgentMcpWorkspaceInput":
        if self.action in {"inspect", "search", "changes"} and self.path is not None:
            raise ValueError("workspace action does not accept a path")
        if self.action in {"read", "diff"} and self.path in {None, "."}:
            raise ValueError("workspace action requires a file path")
        if self.action == "search":
            if self.query is None:
                raise ValueError("workspace search requires a query")
        elif self.query is not None or self.glob is not None or self.regex:
            raise ValueError("workspace search fields require the search action")
        return self


class AgentMcpTurnInput(StrictModel):
    egress: AgentMcpEgressAuthorization
    request: AgentControllerTurnRequest
    deadline_seconds: float = Field(
        default=120.0,
        ge=0.05,
        le=MAX_AGENT_MCP_DEADLINE_SECONDS,
    )
    drain_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)


class AgentMcpWaitInput(StrictModel):
    egress: AgentMcpEgressAuthorization
    request: AgentControllerWaitRequest
    deadline_seconds: float = Field(
        default=120.0,
        ge=0.05,
        le=MAX_AGENT_MCP_DEADLINE_SECONDS,
    )


class AgentMcpStopInput(StrictModel):
    """Explicit authority to stop and reconcile one exact live Agent turn."""

    egress: AgentMcpEgressAuthorization
    mutation_authorized: Literal[True]
    request: AgentControllerStopRequest
    drain_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)

    @field_validator("mutation_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("turn Stop authorization must be exact true")
        return value


class AgentMcpControlInput(StrictModel):
    """Read or transfer one exact project-scoped controller ownership."""

    egress: AgentMcpEgressAuthorization
    action: Literal["status", "offer_handoff", "accept_handoff", "release"]
    session_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    target_connection_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )
    mutation_authorized: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def exact_action_shape(self) -> "AgentMcpControlInput":
        mutation = self.action != "status"
        if self.mutation_authorized is not mutation:
            raise ValueError("controller mutation authorization is incoherent")
        if self.action == "status":
            if self.expected_revision is not None or self.target_connection_id is not None:
                raise ValueError("controller status accepts only a session identity")
        elif self.action == "offer_handoff":
            if self.expected_revision is None or self.target_connection_id is None:
                raise ValueError("controller handoff offer needs revision and target")
        elif (
            self.expected_revision is None
            or self.target_connection_id is not None
        ):
            raise ValueError("controller action shape is invalid")
        return self


class AgentMcpRuntimeInput(StrictModel):
    egress: AgentMcpEgressAuthorization
    model_lifecycle_authorized: Literal[True]
    request: AgentControllerRuntimeRequest

    @field_validator("model_lifecycle_authorized", mode="before")
    @classmethod
    def require_exact_authorization(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("model lifecycle authorization must be exact true")
        return value


class AgentMcpSurfaceError(AgentSurfaceError):
    """Content-free Agent-controller failure safe for MCP serialization."""


class AgentMcpSurface:
    """Expose finite controller operations as standard MCP tools."""

    def __init__(
        self,
        client: AgentControllerClient,
        *,
        allow_model_lifecycle: bool = False,
        scope_project_id: str | None = None,
        controller_connection_id: str | None = None,
        controller_ownership: AgentControllerOwnershipService | None = None,
    ) -> None:
        identity_ready = (
            scope_project_id is not None
            and controller_connection_id is not None
            and controller_ownership is not None
        )
        if any(
            value is not None
            for value in (controller_connection_id, controller_ownership)
        ) and not identity_ready:
            raise ValueError(
                "controller ownership needs connection, project, and service"
            )
        self._client = client
        self._allow_model_lifecycle = allow_model_lifecycle
        self._scope_project_id = scope_project_id
        self._controller_connection_id = controller_connection_id
        self._controller_ownership = controller_ownership

    def _require_project_scope(self, project_id: str) -> None:
        if self._scope_project_id is not None and project_id != self._scope_project_id:
            raise AgentMcpSurfaceError("agent_mcp_scope_violation")

    def _require_session_scope(self, session_id: str) -> None:
        if self._scope_project_id is None:
            return
        try:
            invoked = self._client.invoke(
                AgentControllerInvokeRequest(
                    operation="get_catalog_session",
                    path_parameters={"session_id": session_id},
                )
            )
            record = AgentCatalogSessionRecord.model_validate(invoked.response)
        except (AgentControllerError, ValidationError):
            raise AgentMcpSurfaceError("agent_mcp_scope_violation") from None
        if (
            invoked.status_code != 200
            or record.session_id != session_id
            or record.project_id != self._scope_project_id
        ):
            raise AgentMcpSurfaceError("agent_mcp_scope_violation")

    def _enforce_scope(self, name: str, parsed: StrictModel) -> None:
        """Fail before a scoped bearer can address another project or chat."""

        if self._scope_project_id is None or name in {"agent_discover", "agent_runtime"}:
            return
        if name == "agent_invoke":
            raise AgentMcpSurfaceError("agent_mcp_scope_violation")
        if isinstance(parsed, AgentMcpOpenInput):
            if parsed.request.project_name is not None or parsed.request.project_id is None:
                raise AgentMcpSurfaceError("agent_mcp_scope_violation")
            self._require_project_scope(parsed.request.project_id)
            return
        if isinstance(parsed, (AgentMcpResumeInput, AgentMcpExportInput, AgentMcpCloseInput)):
            self._require_project_scope(parsed.request.project_id)
            self._require_session_scope(parsed.request.session_id)
            return
        if isinstance(parsed, AgentMcpForkInput):
            self._require_project_scope(parsed.request.project_id)
            self._require_project_scope(
                parsed.request.destination_project_id or parsed.request.project_id
            )
            self._require_session_scope(parsed.request.session_id)
            return
        if isinstance(parsed, AgentMcpCatalogInput):
            request = parsed.request
            if isinstance(request, AgentMcpCatalogCreateProjectRequest):
                raise AgentMcpSurfaceError("agent_mcp_scope_violation")
            if isinstance(
                request,
                (AgentMcpCatalogGetProjectRequest, AgentMcpCatalogUpdateProjectRequest),
            ):
                self._require_project_scope(request.project_id)
            elif isinstance(request, AgentMcpCatalogListChatsRequest):
                if request.project_id is not None:
                    self._require_project_scope(request.project_id)
            elif isinstance(
                request,
                (AgentMcpCatalogGetChatRequest, AgentMcpCatalogUpdateChatRequest),
            ):
                self._require_session_scope(request.session_id)
                if (
                    isinstance(request, AgentMcpCatalogUpdateChatRequest)
                    and request.project_id is not None
                ):
                    self._require_project_scope(request.project_id)
            return
        if isinstance(parsed, AgentMcpHistoryInput):
            self._require_project_scope(parsed.project_id)
            self._require_session_scope(parsed.session_id)
            return
        if isinstance(parsed, AgentMcpArtifactsInput):
            self._require_project_scope(parsed.request.project_id)
            self._require_session_scope(parsed.request.session_id)
            return
        if isinstance(parsed, AgentMcpStageAttachmentInput):
            self._require_project_scope(parsed.project_id)
            self._require_session_scope(parsed.session_id)
            return
        if isinstance(parsed, AgentMcpContextInput):
            if isinstance(parsed.request, AgentMcpContextChatRequest):
                self._require_project_scope(parsed.request.project_id)
                self._require_session_scope(parsed.request.session_id)
            return
        if isinstance(parsed, AgentMcpWorkspaceInput):
            self._require_session_scope(parsed.session_id)
            return
        if isinstance(parsed, AgentMcpControlInput):
            self._require_session_scope(parsed.session_id)
            return
        if isinstance(
            parsed,
            (
                AgentMcpProposeInput,
                AgentMcpProposeTransactionInput,
                AgentMcpProposeLifecycleInput,
                AgentMcpTurnInput,
                AgentMcpStopInput,
                AgentMcpWaitInput,
            ),
        ):
            self._require_session_scope(parsed.request.session_id)
            return
        raise AgentMcpSurfaceError("agent_mcp_scope_violation")

    def tools(self) -> tuple[ToolSpec, ...]:
        tools = (
            ToolSpec(
                name="agent_discover",
                description=(
                    "Verify the complete, content-free Prompt Enhancer Agent controller manifest. "
                    "Call this before using the typed tools. This starts no app, model, agent, or shell."
                ),
                input_model=AgentMcpDiscoverInput,
            ),
            ToolSpec(
                name="agent_invoke",
                description=(
                    "Invoke one manifest-declared JSON Agent operation against the already-running "
                    "loopback app. Every POST/PATCH needs mutation_authorized=true. DELETE, "
                    "native-only approvals, SSE, binary reads, and runtime switching are refused."
                ),
                input_model=AgentMcpInvokeInput,
            ),
            ToolSpec(
                name="agent_open",
                description=(
                    "Select one durable Agent project and open exactly one live chat. Unscoped local "
                    "transports may also create a project; project-bound HTTP connections cannot. "
                    "Creation is never retried after ambiguity and native authority is not restored."
                ),
                input_model=AgentMcpOpenInput,
            ),
            ToolSpec(
                name="agent_resume",
                description=(
                    "Resume one exact revision-bound retained Agent chat without restoring "
                    "file, command, web, approval, or other protected authority. A mutation is "
                    "attempted at most once and ambiguous delivery is reconciled read-only."
                ),
                input_model=AgentMcpResumeInput,
            ),
            ToolSpec(
                name="agent_fork",
                description=(
                    "Fork one exact revision-bound retained Agent history into an inert durable "
                    "chat without copying approvals, mutation authority, live tool state, staged "
                    "attachments, or artifacts. One byte-identical retry may reconcile an "
                    "ambiguous result through the caller-owned idempotency key."
                ),
                input_model=AgentMcpForkInput,
            ),
            ToolSpec(
                name="agent_export",
                description=(
                    "Export one complete exact-revision retained Agent history within a caller "
                    "event limit. The projection omits the workspace path, attachment bytes, "
                    "live approval state, raw tool payloads, and mutation authority."
                ),
                input_model=AgentMcpExportInput,
            ),
            ToolSpec(
                name="agent_close",
                description=(
                    "Close one exact idle live Agent chat without deleting its durable catalog "
                    "record or retained history. The close is sent at most once; ambiguous "
                    "delivery gets one read-only reconciliation and never a repeated DELETE."
                ),
                input_model=AgentMcpCloseInput,
            ),
            ToolSpec(
                name="agent_catalog",
                description=(
                    "Strictly browse durable Agent projects and chats or explicitly create, rename, "
                    "pin, move, archive, and restore their metadata with revision checks. This tool "
                    "is projected to one exact project for a project-bound HTTP connection and then "
                    "cannot create a project or move a chat across projects. It "
                    "cannot permanently delete a project, chat, or retained history; delete stays "
                    "in the native Agent UI. Use agent_open to create or focus a live chat."
                ),
                input_model=AgentMcpCatalogInput,
            ),
            ToolSpec(
                name="agent_history",
                description=(
                    "Read one bounded page of an exact chat's locally retained visible events. "
                    "The response excludes live approvals, raw tool arguments/results, and "
                    "reusable authority. This tool cannot export, resume, fork, edit, or delete."
                ),
                input_model=AgentMcpHistoryInput,
            ),
            ToolSpec(
                name="agent_artifacts",
                description=(
                    "List or get strict immutable artifact lineage metadata, export one selected "
                    "version's exact-readback lineage metadata, or preview one exact workspace file "
                    "as content-free path/type/size/digest metadata before native capture. No file "
                    "bytes or capture authority cross this tool. Use agent_workspace for returned "
                    "UTF-8 paths and the native viewer for image, PDF, or download-only content."
                ),
                input_model=AgentMcpArtifactsInput,
            ),
            ToolSpec(
                name="agent_stage_attachment",
                description=(
                    "Stage one caller-supplied PNG, JPEG, PCM WAV, UTF-8 text/data document, "
                    "or supported Office/ODT document for an exact project and live chat. "
                    "Documents are converted to a bounded inert local text projection; PDF is "
                    "not admitted and original document bytes never enter the model. The request "
                    "is integrity-bound inline data with no filesystem path or URL; "
                    "mutation_authorized=true is required. The response is metadata only and "
                    "returns no attachment bytes. Reference its attachment_id in agent_turn "
                    "after the native window shows the staged item."
                ),
                input_model=AgentMcpStageAttachmentInput,
            ),
            ToolSpec(
                name="agent_context",
                description=(
                    "Read a sanitized sequential snapshot of model compatibility, runtime state, "
                    "the runtime's exact last-request context evidence, placement vocabulary, "
                    "verified image/audio/document attachment capabilities, "
                    "and optionally one live chat with staged attachment metadata. This tool omits "
                    "workspace paths, instructions, attachment bytes, process IDs, and mutation authority. "
                    "Chat context evidence is exact only when its bound receipt proves the selected "
                    "session, turn, and model; otherwise it remains explicitly unmeasured. It never "
                    "counts tokens, loads a model, switches runtime, or stages attachments."
                ),
                input_model=AgentMcpContextInput,
            ),
            ToolSpec(
                name="agent_workspace",
                description=(
                    "Read one live chat's bounded workspace inventory, file tree, UTF-8 text "
                    "search, UTF-8 file, reviewed change set, or net diff. Search returns "
                    "relative paths, line numbers, bounded previews, and exact coverage/limit "
                    "evidence. This tool never creates, edits, moves, deletes, or applies a "
                    "file."
                ),
                input_model=AgentMcpWorkspaceInput,
            ),
            ToolSpec(
                name="agent_propose",
                description=(
                    "Offer one exact caller-authored UTF-8 file create or revision-bound edit "
                    "to an idle live chat. This never applies the file: Prompt Enhancer shows "
                    "the diff in its native approval card, and agent_wait observes the verified "
                    "or rejected result after the person decides. In a Save locally chat, only "
                    "a verified write receipt enters durable artifact lineage; proposal content "
                    "and approval data remain live-only. Request IDs are idempotent within the "
                    "live chat and altered replays are refused."
                ),
                input_model=AgentMcpProposeInput,
            ),
            ToolSpec(
                name="agent_propose_transaction",
                description=(
                    "Offer two to eight exact caller-authored absence-bound creates or "
                    "revision-bound edits to an idle live chat. Prompt Enhancer shows one "
                    "native review and publishes the set through its rollback-capable "
                    "transaction lane only after the person approves. Verified per-file receipts "
                    "become durable artifact lineage only in Save locally chats; proposal content "
                    "does not. This tool never applies directly and never retries an ambiguous "
                    "submission."
                ),
                input_model=AgentMcpProposeTransactionInput,
            ),
            ToolSpec(
                name="agent_propose_lifecycle",
                description=(
                    "Offer one exact directory create, no-overwrite directory or file move, "
                    "or revision-bound recoverable file trash to an idle live chat. Prompt "
                    "Enhancer shows the action in its native approval card; this tool never "
                    "applies directly, never permanently deletes, and never retries an "
                    "ambiguous submission. In a Save locally chat, a verified file move "
                    "advances a matching artifact under the same identity as an immutable "
                    "path version; directory moves do not project artifact lineage."
                ),
                input_model=AgentMcpProposeLifecycleInput,
            ),
            ToolSpec(
                name="agent_turn",
                description=(
                    "Submit exactly one message to an idle Agent chat and observe it for a bounded "
                    "deadline. Ambiguous submissions are never repeated. Pending protected work is "
                    "returned for the person to approve in the native Agent window."
                ),
                input_model=AgentMcpTurnInput,
            ),
            ToolSpec(
                name="agent_stop",
                description=(
                    "Stop one exact active Agent chat with explicit mutation authorization. "
                    "The Stop request is sent at most once, ambiguous delivery is never retried, "
                    "and success requires bounded terminal cleanup evidence."
                ),
                input_model=AgentMcpStopInput,
            ),
            ToolSpec(
                name="agent_wait",
                description=(
                    "Continue bounded observation from a prior turn cursor without sending another "
                    "message or requesting Stop. Use after the native owner resolves an approval."
                ),
                input_model=AgentMcpWaitInput,
            ),
        )
        if self._scope_project_id is not None:
            tools = tuple(tool for tool in tools if tool.name != "agent_invoke")
        if self._controller_ownership is not None:
            tools = tools + (
                ToolSpec(
                    name="agent_control",
                    description=(
                        "Read the exact owner of one project-scoped live chat, offer or accept "
                        "a revision-bound handoff to another active connection on the same "
                        "project, or release only objectively settled ownership. Handoff never "
                        "copies native approval, file, command, web, model, or MCP authority."
                    ),
                    input_model=AgentMcpControlInput,
                ),
            )
        if not self._allow_model_lifecycle:
            return tools
        return tools + (
            ToolSpec(
                name="agent_runtime",
                description=(
                    "Explicitly ask the already-running Prompt Enhancer app to load, switch, or stop "
                    "its one registered local model. Requires model_lifecycle_authorized=true; "
                    "mutation is attempted at most once and cleanup uncertainty remains visible."
                ),
                input_model=AgentMcpRuntimeInput,
            ),
        )

    @staticmethod
    def _payload(tool: str, result: Any) -> dict[str, Any]:
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        return {
            "contract_version": AGENT_MCP_CONTRACT_VERSION,
            "tool": tool,
            "result": result,
        }

    @staticmethod
    def _controller_error(error: AgentControllerError) -> AgentMcpSurfaceError:
        return AgentMcpSurfaceError(
            error.code,
            details={
                "http_status": error.http_status,
                "retryable": error.retryable,
            },
        )

    def _call_catalog(self, request: AgentMcpCatalogRequest) -> dict[str, Any]:
        query: dict[str, str | int | bool] = {}
        path_parameters: dict[str, str] = {}
        body: dict[str, Any] | None = None
        expected_status = 200
        command: CreateAgentProject | UpdateAgentProject | UpdateAgentCatalogSession | None = None

        if (
            isinstance(request, AgentMcpCatalogListProjectsRequest)
            and self._scope_project_id is not None
        ):
            operation = "list_projects"
            invoked = self._client.invoke(
                AgentControllerInvokeRequest(
                    operation="get_project",
                    path_parameters={"project_id": self._scope_project_id},
                )
            )
            try:
                project = AgentProjectRecord.model_validate(invoked.response)
            except ValidationError:
                raise AgentMcpSurfaceError("catalog_response_invalid") from None
            if (
                invoked.status_code != 200
                or project.project_id != self._scope_project_id
            ):
                raise AgentMcpSurfaceError("catalog_response_invalid")
            visible = (
                (request.include_archived or project.archived_at is None)
                and (
                    request.search is None
                    or request.search.casefold() in project.name.casefold()
                )
            )
            validated = AgentProjectList(projects=(project,) if visible else ())
            return {
                "action": request.action,
                "operation": operation,
                "status_code": invoked.status_code,
                "response": validated.model_dump(mode="json"),
            }
        if isinstance(request, AgentMcpCatalogListProjectsRequest):
            operation = "list_projects"
            query = {
                "include_archived": request.include_archived,
                "limit": request.limit,
            }
            if request.search is not None:
                query["search"] = request.search
            response_type = AgentProjectList
        elif isinstance(request, AgentMcpCatalogGetProjectRequest):
            operation = "get_project"
            path_parameters = {"project_id": request.project_id}
            response_type = AgentProjectRecord
        elif isinstance(request, AgentMcpCatalogCreateProjectRequest):
            operation = "create_project"
            command = CreateAgentProject(name=request.name)
            body = command.model_dump(mode="json")
            expected_status = 201
            response_type = AgentProjectRecord
        elif isinstance(request, AgentMcpCatalogUpdateProjectRequest):
            operation = "update_project"
            path_parameters = {"project_id": request.project_id}
            command = UpdateAgentProject(
                expected_revision=request.expected_revision,
                name=request.name,
                pinned=request.pinned,
                archived=request.archived,
            )
            body = command.model_dump(mode="json")
            response_type = AgentProjectRecord
        elif isinstance(request, AgentMcpCatalogListChatsRequest):
            if self._scope_project_id is not None and request.project_id is None:
                request = request.model_copy(
                    update={"project_id": self._scope_project_id}
                )
            operation = (
                "list_project_sessions"
                if request.project_id is not None
                else "list_catalog_sessions"
            )
            if request.project_id is not None:
                path_parameters = {"project_id": request.project_id}
            query = {
                "include_archived": request.include_archived,
                "limit": request.limit,
            }
            if request.search is not None:
                query["search"] = request.search
            response_type = AgentCatalogSessionList
        elif isinstance(request, AgentMcpCatalogGetChatRequest):
            operation = "get_catalog_session"
            path_parameters = {"session_id": request.session_id}
            response_type = AgentCatalogSessionRecord
        elif isinstance(request, AgentMcpCatalogUpdateChatRequest):
            operation = "update_catalog_session"
            path_parameters = {"session_id": request.session_id}
            command = UpdateAgentCatalogSession(
                expected_revision=request.expected_revision,
                title=request.title,
                project_id=request.project_id,
                model_alias=request.model_alias,
                pinned=request.pinned,
                archived=request.archived,
            )
            body = command.model_dump(mode="json")
            response_type = AgentCatalogSessionRecord
        else:  # discriminated parsing makes this unreachable; retain a closed failure
            raise AgentMcpSurfaceError("invalid_arguments")

        invoked = self._client.invoke(
            AgentControllerInvokeRequest(
                operation=operation,
                path_parameters=path_parameters,
                query=query,
                body=body,
            )
        )
        if (
            invoked.operation != operation
            or invoked.status_code != expected_status
            or invoked.response is None
        ):
            raise AgentMcpSurfaceError("catalog_response_invalid")
        try:
            validated = response_type.model_validate(invoked.response)
        except ValidationError:
            raise AgentMcpSurfaceError("catalog_response_invalid") from None

        if isinstance(request, AgentMcpCatalogListProjectsRequest):
            assert isinstance(validated, AgentProjectList)
            if len(validated.projects) > request.limit or (
                not request.include_archived
                and any(project.archived_at is not None for project in validated.projects)
            ):
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogGetProjectRequest):
            assert isinstance(validated, AgentProjectRecord)
            if validated.project_id != request.project_id:
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogCreateProjectRequest):
            assert isinstance(validated, AgentProjectRecord)
            assert isinstance(command, CreateAgentProject)
            if validated.name != command.name:
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogUpdateProjectRequest):
            assert isinstance(validated, AgentProjectRecord)
            assert isinstance(command, UpdateAgentProject)
            if (
                validated.project_id != request.project_id
                or validated.revision != command.expected_revision + 1
                or command.name is not None and validated.name != command.name
                or command.pinned is not None and validated.pinned is not command.pinned
                or command.archived is not None
                and (validated.archived_at is not None) is not command.archived
            ):
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogListChatsRequest):
            assert isinstance(validated, AgentCatalogSessionList)
            if (
                len(validated.sessions) > request.limit
                or request.project_id is not None
                and any(
                    session.project_id != request.project_id
                    for session in validated.sessions
                )
                or not request.include_archived
                and any(session.archived_at is not None for session in validated.sessions)
            ):
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogGetChatRequest):
            assert isinstance(validated, AgentCatalogSessionRecord)
            if validated.session_id != request.session_id:
                raise AgentMcpSurfaceError("catalog_response_invalid")
        elif isinstance(request, AgentMcpCatalogUpdateChatRequest):
            assert isinstance(validated, AgentCatalogSessionRecord)
            assert isinstance(command, UpdateAgentCatalogSession)
            if (
                validated.session_id != request.session_id
                or validated.revision != command.expected_revision + 1
                or command.title is not None and validated.title != command.title
                or command.project_id is not None
                and validated.project_id != command.project_id
                or command.model_alias is not None
                and validated.model_alias != command.model_alias
                or command.pinned is not None and validated.pinned is not command.pinned
                or command.archived is not None
                and (validated.archived_at is not None) is not command.archived
            ):
                raise AgentMcpSurfaceError("catalog_response_invalid")

        return {
            "action": request.action,
            "operation": operation,
            "status_code": invoked.status_code,
            "response": validated.model_dump(mode="json"),
        }

    def _call_history(self, request: AgentMcpHistoryInput) -> dict[str, Any]:
        operation = "read_retained_history"
        invoked = self._client.invoke(
            AgentControllerInvokeRequest(
                operation=operation,
                path_parameters={
                    "project_id": request.project_id,
                    "session_id": request.session_id,
                },
                query={"after": request.after, "limit": request.limit},
            )
        )
        if (
            invoked.operation != operation
            or invoked.status_code != 200
            or invoked.response is None
        ):
            raise AgentMcpSurfaceError("history_response_invalid")
        try:
            validated = AgentEvents.model_validate(invoked.response)
        except ValidationError:
            raise AgentMcpSurfaceError("history_response_invalid") from None

        sequences = [event.seq for event in validated.events]
        if (
            validated.session_id != request.session_id
            or validated.running
            or validated.closing
            or validated.stopping
            or validated.cleanup_unconfirmed
            or validated.pending_approval_id is not None
            or len(validated.events) > request.limit
            or validated.first_seq > validated.last_seq
            or sequences != sorted(set(sequences))
            or any(sequence <= request.after for sequence in sequences)
            or any(sequence > validated.last_seq for sequence in sequences)
            or (bool(sequences) and validated.first_seq > sequences[0])
            or any(
                event.kind not in _RETAINED_EVENT_KINDS
                or event.arguments is not None
                or event.approval_id is not None
                or event.preview is not None
                for event in validated.events
            )
        ):
            raise AgentMcpSurfaceError("history_response_invalid")

        return {
            "operation": operation,
            "project_id": request.project_id,
            "session_id": request.session_id,
            "after": request.after,
            "limit": request.limit,
            "status_code": invoked.status_code,
            "response": validated.model_dump(mode="json"),
        }

    def _call_artifacts(self, request: AgentMcpArtifactsRequest) -> dict[str, Any]:
        if isinstance(request, AgentMcpArtifactsListRequest):
            operation = "list_artifacts"
            path_parameters = {
                "project_id": request.project_id,
                "session_id": request.session_id,
            }
            query: dict[str, str | int | bool] = {"limit": request.limit}
            body: dict[str, Any] | None = None
            response_type = AgentArtifactList
        elif isinstance(request, AgentMcpArtifactsGetRequest):
            operation = "get_artifact"
            path_parameters = {
                "project_id": request.project_id,
                "session_id": request.session_id,
                "artifact_id": request.artifact_id,
            }
            query = {}
            body = None
            response_type = AgentArtifactDetail
        elif isinstance(request, AgentMcpArtifactsPreviewCaptureRequest):
            operation = "preview_artifact_capture"
            path_parameters = {
                "project_id": request.project_id,
                "session_id": request.session_id,
            }
            query = {}
            body = PreviewAgentArtifactCapture(
                path=request.path,
                title=request.title,
            ).model_dump(mode="json", exclude_none=True)
            response_type = AgentArtifactCapturePreview
        elif isinstance(request, AgentMcpArtifactsExportRequest):
            operation = "export_artifact_lineage"
            path_parameters = {
                "project_id": request.project_id,
                "session_id": request.session_id,
                "artifact_id": request.artifact_id,
            }
            query = {}
            body = ExportAgentArtifact(
                expected_revision=request.expected_revision,
                version_id=request.version_id,
            ).model_dump(mode="json")
            response_type = AgentArtifactExport
        else:  # discriminated parsing makes this unreachable; retain a closed failure
            raise AgentMcpSurfaceError("invalid_arguments")

        invoked = self._client.invoke(
            AgentControllerInvokeRequest(
                operation=operation,
                path_parameters=path_parameters,
                query=query,
                body=body,
            )
        )
        if (
            invoked.operation != operation
            or invoked.status_code != 200
            or invoked.response is None
        ):
            raise AgentMcpSurfaceError("artifact_response_invalid")
        try:
            validated = response_type.model_validate(invoked.response)
        except ValidationError:
            raise AgentMcpSurfaceError("artifact_response_invalid") from None

        if isinstance(request, AgentMcpArtifactsListRequest):
            assert isinstance(validated, AgentArtifactList)
            artifact_ids = [artifact.artifact_id for artifact in validated.artifacts]
            if (
                validated.project_id != request.project_id
                or validated.session_id != request.session_id
                or len(validated.artifacts) > request.limit
                or len(artifact_ids) != len(set(artifact_ids))
                or any(
                    artifact.project_id != request.project_id
                    or artifact.session_id != request.session_id
                    for artifact in validated.artifacts
                )
            ):
                raise AgentMcpSurfaceError("artifact_response_invalid")
        elif isinstance(request, AgentMcpArtifactsGetRequest):
            assert isinstance(validated, AgentArtifactDetail)
            if (
                validated.project_id != request.project_id
                or validated.session_id != request.session_id
                or validated.artifact_id != request.artifact_id
            ):
                raise AgentMcpSurfaceError("artifact_response_invalid")
        elif isinstance(request, AgentMcpArtifactsPreviewCaptureRequest):
            assert isinstance(validated, AgentArtifactCapturePreview)
            expected_title = request.title or PurePosixPath(request.path).name[:120]
            if (
                validated.project_id != request.project_id
                or validated.session_id != request.session_id
                or validated.path != request.path
                or validated.title != expected_title
            ):
                raise AgentMcpSurfaceError("artifact_response_invalid")
        elif isinstance(request, AgentMcpArtifactsExportRequest):
            assert isinstance(validated, AgentArtifactExport)
            if (
                validated.artifact.project_id != request.project_id
                or validated.artifact.session_id != request.session_id
                or validated.artifact.artifact_id != request.artifact_id
                or validated.artifact.revision != request.expected_revision
                or validated.selected_version.version_id != request.version_id
                or validated.content_included
                or validated.absolute_path_included
            ):
                raise AgentMcpSurfaceError("artifact_response_invalid")

        return {
            "action": request.action,
            "operation": operation,
            "status_code": invoked.status_code,
            "response": validated.model_dump(mode="json"),
        }

    @staticmethod
    def _attachment_view(attachment: AgentAttachment) -> AgentMcpStagedAttachmentView:
        if attachment.state != "staged" or attachment.expires_at is None:
            raise AgentMcpSurfaceError("attachment_response_invalid")
        return AgentMcpStagedAttachmentView(
            attachment_id=attachment.attachment_id,
            model_alias=attachment.model_alias,
            kind=attachment.kind,
            media_type=attachment.media_type,
            display_name=attachment.display_name,
            byte_size=attachment.byte_size,
            width=attachment.width,
            height=attachment.height,
            duration_ms=attachment.duration_ms,
            sample_rate_hz=attachment.sample_rate_hz,
            channels=attachment.channels,
            routing=attachment.routing,
            document_format=attachment.document_format,
            projected_characters=attachment.projected_characters,
            projection_truncated=attachment.projection_truncated,
            omitted_features=attachment.omitted_features,
            source=attachment.source,
            expires_at=attachment.expires_at,
        )

    def _call_stage_attachment(
        self,
        request: AgentMcpStageAttachmentInput,
    ) -> dict[str, Any]:
        attachment = self._client.stage_attachment(
            AgentControllerAttachmentStageRequest(
                project_id=request.project_id,
                session_id=request.session_id,
                attachment=request.attachment,
            )
        )
        view = self._attachment_view(attachment)
        if (
            attachment.session_id != request.session_id
            or attachment.source != "external_agent"
            or attachment.sha256 != request.attachment.sha256
            or attachment.byte_size != request.attachment.byte_size
            or attachment.media_type != request.attachment.media_type
            or attachment.display_name != request.attachment.display_name
        ):
            raise AgentMcpSurfaceError("attachment_response_invalid")
        return {
            "operation": "stage_attachment_inline",
            "status_code": 201,
            "project_id": request.project_id,
            "session_id": request.session_id,
            "attachment": view.model_dump(mode="json"),
            "attachment_bytes_returned": False,
        }

    def _call_context(self, request: AgentMcpContextRequest) -> dict[str, Any]:
        operation_names = ["get_local_runtime", "get_local_model_compatibility"]
        runtime_result = self._client.invoke(
            AgentControllerInvokeRequest(operation="get_local_runtime")
        )
        compatibility_result = self._client.invoke(
            AgentControllerInvokeRequest(operation="get_local_model_compatibility")
        )
        if (
            runtime_result.operation != "get_local_runtime"
            or runtime_result.status_code != 200
            or runtime_result.response is None
            or compatibility_result.operation != "get_local_model_compatibility"
            or compatibility_result.status_code != 200
            or compatibility_result.response is None
        ):
            raise AgentMcpSurfaceError("context_response_invalid")
        try:
            runtime = LocalRuntimeCoordinatorStatus.model_validate(
                runtime_result.response
            )
            compatibility = LocalModelCompatibilityCatalog.model_validate(
                compatibility_result.response
            )
        except ValidationError:
            raise AgentMcpSurfaceError("context_response_invalid") from None

        aliases = [model.alias for model in compatibility.models]
        if len(aliases) != len(set(aliases)):
            raise AgentMcpSurfaceError("context_response_invalid")
        selected_models = sorted(compatibility.models, key=lambda item: item.alias)[
            :MAX_AGENT_MCP_CONTEXT_MODELS
        ]
        model_view = AgentMcpModelCatalogView(
            adapter=AgentMcpRuntimeAdapterView(
                adapter_id=compatibility.adapter.adapter_id,
                adapter_version=compatibility.adapter.adapter_version,
                runtime_version=compatibility.adapter.runtime_version,
                runtime_identity_state=compatibility.adapter.runtime_identity_state,
                capability_probe_version=(
                    compatibility.adapter.capability_probe_version
                ),
            ),
            installed_count=len(compatibility.models),
            returned_count=len(selected_models),
            truncated=len(compatibility.models) > len(selected_models),
            models=tuple(
                AgentMcpModelCompatibilityView(
                    alias=model.alias,
                    state=model.state,
                    reason_code=model.reason_code,
                    architecture=model.architecture,
                    tokenizer_model=model.tokenizer_model,
                    training_context_size=model.training_context_size,
                    execution_state=model.execution_state,
                    context_counter_state=model.context_counter_state,
                )
                for model in selected_models
            ),
        )
        served = (
            None
            if runtime.served is None
            else LocalRuntimeSelection(
                alias=runtime.served.alias,
                device=runtime.served.device,
                gpu_layers=runtime.served.gpu_layers,
                context_size=runtime.served.context_size,
            )
        )
        runtime_view = AgentMcpRuntimeView(
            revision=runtime.revision,
            state=runtime.state,
            requested=runtime.requested,
            served=served,
            cleanup_state=runtime.cleanup.state,
            process_exit_confirmed=runtime.cleanup.process_exit_confirmed,
            capabilities=runtime.capabilities,
            context=runtime.context,
            active_requests=runtime.active_requests,
            last_error_code=runtime.last_error_code,
        )
        attachment_capabilities = AgentMcpAttachmentCapabilityView(
            image_input=runtime.capabilities.vision,
            audio_input=runtime.capabilities.audio,
            document_input=runtime.capabilities.text,
            microphone_recording=runtime.capabilities.recording,
            image_media_types=("image/png", "image/jpeg")
            if runtime.capabilities.vision
            else (),
            audio_media_types=("audio/wav",) if runtime.capabilities.audio else (),
            document_media_types=(
                tuple(AGENT_DOCUMENT_MEDIA_TYPES.values())
                if runtime.capabilities.text
                else ()
            ),
            document_formats=(
                tuple(AGENT_DOCUMENT_MEDIA_TYPES)
                if runtime.capabilities.text
                else ()
            ),
            max_message_attachments=MAX_AGENT_MESSAGE_ATTACHMENTS,
            max_staged_attachments=MAX_AGENT_STAGED_ATTACHMENTS,
            max_message_bytes=MAX_AGENT_ATTACHMENT_MESSAGE_BYTES,
            max_session_bytes=MAX_AGENT_ATTACHMENT_SESSION_BYTES,
            max_image_bytes=MAX_AGENT_IMAGE_BYTES,
            max_image_dimension=MAX_AGENT_IMAGE_DIMENSION,
            max_image_pixels=MAX_AGENT_IMAGE_PIXELS,
            max_audio_bytes=MAX_AGENT_AUDIO_BYTES,
            max_audio_duration_ms=MAX_AGENT_AUDIO_DURATION_MS,
            max_document_bytes=MAX_AGENT_DOCUMENT_BYTES,
            max_text_document_bytes=MAX_AGENT_TEXT_DOCUMENT_BYTES,
            max_document_projection_characters=(
                MAX_AGENT_DOCUMENT_PROJECTION_CHARACTERS
            ),
            max_document_preview_characters=MAX_AGENT_DOCUMENT_PREVIEW_CHARACTERS,
            max_document_message_characters=MAX_AGENT_DOCUMENT_MESSAGE_CHARACTERS,
        )

        chat_view: AgentMcpChatContextView | None = None
        if isinstance(request, AgentMcpContextChatRequest):
            operation_names.extend(
                ["get_live_session", "get_session_context", "list_attachments"]
            )
            session_result = self._client.invoke(
                AgentControllerInvokeRequest(
                    operation="get_live_session",
                    path_parameters={"session_id": request.session_id},
                )
            )
            context_result = self._client.invoke(
                AgentControllerInvokeRequest(
                    operation="get_session_context",
                    path_parameters={"session_id": request.session_id},
                )
            )
            attachments_result = self._client.invoke(
                AgentControllerInvokeRequest(
                    operation="list_attachments",
                    path_parameters={"session_id": request.session_id},
                )
            )
            if (
                session_result.operation != "get_live_session"
                or session_result.status_code != 200
                or session_result.response is None
                or context_result.operation != "get_session_context"
                or context_result.status_code != 200
                or context_result.response is None
                or attachments_result.operation != "list_attachments"
                or attachments_result.status_code != 200
                or attachments_result.response is None
            ):
                raise AgentMcpSurfaceError("context_response_invalid")
            try:
                session = AgentSessionView.model_validate(session_result.response)
                session_context = AgentSessionContextStatus.model_validate(
                    context_result.response
                )
                attachments = AgentAttachmentList.model_validate(
                    attachments_result.response
                )
            except ValidationError:
                raise AgentMcpSurfaceError("context_response_invalid") from None
            attachment_ids = [item.attachment_id for item in attachments.attachments]
            if (
                session.session_id != request.session_id
                or session.settings.project_id != request.project_id
                or session_context.session_id != request.session_id
                or attachments.session_id != request.session_id
                or len(attachment_ids) != len(set(attachment_ids))
                or any(
                    item.state != "staged"
                    or item.expires_at is None
                    or (
                        session.model_alias is not None
                        and item.model_alias != session.model_alias
                    )
                    for item in attachments.attachments
                )
            ):
                raise AgentMcpSurfaceError("context_response_invalid")
            staged = tuple(
                self._attachment_view(item)
                for item in attachments.attachments
            )
            selected_model_ready = bool(
                session.model_alias is not None
                and runtime.state is RuntimeCoordinatorState.READY
                and served is not None
                and served.alias == session.model_alias
                and runtime.capabilities.text
            )
            chat_view = AgentMcpChatContextView(
                project_id=request.project_id,
                session_id=request.session_id,
                configured_model_alias=session.settings.model_alias,
                effective_model_alias=session.model_alias,
                selected_model_ready=selected_model_ready,
                parameters=session.settings.parameters,
                retention_policy=session.settings.retention_policy,
                allow_writes=session.settings.allow_writes,
                allow_commands=session.settings.allow_commands,
                allow_web=session.settings.allow_web,
                max_steps=session.settings.max_steps,
                command_timeout_seconds=session.settings.command_timeout_seconds,
                running=session.running,
                closing=session.closing,
                stopping=session.stopping,
                cleanup_unconfirmed=session.cleanup_unconfirmed,
                approval_pending=session.pending_approval_id is not None,
                turns=session.turns,
                history_revision=session.history_revision,
                recovery_state=session.recovery_state,
                authority_revalidated=session.authority_revalidated,
                history_write_failed=session.history_write_failed,
                context=session_context,
                selected_chat_context_proven=(
                    session_context.binding_state == "bound"
                ),
                staged_attachments=staged,
            )

        view = AgentMcpContextView(
            runtime=runtime_view,
            models=model_view,
            attachments=attachment_capabilities,
            chat=chat_view,
        )
        return {
            "action": request.action,
            "operations": operation_names,
            "view": view.model_dump(mode="json"),
        }

    def _ownership_components(
        self,
    ) -> tuple[str, str, AgentControllerOwnershipService]:
        if (
            self._scope_project_id is None
            or self._controller_connection_id is None
            or self._controller_ownership is None
        ):
            raise AgentMcpSurfaceError("agent_controller_identity_unavailable")
        return (
            self._controller_connection_id,
            self._scope_project_id,
            self._controller_ownership,
        )

    @staticmethod
    def _ownership_surface_error(
        error: AgentControllerOwnershipError,
    ) -> AgentMcpSurfaceError:
        return AgentMcpSurfaceError(error.code)

    def _claim_control(
        self,
        session_id: str,
        *,
        operation: AgentControllerOperation,
    ) -> AgentControllerOwnership:
        connection_id, project_id, ownership = self._ownership_components()
        try:
            session = self._client.live_session(session_id)
        except AgentControllerError as error:
            raise self._controller_error(error) from None
        if session is None or session.settings.project_id != project_id:
            raise AgentMcpSurfaceError("agent_controller_session_unavailable")
        if session.cleanup_unconfirmed:
            raise AgentMcpSurfaceError("agent_controller_cleanup_unconfirmed")
        if (
            session.running
            or session.closing
            or session.stopping
            or session.pending_approval_id is not None
        ):
            raise AgentMcpSurfaceError("agent_controller_session_not_idle")
        try:
            claimed = ownership.claim(
                connection_id=connection_id,
                project_id=project_id,
                session_id=session_id,
                operation=operation,
            )
            return ownership.update(
                session_id,
                owner_connection_id=connection_id,
                state="claimed",
                cursor=session.last_seq,
                last_seq=session.last_seq,
                approval_pending=False,
            )
        except AgentControllerOwnershipError as error:
            raise self._ownership_surface_error(error) from None

    def _owned_control(self, session_id: str) -> AgentControllerOwnership:
        connection_id, project_id, ownership = self._ownership_components()
        try:
            current = ownership.get(session_id)
        except AgentControllerOwnershipError as error:
            raise self._ownership_surface_error(error) from None
        if current is None:
            raise AgentMcpSurfaceError("agent_controller_ownership_required")
        if current.project_id != project_id:
            raise AgentMcpSurfaceError("agent_mcp_scope_violation")
        if current.owner_connection_id != connection_id:
            raise AgentMcpSurfaceError("agent_controller_session_owned")
        if current.state == "revoked":
            raise AgentMcpSurfaceError("agent_controller_connection_inactive")
        return current

    def _update_owned_control(
        self,
        session_id: str,
        *,
        state: Literal[
            "claimed",
            "running",
            "waiting_native_approval",
            "reconnecting",
            "submission_uncertain",
            "stopping",
            "stop_uncertain",
            "cleanup_unconfirmed",
        ],
        cursor: int,
        last_seq: int,
        approval_pending: bool,
    ) -> AgentControllerOwnership | None:
        connection_id, _project_id, ownership = self._ownership_components()
        try:
            return ownership.update(
                session_id,
                owner_connection_id=connection_id,
                state=state,
                cursor=cursor,
                last_seq=last_seq,
                approval_pending=approval_pending,
            )
        except AgentControllerOwnershipError:
            # A handoff may have completed while the old owner's bounded call
            # was still returning. Never turn a settled Agent operation into an
            # ambiguous retry opportunity merely because ownership moved.
            return None

    def _release_owned_control(
        self,
        session_id: str,
        *,
        expected_revision: int | None = None,
    ) -> None:
        connection_id, _project_id, ownership = self._ownership_components()
        try:
            ownership.release_owner(
                owner_connection_id=connection_id,
                session_id=session_id,
                expected_revision=expected_revision,
            )
        except AgentControllerOwnershipError:
            # See _update_owned_control: a completed handoff wins over a late
            # release from the previous owner's in-flight request.
            return

    @staticmethod
    def _deterministic_controller_refusal(error: AgentControllerError) -> bool:
        return error.http_status is not None and 400 <= error.http_status < 500

    def _call_owned_turn(self, parsed: AgentMcpTurnInput) -> AgentControllerTurnResult:
        session_id = parsed.request.session_id
        claimed = self._claim_control(session_id, operation="turn")
        self._update_owned_control(
            session_id,
            state="running",
            cursor=claimed.cursor,
            last_seq=claimed.last_seq,
            approval_pending=False,
        )
        try:
            result = self._client.run_turn(
                parsed.request,
                deadline_seconds=parsed.deadline_seconds,
                poll_interval_seconds=0.1,
                drain_timeout_seconds=parsed.drain_timeout_seconds,
            )
        except AgentControllerError as error:
            if self._deterministic_controller_refusal(error):
                self._release_owned_control(session_id)
            else:
                self._update_owned_control(
                    session_id,
                    state="reconnecting",
                    cursor=claimed.cursor,
                    last_seq=claimed.last_seq,
                    approval_pending=False,
                )
            raise
        if result.outcome in {"settled", "stopped"}:
            self._release_owned_control(session_id)
            return result
        state = {
            "needs_native_approval": "waiting_native_approval",
            "submission_uncertain": "submission_uncertain",
            "cleanup_unconfirmed": "cleanup_unconfirmed",
            "incomplete": "reconnecting",
        }[result.outcome]
        self._update_owned_control(
            session_id,
            state=state,
            cursor=result.cursor,
            last_seq=result.last_seq,
            approval_pending=result.pending_approval_id is not None,
        )
        return result

    def _finish_observation(
        self,
        result: AgentControllerTurnResult,
    ) -> AgentControllerTurnResult:
        if result.outcome in {"settled", "stopped"}:
            self._release_owned_control(result.session_id)
            return result
        state = {
            "needs_native_approval": "waiting_native_approval",
            "submission_uncertain": "submission_uncertain",
            "cleanup_unconfirmed": "cleanup_unconfirmed",
            "incomplete": "reconnecting",
        }[result.outcome]
        self._update_owned_control(
            result.session_id,
            state=state,
            cursor=result.cursor,
            last_seq=result.last_seq,
            approval_pending=result.pending_approval_id is not None,
        )
        return result

    def _finish_stop(
        self,
        result: AgentControllerStopResult,
    ) -> AgentControllerStopResult:
        if result.outcome in {"already_settled", "stopped"}:
            self._release_owned_control(result.session_id)
            return result
        state = {
            "stop_uncertain": "stop_uncertain",
            "cleanup_unconfirmed": "cleanup_unconfirmed",
            "incomplete": "stopping",
        }[result.outcome]
        self._update_owned_control(
            result.session_id,
            state=state,
            cursor=result.cursor,
            last_seq=result.last_seq,
            approval_pending=result.pending_approval_id is not None,
        )
        return result

    def _finish_proposal(
        self,
        receipt: (
            AgentWriteProposalReceipt
            | AgentWriteTransactionProposalReceipt
            | AgentLifecycleProposalReceipt
        ),
    ) -> (
        AgentWriteProposalReceipt
        | AgentWriteTransactionProposalReceipt
        | AgentLifecycleProposalReceipt
    ):
        if receipt.state != "pending_native_review":
            self._release_owned_control(receipt.session_id)
            return receipt
        self._update_owned_control(
            receipt.session_id,
            state="waiting_native_approval",
            cursor=receipt.cursor,
            last_seq=receipt.cursor,
            approval_pending=True,
        )
        return receipt

    def _call_control(self, parsed: AgentMcpControlInput) -> dict[str, Any]:
        connection_id, project_id, ownership = self._ownership_components()
        try:
            current = ownership.get(parsed.session_id)
            if current is not None and current.project_id != project_id:
                raise AgentMcpSurfaceError("agent_mcp_scope_violation")
            if parsed.action == "status":
                return {
                    "action": parsed.action,
                    "ownership": (
                        None if current is None else current.model_dump(mode="json")
                    ),
                }
            if parsed.action == "offer_handoff":
                assert parsed.expected_revision is not None
                assert parsed.target_connection_id is not None
                result = ownership.offer(
                    owner_connection_id=connection_id,
                    command=OfferAgentControllerHandoff(
                        session_id=parsed.session_id,
                        target_connection_id=parsed.target_connection_id,
                        expected_revision=parsed.expected_revision,
                    ),
                )
                return {
                    "action": parsed.action,
                    "ownership": result.model_dump(mode="json"),
                }
            if parsed.action == "accept_handoff":
                assert parsed.expected_revision is not None
                result = ownership.accept(
                    target_connection_id=connection_id,
                    command=AcceptAgentControllerHandoff(
                        session_id=parsed.session_id,
                        expected_revision=parsed.expected_revision,
                    ),
                )
                return {
                    "action": parsed.action,
                    "ownership": result.model_dump(mode="json"),
                }
            assert parsed.action == "release"
            assert parsed.expected_revision is not None
            if current is None:
                raise AgentControllerOwnershipError(
                    "agent_controller_ownership_not_found"
                )
            if current.owner_connection_id != connection_id:
                raise AgentControllerOwnershipError(
                    "agent_controller_session_owned"
                )
            live = self._client.live_session(parsed.session_id)
            if live is not None and (
                live.running
                or live.closing
                or live.stopping
                or live.pending_approval_id is not None
                or live.cleanup_unconfirmed
            ):
                raise AgentControllerOwnershipError(
                    "agent_controller_session_not_settled"
                )
            receipt = ownership.release_owner(
                owner_connection_id=connection_id,
                session_id=parsed.session_id,
                expected_revision=parsed.expected_revision,
            )
            return {
                "action": parsed.action,
                "release": receipt.model_dump(mode="json"),
            }
        except AgentControllerOwnershipError as error:
            raise self._ownership_surface_error(error) from None


    def call(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        specs = {tool.name: tool for tool in self.tools()}
        spec = specs.get(name)
        if spec is None:
            raise AgentMcpSurfaceError("unknown_tool")
        try:
            parsed = spec.input_model.model_validate(dict(arguments))
        except ValidationError:
            raise AgentMcpSurfaceError("invalid_arguments") from None

        try:
            self._enforce_scope(name, parsed)
            if name == "agent_discover":
                assert isinstance(parsed, AgentMcpDiscoverInput)
                result = self._client.discover(refresh=parsed.refresh)
            elif name == "agent_invoke":
                assert isinstance(parsed, AgentMcpInvokeInput)
                manifest = self._client.discover()
                endpoint = next(
                    (
                        item
                        for item in manifest.endpoints
                        if item.operation == parsed.request.operation
                    ),
                    None,
                )
                if endpoint is None:
                    raise AgentControllerError("controller_operation_unknown")
                if endpoint.operation == "stage_attachment_inline":
                    raise AgentMcpSurfaceError(
                        "attachment_staging_requires_dedicated_tool"
                    )
                if endpoint.operation in {
                    "propose_file_transaction",
                    "propose_file_write",
                    "propose_workspace_lifecycle",
                }:
                    raise AgentMcpSurfaceError(
                        "write_proposal_requires_dedicated_tool"
                    )
                if endpoint.operation == "stop_turn":
                    raise AgentMcpSurfaceError("stop_requires_dedicated_tool")
                if endpoint.operation == "resume_retained_session":
                    raise AgentMcpSurfaceError("resume_requires_dedicated_tool")
                if endpoint.operation == "fork_retained_session":
                    raise AgentMcpSurfaceError("fork_requires_dedicated_tool")
                if endpoint.operation == "export_retained_history":
                    raise AgentMcpSurfaceError("export_requires_dedicated_tool")
                if endpoint.operation == "close_live_session":
                    raise AgentMcpSurfaceError("close_requires_dedicated_tool")
                if endpoint.operation == "preview_artifact_capture":
                    raise AgentMcpSurfaceError(
                        "artifact_preview_requires_dedicated_tool"
                    )
                if endpoint.method == "DELETE":
                    raise AgentMcpSurfaceError("destructive_action_requires_agent_ui")
                if (
                    endpoint.method in {"POST", "PATCH"}
                    and not parsed.mutation_authorized
                ):
                    raise AgentMcpSurfaceError("mutation_authorization_required")
                result = self._client.invoke(parsed.request)
            elif name == "agent_open":
                assert isinstance(parsed, AgentMcpOpenInput)
                result = self._client.open_chat(parsed.request)
            elif name == "agent_resume":
                assert isinstance(parsed, AgentMcpResumeInput)
                result = self._client.resume_chat(parsed.request)
            elif name == "agent_fork":
                assert isinstance(parsed, AgentMcpForkInput)
                result = self._client.fork_chat(parsed.request)
            elif name == "agent_export":
                assert isinstance(parsed, AgentMcpExportInput)
                result = self._client.export_chat(parsed.request)
            elif name == "agent_close":
                assert isinstance(parsed, AgentMcpCloseInput)
                result = self._client.close_chat(parsed.request)
            elif name == "agent_catalog":
                assert isinstance(parsed, AgentMcpCatalogInput)
                result = self._call_catalog(parsed.request)
            elif name == "agent_history":
                assert isinstance(parsed, AgentMcpHistoryInput)
                result = self._call_history(parsed)
            elif name == "agent_artifacts":
                assert isinstance(parsed, AgentMcpArtifactsInput)
                result = self._call_artifacts(parsed.request)
            elif name == "agent_stage_attachment":
                assert isinstance(parsed, AgentMcpStageAttachmentInput)
                result = self._call_stage_attachment(parsed)
            elif name == "agent_context":
                assert isinstance(parsed, AgentMcpContextInput)
                result = self._call_context(parsed.request)
            elif name == "agent_workspace":
                assert isinstance(parsed, AgentMcpWorkspaceInput)
                operation = {
                    "inspect": "inspect_workspace",
                    "list": "list_workspace_tree",
                    "search": "search_workspace_text",
                    "read": "read_workspace_file",
                    "changes": "review_changes",
                    "diff": "read_change_diff",
                }[parsed.action]
                query: dict[str, str] = {}
                if parsed.action == "list":
                    query["path"] = parsed.path or "."
                elif parsed.action == "search":
                    assert parsed.query is not None
                    query["query"] = parsed.query
                    query["glob"] = parsed.glob or "**/*"
                    query["regex"] = "true" if parsed.regex else "false"
                elif parsed.action in {"read", "diff"}:
                    assert parsed.path is not None
                    query["path"] = parsed.path
                invoked = self._client.invoke(
                    AgentControllerInvokeRequest(
                        operation=operation,
                        path_parameters={"session_id": parsed.session_id},
                        query=query,
                    )
                )
                response_type = {
                    "inspect": WorkspaceDiscovery,
                    "list": WorkspaceTree,
                    "search": WorkspaceSearchResult,
                    "read": WorkspaceFile,
                    "changes": AgentChangeSet,
                    "diff": AgentChangeDiff,
                }[parsed.action]
                try:
                    validated = response_type.model_validate(invoked.response)
                except ValidationError:
                    raise AgentMcpSurfaceError("workspace_response_invalid") from None
                if validated.session_id != parsed.session_id:
                    raise AgentMcpSurfaceError("workspace_response_invalid")
                if parsed.action in {"list", "read"}:
                    expected_path = parsed.path or "."
                    if validated.path != expected_path:
                        raise AgentMcpSurfaceError("workspace_response_invalid")
                if parsed.action == "diff":
                    assert parsed.path is not None
                    if validated.summary.path != parsed.path:
                        raise AgentMcpSurfaceError("workspace_response_invalid")
                result = {
                    "action": parsed.action,
                    "operation": operation,
                    "status_code": invoked.status_code,
                    "response": validated.model_dump(mode="json"),
                }
            elif name == "agent_control":
                assert isinstance(parsed, AgentMcpControlInput)
                result = self._call_control(parsed)
            elif name == "agent_propose":
                assert isinstance(parsed, AgentMcpProposeInput)
                if self._controller_ownership is None:
                    result = self._client.propose_write(parsed.request)
                else:
                    claimed = self._claim_control(
                        parsed.request.session_id,
                        operation="write_proposal",
                    )
                    self._update_owned_control(
                        parsed.request.session_id,
                        state="running",
                        cursor=claimed.cursor,
                        last_seq=claimed.last_seq,
                        approval_pending=False,
                    )
                    try:
                        result = self._client.propose_write(parsed.request)
                    except AgentControllerError as error:
                        if self._deterministic_controller_refusal(error):
                            self._release_owned_control(parsed.request.session_id)
                        else:
                            self._update_owned_control(
                                parsed.request.session_id,
                                state="submission_uncertain",
                                cursor=claimed.cursor,
                                last_seq=claimed.last_seq,
                                approval_pending=False,
                            )
                        raise
                    result = self._finish_proposal(result)
            elif name == "agent_propose_transaction":
                assert isinstance(parsed, AgentMcpProposeTransactionInput)
                if self._controller_ownership is None:
                    result = self._client.propose_write_transaction(parsed.request)
                else:
                    claimed = self._claim_control(
                        parsed.request.session_id,
                        operation="transaction_proposal",
                    )
                    self._update_owned_control(
                        parsed.request.session_id,
                        state="running",
                        cursor=claimed.cursor,
                        last_seq=claimed.last_seq,
                        approval_pending=False,
                    )
                    try:
                        result = self._client.propose_write_transaction(parsed.request)
                    except AgentControllerError as error:
                        if self._deterministic_controller_refusal(error):
                            self._release_owned_control(parsed.request.session_id)
                        else:
                            self._update_owned_control(
                                parsed.request.session_id,
                                state="submission_uncertain",
                                cursor=claimed.cursor,
                                last_seq=claimed.last_seq,
                                approval_pending=False,
                            )
                        raise
                    result = self._finish_proposal(result)
            elif name == "agent_propose_lifecycle":
                assert isinstance(parsed, AgentMcpProposeLifecycleInput)
                if self._controller_ownership is None:
                    result = self._client.propose_lifecycle(parsed.request)
                else:
                    claimed = self._claim_control(
                        parsed.request.session_id,
                        operation="lifecycle_proposal",
                    )
                    self._update_owned_control(
                        parsed.request.session_id,
                        state="running",
                        cursor=claimed.cursor,
                        last_seq=claimed.last_seq,
                        approval_pending=False,
                    )
                    try:
                        result = self._client.propose_lifecycle(parsed.request)
                    except AgentControllerError as error:
                        if self._deterministic_controller_refusal(error):
                            self._release_owned_control(parsed.request.session_id)
                        else:
                            self._update_owned_control(
                                parsed.request.session_id,
                                state="submission_uncertain",
                                cursor=claimed.cursor,
                                last_seq=claimed.last_seq,
                                approval_pending=False,
                            )
                        raise
                    result = self._finish_proposal(result)
            elif name == "agent_turn":
                assert isinstance(parsed, AgentMcpTurnInput)
                if self._controller_ownership is None:
                    result = self._client.run_turn(
                        parsed.request,
                        deadline_seconds=parsed.deadline_seconds,
                        poll_interval_seconds=0.1,
                        drain_timeout_seconds=parsed.drain_timeout_seconds,
                    )
                else:
                    result = self._call_owned_turn(parsed)
            elif name == "agent_stop":
                assert isinstance(parsed, AgentMcpStopInput)
                if self._controller_ownership is None:
                    result = self._client.stop_turn(
                        parsed.request,
                        drain_timeout_seconds=parsed.drain_timeout_seconds,
                        poll_interval_seconds=0.1,
                    )
                else:
                    current = self._owned_control(parsed.request.session_id)
                    self._update_owned_control(
                        parsed.request.session_id,
                        state="stopping",
                        cursor=current.cursor,
                        last_seq=current.last_seq,
                        approval_pending=current.approval_pending,
                    )
                    try:
                        result = self._client.stop_turn(
                            parsed.request,
                            drain_timeout_seconds=parsed.drain_timeout_seconds,
                            poll_interval_seconds=0.1,
                        )
                    except AgentControllerError:
                        self._update_owned_control(
                            parsed.request.session_id,
                            state="stop_uncertain",
                            cursor=current.cursor,
                            last_seq=current.last_seq,
                            approval_pending=current.approval_pending,
                        )
                        raise
                    result = self._finish_stop(result)
            elif name == "agent_wait":
                assert isinstance(parsed, AgentMcpWaitInput)
                if self._controller_ownership is None:
                    result = self._client.wait_turn(
                        parsed.request,
                        deadline_seconds=parsed.deadline_seconds,
                        poll_interval_seconds=0.1,
                    )
                else:
                    current = self._owned_control(parsed.request.session_id)
                    try:
                        result = self._client.wait_turn(
                            parsed.request,
                            deadline_seconds=parsed.deadline_seconds,
                            poll_interval_seconds=0.1,
                        )
                    except AgentControllerError:
                        self._update_owned_control(
                            parsed.request.session_id,
                            state="reconnecting",
                            cursor=current.cursor,
                            last_seq=current.last_seq,
                            approval_pending=current.approval_pending,
                        )
                        raise
                    result = self._finish_observation(result)
            elif name == "agent_runtime" and self._allow_model_lifecycle:
                assert isinstance(parsed, AgentMcpRuntimeInput)
                result = self._client.coordinate_runtime(parsed.request)
            else:  # guarded by the tool table; fail closed if it ever diverges
                raise AgentMcpSurfaceError("unknown_tool")
        except AgentMcpSurfaceError:
            raise
        except AgentControllerError as error:
            raise self._controller_error(error) from None
        return self._payload(name, result)


__all__ = (
    "AGENT_MCP_CONTRACT_VERSION",
    "AGENT_MCP_CONTEXT_CONTRACT_VERSION",
    "MAX_AGENT_MCP_DEADLINE_SECONDS",
    "MAX_AGENT_MCP_CONTEXT_MODELS",
    "AgentMcpArtifactsGetRequest",
    "AgentMcpArtifactsExportRequest",
    "AgentMcpArtifactsInput",
    "AgentMcpArtifactsListRequest",
    "AgentMcpArtifactsRequest",
    "AgentMcpCatalogCreateProjectRequest",
    "AgentMcpCatalogGetChatRequest",
    "AgentMcpCatalogGetProjectRequest",
    "AgentMcpCatalogInput",
    "AgentMcpCatalogListChatsRequest",
    "AgentMcpCatalogListProjectsRequest",
    "AgentMcpCatalogRequest",
    "AgentMcpCatalogUpdateChatRequest",
    "AgentMcpCatalogUpdateProjectRequest",
    "AgentMcpChatContextView",
    "AgentMcpCloseInput",
    "AgentMcpControlInput",
    "AgentMcpContextChatRequest",
    "AgentMcpContextInput",
    "AgentMcpContextRequest",
    "AgentMcpContextRuntimeRequest",
    "AgentMcpContextView",
    "AgentMcpDiscoverInput",
    "AgentMcpEgressAuthorization",
    "AgentMcpExportInput",
    "AgentMcpForkInput",
    "AgentMcpHistoryInput",
    "AgentMcpInvokeInput",
    "AgentMcpRuntimeAdapterView",
    "AgentMcpOpenInput",
    "AgentMcpProposeInput",
    "AgentMcpProposeLifecycleInput",
    "AgentMcpProposeTransactionInput",
    "AgentMcpResumeInput",
    "AgentMcpRuntimeInput",
    "AgentMcpStageAttachmentInput",
    "AgentMcpStopInput",
    "AgentMcpSurface",
    "AgentMcpSurfaceError",
    "AgentMcpTurnInput",
    "AgentMcpWaitInput",
    "AgentMcpWorkspaceAction",
    "AgentMcpWorkspaceInput",
)
