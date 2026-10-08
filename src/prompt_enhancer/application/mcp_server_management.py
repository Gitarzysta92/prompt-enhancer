"""Durable management records for reviewed MCP servers.

This boundary persists an exact reviewed Registry option, explicit project
permission decisions, content-free compatibility probes, remote activation
state, checksum-pinned local package evidence, and secret-vault state. A remote activation is durable configuration;
it does not retain a network connection, start a process, route a tool, or
grant model authority. A local install performs one bounded, owned compatibility
probe and retains no host; persistent hosting remains a separate boundary.
Secret values are accepted only as ``SecretStr``
and handed to an OS-backed vault; repository contracts never receive them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
from typing import Any, Literal, Protocol

from pydantic import Field, SecretStr, computed_field, field_validator, model_validator

from ..domain import StrictModel
from .mcp_guarded_host import (
    McpGuardedHost,
    McpGuardedHostError,
    McpHostProbeResult,
    McpRemoteConnectionSpec,
    McpRemoteHeader,
    McpReviewedToolContract,
    McpStdioConnectionSpec,
    project_mcp_tool_schema_for_model,
)
from .mcp_local_packages import (
    McpLocalPackageCleanupResult,
    McpLocalPackageConfigurationInspectionResult,
    McpLocalPackageInstallResult,
    McpLocalPackageInstaller,
    McpLocalPackageInstallerError,
    McpLocalPackageLaunchExpectation,
    McpLocalPackageStagedUpdateResult,
)
from .mcp_managed_host import (
    McpManagedHostBinding,
    McpManagedHostStartPreview,
    build_mcp_managed_host_start_preview,
)
from .mcp_registry_catalog import (
    McpRegistryCatalogError,
    McpRegistryCatalogService,
    McpRegistryInstallOption,
    McpRegistryResolvedLocalPackage,
    McpRegistryServerReview,
)


MCP_MANAGED_SERVER_CONTRACT_VERSION = "mcp-managed-server.v2"
MCP_MANAGED_SERVER_PATH = "/v1/integrations/mcp-store/managed"
MAX_MCP_MANAGED_SERVERS = 64
MAX_MCP_MANAGED_LIST = 64
MAX_MCP_SECRET_BYTES = 2_048

_ID_PATTERN = r"^[0-9a-f]{32}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_SERVER_NAME = re.compile(
    r"^[A-Za-z0-9.-]{1,160}/[A-Za-z0-9._-]{1,80}$"
)
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")

McpManagedPermission = Literal[
    "process_spawn",
    "filesystem_read",
    "filesystem_write",
    "network_egress",
    "credential_use",
]
McpManagedRequirementState = Literal[
    "publisher_value_declared",
    "registry_default_declared",
    "value_required",
    "value_pending_store",
    "value_stored",
    "value_store_failed",
    "value_pending_removal",
    "value_cleanup_required",
    "optional_unset",
    "secret_missing",
    "secret_pending_store",
    "secret_stored",
    "secret_store_failed",
    "secret_pending_removal",
    "secret_cleanup_required",
]
McpManagedSecretReferenceState = Literal[
    "pending_store",
    "active",
    "store_failed",
    "pending_removal",
    "cleanup_required",
]

_PERMISSION_ORDER: tuple[McpManagedPermission, ...] = (
    "process_spawn",
    "filesystem_read",
    "filesystem_write",
    "network_egress",
    "credential_use",
)


class McpManagedServerError(RuntimeError):
    """Closed, content-free management failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _sorted_permissions(
    values: Sequence[McpManagedPermission],
) -> tuple[McpManagedPermission, ...]:
    unique = set(values)
    return tuple(item for item in _PERMISSION_ORDER if item in unique)


class CreateMcpManagedServer(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    catalog_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=3, max_length=241)
    version: str = Field(min_length=1, max_length=255)
    option_id: str = Field(pattern=_ID_PATTERN)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _SERVER_NAME.fullmatch(value) is None:
            raise ValueError("invalid server name")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("invalid server version")
        return value


class SetMcpManagedProjectBinding(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    enabled: bool = Field(strict=True)
    granted_permissions: tuple[McpManagedPermission, ...] = Field(max_length=5)
    admitted_tool_ids: tuple[str, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def coherent_grants(self) -> "SetMcpManagedProjectBinding":
        if len(set(self.granted_permissions)) != len(self.granted_permissions):
            raise ValueError("permission grants must be unique")
        if tuple(self.granted_permissions) != _sorted_permissions(
            self.granted_permissions
        ):
            raise ValueError("permission grants are not canonical")
        if not self.enabled and self.granted_permissions:
            raise ValueError("a disabled binding cannot retain grants")
        if (
            len(set(self.admitted_tool_ids)) != len(self.admitted_tool_ids)
            or tuple(sorted(self.admitted_tool_ids)) != self.admitted_tool_ids
            or any(re.fullmatch(_ID_PATTERN, item) is None for item in self.admitted_tool_ids)
        ):
            raise ValueError("admitted MCP tool identities are not canonical")
        if not self.enabled and self.admitted_tool_ids:
            raise ValueError("a disabled binding cannot retain admitted tools")
        return self


class StoreMcpManagedSecret(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    value: SecretStr = Field(min_length=1, max_length=2_048, repr=False)

    @field_validator("value")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if "\x00" in raw or len(raw.encode("utf-8")) > MAX_MCP_SECRET_BYTES:
            raise ValueError("secret value is outside the vault bound")
        return value


class RemoveMcpManagedSecret(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


class StoreMcpManagedConfiguration(StrictModel):
    """One non-secret user value still retained only in the OS vault."""

    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    value: SecretStr = Field(min_length=1, max_length=2_048, repr=False)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if "\x00" in raw or "\r" in raw or "\n" in raw:
            raise ValueError("configuration value contains a control separator")
        if len(raw.encode("utf-8")) > MAX_MCP_SECRET_BYTES:
            raise ValueError("configuration value is outside the vault bound")
        return value


class RemoveMcpManagedConfiguration(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


McpManagedVaultStoreCommand = (
    StoreMcpManagedSecret | StoreMcpManagedConfiguration
)
McpManagedVaultRemoveCommand = (
    RemoveMcpManagedSecret | RemoveMcpManagedConfiguration
)


class ProbeMcpManagedServer(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


class ApplyMcpManagedLifecycle(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class InspectMcpManagedLocalConfiguration(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApplyMcpManagedLocalCleanup(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApplyMcpManagedLocalUpdate(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApplyMcpManagedLocalRollback(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApplyMcpManagedLocalRollbackCleanup(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApplyMcpManagedLocalOperationRecovery(StrictModel):
    request_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)


class McpManagedLocalOperationRecovery(StrictModel):
    operation_id: str = Field(pattern=_ID_PATTERN)
    action: Literal["update", "uninstall", "rollback", "cleanup"]
    status: Literal["cleanup_required"]
    expected_tree_digest: str = Field(pattern=_DIGEST_PATTERN)
    alternate_tree_digest: str | None = Field(
        default=None, pattern=_DIGEST_PATTERN
    )

    @model_validator(mode="after")
    def coherent_recovery(self) -> "McpManagedLocalOperationRecovery":
        if (self.action == "rollback") != (
            self.alternate_tree_digest is not None
        ):
            if self.action != "update":
                raise ValueError("managed local recovery evidence is incoherent")
        return self


class McpManagedSecretVaultStatus(StrictModel):
    provider: Literal["windows_credential_manager", "unavailable"]
    availability: Literal["available", "unavailable"]
    values_in_database: Literal[False] = False
    values_in_api_responses: Literal[False] = False
    values_in_model_context: Literal[False] = False

    @model_validator(mode="after")
    def coherent_provider(self) -> "McpManagedSecretVaultStatus":
        if (self.provider == "unavailable") != (self.availability == "unavailable"):
            raise ValueError("vault provider state is incoherent")
        return self


class McpManagedHostProbe(StrictModel):
    """Durable, content-free receipt for one successful compatibility probe."""

    request_id: str = Field(pattern=_ID_PATTERN)
    checked_at: datetime
    transport: Literal["stdio", "streamable-http", "sse"]
    protocol_version: str = Field(pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
    tool_count: int = Field(strict=True, ge=0, le=256)
    schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    elapsed_ms: int = Field(strict=True, ge=0, le=120_000)
    connection_state: Literal["closed_after_probe"] = "closed_after_probe"
    process_started: bool
    process_tree_cleanup: Literal["verified", "not_applicable"]
    tool_names_persisted: bool = False
    tool_schemas_persisted: bool = False
    tool_results_requested: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_probe(self) -> "McpManagedHostProbe":
        expected = "verified" if self.process_started else "not_applicable"
        if self.process_tree_cleanup != expected:
            raise ValueError("managed MCP probe cleanup is incoherent")
        if self.tool_names_persisted != self.tool_schemas_persisted:
            raise ValueError("managed MCP probe retention truth is incoherent")
        return self


class McpManagedReviewedTool(StrictModel):
    """One owner-reviewable, local-only MCP tool contract."""

    tool_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1, max_length=4_096)
    model_alias: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    input_schema: dict[str, Any]
    input_schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    model_input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    output_schema_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    contract_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if _TOOL_NAME.fullmatch(value) is None:
            raise ValueError("managed MCP tool name is invalid")
        return value

    @field_validator("title", "description")
    @classmethod
    def validate_display_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip() != value or "\r" in value or any(
            (ord(character) < 32 and character not in {"\n", "\t"})
            or ord(character) == 127
            for character in value
        ):
            raise ValueError("managed MCP tool metadata is invalid")
        return value

    @classmethod
    def from_guarded(cls, value: McpReviewedToolContract) -> "McpManagedReviewedTool":
        return cls.model_validate(value.model_dump(mode="python"))

    @model_validator(mode="after")
    def coherent_schema(self) -> "McpManagedReviewedTool":
        if (self.output_schema is None) != (self.output_schema_digest is None):
            raise ValueError("managed MCP output schema evidence is incoherent")
        if self.input_schema.get("type") not in (None, "object"):
            raise ValueError("managed MCP input schema root is invalid")
        try:
            input_digest = _canonical_digest(self.input_schema)
            output_digest = (
                None
                if self.output_schema is None
                else _canonical_digest(self.output_schema)
            )
            contract_digest = _canonical_digest(
                {
                    "name": self.name,
                    "title": self.title,
                    "description": self.description,
                    "input": self.input_schema,
                    "output": self.output_schema,
                }
            )
            _canonical_digest(self.model_input_schema)
            expected_model_schema = project_mcp_tool_schema_for_model(
                self.input_schema
            )
        except (
            McpGuardedHostError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            raise ValueError("managed MCP tool schema is invalid") from None
        if (
            input_digest != self.input_schema_digest
            or output_digest != self.output_schema_digest
            or contract_digest != self.contract_digest
            or contract_digest[:32] != self.tool_id
            or expected_model_schema != self.model_input_schema
        ):
            raise ValueError("managed MCP tool digest evidence is incoherent")
        return self


class McpManagedToolSnapshotSummary(StrictModel):
    snapshot_id: str = Field(pattern=_ID_PATTERN)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    source: Literal["remote_probe", "local_package_probe"]
    source_tree_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    source_manifest_digest: str | None = Field(
        default=None,
        pattern=_DIGEST_PATTERN,
    )
    protocol_version: str = Field(pattern=r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
    tool_count: int = Field(strict=True, ge=0, le=256)
    schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    reviewed_at: datetime
    tool_names_retained_locally: Literal[True] = True
    tool_schemas_retained_locally: Literal[True] = True
    connection_retained: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @field_validator("reviewed_at")
    @classmethod
    def normalize_reviewed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_source(self) -> "McpManagedToolSnapshotSummary":
        local = self.source == "local_package_probe"
        if local != (self.source_tree_digest is not None) or local != (
            self.source_manifest_digest is not None
        ):
            raise ValueError("managed MCP tool snapshot source is incoherent")
        return self


class McpManagedToolSnapshot(McpManagedToolSnapshotSummary):
    contract_version: Literal["mcp-managed-tool-snapshot.v1"] = (
        "mcp-managed-tool-snapshot.v1"
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    tools: tuple[McpManagedReviewedTool, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def coherent_tools(self) -> "McpManagedToolSnapshot":
        if len(self.tools) != self.tool_count:
            raise ValueError("managed MCP tool snapshot count is incoherent")
        if (
            len({item.tool_id for item in self.tools}) != len(self.tools)
            or len({item.name for item in self.tools}) != len(self.tools)
            or len({item.model_alias for item in self.tools}) != len(self.tools)
        ):
            raise ValueError("managed MCP tool snapshot identities are not unique")
        return self


class McpManagedRequirement(StrictModel):
    requirement_id: str = Field(pattern=_ID_PATTERN)
    location: Literal[
        "runtime_argument",
        "package_argument",
        "environment_variable",
        "transport_header",
        "remote_variable",
    ]
    name: str = Field(min_length=1, max_length=128)
    required: bool
    secret: bool
    format: Literal["string", "number", "boolean", "filepath", "unknown"]
    user_value_needed: bool
    configuration_state: McpManagedRequirementState
    secret_vault_provider: Literal["windows_credential_manager"] | None
    value_vault_provider: Literal["windows_credential_manager"] | None = None

    @model_validator(mode="after")
    def coherent_state(self) -> "McpManagedRequirement":
        secret_states = {
            "secret_missing",
            "secret_pending_store",
            "secret_stored",
            "secret_store_failed",
            "secret_pending_removal",
            "secret_cleanup_required",
        }
        value_states = {
            "value_pending_store",
            "value_stored",
            "value_store_failed",
            "value_pending_removal",
            "value_cleanup_required",
        }
        if self.secret:
            if self.configuration_state not in secret_states:
                raise ValueError("secret requirement has a non-secret state")
            has_reference = self.configuration_state != "secret_missing"
            if has_reference != (self.secret_vault_provider is not None):
                raise ValueError("secret reference state is incoherent")
            if self.value_vault_provider is not None:
                raise ValueError("secret requirement has an ordinary-value provider")
        elif (
            self.configuration_state in secret_states
            or self.secret_vault_provider is not None
        ):
            raise ValueError("non-secret requirement has vault state")
        elif self.user_value_needed:
            if self.configuration_state not in {"value_required", *value_states}:
                raise ValueError("user configuration state is incoherent")
            has_reference = self.configuration_state != "value_required"
            if has_reference != (self.value_vault_provider is not None):
                raise ValueError("configuration reference state is incoherent")
        elif (
            self.configuration_state in value_states
            or self.value_vault_provider is not None
        ):
            raise ValueError("declared configuration has user vault state")
        return self


class McpManagedProjectBinding(StrictModel):
    project_id: str = Field(pattern=_ID_PATTERN)
    project_name: str = Field(min_length=1, max_length=120)
    enabled: bool
    required_permissions: tuple[McpManagedPermission, ...] = Field(max_length=5)
    granted_permissions: tuple[McpManagedPermission, ...] = Field(max_length=5)
    admitted_tool_ids: tuple[str, ...] = Field(max_length=256)
    tool_snapshot_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    admission_state: Literal["disabled", "review_required", "admitted"]
    effective_state: Literal[
        "disabled",
        "inactive_tool_review_required",
        "inactive_install_required",
        "inactive_host_unavailable",
    ]
    created_at: datetime
    updated_at: datetime
    revision: int = Field(strict=True, ge=1)

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_binding(self) -> "McpManagedProjectBinding":
        required = _sorted_permissions(self.required_permissions)
        granted = _sorted_permissions(self.granted_permissions)
        if required != self.required_permissions or granted != self.granted_permissions:
            raise ValueError("project permissions are not canonical")
        if self.updated_at < self.created_at:
            raise ValueError("binding timestamps are incoherent")
        if self.enabled:
            if granted != required or self.effective_state == "disabled":
                raise ValueError("enabled binding is not safely bounded")
            if self.admission_state == "admitted":
                if not self.admitted_tool_ids or self.tool_snapshot_id is None:
                    raise ValueError("admitted binding lacks exact tools")
                if self.effective_state not in {
                    "inactive_install_required",
                    "inactive_host_unavailable",
                }:
                    raise ValueError("admitted binding has an incoherent state")
            elif (
                self.admission_state != "review_required"
                or self.admitted_tool_ids
                or self.tool_snapshot_id is not None
                or self.effective_state != "inactive_tool_review_required"
            ):
                raise ValueError("unreviewed binding retains tool admission")
        elif (
            granted
            or self.admitted_tool_ids
            or self.tool_snapshot_id is not None
            or self.admission_state != "disabled"
            or self.effective_state != "disabled"
        ):
            raise ValueError("disabled binding retains authority")
        if (
            len(set(self.admitted_tool_ids)) != len(self.admitted_tool_ids)
            or tuple(sorted(self.admitted_tool_ids)) != self.admitted_tool_ids
        ):
            raise ValueError("admitted MCP tools are not canonical")
        return self


class McpManagedLifecyclePreview(StrictModel):
    contract_version: Literal["mcp-managed-lifecycle-preview.v1"] = (
        "mcp-managed-lifecycle-preview.v1"
    )
    action: Literal["install", "uninstall"]
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    installation_kind: Literal["remote_activation", "local_package"]
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "compatibility_check_required",
        "configuration_required",
        "configuration_inspection_required",
        "package_registry_not_supported",
        "package_integrity_required",
        "local_transport_unsupported",
        "local_installer_unavailable",
        "local_uninstaller_unavailable",
        "already_installed",
        "not_installed",
        "cleanup_required",
        "operation_in_progress",
    ]
    effects: tuple[
        Literal[
            "persist_remote_activation",
            "remove_remote_activation",
            "download_exact_package",
            "verify_artifact_sha256",
            "stage_isolated_package",
            "execute_bounded_compatibility_probe",
            "stop_and_verify_process_tree",
            "publish_verified_package",
            "verify_installed_tree_digest",
            "quarantine_verified_package",
            "remove_quarantined_package",
            "no_package_change",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ] = Field(min_length=4, max_length=10)
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLifecyclePreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed lifecycle availability is incoherent")
        if self.installation_kind == "remote_activation":
            expected_effect = (
                "persist_remote_activation"
                if self.action == "install"
                else "remove_remote_activation"
            )
        else:
            expected_effect = (
                "download_exact_package"
                if self.action == "install"
                else "verify_installed_tree_digest"
            )
        if expected_effect not in self.effects or len(set(self.effects)) != len(
            self.effects
        ):
            raise ValueError("managed lifecycle effects are incoherent")
        return self


class McpManagedLocalCleanupPreview(StrictModel):
    contract_version: Literal["mcp-managed-local-cleanup-preview.v1"] = (
        "mcp-managed-local-cleanup-preview.v1"
    )
    action: Literal["complete_interrupted_uninstall"] = (
        "complete_interrupted_uninstall"
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "cleanup_not_required",
        "unsupported_cleanup_state",
        "local_uninstaller_unavailable",
    ]
    effects: tuple[
        Literal[
            "verify_operation_journal",
            "verify_installed_or_quarantined_tree_digest",
            "finish_quarantined_removal",
            "clear_cleanup_state",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalCleanupPreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed local cleanup availability is incoherent")
        expected = (
            "verify_operation_journal",
            "verify_installed_or_quarantined_tree_digest",
            "finish_quarantined_removal",
            "clear_cleanup_state",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        if self.effects != expected:
            raise ValueError("managed local cleanup effects are incoherent")
        return self


class McpManagedLocalConfigurationInspectionPreview(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-configuration-inspection-preview.v1"
    ] = "mcp-managed-local-configuration-inspection-preview.v1"
    action: Literal["inspect_configuration"] = "inspect_configuration"
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "local_package_required",
        "already_inspected",
        "already_installed",
        "cleanup_required",
        "operation_in_progress",
        "package_registry_not_supported",
        "package_integrity_required",
        "local_transport_unsupported",
        "local_installer_unavailable",
    ]
    effects: tuple[
        Literal[
            "download_exact_package",
            "verify_artifact_sha256",
            "inspect_manifest_configuration",
            "discard_inspection_archive",
            "persist_content_free_configuration_schema",
            "revoke_project_bindings_if_permissions_expand",
            "no_configuration_values_persisted",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalConfigurationInspectionPreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed configuration inspection availability is incoherent")
        expected = (
            "download_exact_package",
            "verify_artifact_sha256",
            "inspect_manifest_configuration",
            "discard_inspection_archive",
            "persist_content_free_configuration_schema",
            "revoke_project_bindings_if_permissions_expand",
            "no_configuration_values_persisted",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        if self.effects != expected:
            raise ValueError("managed configuration inspection effects are incoherent")
        return self


class McpManagedLocalUpdatePreview(StrictModel):
    contract_version: Literal["mcp-managed-local-update-preview.v1"] = (
        "mcp-managed-local-update-preview.v1"
    )
    action: Literal["update"] = "update"
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    current_version: str = Field(min_length=1, max_length=255)
    current_plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    target_version: str | None = Field(default=None, min_length=1, max_length=255)
    target_catalog_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    target_option_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    target_plan_revision: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "local_package_required",
        "install_required",
        "cleanup_required",
        "operation_in_progress",
        "registry_unavailable",
        "already_latest",
        "current_version_metadata_changed",
        "rollback_cleanup_required",
        "configuration_migration_required",
        "target_not_installable",
        "target_option_ambiguous",
        "permission_change_required",
        "local_installer_unavailable",
    ]
    effects: tuple[
        Literal[
            "resolve_official_latest_exact_version",
            "download_exact_target_package",
            "verify_target_artifact_sha256",
            "stage_target_in_isolation",
            "execute_bounded_target_probe",
            "stop_and_verify_target_process_tree",
            "retain_verified_rollback_generation",
            "publish_verified_target_package",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalUpdatePreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed local update availability is incoherent")
        expected = (
            "resolve_official_latest_exact_version",
            "download_exact_target_package",
            "verify_target_artifact_sha256",
            "stage_target_in_isolation",
            "execute_bounded_target_probe",
            "stop_and_verify_target_process_tree",
            "retain_verified_rollback_generation",
            "publish_verified_target_package",
            "no_connection_retained",
            "no_tool_authority",
        )
        if self.effects != expected:
            raise ValueError("managed local update effects are incoherent")
        if self.availability == "available" and (
            self.target_version is None
            or self.target_catalog_id is None
            or self.target_option_id is None
            or self.target_plan_revision is None
            or self.target_version == self.current_version
        ):
            raise ValueError("managed local update target is incoherent")
        if any(
            value is not None
            for value in (
                self.target_catalog_id,
                self.target_option_id,
                self.target_plan_revision,
            )
        ) and any(
            value is None
            for value in (
                self.target_catalog_id,
                self.target_option_id,
                self.target_plan_revision,
            )
        ):
            raise ValueError("managed local update target identity is partial")
        return self


class McpManagedLocalRollbackPreview(StrictModel):
    contract_version: Literal["mcp-managed-local-rollback-preview.v1"] = (
        "mcp-managed-local-rollback-preview.v1"
    )
    action: Literal["rollback"] = "rollback"
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    current_version: str = Field(min_length=1, max_length=255)
    current_plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    target_version: str | None = Field(default=None, min_length=1, max_length=255)
    target_plan_revision: str | None = Field(
        default=None, pattern=_DIGEST_PATTERN
    )
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "local_package_required",
        "install_required",
        "cleanup_required",
        "operation_in_progress",
        "rollback_generation_missing",
        "local_installer_unavailable",
    ]
    effects: tuple[
        Literal[
            "verify_current_tree_digest",
            "verify_rollback_tree_digest",
            "atomically_swap_verified_generations",
            "retain_superseded_current_generation",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalRollbackPreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed local rollback availability is incoherent")
        if (self.target_version is None) != (self.target_plan_revision is None):
            raise ValueError("managed local rollback target is partial")
        if self.availability == "available" and (
            self.target_version is None or self.target_plan_revision is None
        ):
            raise ValueError("managed local rollback target is missing")
        expected = (
            "verify_current_tree_digest",
            "verify_rollback_tree_digest",
            "atomically_swap_verified_generations",
            "retain_superseded_current_generation",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        if self.effects != expected:
            raise ValueError("managed local rollback effects are incoherent")
        return self


class McpManagedLocalRollbackCleanupPreview(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-rollback-cleanup-preview.v1"
    ] = "mcp-managed-local-rollback-cleanup-preview.v1"
    action: Literal["cleanup_rollback_generation"] = (
        "cleanup_rollback_generation"
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    rollback_version: str | None = Field(default=None, min_length=1, max_length=255)
    rollback_plan_revision: str | None = Field(
        default=None, pattern=_DIGEST_PATTERN
    )
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "local_package_required",
        "install_required",
        "cleanup_required",
        "operation_in_progress",
        "rollback_generation_missing",
        "local_installer_unavailable",
    ]
    effects: tuple[
        Literal[
            "verify_rollback_tree_digest",
            "quarantine_verified_rollback_generation",
            "remove_quarantined_rollback_generation",
            "keep_current_generation_installed",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalRollbackCleanupPreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed rollback cleanup availability is incoherent")
        if (self.rollback_version is None) != (
            self.rollback_plan_revision is None
        ):
            raise ValueError("managed rollback cleanup target is partial")
        if self.availability == "available" and self.rollback_version is None:
            raise ValueError("managed rollback cleanup target is missing")
        expected = (
            "verify_rollback_tree_digest",
            "quarantine_verified_rollback_generation",
            "remove_quarantined_rollback_generation",
            "keep_current_generation_installed",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        if self.effects != expected:
            raise ValueError("managed rollback cleanup effects are incoherent")
        return self


class McpManagedLocalOperationRecoveryPreview(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-operation-recovery-preview.v1"
    ] = "mcp-managed-local-operation-recovery-preview.v1"
    action: Literal["recover_interrupted_local_operation"] = (
        "recover_interrupted_local_operation"
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)
    interrupted_action: Literal["update", "rollback", "cleanup"] | None
    availability: Literal["available", "unavailable"]
    reason: Literal[
        "ready_for_native_confirmation",
        "cleanup_not_required",
        "unsupported_cleanup_state",
        "process_cleanup_unconfirmed",
        "local_installer_unavailable",
    ]
    effects: tuple[
        Literal[
            "verify_operation_journal",
            "restore_durable_current_generation",
            "discard_verified_staged_target",
            "retain_verified_rollback_generation",
            "finish_verified_rollback_generation_removal",
            "clear_cleanup_state",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    native_confirmation_required: Literal[True] = True

    @model_validator(mode="after")
    def coherent_preview(self) -> "McpManagedLocalOperationRecoveryPreview":
        if (self.availability == "available") != (
            self.reason == "ready_for_native_confirmation"
        ):
            raise ValueError("managed operation recovery availability is incoherent")
        if self.availability == "available" and self.interrupted_action is None:
            raise ValueError("managed operation recovery action is missing")
        if self.effects[0] != "verify_operation_journal" or self.effects[-3:] != (
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ):
            raise ValueError("managed operation recovery effects are incoherent")
        return self


class McpManagedLocalPackageEvidence(StrictModel):
    """Durable content-free identity for one verified installed package tree."""

    artifact_sha256: str = Field(pattern=_DIGEST_PATTERN)
    artifact_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    tree_digest: str = Field(pattern=_DIGEST_PATTERN)
    manifest_digest: str = Field(pattern=_DIGEST_PATTERN)
    manifest_version: Literal["0.3", "0.4"]
    license_state: Literal["declared"] = "declared"
    runtime_kind: Literal["node", "python", "binary"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def coherent_runtime(self) -> "McpManagedLocalPackageEvidence":
        if (self.runtime_kind == "binary") != (self.runtime_version is None):
            raise ValueError("managed local package runtime evidence is incoherent")
        return self


class McpManagedLocalConfigurationInspection(StrictModel):
    """Durable content-free evidence from one non-executing MCPB inspection."""

    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    artifact_sha256: str = Field(pattern=_DIGEST_PATTERN)
    artifact_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    manifest_digest: str = Field(pattern=_DIGEST_PATTERN)
    manifest_version: Literal["0.3", "0.4"]
    configuration_schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    requirement_ids: tuple[str, ...] = Field(max_length=32)
    inspected_at: datetime
    archive_retained: Literal[False] = False
    process_started: Literal[False] = False
    configuration_values_persisted: Literal[False] = False
    manifest_content_persisted: Literal[False] = False

    @field_validator("inspected_at")
    @classmethod
    def normalize_inspected_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_requirements(self) -> "McpManagedLocalConfigurationInspection":
        if (
            len(set(self.requirement_ids)) != len(self.requirement_ids)
            or any(re.fullmatch(_ID_PATTERN, item) is None for item in self.requirement_ids)
        ):
            raise ValueError("managed configuration requirements are not unique")
        return self


class McpManagedLocalUpdateTarget(StrictModel):
    """Exact public plan metadata persisted before a target tree is published."""

    catalog_id: str = Field(pattern=_ID_PATTERN)
    server_name: str = Field(min_length=3, max_length=241)
    server_title: str = Field(min_length=1, max_length=100)
    server_version: str = Field(min_length=1, max_length=255)
    server_status_at_review: Literal["active", "deprecated", "deleted"]
    option_id: str = Field(pattern=_ID_PATTERN)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    option_label: str = Field(min_length=1, max_length=120)
    registry_type: Literal["mcpb"] = "mcpb"
    package_identifier: str = Field(min_length=1, max_length=512)
    package_version: str | None = Field(default=None, min_length=1, max_length=255)
    runtime_hint: str | None = Field(default=None, min_length=1, max_length=32)
    transport: Literal["stdio"] = "stdio"
    required_permissions: tuple[McpManagedPermission, ...] = Field(max_length=5)
    risks: tuple[
        Literal[
            "downloads_package",
            "executes_local_code",
            "package_integrity_not_declared",
            "command_arguments_declared",
            "filesystem_input_declared",
            "credential_input_declared",
            "remote_network_egress",
            "insecure_remote_transport",
        ],
        ...,
    ] = Field(max_length=8)

    @model_validator(mode="after")
    def coherent_target(self) -> "McpManagedLocalUpdateTarget":
        if _SERVER_NAME.fullmatch(self.server_name) is None:
            raise ValueError("invalid managed update server name")
        if self.required_permissions != _sorted_permissions(
            self.required_permissions
        ):
            raise ValueError("managed update permissions are not canonical")
        return self


class McpManagedLocalRollbackGeneration(McpManagedLocalUpdateTarget):
    """One bounded content-free generation retained for an exact rollback."""

    generation_id: str = Field(pattern=_ID_PATTERN)
    local_package_evidence: McpManagedLocalPackageEvidence
    probe: McpManagedHostProbe
    installed_at: datetime
    retained_at: datetime

    @field_validator("installed_at", "retained_at")
    @classmethod
    def normalize_generation_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_generation(self) -> "McpManagedLocalRollbackGeneration":
        if (
            self.probe.transport != "stdio"
            or not self.probe.process_started
            or self.probe.process_tree_cleanup != "verified"
            or self.retained_at < self.installed_at
        ):
            raise ValueError("managed rollback generation is incoherent")
        return self


class McpManagedServer(StrictModel):
    contract_version: Literal["mcp-managed-server.v2"] = (
        MCP_MANAGED_SERVER_CONTRACT_VERSION
    )
    management_id: str = Field(pattern=_ID_PATTERN)
    catalog_id: str = Field(pattern=_ID_PATTERN)
    server_name: str = Field(min_length=3, max_length=241)
    server_title: str = Field(min_length=1, max_length=100)
    server_version: str = Field(min_length=1, max_length=255)
    server_status_at_review: Literal["active", "deprecated", "deleted"]
    option_id: str = Field(pattern=_ID_PATTERN)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    option_kind: Literal["local_package", "remote_server"]
    option_label: str = Field(min_length=1, max_length=120)
    registry_type: str | None = Field(default=None, min_length=1, max_length=32)
    package_identifier: str | None = Field(default=None, min_length=1, max_length=512)
    package_version: str | None = Field(default=None, min_length=1, max_length=255)
    runtime_hint: str | None = Field(default=None, min_length=1, max_length=32)
    transport: Literal["stdio", "streamable-http", "sse", "unknown"]
    endpoint_host: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_state: Literal[
        "not_applicable",
        "fixed_host",
        "template_requires_configuration",
        "invalid",
    ]
    secure_transport: bool | None
    required_permissions: tuple[McpManagedPermission, ...] = Field(max_length=5)
    risks: tuple[
        Literal[
            "downloads_package",
            "executes_local_code",
            "package_integrity_not_declared",
            "command_arguments_declared",
            "filesystem_input_declared",
            "credential_input_declared",
            "remote_network_egress",
            "insecure_remote_transport",
        ],
        ...,
    ] = Field(max_length=8)
    requirements: tuple[McpManagedRequirement, ...] = Field(max_length=64)
    project_bindings: tuple[McpManagedProjectBinding, ...] = Field(max_length=64)
    created_at: datetime
    updated_at: datetime
    revision: int = Field(strict=True, ge=1)
    lifecycle_state: Literal["planned", "installed", "cleanup_required"] = "planned"
    installation_state: Literal[
        "not_installed", "installed", "cleanup_required"
    ] = "not_installed"
    installation_kind: Literal["none", "remote_activation", "local_package"] = (
        "none"
    )
    operation_state: Literal[
        "idle",
        "installing",
        "updating",
        "uninstalling",
        "rolling_back",
        "cleaning_up",
        "cleanup_required",
    ] = "idle"
    installed_plan_revision: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    installed_at: datetime | None = None
    local_package_evidence: McpManagedLocalPackageEvidence | None = None
    local_configuration_inspection: (
        McpManagedLocalConfigurationInspection | None
    ) = None
    rollback_generation: McpManagedLocalRollbackGeneration | None = None
    process_tree_cleanup: Literal["not_applicable", "verified", "unconfirmed"] = (
        "not_applicable"
    )
    host_state: Literal["not_started"] = "not_started"
    health_state: Literal["not_checked", "compatible"] = "not_checked"
    last_health_checked_at: datetime | None = None
    last_probe: McpManagedHostProbe | None = None
    tool_snapshot: McpManagedToolSnapshotSummary | None = None
    tool_review_state: Literal["probe_required", "reviewable"] = "probe_required"
    update_state: Literal["not_checked"] = "not_checked"
    latest_available_version: None = None
    tool_routing_state: Literal["inactive"] = "inactive"
    @computed_field
    @property
    def install_action(
        self,
    ) -> Literal[
        "available_native_confirmation_required",
        "unavailable_compatibility_check_required",
        "unavailable_configuration_required",
        "unavailable_package_registry_not_supported",
        "unavailable_package_integrity_required",
        "unavailable_local_transport_unsupported",
        "unavailable_configuration_inspection_required",
        "unavailable_cleanup_required",
        "unavailable_operation_in_progress",
        "not_applicable_already_installed",
    ]:
        if self.installation_state == "cleanup_required":
            return "unavailable_cleanup_required"
        if self.operation_state != "idle":
            return "unavailable_operation_in_progress"
        if self.installation_state == "installed":
            return "not_applicable_already_installed"
        if self.option_kind == "local_package":
            if self.registry_type != "mcpb":
                return "unavailable_package_registry_not_supported"
            if "package_integrity_not_declared" in self.risks:
                return "unavailable_package_integrity_required"
            if self.transport != "stdio":
                return "unavailable_local_transport_unsupported"
            if self.local_configuration_inspection is None:
                return "unavailable_configuration_inspection_required"
        blocked = {
            "value_required",
            "value_pending_store",
            "value_store_failed",
            "value_pending_removal",
            "value_cleanup_required",
            "secret_missing",
            "secret_pending_store",
            "secret_store_failed",
            "secret_pending_removal",
            "secret_cleanup_required",
        }
        if any(item.configuration_state in blocked for item in self.requirements):
            return "unavailable_configuration_required"
        if self.option_kind == "local_package":
            return "available_native_confirmation_required"
        if self.health_state != "compatible":
            return "unavailable_compatibility_check_required"
        return "available_native_confirmation_required"

    @computed_field
    @property
    def uninstall_action(
        self,
    ) -> Literal[
        "available_native_confirmation_required",
        "not_applicable_not_installed",
        "unavailable_cleanup_required",
        "unavailable_operation_in_progress",
    ]:
        if self.installation_state == "cleanup_required":
            return "unavailable_cleanup_required"
        if self.operation_state != "idle":
            return "unavailable_operation_in_progress"
        if self.installation_state == "installed":
            return "available_native_confirmation_required"
        return "not_applicable_not_installed"

    @computed_field
    @property
    def probe_action(
        self,
    ) -> Literal[
        "available_native_confirmation_required",
        "unavailable_install_required",
        "unavailable_configuration_required",
        "unavailable_option_unsupported",
        "not_applicable_verified_during_install",
    ]:
        if self.option_kind == "local_package":
            return (
                "not_applicable_verified_during_install"
                if self.installation_state == "installed" and self.last_probe is not None
                else "unavailable_install_required"
            )
        if (
            self.transport not in {"streamable-http", "sse"}
            or self.endpoint_state not in {
                "fixed_host",
                "template_requires_configuration",
            }
            or (
                self.endpoint_state == "fixed_host"
                and self.secure_transport is not True
            )
        ):
            return "unavailable_option_unsupported"
        blocked = {
            "value_required",
            "value_pending_store",
            "value_store_failed",
            "value_pending_removal",
            "value_cleanup_required",
            "secret_missing",
            "secret_pending_store",
            "secret_store_failed",
            "secret_pending_removal",
            "secret_cleanup_required",
        }
        if any(item.configuration_state in blocked for item in self.requirements):
            return "unavailable_configuration_required"
        return "available_native_confirmation_required"

    @field_validator(
        "created_at", "updated_at", "last_health_checked_at", "installed_at"
    )
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def coherent_record(self) -> "McpManagedServer":
        if _SERVER_NAME.fullmatch(self.server_name) is None:
            raise ValueError("invalid managed server name")
        if self.updated_at < self.created_at:
            raise ValueError("managed server timestamps are incoherent")
        if self.required_permissions != _sorted_permissions(
            self.required_permissions
        ):
            raise ValueError("managed permissions are not canonical")
        if self.option_kind == "local_package":
            if (
                self.registry_type is None
                or self.package_identifier is None
                or self.endpoint_host is not None
                or self.endpoint_state != "not_applicable"
                or self.secure_transport is not None
            ):
                raise ValueError("managed local package identity is incomplete")
        else:
            if any(
                value is not None
                for value in (
                    self.registry_type,
                    self.package_identifier,
                    self.package_version,
                    self.runtime_hint,
                )
            ) or self.endpoint_state == "not_applicable":
                raise ValueError("managed remote option contains incoherent identity")
            if self.local_configuration_inspection is not None:
                raise ValueError("managed remote option has a local inspection")
        if self.local_configuration_inspection is not None:
            inspection = self.local_configuration_inspection
            if (
                self.option_kind != "local_package"
                or inspection.plan_revision != self.plan_revision
                or not set(inspection.requirement_ids).issubset(
                    {item.requirement_id for item in self.requirements}
                )
            ):
                raise ValueError("managed local configuration inspection is incoherent")
        if self.endpoint_state == "fixed_host":
            if self.endpoint_host is None or self.secure_transport is None:
                raise ValueError("managed fixed endpoint is incomplete")
        elif self.endpoint_host is not None or (
            self.endpoint_state != "not_applicable"
            and self.secure_transport is not None
        ):
            raise ValueError("managed endpoint state is incoherent")
        if len({item.requirement_id for item in self.requirements}) != len(
            self.requirements
        ):
            raise ValueError("managed requirements are not unique")
        if len({item.project_id for item in self.project_bindings}) != len(
            self.project_bindings
        ):
            raise ValueError("managed project bindings are not unique")
        if any(
            item.required_permissions != self.required_permissions
            for item in self.project_bindings
        ):
            raise ValueError("managed project permissions do not match the plan")
        if self.last_probe is None:
            if self.health_state != "not_checked" or self.last_health_checked_at is not None:
                raise ValueError("managed MCP health state lacks a probe")
        elif (
            self.health_state != "compatible"
            or self.last_health_checked_at != self.last_probe.checked_at
            or self.last_probe.transport != self.transport
        ):
            raise ValueError("managed MCP health state is incoherent")
        if self.tool_snapshot is None:
            if self.tool_review_state != "probe_required":
                raise ValueError("managed MCP tool review lacks a snapshot")
        elif (
            self.tool_review_state != "reviewable"
            or self.last_probe is None
            or self.tool_snapshot.plan_revision != self.plan_revision
            or self.tool_snapshot.protocol_version != self.last_probe.protocol_version
            or self.tool_snapshot.tool_count != self.last_probe.tool_count
            or self.tool_snapshot.schema_digest != self.last_probe.schema_digest
            or not self.last_probe.tool_names_persisted
            or not self.last_probe.tool_schemas_persisted
        ):
            raise ValueError("managed MCP tool review state is incoherent")
        if self.tool_snapshot is not None:
            if self.tool_snapshot.source == "local_package_probe":
                if (
                    self.option_kind != "local_package"
                    or self.local_package_evidence is None
                    or self.tool_snapshot.source_tree_digest
                    != self.local_package_evidence.tree_digest
                    or self.tool_snapshot.source_manifest_digest
                    != self.local_package_evidence.manifest_digest
                ):
                    raise ValueError(
                        "managed MCP local tool snapshot does not match the package"
                    )
            elif self.option_kind != "remote_server":
                raise ValueError(
                    "managed MCP remote tool snapshot does not match the plan"
                )
        admitted_bindings = tuple(
            item
            for item in self.project_bindings
            if item.admission_state == "admitted"
        )
        if admitted_bindings and self.tool_snapshot is None:
            raise ValueError("managed MCP binding lacks a current tool snapshot")
        if self.tool_snapshot is not None and any(
            item.tool_snapshot_id != self.tool_snapshot.snapshot_id
            for item in admitted_bindings
        ):
            raise ValueError("managed MCP binding targets a stale tool snapshot")
        if self.installation_state == "not_installed":
            if (
                self.lifecycle_state != "planned"
                or self.installation_kind != "none"
                or self.installed_plan_revision is not None
                or self.installed_at is not None
                or self.local_package_evidence is not None
                or self.rollback_generation is not None
                or self.process_tree_cleanup != "not_applicable"
            ):
                raise ValueError("managed uninstalled lifecycle is incoherent")
        elif self.installation_state == "installed":
            if (
                self.lifecycle_state != "installed"
                or self.installation_kind == "none"
                or self.installed_plan_revision != self.plan_revision
                or self.installed_at is None
            ):
                raise ValueError("managed installed lifecycle is incoherent")
            if self.installation_kind == "remote_activation" and (
                self.option_kind != "remote_server"
                or self.process_tree_cleanup != "not_applicable"
                or self.local_package_evidence is not None
                or self.rollback_generation is not None
            ):
                raise ValueError("managed remote activation is incoherent")
            if self.installation_kind == "local_package" and (
                self.option_kind != "local_package"
                or self.process_tree_cleanup != "verified"
                or self.local_package_evidence is None
                or self.last_probe is None
                or not self.last_probe.process_started
                or self.last_probe.process_tree_cleanup != "verified"
            ):
                raise ValueError("managed local package installation is incoherent")
            if (
                self.installation_kind == "local_package"
                and self.local_configuration_inspection is not None
                and self.local_package_evidence is not None
                and (
                    self.local_configuration_inspection.artifact_sha256
                    != self.local_package_evidence.artifact_sha256
                    or self.local_configuration_inspection.manifest_digest
                    != self.local_package_evidence.manifest_digest
                    or self.local_configuration_inspection.manifest_version
                    != self.local_package_evidence.manifest_version
                )
            ):
                raise ValueError(
                    "managed local package does not match its configuration inspection"
                )
            if self.rollback_generation is not None and (
                self.rollback_generation.server_name != self.server_name
                or self.rollback_generation.plan_revision == self.plan_revision
                or self.rollback_generation.required_permissions
                != self.required_permissions
            ):
                raise ValueError("managed rollback generation does not match the plan")
        elif (
            self.lifecycle_state != "cleanup_required"
            or self.operation_state != "cleanup_required"
        ):
            raise ValueError("managed cleanup lifecycle is incoherent")
        return self


class McpManagedServerList(StrictModel):
    contract_version: Literal["mcp-managed-server.v2"] = (
        MCP_MANAGED_SERVER_CONTRACT_VERSION
    )
    servers: tuple[McpManagedServer, ...] = Field(max_length=MAX_MCP_MANAGED_LIST)
    total: int = Field(strict=True, ge=0, le=MAX_MCP_MANAGED_SERVERS)
    secret_vault: McpManagedSecretVaultStatus
    execution_truth: Literal[
        "reviewed_tool_admission_without_persistent_host_or_tool_authority"
    ] = (
        "reviewed_tool_admission_without_persistent_host_or_tool_authority"
    )

    @model_validator(mode="after")
    def coherent_total(self) -> "McpManagedServerList":
        if self.total != len(self.servers):
            raise ValueError("managed server total is incoherent")
        if len({item.management_id for item in self.servers}) != len(self.servers):
            raise ValueError("managed server identities are not unique")
        return self


class McpManagedServerReceipt(StrictModel):
    contract_version: Literal["mcp-managed-server.v2"] = (
        MCP_MANAGED_SERVER_CONTRACT_VERSION
    )
    server: McpManagedServer
    idempotent_replay: bool
    process_started: Literal[False] = False
    endpoint_connected: Literal[False] = False
    package_changed: Literal[False] = False
    tool_authority_granted: Literal[False] = False


class McpManagedProbeReceipt(StrictModel):
    contract_version: Literal["mcp-managed-server.v2"] = (
        MCP_MANAGED_SERVER_CONTRACT_VERSION
    )
    server: McpManagedServer
    probe: McpManagedHostProbe
    idempotent_replay: bool
    endpoint_connection_attempted: Literal[True] = True
    connection_retained: Literal[False] = False
    package_changed: Literal[False] = False
    tool_results_requested: Literal[False] = False
    tool_authority_granted: Literal[False] = False


class McpManagedLifecycleReceipt(StrictModel):
    contract_version: Literal["mcp-managed-lifecycle-receipt.v2"] = (
        "mcp-managed-lifecycle-receipt.v2"
    )
    action: Literal["install", "uninstall"]
    installation_kind: Literal["remote_activation", "local_package"]
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    package_changed: bool = False
    process_started: bool = False
    process_tree_cleanup: Literal["verified", "not_applicable"] = "not_applicable"
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_effects(self) -> "McpManagedLifecycleReceipt":
        if self.action == "install" and (
            self.server.installation_state != "installed"
            or self.server.installation_kind != self.installation_kind
        ):
            raise ValueError("managed lifecycle receipt install state is incoherent")
        if self.action == "uninstall" and self.server.installation_state != "not_installed":
            raise ValueError("managed lifecycle receipt uninstall state is incoherent")
        local_change = self.installation_kind == "local_package"
        local_install = local_change and self.action == "install"
        if self.package_changed != local_change or self.process_started != local_install:
            raise ValueError("managed lifecycle receipt effects are incoherent")
        expected_cleanup = "verified" if local_install else "not_applicable"
        if self.process_tree_cleanup != expected_cleanup:
            raise ValueError("managed lifecycle receipt cleanup is incoherent")
        return self


class McpManagedLocalConfigurationInspectionReceipt(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-configuration-inspection-receipt.v1"
    ] = "mcp-managed-local-configuration-inspection-receipt.v1"
    action: Literal["inspect_configuration"] = "inspect_configuration"
    server: McpManagedServer
    inspection: McpManagedLocalConfigurationInspection
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    archive_retained: Literal[False] = False
    process_started: Literal[False] = False
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False
    configuration_values_persisted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_inspection(self) -> "McpManagedLocalConfigurationInspectionReceipt":
        if (
            self.server.local_configuration_inspection != self.inspection
            or self.server.option_kind != "local_package"
            or self.server.installation_state != "not_installed"
        ):
            raise ValueError("managed configuration inspection receipt is incoherent")
        return self


class McpManagedLocalCleanupReceipt(StrictModel):
    contract_version: Literal["mcp-managed-local-cleanup-receipt.v1"] = (
        "mcp-managed-local-cleanup-receipt.v1"
    )
    action: Literal["complete_interrupted_uninstall"] = (
        "complete_interrupted_uninstall"
    )
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    package_presence: Literal["absent"] = "absent"
    filesystem_changed: bool = Field(strict=True)
    process_started: Literal[False] = False
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_result(self) -> "McpManagedLocalCleanupReceipt":
        if (
            self.server.option_kind != "local_package"
            or self.server.installation_state != "not_installed"
            or self.server.lifecycle_state != "planned"
            or self.server.operation_state != "idle"
            or self.server.local_package_evidence is not None
        ):
            raise ValueError("managed local cleanup receipt is incoherent")
        if self.idempotent_replay and self.filesystem_changed:
            raise ValueError("managed local cleanup replay cannot change files")
        return self


class McpManagedLocalUpdateReceipt(StrictModel):
    contract_version: Literal["mcp-managed-local-update-receipt.v1"] = (
        "mcp-managed-local-update-receipt.v1"
    )
    action: Literal["update"] = "update"
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    package_changed: Literal[True] = True
    process_started: Literal[True] = True
    process_tree_cleanup: Literal["verified"] = "verified"
    rollback_generation_retained: Literal[True] = True
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_update(self) -> "McpManagedLocalUpdateReceipt":
        if (
            self.server.option_kind != "local_package"
            or self.server.installation_state != "installed"
            or self.server.operation_state != "idle"
            or self.server.rollback_generation is None
            or self.server.local_package_evidence is None
        ):
            raise ValueError("managed local update receipt is incoherent")
        return self


class McpManagedLocalRollbackReceipt(StrictModel):
    contract_version: Literal["mcp-managed-local-rollback-receipt.v1"] = (
        "mcp-managed-local-rollback-receipt.v1"
    )
    action: Literal["rollback"] = "rollback"
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    package_changed: Literal[True] = True
    process_started: Literal[False] = False
    process_tree_cleanup: Literal["not_applicable"] = "not_applicable"
    rollback_generation_retained: Literal[True] = True
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_rollback(self) -> "McpManagedLocalRollbackReceipt":
        if (
            self.server.option_kind != "local_package"
            or self.server.installation_state != "installed"
            or self.server.operation_state != "idle"
            or self.server.rollback_generation is None
            or self.server.local_package_evidence is None
        ):
            raise ValueError("managed local rollback receipt is incoherent")
        return self


class McpManagedLocalRollbackCleanupReceipt(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-rollback-cleanup-receipt.v1"
    ] = "mcp-managed-local-rollback-cleanup-receipt.v1"
    action: Literal["cleanup_rollback_generation"] = (
        "cleanup_rollback_generation"
    )
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    filesystem_changed: bool = Field(strict=True)
    rollback_generation_retained: Literal[False] = False
    process_started: Literal[False] = False
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_cleanup(self) -> "McpManagedLocalRollbackCleanupReceipt":
        if (
            self.server.option_kind != "local_package"
            or self.server.installation_state != "installed"
            or self.server.operation_state != "idle"
            or self.server.rollback_generation is not None
            or self.server.local_package_evidence is None
        ):
            raise ValueError("managed rollback cleanup receipt is incoherent")
        if self.idempotent_replay and self.filesystem_changed:
            raise ValueError("managed rollback cleanup replay changed files")
        return self


class McpManagedLocalOperationRecoveryReceipt(StrictModel):
    contract_version: Literal[
        "mcp-managed-local-operation-recovery-receipt.v1"
    ] = "mcp-managed-local-operation-recovery-receipt.v1"
    action: Literal["recover_interrupted_local_operation"] = (
        "recover_interrupted_local_operation"
    )
    recovered_action: Literal["update", "rollback", "cleanup"]
    server: McpManagedServer
    preview_digest: str = Field(pattern=_DIGEST_PATTERN)
    idempotent_replay: bool
    filesystem_state_verified: Literal[True] = True
    process_started: Literal[False] = False
    endpoint_connected: Literal[False] = False
    connection_retained: Literal[False] = False
    persistent_host_started: Literal[False] = False
    tool_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_recovery(self) -> "McpManagedLocalOperationRecoveryReceipt":
        if (
            self.server.option_kind != "local_package"
            or self.server.installation_state != "installed"
            or self.server.operation_state != "idle"
            or self.server.local_package_evidence is None
        ):
            raise ValueError("managed local operation recovery is incoherent")
        if self.recovered_action == "cleanup":
            if self.server.rollback_generation is not None:
                raise ValueError("managed cleanup recovery retained a generation")
        elif self.recovered_action == "rollback":
            if self.server.rollback_generation is None:
                raise ValueError("managed rollback recovery lost its generation")
        elif self.server.rollback_generation is not None:
            raise ValueError("managed update recovery retained a generation")
        return self


class McpSecretVault(Protocol):
    @property
    def provider(self) -> Literal["windows_credential_manager", "unavailable"]: ...

    def available(self) -> bool: ...

    def contains(self, reference_id: str) -> bool: ...

    def read(self, reference_id: str) -> SecretStr: ...

    def write(self, reference_id: str, value: SecretStr) -> None: ...

    def delete(self, reference_id: str) -> None: ...


class SecretReservation(StrictModel):
    reference_id: str = Field(pattern=_ID_PATTERN)
    state: McpManagedSecretReferenceState
    idempotent_replay: bool
    server: McpManagedServer


class SecretRemoval(StrictModel):
    reference_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    state: McpManagedSecretReferenceState | None
    idempotent_replay: bool
    server: McpManagedServer


class McpManagedServerRepository(Protocol):
    def get_create_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, str] | None: ...

    def create_server(
        self,
        *,
        management_id: str,
        command: CreateMcpManagedServer,
        request_fingerprint: str,
        review: McpRegistryServerReview,
        option: McpRegistryInstallOption,
        required_permissions: tuple[McpManagedPermission, ...],
        created_at: datetime,
        limit: int,
    ) -> tuple[McpManagedServer, bool]: ...

    def list_servers(self, *, limit: int) -> Sequence[McpManagedServer]: ...

    def get_server(self, management_id: str) -> McpManagedServer | None: ...

    def get_tool_snapshot(
        self,
        management_id: str,
    ) -> McpManagedToolSnapshot | None: ...

    def get_secret_reference(
        self,
        management_id: str,
        requirement_id: str,
    ) -> str | None: ...

    def get_probe_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, McpManagedHostProbe, str] | None: ...

    def record_probe(
        self,
        management_id: str,
        *,
        command: ProbeMcpManagedServer,
        request_fingerprint: str,
        result: McpHostProbeResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, McpManagedHostProbe, bool]: ...

    def get_lifecycle_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, Literal["install", "uninstall"], str, str] | None: ...

    def get_local_configuration_inspection_request(
        self,
        request_id: str,
    ) -> tuple[
        McpManagedServer,
        McpManagedLocalConfigurationInspection,
        str,
        str,
    ] | None: ...

    def record_local_configuration_inspection(
        self,
        management_id: str,
        *,
        command: InspectMcpManagedLocalConfiguration,
        request_fingerprint: str,
        result: McpLocalPackageConfigurationInspectionResult,
        inspected_at: datetime,
    ) -> tuple[
        McpManagedServer,
        McpManagedLocalConfigurationInspection,
        bool,
    ]: ...

    def apply_remote_activation(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        action: Literal["install", "uninstall"],
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def begin_local_install(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def finish_local_install(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        result: McpLocalPackageInstallResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_local_install(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        error_code: str,
        cleanup_required: bool,
        process_tree_cleanup: Literal[
            "verified", "not_applicable", "unconfirmed"
        ],
        updated_at: datetime,
    ) -> None: ...

    def begin_local_uninstall(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def mark_local_uninstall_prepared(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def finish_local_uninstall(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_local_uninstall(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        error_code: str,
        cleanup_required: bool,
        updated_at: datetime,
    ) -> None: ...

    def get_local_operation(
        self,
        management_id: str,
    ) -> McpManagedLocalOperationRecovery | None: ...

    def finish_local_uninstall_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalCleanup,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def get_local_update_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, str, str] | None: ...

    def begin_local_update(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalUpdate,
        request_fingerprint: str,
        target: McpManagedLocalUpdateTarget,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def mark_local_update_staged(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        result: McpLocalPackageStagedUpdateResult,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def finish_local_update(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalUpdate,
        request_fingerprint: str,
        target: McpManagedLocalUpdateTarget,
        result: McpLocalPackageStagedUpdateResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_local_update(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        error_code: str,
        cleanup_required: bool,
        process_tree_cleanup: Literal[
            "verified", "not_applicable", "unconfirmed"
        ],
        updated_at: datetime,
    ) -> None: ...

    def get_local_swap_request(
        self,
        request_id: str,
        *,
        action: Literal["rollback", "cleanup"],
    ) -> tuple[McpManagedServer, str, str] | None: ...

    def begin_local_rollback(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollback,
        request_fingerprint: str,
        expected_current_tree_digest: str,
        expected_rollback_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def finish_local_rollback(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollback,
        request_fingerprint: str,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def begin_local_rollback_cleanup(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollbackCleanup,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer: ...

    def finish_local_rollback_cleanup(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollbackCleanup,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_local_swap(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        action: Literal["rollback", "cleanup"],
        error_code: str,
        cleanup_required: bool,
        updated_at: datetime,
    ) -> None: ...

    def get_local_recovery_request(
        self,
        request_id: str,
    ) -> tuple[
        McpManagedServer,
        Literal["update", "rollback", "cleanup"],
        str,
        str,
    ] | None: ...

    def begin_local_operation_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalOperationRecovery,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> McpManagedLocalOperationRecovery: ...

    def finish_local_operation_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalOperationRecovery,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def set_project_binding(
        self,
        management_id: str,
        project_id: str,
        *,
        command: SetMcpManagedProjectBinding,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def reserve_secret(
        self,
        management_id: str,
        requirement_id: str,
        *,
        command: McpManagedVaultStoreCommand,
        request_fingerprint: str,
        reference_id: str,
        vault_provider: Literal["windows_credential_manager"],
        updated_at: datetime,
    ) -> SecretReservation: ...

    def finish_secret_store(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        reference_id: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_secret_store(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        reference_id: str,
        updated_at: datetime,
    ) -> None: ...

    def begin_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        command: McpManagedVaultRemoveCommand,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> SecretRemoval: ...

    def finish_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        reference_id: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]: ...

    def fail_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        reference_id: str,
        updated_at: datetime,
    ) -> None: ...


def _required_permissions(
    option: McpRegistryInstallOption,
) -> tuple[McpManagedPermission, ...]:
    permissions: list[McpManagedPermission] = []
    risks = set(option.risks)
    if option.kind == "local_package":
        permissions.append("process_spawn")
    if "filesystem_input_declared" in risks:
        permissions.extend(("filesystem_read", "filesystem_write"))
    if option.kind == "remote_server" or "remote_network_egress" in risks:
        permissions.append("network_egress")
    if "credential_input_declared" in risks:
        permissions.append("credential_use")
    return _sorted_permissions(permissions)


class McpManagedServerService:
    """Persist exact plans, permissions, probes, and remote activation state."""

    def __init__(
        self,
        repository: McpManagedServerRepository,
        catalog: McpRegistryCatalogService,
        vault: McpSecretVault,
        host: McpGuardedHost | None = None,
        installer: McpLocalPackageInstaller | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._vault = vault
        self._host = host
        self._installer = installer
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: secrets.token_hex(16))

    def _now(self) -> datetime:
        return _utc(self._clock())

    @staticmethod
    def _identity(value: str, code: str) -> str:
        if re.fullmatch(_ID_PATTERN, value) is None:
            raise McpManagedServerError(code)
        return value

    def _vault_status(self) -> McpManagedSecretVaultStatus:
        available = self._vault.available()
        provider = self._vault.provider if available else "unavailable"
        return McpManagedSecretVaultStatus(
            provider=provider,
            availability="available" if available else "unavailable",
        )

    def create(self, command: CreateMcpManagedServer) -> McpManagedServerReceipt:
        request_fingerprint = _canonical_digest(command.model_dump(mode="json"))
        replay = self._repository.get_create_request(command.request_id)
        if replay is not None:
            record, stored_fingerprint = replay
            if stored_fingerprint != request_fingerprint:
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedServerReceipt(server=record, idempotent_replay=True)
        try:
            review = self._catalog.review_server(
                catalog_id=command.catalog_id,
                name=command.name,
                version=command.version,
            )
        except McpRegistryCatalogError as error:
            raise McpManagedServerError(error.code) from None
        if review.plan_revision != command.plan_revision:
            raise McpManagedServerError("mcp_managed_plan_revision_conflict")
        if review.server.status != "active":
            raise McpManagedServerError("mcp_managed_server_not_installable")
        option = next(
            (item for item in review.options if item.option_id == command.option_id),
            None,
        )
        if option is None:
            raise McpManagedServerError("mcp_managed_option_not_found")
        if option.compatibility.status == "unsupported":
            raise McpManagedServerError("mcp_managed_option_unsupported")
        record, replay = self._repository.create_server(
            management_id=self._identity(
                self._id(), "mcp_managed_generated_identity_invalid"
            ),
            command=command,
            request_fingerprint=request_fingerprint,
            review=review,
            option=option,
            required_permissions=_required_permissions(option),
            created_at=self._now(),
            limit=MAX_MCP_MANAGED_SERVERS,
        )
        return McpManagedServerReceipt(server=record, idempotent_replay=replay)

    def list(self) -> McpManagedServerList:
        records = tuple(
            self._repository.list_servers(limit=MAX_MCP_MANAGED_LIST)
        )
        return McpManagedServerList(
            servers=records,
            total=len(records),
            secret_vault=self._vault_status(),
        )

    def get(self, management_id: str) -> McpManagedServer:
        self._identity(management_id, "mcp_managed_server_not_found")
        record = self._repository.get_server(management_id)
        if record is None:
            raise McpManagedServerError("mcp_managed_server_not_found")
        return record

    def get_tool_snapshot(self, management_id: str) -> McpManagedToolSnapshot:
        self._identity(management_id, "mcp_managed_server_not_found")
        if self._repository.get_server(management_id) is None:
            raise McpManagedServerError("mcp_managed_server_not_found")
        snapshot = self._repository.get_tool_snapshot(management_id)
        if snapshot is None:
            raise McpManagedServerError("mcp_managed_tool_review_required")
        return snapshot

    @staticmethod
    def _configuration_inspection_effects() -> tuple[
        Literal[
            "download_exact_package",
            "verify_artifact_sha256",
            "inspect_manifest_configuration",
            "discard_inspection_archive",
            "persist_content_free_configuration_schema",
            "revoke_project_bindings_if_permissions_expand",
            "no_configuration_values_persisted",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]:
        return (
            "download_exact_package",
            "verify_artifact_sha256",
            "inspect_manifest_configuration",
            "discard_inspection_archive",
            "persist_content_free_configuration_schema",
            "revoke_project_bindings_if_permissions_expand",
            "no_configuration_values_persisted",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )

    def local_configuration_inspection_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalConfigurationInspectionPreview:
        record = self.get(management_id)
        if record.option_kind != "local_package":
            reason = "local_package_required"
        elif record.installation_state == "cleanup_required":
            reason = "cleanup_required"
        elif record.operation_state != "idle":
            reason = "operation_in_progress"
        elif record.installation_state == "installed":
            reason = "already_installed"
        elif record.local_configuration_inspection is not None:
            reason = "already_inspected"
        elif record.registry_type != "mcpb":
            reason = "package_registry_not_supported"
        elif "package_integrity_not_declared" in record.risks:
            reason = "package_integrity_required"
        elif record.transport != "stdio":
            reason = "local_transport_unsupported"
        elif self._installer is None or not self._installer.supports("mcpb"):
            reason = "local_installer_unavailable"
        else:
            reason = "ready_for_native_confirmation"
        material = {
            "contract_version": (
                "mcp-managed-local-configuration-inspection-preview.v1"
            ),
            "action": "inspect_configuration",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "plan_revision": record.plan_revision,
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": self._configuration_inspection_effects(),
            "native_confirmation_required": True,
        }
        return McpManagedLocalConfigurationInspectionPreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def inspect_local_configuration(
        self,
        management_id: str,
        command: InspectMcpManagedLocalConfiguration,
    ) -> McpManagedLocalConfigurationInspectionReceipt:
        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "inspect_configuration",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_local_configuration_inspection_request(
            command.request_id
        )
        if replay is not None:
            record, inspection, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalConfigurationInspectionReceipt(
                server=record,
                inspection=inspection,
                preview_digest=stored_preview,
                idempotent_replay=True,
            )

        preview = self.local_configuration_inspection_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError(
                "mcp_managed_configuration_inspection_preview_conflict"
            )
        if preview.availability != "available":
            raise McpManagedServerError(
                f"mcp_managed_configuration_inspection_{preview.reason}"
            )
        record = self.get(management_id)
        installer = self._installer
        if installer is None:
            raise McpManagedServerError("mcp_managed_local_installer_unavailable")
        try:
            package = self._catalog.resolve_local_package(
                catalog_id=record.catalog_id,
                name=record.server_name,
                version=record.server_version,
                option_id=record.option_id,
                plan_revision=record.plan_revision,
                inspection_only=True,
            )
        except McpRegistryCatalogError as error:
            raise McpManagedServerError(error.code) from None
        try:
            result = installer.inspect_configuration(
                package,
                management_id=management_id,
            )
        except McpLocalPackageInstallerError as error:
            raise McpManagedServerError(error.code) from None
        updated, inspection, replayed = (
            self._repository.record_local_configuration_inspection(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                result=result,
                inspected_at=self._now(),
            )
        )
        return McpManagedLocalConfigurationInspectionReceipt(
            server=updated,
            inspection=inspection,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
        )

    @staticmethod
    def _lifecycle_effects(
        action: Literal["install", "uninstall"],
        installation_kind: Literal["remote_activation", "local_package"],
    ) -> tuple[
        Literal[
            "persist_remote_activation",
            "remove_remote_activation",
            "download_exact_package",
            "verify_artifact_sha256",
            "stage_isolated_package",
            "execute_bounded_compatibility_probe",
            "stop_and_verify_process_tree",
            "publish_verified_package",
            "verify_installed_tree_digest",
            "quarantine_verified_package",
            "remove_quarantined_package",
            "no_package_change",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        ],
        ...,
    ]:
        if installation_kind == "remote_activation":
            first = (
                "persist_remote_activation"
                if action == "install"
                else "remove_remote_activation"
            )
        else:
            if action == "install":
                return (
                    "download_exact_package",
                    "verify_artifact_sha256",
                    "stage_isolated_package",
                    "execute_bounded_compatibility_probe",
                    "stop_and_verify_process_tree",
                    "publish_verified_package",
                    "no_connection_retained",
                    "no_tool_authority",
                )
            return (
                "verify_installed_tree_digest",
                "quarantine_verified_package",
                "remove_quarantined_package",
                "no_process_start",
                "no_connection_retained",
                "no_tool_authority",
            )
        return (
            first,
            "no_package_change",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )

    def lifecycle_preview(
        self,
        management_id: str,
        action: Literal["install", "uninstall"],
    ) -> McpManagedLifecyclePreview:
        record = self.get(management_id)
        if action == "install":
            reason_by_state = {
                "available_native_confirmation_required": "ready_for_native_confirmation",
                "unavailable_compatibility_check_required": "compatibility_check_required",
                "unavailable_configuration_required": "configuration_required",
                "unavailable_configuration_inspection_required": (
                    "configuration_inspection_required"
                ),
                "unavailable_package_registry_not_supported": "package_registry_not_supported",
                "unavailable_package_integrity_required": "package_integrity_required",
                "unavailable_local_transport_unsupported": "local_transport_unsupported",
                "unavailable_cleanup_required": "cleanup_required",
                "unavailable_operation_in_progress": "operation_in_progress",
                "not_applicable_already_installed": "already_installed",
            }
            reason = reason_by_state[record.install_action]
            if (
                reason == "ready_for_native_confirmation"
                and record.option_kind == "local_package"
                and (
                    self._installer is None
                    or record.registry_type is None
                    or not self._installer.supports(record.registry_type)
                )
            ):
                reason = "local_installer_unavailable"
        else:
            reason_by_state = {
                "available_native_confirmation_required": "ready_for_native_confirmation",
                "not_applicable_not_installed": "not_installed",
                "unavailable_cleanup_required": "cleanup_required",
                "unavailable_operation_in_progress": "operation_in_progress",
            }
            reason = reason_by_state[record.uninstall_action]
            if (
                reason == "ready_for_native_confirmation"
                and record.installation_kind == "local_package"
                and (
                    self._installer is None
                    or record.registry_type is None
                    or not self._installer.supports(record.registry_type)
                )
            ):
                reason = "local_uninstaller_unavailable"
        material = {
            "contract_version": "mcp-managed-lifecycle-preview.v1",
            "action": action,
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "plan_revision": record.plan_revision,
            "installation_kind": (
                "remote_activation"
                if record.option_kind == "remote_server"
                else "local_package"
            ),
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": self._lifecycle_effects(
                action,
                "remote_activation"
                if record.option_kind == "remote_server"
                else "local_package",
            ),
            "native_confirmation_required": True,
        }
        return McpManagedLifecyclePreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    @staticmethod
    def _lifecycle_receipt(
        *,
        action: Literal["install", "uninstall"],
        server: McpManagedServer,
        preview_digest: str,
        idempotent_replay: bool,
    ) -> McpManagedLifecycleReceipt:
        local_install = (
            action == "install"
            and server.installation_kind == "local_package"
            and server.installation_state == "installed"
        )
        installation_kind: Literal["remote_activation", "local_package"] = (
            "local_package"
            if server.option_kind == "local_package"
            else "remote_activation"
        )
        return McpManagedLifecycleReceipt(
            action=action,
            installation_kind=installation_kind,
            server=server,
            preview_digest=preview_digest,
            idempotent_replay=idempotent_replay,
            package_changed=installation_kind == "local_package",
            process_started=local_install,
            process_tree_cleanup="verified" if local_install else "not_applicable",
        )

    def apply_lifecycle(
        self,
        management_id: str,
        action: Literal["install", "uninstall"],
        command: ApplyMcpManagedLifecycle,
    ) -> McpManagedLifecycleReceipt:
        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": action,
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_lifecycle_request(command.request_id)
        if replay is not None:
            record, stored_action, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_action != action
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return self._lifecycle_receipt(
                action=action,
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
            )

        preview = self.lifecycle_preview(management_id, action)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError("mcp_managed_lifecycle_preview_conflict")
        if preview.availability != "available":
            raise McpManagedServerError(
                f"mcp_managed_{action}_{preview.reason}"
            )
        record = self.get(management_id)
        if record.option_kind == "remote_server":
            if action == "install":
                # Re-fetch the plan, resolve reviewed OS-vault inputs, and bind
                # the exact endpoint without opening a connection. Store-06
                # remains the only persistent-host boundary.
                self._resolve_remote_connection(
                    record,
                    configuration_required_code=(
                        "mcp_managed_install_configuration_required"
                    ),
                    plan_changed_code="mcp_managed_install_plan_changed",
                    configuration_invalid_code=(
                        "mcp_managed_install_configuration_invalid"
                    ),
                )
            updated, replayed = self._repository.apply_remote_activation(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                action=action,
                updated_at=self._now(),
            )
            return self._lifecycle_receipt(
                action=action,
                server=updated,
                preview_digest=preview.preview_digest,
                idempotent_replay=replayed,
            )

        installer = self._installer
        if (
            installer is None
            or record.registry_type is None
            or not installer.supports(record.registry_type)
        ):
            raise McpManagedServerError("mcp_managed_local_installer_unavailable")
        if action == "uninstall":
            evidence = record.local_package_evidence
            if evidence is None:
                raise McpManagedServerError(
                    "mcp_managed_lifecycle_transition_conflict"
                )
            self._repository.begin_local_uninstall(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                expected_tree_digest=evidence.tree_digest,
                updated_at=self._now(),
            )
            try:
                prepared = installer.prepare_uninstall(
                    management_id=management_id,
                    operation_id=command.request_id,
                    expected_tree_digest=evidence.tree_digest,
                )
            except McpLocalPackageInstallerError as error:
                try:
                    self._repository.fail_local_uninstall(
                        management_id,
                        request_id=command.request_id,
                        request_fingerprint=fingerprint,
                        error_code=error.code,
                        cleanup_required=error.cleanup_required,
                        updated_at=self._now(),
                    )
                except McpManagedServerError:
                    raise
                raise McpManagedServerError(error.code) from None
            if prepared.tree_digest != evidence.tree_digest:
                self._repository.fail_local_uninstall(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code="mcp_package_uninstall_evidence_mismatch",
                    cleanup_required=True,
                    updated_at=self._now(),
                )
                raise McpManagedServerError(
                    "mcp_package_uninstall_evidence_mismatch"
                )
            try:
                self._repository.mark_local_uninstall_prepared(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    updated_at=self._now(),
                )
            except McpManagedServerError as error:
                restored = installer.rollback_uninstall(
                    management_id=management_id,
                    operation_id=command.request_id,
                    expected_tree_digest=evidence.tree_digest,
                )
                try:
                    self._repository.fail_local_uninstall(
                        management_id,
                        request_id=command.request_id,
                        request_fingerprint=fingerprint,
                        error_code="mcp_package_uninstall_prepare_commit_failed",
                        cleanup_required=not restored,
                        updated_at=self._now(),
                    )
                except McpManagedServerError:
                    pass
                raise error
            removed = installer.commit_uninstall(
                management_id=management_id,
                operation_id=command.request_id,
                expected_tree_digest=evidence.tree_digest,
            )
            if not removed:
                self._repository.fail_local_uninstall(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code="mcp_package_uninstall_cleanup_unconfirmed",
                    cleanup_required=True,
                    updated_at=self._now(),
                )
                raise McpManagedServerError(
                    "mcp_package_uninstall_cleanup_unconfirmed"
                )
            try:
                updated, replayed = self._repository.finish_local_uninstall(
                    management_id,
                    command=command,
                    request_fingerprint=fingerprint,
                    expected_tree_digest=evidence.tree_digest,
                    updated_at=self._now(),
                )
            except McpManagedServerError as error:
                try:
                    self._repository.fail_local_uninstall(
                        management_id,
                        request_id=command.request_id,
                        request_fingerprint=fingerprint,
                        error_code="mcp_package_uninstall_commit_failed",
                        cleanup_required=True,
                        updated_at=self._now(),
                    )
                except McpManagedServerError:
                    pass
                raise error
            return self._lifecycle_receipt(
                action=action,
                server=updated,
                preview_digest=preview.preview_digest,
                idempotent_replay=replayed,
            )

        package = self._resolve_local_package(
            record,
            configuration_required_code=(
                "mcp_managed_install_configuration_required"
            ),
            configuration_invalid_code=(
                "mcp_managed_install_configuration_invalid"
            ),
        )
        user_configuration = self._resolve_mcpb_user_configuration(
            record,
            configuration_required_code=(
                "mcp_managed_install_configuration_required"
            ),
        )

        self._repository.begin_local_install(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            updated_at=self._now(),
        )
        try:
            result = installer.install_and_probe(
                package,
                management_id=management_id,
                user_configuration=user_configuration,
            )
        except McpLocalPackageInstallerError as error:
            try:
                self._repository.fail_local_install(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code=error.code,
                    cleanup_required=error.cleanup_required,
                    process_tree_cleanup=error.process_tree_cleanup,
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                raise
            raise McpManagedServerError(error.code) from None

        checked_at = self._now()
        try:
            updated, replayed = self._repository.finish_local_install(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                result=result,
                checked_at=checked_at,
            )
        except McpManagedServerError as error:
            rolled_back = installer.rollback_publication(
                management_id=management_id,
                expected_tree_digest=result.tree_digest,
            )
            try:
                self._repository.fail_local_install(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code="mcp_package_commit_failed",
                    cleanup_required=not rolled_back,
                    process_tree_cleanup="verified",
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise error
        return self._lifecycle_receipt(
            action=action,
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
        )

    def local_cleanup_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalCleanupPreview:
        """Describe recovery of one interrupted, journaled local uninstall."""

        record = self.get(management_id)
        operation = self._repository.get_local_operation(management_id)
        installer = self._installer
        if record.installation_state != "cleanup_required":
            reason = "cleanup_not_required"
        elif (
            record.option_kind != "local_package"
            or operation is None
            or operation.action != "uninstall"
            or operation.status != "cleanup_required"
            or record.local_package_evidence is None
            or record.local_package_evidence.tree_digest
            != operation.expected_tree_digest
        ):
            reason = "unsupported_cleanup_state"
        elif (
            installer is None
            or record.registry_type is None
            or not installer.supports(record.registry_type)
        ):
            reason = "local_uninstaller_unavailable"
        else:
            reason = "ready_for_native_confirmation"
        effects = (
            "verify_operation_journal",
            "verify_installed_or_quarantined_tree_digest",
            "finish_quarantined_removal",
            "clear_cleanup_state",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        material = {
            "contract_version": "mcp-managed-local-cleanup-preview.v1",
            "action": "complete_interrupted_uninstall",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "plan_revision": record.plan_revision,
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": effects,
            "native_confirmation_required": True,
        }
        return McpManagedLocalCleanupPreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def local_update_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalUpdatePreview:
        """Resolve the official latest alias and preview one exact safe target."""

        record = self.get(management_id)
        target_version: str | None = None
        target_catalog_id: str | None = None
        target_option_id: str | None = None
        target_plan_revision: str | None = None
        candidate: McpRegistryInstallOption | None = None
        if record.option_kind != "local_package":
            reason = "local_package_required"
        elif record.installation_state == "cleanup_required":
            reason = "cleanup_required"
        elif record.operation_state != "idle":
            reason = "operation_in_progress"
        elif record.installation_state != "installed":
            reason = "install_required"
        elif record.rollback_generation is not None:
            reason = "rollback_cleanup_required"
        elif record.requirements:
            reason = "configuration_migration_required"
        else:
            try:
                latest = self._catalog.review_latest_server(
                    name=record.server_name
                )
            except McpRegistryCatalogError:
                reason = "registry_unavailable"
            else:
                target_version = latest.server.version
                if latest.server.status != "active":
                    reason = "target_not_installable"
                elif target_version == record.server_version:
                    reason = (
                        "already_latest"
                        if latest.plan_revision == record.plan_revision
                        else "current_version_metadata_changed"
                    )
                else:
                    eligible = tuple(
                        option
                        for option in latest.options
                        if option.kind == "local_package"
                        and option.registry_type == "mcpb"
                        and option.transport == "stdio"
                        and option.checksum_state == "declared"
                        and option.compatibility.status == "reviewable"
                        and not option.requirements
                    )
                    if not eligible:
                        reason = "target_not_installable"
                    elif len(eligible) != 1:
                        reason = "target_option_ambiguous"
                    else:
                        candidate = eligible[0]
                        try:
                            self._catalog.resolve_local_package(
                                catalog_id=latest.server.catalog_id,
                                name=latest.server.name,
                                version=latest.server.version,
                                option_id=candidate.option_id,
                                plan_revision=latest.plan_revision,
                            )
                        except McpRegistryCatalogError:
                            reason = "target_not_installable"
                        else:
                            if _required_permissions(candidate) != (
                                record.required_permissions
                            ):
                                reason = "permission_change_required"
                            elif (
                                self._installer is None
                                or not self._installer.supports("mcpb")
                            ):
                                reason = "local_installer_unavailable"
                            else:
                                target_catalog_id = latest.server.catalog_id
                                target_option_id = candidate.option_id
                                target_plan_revision = latest.plan_revision
                                reason = "ready_for_native_confirmation"
        effects = (
            "resolve_official_latest_exact_version",
            "download_exact_target_package",
            "verify_target_artifact_sha256",
            "stage_target_in_isolation",
            "execute_bounded_target_probe",
            "stop_and_verify_target_process_tree",
            "retain_verified_rollback_generation",
            "publish_verified_target_package",
            "no_connection_retained",
            "no_tool_authority",
        )
        material = {
            "contract_version": "mcp-managed-local-update-preview.v1",
            "action": "update",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "current_version": record.server_version,
            "current_plan_revision": record.plan_revision,
            "target_version": target_version,
            "target_catalog_id": target_catalog_id,
            "target_option_id": target_option_id,
            "target_plan_revision": target_plan_revision,
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": effects,
            "native_confirmation_required": True,
        }
        return McpManagedLocalUpdatePreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def apply_local_update(
        self,
        management_id: str,
        command: ApplyMcpManagedLocalUpdate,
    ) -> McpManagedLocalUpdateReceipt:
        """Stage, probe, publish, and durably commit one exact latest version."""

        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "update",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_local_update_request(command.request_id)
        if replay is not None:
            record, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalUpdateReceipt(
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
            )

        preview = self.local_update_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError("mcp_managed_update_preview_conflict")
        if preview.availability != "available":
            raise McpManagedServerError(f"mcp_managed_update_{preview.reason}")
        record = self.get(management_id)
        installer = self._installer
        evidence = record.local_package_evidence
        if (
            installer is None
            or evidence is None
            or record.registry_type != "mcpb"
            or not installer.supports("mcpb")
            or preview.target_catalog_id is None
            or preview.target_version is None
            or preview.target_option_id is None
            or preview.target_plan_revision is None
        ):
            raise McpManagedServerError(
                "mcp_managed_update_transition_conflict"
            )

        try:
            latest = self._catalog.review_latest_server(name=record.server_name)
        except McpRegistryCatalogError as error:
            raise McpManagedServerError(error.code) from None
        candidate = next(
            (
                option
                for option in latest.options
                if option.option_id == preview.target_option_id
            ),
            None,
        )
        if (
            latest.server.catalog_id != preview.target_catalog_id
            or latest.server.name != record.server_name
            or latest.server.version != preview.target_version
            or latest.server.status != "active"
            or latest.plan_revision != preview.target_plan_revision
            or candidate is None
            or candidate.kind != "local_package"
            or candidate.registry_type != "mcpb"
            or candidate.transport != "stdio"
            or candidate.checksum_state != "declared"
            or candidate.compatibility.status != "reviewable"
            or candidate.requirements
            or _required_permissions(candidate) != record.required_permissions
        ):
            raise McpManagedServerError("mcp_managed_update_target_changed")
        target = McpManagedLocalUpdateTarget(
            catalog_id=latest.server.catalog_id,
            server_name=latest.server.name,
            server_title=latest.server.title,
            server_version=latest.server.version,
            server_status_at_review=latest.server.status,
            option_id=candidate.option_id,
            plan_revision=latest.plan_revision,
            option_label=candidate.label,
            registry_type="mcpb",
            package_identifier=candidate.package_identifier,
            package_version=candidate.package_version,
            runtime_hint=candidate.runtime_hint,
            transport="stdio",
            required_permissions=record.required_permissions,
            risks=candidate.risks,
        )
        try:
            package = self._catalog.resolve_local_package(
                catalog_id=target.catalog_id,
                name=target.server_name,
                version=target.server_version,
                option_id=target.option_id,
                plan_revision=target.plan_revision,
            )
        except McpRegistryCatalogError as error:
            raise McpManagedServerError(error.code) from None

        self._repository.begin_local_update(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            target=target,
            expected_tree_digest=evidence.tree_digest,
            updated_at=self._now(),
        )
        try:
            result = installer.stage_update(
                package,
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=evidence.tree_digest,
            )
        except McpLocalPackageInstallerError as error:
            self._repository.fail_local_update(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                error_code=error.code,
                cleanup_required=error.cleanup_required,
                process_tree_cleanup=error.process_tree_cleanup,
                updated_at=self._now(),
            )
            raise McpManagedServerError(error.code) from None

        try:
            self._repository.mark_local_update_staged(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                result=result,
                updated_at=self._now(),
            )
        except McpManagedServerError as error:
            restored = installer.rollback_update_publication(
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=evidence.tree_digest,
                expected_target_tree_digest=result.tree_digest,
            )
            try:
                self._repository.fail_local_update(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code="mcp_package_update_stage_commit_failed",
                    cleanup_required=not restored,
                    process_tree_cleanup="verified",
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise error

        try:
            publication = installer.publish_update(
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=evidence.tree_digest,
                expected_target_tree_digest=result.tree_digest,
            )
        except McpLocalPackageInstallerError as error:
            try:
                self._repository.fail_local_update(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code=error.code,
                    cleanup_required=error.cleanup_required,
                    process_tree_cleanup="verified",
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise McpManagedServerError(error.code) from None
        if (
            publication.target_tree_digest != result.tree_digest
            or publication.rollback_tree_digest != evidence.tree_digest
        ):
            restored = installer.rollback_update_publication(
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=evidence.tree_digest,
                expected_target_tree_digest=result.tree_digest,
            )
            self._repository.fail_local_update(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                error_code="mcp_package_update_evidence_mismatch",
                cleanup_required=not restored,
                process_tree_cleanup="verified",
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_package_update_evidence_mismatch"
            )

        try:
            updated, replayed = self._repository.finish_local_update(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                target=target,
                result=result,
                checked_at=self._now(),
            )
        except McpManagedServerError as error:
            restored = installer.rollback_update_publication(
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=evidence.tree_digest,
                expected_target_tree_digest=result.tree_digest,
            )
            try:
                self._repository.fail_local_update(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    error_code="mcp_package_update_commit_failed",
                    cleanup_required=not restored,
                    process_tree_cleanup="verified",
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise error
        return McpManagedLocalUpdateReceipt(
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
        )

    def local_rollback_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalRollbackPreview:
        record = self.get(management_id)
        generation = record.rollback_generation
        if record.option_kind != "local_package":
            reason = "local_package_required"
        elif record.installation_state == "cleanup_required":
            reason = "cleanup_required"
        elif record.operation_state != "idle":
            reason = "operation_in_progress"
        elif record.installation_state != "installed":
            reason = "install_required"
        elif generation is None:
            reason = "rollback_generation_missing"
        elif (
            self._installer is None
            or record.registry_type is None
            or not self._installer.supports(record.registry_type)
        ):
            reason = "local_installer_unavailable"
        else:
            reason = "ready_for_native_confirmation"
        effects = (
            "verify_current_tree_digest",
            "verify_rollback_tree_digest",
            "atomically_swap_verified_generations",
            "retain_superseded_current_generation",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        material = {
            "contract_version": "mcp-managed-local-rollback-preview.v1",
            "action": "rollback",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "current_version": record.server_version,
            "current_plan_revision": record.plan_revision,
            "target_version": (
                None if generation is None else generation.server_version
            ),
            "target_plan_revision": (
                None if generation is None else generation.plan_revision
            ),
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": effects,
            "native_confirmation_required": True,
        }
        return McpManagedLocalRollbackPreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def local_rollback_cleanup_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalRollbackCleanupPreview:
        record = self.get(management_id)
        generation = record.rollback_generation
        if record.option_kind != "local_package":
            reason = "local_package_required"
        elif record.installation_state == "cleanup_required":
            reason = "cleanup_required"
        elif record.operation_state != "idle":
            reason = "operation_in_progress"
        elif record.installation_state != "installed":
            reason = "install_required"
        elif generation is None:
            reason = "rollback_generation_missing"
        elif (
            self._installer is None
            or record.registry_type is None
            or not self._installer.supports(record.registry_type)
        ):
            reason = "local_installer_unavailable"
        else:
            reason = "ready_for_native_confirmation"
        effects = (
            "verify_rollback_tree_digest",
            "quarantine_verified_rollback_generation",
            "remove_quarantined_rollback_generation",
            "keep_current_generation_installed",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        material = {
            "contract_version": (
                "mcp-managed-local-rollback-cleanup-preview.v1"
            ),
            "action": "cleanup_rollback_generation",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "rollback_version": (
                None if generation is None else generation.server_version
            ),
            "rollback_plan_revision": (
                None if generation is None else generation.plan_revision
            ),
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": effects,
            "native_confirmation_required": True,
        }
        return McpManagedLocalRollbackCleanupPreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def apply_local_rollback(
        self,
        management_id: str,
        command: ApplyMcpManagedLocalRollback,
    ) -> McpManagedLocalRollbackReceipt:
        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "rollback",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_local_swap_request(
            command.request_id,
            action="rollback",
        )
        if replay is not None:
            record, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalRollbackReceipt(
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
            )
        preview = self.local_rollback_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError("mcp_managed_rollback_preview_conflict")
        if preview.availability != "available":
            raise McpManagedServerError(f"mcp_managed_rollback_{preview.reason}")
        record = self.get(management_id)
        generation = record.rollback_generation
        current = record.local_package_evidence
        installer = self._installer
        if generation is None or current is None or installer is None:
            raise McpManagedServerError(
                "mcp_managed_rollback_transition_conflict"
            )
        rollback_digest = generation.local_package_evidence.tree_digest
        self._repository.begin_local_rollback(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            expected_current_tree_digest=current.tree_digest,
            expected_rollback_tree_digest=rollback_digest,
            updated_at=self._now(),
        )
        swapped = installer.swap_rollback_generation(
            management_id=management_id,
            operation_id=command.request_id,
            expected_current_tree_digest=current.tree_digest,
            expected_rollback_tree_digest=rollback_digest,
        )
        if not swapped:
            self._repository.fail_local_swap(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                action="rollback",
                error_code="mcp_package_rollback_swap_unconfirmed",
                cleanup_required=True,
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_package_rollback_swap_unconfirmed"
            )
        try:
            updated, replayed = self._repository.finish_local_rollback(
                management_id,
                command=command,
                request_fingerprint=fingerprint,
                checked_at=self._now(),
            )
        except McpManagedServerError as error:
            restored = installer.swap_rollback_generation(
                management_id=management_id,
                operation_id=command.request_id,
                expected_current_tree_digest=rollback_digest,
                expected_rollback_tree_digest=current.tree_digest,
            )
            try:
                self._repository.fail_local_swap(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    action="rollback",
                    error_code="mcp_package_rollback_commit_failed",
                    cleanup_required=not restored,
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise error
        return McpManagedLocalRollbackReceipt(
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
        )

    def cleanup_local_rollback_generation(
        self,
        management_id: str,
        command: ApplyMcpManagedLocalRollbackCleanup,
    ) -> McpManagedLocalRollbackCleanupReceipt:
        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "cleanup_rollback_generation",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_local_swap_request(
            command.request_id,
            action="cleanup",
        )
        if replay is not None:
            record, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalRollbackCleanupReceipt(
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
                filesystem_changed=False,
            )
        preview = self.local_rollback_cleanup_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError(
                "mcp_managed_rollback_cleanup_preview_conflict"
            )
        if preview.availability != "available":
            raise McpManagedServerError(
                f"mcp_managed_rollback_cleanup_{preview.reason}"
            )
        record = self.get(management_id)
        generation = record.rollback_generation
        installer = self._installer
        if generation is None or installer is None:
            raise McpManagedServerError(
                "mcp_managed_rollback_cleanup_transition_conflict"
            )
        expected_digest = generation.local_package_evidence.tree_digest
        self._repository.begin_local_rollback_cleanup(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            expected_tree_digest=expected_digest,
            updated_at=self._now(),
        )
        try:
            result = installer.cleanup_rollback_generation(
                management_id=management_id,
                operation_id=command.request_id,
                expected_tree_digest=expected_digest,
            )
        except McpLocalPackageInstallerError as error:
            self._repository.fail_local_swap(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                action="cleanup",
                error_code=error.code,
                cleanup_required=error.cleanup_required,
                updated_at=self._now(),
            )
            raise McpManagedServerError(error.code) from None
        if result.tree_digest != expected_digest:
            self._repository.fail_local_swap(
                management_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                action="cleanup",
                error_code="mcp_package_rollback_cleanup_evidence_mismatch",
                cleanup_required=True,
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_package_rollback_cleanup_evidence_mismatch"
            )
        try:
            updated, replayed = (
                self._repository.finish_local_rollback_cleanup(
                    management_id,
                    command=command,
                    request_fingerprint=fingerprint,
                    expected_tree_digest=expected_digest,
                    updated_at=self._now(),
                )
            )
        except McpManagedServerError as error:
            try:
                self._repository.fail_local_swap(
                    management_id,
                    request_id=command.request_id,
                    request_fingerprint=fingerprint,
                    action="cleanup",
                    error_code="mcp_package_rollback_cleanup_commit_failed",
                    cleanup_required=True,
                    updated_at=self._now(),
                )
            except McpManagedServerError:
                pass
            raise error
        return McpManagedLocalRollbackCleanupReceipt(
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
            filesystem_changed=False if replayed else result.filesystem_changed,
        )

    def local_operation_recovery_preview(
        self,
        management_id: str,
    ) -> McpManagedLocalOperationRecoveryPreview:
        record = self.get(management_id)
        operation = self._repository.get_local_operation(management_id)
        interrupted_action: Literal["update", "rollback", "cleanup"] | None = (
            None
        )
        if operation is not None and operation.action in {
            "update",
            "rollback",
            "cleanup",
        }:
            interrupted_action = operation.action
        if record.installation_state != "cleanup_required":
            reason = "cleanup_not_required"
        elif (
            operation is None
            or interrupted_action is None
            or record.option_kind != "local_package"
            or record.local_package_evidence is None
        ):
            reason = "unsupported_cleanup_state"
        elif record.process_tree_cleanup != "verified":
            reason = "process_cleanup_unconfirmed"
        elif operation.action == "update" and (
            operation.alternate_tree_digest is None
            or record.local_package_evidence.tree_digest
            != operation.expected_tree_digest
            or record.rollback_generation is not None
        ):
            reason = "unsupported_cleanup_state"
        elif operation.action == "rollback" and (
            operation.alternate_tree_digest is None
            or record.local_package_evidence.tree_digest
            != operation.expected_tree_digest
            or record.rollback_generation is None
            or record.rollback_generation.local_package_evidence.tree_digest
            != operation.alternate_tree_digest
        ):
            reason = "unsupported_cleanup_state"
        elif operation.action == "cleanup" and (
            record.rollback_generation is None
            or record.rollback_generation.local_package_evidence.tree_digest
            != operation.expected_tree_digest
        ):
            reason = "unsupported_cleanup_state"
        elif (
            self._installer is None
            or record.registry_type is None
            or not self._installer.supports(record.registry_type)
        ):
            reason = "local_installer_unavailable"
        else:
            reason = "ready_for_native_confirmation"
        middle_by_action: dict[
            Literal["update", "rollback", "cleanup"], tuple[str, ...]
        ] = {
            "update": (
                "restore_durable_current_generation",
                "discard_verified_staged_target",
            ),
            "rollback": (
                "restore_durable_current_generation",
                "retain_verified_rollback_generation",
            ),
            "cleanup": (
                "finish_verified_rollback_generation_removal",
            ),
        }
        effects = (
            "verify_operation_journal",
            *(
                ()
                if interrupted_action is None
                else middle_by_action[interrupted_action]
            ),
            "clear_cleanup_state",
            "no_process_start",
            "no_connection_retained",
            "no_tool_authority",
        )
        material = {
            "contract_version": (
                "mcp-managed-local-operation-recovery-preview.v1"
            ),
            "action": "recover_interrupted_local_operation",
            "management_id": record.management_id,
            "expected_revision": record.revision,
            "interrupted_action": interrupted_action,
            "availability": (
                "available"
                if reason == "ready_for_native_confirmation"
                else "unavailable"
            ),
            "reason": reason,
            "effects": effects,
            "native_confirmation_required": True,
        }
        return McpManagedLocalOperationRecoveryPreview(
            **material,
            preview_digest=_canonical_digest(material),
        )

    def recover_local_operation(
        self,
        management_id: str,
        command: ApplyMcpManagedLocalOperationRecovery,
    ) -> McpManagedLocalOperationRecoveryReceipt:
        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "recover_interrupted_local_operation",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_local_recovery_request(command.request_id)
        if replay is not None:
            record, recovered_action, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalOperationRecoveryReceipt(
                recovered_action=recovered_action,
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
            )
        preview = self.local_operation_recovery_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError("mcp_managed_recovery_preview_conflict")
        if preview.availability != "available":
            raise McpManagedServerError(f"mcp_managed_recovery_{preview.reason}")
        operation = self._repository.get_local_operation(management_id)
        installer = self._installer
        if (
            operation is None
            or operation.action == "uninstall"
            or installer is None
        ):
            raise McpManagedServerError(
                "mcp_managed_recovery_transition_conflict"
            )
        operation = self._repository.begin_local_operation_recovery(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            operation=operation,
            updated_at=self._now(),
        )
        if operation.action == "update":
            assert operation.alternate_tree_digest is not None
            verified = installer.rollback_update_publication(
                management_id=management_id,
                operation_id=operation.operation_id,
                expected_current_tree_digest=operation.expected_tree_digest,
                expected_target_tree_digest=operation.alternate_tree_digest,
            )
        elif operation.action == "rollback":
            assert operation.alternate_tree_digest is not None
            verified = installer.swap_rollback_generation(
                management_id=management_id,
                operation_id=operation.operation_id,
                expected_current_tree_digest=operation.alternate_tree_digest,
                expected_rollback_tree_digest=operation.expected_tree_digest,
            )
        else:
            try:
                result = installer.cleanup_rollback_generation(
                    management_id=management_id,
                    operation_id=operation.operation_id,
                    expected_tree_digest=operation.expected_tree_digest,
                )
            except McpLocalPackageInstallerError as error:
                raise McpManagedServerError(error.code) from None
            verified = result.tree_digest == operation.expected_tree_digest
        if not verified:
            raise McpManagedServerError(
                "mcp_package_operation_recovery_unconfirmed"
            )
        updated, replayed = self._repository.finish_local_operation_recovery(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            operation=operation,
            updated_at=self._now(),
        )
        return McpManagedLocalOperationRecoveryReceipt(
            recovered_action=operation.action,
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
        )

    def complete_local_uninstall_cleanup(
        self,
        management_id: str,
        command: ApplyMcpManagedLocalCleanup,
    ) -> McpManagedLocalCleanupReceipt:
        """Finish a crash-left uninstall without starting package code."""

        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "complete_interrupted_uninstall",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_lifecycle_request(command.request_id)
        if replay is not None:
            record, stored_action, stored_fingerprint, stored_preview = replay
            if (
                record.management_id != management_id
                or stored_action != "uninstall"
                or stored_fingerprint != fingerprint
                or stored_preview != command.preview_digest
                or record.installation_state != "not_installed"
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedLocalCleanupReceipt(
                server=record,
                preview_digest=stored_preview,
                idempotent_replay=True,
                filesystem_changed=False,
            )

        preview = self.local_cleanup_preview(management_id)
        if command.expected_revision != preview.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if command.preview_digest != preview.preview_digest:
            raise McpManagedServerError("mcp_managed_cleanup_preview_conflict")
        if preview.availability != "available":
            raise McpManagedServerError(f"mcp_managed_cleanup_{preview.reason}")
        operation = self._repository.get_local_operation(management_id)
        record = self.get(management_id)
        installer = self._installer
        if (
            operation is None
            or record.local_package_evidence is None
            or installer is None
            or record.registry_type is None
            or not installer.supports(record.registry_type)
        ):
            raise McpManagedServerError(
                "mcp_managed_cleanup_transition_conflict"
            )
        try:
            result: McpLocalPackageCleanupResult = (
                installer.complete_interrupted_uninstall(
                    management_id=management_id,
                    operation_id=operation.operation_id,
                    expected_tree_digest=operation.expected_tree_digest,
                )
            )
        except McpLocalPackageInstallerError as error:
            raise McpManagedServerError(error.code) from None
        if result.tree_digest != operation.expected_tree_digest:
            raise McpManagedServerError(
                "mcp_package_uninstall_evidence_mismatch"
            )
        updated, replayed = self._repository.finish_local_uninstall_recovery(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            operation=operation,
            updated_at=self._now(),
        )
        return McpManagedLocalCleanupReceipt(
            server=updated,
            preview_digest=preview.preview_digest,
            idempotent_replay=replayed,
            filesystem_changed=False if replayed else result.filesystem_changed,
        )

    def apply_remote_lifecycle(
        self,
        management_id: str,
        action: Literal["install", "uninstall"],
        command: ApplyMcpManagedLifecycle,
    ) -> McpManagedLifecycleReceipt:
        """Compatibility alias retained for Store-05a callers."""

        return self.apply_lifecycle(management_id, action, command)

    def _resolve_remote_connection(
        self,
        record: McpManagedServer,
        *,
        configuration_required_code: str,
        plan_changed_code: str,
        configuration_invalid_code: str,
    ) -> McpRemoteConnectionSpec:
        variable_values: dict[str, SecretStr] = {}
        for requirement in record.requirements:
            if requirement.location != "remote_variable":
                continue
            if requirement.secret:
                if requirement.configuration_state != "secret_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_secret_vault_read_failed"
            elif requirement.user_value_needed:
                if requirement.configuration_state != "value_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_configuration_vault_read_failed"
            else:
                continue
            reference_id = self._active_vault_reference(
                record,
                requirement,
                read_failure=read_failure,
            )
            try:
                variable_values[requirement.requirement_id] = self._vault.read(
                    reference_id
                )
            except Exception:
                raise McpManagedServerError(read_failure) from None
        try:
            resolved = self._catalog.resolve_remote_connection(
                catalog_id=record.catalog_id,
                name=record.server_name,
                version=record.server_version,
                option_id=record.option_id,
                plan_revision=record.plan_revision,
                variable_values=variable_values,
            )
        except McpRegistryCatalogError as error:
            if error.code == "mcp_registry_connection_configuration_required":
                raise McpManagedServerError(configuration_required_code) from None
            raise McpManagedServerError(error.code) from None

        requirement_by_id = {
            item.requirement_id: item for item in record.requirements
        }
        headers: list[McpRemoteHeader] = []
        for declaration in resolved.headers:
            requirement = requirement_by_id.get(declaration.requirement_id)
            if requirement is None or requirement.location != "transport_header":
                raise McpManagedServerError(plan_changed_code)
            value: SecretStr | None = None
            if declaration.secret:
                if requirement.configuration_state != "secret_stored":
                    raise McpManagedServerError(configuration_required_code)
                reference_id = self._active_vault_reference(
                    record,
                    requirement,
                    read_failure="mcp_managed_secret_vault_read_failed",
                )
                try:
                    value = self._vault.read(reference_id)
                except Exception:
                    raise McpManagedServerError(
                        "mcp_managed_secret_vault_read_failed"
                    ) from None
            elif requirement.user_value_needed:
                if requirement.configuration_state != "value_stored":
                    raise McpManagedServerError(configuration_required_code)
                reference_id = self._active_vault_reference(
                    record,
                    requirement,
                    read_failure="mcp_managed_configuration_vault_read_failed",
                )
                try:
                    value = self._vault.read(reference_id)
                except Exception:
                    raise McpManagedServerError(
                        "mcp_managed_configuration_vault_read_failed"
                    ) from None
            elif declaration.declared_value is not None:
                value = declaration.declared_value
            elif declaration.required:
                raise McpManagedServerError(configuration_required_code)
            if value is None:
                continue
            try:
                headers.append(McpRemoteHeader(name=declaration.name, value=value))
            except Exception:
                raise McpManagedServerError(configuration_invalid_code) from None

        try:
            return McpRemoteConnectionSpec(
                management_id=record.management_id,
                catalog_id=resolved.catalog_id,
                option_id=resolved.option_id,
                plan_revision=resolved.plan_revision,
                transport=resolved.transport,
                endpoint_host=resolved.endpoint_host,
                endpoint=resolved.endpoint,
                headers=tuple(headers),
            )
        except Exception:
            raise McpManagedServerError(configuration_invalid_code) from None

    def _resolve_local_package(
        self,
        record: McpManagedServer,
        *,
        configuration_required_code: str,
        configuration_invalid_code: str,
    ) -> McpRegistryResolvedLocalPackage:
        configuration_values: dict[str, SecretStr] = {}
        local_locations = {
            "runtime_argument",
            "package_argument",
            "environment_variable",
        }
        manifest_requirement_ids = (
            set()
            if record.local_configuration_inspection is None
            else set(record.local_configuration_inspection.requirement_ids)
        )
        for requirement in record.requirements:
            if (
                requirement.location not in local_locations
                or requirement.requirement_id in manifest_requirement_ids
            ):
                continue
            if requirement.secret:
                if requirement.configuration_state != "secret_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_secret_vault_read_failed"
            elif requirement.user_value_needed:
                if requirement.configuration_state != "value_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_configuration_vault_read_failed"
            else:
                continue
            reference_id = self._active_vault_reference(
                record,
                requirement,
                read_failure=read_failure,
            )
            try:
                configuration_values[requirement.requirement_id] = self._vault.read(
                    reference_id
                )
            except Exception:
                raise McpManagedServerError(read_failure) from None
        try:
            return self._catalog.resolve_local_package(
                catalog_id=record.catalog_id,
                name=record.server_name,
                version=record.server_version,
                option_id=record.option_id,
                plan_revision=record.plan_revision,
                configuration_values=configuration_values,
            )
        except McpRegistryCatalogError as error:
            if error.code == "mcp_registry_package_configuration_required":
                raise McpManagedServerError(configuration_required_code) from None
            if error.code in {
                "mcp_registry_package_configuration_invalid",
                "mcp_registry_package_argument_invalid",
                "mcp_registry_package_environment_invalid",
            }:
                raise McpManagedServerError(configuration_invalid_code) from None
            raise McpManagedServerError(error.code) from None

    def _resolve_mcpb_user_configuration(
        self,
        record: McpManagedServer,
        *,
        configuration_required_code: str,
    ) -> dict[str, SecretStr]:
        inspection = record.local_configuration_inspection
        if inspection is None:
            if record.installation_state == "installed":
                return {}
            raise McpManagedServerError(configuration_required_code)
        requirements = {
            item.requirement_id: item for item in record.requirements
        }
        if any(
            requirement_id not in requirements
            for requirement_id in inspection.requirement_ids
        ):
            raise McpManagedServerError("mcp_managed_install_plan_changed")
        values: dict[str, SecretStr] = {}
        for requirement_id in inspection.requirement_ids:
            requirement = requirements[requirement_id]
            if requirement.secret:
                if requirement.configuration_state != "secret_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_secret_vault_read_failed"
            elif requirement.user_value_needed:
                if requirement.configuration_state != "value_stored":
                    raise McpManagedServerError(configuration_required_code)
                read_failure = "mcp_managed_configuration_vault_read_failed"
            else:
                continue
            reference_id = self._active_vault_reference(
                record,
                requirement,
                read_failure=read_failure,
            )
            try:
                values[requirement.name] = self._vault.read(reference_id)
            except Exception:
                raise McpManagedServerError(read_failure) from None
        return values

    def resolve_transient_host_connection(
        self,
        management_id: str,
        *,
        expected_revision: int,
    ) -> McpRemoteConnectionSpec | McpStdioConnectionSpec:
        """Re-derive exact connection material without opening a connection."""

        self._identity(management_id, "mcp_managed_server_not_found")
        record = self.get(management_id)
        if record.revision != expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if (
            record.lifecycle_state != "installed"
            or record.installation_state != "installed"
        ):
            raise McpManagedServerError("mcp_managed_host_install_required")
        if record.operation_state != "idle":
            raise McpManagedServerError("mcp_managed_host_operation_in_progress")
        if record.tool_snapshot is None or record.tool_review_state != "reviewable":
            raise McpManagedServerError("mcp_managed_host_tool_review_required")

        if record.option_kind == "remote_server":
            if record.installation_kind != "remote_activation":
                raise McpManagedServerError("mcp_managed_host_install_required")
            connection: McpRemoteConnectionSpec | McpStdioConnectionSpec = (
                self._resolve_remote_connection(
                    record,
                    configuration_required_code=(
                        "mcp_managed_host_configuration_required"
                    ),
                    plan_changed_code="mcp_managed_host_plan_changed",
                    configuration_invalid_code=(
                        "mcp_managed_host_configuration_invalid"
                    ),
                )
            )
        else:
            evidence = record.local_package_evidence
            installer = self._installer
            if (
                record.installation_kind != "local_package"
                or evidence is None
                or installer is None
                or record.registry_type is None
                or not installer.supports(record.registry_type)
            ):
                raise McpManagedServerError("mcp_managed_host_install_required")
            package = self._resolve_local_package(
                record,
                configuration_required_code=(
                    "mcp_managed_host_configuration_required"
                ),
                configuration_invalid_code=(
                    "mcp_managed_host_configuration_invalid"
                ),
            )
            user_configuration = self._resolve_mcpb_user_configuration(
                record,
                configuration_required_code=(
                    "mcp_managed_host_configuration_required"
                ),
            )
            try:
                connection = installer.resolve_installed_connection(
                    management_id=management_id,
                    expected=McpLocalPackageLaunchExpectation(
                        tree_digest=evidence.tree_digest,
                        manifest_digest=evidence.manifest_digest,
                        manifest_version=evidence.manifest_version,
                        runtime_kind=evidence.runtime_kind,
                        runtime_version=evidence.runtime_version,
                    ),
                    configuration=package,
                    user_configuration=user_configuration,
                )
            except McpLocalPackageInstallerError as error:
                raise McpManagedServerError(error.code) from None

        current = self.get(management_id)
        if (
            current.revision != expected_revision
            or current.plan_revision != record.plan_revision
            or current.tool_snapshot != record.tool_snapshot
        ):
            raise McpManagedServerError("mcp_managed_revision_conflict")
        return connection

    def resolve_host_binding(
        self,
        management_id: str,
        project_id: str,
        *,
        expected_server_revision: int,
        expected_project_binding_revision: int,
        expected_tool_snapshot_id: str,
    ) -> McpManagedHostBinding:
        """Resolve exact content-free host authority without connection material."""

        self._identity(management_id, "mcp_managed_server_not_found")
        self._identity(project_id, "mcp_managed_project_not_found")
        self._identity(
            expected_tool_snapshot_id,
            "mcp_managed_host_tool_snapshot_conflict",
        )
        if (
            isinstance(expected_server_revision, bool)
            or not isinstance(expected_server_revision, int)
            or expected_server_revision < 1
        ):
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if (
            isinstance(expected_project_binding_revision, bool)
            or not isinstance(expected_project_binding_revision, int)
            or expected_project_binding_revision < 1
        ):
            raise McpManagedServerError(
                "mcp_managed_host_project_binding_conflict"
            )
        record = self.get(management_id)
        if record.revision != expected_server_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if (
            record.lifecycle_state != "installed"
            or record.installation_state != "installed"
        ):
            raise McpManagedServerError("mcp_managed_host_install_required")
        if record.operation_state != "idle":
            raise McpManagedServerError("mcp_managed_host_operation_in_progress")
        snapshot_summary = record.tool_snapshot
        if snapshot_summary is None or record.tool_review_state != "reviewable":
            raise McpManagedServerError("mcp_managed_host_tool_review_required")
        if snapshot_summary.snapshot_id != expected_tool_snapshot_id:
            raise McpManagedServerError("mcp_managed_host_tool_snapshot_conflict")

        project_binding = next(
            (
                item
                for item in record.project_bindings
                if item.project_id == project_id
            ),
            None,
        )
        if project_binding is None:
            raise McpManagedServerError("mcp_managed_host_project_not_admitted")
        if project_binding.revision != expected_project_binding_revision:
            raise McpManagedServerError(
                "mcp_managed_host_project_binding_conflict"
            )
        if (
            not project_binding.enabled
            or project_binding.admission_state != "admitted"
            or project_binding.effective_state != "inactive_host_unavailable"
            or project_binding.tool_snapshot_id != snapshot_summary.snapshot_id
            or not project_binding.admitted_tool_ids
            or project_binding.granted_permissions != record.required_permissions
        ):
            raise McpManagedServerError("mcp_managed_host_project_not_admitted")

        snapshot = self._repository.get_tool_snapshot(management_id)
        snapshot_summary_fields = set(McpManagedToolSnapshotSummary.model_fields)
        if (
            snapshot is None
            or snapshot.management_id != management_id
            or snapshot.model_dump(
                mode="python",
                include=snapshot_summary_fields,
            )
            != snapshot_summary.model_dump(mode="python")
            or snapshot.plan_revision != record.plan_revision
        ):
            raise McpManagedServerError("mcp_managed_host_tool_snapshot_conflict")
        available_tool_ids = {item.tool_id for item in snapshot.tools}
        if any(
            item not in available_tool_ids
            for item in project_binding.admitted_tool_ids
        ):
            raise McpManagedServerError("mcp_managed_host_tool_snapshot_conflict")
        if record.transport not in {"stdio", "streamable-http", "sse"}:
            raise McpManagedServerError("mcp_managed_host_transport_unsupported")

        try:
            resolved = McpManagedHostBinding(
                management_id=management_id,
                project_id=project_id,
                server_revision=record.revision,
                project_binding_revision=project_binding.revision,
                plan_revision=record.plan_revision,
                option_kind=record.option_kind,
                transport=record.transport,
                tool_snapshot_id=snapshot.snapshot_id,
                tool_schema_digest=snapshot.schema_digest,
                reviewed_tool_count=snapshot.tool_count,
                admitted_tool_ids=project_binding.admitted_tool_ids,
                granted_permissions=project_binding.granted_permissions,
            )
        except Exception:
            raise McpManagedServerError("mcp_managed_host_binding_invalid") from None

        current = self.get(management_id)
        current_snapshot = self._repository.get_tool_snapshot(management_id)
        current_project_binding = next(
            (
                item
                for item in current.project_bindings
                if item.project_id == project_id
            ),
            None,
        )
        if (
            current.revision != expected_server_revision
            or current.plan_revision != record.plan_revision
            or current.tool_snapshot != snapshot_summary
            or current_project_binding != project_binding
            or current_snapshot != snapshot
        ):
            raise McpManagedServerError("mcp_managed_revision_conflict")
        return resolved

    def resolve_host_start_preview(
        self,
        management_id: str,
        project_id: str,
        *,
        expected_server_revision: int,
        expected_project_binding_revision: int,
        expected_tool_snapshot_id: str,
    ) -> McpManagedHostStartPreview:
        """Build an exact native-confirmation preview without starting a host."""

        binding = self.resolve_host_binding(
            management_id,
            project_id,
            expected_server_revision=expected_server_revision,
            expected_project_binding_revision=(
                expected_project_binding_revision
            ),
            expected_tool_snapshot_id=expected_tool_snapshot_id,
        )
        return build_mcp_managed_host_start_preview(binding)

    def probe_remote(
        self,
        management_id: str,
        command: ProbeMcpManagedServer,
    ) -> McpManagedProbeReceipt:
        """Run one native-confirmed, non-tool remote compatibility check."""

        self._identity(management_id, "mcp_managed_server_not_found")
        fingerprint = _canonical_digest(
            {
                "action": "probe_remote",
                "management_id": management_id,
                "command": command.model_dump(mode="json"),
            }
        )
        replay = self._repository.get_probe_request(command.request_id)
        if replay is not None:
            record, probe, stored_fingerprint = replay
            if (
                stored_fingerprint != fingerprint
                or record.management_id != management_id
            ):
                raise McpManagedServerError("mcp_managed_request_conflict")
            return McpManagedProbeReceipt(
                server=record,
                probe=probe,
                idempotent_replay=True,
            )

        record = self.get(management_id)
        if record.revision != command.expected_revision:
            raise McpManagedServerError("mcp_managed_revision_conflict")
        if record.probe_action != "available_native_confirmation_required":
            codes = {
                "unavailable_install_required": "mcp_managed_probe_install_required",
                "unavailable_configuration_required": "mcp_managed_probe_configuration_required",
                "unavailable_option_unsupported": "mcp_managed_probe_option_unsupported",
            }
            raise McpManagedServerError(codes[record.probe_action])
        if self._host is None:
            raise McpManagedServerError("mcp_managed_probe_host_unavailable")
        connection = self._resolve_remote_connection(
            record,
            configuration_required_code="mcp_managed_probe_configuration_required",
            plan_changed_code="mcp_managed_probe_plan_changed",
            configuration_invalid_code="mcp_managed_probe_configuration_invalid",
        )
        try:
            result = self._host.probe(connection)
        except McpGuardedHostError as error:
            raise McpManagedServerError(error.code) from None
        checked_at = self._now()
        updated, probe, replayed = self._repository.record_probe(
            management_id,
            command=command,
            request_fingerprint=fingerprint,
            result=result,
            checked_at=checked_at,
        )
        return McpManagedProbeReceipt(
            server=updated,
            probe=probe,
            idempotent_replay=replayed,
        )

    def set_project_binding(
        self,
        management_id: str,
        project_id: str,
        command: SetMcpManagedProjectBinding,
    ) -> McpManagedServerReceipt:
        record = self.get(management_id)
        self._identity(project_id, "mcp_managed_project_not_found")
        expected = record.required_permissions if command.enabled else ()
        if command.granted_permissions != expected:
            raise McpManagedServerError("mcp_managed_permission_grants_incomplete")
        if command.enabled:
            snapshot = self._repository.get_tool_snapshot(management_id)
            if snapshot is None:
                raise McpManagedServerError("mcp_managed_tool_review_required")
            available = {item.tool_id for item in snapshot.tools}
            if not command.admitted_tool_ids:
                raise McpManagedServerError("mcp_managed_tool_admission_required")
            if any(item not in available for item in command.admitted_tool_ids):
                raise McpManagedServerError("mcp_managed_tool_admission_stale")
        fingerprint = _canonical_digest(
            {
                "action": "set_project_binding",
                "management_id": management_id,
                "project_id": project_id,
                "command": command.model_dump(mode="json"),
            }
        )
        updated, replay = self._repository.set_project_binding(
            management_id,
            project_id,
            command=command,
            request_fingerprint=fingerprint,
            updated_at=self._now(),
        )
        return McpManagedServerReceipt(server=updated, idempotent_replay=replay)

    @staticmethod
    def _secret_reference_id(management_id: str, requirement_id: str) -> str:
        return hashlib.sha256(
            (
                "prompt-enhancer/mcp-secret-reference/v1\0"
                + management_id
                + "\0"
                + requirement_id
            ).encode("ascii")
        ).hexdigest()[:32]

    @staticmethod
    def _secret_requirement(
        record: McpManagedServer,
        requirement_id: str,
    ) -> McpManagedRequirement:
        if re.fullmatch(_ID_PATTERN, requirement_id) is None:
            raise McpManagedServerError("mcp_managed_requirement_not_found")
        requirement = next(
            (item for item in record.requirements if item.requirement_id == requirement_id),
            None,
        )
        if requirement is None or not requirement.secret:
            raise McpManagedServerError("mcp_managed_requirement_not_found")
        return requirement

    @staticmethod
    def _configuration_requirement(
        record: McpManagedServer,
        requirement_id: str,
    ) -> McpManagedRequirement:
        if re.fullmatch(_ID_PATTERN, requirement_id) is None:
            raise McpManagedServerError("mcp_managed_requirement_not_found")
        requirement = next(
            (item for item in record.requirements if item.requirement_id == requirement_id),
            None,
        )
        if (
            requirement is None
            or requirement.secret
            or not requirement.user_value_needed
        ):
            raise McpManagedServerError("mcp_managed_requirement_not_found")
        return requirement

    @staticmethod
    def _validate_configuration_value(
        requirement: McpManagedRequirement,
        value: SecretStr,
    ) -> None:
        raw = value.get_secret_value()
        if requirement.format == "boolean" and raw not in {"true", "false"}:
            raise McpManagedServerError("mcp_managed_configuration_value_invalid")
        if requirement.format == "number":
            try:
                number = float(raw)
            except ValueError:
                raise McpManagedServerError(
                    "mcp_managed_configuration_value_invalid"
                ) from None
            if not math.isfinite(number):
                raise McpManagedServerError("mcp_managed_configuration_value_invalid")
        if requirement.format == "filepath":
            candidate = Path(raw)
            if not candidate.is_absolute() or any(character in raw for character in "*?[]"):
                raise McpManagedServerError("mcp_managed_configuration_value_invalid")

    @staticmethod
    def _configuration_reference_id(
        management_id: str,
        requirement_id: str,
    ) -> str:
        return hashlib.sha256(
            (
                "prompt-enhancer/mcp-configuration-reference/v1\0"
                + management_id
                + "\0"
                + requirement_id
            ).encode("ascii")
        ).hexdigest()[:32]

    def _active_vault_reference(
        self,
        record: McpManagedServer,
        requirement: McpManagedRequirement,
        *,
        read_failure: str,
    ) -> str:
        """Return only the deterministic reference owned by this exact field.

        The opaque reference is not secret, but accepting a syntactically valid
        reference from another plan would let corrupted state read or delete a
        different credential.  Keep missing and cross-bound references
        intentionally indistinguishable at the public boundary.
        """

        expected = (
            self._secret_reference_id(
                record.management_id,
                requirement.requirement_id,
            )
            if requirement.secret
            else self._configuration_reference_id(
                record.management_id,
                requirement.requirement_id,
            )
        )
        actual = self._repository.get_secret_reference(
            record.management_id,
            requirement.requirement_id,
        )
        if actual is None or not hmac.compare_digest(actual, expected):
            raise McpManagedServerError(read_failure)
        return actual

    @staticmethod
    def _configuration_repository_error(
        error: McpManagedServerError,
    ) -> McpManagedServerError:
        """Translate legacy shared-vault storage errors into truthful API copy."""

        code = {
            "mcp_managed_secret_already_configured": (
                "mcp_managed_configuration_already_configured"
            ),
            "mcp_managed_secret_not_configured": (
                "mcp_managed_configuration_not_configured"
            ),
            "mcp_managed_secret_operation_pending": (
                "mcp_managed_configuration_operation_pending"
            ),
            "mcp_managed_secret_transition_conflict": (
                "mcp_managed_configuration_transition_conflict"
            ),
        }.get(error.code, error.code)
        return McpManagedServerError(code)

    def store_secret(
        self,
        management_id: str,
        requirement_id: str,
        command: StoreMcpManagedSecret,
    ) -> McpManagedServerReceipt:
        record = self.get(management_id)
        self._secret_requirement(record, requirement_id)
        if not self._vault.available() or self._vault.provider != "windows_credential_manager":
            raise McpManagedServerError("mcp_managed_secret_vault_unavailable")
        reference_id = self._secret_reference_id(management_id, requirement_id)
        fingerprint = _canonical_digest(
            {
                "action": "store_secret",
                "management_id": management_id,
                "requirement_id": requirement_id,
                "request_id": command.request_id,
                "expected_revision": command.expected_revision,
            }
        )
        reservation = self._repository.reserve_secret(
            management_id,
            requirement_id,
            command=command,
            request_fingerprint=fingerprint,
            reference_id=reference_id,
            vault_provider="windows_credential_manager",
            updated_at=self._now(),
        )
        if reservation.state == "active":
            return McpManagedServerReceipt(
                server=reservation.server,
                idempotent_replay=True,
            )
        try:
            # Rewriting the exact deterministic target is intentional.  It makes
            # a native-confirmed retry repair an ambiguous prior vault write and
            # ensures the value from this reviewed request wins.
            self._vault.write(reference_id, command.value)
        except Exception:
            self._repository.fail_secret_store(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError("mcp_managed_secret_vault_write_failed") from None
        updated, replay = self._repository.finish_secret_store(
            management_id,
            requirement_id,
            request_id=command.request_id,
            request_fingerprint=fingerprint,
            reference_id=reference_id,
            updated_at=self._now(),
        )
        return McpManagedServerReceipt(
            server=updated,
            idempotent_replay=reservation.idempotent_replay or replay,
        )

    def remove_secret(
        self,
        management_id: str,
        requirement_id: str,
        command: RemoveMcpManagedSecret,
    ) -> McpManagedServerReceipt:
        record = self.get(management_id)
        self._secret_requirement(record, requirement_id)
        expected_reference_id = self._secret_reference_id(
            management_id,
            requirement_id,
        )
        if not self._vault.available() or self._vault.provider != "windows_credential_manager":
            raise McpManagedServerError("mcp_managed_secret_vault_unavailable")
        fingerprint = _canonical_digest(
            {
                "action": "remove_secret",
                "management_id": management_id,
                "requirement_id": requirement_id,
                "command": command.model_dump(mode="json"),
            }
        )
        removal = self._repository.begin_secret_removal(
            management_id,
            requirement_id,
            command=command,
            request_fingerprint=fingerprint,
            updated_at=self._now(),
        )
        if removal.reference_id is None:
            return McpManagedServerReceipt(
                server=removal.server,
                idempotent_replay=True,
            )
        if not hmac.compare_digest(removal.reference_id, expected_reference_id):
            self._repository.fail_secret_removal(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=removal.reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError("mcp_managed_secret_cleanup_required")
        try:
            self._vault.delete(removal.reference_id)
        except Exception:
            self._repository.fail_secret_removal(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=removal.reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError("mcp_managed_secret_cleanup_required") from None
        updated, replay = self._repository.finish_secret_removal(
            management_id,
            requirement_id,
            request_id=command.request_id,
            request_fingerprint=fingerprint,
            reference_id=removal.reference_id,
            updated_at=self._now(),
        )
        return McpManagedServerReceipt(
            server=updated,
            idempotent_replay=removal.idempotent_replay or replay,
        )

    def store_configuration(
        self,
        management_id: str,
        requirement_id: str,
        command: StoreMcpManagedConfiguration,
    ) -> McpManagedServerReceipt:
        """Store one non-secret input in the OS vault without API echo."""

        record = self.get(management_id)
        requirement = self._configuration_requirement(record, requirement_id)
        self._validate_configuration_value(requirement, command.value)
        if not self._vault.available() or self._vault.provider != "windows_credential_manager":
            raise McpManagedServerError("mcp_managed_secret_vault_unavailable")
        reference_id = self._configuration_reference_id(
            management_id,
            requirement_id,
        )
        fingerprint = _canonical_digest(
            {
                # The repository mutation ledger predates generic values. Its
                # fixed action remains private; the value itself is excluded.
                "action": "store_secret",
                "value_kind": "non_secret_configuration",
                "management_id": management_id,
                "requirement_id": requirement_id,
                "request_id": command.request_id,
                "expected_revision": command.expected_revision,
            }
        )
        try:
            reservation = self._repository.reserve_secret(
                management_id,
                requirement_id,
                command=command,
                request_fingerprint=fingerprint,
                reference_id=reference_id,
                vault_provider="windows_credential_manager",
                updated_at=self._now(),
            )
        except McpManagedServerError as error:
            raise self._configuration_repository_error(error) from None
        if reservation.state == "active":
            return McpManagedServerReceipt(
                server=reservation.server,
                idempotent_replay=True,
            )
        try:
            self._vault.write(reference_id, command.value)
        except Exception:
            self._repository.fail_secret_store(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_managed_configuration_vault_write_failed"
            ) from None
        try:
            updated, replay = self._repository.finish_secret_store(
                management_id,
                requirement_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                reference_id=reference_id,
                updated_at=self._now(),
            )
        except McpManagedServerError as error:
            raise self._configuration_repository_error(error) from None
        return McpManagedServerReceipt(
            server=updated,
            idempotent_replay=reservation.idempotent_replay or replay,
        )

    def remove_configuration(
        self,
        management_id: str,
        requirement_id: str,
        command: RemoveMcpManagedConfiguration,
    ) -> McpManagedServerReceipt:
        record = self.get(management_id)
        self._configuration_requirement(record, requirement_id)
        expected_reference_id = self._configuration_reference_id(
            management_id,
            requirement_id,
        )
        if not self._vault.available() or self._vault.provider != "windows_credential_manager":
            raise McpManagedServerError("mcp_managed_secret_vault_unavailable")
        fingerprint = _canonical_digest(
            {
                "action": "remove_secret",
                "value_kind": "non_secret_configuration",
                "management_id": management_id,
                "requirement_id": requirement_id,
                "command": command.model_dump(mode="json"),
            }
        )
        try:
            removal = self._repository.begin_secret_removal(
                management_id,
                requirement_id,
                command=command,
                request_fingerprint=fingerprint,
                updated_at=self._now(),
            )
        except McpManagedServerError as error:
            raise self._configuration_repository_error(error) from None
        if removal.reference_id is None:
            return McpManagedServerReceipt(
                server=removal.server,
                idempotent_replay=True,
            )
        if not hmac.compare_digest(removal.reference_id, expected_reference_id):
            self._repository.fail_secret_removal(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=removal.reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_managed_configuration_cleanup_required"
            )
        try:
            self._vault.delete(removal.reference_id)
        except Exception:
            self._repository.fail_secret_removal(
                management_id,
                requirement_id,
                request_id=command.request_id,
                reference_id=removal.reference_id,
                updated_at=self._now(),
            )
            raise McpManagedServerError(
                "mcp_managed_configuration_cleanup_required"
            ) from None
        try:
            updated, replay = self._repository.finish_secret_removal(
                management_id,
                requirement_id,
                request_id=command.request_id,
                request_fingerprint=fingerprint,
                reference_id=removal.reference_id,
                updated_at=self._now(),
            )
        except McpManagedServerError as error:
            raise self._configuration_repository_error(error) from None
        return McpManagedServerReceipt(
            server=updated,
            idempotent_replay=removal.idempotent_replay or replay,
        )


__all__ = (
    "MAX_MCP_MANAGED_LIST",
    "MAX_MCP_MANAGED_SERVERS",
    "MAX_MCP_SECRET_BYTES",
    "MCP_MANAGED_SERVER_CONTRACT_VERSION",
    "MCP_MANAGED_SERVER_PATH",
    "ApplyMcpManagedLifecycle",
    "ApplyMcpManagedLocalCleanup",
    "CreateMcpManagedServer",
    "InspectMcpManagedLocalConfiguration",
    "McpManagedPermission",
    "McpManagedHostProbe",
    "McpManagedLifecyclePreview",
    "McpManagedLifecycleReceipt",
    "McpManagedLocalCleanupPreview",
    "McpManagedLocalCleanupReceipt",
    "McpManagedLocalConfigurationInspection",
    "McpManagedLocalConfigurationInspectionPreview",
    "McpManagedLocalConfigurationInspectionReceipt",
    "McpManagedLocalOperationRecovery",
    "McpManagedLocalUpdatePreview",
    "McpManagedLocalPackageEvidence",
    "McpManagedProbeReceipt",
    "McpManagedProjectBinding",
    "McpManagedReviewedTool",
    "McpManagedRequirement",
    "McpManagedSecretReferenceState",
    "McpManagedSecretVaultStatus",
    "McpManagedServer",
    "McpManagedServerError",
    "McpManagedServerList",
    "McpManagedServerReceipt",
    "McpManagedServerRepository",
    "McpManagedServerService",
    "McpManagedToolSnapshot",
    "McpManagedToolSnapshotSummary",
    "McpSecretVault",
    "ProbeMcpManagedServer",
    "RemoveMcpManagedConfiguration",
    "RemoveMcpManagedSecret",
    "SecretRemoval",
    "SecretReservation",
    "SetMcpManagedProjectBinding",
    "StoreMcpManagedConfiguration",
    "StoreMcpManagedSecret",
)
