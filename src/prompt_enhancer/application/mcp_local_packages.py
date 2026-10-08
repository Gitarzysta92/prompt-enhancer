"""Narrow boundary for checksum-pinned, isolated local MCP packages.

Archive contents and manifest text remain inside infrastructure. Exact launch
paths, arguments, and environment values may leave the installer only inside a
transient guarded connection specification; they are never durable or public.
Infrastructure returns bounded integrity evidence plus strict local-only tool
contracts for owner review, while public lifecycle receipts still exclude tool
names and schemas.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

from pydantic import Field, SecretStr, model_validator

from ..domain import StrictModel
from .mcp_guarded_host import McpHostProbeResult, McpStdioConnectionSpec
from .mcp_registry_catalog import McpRegistryResolvedLocalPackage


class McpLocalPackageInstallerError(RuntimeError):
    """Content-free installer failure with explicit cleanup truth."""

    def __init__(
        self,
        code: str,
        *,
        cleanup_required: bool = False,
        process_tree_cleanup: Literal["verified", "not_applicable", "unconfirmed"] = (
            "not_applicable"
        ),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.cleanup_required = cleanup_required
        self.process_tree_cleanup = process_tree_cleanup


class McpLocalPackageInstallResult(StrictModel):
    """Content-free evidence returned after publication and process cleanup."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: Literal["0.3", "0.4"]
    license_state: Literal["declared"] = "declared"
    runtime_kind: Literal["node", "python", "binary"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=64)
    probe: McpHostProbeResult
    publication_state: Literal["published"] = "published"


class McpLocalPackageUserConfigurationRequirement(StrictModel):
    """Reviewed, content-free MCPB user configuration metadata."""

    requirement_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    location: Literal["package_argument", "environment_variable"]
    required: bool
    secret: bool
    format: Literal["string", "number", "boolean", "filepath"]
    user_value_needed: bool
    default_declared: bool

    @model_validator(mode="after")
    def coherent_value_source(self) -> "McpLocalPackageUserConfigurationRequirement":
        if self.user_value_needed != (self.required and not self.default_declared):
            raise ValueError("MCPB configuration value source is incoherent")
        return self


class McpLocalPackageConfigurationInspectionResult(StrictModel):
    """No-execution result after exact artifact and manifest inspection."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: Literal["0.3", "0.4"]
    configuration_schema_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: tuple[McpLocalPackageUserConfigurationRequirement, ...] = Field(
        max_length=32
    )
    archive_retained: Literal[False] = False
    process_started: Literal[False] = False


class McpLocalPackageUninstallResult(StrictModel):
    """Content-free evidence for one digest-bound quarantine transition."""

    tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    quarantine_state: Literal["prepared"] = "prepared"
    package_changed: Literal[True] = True
    process_started: Literal[False] = False


class McpLocalPackageCleanupResult(StrictModel):
    """Truthful result for replay-safe completion of an interrupted removal."""

    tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_presence: Literal["absent"] = "absent"
    filesystem_changed: bool = Field(strict=True)
    process_started: Literal[False] = False


class McpLocalPackageLaunchExpectation(StrictModel):
    """Content-free evidence required to re-derive one transient launch."""

    tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: Literal["0.3", "0.4"]
    runtime_kind: Literal["node", "python", "binary"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def coherent_runtime(self) -> "McpLocalPackageLaunchExpectation":
        if (self.runtime_kind == "binary") != (self.runtime_version is None):
            raise ValueError("local package launch runtime evidence is incoherent")
        return self


class McpLocalPackageStagedUpdateResult(StrictModel):
    """Content-free evidence for a verified target that is not yet published."""

    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: Literal["0.3", "0.4"]
    license_state: Literal["declared"] = "declared"
    runtime_kind: Literal["node", "python", "binary"]
    runtime_version: str | None = Field(default=None, min_length=1, max_length=64)
    probe: McpHostProbeResult
    staging_state: Literal["verified"] = "verified"


class McpLocalPackageUpdatePublicationResult(StrictModel):
    """Exact digests after publishing a target and retaining one generation."""

    target_tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollback_tree_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_changed: Literal[True] = True
    process_started: Literal[False] = False
    rollback_generation_retained: Literal[True] = True


class McpLocalPackageInstaller(Protocol):
    """Registry-specific adapter; implementations must never invoke a shell."""

    def supports(self, registry_type: str) -> bool: ...

    def inspect_configuration(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
    ) -> McpLocalPackageConfigurationInspectionResult: ...

    def install_and_probe(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpLocalPackageInstallResult: ...

    def resolve_installed_connection(
        self,
        *,
        management_id: str,
        expected: McpLocalPackageLaunchExpectation,
        configuration: McpRegistryResolvedLocalPackage | None = None,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpStdioConnectionSpec: ...

    def rollback_publication(
        self,
        *,
        management_id: str,
        expected_tree_digest: str,
    ) -> bool: ...

    def prepare_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageUninstallResult: ...

    def commit_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> bool: ...

    def rollback_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> bool: ...

    def complete_interrupted_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageCleanupResult: ...

    def stage_update(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpLocalPackageStagedUpdateResult: ...

    def publish_update(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> McpLocalPackageUpdatePublicationResult: ...

    def rollback_update_publication(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> bool: ...

    def swap_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_rollback_tree_digest: str,
    ) -> bool: ...

    def cleanup_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageCleanupResult: ...


__all__ = (
    "McpLocalPackageConfigurationInspectionResult",
    "McpLocalPackageInstallResult",
    "McpLocalPackageCleanupResult",
    "McpLocalPackageInstaller",
    "McpLocalPackageInstallerError",
    "McpLocalPackageLaunchExpectation",
    "McpLocalPackageStagedUpdateResult",
    "McpLocalPackageUninstallResult",
    "McpLocalPackageUpdatePublicationResult",
    "McpLocalPackageUserConfigurationRequirement",
)
