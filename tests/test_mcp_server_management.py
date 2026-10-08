"""Store-03: durable plans, project grants, and OS-vault references."""

from __future__ import annotations

from datetime import UTC, datetime
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogService,
    CreateAgentProject,
)
from prompt_enhancer.application.mcp_registry_catalog import (
    McpRegistryCacheRecord,
    McpRegistryCatalogService,
)
from prompt_enhancer.application.mcp_guarded_host import (
    McpGuardedHostError,
    McpHostProbeResult,
    McpReviewedToolContract,
    McpStdioConnectionSpec,
)
from prompt_enhancer.application.mcp_local_packages import (
    McpLocalPackageCleanupResult,
    McpLocalPackageConfigurationInspectionResult,
    McpLocalPackageInstallResult,
    McpLocalPackageInstallerError,
    McpLocalPackageLaunchExpectation,
    McpLocalPackageStagedUpdateResult,
    McpLocalPackageUninstallResult,
    McpLocalPackageUpdatePublicationResult,
    McpLocalPackageUserConfigurationRequirement,
)
from prompt_enhancer.application.mcp_server_management import (
    MCP_MANAGED_SERVER_PATH,
    ApplyMcpManagedLocalRollback,
    ApplyMcpManagedLocalRollbackCleanup,
    ApplyMcpManagedLocalOperationRecovery,
    ApplyMcpManagedLocalUpdate,
    ApplyMcpManagedLifecycle,
    ApplyMcpManagedLocalCleanup,
    CreateMcpManagedServer,
    InspectMcpManagedLocalConfiguration,
    McpManagedServer,
    McpManagedServerError,
    McpManagedServerList,
    McpManagedServerService,
    ProbeMcpManagedServer,
    RemoveMcpManagedConfiguration,
    RemoveMcpManagedSecret,
    SetMcpManagedProjectBinding,
    StoreMcpManagedConfiguration,
    StoreMcpManagedSecret,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.infrastructure.sqlite.mcp_server_management import (
    SqliteMcpManagedServerRepository,
)
from prompt_enhancer.infrastructure.mcp_secret_vault import (
    WindowsCredentialManagerMcpSecretVault,
)
from prompt_enhancer.interfaces.http.mcp_server_management_routes import (
    create_mcp_server_management_router,
)


T0 = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _reviewed_probe(
    management_id: str,
    *,
    transport: str,
    tool_count: int,
    elapsed_ms: int,
    process_started: bool,
    description: str = "Reads fictional example data without external effects.",
) -> McpHostProbeResult:
    canonical: list[dict[str, Any]] = []
    reviewed: list[McpReviewedToolContract] = []
    for index in range(tool_count):
        name = f"synthetic_tool_{index + 1}"
        title = f"Synthetic tool {index + 1}"
        input_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        }
        material = {
            "name": name,
            "title": title,
            "description": description,
            "input": input_schema,
            "output": None,
        }
        canonical.append(material)
        contract_json = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        contract_digest = hashlib.sha256(contract_json.encode("utf-8")).hexdigest()
        input_json = json.dumps(
            input_schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        reviewed.append(
            McpReviewedToolContract(
                tool_id=contract_digest[:32],
                name=name,
                title=title,
                description=description,
                model_alias=f"mcp_{management_id[:8]}_synthetic_{index + 1}",
                input_schema=input_schema,
                input_schema_digest=hashlib.sha256(
                    input_json.encode("utf-8")
                ).hexdigest(),
                model_input_schema=input_schema,
                contract_digest=contract_digest,
            )
        )
    schema_json = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return McpHostProbeResult(
        transport=transport,
        protocol_version="2026-07-28",
        tool_count=tool_count,
        schema_digest=hashlib.sha256(schema_json.encode("utf-8")).hexdigest(),
        elapsed_ms=elapsed_ms,
        process_started=process_started,
        process_tree_cleanup="verified" if process_started else "not_applicable",
        tool_names_persisted=True,
        tool_schemas_persisted=True,
        reviewed_tools=tuple(reviewed),
    )


def _detail_page() -> dict[str, Any]:
    return {
        "server": {
            "$schema": "https://static.modelcontextprotocol.io/schemas/example/server.schema.json",
            "name": "com.example/synthetic-files",
            "title": "Synthetic Files",
            "description": "Inspect fictional example files through MCP.",
            "version": "1.2.3",
            "websiteUrl": "https://example.com/synthetic-files",
            "repository": {
                "url": "https://github.com/example/synthetic-files",
                "source": "github",
                "id": "synthetic-repository-id",
                "subfolder": "packages/files",
            },
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "@example/synthetic-files",
                    "version": "1.2.3",
                    "runtimeHint": "npx",
                    "fileSha256": "a" * 64,
                    "transport": {"type": "stdio"},
                    "runtimeArguments": [
                        {
                            "type": "named",
                            "name": "--workspace",
                            "description": "A fictional workspace folder.",
                            "format": "filepath",
                            "isRequired": True,
                            "placeholder": "X:\\example\\workspace",
                        }
                    ],
                    "packageArguments": [
                        {"type": "named", "name": "--mode", "value": "example-fixed"}
                    ],
                    "environmentVariables": [
                        {
                            "name": "EXAMPLE_TOKEN",
                            "description": "A fictional access token.",
                            "isRequired": True,
                            "isSecret": True,
                            "placeholder": "example-placeholder",
                        }
                    ],
                }
            ],
            "remotes": [],
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "updatedAt": "2026-08-28T10:20:30Z",
                "isLatest": True,
            }
        },
    }


class _RegistryClient:
    def get_server_version(self, *, name: str, version: str):
        assert name == "com.example/synthetic-files"
        assert version == "1.2.3"
        return _detail_page()

    def list_server_versions(self, *, name: str):
        assert name == "com.example/synthetic-files"
        return {"servers": [_detail_page()], "metadata": {"count": 1}}

    def list_servers(self, *, search: str, cursor: str | None, limit: int):
        del search, cursor, limit
        return {"servers": [_detail_page()], "metadata": {"count": 1}}


def _remote_detail_page(
    *,
    secret_header: bool = False,
    configuration_header: dict[str, Any] | None = None,
    endpoint: str = "https://mcp.example.com/service?synthetic=hidden",
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = _detail_page()
    detail["server"]["packages"] = []
    remote: dict[str, Any] = {
        "type": "streamable-http",
        "url": endpoint,
    }
    if variables is not None:
        remote["variables"] = copy.deepcopy(variables)
    headers: list[dict[str, Any]] = []
    if secret_header:
        headers.append(
            {
                "name": "Authorization",
                "isRequired": True,
                "isSecret": True,
            }
        )
    if configuration_header is not None:
        headers.append(copy.deepcopy(configuration_header))
    if headers:
        remote["headers"] = headers
    detail["server"]["remotes"] = [remote]
    return detail


class _RemoteRegistryClient:
    def __init__(
        self,
        *,
        secret_header: bool = False,
        configuration_header: dict[str, Any] | None = None,
        endpoint: str = "https://mcp.example.com/service?synthetic=hidden",
        variables: dict[str, Any] | None = None,
    ) -> None:
        self.detail = _remote_detail_page(
            secret_header=secret_header,
            configuration_header=configuration_header,
            endpoint=endpoint,
            variables=variables,
        )

    def get_server_version(self, *, name: str, version: str):
        assert name == "com.example/synthetic-files"
        assert version == "1.2.3"
        return self.detail

    def list_server_versions(self, *, name: str):
        assert name == "com.example/synthetic-files"
        return {"servers": [self.detail], "metadata": {"count": 1}}

    def list_servers(self, *, search: str, cursor: str | None, limit: int):
        del search, cursor, limit
        return {"servers": [self.detail], "metadata": {"count": 1}}


def _mcpb_detail_page() -> dict[str, Any]:
    detail = _detail_page()
    detail["server"]["packages"] = [
        {
            "registryType": "mcpb",
            "identifier": (
                "https://github.com/example/synthetic-files/releases/download/"
                "v1.2.3/synthetic-files.mcpb"
            ),
            "version": "1.2.3",
            "fileSha256": "b" * 64,
            "transport": {"type": "stdio"},
        }
    ]
    detail["server"]["remotes"] = []
    return detail


class _McpbRegistryClient:
    def __init__(self) -> None:
        self.detail = _mcpb_detail_page()

    def get_server_version(self, *, name: str, version: str):
        assert name == "com.example/synthetic-files"
        assert version == "1.2.3"
        return self.detail

    def list_server_versions(self, *, name: str):
        assert name == "com.example/synthetic-files"
        return {"servers": [self.detail], "metadata": {"count": 1}}

    def list_servers(self, *, search: str, cursor: str | None, limit: int):
        del search, cursor, limit
        return {"servers": [self.detail], "metadata": {"count": 1}}


def _versioned_mcpb_detail(version: str, digest_character: str) -> dict[str, Any]:
    detail = copy.deepcopy(_mcpb_detail_page())
    detail["server"]["version"] = version
    package = detail["server"]["packages"][0]
    package["version"] = version
    package["identifier"] = (
        "https://github.com/example/synthetic-files/releases/download/"
        f"v{version}/synthetic-files.mcpb"
    )
    package["fileSha256"] = digest_character * 64
    return detail


class _UpdatingMcpbRegistryClient(_McpbRegistryClient):
    def __init__(self) -> None:
        self.current = _versioned_mcpb_detail("1.2.3", "b")
        self.latest = _versioned_mcpb_detail("2.0.0", "f")
        self.detail = self.current
        self.calls: list[tuple[str, str]] = []

    def get_server_version(self, *, name: str, version: str):
        assert name == "com.example/synthetic-files"
        self.calls.append((name, version))
        if version == "latest" or version == "2.0.0":
            return self.latest
        assert version == "1.2.3"
        return self.current

    def list_server_versions(self, *, name: str):
        assert name == "com.example/synthetic-files"
        return {
            "servers": [self.latest, self.current],
            "metadata": {"count": 2},
        }

    def list_servers(self, *, search: str, cursor: str | None, limit: int):
        del search, cursor, limit
        return {"servers": [self.current], "metadata": {"count": 1}}

class _Host:
    def __init__(self) -> None:
        self.connections = []

    def probe(self, connection):  # noqa: ANN001
        self.connections.append(connection)
        return _reviewed_probe(
            connection.management_id,
            transport=connection.transport,
            tool_count=2,
            elapsed_ms=41,
            process_started=False,
        )


class _DriftingHost:
    def __init__(self) -> None:
        self.connections = []

    def probe(self, connection):  # noqa: ANN001
        self.connections.append(connection)
        return _reviewed_probe(
            connection.management_id,
            transport=connection.transport,
            tool_count=2 if len(self.connections) == 1 else 1,
            elapsed_ms=40 + len(self.connections),
            process_started=False,
        )


class _RefusingRemoteHost:
    def __init__(self, code: str) -> None:
        self.code = code
        self.connections = []

    def probe(self, connection):  # noqa: ANN001
        self.connections.append(connection)
        raise McpGuardedHostError(self.code)


class _LocalInstaller:
    def __init__(self) -> None:
        self.inspections = []
        self.inspection_requirements: tuple[
            McpLocalPackageUserConfigurationRequirement, ...
        ] = ()
        self.installs: list[tuple[str, str]] = []
        self.install_packages = []
        self.install_user_configurations = []
        self.rollbacks: list[tuple[str, str]] = []
        self.uninstalls: list[tuple[str, str, str]] = []
        self.uninstall_commits: list[tuple[str, str, str]] = []
        self.uninstall_rollbacks: list[tuple[str, str, str]] = []
        self.recoveries: list[tuple[str, str, str]] = []
        self.failure: McpLocalPackageInstallerError | None = None
        self.uninstall_failure: McpLocalPackageInstallerError | None = None
        self.uninstall_commit_succeeds = True
        self.uninstall_rollback_succeeds = True
        self.recovery_failure: McpLocalPackageInstallerError | None = None
        self.recovery_filesystem_changed = True
        self.update_stages: list[tuple[str, str, str, str]] = []
        self.update_publications: list[tuple[str, str, str, str]] = []
        self.update_publication_rollbacks: list[tuple[str, str, str, str]] = []
        self.update_stage_failure: McpLocalPackageInstallerError | None = None
        self.update_publish_failure: McpLocalPackageInstallerError | None = None
        self.update_rollback_succeeds = True
        self.update_tool_count = 4
        self.update_tool_description = (
            "Reads fictional example data without external effects."
        )
        self.rollback_swaps: list[tuple[str, str, str, str]] = []
        self.rollback_swap_succeeds = True
        self.rollback_cleanups: list[tuple[str, str, str]] = []
        self.rollback_cleanup_failure: McpLocalPackageInstallerError | None = None
        self.rollback_cleanup_changed = True
        self.connection_resolutions: list[
            tuple[str, McpLocalPackageLaunchExpectation]
        ] = []
        self.connection_configurations = []
        self.connection_user_configurations = []
        self.connection_resolution_failure: McpLocalPackageInstallerError | None = None

    def supports(self, registry_type: str) -> bool:
        return registry_type == "mcpb"

    def inspect_configuration(self, package, *, management_id: str):  # noqa: ANN001
        self.inspections.append((management_id, package))
        return McpLocalPackageConfigurationInspectionResult(
            artifact_sha256=package.file_sha256,
            artifact_bytes=2_048,
            manifest_digest="d" * 64,
            manifest_version="0.3",
            configuration_schema_digest="e" * 64,
            requirements=self.inspection_requirements,
        )

    def install_and_probe(
        self,
        package,  # noqa: ANN001
        *,
        management_id: str,
        user_configuration=None,  # noqa: ANN001
    ):
        self.install_user_configurations.append(user_configuration)
        self.installs.append((management_id, package.file_sha256))
        self.install_packages.append(package)
        if self.failure is not None:
            raise self.failure
        return McpLocalPackageInstallResult(
            artifact_sha256=package.file_sha256,
            artifact_bytes=4_096,
            tree_digest="c" * 64,
            manifest_digest="d" * 64,
            manifest_version="0.3",
            runtime_kind="binary",
            runtime_version=None,
            probe=_reviewed_probe(
                management_id,
                transport="stdio",
                tool_count=3,
                elapsed_ms=73,
                process_started=True,
            ),
        )

    def resolve_installed_connection(
        self,
        *,
        management_id: str,
        expected: McpLocalPackageLaunchExpectation,
        configuration=None,  # noqa: ANN001
        user_configuration=None,  # noqa: ANN001
    ) -> McpStdioConnectionSpec:
        self.connection_resolutions.append((management_id, expected))
        self.connection_configurations.append(configuration)
        self.connection_user_configurations.append(user_configuration)
        if self.connection_resolution_failure is not None:
            raise self.connection_resolution_failure
        return McpStdioConnectionSpec(
            management_id=management_id,
            executable="X:\\example\\synthetic-mcp\\server.exe",
            arguments=("--mode", "synthetic"),
            environment={"EXAMPLE_MODE": "synthetic"},
            working_directory="X:\\example\\synthetic-mcp",
        )

    def rollback_publication(
        self, *, management_id: str, expected_tree_digest: str
    ) -> bool:
        self.rollbacks.append((management_id, expected_tree_digest))
        return True

    def prepare_uninstall(
        self, *, management_id: str, operation_id: str, expected_tree_digest: str
    ) -> McpLocalPackageUninstallResult:
        self.uninstalls.append((management_id, operation_id, expected_tree_digest))
        if self.uninstall_failure is not None:
            raise self.uninstall_failure
        return McpLocalPackageUninstallResult(tree_digest=expected_tree_digest)

    def commit_uninstall(
        self, *, management_id: str, operation_id: str, expected_tree_digest: str
    ) -> bool:
        self.uninstall_commits.append(
            (management_id, operation_id, expected_tree_digest)
        )
        return self.uninstall_commit_succeeds

    def rollback_uninstall(
        self, *, management_id: str, operation_id: str, expected_tree_digest: str
    ) -> bool:
        self.uninstall_rollbacks.append(
            (management_id, operation_id, expected_tree_digest)
        )
        return self.uninstall_rollback_succeeds

    def complete_interrupted_uninstall(
        self, *, management_id: str, operation_id: str, expected_tree_digest: str
    ) -> McpLocalPackageCleanupResult:
        self.recoveries.append(
            (management_id, operation_id, expected_tree_digest)
        )
        if self.recovery_failure is not None:
            raise self.recovery_failure
        return McpLocalPackageCleanupResult(
            tree_digest=expected_tree_digest,
            filesystem_changed=self.recovery_filesystem_changed,
        )

    def stage_update(
        self,
        package,  # noqa: ANN001
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        user_configuration=None,  # noqa: ANN001
    ) -> McpLocalPackageStagedUpdateResult:
        assert user_configuration is None or user_configuration == {}
        self.update_stages.append(
            (
                management_id,
                operation_id,
                expected_current_tree_digest,
                package.file_sha256,
            )
        )
        if self.update_stage_failure is not None:
            raise self.update_stage_failure
        return McpLocalPackageStagedUpdateResult(
            artifact_sha256=package.file_sha256,
            artifact_bytes=8_192,
            tree_digest="8" * 64,
            manifest_digest="9" * 64,
            manifest_version="0.4",
            runtime_kind="binary",
            runtime_version=None,
            probe=_reviewed_probe(
                management_id,
                transport="stdio",
                tool_count=self.update_tool_count,
                elapsed_ms=83,
                process_started=True,
                description=self.update_tool_description,
            ),
        )

    def publish_update(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> McpLocalPackageUpdatePublicationResult:
        self.update_publications.append(
            (
                management_id,
                operation_id,
                expected_current_tree_digest,
                expected_target_tree_digest,
            )
        )
        if self.update_publish_failure is not None:
            raise self.update_publish_failure
        return McpLocalPackageUpdatePublicationResult(
            target_tree_digest=expected_target_tree_digest,
            rollback_tree_digest=expected_current_tree_digest,
        )

    def rollback_update_publication(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> bool:
        self.update_publication_rollbacks.append(
            (
                management_id,
                operation_id,
                expected_current_tree_digest,
                expected_target_tree_digest,
            )
        )
        return self.update_rollback_succeeds

    def swap_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_rollback_tree_digest: str,
    ) -> bool:
        self.rollback_swaps.append(
            (
                management_id,
                operation_id,
                expected_current_tree_digest,
                expected_rollback_tree_digest,
            )
        )
        return self.rollback_swap_succeeds

    def cleanup_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageCleanupResult:
        self.rollback_cleanups.append(
            (management_id, operation_id, expected_tree_digest)
        )
        if self.rollback_cleanup_failure is not None:
            raise self.rollback_cleanup_failure
        return McpLocalPackageCleanupResult(
            tree_digest=expected_tree_digest,
            filesystem_changed=self.rollback_cleanup_changed,
        )


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, McpRegistryCacheRecord] = {}

    def get(self, key: str) -> McpRegistryCacheRecord | None:
        return self.values.get(key)

    def put(self, key: str, record: McpRegistryCacheRecord) -> None:
        self.values[key] = record


class _Vault:
    provider = "windows_credential_manager"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.reads: list[str] = []
        self.fail_write = False
        self.fail_delete = False

    def available(self) -> bool:
        return True

    def contains(self, reference_id: str) -> bool:
        return reference_id in self.values

    def read(self, reference_id: str) -> SecretStr:
        self.reads.append(reference_id)
        try:
            return SecretStr(self.values[reference_id])
        except KeyError:
            raise RuntimeError("synthetic vault read failed") from None

    def write(self, reference_id: str, value: SecretStr) -> None:
        if self.fail_write:
            raise RuntimeError("synthetic vault write failed")
        self.values[reference_id] = value.get_secret_value()

    def delete(self, reference_id: str) -> None:
        if self.fail_delete:
            raise RuntimeError("synthetic vault delete failed")
        self.values.pop(reference_id, None)


def _database(tmp_path: Path) -> AgentCatalogSqliteDatabase:
    return AgentCatalogSqliteDatabase(tmp_path / AGENT_CATALOG_DATABASE_FILENAME)


def _catalog() -> McpRegistryCatalogService:
    return McpRegistryCatalogService(
        _RegistryClient(),
        _MemoryCache(),
        clock=lambda: T0,
    )


def _remote_catalog(client: _RemoteRegistryClient) -> McpRegistryCatalogService:
    return McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)


def _mcpb_catalog(client: _McpbRegistryClient) -> McpRegistryCatalogService:
    return McpRegistryCatalogService(client, _MemoryCache(), clock=lambda: T0)


def _service(
    database: AgentCatalogSqliteDatabase,
    vault: _Vault,
    *,
    ids: list[str] | None = None,
    catalog: McpRegistryCatalogService | None = None,
    host=None,
    installer=None,
) -> McpManagedServerService:
    generated = iter(ids or ["9" * 32])
    return McpManagedServerService(
        SqliteMcpManagedServerRepository(database),
        catalog or _catalog(),
        vault,
        host,
        installer,
        clock=lambda: T0,
        id_factory=lambda: next(generated),
    )


def _review(service: McpManagedServerService):
    catalog = service._catalog.list_servers()  # type: ignore[attr-defined]
    server = catalog.servers[0]
    review = service._catalog.review_server(  # type: ignore[attr-defined]
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
    )
    return server, review, review.options[0]


def _create(
    service: McpManagedServerService,
    *,
    inspect_local: bool = True,
):
    server, review, option = _review(service)
    command = CreateMcpManagedServer(
        request_id="1" * 32,
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
    )
    receipt = service.create(command)
    if inspect_local:
        preview = service.local_configuration_inspection_preview(
            receipt.server.management_id
        )
        if preview.availability == "available":
            inspected = service.inspect_local_configuration(
                receipt.server.management_id,
                InspectMcpManagedLocalConfiguration(
                    request_id="0" * 32,
                    expected_revision=preview.expected_revision,
                    preview_digest=preview.preview_digest,
                ),
            )
            receipt = receipt.model_copy(update={"server": inspected.server})
    return receipt, command


def _create_remote(service: McpManagedServerService):
    server, review, option = _review(service)
    assert option.kind == "remote_server"
    command = CreateMcpManagedServer(
        request_id="6" * 32,
        catalog_id=server.catalog_id,
        name=server.name,
        version=server.version,
        option_id=option.option_id,
        plan_revision=review.plan_revision,
    )
    return service.create(command), command


def _project(database: AgentCatalogSqliteDatabase, *, project_id: str, name: str):
    return AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=lambda: project_id,
    ).create_project(CreateAgentProject(name=name))


def _secret_requirement(record):
    return next(item for item in record.requirements if item.secret)


def _configuration_requirement(record, *, location: str = "transport_header"):
    return next(
        item
        for item in record.requirements
        if not item.secret
        and item.user_value_needed
        and item.location == location
    )


def test_reviewed_plan_is_durable_bounded_and_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(database, vault)

    receipt, command = _create(service)
    record = receipt.server

    assert receipt.idempotent_replay is False
    assert receipt.process_started is False
    assert receipt.endpoint_connected is False
    assert receipt.package_changed is False
    assert receipt.tool_authority_granted is False
    assert record.lifecycle_state == "planned"
    assert record.installation_state == "not_installed"
    assert record.host_state == "not_started"
    assert record.health_state == "not_checked"
    assert record.update_state == "not_checked"
    assert record.tool_routing_state == "inactive"
    assert record.required_permissions == (
        "process_spawn",
        "filesystem_read",
        "filesystem_write",
        "credential_use",
    )
    assert _secret_requirement(record).configuration_state == "secret_missing"
    assert next(
        item for item in record.requirements if item.name == "--workspace"
    ).configuration_state == "value_required"
    assert next(
        item for item in record.requirements if item.name == "--mode"
    ).configuration_state == "publisher_value_declared"

    replay = service.create(command)
    assert replay.idempotent_replay is True
    assert replay.server == record

    restarted = _service(database, vault, ids=["8" * 32])
    listed = restarted.list()
    assert listed.total == 1
    assert listed.servers == (record,)
    assert listed.secret_vault.availability == "available"
    assert listed.secret_vault.values_in_database is False
    assert listed.execution_truth == (
        "reviewed_tool_admission_without_persistent_host_or_tool_authority"
    )


def test_project_binding_requires_exact_grants_and_stays_inactive(tmp_path: Path) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=_Host(),
    )
    project = _project(database, project_id="2" * 32, name="Synthetic project")
    other = _project(database, project_id="3" * 32, name="Other synthetic project")
    created, _ = _create_remote(service)
    probed = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    )
    snapshot = service.get_tool_snapshot(created.server.management_id)
    admitted_tool_ids = tuple(sorted(item.tool_id for item in snapshot.tools))

    with pytest.raises(McpManagedServerError) as incomplete:
        service.set_project_binding(
            created.server.management_id,
            project.project_id,
            SetMcpManagedProjectBinding(
                request_id="4" * 32,
                expected_revision=probed.server.revision,
                enabled=True,
                granted_permissions=("process_spawn",),
            ),
        )
    assert incomplete.value.code == "mcp_managed_permission_grants_incomplete"

    command = SetMcpManagedProjectBinding(
        request_id="5" * 32,
        expected_revision=probed.server.revision,
        enabled=True,
        granted_permissions=probed.server.required_permissions,
        admitted_tool_ids=admitted_tool_ids,
    )
    bound = service.set_project_binding(
        created.server.management_id,
        project.project_id,
        command,
    )
    assert bound.idempotent_replay is False
    assert len(bound.server.project_bindings) == 1
    binding = bound.server.project_bindings[0]
    assert binding.project_id == project.project_id
    assert binding.enabled is True
    assert binding.admission_state == "admitted"
    assert binding.tool_snapshot_id == snapshot.snapshot_id
    assert binding.admitted_tool_ids == admitted_tool_ids
    assert binding.effective_state == "inactive_install_required"
    assert binding.granted_permissions == bound.server.required_permissions
    assert all(item.project_id != other.project_id for item in bound.server.project_bindings)
    assert service.set_project_binding(
        created.server.management_id,
        project.project_id,
        command,
    ).idempotent_replay is True

    disabled = service.set_project_binding(
        created.server.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="8" * 32,
            expected_revision=bound.server.revision,
            enabled=False,
            granted_permissions=(),
        ),
    ).server.project_bindings[0]
    assert disabled.enabled is False
    assert disabled.granted_permissions == ()
    assert disabled.effective_state == "disabled"


def test_new_tool_snapshot_invalidates_exact_project_admission(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    host = _DriftingHost()
    service = _service(
        database,
        _Vault(),
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=host,
    )
    project = _project(database, project_id="2" * 32, name="Synthetic project")
    other = _project(database, project_id="3" * 32, name="Other synthetic project")
    created, _ = _create_remote(service)
    first_probe = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    )
    first_snapshot = service.get_tool_snapshot(created.server.management_id)
    first_ids = tuple(sorted(item.tool_id for item in first_snapshot.tools))
    admitted = service.set_project_binding(
        created.server.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="5" * 32,
            expected_revision=first_probe.server.revision,
            enabled=True,
            granted_permissions=first_probe.server.required_permissions,
            admitted_tool_ids=first_ids,
        ),
    ).server
    assert admitted.project_bindings[0].admission_state == "admitted"
    assert admitted.project_bindings[0].tool_snapshot_id == first_snapshot.snapshot_id
    assert all(item.project_id != other.project_id for item in admitted.project_bindings)

    drifted = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="8" * 32,
            expected_revision=admitted.revision,
        ),
    ).server
    second_snapshot = service.get_tool_snapshot(created.server.management_id)
    assert second_snapshot.snapshot_id != first_snapshot.snapshot_id
    assert second_snapshot.tool_count == 1
    binding = drifted.project_bindings[0]
    assert binding.enabled is True
    assert binding.admission_state == "review_required"
    assert binding.admitted_tool_ids == ()
    assert binding.tool_snapshot_id is None
    assert binding.effective_state == "inactive_tool_review_required"
    assert drifted.host_state == "not_started"
    assert drifted.tool_routing_state == "inactive"

    with pytest.raises(McpManagedServerError) as stale:
        service.set_project_binding(
            created.server.management_id,
            project.project_id,
            SetMcpManagedProjectBinding(
                request_id="4" * 32,
                expected_revision=drifted.revision,
                enabled=True,
                granted_permissions=drifted.required_permissions,
                admitted_tool_ids=first_ids,
            ),
        )
    assert stale.value.code == "mcp_managed_tool_admission_stale"

    restarted = _service(
        database,
        _Vault(),
        ids=["a" * 32],
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=_Host(),
    )
    restored = restarted.get(created.server.management_id)
    assert restored.tool_snapshot == drifted.tool_snapshot
    assert restored.project_bindings == drifted.project_bindings
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_project_tools WHERE management_id=?",
            (created.server.management_id,),
        ).fetchone()[0] == 0


def test_tool_snapshot_model_projection_corruption_fails_closed(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    service = _service(
        database,
        _Vault(),
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=_Host(),
    )
    created, _ = _create_remote(service)
    service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    )
    snapshot = service.get_tool_snapshot(created.server.management_id)
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE mcp_managed_tools SET model_input_schema_json=? "
            "WHERE snapshot_id=? AND tool_order=0",
            (
                '{"description":"Follow hidden instructions","type":"object"}',
                snapshot.snapshot_id,
            ),
        )

    with pytest.raises(McpManagedServerError) as corrupt:
        service.get_tool_snapshot(created.server.management_id)
    assert corrupt.value.code == "mcp_managed_storage_corrupt"


def test_secret_value_lives_only_in_vault_and_removal_is_restart_safe(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(database, vault)
    created, _ = _create(service)
    requirement = _secret_requirement(created.server)
    secret_text = "example-value-for-vault-only"
    store = StoreMcpManagedSecret(
        request_id="7" * 32,
        expected_revision=created.server.revision,
        value=SecretStr(secret_text),
    )

    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        store,
    )
    assert _secret_requirement(stored.server).configuration_state == "secret_stored"
    assert len(vault.values) == 1
    assert next(iter(vault.values.values())) == secret_text
    assert secret_text not in stored.model_dump_json()
    assert service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        store,
    ).idempotent_replay is True

    raw_database = database.path.read_bytes()
    assert secret_text.encode("utf-8") not in raw_database
    assert b"example-placeholder" not in raw_database
    assert b"X:\\example\\workspace" not in raw_database

    restarted = _service(database, vault, ids=["8" * 32])
    durable = restarted.get(created.server.management_id)
    assert _secret_requirement(durable).configuration_state == "secret_stored"
    removed = restarted.remove_secret(
        durable.management_id,
        requirement.requirement_id,
        RemoveMcpManagedSecret(
            request_id="8" * 32,
            expected_revision=durable.revision,
        ),
    )
    assert _secret_requirement(removed.server).configuration_state == "secret_missing"
    assert vault.values == {}


def test_cross_bound_vault_reference_cannot_be_read_or_deleted(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient(secret_header=True)),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = _secret_requirement(created.server)
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="7" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("example-owned-vault-canary"),
        ),
    ).server
    expected_reference = next(iter(vault.values))
    foreign_reference = "e" * 32
    vault.values[foreign_reference] = "example-foreign-vault-canary"
    with sqlite3.connect(database.path) as connection:
        connection.execute(
            "UPDATE mcp_managed_secret_references SET reference_id=? "
            "WHERE management_id=? AND requirement_id=?",
            (
                foreign_reference,
                stored.management_id,
                requirement.requirement_id,
            ),
        )

    reads_before = tuple(vault.reads)
    with pytest.raises(McpManagedServerError) as read_refused:
        service.probe_remote(
            stored.management_id,
            ProbeMcpManagedServer(
                request_id="8" * 32,
                expected_revision=stored.revision,
            ),
        )
    assert read_refused.value.code == "mcp_managed_secret_vault_read_failed"
    assert tuple(vault.reads) == reads_before
    assert host.connections == []

    with pytest.raises(McpManagedServerError) as delete_refused:
        service.remove_secret(
            stored.management_id,
            requirement.requirement_id,
            RemoveMcpManagedSecret(
                request_id="9" * 32,
                expected_revision=stored.revision,
            ),
        )
    assert delete_refused.value.code == "mcp_managed_secret_cleanup_required"
    assert vault.values == {
        expected_reference: "example-owned-vault-canary",
        foreign_reference: "example-foreign-vault-canary",
    }
    assert _secret_requirement(
        service.get(stored.management_id)
    ).configuration_state == "secret_cleanup_required"
    persisted = database.path.read_bytes()
    assert b"example-owned-vault-canary" not in persisted
    assert b"example-foreign-vault-canary" not in persisted


def test_missing_vault_value_fails_closed_without_connection_or_fallback(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient(secret_header=True)),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = _secret_requirement(created.server)
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="a" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("example-stale-vault-canary"),
        ),
    ).server
    vault.values.clear()

    with pytest.raises(McpManagedServerError) as missing:
        service.probe_remote(
            stored.management_id,
            ProbeMcpManagedServer(
                request_id="b" * 32,
                expected_revision=stored.revision,
            ),
        )
    assert missing.value.code == "mcp_managed_secret_vault_read_failed"
    assert host.connections == []
    assert "example-stale-vault-canary" not in str(missing.value)
    assert b"example-stale-vault-canary" not in database.path.read_bytes()


def test_http_missing_secret_value_is_content_free_across_response_logs_and_database(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient(secret_header=True)),
        host=host,
    )
    caplog.set_level("DEBUG")
    created, _ = _create_remote(service)
    requirement = _secret_requirement(created.server)
    canary = "example-http-vault-canary"
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="c" * 32,
            expected_revision=created.server.revision,
            value=SecretStr(canary),
        ),
    ).server
    vault.values.clear()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    response = TestClient(app).post(
        f"{MCP_MANAGED_SERVER_PATH}/{stored.management_id}/probe",
        json={"request_id": "d" * 32, "expected_revision": stored.revision},
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "mcp_managed_secret_vault_read_failed"}
    assert host.connections == []
    assert canary not in response.text
    assert canary not in caplog.text
    assert canary.encode("utf-8") not in database.path.read_bytes()


def test_http_missing_configuration_value_is_content_free_and_never_connects(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "description": "Synthetic tenant scope.",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
        host=host,
    )
    caplog.set_level("DEBUG")
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)
    canary = "example-http-configuration-canary"
    stored = service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="e" * 32,
            expected_revision=created.server.revision,
            value=SecretStr(canary),
        ),
    ).server
    vault.values.clear()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    response = TestClient(app).post(
        f"{MCP_MANAGED_SERVER_PATH}/{stored.management_id}/probe",
        json={"request_id": "f" * 32, "expected_revision": stored.revision},
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "mcp_managed_configuration_vault_read_failed"
    }
    assert host.connections == []
    assert canary not in response.text
    assert canary not in caplog.text
    assert canary.encode("utf-8") not in database.path.read_bytes()


def test_vault_failures_leave_truthful_non_active_states(tmp_path: Path) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(database, vault)
    created, _ = _create(service)
    requirement = _secret_requirement(created.server)
    vault.fail_write = True

    with pytest.raises(McpManagedServerError) as failed:
        service.store_secret(
            created.server.management_id,
            requirement.requirement_id,
            StoreMcpManagedSecret(
                request_id="9" * 32,
                expected_revision=created.server.revision,
                value=SecretStr("example-vault-failure-value"),
            ),
        )
    assert failed.value.code == "mcp_managed_secret_vault_write_failed"
    current = service.get(created.server.management_id)
    assert _secret_requirement(current).configuration_state == "secret_store_failed"
    assert vault.values == {}

    vault.fail_write = False
    recovered = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="9" * 32,
            # The same exact request repairs its reserved transition even
            # though the failure receipt advanced the durable revision.
            expected_revision=created.server.revision,
            value=SecretStr("example-vault-failure-value"),
        ),
    )
    assert recovered.idempotent_replay is True
    assert _secret_requirement(recovered.server).configuration_state == (
        "secret_stored"
    )


def test_vault_cleanup_failure_can_retry_the_same_exact_request(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(database, vault)
    created, _ = _create(service)
    requirement = _secret_requirement(created.server)
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="a" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("example-cleanup-retry-value"),
        ),
    ).server
    command = RemoveMcpManagedSecret(
        request_id="b" * 32,
        expected_revision=stored.revision,
    )
    vault.fail_delete = True

    with pytest.raises(McpManagedServerError) as failed:
        service.remove_secret(
            stored.management_id,
            requirement.requirement_id,
            command,
        )
    assert failed.value.code == "mcp_managed_secret_cleanup_required"
    assert _secret_requirement(service.get(stored.management_id)).configuration_state == (
        "secret_cleanup_required"
    )

    vault.fail_delete = False
    recovered = service.remove_secret(
        stored.management_id,
        requirement.requirement_id,
        command,
    )
    assert recovered.idempotent_replay is True
    assert _secret_requirement(recovered.server).configuration_state == (
        "secret_missing"
    )
    assert vault.values == {}


def test_non_secret_remote_header_is_vault_only_resolved_transiently_and_removed(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "description": "Synthetic tenant scope.",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)
    value = "example-scope-alpha"
    command = StoreMcpManagedConfiguration(
        request_id="c" * 32,
        expected_revision=created.server.revision,
        value=SecretStr(value),
    )

    assert requirement.configuration_state == "value_required"
    assert requirement.secret_vault_provider is None
    assert requirement.value_vault_provider is None
    stored = service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        command,
    )
    stored_requirement = _configuration_requirement(stored.server)
    assert stored_requirement.configuration_state == "value_stored"
    assert stored_requirement.secret_vault_provider is None
    assert stored_requirement.value_vault_provider == "windows_credential_manager"
    assert service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        command,
    ).idempotent_replay is True
    assert value not in stored.model_dump_json()
    assert value.encode("utf-8") not in database.path.read_bytes()

    probed = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="d" * 32,
            expected_revision=stored.server.revision,
        ),
    )
    assert len(host.connections) == 1
    connection = host.connections[0]
    assert tuple(item.name for item in connection.headers) == ("X-Example-Scope",)
    assert connection.headers[0].value.get_secret_value() == value
    assert value not in repr(connection)
    assert value not in probed.model_dump_json()
    assert len(vault.reads) == 1

    restarted = _service(
        database,
        vault,
        ids=["e" * 32],
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "description": "Synthetic tenant scope.",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
        host=_Host(),
    )
    durable = restarted.get(created.server.management_id)
    assert _configuration_requirement(durable).configuration_state == "value_stored"
    removed = restarted.remove_configuration(
        durable.management_id,
        requirement.requirement_id,
        RemoveMcpManagedConfiguration(
            request_id="e" * 32,
            expected_revision=durable.revision,
        ),
    )
    cleared = _configuration_requirement(removed.server)
    assert cleared.configuration_state == "value_required"
    assert cleared.value_vault_provider is None
    assert vault.values == {}


def test_configuration_change_revokes_current_probe_and_exact_tool_admission(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "description": "Synthetic tenant scope.",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
        host=_Host(),
    )
    project = _project(database, project_id="6" * 32, name="Synthetic project")
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)
    configured = service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="a" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("example-scope-alpha"),
        ),
    ).server
    probed = service.probe_remote(
        configured.management_id,
        ProbeMcpManagedServer(
            request_id="b" * 32,
            expected_revision=configured.revision,
        ),
    ).server
    snapshot = service.get_tool_snapshot(configured.management_id)
    admitted = service.set_project_binding(
        configured.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="c" * 32,
            expected_revision=probed.revision,
            enabled=True,
            granted_permissions=probed.required_permissions,
            admitted_tool_ids=tuple(sorted(item.tool_id for item in snapshot.tools)),
        ),
    ).server
    assert admitted.last_probe is not None
    assert admitted.tool_snapshot is not None
    assert admitted.project_bindings[0].admission_state == "admitted"

    removed = service.remove_configuration(
        configured.management_id,
        requirement.requirement_id,
        RemoveMcpManagedConfiguration(
            request_id="d" * 32,
            expected_revision=admitted.revision,
        ),
    ).server

    assert removed.last_probe is None
    assert removed.health_state == "not_checked"
    assert removed.tool_snapshot is None
    assert removed.tool_review_state == "probe_required"
    binding = removed.project_bindings[0]
    assert binding.enabled is True
    assert binding.admission_state == "review_required"
    assert binding.tool_snapshot_id is None
    assert binding.admitted_tool_ids == ()
    assert binding.effective_state == "inactive_tool_review_required"
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_probe_receipts WHERE management_id=?",
            (configured.management_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_tool_snapshots WHERE management_id=?",
            (configured.management_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT snapshot_id FROM mcp_managed_tool_snapshot_state "
            "WHERE management_id=?",
            (configured.management_id,),
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_project_tools WHERE management_id=?",
            (configured.management_id,),
        ).fetchone()[0] == 0

    replaced = service.store_configuration(
        configured.management_id,
        requirement.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="e" * 32,
            expected_revision=removed.revision,
            value=SecretStr("example-scope-beta"),
        ),
    ).server
    assert replaced.last_probe is None
    assert replaced.tool_snapshot is None
    assert replaced.project_bindings[0].admission_state == "review_required"


def test_remote_endpoint_template_is_vault_resolved_https_guarded_and_activatable(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                endpoint="{base_url}/service?synthetic=hidden",
                variables={
                    "base_url": {
                        "description": "Synthetic service origin.",
                        "format": "string",
                        "isRequired": True,
                    }
                },
            )
        ),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(
        created.server,
        location="remote_variable",
    )
    assert created.server.endpoint_state == "template_requires_configuration"
    assert created.server.endpoint_host is None
    assert created.server.secure_transport is None
    assert created.server.probe_action == "unavailable_configuration_required"

    insecure = service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="a" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("http://mcp.example.com"),
        ),
    ).server
    with pytest.raises(McpManagedServerError) as rejected:
        service.probe_remote(
            insecure.management_id,
            ProbeMcpManagedServer(
                request_id="b" * 32,
                expected_revision=insecure.revision,
            ),
        )
    assert rejected.value.code == "mcp_managed_probe_configuration_required"
    assert host.connections == []

    cleared = service.remove_configuration(
        insecure.management_id,
        requirement.requirement_id,
        RemoveMcpManagedConfiguration(
            request_id="c" * 32,
            expected_revision=insecure.revision,
        ),
    ).server
    configured_value = "https://mcp.example.com"
    configured = service.store_configuration(
        cleared.management_id,
        requirement.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="d" * 32,
            expected_revision=cleared.revision,
            value=SecretStr(configured_value),
        ),
    ).server
    assert configured.probe_action == "available_native_confirmation_required"
    assert configured.endpoint_host is None
    probed = service.probe_remote(
        configured.management_id,
        ProbeMcpManagedServer(
            request_id="e" * 32,
            expected_revision=configured.revision,
        ),
    ).server
    assert len(host.connections) == 1
    connection = host.connections[0]
    assert connection.endpoint_host == "mcp.example.com"
    assert connection.endpoint.get_secret_value() == (
        "https://mcp.example.com/service?synthetic=hidden"
    )
    assert configured_value not in repr(connection)
    assert probed.endpoint_host is None

    preview = service.lifecycle_preview(probed.management_id, "install")
    assert preview.availability == "available"
    activated = service.apply_lifecycle(
        probed.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="f" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    assert activated.installation_state == "installed"
    assert activated.installation_kind == "remote_activation"
    assert activated.endpoint_host is None
    rendered = activated.model_dump_json()
    assert configured_value not in rendered
    raw_database = database.path.read_bytes()
    assert configured_value.encode("utf-8") not in raw_database
    assert b"http://mcp.example.com" not in raw_database


@pytest.mark.parametrize(
    ("value_format", "invalid_value"),
    (
        ("boolean", "yes"),
        ("number", "NaN"),
        ("filepath", "relative/example.txt"),
    ),
)
def test_non_secret_configuration_formats_fail_closed_before_vault_write(
    tmp_path: Path,
    value_format: str,
    invalid_value: str,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Configuration",
                    "format": value_format,
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
    )
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)

    with pytest.raises(McpManagedServerError) as rejected:
        service.store_configuration(
            created.server.management_id,
            requirement.requirement_id,
            StoreMcpManagedConfiguration(
                request_id="f" * 32,
                expected_revision=created.server.revision,
                value=SecretStr(invalid_value),
            ),
        )
    assert rejected.value.code == "mcp_managed_configuration_value_invalid"
    assert vault.values == {}
    assert _configuration_requirement(
        service.get(created.server.management_id)
    ).configuration_state == "value_required"
    assert invalid_value.encode("utf-8") not in database.path.read_bytes()


@pytest.mark.parametrize("invalid_value", ("line\rbreak", "line\nbreak", "nul\x00byte"))
def test_non_secret_configuration_command_rejects_control_separators(
    invalid_value: str,
) -> None:
    with pytest.raises(ValueError):
        StoreMcpManagedConfiguration(
            request_id="1" * 32,
            expected_revision=1,
            value=SecretStr(invalid_value),
        )


def test_non_secret_configuration_failures_are_truthful_and_retryable(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
    )
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)
    store = StoreMcpManagedConfiguration(
        request_id="2" * 32,
        expected_revision=created.server.revision,
        value=SecretStr("example-retry-scope"),
    )
    vault.fail_write = True
    with pytest.raises(McpManagedServerError) as write_failed:
        service.store_configuration(
            created.server.management_id,
            requirement.requirement_id,
            store,
        )
    assert write_failed.value.code == "mcp_managed_configuration_vault_write_failed"
    assert _configuration_requirement(
        service.get(created.server.management_id)
    ).configuration_state == "value_store_failed"

    vault.fail_write = False
    stored = service.store_configuration(
        created.server.management_id,
        requirement.requirement_id,
        store,
    )
    assert stored.idempotent_replay is True
    removal = RemoveMcpManagedConfiguration(
        request_id="3" * 32,
        expected_revision=stored.server.revision,
    )
    vault.fail_delete = True
    with pytest.raises(McpManagedServerError) as cleanup_failed:
        service.remove_configuration(
            created.server.management_id,
            requirement.requirement_id,
            removal,
        )
    assert cleanup_failed.value.code == "mcp_managed_configuration_cleanup_required"
    assert _configuration_requirement(
        service.get(created.server.management_id)
    ).configuration_state == "value_cleanup_required"

    vault.fail_delete = False
    recovered = service.remove_configuration(
        created.server.management_id,
        requirement.requirement_id,
        removal,
    )
    assert recovered.idempotent_replay is True
    assert _configuration_requirement(
        recovered.server
    ).configuration_state == "value_required"
    assert vault.values == {}


def test_secret_and_non_secret_configuration_routes_do_not_cross_kinds(
    tmp_path: Path,
) -> None:
    service = _service(
        _database(tmp_path),
        _Vault(),
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                secret_header=True,
                configuration_header={
                    "name": "X-Example-Scope",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                },
            )
        ),
    )
    created, _ = _create_remote(service)
    secret = _secret_requirement(created.server)
    configuration = _configuration_requirement(created.server)

    with pytest.raises(McpManagedServerError) as wrong_secret_route:
        service.store_secret(
            created.server.management_id,
            configuration.requirement_id,
            StoreMcpManagedSecret(
                request_id="4" * 32,
                expected_revision=created.server.revision,
                value=SecretStr("example-secret-route-value"),
            ),
        )
    assert wrong_secret_route.value.code == "mcp_managed_requirement_not_found"
    with pytest.raises(McpManagedServerError) as wrong_configuration_route:
        service.store_configuration(
            created.server.management_id,
            secret.requirement_id,
            StoreMcpManagedConfiguration(
                request_id="5" * 32,
                expected_revision=created.server.revision,
                value=SecretStr("example-ordinary-route-value"),
            ),
        )
    assert wrong_configuration_route.value.code == "mcp_managed_requirement_not_found"


def test_remote_probe_is_durable_content_free_and_idempotent(tmp_path: Path) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    registry = _RemoteRegistryClient()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    assert created.server.probe_action == "available_native_confirmation_required"
    command = ProbeMcpManagedServer(
        request_id="7" * 32,
        expected_revision=created.server.revision,
    )

    receipt = service.probe_remote(created.server.management_id, command)

    assert receipt.idempotent_replay is False
    assert receipt.endpoint_connection_attempted is True
    assert receipt.connection_retained is False
    assert receipt.package_changed is False
    assert receipt.tool_results_requested is False
    assert receipt.tool_authority_granted is False
    assert receipt.probe.tool_count == 2
    assert receipt.server.revision == 2
    assert receipt.server.health_state == "compatible"
    assert receipt.server.last_probe == receipt.probe
    assert receipt.server.last_health_checked_at == T0
    assert len(host.connections) == 1
    assert host.connections[0].endpoint.get_secret_value().endswith(
        "synthetic=hidden"
    )

    replay = service.probe_remote(created.server.management_id, command)
    assert replay.idempotent_replay is True
    assert replay.probe == receipt.probe
    assert len(host.connections) == 1

    restarted = _service(
        database,
        vault,
        catalog=_remote_catalog(registry),
        host=_Host(),
    )
    assert restarted.get(created.server.management_id).last_probe == receipt.probe
    rendered = receipt.model_dump_json()
    for forbidden in (
        "synthetic=hidden",
        "synthetic_lookup",
    ):
        assert forbidden not in rendered


def test_probe_rejects_stale_or_changed_plan_before_network(tmp_path: Path) -> None:
    database = _database(tmp_path)
    registry = _RemoteRegistryClient()
    host = _Host()
    service = _service(
        database,
        _Vault(),
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    with pytest.raises(McpManagedServerError, match="mcp_managed_revision_conflict"):
        service.probe_remote(
            created.server.management_id,
            ProbeMcpManagedServer(request_id="7" * 32, expected_revision=99),
        )
    assert host.connections == []

    registry.detail["server"]["remotes"][0]["url"] = (
        "https://changed.example.com/service"
    )
    with pytest.raises(McpManagedServerError, match="mcp_registry_connection_plan_changed"):
        service.probe_remote(
            created.server.management_id,
            ProbeMcpManagedServer(
                request_id="8" * 32,
                expected_revision=created.server.revision,
            ),
        )
    assert host.connections == []


def test_probe_reads_configured_secret_just_in_time_without_persisting_it(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    registry = _RemoteRegistryClient(secret_header=True)
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = created.server.requirements[0]
    assert created.server.probe_action == "unavailable_configuration_required"
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="7" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("synthetic-probe-secret"),
        ),
    )
    assert stored.server.probe_action == "available_native_confirmation_required"

    receipt = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="8" * 32,
            expected_revision=stored.server.revision,
        ),
    )

    assert len(vault.reads) == 1
    assert host.connections[0].headers[0].name == "Authorization"
    assert (
        host.connections[0].headers[0].value.get_secret_value()
        == "synthetic-probe-secret"
    )
    assert "synthetic-probe-secret" not in receipt.model_dump_json()
    with sqlite3.connect(database.path) as connection:
        persisted = "\n".join(
            str(value)
            for table in (
                "mcp_managed_servers",
                "mcp_managed_requirements",
                "mcp_managed_secret_references",
                "mcp_managed_probe_receipts",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "synthetic-probe-secret" not in persisted


def test_secret_rotation_requires_a_fresh_probe_and_tool_review(tmp_path: Path) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient(secret_header=True)),
        host=_Host(),
    )
    created, _ = _create_remote(service)
    requirement = _secret_requirement(created.server)
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="7" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("synthetic-rotated-secret"),
        ),
    ).server
    probed = service.probe_remote(
        stored.management_id,
        ProbeMcpManagedServer(
            request_id="8" * 32,
            expected_revision=stored.revision,
        ),
    ).server
    assert probed.last_probe is not None
    assert probed.tool_snapshot is not None

    removed = service.remove_secret(
        probed.management_id,
        requirement.requirement_id,
        RemoveMcpManagedSecret(
            request_id="9" * 32,
            expected_revision=probed.revision,
        ),
    ).server

    assert removed.last_probe is None
    assert removed.health_state == "not_checked"
    assert removed.tool_snapshot is None
    assert removed.tool_review_state == "probe_required"
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_probe_receipts WHERE management_id=?",
            (probed.management_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM mcp_managed_tool_snapshots WHERE management_id=?",
            (probed.management_id,),
        ).fetchone()[0] == 1


def test_local_plan_cannot_probe_before_guarded_install(tmp_path: Path) -> None:
    service = _service(_database(tmp_path), _Vault(), host=_Host())
    created, _ = _create(service)
    assert created.server.probe_action == "unavailable_install_required"
    with pytest.raises(McpManagedServerError, match="mcp_managed_probe_install_required"):
        service.probe_remote(
            created.server.management_id,
            ProbeMcpManagedServer(
                request_id="7" * 32,
                expected_revision=created.server.revision,
            ),
        )


def _compatible_remote_service(
    tmp_path: Path,
) -> tuple[
    McpManagedServerService,
    _RemoteRegistryClient,
    _Host,
    McpManagedServer,
]:
    database = _database(tmp_path)
    registry = _RemoteRegistryClient()
    host = _Host()
    service = _service(
        database,
        _Vault(),
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    checked = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    ).server
    return service, registry, host, checked


def test_remote_install_preview_is_revision_bound_and_requires_compatibility(
    tmp_path: Path,
) -> None:
    service = _service(
        _database(tmp_path),
        _Vault(),
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=_Host(),
    )
    created, _ = _create_remote(service)
    unavailable = service.lifecycle_preview(created.server.management_id, "install")
    assert unavailable.availability == "unavailable"
    assert unavailable.reason == "compatibility_check_required"
    assert unavailable.effects == (
        "persist_remote_activation",
        "no_package_change",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )

    checked = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    ).server
    available = service.lifecycle_preview(checked.management_id, "install")
    assert available.availability == "available"
    assert available.reason == "ready_for_native_confirmation"
    assert available.expected_revision == checked.revision
    assert available.preview_digest != unavailable.preview_digest

    with pytest.raises(
        McpManagedServerError,
        match="mcp_managed_lifecycle_preview_conflict",
    ):
        service.apply_remote_lifecycle(
            checked.management_id,
            "install",
            ApplyMcpManagedLifecycle(
                request_id="8" * 32,
                expected_revision=checked.revision,
                preview_digest=unavailable.preview_digest,
            ),
        )
    assert service.get(checked.management_id).installation_state == "not_installed"


def test_remote_activation_is_durable_idempotent_and_effect_free(
    tmp_path: Path,
) -> None:
    service, registry, host, checked = _compatible_remote_service(tmp_path)
    preview = service.lifecycle_preview(checked.management_id, "install")
    command = ApplyMcpManagedLifecycle(
        request_id="8" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    receipt = service.apply_remote_lifecycle(checked.management_id, "install", command)

    assert receipt.action == "install"
    assert receipt.idempotent_replay is False
    assert receipt.package_changed is False
    assert receipt.process_started is False
    assert receipt.endpoint_connected is False
    assert receipt.connection_retained is False
    assert receipt.persistent_host_started is False
    assert receipt.tool_authority_granted is False
    assert receipt.server.lifecycle_state == "installed"
    assert receipt.server.installation_state == "installed"
    assert receipt.server.installation_kind == "remote_activation"
    assert receipt.server.operation_state == "idle"
    assert receipt.server.installed_plan_revision == receipt.server.plan_revision
    assert receipt.server.installed_at == T0
    assert receipt.server.process_tree_cleanup == "not_applicable"
    assert receipt.server.install_action == "not_applicable_already_installed"
    assert receipt.server.uninstall_action == "available_native_confirmation_required"
    # The lifecycle re-fetches exact Registry material but does not run another
    # host probe or retain an endpoint connection.
    assert len(host.connections) == 1

    replay = service.apply_remote_lifecycle(checked.management_id, "install", command)
    assert replay.idempotent_replay is True
    assert replay.server == receipt.server
    assert len(host.connections) == 1

    restarted = _service(
        service._repository._database,  # type: ignore[attr-defined]
        _Vault(),
        catalog=_remote_catalog(registry),
        host=_Host(),
    )
    assert restarted.get(checked.management_id) == receipt.server
    rendered = receipt.model_dump_json()
    assert "synthetic=hidden" not in rendered
    assert "synthetic_lookup" not in rendered
    with sqlite3.connect(service._repository._database.path) as connection:  # type: ignore[attr-defined]
        persisted = "\n".join(
            str(value)
            for table in (
                "mcp_managed_lifecycle_state",
                "mcp_managed_lifecycle_receipts",
            )
            for row in connection.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "synthetic=hidden" not in persisted
    assert "mcp.example.com/service" not in persisted


def test_remote_host_connection_is_transient_exact_and_never_opened(
    tmp_path: Path,
) -> None:
    service, registry, host, checked = _compatible_remote_service(tmp_path)
    with pytest.raises(
        McpManagedServerError,
        match="mcp_managed_host_install_required",
    ):
        service.resolve_transient_host_connection(
            checked.management_id,
            expected_revision=checked.revision,
        )
    assert len(host.connections) == 1

    preview = service.lifecycle_preview(checked.management_id, "install")
    installed = service.apply_remote_lifecycle(
        checked.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    connection = service.resolve_transient_host_connection(
        installed.management_id,
        expected_revision=installed.revision,
    )

    assert connection.management_id == installed.management_id
    assert connection.plan_revision == installed.plan_revision
    assert connection.endpoint_host == "mcp.example.com"
    assert connection.endpoint.get_secret_value().endswith("synthetic=hidden")
    assert connection.headers == ()
    assert "synthetic=hidden" not in repr(connection)
    assert "synthetic=hidden" not in connection.model_dump_json()
    assert len(host.connections) == 1

    registry.detail["server"]["remotes"][0]["url"] = (
        "https://changed.example.com/service"
    )
    with pytest.raises(
        McpManagedServerError,
        match="mcp_registry_connection_plan_changed",
    ):
        service.resolve_transient_host_connection(
            installed.management_id,
            expected_revision=installed.revision,
        )
    assert len(host.connections) == 1

    with pytest.raises(
        McpManagedServerError,
        match="mcp_managed_revision_conflict",
    ):
        service.resolve_transient_host_connection(
            installed.management_id,
            expected_revision=installed.revision - 1,
        )
    assert len(host.connections) == 1


def test_remote_host_binding_is_exact_content_free_and_opens_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=host,
    )
    project = _project(
        database,
        project_id="2" * 32,
        name="Synthetic project",
    )
    created, _ = _create_remote(service)
    checked = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    ).server
    checked_snapshot = service.get_tool_snapshot(checked.management_id)
    with pytest.raises(McpManagedServerError) as not_installed:
        service.resolve_host_binding(
            checked.management_id,
            project.project_id,
            expected_server_revision=checked.revision,
            expected_project_binding_revision=1,
            expected_tool_snapshot_id=checked_snapshot.snapshot_id,
        )
    assert not_installed.value.code == "mcp_managed_host_install_required"
    preview = service.lifecycle_preview(checked.management_id, "install")
    installed = service.apply_remote_lifecycle(
        checked.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    snapshot = service.get_tool_snapshot(installed.management_id)
    admitted_tool_ids = tuple(sorted(item.tool_id for item in snapshot.tools))
    bound = service.set_project_binding(
        installed.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="3" * 32,
            expected_revision=installed.revision,
            enabled=True,
            granted_permissions=installed.required_permissions,
            admitted_tool_ids=admitted_tool_ids,
        ),
    ).server
    durable_binding = bound.project_bindings[0]
    host_connections_before = len(host.connections)
    vault_reads_before = len(vault.reads)

    resolved = service.resolve_host_binding(
        bound.management_id,
        project.project_id,
        expected_server_revision=bound.revision,
        expected_project_binding_revision=durable_binding.revision,
        expected_tool_snapshot_id=snapshot.snapshot_id,
    )
    start_preview = service.resolve_host_start_preview(
        bound.management_id,
        project.project_id,
        expected_server_revision=bound.revision,
        expected_project_binding_revision=durable_binding.revision,
        expected_tool_snapshot_id=snapshot.snapshot_id,
    )

    assert resolved.management_id == bound.management_id
    assert resolved.project_id == project.project_id
    assert resolved.server_revision == bound.revision
    assert resolved.project_binding_revision == durable_binding.revision
    assert resolved.plan_revision == bound.plan_revision
    assert resolved.option_kind == "remote_server"
    assert resolved.transport == "streamable-http"
    assert resolved.tool_snapshot_id == snapshot.snapshot_id
    assert resolved.tool_schema_digest == snapshot.schema_digest
    assert resolved.reviewed_tool_count == snapshot.tool_count
    assert resolved.admitted_tool_ids == admitted_tool_ids
    assert resolved.granted_permissions == bound.required_permissions
    assert resolved.tool_calls_available is True
    assert resolved.tool_routing_state == "project_scoped_fresh_approval"
    assert start_preview.binding == resolved
    assert start_preview.preview_starts_host is False
    assert start_preview.native_confirmation_required is True
    assert start_preview.tool_calls_available is True
    assert start_preview.execution_kind == "reviewed_remote_connection"
    assert len(start_preview.preview_digest) == 64
    rendered = resolved.model_dump_json()
    assert "mcp.example.com" not in rendered
    assert "endpoint" not in rendered
    assert "credential" not in rendered
    assert len(host.connections) == host_connections_before
    assert len(vault.reads) == vault_reads_before

    original_get_server = service._repository.get_server
    server_reads = 0

    def drift_after_first_read(management_id: str):  # noqa: ANN202
        nonlocal server_reads
        server_reads += 1
        current = original_get_server(management_id)
        if server_reads == 2 and current is not None:
            return current.model_copy(update={"revision": current.revision + 1})
        return current

    monkeypatch.setattr(
        service._repository,
        "get_server",
        drift_after_first_read,
    )
    with pytest.raises(McpManagedServerError) as raced:
        service.resolve_host_binding(
            bound.management_id,
            project.project_id,
            expected_server_revision=bound.revision,
            expected_project_binding_revision=durable_binding.revision,
            expected_tool_snapshot_id=snapshot.snapshot_id,
        )
    assert raced.value.code == "mcp_managed_revision_conflict"
    assert len(host.connections) == host_connections_before
    assert len(vault.reads) == vault_reads_before


def test_host_binding_refuses_cross_project_and_stale_authority(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    host = _Host()
    service = _service(
        database,
        _Vault(),
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=host,
    )
    project = _project(
        database,
        project_id="2" * 32,
        name="Synthetic project",
    )
    other = _project(
        database,
        project_id="3" * 32,
        name="Other synthetic project",
    )
    created, _ = _create_remote(service)
    checked = service.probe_remote(
        created.server.management_id,
        ProbeMcpManagedServer(
            request_id="7" * 32,
            expected_revision=created.server.revision,
        ),
    ).server
    preview = service.lifecycle_preview(checked.management_id, "install")
    installed = service.apply_remote_lifecycle(
        checked.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    snapshot = service.get_tool_snapshot(installed.management_id)
    bound = service.set_project_binding(
        installed.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="4" * 32,
            expected_revision=installed.revision,
            enabled=True,
            granted_permissions=installed.required_permissions,
            admitted_tool_ids=tuple(sorted(item.tool_id for item in snapshot.tools)),
        ),
    ).server
    durable_binding = bound.project_bindings[0]
    calls_before = len(host.connections)

    cases = (
        (
            other.project_id,
            bound.revision,
            durable_binding.revision,
            snapshot.snapshot_id,
            "mcp_managed_host_project_not_admitted",
        ),
        (
            project.project_id,
            bound.revision - 1,
            durable_binding.revision,
            snapshot.snapshot_id,
            "mcp_managed_revision_conflict",
        ),
        (
            project.project_id,
            bound.revision,
            durable_binding.revision + 1,
            snapshot.snapshot_id,
            "mcp_managed_host_project_binding_conflict",
        ),
        (
            project.project_id,
            bound.revision,
            True,
            snapshot.snapshot_id,
            "mcp_managed_host_project_binding_conflict",
        ),
        (
            project.project_id,
            bound.revision,
            durable_binding.revision,
            "f" * 32,
            "mcp_managed_host_tool_snapshot_conflict",
        ),
    )
    for project_id, server_revision, binding_revision, snapshot_id, code in cases:
        with pytest.raises(McpManagedServerError) as failure:
            service.resolve_host_binding(
                bound.management_id,
                project_id,
                expected_server_revision=server_revision,
                expected_project_binding_revision=binding_revision,
                expected_tool_snapshot_id=snapshot_id,
            )
        assert failure.value.code == code

    disabled = service.set_project_binding(
        bound.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="5" * 32,
            expected_revision=bound.revision,
            enabled=False,
            granted_permissions=(),
        ),
    ).server
    disabled_binding = disabled.project_bindings[0]
    with pytest.raises(McpManagedServerError) as not_admitted:
        service.resolve_host_binding(
            disabled.management_id,
            project.project_id,
            expected_server_revision=disabled.revision,
            expected_project_binding_revision=disabled_binding.revision,
            expected_tool_snapshot_id=snapshot.snapshot_id,
        )
    assert not_admitted.value.code == "mcp_managed_host_project_not_admitted"
    assert len(host.connections) == calls_before


def test_local_host_binding_does_not_derive_or_start_installed_package(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(_McpbRegistryClient()),
        installer=installer,
    )
    project = _project(
        database,
        project_id="2" * 32,
        name="Synthetic project",
    )
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    snapshot = service.get_tool_snapshot(installed.management_id)
    bound = service.set_project_binding(
        installed.management_id,
        project.project_id,
        SetMcpManagedProjectBinding(
            request_id="8" * 32,
            expected_revision=installed.revision,
            enabled=True,
            granted_permissions=installed.required_permissions,
            admitted_tool_ids=tuple(sorted(item.tool_id for item in snapshot.tools)),
        ),
    ).server
    durable_binding = bound.project_bindings[0]

    resolved = service.resolve_host_binding(
        bound.management_id,
        project.project_id,
        expected_server_revision=bound.revision,
        expected_project_binding_revision=durable_binding.revision,
        expected_tool_snapshot_id=snapshot.snapshot_id,
    )

    assert resolved.option_kind == "local_package"
    assert resolved.transport == "stdio"
    assert resolved.granted_permissions == bound.required_permissions
    assert installer.connection_resolutions == []
    assert installer.installs == [(bound.management_id, "b" * 64)]


def test_remote_host_connection_reads_secret_just_in_time_without_persistence(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    vault = _Vault()
    registry = _RemoteRegistryClient(secret_header=True)
    host = _Host()
    service = _service(
        database,
        vault,
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    requirement = created.server.requirements[0]
    stored = service.store_secret(
        created.server.management_id,
        requirement.requirement_id,
        StoreMcpManagedSecret(
            request_id="7" * 32,
            expected_revision=created.server.revision,
            value=SecretStr("synthetic-host-secret"),
        ),
    ).server
    checked = service.probe_remote(
        stored.management_id,
        ProbeMcpManagedServer(
            request_id="8" * 32,
            expected_revision=stored.revision,
        ),
    ).server
    preview = service.lifecycle_preview(checked.management_id, "install")
    installed = service.apply_remote_lifecycle(
        checked.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="9" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    reads_before = len(vault.reads)

    connection = service.resolve_transient_host_connection(
        installed.management_id,
        expected_revision=installed.revision,
    )

    assert len(vault.reads) == reads_before + 1
    assert connection.headers[0].name == "Authorization"
    assert (
        connection.headers[0].value.get_secret_value()
        == "synthetic-host-secret"
    )
    assert "synthetic-host-secret" not in repr(connection)
    assert "synthetic-host-secret" not in connection.model_dump_json()
    assert len(host.connections) == 1
    with sqlite3.connect(database.path) as sqlite:
        persisted = "\n".join(
            str(value)
            for table in (
                "mcp_managed_servers",
                "mcp_managed_requirements",
                "mcp_managed_secret_references",
                "mcp_managed_lifecycle_receipts",
            )
            for row in sqlite.execute(f"SELECT * FROM {table}").fetchall()
            for value in row
        )
    assert "synthetic-host-secret" not in persisted


def test_remote_activation_revalidates_hidden_material_before_commit(
    tmp_path: Path,
) -> None:
    service, registry, host, checked = _compatible_remote_service(tmp_path)
    preview = service.lifecycle_preview(checked.management_id, "install")
    registry.detail["server"]["remotes"][0]["url"] = (
        "https://mcp.example.com/changed-path?synthetic=changed"
    )

    with pytest.raises(
        McpManagedServerError,
        match="mcp_registry_connection_plan_changed",
    ):
        service.apply_remote_lifecycle(
            checked.management_id,
            "install",
            ApplyMcpManagedLifecycle(
                request_id="8" * 32,
                expected_revision=checked.revision,
                preview_digest=preview.preview_digest,
            ),
        )

    current = service.get(checked.management_id)
    assert current.installation_state == "not_installed"
    assert current.revision == checked.revision
    assert len(host.connections) == 1


def test_remote_uninstall_removes_only_activation_and_is_restart_safe(
    tmp_path: Path,
) -> None:
    service, registry, host, checked = _compatible_remote_service(tmp_path)
    install_preview = service.lifecycle_preview(checked.management_id, "install")
    installed = service.apply_remote_lifecycle(
        checked.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.lifecycle_preview(installed.management_id, "uninstall")
    assert preview.availability == "available"
    assert preview.effects[0] == "remove_remote_activation"
    command = ApplyMcpManagedLifecycle(
        request_id="9" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    receipt = service.apply_remote_lifecycle(installed.management_id, "uninstall", command)

    assert receipt.action == "uninstall"
    assert receipt.server.lifecycle_state == "planned"
    assert receipt.server.installation_state == "not_installed"
    assert receipt.server.installation_kind == "none"
    assert receipt.server.installed_plan_revision is None
    assert receipt.server.installed_at is None
    assert receipt.server.last_probe is not None
    assert receipt.server.project_bindings == installed.project_bindings
    assert len(host.connections) == 1
    replay = service.apply_remote_lifecycle(installed.management_id, "uninstall", command)
    assert replay.idempotent_replay is True

    restarted = _service(
        service._repository._database,  # type: ignore[attr-defined]
        _Vault(),
        catalog=_remote_catalog(registry),
        host=_Host(),
    )
    assert restarted.get(installed.management_id) == receipt.server


def test_non_mcpb_local_lifecycle_stays_truthfully_unsupported(
    tmp_path: Path,
) -> None:
    service = _service(_database(tmp_path), _Vault(), host=_Host())
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    assert preview.installation_kind == "local_package"
    assert preview.availability == "unavailable"
    assert preview.reason == "package_registry_not_supported"
    assert preview.effects[0] == "download_exact_package"
    assert "persist_remote_activation" not in preview.effects
    with pytest.raises(
        McpManagedServerError,
        match="mcp_managed_install_package_registry_not_supported",
    ):
        service.apply_remote_lifecycle(
            created.server.management_id,
            "install",
            ApplyMcpManagedLifecycle(
                request_id="7" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )
    assert service.get(created.server.management_id).installation_state == (
        "not_installed"
    )


def test_mcpb_install_is_exact_durable_idempotent_and_retains_no_host(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    assert created.server.install_action == "available_native_confirmation_required"
    preview = service.lifecycle_preview(created.server.management_id, "install")
    assert preview.availability == "available"
    assert preview.effects == (
        "download_exact_package",
        "verify_artifact_sha256",
        "stage_isolated_package",
        "execute_bounded_compatibility_probe",
        "stop_and_verify_process_tree",
        "publish_verified_package",
        "no_connection_retained",
        "no_tool_authority",
    )
    command = ApplyMcpManagedLifecycle(
        request_id="7" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    receipt = service.apply_lifecycle(
        created.server.management_id,
        "install",
        command,
    )

    installed = receipt.server
    assert receipt.package_changed is True
    assert receipt.process_started is True
    assert receipt.process_tree_cleanup == "verified"
    assert receipt.connection_retained is False
    assert receipt.persistent_host_started is False
    assert receipt.tool_authority_granted is False
    assert installed.installation_state == "installed"
    assert installed.installation_kind == "local_package"
    assert installed.host_state == "not_started"
    assert installed.health_state == "compatible"
    assert installed.tool_routing_state == "inactive"
    assert installed.process_tree_cleanup == "verified"
    assert installed.local_package_evidence is not None
    assert installed.local_package_evidence.artifact_sha256 == "b" * 64
    assert installed.local_package_evidence.tree_digest == "c" * 64
    assert installed.tool_snapshot is not None
    assert (
        installed.tool_snapshot.source_tree_digest
        == installed.local_package_evidence.tree_digest
    )
    assert (
        installed.tool_snapshot.source_manifest_digest
        == installed.local_package_evidence.manifest_digest
    )
    assert installed.last_probe is not None
    assert installed.last_probe.process_started is True
    assert installed.last_probe.tool_count == 3
    assert installed.probe_action == "not_applicable_verified_during_install"
    assert installed.uninstall_action == "available_native_confirmation_required"
    assert installer.installs == [(installed.management_id, "b" * 64)]

    mismatched_snapshot = installed.model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    mismatched_snapshot["tool_snapshot"]["source_manifest_digest"] = "0" * 64
    with pytest.raises(
        ValueError,
        match="local tool snapshot does not match the package",
    ):
        McpManagedServer.model_validate(mismatched_snapshot)

    wrong_snapshot_source = installed.model_dump(
        mode="python",
        exclude_computed_fields=True,
    )
    wrong_snapshot_source["tool_snapshot"].update(
        source="remote_probe",
        source_tree_digest=None,
        source_manifest_digest=None,
    )
    with pytest.raises(
        ValueError,
        match="remote tool snapshot does not match the plan",
    ):
        McpManagedServer.model_validate(wrong_snapshot_source)

    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    assert restarted.get(installed.management_id) == installed
    replay = restarted.apply_lifecycle(installed.management_id, "install", command)
    assert replay.idempotent_replay is True
    assert replay.package_changed is True
    assert installer.installs == [(installed.management_id, "b" * 64)]

    with sqlite3.connect(database.path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM mcp_managed_local_packages WHERE management_id=?",
            (installed.management_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "installed"
        assert row["process_tree_cleanup"] == "verified"
        assert not any(
            token in key
            for key in row.keys()
            for token in ("path", "command", "argument", "environment", "tool_name")
        )


def test_mcpb_manifest_configuration_requires_nonexecuting_inspection_and_vault_values(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    vault = _Vault()
    installer = _LocalInstaller()
    installer.inspection_requirements = (
        McpLocalPackageUserConfigurationRequirement(
            requirement_id="4" * 32,
            key="WORKSPACE",
            location="package_argument",
            required=True,
            secret=False,
            format="filepath",
            user_value_needed=True,
            default_declared=False,
        ),
        McpLocalPackageUserConfigurationRequirement(
            requirement_id="5" * 32,
            key="ACCESS_TOKEN",
            location="environment_variable",
            required=True,
            secret=True,
            format="string",
            user_value_needed=True,
            default_declared=False,
        ),
        McpLocalPackageUserConfigurationRequirement(
            requirement_id="6" * 32,
            key="RETRY_LIMIT",
            location="environment_variable",
            required=False,
            secret=False,
            format="number",
            user_value_needed=False,
            default_declared=True,
        ),
    )
    service = _service(
        database,
        vault,
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service, inspect_local=False)
    record = created.server
    assert record.install_action == "unavailable_configuration_inspection_required"

    preview = service.local_configuration_inspection_preview(record.management_id)
    assert preview.availability == "available"
    assert preview.effects[-4:] == (
        "no_configuration_values_persisted",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )
    command = InspectMcpManagedLocalConfiguration(
        request_id="2" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )
    receipt = service.inspect_local_configuration(record.management_id, command)

    inspected = receipt.server
    assert receipt.process_started is False
    assert receipt.archive_retained is False
    assert receipt.configuration_values_persisted is False
    assert receipt.inspection.requirement_ids == ("4" * 32, "5" * 32, "6" * 32)
    assert inspected.local_configuration_inspection == receipt.inspection
    assert inspected.required_permissions == (
        "process_spawn",
        "filesystem_read",
        "credential_use",
    )
    assert "filesystem_input_declared" in inspected.risks
    assert "credential_input_declared" in inspected.risks
    assert inspected.install_action == "unavailable_configuration_required"
    assert installer.inspections[0][1].execution_configuration_state == (
        "inspection_only"
    )
    replay = service.inspect_local_configuration(record.management_id, command)
    assert replay.idempotent_replay is True
    assert len(installer.inspections) == 1

    workspace = next(
        item for item in inspected.requirements if item.name == "WORKSPACE"
    )
    token = next(
        item for item in inspected.requirements if item.name == "ACCESS_TOKEN"
    )
    workspace_value = "X:\\example\\mcpb-workspace"
    token_value = "synthetic-mcpb-inspection-token"
    configured = service.store_configuration(
        inspected.management_id,
        workspace.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="3" * 32,
            expected_revision=inspected.revision,
            value=SecretStr(workspace_value),
        ),
    ).server
    configured = service.store_secret(
        inspected.management_id,
        token.requirement_id,
        StoreMcpManagedSecret(
            request_id="4" * 32,
            expected_revision=configured.revision,
            value=SecretStr(token_value),
        ),
    ).server
    assert configured.install_action == "available_native_confirmation_required"

    install_preview = service.lifecycle_preview(configured.management_id, "install")
    installed = service.apply_lifecycle(
        configured.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    resolved_values = installer.install_user_configurations[-1]
    assert set(resolved_values) == {"WORKSPACE", "ACCESS_TOKEN"}
    assert resolved_values["WORKSPACE"].get_secret_value() == workspace_value
    assert resolved_values["ACCESS_TOKEN"].get_secret_value() == token_value
    assert installer.install_packages[-1].execution_configuration_state == "resolved"
    assert token_value not in installed.model_dump_json()
    assert workspace_value not in installed.model_dump_json()

    service.resolve_transient_host_connection(
        installed.management_id,
        expected_revision=installed.revision,
    )
    restarted_values = installer.connection_user_configurations[-1]
    assert restarted_values["WORKSPACE"].get_secret_value() == workspace_value
    assert restarted_values["ACCESS_TOKEN"].get_secret_value() == token_value
    with sqlite3.connect(database.path) as connection:
        durable_sql = "\n".join(connection.iterdump())
        row = connection.execute(
            "SELECT * FROM mcp_managed_local_configuration_inspections "
            "WHERE management_id=? AND current_state=1",
            (installed.management_id,),
        ).fetchone()
    assert row is not None
    assert token_value not in durable_sql
    assert workspace_value not in durable_sql


def test_configured_mcpb_install_and_start_resolve_vault_values_transiently(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    package = registry.detail["server"]["packages"][0]
    package["packageArguments"] = [
        {
            "type": "named",
            "name": "--workspace",
            "format": "filepath",
            "isRequired": True,
        }
    ]
    package["environmentVariables"] = [
        {
            "name": "EXAMPLE_TOKEN",
            "isRequired": True,
            "isSecret": True,
        }
    ]
    vault = _Vault()
    installer = _LocalInstaller()
    service = _service(
        database,
        vault,
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    workspace = next(
        item for item in created.server.requirements if item.name == "--workspace"
    )
    credential = next(
        item for item in created.server.requirements if item.name == "EXAMPLE_TOKEN"
    )
    workspace_value = "X:\\example\\configured-workspace"
    credential_value = "synthetic-configured-token"
    assert created.server.install_action == "unavailable_configuration_required"
    configured = service.store_configuration(
        created.server.management_id,
        workspace.requirement_id,
        StoreMcpManagedConfiguration(
            request_id="2" * 32,
            expected_revision=created.server.revision,
            value=SecretStr(workspace_value),
        ),
    ).server
    configured = service.store_secret(
        configured.management_id,
        credential.requirement_id,
        StoreMcpManagedSecret(
            request_id="3" * 32,
            expected_revision=configured.revision,
            value=SecretStr(credential_value),
        ),
    ).server
    preview = service.lifecycle_preview(configured.management_id, "install")
    assert preview.availability == "available"

    installed = service.apply_lifecycle(
        configured.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="4" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server

    resolved_install = installer.install_packages[0]
    assert tuple(
        item.get_secret_value() for item in resolved_install.package_arguments
    ) == (f"--workspace={workspace_value}",)
    assert resolved_install.environment[0].name == "EXAMPLE_TOKEN"
    assert (
        resolved_install.environment[0].value.get_secret_value()
        == credential_value
    )
    for private_value in (workspace_value, credential_value):
        assert private_value not in repr(resolved_install)
        assert private_value not in resolved_install.model_dump_json()
        assert private_value.encode("utf-8") not in database.path.read_bytes()

    service.resolve_transient_host_connection(
        installed.management_id,
        expected_revision=installed.revision,
    )
    start_configuration = installer.connection_configurations[-1]
    assert start_configuration is not None
    assert tuple(
        item.get_secret_value() for item in start_configuration.package_arguments
    ) == (f"--workspace={workspace_value}",)
    assert (
        start_configuration.environment[0].value.get_secret_value()
        == credential_value
    )
    assert len(vault.reads) == 4


def test_local_host_connection_binds_exact_installed_evidence_without_start(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    assert installed.local_package_evidence is not None

    connection = service.resolve_transient_host_connection(
        installed.management_id,
        expected_revision=installed.revision,
    )

    assert connection.management_id == installed.management_id
    assert connection.arguments == ("--mode", "synthetic")
    assert connection.environment == {"EXAMPLE_MODE": "synthetic"}
    assert "X:\\example" not in repr(connection)
    assert installer.connection_resolutions == [
        (
            installed.management_id,
            McpLocalPackageLaunchExpectation(
                tree_digest=installed.local_package_evidence.tree_digest,
                manifest_digest=installed.local_package_evidence.manifest_digest,
                manifest_version=installed.local_package_evidence.manifest_version,
                runtime_kind=installed.local_package_evidence.runtime_kind,
                runtime_version=installed.local_package_evidence.runtime_version,
            ),
        )
    ]
    with pytest.raises(
        McpManagedServerError,
        match="mcp_managed_revision_conflict",
    ):
        service.resolve_transient_host_connection(
            installed.management_id,
            expected_revision=installed.revision - 1,
        )
    assert len(installer.connection_resolutions) == 1

    installer.connection_resolution_failure = McpLocalPackageInstallerError(
        "mcp_package_installed_tree_changed",
        cleanup_required=True,
    )
    with pytest.raises(
        McpManagedServerError,
        match="mcp_package_installed_tree_changed",
    ):
        service.resolve_transient_host_connection(
            installed.management_id,
            expected_revision=installed.revision,
        )
    assert len(installer.connection_resolutions) == 2


def test_mcpb_update_preview_binds_the_official_latest_exact_target(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id,
        "install",
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server

    preview = service.local_update_preview(installed.management_id)

    assert preview.availability == "available"
    assert preview.reason == "ready_for_native_confirmation"
    assert preview.current_version == "1.2.3"
    assert preview.current_plan_revision == installed.plan_revision
    assert preview.target_version == "2.0.0"
    assert preview.target_catalog_id is not None
    assert preview.target_option_id is not None
    assert preview.target_plan_revision is not None
    assert preview.target_plan_revision != installed.plan_revision
    assert preview.effects == (
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
    assert registry.calls.count((installed.server_name, "latest")) == 1
    assert registry.calls.count((installed.server_name, "2.0.0")) == 2


def test_mcpb_update_preview_reports_already_latest_without_guessing_versions(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    registry.latest = registry.current
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id,
        "install",
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server

    preview = service.local_update_preview(installed.management_id)

    assert preview.availability == "unavailable"
    assert preview.reason == "already_latest"
    assert preview.target_version == installed.server_version
    assert preview.target_catalog_id is None
    assert preview.target_option_id is None
    assert preview.target_plan_revision is None
    assert registry.calls.count((installed.server_name, "latest")) == 1


def test_mcpb_update_preview_refuses_ambiguous_latest_package_selection(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    alternative = copy.deepcopy(registry.latest["server"]["packages"][0])
    alternative["identifier"] = (
        "https://github.com/example/synthetic-files/releases/download/"
        "v2.0.0/synthetic-files-alternative.mcpb"
    )
    alternative["fileSha256"] = "a" * 64
    registry.latest["server"]["packages"].append(alternative)
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id,
        "install",
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server

    preview = service.local_update_preview(installed.management_id)

    assert preview.availability == "unavailable"
    assert preview.reason == "target_option_ambiguous"
    assert preview.target_version == "2.0.0"
    assert preview.target_catalog_id is None
    assert preview.target_option_id is None
    assert preview.target_plan_revision is None


def test_mcpb_update_is_atomic_durable_idempotent_and_retains_one_generation(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)
    command = ApplyMcpManagedLocalUpdate(
        request_id="8" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    receipt = service.apply_local_update(installed.management_id, command)

    updated = receipt.server
    assert receipt.idempotent_replay is False
    assert receipt.package_changed is True
    assert receipt.process_started is True
    assert receipt.process_tree_cleanup == "verified"
    assert receipt.rollback_generation_retained is True
    assert receipt.endpoint_connected is False
    assert receipt.connection_retained is False
    assert receipt.persistent_host_started is False
    assert receipt.tool_authority_granted is False
    assert updated.server_version == "2.0.0"
    assert updated.plan_revision == preview.target_plan_revision
    assert updated.revision == installed.revision + 1
    assert updated.operation_state == "idle"
    assert updated.installed_plan_revision == updated.plan_revision
    assert updated.local_package_evidence is not None
    assert updated.local_package_evidence.artifact_sha256 == "f" * 64
    assert updated.local_package_evidence.tree_digest == "8" * 64
    assert updated.last_probe is not None
    assert updated.last_probe.request_id == command.request_id
    assert updated.last_probe.tool_count == 4
    generation = updated.rollback_generation
    assert generation is not None
    assert generation.generation_id == command.request_id
    assert generation.server_version == installed.server_version
    assert generation.plan_revision == installed.plan_revision
    assert generation.local_package_evidence == installed.local_package_evidence
    assert generation.probe == installed.last_probe
    assert generation.required_permissions == updated.required_permissions
    assert installer.update_stages == [
        (
            installed.management_id,
            command.request_id,
            "c" * 64,
            "f" * 64,
        )
    ]
    assert installer.update_publications == [
        (
            installed.management_id,
            command.request_id,
            "c" * 64,
            "8" * 64,
        )
    ]
    assert installer.update_publication_rollbacks == []

    blocked = service.local_update_preview(updated.management_id)
    assert blocked.availability == "unavailable"
    assert blocked.reason == "rollback_cleanup_required"

    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    assert restarted.get(updated.management_id) == updated
    replay = restarted.apply_local_update(updated.management_id, command)
    assert replay.idempotent_replay is True
    assert replay.server == updated
    assert len(installer.update_stages) == 1
    assert len(installer.update_publications) == 1

    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_operations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_update_payloads"
        ).fetchone()[0] == 0
        generation_row = connection.execute(
            "SELECT plan_revision,tree_digest FROM "
            "mcp_managed_local_rollback_generations WHERE management_id=?",
            (updated.management_id,),
        ).fetchone()
        assert generation_row == (installed.plan_revision, "c" * 64)


def test_mcpb_update_journal_accepts_bounded_reviewed_tools_above_legacy_limit(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    installer.update_tool_count = 9
    installer.update_tool_description = "x" * 4_096
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id,
        "install",
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)

    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server

    assert updated.last_probe is not None
    assert updated.last_probe.tool_count == 9
    snapshot = service.get_tool_snapshot(updated.management_id)
    assert snapshot.tool_count == 9
    assert len(snapshot.tools) == 9


def test_mcpb_update_compensates_a_database_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)
    command = ApplyMcpManagedLocalUpdate(
        request_id="8" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    def fail_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise McpManagedServerError("mcp_managed_storage_unavailable")

    monkeypatch.setattr(service._repository, "finish_local_update", fail_commit)
    with pytest.raises(
        McpManagedServerError, match="mcp_managed_storage_unavailable"
    ):
        service.apply_local_update(installed.management_id, command)

    assert service.get(installed.management_id) == installed
    assert installer.update_publication_rollbacks == [
        (
            installed.management_id,
            command.request_id,
            "c" * 64,
            "8" * 64,
        )
    ]
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_operations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_rollback_generations"
        ).fetchone()[0] == 0


def test_mcpb_update_stage_failure_preserves_the_current_generation(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    installer.update_stage_failure = McpLocalPackageInstallerError(
        "mcp_package_integrity_mismatch",
        process_tree_cleanup="not_applicable",
    )
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)

    with pytest.raises(
        McpManagedServerError, match="mcp_package_integrity_mismatch"
    ):
        service.apply_local_update(
            installed.management_id,
            ApplyMcpManagedLocalUpdate(
                request_id="8" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )

    assert service.get(installed.management_id) == installed
    assert installer.update_publications == []
    assert installer.update_publication_rollbacks == []
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_operations"
        ).fetchone()[0] == 0


def test_mcpb_rollback_is_reversible_and_retained_generation_cleanup_is_explicit(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)
    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=update_preview.expected_revision,
            preview_digest=update_preview.preview_digest,
        ),
    ).server

    rollback_preview = service.local_rollback_preview(updated.management_id)
    assert rollback_preview.availability == "available"
    assert rollback_preview.current_version == "2.0.0"
    assert rollback_preview.target_version == "1.2.3"
    assert rollback_preview.effects == (
        "verify_current_tree_digest",
        "verify_rollback_tree_digest",
        "atomically_swap_verified_generations",
        "retain_superseded_current_generation",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )
    rollback_command = ApplyMcpManagedLocalRollback(
        request_id="9" * 32,
        expected_revision=rollback_preview.expected_revision,
        preview_digest=rollback_preview.preview_digest,
    )
    receipt = service.apply_local_rollback(
        updated.management_id,
        rollback_command,
    )

    rolled_back = receipt.server
    assert receipt.idempotent_replay is False
    assert receipt.process_started is False
    assert receipt.process_tree_cleanup == "not_applicable"
    assert receipt.rollback_generation_retained is True
    assert rolled_back.server_version == "1.2.3"
    assert rolled_back.plan_revision == installed.plan_revision
    assert rolled_back.local_package_evidence == installed.local_package_evidence
    assert rolled_back.last_probe == installed.last_probe
    assert rolled_back.rollback_generation is not None
    assert rolled_back.rollback_generation.generation_id == rollback_command.request_id
    assert rolled_back.rollback_generation.server_version == "2.0.0"
    assert (
        rolled_back.rollback_generation.local_package_evidence
        == updated.local_package_evidence
    )
    assert installer.rollback_swaps == [
        (
            updated.management_id,
            rollback_command.request_id,
            "8" * 64,
            "c" * 64,
        )
    ]
    replay = service.apply_local_rollback(
        updated.management_id,
        rollback_command,
    )
    assert replay.idempotent_replay is True
    assert replay.server == rolled_back
    assert len(installer.rollback_swaps) == 1

    cleanup_preview = service.local_rollback_cleanup_preview(
        rolled_back.management_id
    )
    assert cleanup_preview.availability == "available"
    assert cleanup_preview.rollback_version == "2.0.0"
    assert cleanup_preview.effects[-3:] == (
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )
    cleanup_command = ApplyMcpManagedLocalRollbackCleanup(
        request_id="a" * 32,
        expected_revision=cleanup_preview.expected_revision,
        preview_digest=cleanup_preview.preview_digest,
    )
    cleanup = service.cleanup_local_rollback_generation(
        rolled_back.management_id,
        cleanup_command,
    )
    assert cleanup.idempotent_replay is False
    assert cleanup.filesystem_changed is True
    assert cleanup.process_started is False
    assert cleanup.server.rollback_generation is None
    assert cleanup.server.server_version == "1.2.3"
    assert installer.rollback_cleanups == [
        (rolled_back.management_id, cleanup_command.request_id, "8" * 64)
    ]
    cleanup_replay = service.cleanup_local_rollback_generation(
        rolled_back.management_id,
        cleanup_command,
    )
    assert cleanup_replay.idempotent_replay is True
    assert cleanup_replay.filesystem_changed is False
    assert len(installer.rollback_cleanups) == 1
    next_update = service.local_update_preview(cleanup.server.management_id)
    assert next_update.availability == "available"


def test_mcpb_rollback_compensates_a_database_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)
    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=update_preview.expected_revision,
            preview_digest=update_preview.preview_digest,
        ),
    ).server
    preview = service.local_rollback_preview(updated.management_id)
    command = ApplyMcpManagedLocalRollback(
        request_id="9" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    def fail_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise McpManagedServerError("mcp_managed_storage_unavailable")

    monkeypatch.setattr(service._repository, "finish_local_rollback", fail_commit)
    with pytest.raises(
        McpManagedServerError, match="mcp_managed_storage_unavailable"
    ):
        service.apply_local_rollback(updated.management_id, command)

    assert service.get(updated.management_id) == updated
    assert installer.rollback_swaps == [
        (updated.management_id, command.request_id, "8" * 64, "c" * 64),
        (updated.management_id, command.request_id, "c" * 64, "8" * 64),
    ]
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM mcp_managed_local_operations"
        ).fetchone()[0] == 0


def test_interrupted_update_recovery_restores_the_durable_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    installer.update_rollback_succeeds = False
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)

    def fail_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise McpManagedServerError("mcp_managed_storage_unavailable")

    monkeypatch.setattr(service._repository, "finish_local_update", fail_commit)
    with pytest.raises(
        McpManagedServerError, match="mcp_managed_storage_unavailable"
    ):
        service.apply_local_update(
            installed.management_id,
            ApplyMcpManagedLocalUpdate(
                request_id="8" * 32,
                expected_revision=update_preview.expected_revision,
                preview_digest=update_preview.preview_digest,
            ),
        )

    interrupted = service.get(installed.management_id)
    assert interrupted.installation_state == "cleanup_required"
    assert interrupted.operation_state == "cleanup_required"
    assert interrupted.process_tree_cleanup == "verified"
    recovery_preview = service.local_operation_recovery_preview(
        interrupted.management_id
    )
    assert recovery_preview.availability == "available"
    assert recovery_preview.interrupted_action == "update"
    assert recovery_preview.effects[1:3] == (
        "restore_durable_current_generation",
        "discard_verified_staged_target",
    )

    installer.update_rollback_succeeds = True
    recovery_command = ApplyMcpManagedLocalOperationRecovery(
        request_id="a" * 32,
        expected_revision=recovery_preview.expected_revision,
        preview_digest=recovery_preview.preview_digest,
    )
    recovered = service.recover_local_operation(
        interrupted.management_id,
        recovery_command,
    )
    assert recovered.recovered_action == "update"
    assert recovered.filesystem_state_verified is True
    assert recovered.process_started is False
    assert recovered.server.installation_state == "installed"
    assert recovered.server.server_version == installed.server_version
    assert recovered.server.plan_revision == installed.plan_revision
    assert recovered.server.local_package_evidence == installed.local_package_evidence
    assert recovered.server.rollback_generation is None
    replay = service.recover_local_operation(
        interrupted.management_id,
        recovery_command,
    )
    assert replay.idempotent_replay is True


def test_interrupted_rollback_recovery_keeps_both_durable_generations(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)
    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=update_preview.expected_revision,
            preview_digest=update_preview.preview_digest,
        ),
    ).server
    rollback_preview = service.local_rollback_preview(updated.management_id)
    installer.rollback_swap_succeeds = False
    with pytest.raises(
        McpManagedServerError, match="mcp_package_rollback_swap_unconfirmed"
    ):
        service.apply_local_rollback(
            updated.management_id,
            ApplyMcpManagedLocalRollback(
                request_id="9" * 32,
                expected_revision=rollback_preview.expected_revision,
                preview_digest=rollback_preview.preview_digest,
            ),
        )

    interrupted = service.get(updated.management_id)
    recovery_preview = service.local_operation_recovery_preview(
        interrupted.management_id
    )
    assert recovery_preview.availability == "available"
    assert recovery_preview.interrupted_action == "rollback"
    installer.rollback_swap_succeeds = True
    recovered = service.recover_local_operation(
        interrupted.management_id,
        ApplyMcpManagedLocalOperationRecovery(
            request_id="a" * 32,
            expected_revision=recovery_preview.expected_revision,
            preview_digest=recovery_preview.preview_digest,
        ),
    ).server
    assert recovered.server_version == updated.server_version
    assert recovered.local_package_evidence == updated.local_package_evidence
    assert recovered.rollback_generation == updated.rollback_generation
    assert recovered.installation_state == "installed"


def test_interrupted_rollback_cleanup_recovery_finishes_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)
    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=update_preview.expected_revision,
            preview_digest=update_preview.preview_digest,
        ),
    ).server
    cleanup_preview = service.local_rollback_cleanup_preview(
        updated.management_id
    )

    def fail_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise McpManagedServerError("mcp_managed_storage_unavailable")

    monkeypatch.setattr(
        service._repository,
        "finish_local_rollback_cleanup",
        fail_commit,
    )
    with pytest.raises(
        McpManagedServerError, match="mcp_managed_storage_unavailable"
    ):
        service.cleanup_local_rollback_generation(
            updated.management_id,
            ApplyMcpManagedLocalRollbackCleanup(
                request_id="9" * 32,
                expected_revision=cleanup_preview.expected_revision,
                preview_digest=cleanup_preview.preview_digest,
            ),
        )

    interrupted = service.get(updated.management_id)
    recovery_preview = service.local_operation_recovery_preview(
        interrupted.management_id
    )
    assert recovery_preview.availability == "available"
    assert recovery_preview.interrupted_action == "cleanup"
    installer.rollback_cleanup_changed = False
    recovered = service.recover_local_operation(
        interrupted.management_id,
        ApplyMcpManagedLocalOperationRecovery(
            request_id="a" * 32,
            expected_revision=recovery_preview.expected_revision,
            preview_digest=recovery_preview.preview_digest,
        ),
    ).server
    assert recovered.installation_state == "installed"
    assert recovered.server_version == updated.server_version
    assert recovered.rollback_generation is None


def test_restart_reconciles_a_prepublished_update_for_explicit_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)

    def interrupt_publication(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "publish_update", interrupt_publication)
    with pytest.raises(KeyboardInterrupt):
        service.apply_local_update(
            installed.management_id,
            ApplyMcpManagedLocalUpdate(
                request_id="8" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )

    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    interrupted = restarted.get(installed.management_id)
    assert interrupted.installation_state == "cleanup_required"
    assert interrupted.process_tree_cleanup == "verified"
    recovery_preview = restarted.local_operation_recovery_preview(
        interrupted.management_id
    )
    assert recovery_preview.availability == "available"
    assert recovery_preview.interrupted_action == "update"
    recovered = restarted.recover_local_operation(
        interrupted.management_id,
        ApplyMcpManagedLocalOperationRecovery(
            request_id="a" * 32,
            expected_revision=recovery_preview.expected_revision,
            preview_digest=recovery_preview.preview_digest,
        ),
    ).server
    assert recovered.installation_state == "installed"
    assert recovered.plan_revision == installed.plan_revision


def test_restart_refuses_to_claim_process_cleanup_for_an_unstaged_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.local_update_preview(installed.management_id)

    def interrupt_staging(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(installer, "stage_update", interrupt_staging)
    with pytest.raises(KeyboardInterrupt):
        service.apply_local_update(
            installed.management_id,
            ApplyMcpManagedLocalUpdate(
                request_id="8" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )
    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    interrupted = restarted.get(installed.management_id)
    assert interrupted.process_tree_cleanup == "unconfirmed"
    recovery = restarted.local_operation_recovery_preview(
        interrupted.management_id
    )
    assert recovery.availability == "unavailable"
    assert recovery.reason == "process_cleanup_unconfirmed"


def test_mcpb_uninstall_is_digest_bound_durable_idempotent_and_process_free(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.lifecycle_preview(installed.management_id, "uninstall")
    assert preview.availability == "available"
    assert preview.effects == (
        "verify_installed_tree_digest",
        "quarantine_verified_package",
        "remove_quarantined_package",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )
    command = ApplyMcpManagedLifecycle(
        request_id="8" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )

    receipt = service.apply_lifecycle(installed.management_id, "uninstall", command)

    assert receipt.contract_version == "mcp-managed-lifecycle-receipt.v2"
    assert receipt.installation_kind == "local_package"
    assert receipt.package_changed is True
    assert receipt.process_started is False
    assert receipt.process_tree_cleanup == "not_applicable"
    assert receipt.connection_retained is False
    assert receipt.tool_authority_granted is False
    assert receipt.server.installation_state == "not_installed"
    assert receipt.server.installation_kind == "none"
    assert receipt.server.local_package_evidence is None
    assert installer.uninstalls == [
        (installed.management_id, command.request_id, "c" * 64)
    ]
    assert installer.uninstall_commits == [
        (installed.management_id, command.request_id, "c" * 64)
    ]

    replay = service.apply_lifecycle(installed.management_id, "uninstall", command)
    assert replay.idempotent_replay is True
    assert replay == receipt.model_copy(update={"idempotent_replay": True})
    assert len(installer.uninstalls) == 1
    assert len(installer.uninstall_commits) == 1
    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    assert restarted.get(installed.management_id) == receipt.server
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT 1 FROM mcp_managed_local_packages WHERE management_id=?",
            (installed.management_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM mcp_managed_local_operations WHERE management_id=?",
            (installed.management_id,),
        ).fetchone() is None


def test_mcpb_uninstall_failure_is_retryable_or_quarantined_explicitly(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.lifecycle_preview(installed.management_id, "uninstall")
    installer.uninstall_failure = McpLocalPackageInstallerError(
        "mcp_package_uninstall_quarantine_failed"
    )
    with pytest.raises(
        McpManagedServerError, match="mcp_package_uninstall_quarantine_failed"
    ):
        service.apply_lifecycle(
            installed.management_id,
            "uninstall",
            ApplyMcpManagedLifecycle(
                request_id="8" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )
    retryable = service.get(installed.management_id)
    assert retryable.installation_state == "installed"
    assert retryable.operation_state == "idle"
    assert retryable.revision == installed.revision

    installer.uninstall_failure = None
    installer.uninstall_commit_succeeds = False
    retry_preview = service.lifecycle_preview(installed.management_id, "uninstall")
    with pytest.raises(
        McpManagedServerError, match="mcp_package_uninstall_cleanup_unconfirmed"
    ):
        service.apply_lifecycle(
            installed.management_id,
            "uninstall",
            ApplyMcpManagedLifecycle(
                request_id="9" * 32,
                expected_revision=retry_preview.expected_revision,
                preview_digest=retry_preview.preview_digest,
            ),
        )
    quarantined = service.get(installed.management_id)
    assert quarantined.installation_state == "cleanup_required"
    assert quarantined.operation_state == "cleanup_required"
    assert quarantined.local_package_evidence is not None
    assert quarantined.local_package_evidence.tree_digest == "c" * 64
    assert quarantined.revision == installed.revision + 1
    assert quarantined.uninstall_action == "unavailable_cleanup_required"
    with sqlite3.connect(database.path) as connection:
        row = connection.execute(
            "SELECT action,status,error_code FROM mcp_managed_local_operations "
            "WHERE management_id=?",
            (installed.management_id,),
        ).fetchone()
        assert row == (
            "uninstall",
            "cleanup_required",
            "mcp_package_uninstall_cleanup_unconfirmed",
        )


def test_mcpb_uninstall_interruption_reconciles_to_cleanup_required(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    preview = service.lifecycle_preview(installed.management_id, "uninstall")
    command = ApplyMcpManagedLifecycle(
        request_id="8" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )
    repository = service._repository  # type: ignore[attr-defined]
    pending = repository.begin_local_uninstall(
        installed.management_id,
        command=command,
        request_fingerprint="f" * 64,
        expected_tree_digest="c" * 64,
        updated_at=datetime(2040, 1, 1, tzinfo=UTC),
    )
    assert pending.installation_state == "installed"
    assert pending.operation_state == "uninstalling"

    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    reconciled = restarted.get(installed.management_id)
    assert reconciled.installation_state == "cleanup_required"
    assert reconciled.operation_state == "cleanup_required"
    assert reconciled.local_package_evidence is not None
    assert reconciled.process_tree_cleanup == "verified"
    assert reconciled.revision == installed.revision + 1
    with sqlite3.connect(database.path) as connection:
        row = connection.execute(
            "SELECT status,error_code FROM mcp_managed_local_operations "
            "WHERE management_id=?",
            (installed.management_id,),
        ).fetchone()
        assert row == (
            "cleanup_required",
            "mcp_package_operation_interrupted",
        )


def test_interrupted_local_uninstall_has_explicit_idempotent_cleanup(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    uninstall_preview = service.lifecycle_preview(
        installed.management_id, "uninstall"
    )
    operation_command = ApplyMcpManagedLifecycle(
        request_id="8" * 32,
        expected_revision=uninstall_preview.expected_revision,
        preview_digest=uninstall_preview.preview_digest,
    )
    service._repository.begin_local_uninstall(  # type: ignore[attr-defined]
        installed.management_id,
        command=operation_command,
        request_fingerprint="f" * 64,
        expected_tree_digest="c" * 64,
        updated_at=datetime(2040, 1, 1, tzinfo=UTC),
    )
    recovered_service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )

    preview = recovered_service.local_cleanup_preview(installed.management_id)
    assert preview.availability == "available"
    assert preview.reason == "ready_for_native_confirmation"
    assert preview.effects == (
        "verify_operation_journal",
        "verify_installed_or_quarantined_tree_digest",
        "finish_quarantined_removal",
        "clear_cleanup_state",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    )
    command = ApplyMcpManagedLocalCleanup(
        request_id="9" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )
    receipt = recovered_service.complete_local_uninstall_cleanup(
        installed.management_id,
        command,
    )

    assert receipt.contract_version == "mcp-managed-local-cleanup-receipt.v1"
    assert receipt.package_presence == "absent"
    assert receipt.filesystem_changed is True
    assert receipt.process_started is False
    assert receipt.connection_retained is False
    assert receipt.tool_authority_granted is False
    assert receipt.server.installation_state == "not_installed"
    assert receipt.server.operation_state == "idle"
    assert receipt.server.local_package_evidence is None
    assert installer.recoveries == [
        (installed.management_id, operation_command.request_id, "c" * 64)
    ]

    replay = recovered_service.complete_local_uninstall_cleanup(
        installed.management_id,
        command,
    )
    assert replay.idempotent_replay is True
    assert replay.filesystem_changed is False
    assert len(installer.recoveries) == 1
    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    assert restarted.get(installed.management_id) == receipt.server
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT 1 FROM mcp_managed_local_operations WHERE management_id=?",
            (installed.management_id,),
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM mcp_managed_local_packages WHERE management_id=?",
            (installed.management_id,),
        ).fetchone() is None


def test_interrupted_local_uninstall_cleanup_failure_remains_retryable(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    uninstall_preview = service.lifecycle_preview(
        installed.management_id, "uninstall"
    )
    service._repository.begin_local_uninstall(  # type: ignore[attr-defined]
        installed.management_id,
        command=ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=uninstall_preview.expected_revision,
            preview_digest=uninstall_preview.preview_digest,
        ),
        request_fingerprint="f" * 64,
        expected_tree_digest="c" * 64,
        updated_at=datetime(2040, 1, 1, tzinfo=UTC),
    )
    recovered_service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    preview = recovered_service.local_cleanup_preview(installed.management_id)
    command = ApplyMcpManagedLocalCleanup(
        request_id="9" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )
    installer.recovery_failure = McpLocalPackageInstallerError(
        "mcp_package_installed_tree_changed",
        cleanup_required=True,
    )

    with pytest.raises(
        McpManagedServerError,
        match="mcp_package_installed_tree_changed",
    ):
        recovered_service.complete_local_uninstall_cleanup(
            installed.management_id,
            command,
        )

    still_quarantined = recovered_service.get(installed.management_id)
    assert still_quarantined.installation_state == "cleanup_required"
    assert still_quarantined.operation_state == "cleanup_required"
    installer.recovery_failure = None
    installer.recovery_filesystem_changed = False
    receipt = recovered_service.complete_local_uninstall_cleanup(
        installed.management_id,
        command,
    )
    assert receipt.filesystem_changed is False
    assert receipt.server.installation_state == "not_installed"


def test_mcpb_failed_install_rolls_back_operation_or_marks_cleanup(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    installer.failure = McpLocalPackageInstallerError(
        "mcp_package_integrity_mismatch"
    )
    with pytest.raises(McpManagedServerError, match="mcp_package_integrity_mismatch"):
        service.apply_lifecycle(
            created.server.management_id,
            "install",
            ApplyMcpManagedLifecycle(
                request_id="7" * 32,
                expected_revision=preview.expected_revision,
                preview_digest=preview.preview_digest,
            ),
        )
    clean = service.get(created.server.management_id)
    assert clean.installation_state == "not_installed"
    assert clean.operation_state == "idle"

    next_preview = service.lifecycle_preview(created.server.management_id, "install")
    installer.failure = McpLocalPackageInstallerError(
        "mcp_host_cleanup_unconfirmed",
        cleanup_required=True,
        process_tree_cleanup="unconfirmed",
    )
    with pytest.raises(McpManagedServerError, match="mcp_host_cleanup_unconfirmed"):
        service.apply_lifecycle(
            created.server.management_id,
            "install",
            ApplyMcpManagedLifecycle(
                request_id="8" * 32,
                expected_revision=next_preview.expected_revision,
                preview_digest=next_preview.preview_digest,
            ),
        )
    uncertain = service.get(created.server.management_id)
    assert uncertain.installation_state == "cleanup_required"
    assert uncertain.operation_state == "cleanup_required"
    assert uncertain.process_tree_cleanup == "unconfirmed"
    assert uncertain.install_action == "unavailable_cleanup_required"


def test_mcpb_install_interrupted_before_commit_reconciles_on_restart(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    command = ApplyMcpManagedLifecycle(
        request_id="7" * 32,
        expected_revision=preview.expected_revision,
        preview_digest=preview.preview_digest,
    )
    repository = service._repository  # type: ignore[attr-defined]
    staged = repository.begin_local_install(
        created.server.management_id,
        command=command,
        request_fingerprint="8" * 64,
        updated_at=datetime(2040, 1, 1, tzinfo=UTC),
    )
    assert staged.operation_state == "installing"
    assert staged.installation_state == "not_installed"

    restarted = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    reconciled = restarted.get(created.server.management_id)
    assert reconciled.revision == created.server.revision + 1
    assert reconciled.lifecycle_state == "cleanup_required"
    assert reconciled.installation_state == "cleanup_required"
    assert reconciled.installation_kind == "local_package"
    assert reconciled.operation_state == "cleanup_required"
    assert reconciled.process_tree_cleanup == "unconfirmed"
    assert reconciled.install_action == "unavailable_cleanup_required"
    assert reconciled.uninstall_action == "unavailable_cleanup_required"
    blocked = restarted.lifecycle_preview(reconciled.management_id, "install")
    assert blocked.availability == "unavailable"
    assert blocked.reason == "cleanup_required"
    assert installer.installs == []
    with sqlite3.connect(database.path) as connection:
        row = connection.execute(
            "SELECT status,error_code FROM mcp_managed_local_packages "
            "WHERE management_id=?",
            (reconciled.management_id,),
        ).fetchone()
        assert row == ("cleanup_required", "mcp_package_install_interrupted")


def test_response_models_reject_incoherent_or_duplicate_management_state(
    tmp_path: Path,
) -> None:
    service = _service(_database(tmp_path), _Vault())
    created, _ = _create(service)
    payload = created.server.model_dump(mode="json")
    payload["endpoint_state"] = "fixed_host"
    payload["endpoint_host"] = "mcp.example.com"
    payload["secure_transport"] = True
    with pytest.raises(ValueError):
        McpManagedServer.model_validate(payload)

    with pytest.raises(ValueError):
        McpManagedServerList(
            servers=(created.server, created.server),
            total=2,
            secret_vault=service.list().secret_vault,
        )
    with pytest.raises(ValueError):
        McpManagedServerList(
            servers=(created.server,),
            total=0,
            secret_vault=service.list().secret_vault,
        )


def test_windows_vault_adapter_addresses_only_the_exact_opaque_target() -> None:
    class _SyntheticCredentialApi:
        def __init__(self) -> None:
            self.write_target: str | None = None
            self.write_blob: bytes | None = None
            self.delete_target: str | None = None

        def CredWriteW(self, pointer, flags: int) -> int:
            import ctypes

            assert flags == 0
            credential = pointer._obj
            self.write_target = credential.TargetName
            self.write_blob = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return 1

        def CredDeleteW(self, target: str, credential_type: int, flags: int) -> int:
            assert credential_type == 1
            assert flags == 0
            self.delete_target = target
            return 1

    reference_id = "c" * 32
    value = "example-adapter-vault-value"
    api = _SyntheticCredentialApi()
    vault = WindowsCredentialManagerMcpSecretVault()
    vault._api = api  # type: ignore[assignment]

    vault.write(reference_id, SecretStr(value))
    assert api.write_target == f"PromptEnhancer/MCP/{reference_id}"
    assert api.write_blob == value.encode("utf-8")
    vault.delete(reference_id)
    assert api.delete_target == f"PromptEnhancer/MCP/{reference_id}"

    with pytest.raises(McpManagedServerError) as invalid:
        vault.write("invalid-reference", SecretStr(value))
    assert invalid.value.code == "mcp_managed_secret_reference_invalid"


def test_http_management_is_private_authenticated_and_native_confirmed(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    service = _service(database, _Vault())
    server, review, option = _review(service)
    app = FastAPI()
    confirmations: list[bool] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append(True)

    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    http = TestClient(app)
    payload = {
        "request_id": "a" * 32,
        "catalog_id": server.catalog_id,
        "name": server.name,
        "version": server.version,
        "option_id": option.option_id,
        "plan_revision": review.plan_revision,
    }
    assert http.get(MCP_MANAGED_SERVER_PATH).status_code == 401
    denied = http.post(
        MCP_MANAGED_SERVER_PATH,
        json=payload,
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert denied.status_code == 403
    response = http.post(
        MCP_MANAGED_SERVER_PATH,
        json=payload,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["process_started"] is False
    assert confirmations == [True]
    listing = http.get(
        MCP_MANAGED_SERVER_PATH,
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "no-store, private"
    assert listing.json()["total"] == 1


def test_http_local_configuration_inspection_is_private_non_executing_and_confirmed(
    tmp_path: Path,
) -> None:
    installer = _LocalInstaller()
    installer.inspection_requirements = (
        McpLocalPackageUserConfigurationRequirement(
            requirement_id="4" * 32,
            key="WORKSPACE",
            location="package_argument",
            required=True,
            secret=False,
            format="filepath",
            user_value_needed=True,
            default_declared=False,
        ),
    )
    service = _service(
        _database(tmp_path),
        _Vault(),
        catalog=_mcpb_catalog(_McpbRegistryClient()),
        installer=installer,
    )
    created, _option = _create(service, inspect_local=False)
    confirmations: list[str] = []

    class _Runtime:
        def __init__(self) -> None:
            self.revocations: list[tuple[str, str]] = []

        def revoke_server_hosts(
            self,
            management_id: str,
            *,
            request_id: str,
        ) -> None:
            self.revocations.append((management_id, request_id))

    runtime = _Runtime()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append("confirmed")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
            runtime,  # type: ignore[arg-type]
        )
    )
    http = TestClient(app)
    base = f"{MCP_MANAGED_SERVER_PATH}/{created.server.management_id}"
    preview_path = f"{base}/configuration-inspection-preview"
    mutation_path = f"{base}/configuration-inspection"

    assert http.get(preview_path).status_code == 401
    preview_response = http.get(
        preview_path,
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["cache-control"] == "no-store, private"
    preview = preview_response.json()
    assert preview["availability"] == "available"
    assert preview["effects"][-4:] == [
        "no_configuration_values_persisted",
        "no_process_start",
        "no_connection_retained",
        "no_tool_authority",
    ]
    assert installer.inspections == []

    body = {
        "request_id": "a" * 32,
        "expected_revision": preview["expected_revision"],
        "preview_digest": preview["preview_digest"],
    }
    assert http.post(mutation_path, json=body).status_code == 401
    assert http.post(
        mutation_path,
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    assert installer.inspections == []
    assert runtime.revocations == []

    inspected = http.post(
        mutation_path,
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert inspected.status_code == 200
    assert inspected.headers["cache-control"] == "no-store, private"
    payload = inspected.json()
    assert payload["archive_retained"] is False
    assert payload["process_started"] is False
    assert payload["connection_retained"] is False
    assert payload["configuration_values_persisted"] is False
    assert payload["inspection"]["manifest_content_persisted"] is False
    assert payload["inspection"]["requirement_ids"] == ["4" * 32]
    assert '"value":' not in json.dumps(payload)
    assert len(installer.inspections) == 1
    assert installer.inspections[0][1].execution_configuration_state == (
        "inspection_only"
    )
    assert runtime.revocations == [(created.server.management_id, "a" * 32)]
    assert confirmations == ["confirmed"]


def test_http_non_secret_configuration_is_confirmed_private_and_revokes_hosts(
    tmp_path: Path,
) -> None:
    vault = _Vault()
    service = _service(
        _database(tmp_path),
        vault,
        catalog=_remote_catalog(
            _RemoteRegistryClient(
                configuration_header={
                    "name": "X-Example-Scope",
                    "format": "string",
                    "isRequired": True,
                    "isSecret": False,
                }
            )
        ),
    )
    created, _ = _create_remote(service)
    requirement = _configuration_requirement(created.server)
    confirmations: list[str] = []

    class _Runtime:
        def __init__(self) -> None:
            self.revocations: list[tuple[str, str]] = []

        def revoke_server_hosts(
            self,
            management_id: str,
            *,
            request_id: str,
        ) -> None:
            self.revocations.append((management_id, request_id))

    runtime = _Runtime()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append("confirmed")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
            runtime,  # type: ignore[arg-type]
        )
    )
    http = TestClient(app)
    base = (
        f"{MCP_MANAGED_SERVER_PATH}/{created.server.management_id}"
        f"/configuration/{requirement.requirement_id}"
    )
    value = "example-http-scope"
    body = {
        "request_id": "a" * 32,
        "expected_revision": created.server.revision,
        "value": value,
    }
    assert http.post(base, json=body).status_code == 401
    assert http.post(
        base,
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    assert runtime.revocations == []

    stored = http.post(
        base,
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert stored.status_code == 200
    assert stored.headers["cache-control"] == "no-store, private"
    assert value not in stored.text
    stored_payload = stored.json()
    stored_requirement = next(
        item
        for item in stored_payload["server"]["requirements"]
        if item["requirement_id"] == requirement.requirement_id
    )
    assert stored_requirement["configuration_state"] == "value_stored"
    assert stored_requirement["secret_vault_provider"] is None
    assert stored_requirement["value_vault_provider"] == (
        "windows_credential_manager"
    )
    assert runtime.revocations == [
        (created.server.management_id, "a" * 32)
    ]

    removal = http.post(
        f"{base}/remove",
        json={
            "request_id": "b" * 32,
            "expected_revision": stored_payload["server"]["revision"],
        },
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert removal.status_code == 200
    assert value not in removal.text
    removed_requirement = next(
        item
        for item in removal.json()["server"]["requirements"]
        if item["requirement_id"] == requirement.requirement_id
    )
    assert removed_requirement["configuration_state"] == "value_required"
    assert removed_requirement["value_vault_provider"] is None
    assert runtime.revocations == [
        (created.server.management_id, "a" * 32),
        (created.server.management_id, "b" * 32),
    ]
    assert confirmations == ["confirmed", "confirmed"]
    assert vault.values == {}


def test_http_probe_requires_native_confirmation_and_returns_closed_receipt(
    tmp_path: Path,
) -> None:
    registry = _RemoteRegistryClient()
    host = _Host()
    service = _service(
        _database(tmp_path),
        _Vault(),
        catalog=_remote_catalog(registry),
        host=host,
    )
    created, _ = _create_remote(service)
    confirmations: list[bool] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append(True)

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    http = TestClient(app)
    path = f"{MCP_MANAGED_SERVER_PATH}/{created.server.management_id}/probe"
    body = {"request_id": "7" * 32, "expected_revision": 1}
    assert http.post(path, json=body).status_code == 401
    assert http.post(
        path,
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    response = http.post(
        path,
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["endpoint_connection_attempted"] is True
    assert response.json()["connection_retained"] is False
    assert response.json()["probe"]["tool_results_requested"] is False
    assert response.json()["probe"]["tool_names_persisted"] is True
    tools_path = f"{MCP_MANAGED_SERVER_PATH}/{created.server.management_id}/tools"
    assert http.get(tools_path).status_code == 401
    tools = http.get(
        tools_path,
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert tools.status_code == 200
    assert tools.headers["cache-control"] == "no-store, private"
    assert tools.json()["contract_version"] == "mcp-managed-tool-snapshot.v1"
    assert tools.json()["management_id"] == created.server.management_id
    assert [item["name"] for item in tools.json()["tools"]] == [
        "synthetic_tool_1",
        "synthetic_tool_2",
    ]
    assert tools.json()["tools"][0]["input_schema"]["type"] == "object"
    assert tools.json()["connection_retained"] is False
    assert tools.json()["tool_authority_granted"] is False
    assert confirmations == [True]
    assert len(host.connections) == 1


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("mcp_host_endpoint_not_public", 503),
        ("mcp_host_redirect_refused", 503),
        ("mcp_host_tls_policy_invalid", 503),
        ("mcp_host_headers_too_large", 503),
        ("mcp_host_headers_invalid", 503),
        ("mcp_host_content_encoding_unsupported", 503),
        ("mcp_host_response_too_large", 503),
        ("mcp_host_sse_event_count_exceeded", 503),
        ("mcp_host_process_output_limit", 503),
        ("mcp_host_visible_window_detected", 503),
        ("mcp_host_process_visibility_unconfirmed", 503),
        ("mcp_host_deadline_exceeded", 503),
        ("mcp_host_protocol_unsupported", 422),
        ("mcp_host_tool_identity_conflict", 422),
        ("mcp_host_tool_schema_recursive", 422),
        ("mcp_host_tool_schema_keyword_unsupported", 422),
        ("mcp_host_tool_schema_pattern_unsafe", 422),
    ],
)
def test_http_probe_returns_only_safe_remote_refusal_code(
    tmp_path: Path,
    code: str,
    expected_status: int,
) -> None:
    host = _RefusingRemoteHost(code)
    service = _service(
        _database(tmp_path),
        _Vault(),
        catalog=_remote_catalog(_RemoteRegistryClient()),
        host=host,
    )
    created, _ = _create_remote(service)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    response = TestClient(app).post(
        f"{MCP_MANAGED_SERVER_PATH}/{created.server.management_id}/probe",
        json={"request_id": "9" * 32, "expected_revision": 1},
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": code}
    assert "synthetic=hidden" not in response.text
    assert len(host.connections) == 1


def test_http_remote_lifecycle_has_private_preview_and_confirmed_mutations(
    tmp_path: Path,
) -> None:
    service, _registry, host, checked = _compatible_remote_service(tmp_path)
    confirmations: list[str] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append("confirmed")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    http = TestClient(app)
    base = f"{MCP_MANAGED_SERVER_PATH}/{checked.management_id}"
    assert http.get(f"{base}/install-preview").status_code == 401
    preview_response = http.get(
        f"{base}/install-preview",
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["cache-control"] == "no-store, private"
    preview = preview_response.json()
    assert preview["availability"] == "available"
    assert preview["effects"][0] == "persist_remote_activation"
    body = {
        "request_id": "8" * 32,
        "expected_revision": preview["expected_revision"],
        "preview_digest": preview["preview_digest"],
    }
    assert http.post(
        f"{base}/install",
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    installed = http.post(
        f"{base}/install",
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert installed.status_code == 200
    assert installed.headers["cache-control"] == "no-store, private"
    assert installed.json()["server"]["installation_state"] == "installed"
    assert installed.json()["endpoint_connected"] is False
    assert installed.json()["tool_authority_granted"] is False

    uninstall_preview = http.get(
        f"{base}/uninstall-preview",
        headers={"Authorization": "Bearer example-local-token"},
    ).json()
    removed = http.post(
        f"{base}/uninstall",
        json={
            "request_id": "9" * 32,
            "expected_revision": uninstall_preview["expected_revision"],
            "preview_digest": uninstall_preview["preview_digest"],
        },
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert removed.status_code == 200
    assert removed.json()["server"]["installation_state"] == "not_installed"
    assert confirmations == ["confirmed", "confirmed"]
    assert len(host.connections) == 1


def test_http_local_update_preview_is_private_read_only_and_exact(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id,
        "install",
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    confirmations: list[bool] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append(True)

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    http = TestClient(app)
    path = f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/update-preview"

    assert http.get(path).status_code == 401
    response = http.get(
        path,
        headers={"Authorization": "Bearer example-local-token"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    payload = response.json()
    assert payload["action"] == "update"
    assert payload["current_version"] == "1.2.3"
    assert payload["target_version"] == "2.0.0"
    assert payload["availability"] == "available"
    assert payload["effects"][-2:] == [
        "no_connection_retained",
        "no_tool_authority",
    ]
    assert confirmations == []
    assert installer.installs == [(installed.management_id, "b" * 64)]
    command = {
        "request_id": "8" * 32,
        "expected_revision": payload["expected_revision"],
        "preview_digest": payload["preview_digest"],
    }
    update_path = f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/update"
    assert http.post(
        update_path,
        json=command,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    applied = http.post(
        update_path,
        json=command,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert applied.status_code == 200
    assert applied.headers["cache-control"] == "no-store, private"
    receipt = applied.json()
    assert receipt["action"] == "update"
    assert receipt["server"]["server_version"] == "2.0.0"
    assert receipt["server"]["rollback_generation"]["server_version"] == "1.2.3"
    assert receipt["connection_retained"] is False
    assert receipt["tool_authority_granted"] is False
    rollback_preview = http.get(
        f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/rollback-preview",
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert rollback_preview.status_code == 200
    rollback_payload = rollback_preview.json()
    assert rollback_payload["target_version"] == "1.2.3"
    rolled_back = http.post(
        f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/rollback",
        json={
            "request_id": "9" * 32,
            "expected_revision": rollback_payload["expected_revision"],
            "preview_digest": rollback_payload["preview_digest"],
        },
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["server"]["server_version"] == "1.2.3"
    cleanup_preview = http.get(
        f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/rollback-cleanup-preview",
        headers={"Authorization": "Bearer example-local-token"},
    ).json()
    cleaned = http.post(
        f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}/rollback-cleanup",
        json={
            "request_id": "a" * 32,
            "expected_revision": cleanup_preview["expected_revision"],
            "preview_digest": cleanup_preview["preview_digest"],
        },
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert cleaned.status_code == 200
    assert cleaned.json()["server"]["rollback_generation"] is None
    assert confirmations == [True, True, True]


def test_http_interrupted_local_uninstall_recovery_is_private_and_confirmed(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    registry = _McpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    uninstall_preview = service.lifecycle_preview(
        installed.management_id, "uninstall"
    )
    service._repository.begin_local_uninstall(  # type: ignore[attr-defined]
        installed.management_id,
        command=ApplyMcpManagedLifecycle(
            request_id="8" * 32,
            expected_revision=uninstall_preview.expected_revision,
            preview_digest=uninstall_preview.preview_digest,
        ),
        request_fingerprint="f" * 64,
        expected_tree_digest="c" * 64,
        updated_at=datetime(2040, 1, 1, tzinfo=UTC),
    )
    recovered_service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    confirmations: list[str] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append("confirmed")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            recovered_service,
        )
    )
    http = TestClient(app)
    base = f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}"
    assert http.get(f"{base}/cleanup-preview").status_code == 401
    preview_response = http.get(
        f"{base}/cleanup-preview",
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["cache-control"] == "no-store, private"
    preview = preview_response.json()
    assert preview["availability"] == "available"
    assert preview["effects"][0] == "verify_operation_journal"
    body = {
        "request_id": "9" * 32,
        "expected_revision": preview["expected_revision"],
        "preview_digest": preview["preview_digest"],
    }
    assert http.post(
        f"{base}/cleanup",
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    recovered = http.post(
        f"{base}/cleanup",
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert recovered.status_code == 200
    assert recovered.headers["cache-control"] == "no-store, private"
    assert recovered.json()["package_presence"] == "absent"
    assert recovered.json()["process_started"] is False
    assert recovered.json()["server"]["installation_state"] == "not_installed"
    assert confirmations == ["confirmed"]


def test_http_interrupted_update_recovery_is_private_exact_and_confirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    install_preview = service.lifecycle_preview(
        created.server.management_id, "install"
    )
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=install_preview.expected_revision,
            preview_digest=install_preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)

    def fail_commit(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        del args, kwargs
        raise McpManagedServerError("mcp_managed_storage_unavailable")

    monkeypatch.setattr(service._repository, "finish_local_update", fail_commit)
    installer.update_rollback_succeeds = False
    with pytest.raises(
        McpManagedServerError, match="mcp_managed_storage_unavailable"
    ):
        service.apply_local_update(
            installed.management_id,
            ApplyMcpManagedLocalUpdate(
                request_id="8" * 32,
                expected_revision=update_preview.expected_revision,
                preview_digest=update_preview.preview_digest,
            ),
        )
    installer.update_rollback_succeeds = True
    confirmations: list[str] = []

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer example-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_example_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_example_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append("confirmed")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            service,
        )
    )
    http = TestClient(app)
    base = f"{MCP_MANAGED_SERVER_PATH}/{installed.management_id}"
    assert http.get(f"{base}/recovery-preview").status_code == 401
    preview_response = http.get(
        f"{base}/recovery-preview",
        headers={"Authorization": "Bearer example-local-token"},
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["cache-control"] == "no-store, private"
    preview = preview_response.json()
    assert preview["interrupted_action"] == "update"
    assert preview["availability"] == "available"
    assert preview["effects"][1:3] == [
        "restore_durable_current_generation",
        "discard_verified_staged_target",
    ]
    body = {
        "request_id": "9" * 32,
        "expected_revision": preview["expected_revision"],
        "preview_digest": preview["preview_digest"],
    }
    assert http.post(
        f"{base}/recovery",
        json=body,
        headers={"Authorization": "Bearer example-local-token"},
    ).status_code == 403
    recovered = http.post(
        f"{base}/recovery",
        json=body,
        headers={
            "Authorization": "Bearer example-local-token",
            "X-Example-Confirmation": "confirmed",
        },
    )
    assert recovered.status_code == 200
    assert recovered.headers["cache-control"] == "no-store, private"
    assert recovered.json()["recovered_action"] == "update"
    assert recovered.json()["filesystem_state_verified"] is True
    assert recovered.json()["process_started"] is False
    assert recovered.json()["server"]["installation_state"] == "installed"
    assert recovered.json()["server"]["server_version"] == "1.2.3"
    assert confirmations == ["confirmed"]


def test_schema_eleven_migrates_without_changing_existing_projects(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    database = _database(tmp_path)
    project = _project(database, project_id="b" * 32, name="Migration project")
    with sqlite3.connect(database.path) as connection:
        downgrade_agent_catalog_post_v20(connection)
        for table in (
            "mcp_managed_tool_call_receipts",
            "mcp_managed_project_tools",
            "mcp_managed_tool_snapshot_state",
            "mcp_managed_tools",
            "mcp_managed_tool_snapshots",
            "mcp_managed_local_swap_receipts",
            "mcp_managed_local_recovery_attempts",
            "mcp_managed_local_rollback_generations",
            "mcp_managed_local_update_payloads",
            "mcp_managed_local_operations",
            "mcp_managed_local_packages",
            "mcp_managed_lifecycle_receipts",
            "mcp_managed_lifecycle_state",
            "mcp_managed_probe_receipts",
            "mcp_managed_mutations",
            "mcp_managed_secret_references",
            "mcp_managed_project_bindings",
            "mcp_managed_requirements",
            "mcp_managed_servers",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=12"
        )
        connection.execute("PRAGMA user_version=11")

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    catalog = AgentCatalogService(SqliteAgentCatalogRepository(migrated))
    assert catalog.get_project(project.project_id).name == "Migration project"
    assert SqliteMcpManagedServerRepository(migrated).list_servers(limit=64) == ()


def test_schema_thirteen_backfills_existing_plans_as_uninstalled(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    database = _database(tmp_path)
    service = _service(database, _Vault())
    created, _ = _create(service)
    with sqlite3.connect(database.path) as connection:
        downgrade_agent_catalog_post_v20(connection)
        connection.execute("DROP TABLE mcp_managed_tool_call_receipts")
        connection.execute("DROP TABLE mcp_managed_project_tools")
        connection.execute("DROP TABLE mcp_managed_tool_snapshot_state")
        connection.execute("DROP TABLE mcp_managed_tools")
        connection.execute("DROP TABLE mcp_managed_tool_snapshots")
        connection.execute("DROP TABLE mcp_managed_local_swap_receipts")
        connection.execute("DROP TABLE mcp_managed_local_recovery_attempts")
        connection.execute("DROP TABLE mcp_managed_local_rollback_generations")
        connection.execute("DROP TABLE mcp_managed_local_update_payloads")
        connection.execute("DROP TABLE mcp_managed_local_operations")
        connection.execute("DROP TABLE mcp_managed_local_packages")
        connection.execute("DROP TABLE mcp_managed_lifecycle_receipts")
        connection.execute("DROP TABLE mcp_managed_lifecycle_state")
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=14"
        )
        connection.execute("PRAGMA user_version=13")

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    restored = SqliteMcpManagedServerRepository(migrated).get_server(
        created.server.management_id
    )
    assert restored is not None
    assert restored.plan_revision == created.server.plan_revision
    assert restored.lifecycle_state == "planned"
    assert restored.installation_state == "not_installed"
    assert restored.installation_kind == "none"
    assert restored.operation_state == "idle"
    assert restored.installed_plan_revision is None
    assert restored.installed_at is None


def test_schema_eighteen_expands_the_bounded_update_evidence_journal(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    database = _database(tmp_path)
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with sqlite3.connect(database.path) as connection:
        downgrade_agent_catalog_post_v20(connection)
        connection.execute("DROP TABLE mcp_managed_tool_call_receipts")
        connection.execute(
            "ALTER TABLE mcp_managed_tool_snapshots "
            "DROP COLUMN source_manifest_digest"
        )
        connection.execute("DROP TABLE mcp_managed_local_update_payloads")
        connection.execute(
            """
            CREATE TABLE mcp_managed_local_update_payloads (
                request_id TEXT PRIMARY KEY,
                management_id TEXT NOT NULL UNIQUE,
                target_plan_json TEXT NOT NULL,
                target_plan_digest TEXT NOT NULL,
                target_result_json TEXT CHECK(
                    target_result_json IS NULL OR
                    length(target_result_json) BETWEEN 2 AND 32768
                ),
                target_result_digest TEXT,
                target_tree_digest TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            ) STRICT
            """
        )
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=19"
        )
        connection.execute("PRAGMA user_version=18")

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        definition = str(connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='mcp_managed_local_update_payloads'"
        ).fetchone()[0])
        assert (
            "length(target_result_json) BETWEEN 2 AND 4194304"
            in definition
        )


def test_schema_nineteen_backfills_current_and_retained_snapshot_manifests(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    database = _database(tmp_path)
    registry = _UpdatingMcpbRegistryClient()
    installer = _LocalInstaller()
    service = _service(
        database,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    created, _ = _create(service)
    preview = service.lifecycle_preview(created.server.management_id, "install")
    installed = service.apply_lifecycle(
        created.server.management_id,
        "install",
        ApplyMcpManagedLifecycle(
            request_id="7" * 32,
            expected_revision=preview.expected_revision,
            preview_digest=preview.preview_digest,
        ),
    ).server
    update_preview = service.local_update_preview(installed.management_id)
    updated = service.apply_local_update(
        installed.management_id,
        ApplyMcpManagedLocalUpdate(
            request_id="8" * 32,
            expected_revision=update_preview.expected_revision,
            preview_digest=update_preview.preview_digest,
        ),
    ).server
    assert installed.local_package_evidence is not None
    assert updated.local_package_evidence is not None
    with sqlite3.connect(database.path) as connection:
        downgrade_agent_catalog_post_v20(connection)
        connection.execute("DROP TABLE mcp_managed_tool_call_receipts")
        connection.execute(
            "ALTER TABLE mcp_managed_tool_snapshots "
            "DROP COLUMN source_manifest_digest"
        )
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=20"
        )
        connection.execute("PRAGMA user_version=19")

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    restarted = _service(
        migrated,
        _Vault(),
        catalog=_mcpb_catalog(registry),
        installer=installer,
    )
    snapshot = restarted.get_tool_snapshot(updated.management_id)
    assert snapshot.source_tree_digest == updated.local_package_evidence.tree_digest
    assert (
        snapshot.source_manifest_digest
        == updated.local_package_evidence.manifest_digest
    )

    rollback_preview = restarted.local_rollback_preview(updated.management_id)
    rolled_back = restarted.apply_local_rollback(
        updated.management_id,
        ApplyMcpManagedLocalRollback(
            request_id="9" * 32,
            expected_revision=rollback_preview.expected_revision,
            preview_digest=rollback_preview.preview_digest,
        ),
    ).server
    snapshot = restarted.get_tool_snapshot(rolled_back.management_id)
    assert snapshot is not None
    assert snapshot.source_tree_digest == installed.local_package_evidence.tree_digest
    assert (
        snapshot.source_manifest_digest
        == installed.local_package_evidence.manifest_digest
    )
