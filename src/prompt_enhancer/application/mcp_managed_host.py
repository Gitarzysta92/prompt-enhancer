"""Strict, content-free contracts for owner-started managed MCP hosts.

This module defines no supervisor implementation and performs no process,
network, filesystem, vault, persistence, model, or tool operation. It exists so
the later Store-06b runtime cannot invent authority outside exact reviewed
server, project-binding, and tool-snapshot revisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator

from ..domain import StrictModel


MCP_MANAGED_HOST_CONTRACT_VERSION = "mcp-managed-host.v2"
MAX_MCP_MANAGED_ACTIVE_HOSTS = 4
MAX_MCP_MANAGED_HOST_QUEUE = 16
MAX_MCP_MANAGED_HOST_START_SECONDS = 20.0
MAX_MCP_MANAGED_HOST_HEALTH_SECONDS = 10.0
MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS = 30.0

_ID_PATTERN = r"^[0-9a-f]{32}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_ERROR_PATTERN = r"^[a-z0-9_]{1,96}$"

McpManagedHostState = Literal[
    "not_started",
    "starting",
    "ready",
    "unhealthy",
    "stopping",
    "cleanup_required",
]
McpManagedHostReason = Literal[
    "never_started",
    "stopped_by_owner",
    "stopped_after_restart",
    "start_cancelled",
    "app_shutdown",
    "start_requested",
    "healthy",
    "transport_failed",
    "process_exited",
    "health_timeout",
    "contract_drift",
    "binding_changed",
    "server_changed",
    "owner_stop",
    "cleanup_unconfirmed",
]
McpManagedHostPermission = Literal[
    "process_spawn",
    "filesystem_read",
    "filesystem_write",
    "network_egress",
    "credential_use",
]
McpManagedHostCleanupState = Literal[
    "not_applicable",
    "pending",
    "verified",
    "unconfirmed",
]
McpManagedHostExecutionKind = Literal[
    "local_native_process",
    "reviewed_remote_connection",
]
McpManagedHostRiskNotice = Literal[
    "local_native_code_uses_current_user_os_authority",
    "remote_connection_uses_reviewed_configuration",
]
McpManagedHostStartEffect = Literal[
    "execute_reviewed_local_package",
    "run_with_current_user_os_permissions",
    "own_hidden_process_tree",
    "open_reviewed_remote_connection",
    "enumerate_exact_tool_contracts",
    "retain_connection_for_current_app_run",
    "periodic_contract_health_check",
    "register_admitted_project_tools",
    "tool_calls_require_fresh_native_approval",
    "no_automatic_restart",
]
McpManagedHostReceiptAction = Literal[
    "start",
    "stop",
    "revoke_project",
    "revoke_server",
    "health_revoke",
    "shutdown",
]
McpManagedHostReceiptOutcome = Literal[
    "ready",
    "stopped",
    "refused",
    "failed",
    "cleanup_required",
]
McpManagedHostReceiptReason = Literal[
    "owner_start",
    "owner_stop",
    "project_revoked",
    "server_revoked",
    "health_failed",
    "app_shutdown",
    "start_refused",
    "start_failed",
    "cleanup_unconfirmed",
]
McpManagedHostCleanupBlockReason = Literal[
    "local_process_cleanup_unconfirmed",
    "remote_connection_cleanup_unconfirmed",
]

_PERMISSION_ORDER: tuple[McpManagedHostPermission, ...] = (
    "process_spawn",
    "filesystem_read",
    "filesystem_write",
    "network_egress",
    "credential_use",
)
_REASONS_BY_STATE: dict[str, frozenset[str]] = {
    "not_started": frozenset(
        {
            "never_started",
            "stopped_by_owner",
            "stopped_after_restart",
            "start_cancelled",
            "app_shutdown",
        }
    ),
    "starting": frozenset({"start_requested"}),
    "ready": frozenset({"healthy"}),
    "unhealthy": frozenset(
        {
            "transport_failed",
            "process_exited",
            "health_timeout",
            "contract_drift",
            "binding_changed",
            "server_changed",
        }
    ),
    "stopping": frozenset(
        {"owner_stop", "app_shutdown", "binding_changed", "server_changed"}
    ),
    "cleanup_required": frozenset({"cleanup_unconfirmed"}),
}
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "not_started": frozenset({"not_started", "starting"}),
    "starting": frozenset(
        {"starting", "ready", "unhealthy", "stopping", "not_started", "cleanup_required"}
    ),
    "ready": frozenset({"ready", "unhealthy", "stopping", "cleanup_required"}),
    "unhealthy": frozenset({"unhealthy", "stopping", "not_started", "cleanup_required"}),
    "stopping": frozenset({"stopping", "not_started", "cleanup_required"}),
    "cleanup_required": frozenset({"cleanup_required", "not_started"}),
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("managed host timestamps require a timezone")
    return value.astimezone(UTC)


def _canonical_permissions(
    values: tuple[McpManagedHostPermission, ...],
) -> tuple[McpManagedHostPermission, ...]:
    selected = set(values)
    return tuple(item for item in _PERMISSION_ORDER if item in selected)


class McpManagedHostBinding(StrictModel):
    """Exact content-free durable authority that one app-run start may bind."""

    contract_version: Literal["mcp-managed-host.v2"] = (
        MCP_MANAGED_HOST_CONTRACT_VERSION
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    server_revision: int = Field(strict=True, ge=1)
    project_binding_revision: int = Field(strict=True, ge=1)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    option_kind: Literal["local_package", "remote_server"]
    transport: Literal["stdio", "streamable-http", "sse"]
    tool_snapshot_id: str = Field(pattern=_ID_PATTERN)
    tool_schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    reviewed_tool_count: int = Field(strict=True, ge=1, le=256)
    admitted_tool_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    granted_permissions: tuple[McpManagedHostPermission, ...] = Field(
        max_length=5
    )
    execution_scope: Literal["current_app_run_owner_start_only"] = (
        "current_app_run_owner_start_only"
    )
    tool_calls_available: Literal[True] = True
    tool_routing_state: Literal["project_scoped_fresh_approval"] = (
        "project_scoped_fresh_approval"
    )

    @model_validator(mode="after")
    def coherent_binding(self) -> "McpManagedHostBinding":
        if (
            len(set(self.admitted_tool_ids)) != len(self.admitted_tool_ids)
            or tuple(sorted(self.admitted_tool_ids)) != self.admitted_tool_ids
            or any(re.fullmatch(_ID_PATTERN, item) is None for item in self.admitted_tool_ids)
            or len(self.admitted_tool_ids) > self.reviewed_tool_count
        ):
            raise ValueError("managed host admitted tools are not canonical")
        if (
            len(set(self.granted_permissions)) != len(self.granted_permissions)
            or self.granted_permissions
            != _canonical_permissions(self.granted_permissions)
        ):
            raise ValueError("managed host permissions are not canonical")
        if (self.option_kind == "local_package") != (self.transport == "stdio"):
            raise ValueError("managed host option and transport are incoherent")
        return self


class StartMcpManagedHost(StrictModel):
    """Native-confirmation-bound request; it contains no connection material."""

    request_id: str = Field(pattern=_ID_PATTERN)
    expected_server_revision: int = Field(strict=True, ge=1)
    expected_project_binding_revision: int = Field(strict=True, ge=1)
    expected_tool_snapshot_id: str = Field(pattern=_ID_PATTERN)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    deadline_seconds: float = Field(
        default=MAX_MCP_MANAGED_HOST_START_SECONDS,
        strict=True,
        ge=0.1,
        le=MAX_MCP_MANAGED_HOST_START_SECONDS,
    )

    @field_validator("deadline_seconds")
    @classmethod
    def finite_deadline(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("managed host start deadline is invalid")
        return value


class StopMcpManagedHost(StrictModel):
    """Authority-reducing request; native confirmation is deliberately absent."""

    request_id: str = Field(pattern=_ID_PATTERN)
    expected_instance_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    deadline_seconds: float = Field(
        default=MAX_MCP_MANAGED_HOST_START_SECONDS,
        strict=True,
        ge=0.1,
        le=MAX_MCP_MANAGED_HOST_START_SECONDS,
    )

    @field_validator("deadline_seconds")
    @classmethod
    def finite_deadline(cls, value: float) -> float:
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("managed host stop deadline is invalid")
        return value


class McpManagedHostStatus(StrictModel):
    """Current content-free project/server host truth for one app process."""

    contract_version: Literal["mcp-managed-host.v2"] = (
        MCP_MANAGED_HOST_CONTRACT_VERSION
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    state: McpManagedHostState
    reason: McpManagedHostReason
    binding: McpManagedHostBinding | None = None
    instance_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    observed_tool_count: int | None = Field(default=None, strict=True, ge=0, le=256)
    observed_schema_digest: str | None = Field(
        default=None,
        pattern=_DIGEST_PATTERN,
    )
    started_at: datetime | None = None
    last_checked_at: datetime | None = None
    stopped_at: datetime | None = None
    last_transition_at: datetime
    process_started: bool = Field(strict=True)
    cleanup_state: McpManagedHostCleanupState
    host_lease_active: bool = Field(strict=True)
    error_code: str | None = Field(default=None, pattern=_ERROR_PATTERN)
    tool_calls_available: bool = Field(default=False, strict=True)
    tool_routing_state: Literal["inactive", "project_scoped_fresh_approval"] = (
        "inactive"
    )
    connection_material_retained_in_status: Literal[False] = False

    @field_validator(
        "started_at",
        "last_checked_at",
        "stopped_at",
        "last_transition_at",
    )
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_status(self) -> "McpManagedHostStatus":
        if self.reason not in _REASONS_BY_STATE[self.state]:
            raise ValueError("managed host state reason is incoherent")
        if self.binding is not None and (
            self.binding.management_id != self.management_id
            or self.binding.project_id != self.project_id
        ):
            raise ValueError("managed host binding identity is incoherent")
        observed_pair = (
            self.observed_tool_count is not None,
            self.observed_schema_digest is not None,
        )
        if observed_pair[0] != observed_pair[1]:
            raise ValueError("managed host observation is incomplete")
        routing_active = (
            self.tool_calls_available
            and self.tool_routing_state == "project_scoped_fresh_approval"
        )
        if self.state == "ready":
            if not routing_active:
                raise ValueError("ready managed host lacks project-scoped tool routing")
        elif self.tool_calls_available or self.tool_routing_state != "inactive":
            raise ValueError("inactive managed host claims tool-call authority")
        for value in (self.last_checked_at, self.stopped_at, self.last_transition_at):
            if self.started_at is not None and value is not None and value < self.started_at:
                raise ValueError("managed host timestamps are incoherent")

        if self.state == "not_started":
            if (
                self.instance_id is not None
                or self.started_at is not None
                or self.last_checked_at is not None
                or any(observed_pair)
                or self.process_started
                or self.host_lease_active
                or self.cleanup_state not in {"not_applicable", "verified"}
                or self.error_code is not None
            ):
                raise ValueError("stopped managed host retains runtime authority")
            return self

        if self.binding is None or self.instance_id is None or self.started_at is None:
            raise ValueError("active managed host lacks an exact instance binding")
        local = self.binding.transport == "stdio"
        if not local and self.process_started:
            raise ValueError("remote managed host cannot claim a local process")

        if self.state == "starting":
            if (
                any(observed_pair)
                or self.last_checked_at is not None
                or self.stopped_at is not None
                or self.host_lease_active
                or self.error_code is not None
                or self.cleanup_state
                not in ({"pending"} if self.process_started else {"not_applicable"})
            ):
                raise ValueError("starting managed host has incoherent evidence")
        elif self.state == "ready":
            expected_cleanup = "pending" if local else "not_applicable"
            if (
                not self.host_lease_active
                or self.last_checked_at is None
                or self.stopped_at is not None
                or self.error_code is not None
                or self.observed_tool_count != self.binding.reviewed_tool_count
                or self.observed_schema_digest != self.binding.tool_schema_digest
                or self.process_started != local
                or self.cleanup_state != expected_cleanup
            ):
                raise ValueError("ready managed host lacks exact health evidence")
        elif self.state in {"unhealthy", "stopping"}:
            if (
                self.host_lease_active
                or self.stopped_at is not None
                or self.cleanup_state == "unconfirmed"
                or (self.state == "unhealthy") != (self.error_code is not None)
            ):
                raise ValueError("revoked managed host has incoherent evidence")
        elif (
            self.state != "cleanup_required"
            or self.host_lease_active
            or self.cleanup_state != "unconfirmed"
            or self.stopped_at is None
            or self.error_code is None
        ):
            raise ValueError("managed host cleanup block is incoherent")
        return self


def mcp_managed_host_binding_digest(binding: McpManagedHostBinding) -> str:
    """Return deterministic content-free binding evidence for previews/receipts."""

    encoded = json.dumps(
        binding.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _managed_host_start_effects(
    *,
    local: bool,
) -> tuple[McpManagedHostStartEffect, ...]:
    common: tuple[McpManagedHostStartEffect, ...] = (
        "enumerate_exact_tool_contracts",
        "retain_connection_for_current_app_run",
        "periodic_contract_health_check",
        "register_admitted_project_tools",
        "tool_calls_require_fresh_native_approval",
        "no_automatic_restart",
    )
    if not local:
        return ("open_reviewed_remote_connection", *common)
    return (
        "execute_reviewed_local_package",
        "run_with_current_user_os_permissions",
        "own_hidden_process_tree",
        *common,
    )


class McpManagedHostStartPreview(StrictModel):
    """Exact read-only preview for one owner-confirmed app-run host start."""

    contract_version: Literal["mcp-managed-host-start-preview.v2"] = (
        "mcp-managed-host-start-preview.v2"
    )
    binding: McpManagedHostBinding
    binding_digest: str = Field(pattern=_DIGEST_PATTERN)
    execution_kind: McpManagedHostExecutionKind
    risk_notice: McpManagedHostRiskNotice
    effects: tuple[McpManagedHostStartEffect, ...] = Field(
        min_length=7,
        max_length=9,
    )
    availability: Literal["available"] = "available"
    reason: Literal["ready_for_native_confirmation"] = (
        "ready_for_native_confirmation"
    )
    native_confirmation_required: Literal[True] = True
    preview_starts_host: Literal[False] = False
    current_app_run_only: Literal[True] = True
    automatic_start: Literal[False] = False
    automatic_restart: Literal[False] = False
    persists_across_app_restart: Literal[False] = False
    model_tool_registration_available: Literal[True] = True
    tool_calls_available: Literal[True] = True
    tool_routing_state: Literal["project_scoped_fresh_approval"] = (
        "project_scoped_fresh_approval"
    )
    connection_material_in_preview: Literal[False] = False

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedHostStartPreview":
        if self.binding_digest != mcp_managed_host_binding_digest(self.binding):
            raise ValueError("managed host preview binding digest is incoherent")
        local = self.binding.option_kind == "local_package"
        expected_execution = (
            "local_native_process" if local else "reviewed_remote_connection"
        )
        expected_notice = (
            "local_native_code_uses_current_user_os_authority"
            if local
            else "remote_connection_uses_reviewed_configuration"
        )
        expected_effects = _managed_host_start_effects(local=local)
        if (
            self.execution_kind != expected_execution
            or self.risk_notice != expected_notice
            or self.effects != expected_effects
        ):
            raise ValueError("managed host preview authority is incoherent")
        return self

    @computed_field
    @property
    def preview_digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_computed_fields=True),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


def build_mcp_managed_host_start_preview(
    binding: McpManagedHostBinding,
) -> McpManagedHostStartPreview:
    """Build a truthful preview; this function performs no runtime operation."""

    local = binding.option_kind == "local_package"
    return McpManagedHostStartPreview(
        binding=binding,
        binding_digest=mcp_managed_host_binding_digest(binding),
        execution_kind=(
            "local_native_process" if local else "reviewed_remote_connection"
        ),
        risk_notice=(
            "local_native_code_uses_current_user_os_authority"
            if local
            else "remote_connection_uses_reviewed_configuration"
        ),
        effects=_managed_host_start_effects(local=local),
    )


class McpManagedHostActionReceipt(StrictModel):
    """Durable content-free truth for one settled host lifecycle action."""

    contract_version: Literal["mcp-managed-host-action-receipt.v1"] = (
        "mcp-managed-host-action-receipt.v1"
    )
    receipt_id: str = Field(pattern=_ID_PATTERN)
    request_id: str = Field(pattern=_ID_PATTERN)
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    instance_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    app_run_digest: str = Field(pattern=_DIGEST_PATTERN)
    binding_digest: str = Field(pattern=_DIGEST_PATTERN)
    execution_kind: McpManagedHostExecutionKind
    action: McpManagedHostReceiptAction
    outcome: McpManagedHostReceiptOutcome
    reason: McpManagedHostReceiptReason
    requested_at: datetime
    completed_at: datetime
    process_started: bool = Field(strict=True)
    cleanup_state: McpManagedHostCleanupState
    host_ready: bool = Field(strict=True)
    error_code: str | None = Field(default=None, pattern=_ERROR_PATTERN)
    endpoint_persisted: Literal[False] = False
    credential_persisted: Literal[False] = False
    command_or_path_persisted: Literal[False] = False
    tool_content_persisted: Literal[False] = False
    prompt_or_result_persisted: Literal[False] = False
    replay_grants_authority: Literal[False] = False

    @field_validator("requested_at", "completed_at")
    @classmethod
    def normalize_receipt_time(cls, value: datetime) -> datetime:
        normalized = _utc(value)
        if normalized is None:
            raise ValueError("managed host receipt timestamp is required")
        return normalized

    @model_validator(mode="after")
    def coherent_receipt(self) -> "McpManagedHostActionReceipt":
        if self.completed_at < self.requested_at:
            raise ValueError("managed host receipt timestamps are incoherent")
        if self.process_started and self.instance_id is None:
            raise ValueError("managed host process receipt lacks an instance")
        local = self.execution_kind == "local_native_process"
        if not local and self.process_started:
            raise ValueError("remote managed host receipt claims a local process")
        reason_by_settled_action: dict[str, str] = {
            "stop": "owner_stop",
            "revoke_project": "project_revoked",
            "revoke_server": "server_revoked",
            "health_revoke": "health_failed",
            "shutdown": "app_shutdown",
        }
        if self.outcome == "ready":
            if (
                self.action != "start"
                or self.reason != "owner_start"
                or self.instance_id is None
                or not self.host_ready
                or self.error_code is not None
                or self.process_started != local
                or self.cleanup_state
                != ("pending" if self.process_started else "not_applicable")
            ):
                raise ValueError("ready managed host receipt is incoherent")
        elif self.outcome == "refused":
            if (
                self.action != "start"
                or self.reason != "start_refused"
                or self.instance_id is not None
                or self.process_started
                or self.host_ready
                or self.cleanup_state != "not_applicable"
                or self.error_code is None
            ):
                raise ValueError("refused managed host receipt is incoherent")
        elif self.outcome == "failed":
            if (
                self.action != "start"
                or self.reason != "start_failed"
                or self.host_ready
                or self.cleanup_state
                != ("verified" if self.process_started else "not_applicable")
                or self.error_code is None
            ):
                raise ValueError("failed managed host receipt is incoherent")
        elif self.outcome == "cleanup_required":
            if (
                self.reason != "cleanup_unconfirmed"
                or self.instance_id is None
                or self.host_ready
                or self.cleanup_state != "unconfirmed"
                or self.error_code is None
                or self.process_started != local
            ):
                raise ValueError("blocked managed host receipt is incoherent")
        elif (
            self.outcome != "stopped"
            or self.action not in reason_by_settled_action
            or self.reason != reason_by_settled_action[self.action]
            or self.instance_id is None
            or self.host_ready
            or (self.process_started and not local)
            or self.cleanup_state
            != ("verified" if self.process_started else "not_applicable")
            or self.error_code is not None
        ):
            raise ValueError("stopped managed host receipt is incoherent")
        return self


class McpManagedHostCleanupBlock(StrictModel):
    """Durable restart/lifecycle block when connection cleanup is uncertain."""

    contract_version: Literal["mcp-managed-host-cleanup-block.v1"] = (
        "mcp-managed-host-cleanup-block.v1"
    )
    block_id: str = Field(pattern=_ID_PATTERN)
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    instance_id: str = Field(pattern=_ID_PATTERN)
    app_run_digest: str = Field(pattern=_DIGEST_PATTERN)
    binding_digest: str = Field(pattern=_DIGEST_PATTERN)
    reason: McpManagedHostCleanupBlockReason
    state: Literal["active", "resolved"]
    process_started: bool = Field(strict=True)
    cleanup_verified: bool = Field(strict=True)
    lifecycle_actions_blocked: bool = Field(strict=True)
    recovery_attempts: int = Field(strict=True, ge=0, le=100)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    endpoint_persisted: Literal[False] = False
    credential_persisted: Literal[False] = False
    process_identity_persisted: Literal[False] = False
    command_or_path_persisted: Literal[False] = False
    tool_content_persisted: Literal[False] = False

    @field_validator("created_at", "updated_at", "resolved_at")
    @classmethod
    def normalize_cleanup_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_cleanup_block(self) -> "McpManagedHostCleanupBlock":
        if self.updated_at < self.created_at or (
            self.resolved_at is not None and self.resolved_at < self.created_at
        ) or (
            self.resolved_at is not None and self.resolved_at > self.updated_at
        ):
            raise ValueError("managed host cleanup timestamps are incoherent")
        local_reason = self.reason == "local_process_cleanup_unconfirmed"
        if local_reason != self.process_started:
            raise ValueError("managed host cleanup process truth is incoherent")
        resolved = self.state == "resolved"
        if (
            resolved != self.cleanup_verified
            or resolved != (self.resolved_at is not None)
            or resolved == self.lifecycle_actions_blocked
        ):
            raise ValueError("managed host cleanup block state is incoherent")
        return self


def require_mcp_managed_host_transition(
    previous: McpManagedHostState,
    next_state: McpManagedHostState,
) -> None:
    """Reject authority-skipping host transitions before any side effect."""

    if next_state not in _ALLOWED_TRANSITIONS[previous]:
        raise ValueError("managed host state transition is not allowed")


__all__ = (
    "MCP_MANAGED_HOST_CONTRACT_VERSION",
    "MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS",
    "MAX_MCP_MANAGED_ACTIVE_HOSTS",
    "MAX_MCP_MANAGED_HOST_HEALTH_SECONDS",
    "MAX_MCP_MANAGED_HOST_QUEUE",
    "MAX_MCP_MANAGED_HOST_START_SECONDS",
    "McpManagedHostBinding",
    "McpManagedHostActionReceipt",
    "McpManagedHostCleanupBlock",
    "McpManagedHostCleanupBlockReason",
    "McpManagedHostCleanupState",
    "McpManagedHostExecutionKind",
    "McpManagedHostPermission",
    "McpManagedHostReason",
    "McpManagedHostReceiptAction",
    "McpManagedHostReceiptOutcome",
    "McpManagedHostReceiptReason",
    "McpManagedHostRiskNotice",
    "McpManagedHostStartEffect",
    "McpManagedHostStartPreview",
    "McpManagedHostState",
    "McpManagedHostStatus",
    "StartMcpManagedHost",
    "StopMcpManagedHost",
    "build_mcp_managed_host_start_preview",
    "mcp_managed_host_binding_digest",
    "require_mcp_managed_host_transition",
)
