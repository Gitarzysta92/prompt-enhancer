"""SQLite repository for MCP plans and content-free host receipts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import json
import re
import sqlite3
from typing import Any, Literal, cast

from ...application.mcp_registry_catalog import (
    McpRegistryInstallOption,
    McpRegistryServerReview,
)
from ...application.mcp_guarded_host import McpHostProbeResult
from ...application.mcp_local_packages import (
    McpLocalPackageConfigurationInspectionResult,
    McpLocalPackageInstallResult,
    McpLocalPackageStagedUpdateResult,
)
from ...application.mcp_server_management import (
    ApplyMcpManagedLocalCleanup,
    ApplyMcpManagedLocalOperationRecovery,
    ApplyMcpManagedLocalRollback,
    ApplyMcpManagedLocalRollbackCleanup,
    ApplyMcpManagedLocalUpdate,
    ApplyMcpManagedLifecycle,
    CreateMcpManagedServer,
    InspectMcpManagedLocalConfiguration,
    MAX_MCP_MANAGED_SERVERS,
    McpManagedPermission,
    McpManagedHostProbe,
    McpManagedLocalPackageEvidence,
    McpManagedLocalConfigurationInspection,
    McpManagedLocalRollbackGeneration,
    McpManagedLocalUpdateTarget,
    McpManagedLocalOperationRecovery,
    McpManagedProjectBinding,
    McpManagedRequirement,
    McpManagedSecretReferenceState,
    McpManagedServer,
    McpManagedServerError,
    McpManagedReviewedTool,
    McpManagedToolSnapshot,
    McpManagedToolSnapshotSummary,
    McpManagedVaultRemoveCommand,
    McpManagedVaultStoreCommand,
    ProbeMcpManagedServer,
    RemoveMcpManagedSecret,
    SecretRemoval,
    SecretReservation,
    SetMcpManagedProjectBinding,
    StoreMcpManagedSecret,
)
from ...application.agent_catalog import AgentCatalogError
from .agent_catalog import AgentCatalogSqliteDatabase


_PERMISSIONS: tuple[McpManagedPermission, ...] = (
    "process_spawn",
    "filesystem_read",
    "filesystem_write",
    "network_egress",
    "credential_use",
)
_RISKS = {
    "downloads_package",
    "executes_local_code",
    "package_integrity_not_declared",
    "command_arguments_declared",
    "filesystem_input_declared",
    "credential_input_declared",
    "remote_network_egress",
    "insecure_remote_transport",
}
_MAX_STAGED_UPDATE_RESULT_JSON_CHARS = 4 * 1024 * 1024


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _json_tuple(
    value: object,
    *,
    allowed: set[str],
    maximum: int,
) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        raise McpManagedServerError("mcp_managed_storage_corrupt") from None
    if (
        not isinstance(parsed, list)
        or len(parsed) > maximum
        or any(not isinstance(item, str) or item not in allowed for item in parsed)
        or len(set(parsed)) != len(parsed)
    ):
        raise McpManagedServerError("mcp_managed_storage_corrupt")
    return tuple(parsed)


def _canonical_json(values: Sequence[str]) -> str:
    return json.dumps(list(values), separators=(",", ":"), ensure_ascii=True)


def _identity_tuple(value: object, *, maximum: int) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        raise McpManagedServerError("mcp_managed_storage_corrupt") from None
    if (
        not isinstance(parsed, list)
        or len(parsed) > maximum
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"^[0-9a-f]{32}$", item) is None
            for item in parsed
        )
        or len(set(parsed)) != len(parsed)
    ):
        raise McpManagedServerError("mcp_managed_storage_corrupt")
    return tuple(parsed)


def _model_json(value: Any) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _mapping_json(
    value: dict[str, Any],
    *,
    error_code: str = "mcp_managed_tool_snapshot_invalid",
) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise McpManagedServerError(error_code) from None


def _mapping_from_json(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, RecursionError):
        raise McpManagedServerError("mcp_managed_storage_corrupt") from None
    if not isinstance(parsed, dict):
        raise McpManagedServerError("mcp_managed_storage_corrupt")
    return parsed


def _probe_result_payload(value: McpHostProbeResult) -> dict[str, Any]:
    payload = value.model_dump(mode="json")
    payload["reviewed_tools"] = [
        item.model_dump(mode="json") for item in value.reviewed_tools
    ]
    return payload


def _install_result_json(
    value: McpLocalPackageInstallResult | McpLocalPackageStagedUpdateResult,
) -> str:
    payload = value.model_dump(mode="json")
    payload["probe"] = _probe_result_payload(value.probe)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(encoded) > _MAX_STAGED_UPDATE_RESULT_JSON_CHARS:
        raise McpManagedServerError("mcp_managed_update_evidence_invalid")
    return encoded


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SqliteMcpManagedServerRepository:
    """Store public plan metadata, grants, and opaque vault references."""

    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database
        self._database.initialize()
        self._reconcile_interrupted_local_installs()
        self._reconcile_interrupted_local_operations()

    def _reconcile_interrupted_local_installs(self) -> None:
        """Turn crash-left staging operations into explicit cleanup state."""

        stamp = _iso(datetime.now(UTC))
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    rows = connection.execute(
                        "SELECT management_id FROM mcp_managed_local_packages "
                        "WHERE status='installing'"
                    ).fetchall()
                    for row in rows:
                        management_id = str(row["management_id"])
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_packages
                            SET status='cleanup_required',
                                process_tree_cleanup='unconfirmed',
                                error_code='mcp_package_install_interrupted',updated_at=?
                            WHERE management_id=? AND status='installing'
                            """,
                            (stamp, management_id),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup='unconfirmed',
                                last_error_code='mcp_package_install_interrupted',
                                updated_at=?
                            WHERE management_id=?
                            """,
                            (stamp, management_id),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? WHERE management_id=?",
                            (stamp, management_id),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def _reconcile_interrupted_local_operations(self) -> None:
        """Quarantine crash-left update/removal operations for explicit recovery."""

        stamp = _iso(datetime.now(UTC))
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    rows = connection.execute(
                        "SELECT management_id,action,status "
                        "FROM mcp_managed_local_operations "
                        "WHERE status IN ('reserved','prepared')"
                    ).fetchall()
                    for row in rows:
                        management_id = str(row["management_id"])
                        action = str(row["action"])
                        process_cleanup = (
                            "unconfirmed"
                            if action == "update"
                            and str(row["status"]) == "reserved"
                            else "verified"
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_operations
                            SET status='cleanup_required',
                                error_code='mcp_package_operation_interrupted',
                                updated_at=?
                            WHERE management_id=?
                              AND status IN ('reserved','prepared')
                            """,
                            (stamp, management_id),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup=?,
                                last_error_code='mcp_package_operation_interrupted',
                                updated_at=?
                            WHERE management_id=?
                            """,
                            (process_cleanup, stamp, management_id),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? WHERE management_id=?",
                            (stamp, management_id),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    @staticmethod
    def _tool_snapshot(
        connection: sqlite3.Connection,
        management_id: str,
    ) -> McpManagedToolSnapshot | None:
        state = connection.execute(
            "SELECT snapshot_id FROM mcp_managed_tool_snapshot_state "
            "WHERE management_id=?",
            (management_id,),
        ).fetchone()
        if state is None:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        if state["snapshot_id"] is None:
            return None
        snapshot_id = str(state["snapshot_id"])
        row = connection.execute(
            "SELECT * FROM mcp_managed_tool_snapshots "
            "WHERE snapshot_id=? AND management_id=?",
            (snapshot_id, management_id),
        ).fetchone()
        if row is None:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        tool_rows = connection.execute(
            "SELECT * FROM mcp_managed_tools WHERE snapshot_id=? "
            "ORDER BY tool_order, tool_id",
            (snapshot_id,),
        ).fetchall()
        tools: list[McpManagedReviewedTool] = []
        canonical: list[dict[str, Any]] = []
        for index, tool_row in enumerate(tool_rows):
            if int(tool_row["tool_order"]) != index:
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            input_schema = _mapping_from_json(tool_row["input_schema_json"])
            model_input_schema = _mapping_from_json(
                tool_row["model_input_schema_json"]
            )
            output_schema = (
                None
                if tool_row["output_schema_json"] is None
                else _mapping_from_json(tool_row["output_schema_json"])
            )
            if _text_digest(_mapping_json(
                input_schema,
                error_code="mcp_managed_storage_corrupt",
            )) != str(
                tool_row["input_schema_digest"]
            ) or (
                output_schema is not None
                and _text_digest(_mapping_json(
                    output_schema,
                    error_code="mcp_managed_storage_corrupt",
                ))
                != str(tool_row["output_schema_digest"])
            ):
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            contract_material = _mapping_json(
                {
                    "name": str(tool_row["name"]),
                    "title": (
                        None
                        if tool_row["title"] is None
                        else str(tool_row["title"])
                    ),
                    "description": (
                        None
                        if tool_row["description"] is None
                        else str(tool_row["description"])
                    ),
                    "input": input_schema,
                    "output": output_schema,
                },
                error_code="mcp_managed_storage_corrupt",
            )
            contract_digest = _text_digest(contract_material)
            if (
                contract_digest != str(tool_row["contract_digest"])
                or contract_digest[:32] != str(tool_row["tool_id"])
            ):
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            try:
                tool = McpManagedReviewedTool(
                    tool_id=str(tool_row["tool_id"]),
                    name=str(tool_row["name"]),
                    title=(
                        None
                        if tool_row["title"] is None
                        else str(tool_row["title"])
                    ),
                    description=(
                        None
                        if tool_row["description"] is None
                        else str(tool_row["description"])
                    ),
                    model_alias=str(tool_row["model_alias"]),
                    input_schema=input_schema,
                    input_schema_digest=str(tool_row["input_schema_digest"]),
                    model_input_schema=model_input_schema,
                    output_schema=output_schema,
                    output_schema_digest=(
                        None
                        if tool_row["output_schema_digest"] is None
                        else str(tool_row["output_schema_digest"])
                    ),
                    contract_digest=contract_digest,
                )
            except ValueError:
                raise McpManagedServerError("mcp_managed_storage_corrupt") from None
            tools.append(tool)
            canonical.append(
                {
                    "name": tool.name,
                    "title": tool.title,
                    "description": tool.description,
                    "input": tool.input_schema,
                    "output": tool.output_schema,
                }
            )
        if (
            len(tools) != int(row["tool_count"])
            or [item.name for item in tools]
            != sorted(item.name for item in tools)
            or _text_digest(
                json.dumps(
                    canonical,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
            != str(row["schema_digest"])
        ):
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        try:
            return McpManagedToolSnapshot(
                snapshot_id=snapshot_id,
                management_id=management_id,
                plan_revision=str(row["plan_revision"]),
                source=str(row["source"]),
                source_tree_digest=(
                    None
                    if row["source_tree_digest"] is None
                    else str(row["source_tree_digest"])
                ),
                source_manifest_digest=(
                    None
                    if row["source_manifest_digest"] is None
                    else str(row["source_manifest_digest"])
                ),
                protocol_version=str(row["protocol_version"]),
                tool_count=int(row["tool_count"]),
                schema_digest=str(row["schema_digest"]),
                reviewed_at=_time(str(row["reviewed_at"])),
                tools=tuple(tools),
            )
        except ValueError:
            raise McpManagedServerError("mcp_managed_storage_corrupt") from None

    @staticmethod
    def _set_current_tool_snapshot(
        connection: sqlite3.Connection,
        management_id: str,
        *,
        snapshot_id: str | None,
        updated_at: datetime,
    ) -> None:
        state = connection.execute(
            "SELECT snapshot_id FROM mcp_managed_tool_snapshot_state "
            "WHERE management_id=?",
            (management_id,),
        ).fetchone()
        if state is None:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        previous = None if state["snapshot_id"] is None else str(state["snapshot_id"])
        if previous != snapshot_id:
            connection.execute(
                "DELETE FROM mcp_managed_project_tools WHERE management_id=?",
                (management_id,),
            )
        connection.execute(
            "UPDATE mcp_managed_tool_snapshot_state "
            "SET snapshot_id=?,updated_at=? WHERE management_id=?",
            (snapshot_id, _iso(updated_at), management_id),
        )

    @staticmethod
    def _invalidate_connection_review(
        connection: sqlite3.Connection,
        management_id: str,
        *,
        updated_at: datetime,
    ) -> None:
        """Revoke current schemas and admissions without erasing audit history."""

        SqliteMcpManagedServerRepository._set_current_tool_snapshot(
            connection,
            management_id,
            snapshot_id=None,
            updated_at=updated_at,
        )

    @staticmethod
    def _store_tool_snapshot(
        connection: sqlite3.Connection,
        management_id: str,
        *,
        observation_id: str,
        plan_revision: str,
        source_tree_digest: str | None,
        source_manifest_digest: str | None,
        result: McpHostProbeResult,
        reviewed_at: datetime,
    ) -> str | None:
        if not result.tool_names_persisted or not result.tool_schemas_persisted:
            SqliteMcpManagedServerRepository._set_current_tool_snapshot(
                connection,
                management_id,
                snapshot_id=None,
                updated_at=reviewed_at,
            )
            return None
        try:
            tools = tuple(
                McpManagedReviewedTool.from_guarded(item)
                for item in result.reviewed_tools
            )
        except ValueError:
            raise McpManagedServerError(
                "mcp_managed_tool_snapshot_invalid"
            ) from None
        if len(tools) != result.tool_count:
            raise McpManagedServerError("mcp_managed_tool_snapshot_invalid")
        if (source_tree_digest is None) != (source_manifest_digest is None):
            raise McpManagedServerError("mcp_managed_tool_snapshot_invalid")
        source = "remote_probe" if source_tree_digest is None else "local_package_probe"
        identity = "\0".join(
            (
                "mcp-managed-tool-snapshot.v1",
                management_id,
                observation_id,
                plan_revision,
                source_tree_digest or "",
                source_manifest_digest or "",
                result.protocol_version,
                result.schema_digest,
            )
        )
        snapshot_id = _text_digest(identity)[:32]
        existing = connection.execute(
            "SELECT * FROM mcp_managed_tool_snapshots WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchone()
        if existing is None:
            stamp = _iso(reviewed_at)
            connection.execute(
                """
                INSERT INTO mcp_managed_tool_snapshots(
                    snapshot_id,management_id,observation_id,plan_revision,
                    source,source_tree_digest,source_manifest_digest,
                    protocol_version,tool_count,
                    schema_digest,reviewed_at,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    snapshot_id,
                    management_id,
                    observation_id,
                    plan_revision,
                    source,
                    source_tree_digest,
                    source_manifest_digest,
                    result.protocol_version,
                    result.tool_count,
                    result.schema_digest,
                    stamp,
                    stamp,
                ),
            )
            for index, tool in enumerate(tools):
                connection.execute(
                    """
                    INSERT INTO mcp_managed_tools(
                        snapshot_id,tool_id,tool_order,name,title,description,
                        model_alias,input_schema_json,input_schema_digest,
                        model_input_schema_json,output_schema_json,
                        output_schema_digest,contract_digest
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        snapshot_id,
                        tool.tool_id,
                        index,
                        tool.name,
                        tool.title,
                        tool.description,
                        tool.model_alias,
                        _mapping_json(tool.input_schema),
                        tool.input_schema_digest,
                        _mapping_json(tool.model_input_schema),
                        (
                            None
                            if tool.output_schema is None
                            else _mapping_json(tool.output_schema)
                        ),
                        tool.output_schema_digest,
                        tool.contract_digest,
                    ),
                )
        elif (
            str(existing["management_id"]) != management_id
            or str(existing["observation_id"]) != observation_id
            or str(existing["plan_revision"]) != plan_revision
            or str(existing["source"]) != source
            or (
                None
                if existing["source_tree_digest"] is None
                else str(existing["source_tree_digest"])
            )
            != source_tree_digest
            or (
                None
                if existing["source_manifest_digest"] is None
                else str(existing["source_manifest_digest"])
            )
            != source_manifest_digest
            or str(existing["protocol_version"]) != result.protocol_version
            or int(existing["tool_count"]) != result.tool_count
            or str(existing["schema_digest"]) != result.schema_digest
        ):
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        SqliteMcpManagedServerRepository._set_current_tool_snapshot(
            connection,
            management_id,
            snapshot_id=snapshot_id,
            updated_at=reviewed_at,
        )
        snapshot = SqliteMcpManagedServerRepository._tool_snapshot(
            connection,
            management_id,
        )
        if snapshot is None or snapshot.tools != tools:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        return snapshot_id

    @staticmethod
    def _activate_tool_snapshot_for_tree(
        connection: sqlite3.Connection,
        management_id: str,
        *,
        plan_revision: str,
        tree_digest: str,
        manifest_digest: str,
        updated_at: datetime,
    ) -> None:
        row = connection.execute(
            """
            SELECT snapshot_id FROM mcp_managed_tool_snapshots
            WHERE management_id=? AND plan_revision=?
              AND source='local_package_probe' AND source_tree_digest=?
              AND source_manifest_digest=?
            ORDER BY reviewed_at DESC,snapshot_id DESC LIMIT 1
            """,
            (management_id, plan_revision, tree_digest, manifest_digest),
        ).fetchone()
        SqliteMcpManagedServerRepository._set_current_tool_snapshot(
            connection,
            management_id,
            snapshot_id=None if row is None else str(row["snapshot_id"]),
            updated_at=updated_at,
        )

    @staticmethod
    def _configuration_inspection(
        row: sqlite3.Row,
    ) -> McpManagedLocalConfigurationInspection:
        if any(
            bool(row[name])
            for name in (
                "archive_retained",
                "process_started",
                "configuration_values_persisted",
                "manifest_content_persisted",
            )
        ):
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        try:
            return McpManagedLocalConfigurationInspection(
                plan_revision=str(row["plan_revision"]),
                artifact_sha256=str(row["artifact_sha256"]),
                artifact_bytes=int(row["artifact_bytes"]),
                manifest_digest=str(row["manifest_digest"]),
                manifest_version=str(row["manifest_version"]),
                configuration_schema_digest=str(
                    row["configuration_schema_digest"]
                ),
                requirement_ids=_identity_tuple(
                    row["requirement_ids_json"],
                    maximum=32,
                ),
                inspected_at=_time(str(row["inspected_at"])),
            )
        except ValueError:
            raise McpManagedServerError("mcp_managed_storage_corrupt") from None

    @staticmethod
    def _server(
        connection: sqlite3.Connection,
        management_id: str,
    ) -> McpManagedServer | None:
        row = connection.execute(
            "SELECT * FROM mcp_managed_servers WHERE management_id=?",
            (management_id,),
        ).fetchone()
        if row is None:
            return None
        required_permissions = cast(
            tuple[McpManagedPermission, ...],
            _json_tuple(
                row["required_permissions_json"],
                allowed=set(_PERMISSIONS),
                maximum=5,
            ),
        )
        risks = _json_tuple(row["risks_json"], allowed=_RISKS, maximum=8)
        requirement_rows = connection.execute(
            """
            SELECT requirement.*, secret_ref.reference_state,
                   secret_ref.vault_provider
            FROM mcp_managed_requirements requirement
            LEFT JOIN mcp_managed_secret_references secret_ref
              ON secret_ref.management_id=requirement.management_id
             AND secret_ref.requirement_id=requirement.requirement_id
            WHERE requirement.management_id=?
            ORDER BY requirement.requirement_order, requirement.requirement_id
            """,
            (management_id,),
        ).fetchall()
        requirements: list[McpManagedRequirement] = []
        for requirement in requirement_rows:
            secret = bool(requirement["secret"])
            reference_state = requirement["reference_state"]
            if secret:
                state_by_reference: dict[str | None, str] = {
                    None: "secret_missing",
                    "pending_store": "secret_pending_store",
                    "active": "secret_stored",
                    "store_failed": "secret_store_failed",
                    "pending_removal": "secret_pending_removal",
                    "cleanup_required": "secret_cleanup_required",
                }
                configuration_state = state_by_reference.get(reference_state)
                if configuration_state is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
            elif bool(requirement["user_value_needed"]):
                state_by_reference = {
                    None: "value_required",
                    "pending_store": "value_pending_store",
                    "active": "value_stored",
                    "store_failed": "value_store_failed",
                    "pending_removal": "value_pending_removal",
                    "cleanup_required": "value_cleanup_required",
                }
                configuration_state = state_by_reference.get(reference_state)
                if configuration_state is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
            elif bool(requirement["fixed_value_declared"]):
                if reference_state is not None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                configuration_state = "publisher_value_declared"
            elif bool(requirement["default_declared"]):
                if reference_state is not None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                configuration_state = "registry_default_declared"
            else:
                if reference_state is not None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                configuration_state = "optional_unset"
            requirements.append(
                McpManagedRequirement(
                    requirement_id=str(requirement["requirement_id"]),
                    location=str(requirement["location"]),
                    name=str(requirement["name"]),
                    required=bool(requirement["required"]),
                    secret=secret,
                    format=str(requirement["value_format"]),
                    user_value_needed=bool(requirement["user_value_needed"]),
                    configuration_state=configuration_state,
                    secret_vault_provider=(
                        None
                        if not secret or requirement["vault_provider"] is None
                        else str(requirement["vault_provider"])
                    ),
                    value_vault_provider=(
                        str(requirement["vault_provider"])
                        if not secret
                        and bool(requirement["user_value_needed"])
                        and requirement["vault_provider"] is not None
                        else None
                    ),
                )
            )
        lifecycle = connection.execute(
            "SELECT * FROM mcp_managed_lifecycle_state WHERE management_id=?",
            (management_id,),
        ).fetchone()
        if lifecycle is None:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        tool_snapshot = SqliteMcpManagedServerRepository._tool_snapshot(
            connection,
            management_id,
        )
        local_package = connection.execute(
            "SELECT * FROM mcp_managed_local_packages WHERE management_id=?",
            (management_id,),
        ).fetchone()
        inspection_row = connection.execute(
            "SELECT * FROM mcp_managed_local_configuration_inspections "
            "WHERE management_id=? AND current_state=1",
            (management_id,),
        ).fetchone()
        configuration_inspection = (
            None
            if inspection_row is None
            else SqliteMcpManagedServerRepository._configuration_inspection(
                inspection_row
            )
        )
        binding_rows = connection.execute(
            """
            SELECT binding.*, project.name AS project_name
            FROM mcp_managed_project_bindings binding
            JOIN agent_projects project ON project.project_id=binding.project_id
            WHERE binding.management_id=?
            ORDER BY project.name COLLATE NOCASE, binding.project_id
            """,
            (management_id,),
        ).fetchall()
        admitted_rows = connection.execute(
            """
            SELECT project_id,snapshot_id,tool_id
            FROM mcp_managed_project_tools
            WHERE management_id=?
            ORDER BY project_id,tool_id
            """,
            (management_id,),
        ).fetchall()
        admitted_by_project: dict[str, list[sqlite3.Row]] = {}
        for admitted in admitted_rows:
            admitted_by_project.setdefault(str(admitted["project_id"]), []).append(
                admitted
            )
        available_tool_ids = (
            set() if tool_snapshot is None else {item.tool_id for item in tool_snapshot.tools}
        )
        bindings: list[McpManagedProjectBinding] = []
        for binding in binding_rows:
            granted = cast(
                tuple[McpManagedPermission, ...],
                _json_tuple(
                    binding["granted_permissions_json"],
                    allowed=set(_PERMISSIONS),
                    maximum=5,
                ),
            )
            enabled = bool(binding["enabled"])
            project_id = str(binding["project_id"])
            admitted = admitted_by_project.pop(project_id, [])
            admitted_ids = tuple(str(item["tool_id"]) for item in admitted)
            admitted_snapshot_ids = {str(item["snapshot_id"]) for item in admitted}
            if not enabled and admitted:
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            if admitted and (
                tool_snapshot is None
                or admitted_snapshot_ids != {tool_snapshot.snapshot_id}
                or not set(admitted_ids).issubset(available_tool_ids)
            ):
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            admission_state = "admitted" if admitted else (
                "review_required" if enabled else "disabled"
            )
            effective_state = (
                "disabled"
                if not enabled
                else "inactive_tool_review_required"
                if not admitted
                else "inactive_host_unavailable"
                if str(lifecycle["installation_state"]) == "installed"
                else "inactive_install_required"
            )
            bindings.append(
                McpManagedProjectBinding(
                    project_id=project_id,
                    project_name=str(binding["project_name"]),
                    enabled=enabled,
                    required_permissions=required_permissions,
                    granted_permissions=granted,
                    admitted_tool_ids=admitted_ids,
                    tool_snapshot_id=(
                        tool_snapshot.snapshot_id if admitted else None
                    ),
                    admission_state=admission_state,
                    effective_state=effective_state,
                    created_at=_time(str(binding["created_at"])),
                    updated_at=_time(str(binding["updated_at"])),
                    revision=int(binding["revision"]),
                )
            )
        if admitted_by_project:
            raise McpManagedServerError("mcp_managed_storage_corrupt")
        probe_row = connection.execute(
            """
            SELECT receipt.*
            FROM mcp_managed_probe_receipts receipt
            JOIN mcp_managed_tool_snapshot_state state
              ON state.management_id=receipt.management_id
            JOIN mcp_managed_tool_snapshots snapshot
              ON snapshot.management_id=receipt.management_id
             AND snapshot.snapshot_id=state.snapshot_id
             AND snapshot.observation_id=receipt.request_id
            WHERE receipt.management_id=?
            """,
            (management_id,),
        ).fetchone()
        local_operation = connection.execute(
            "SELECT * FROM mcp_managed_local_operations WHERE management_id=?",
            (management_id,),
        ).fetchone()
        generation_row = connection.execute(
            "SELECT * FROM mcp_managed_local_rollback_generations "
            "WHERE management_id=?",
            (management_id,),
        ).fetchone()
        local_installed = (
            local_package is not None and str(local_package["status"]) == "installed"
        )
        if local_installed:
            snapshot_matches_probe = (
                tool_snapshot is not None
                and tool_snapshot.source == "local_package_probe"
                and tool_snapshot.source_tree_digest == str(local_package["tree_digest"])
                and tool_snapshot.source_manifest_digest
                == str(local_package["manifest_digest"])
                and tool_snapshot.plan_revision == str(row["plan_revision"])
                and tool_snapshot.protocol_version
                == str(local_package["protocol_version"])
                and tool_snapshot.tool_count == int(local_package["tool_count"])
                and tool_snapshot.schema_digest == str(local_package["schema_digest"])
            )
            last_probe = McpManagedHostProbe(
                request_id=str(local_package["request_id"]),
                checked_at=_time(str(local_package["checked_at"])),
                transport="stdio",
                protocol_version=str(local_package["protocol_version"]),
                tool_count=int(local_package["tool_count"]),
                schema_digest=str(local_package["schema_digest"]),
                elapsed_ms=int(local_package["elapsed_ms"]),
                process_started=True,
                process_tree_cleanup="verified",
                tool_names_persisted=snapshot_matches_probe,
                tool_schemas_persisted=snapshot_matches_probe,
            )
            local_evidence = McpManagedLocalPackageEvidence(
                artifact_sha256=str(local_package["artifact_sha256"]),
                artifact_bytes=int(local_package["artifact_bytes"]),
                tree_digest=str(local_package["tree_digest"]),
                manifest_digest=str(local_package["manifest_digest"]),
                manifest_version=str(local_package["manifest_version"]),
                license_state=str(local_package["license_state"]),
                runtime_kind=str(local_package["runtime_kind"]),
                runtime_version=(
                    None
                    if local_package["runtime_version"] is None
                    else str(local_package["runtime_version"])
                ),
            )
        else:
            snapshot_matches_probe = (
                probe_row is not None
                and tool_snapshot is not None
                and tool_snapshot.source == "remote_probe"
                and tool_snapshot.plan_revision == str(row["plan_revision"])
                and tool_snapshot.protocol_version == str(probe_row["protocol_version"])
                and tool_snapshot.tool_count == int(probe_row["tool_count"])
                and tool_snapshot.schema_digest == str(probe_row["schema_digest"])
            )
            last_probe = (
                None
                if probe_row is None
                else SqliteMcpManagedServerRepository._probe(
                    probe_row,
                    retained=snapshot_matches_probe,
                )
            )
            local_evidence = None
        rollback_generation: McpManagedLocalRollbackGeneration | None = None
        if generation_row is not None:
            generation_json = str(generation_row["generation_json"])
            if _text_digest(generation_json) != str(
                generation_row["generation_digest"]
            ):
                raise McpManagedServerError("mcp_managed_storage_corrupt")
            try:
                rollback_generation = (
                    McpManagedLocalRollbackGeneration.model_validate_json(
                        generation_json
                    )
                )
            except ValueError:
                raise McpManagedServerError("mcp_managed_storage_corrupt") from None
            if (
                rollback_generation.generation_id
                != str(generation_row["generation_id"])
                or rollback_generation.plan_revision
                != str(generation_row["plan_revision"])
                or rollback_generation.server_version
                != str(generation_row["server_version"])
                or rollback_generation.local_package_evidence.tree_digest
                != str(generation_row["tree_digest"])
            ):
                raise McpManagedServerError("mcp_managed_storage_corrupt")
        return McpManagedServer(
            management_id=str(row["management_id"]),
            catalog_id=str(row["catalog_id"]),
            server_name=str(row["server_name"]),
            server_title=str(row["server_title"]),
            server_version=str(row["server_version"]),
            server_status_at_review=str(row["server_status_at_review"]),
            option_id=str(row["option_id"]),
            plan_revision=str(row["plan_revision"]),
            option_kind=str(row["option_kind"]),
            option_label=str(row["option_label"]),
            registry_type=None if row["registry_type"] is None else str(row["registry_type"]),
            package_identifier=(
                None if row["package_identifier"] is None else str(row["package_identifier"])
            ),
            package_version=None if row["package_version"] is None else str(row["package_version"]),
            runtime_hint=None if row["runtime_hint"] is None else str(row["runtime_hint"]),
            transport=str(row["transport"]),
            endpoint_host=None if row["endpoint_host"] is None else str(row["endpoint_host"]),
            endpoint_state=str(row["endpoint_state"]),
            secure_transport=(
                None if row["secure_transport"] is None else bool(row["secure_transport"])
            ),
            required_permissions=required_permissions,
            risks=risks,
            requirements=tuple(requirements),
            project_bindings=tuple(bindings),
            created_at=_time(str(row["created_at"])),
            updated_at=_time(str(row["updated_at"])),
            revision=int(row["revision"]),
            lifecycle_state=str(lifecycle["lifecycle_state"]),
            installation_state=str(lifecycle["installation_state"]),
            installation_kind=str(lifecycle["installation_kind"]),
            operation_state=(
                "installing"
                if local_package is not None
                and str(local_package["status"]) == "installing"
                else "uninstalling"
                if local_operation is not None
                and str(local_operation["action"]) == "uninstall"
                and str(local_operation["status"]) in {"reserved", "prepared"}
                else "updating"
                if local_operation is not None
                and str(local_operation["action"]) == "update"
                and str(local_operation["status"]) in {"reserved", "prepared"}
                else "rolling_back"
                if local_operation is not None
                and str(local_operation["action"]) == "rollback"
                and str(local_operation["status"]) in {"reserved", "prepared"}
                else "cleaning_up"
                if local_operation is not None
                and str(local_operation["action"]) == "cleanup"
                and str(local_operation["status"]) in {"reserved", "prepared"}
                else "cleanup_required"
                if (
                    local_package is not None
                    and str(local_package["status"]) == "cleanup_required"
                )
                or (
                    local_operation is not None
                    and str(local_operation["status"]) == "cleanup_required"
                )
                else str(lifecycle["operation_state"])
            ),
            installed_plan_revision=(
                None
                if lifecycle["installed_plan_revision"] is None
                else str(lifecycle["installed_plan_revision"])
            ),
            installed_at=(
                None
                if lifecycle["installed_at"] is None
                else _time(str(lifecycle["installed_at"]))
            ),
            local_package_evidence=local_evidence,
            local_configuration_inspection=configuration_inspection,
            rollback_generation=rollback_generation,
            process_tree_cleanup=str(lifecycle["process_tree_cleanup"]),
            host_state=str(row["host_state"]),
            health_state="not_checked" if last_probe is None else "compatible",
            last_health_checked_at=(
                None if last_probe is None else last_probe.checked_at
            ),
            last_probe=last_probe,
            tool_snapshot=(
                None
                if tool_snapshot is None
                else McpManagedToolSnapshotSummary.model_validate(
                    tool_snapshot.model_dump(mode="python", exclude={"tools", "management_id", "contract_version"})
                )
            ),
            tool_review_state=(
                "reviewable" if tool_snapshot is not None else "probe_required"
            ),
            update_state=str(row["update_state"]),
            latest_available_version=None,
            tool_routing_state=str(row["tool_routing_state"]),
        )

    @staticmethod
    def _probe(
        row: sqlite3.Row,
        *,
        retained: bool = False,
    ) -> McpManagedHostProbe:
        return McpManagedHostProbe(
            request_id=str(row["request_id"]),
            checked_at=_time(str(row["checked_at"])),
            transport=str(row["transport"]),
            protocol_version=str(row["protocol_version"]),
            tool_count=int(row["tool_count"]),
            schema_digest=str(row["schema_digest"]),
            elapsed_ms=int(row["elapsed_ms"]),
            process_started=bool(row["process_started"]),
            process_tree_cleanup=str(row["process_tree_cleanup"]),
            tool_names_persisted=retained,
            tool_schemas_persisted=retained,
        )

    @staticmethod
    def _required_permissions(row: sqlite3.Row) -> tuple[McpManagedPermission, ...]:
        return cast(
            tuple[McpManagedPermission, ...],
            _json_tuple(
                row["required_permissions_json"],
                allowed=set(_PERMISSIONS),
                maximum=5,
            ),
        )

    @staticmethod
    def _server_row(
        connection: sqlite3.Connection,
        management_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM mcp_managed_servers WHERE management_id=?",
            (management_id,),
        ).fetchone()
        if row is None:
            raise McpManagedServerError("mcp_managed_server_not_found")
        return row

    @staticmethod
    def _request_is_unused(connection: sqlite3.Connection, request_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM mcp_managed_servers WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_mutations WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_probe_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_local_packages WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_local_configuration_inspections "
                "WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_local_operations WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_local_recovery_attempts "
                "WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
            and connection.execute(
                "SELECT 1 FROM mcp_managed_local_swap_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            is None
        )

    @staticmethod
    def _mutation_replay(
        connection: sqlite3.Connection,
        *,
        request_id: str,
        request_fingerprint: str,
        action: str,
        management_id: str,
        target_id: str,
    ) -> McpManagedServer | None:
        row = connection.execute(
            "SELECT * FROM mcp_managed_mutations WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is None:
            if connection.execute(
                "SELECT 1 FROM mcp_managed_servers WHERE request_id=?",
                (request_id,),
            ).fetchone() is not None:
                raise McpManagedServerError("mcp_managed_request_conflict")
            if connection.execute(
                "SELECT 1 FROM mcp_managed_probe_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone() is not None:
                raise McpManagedServerError("mcp_managed_request_conflict")
            if connection.execute(
                "SELECT 1 FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                (request_id,),
            ).fetchone() is not None:
                raise McpManagedServerError("mcp_managed_request_conflict")
            return None
        if (
            str(row["request_fingerprint"]) != request_fingerprint
            or str(row["action"]) != action
            or str(row["management_id"]) != management_id
            or str(row["target_id"]) != target_id
        ):
            raise McpManagedServerError("mcp_managed_request_conflict")
        record = SqliteMcpManagedServerRepository._server(
            connection, management_id
        )
        if record is None:
            raise McpManagedServerError("mcp_managed_server_not_found")
        if record.revision != int(row["resulting_revision"]):
            raise McpManagedServerError("mcp_managed_replay_stale")
        return record

    @staticmethod
    def _append_mutation(
        connection: sqlite3.Connection,
        *,
        request_id: str,
        request_fingerprint: str,
        action: str,
        management_id: str,
        target_id: str,
        resulting_revision: int,
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO mcp_managed_mutations(
                request_id,request_fingerprint,action,management_id,target_id,
                resulting_revision,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                request_id,
                request_fingerprint,
                action,
                management_id,
                target_id,
                resulting_revision,
                _iso(created_at),
            ),
        )
        connection.execute(
            """
            DELETE FROM mcp_managed_mutations
            WHERE request_id IN (
                SELECT request_id FROM mcp_managed_mutations
                WHERE management_id=?
                ORDER BY created_at DESC, request_id DESC
                LIMIT -1 OFFSET 64
            )
            """,
            (management_id,),
        )

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
    ) -> tuple[McpManagedServer, bool]:
        if not 1 <= limit <= MAX_MCP_MANAGED_SERVERS:
            raise McpManagedServerError("mcp_managed_limit_invalid")
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    replay = connection.execute(
                        "SELECT * FROM mcp_managed_servers WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if replay is not None:
                        if str(replay["request_fingerprint"]) != request_fingerprint:
                            raise McpManagedServerError("mcp_managed_request_conflict")
                        record = self._server(connection, str(replay["management_id"]))
                        if record is None:
                            raise McpManagedServerError("mcp_managed_storage_corrupt")
                        connection.execute("COMMIT")
                        return record, True
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    if int(connection.execute(
                        "SELECT COUNT(*) FROM mcp_managed_servers"
                    ).fetchone()[0]) >= limit:
                        raise McpManagedServerError("too_many_mcp_managed_servers")
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_servers WHERE catalog_id=? AND option_id=?",
                        (command.catalog_id, command.option_id),
                    ).fetchone() is not None:
                        raise McpManagedServerError("mcp_managed_server_exists")
                    stamp = _iso(created_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_servers(
                            management_id,request_id,request_fingerprint,catalog_id,
                            server_name,server_title,server_version,server_status_at_review,
                            option_id,plan_revision,option_kind,option_label,registry_type,
                            package_identifier,package_version,runtime_hint,transport,
                            endpoint_host,endpoint_state,secure_transport,
                            required_permissions_json,risks_json,created_at,updated_at,
                            revision,lifecycle_state,installation_state,host_state,
                            health_state,last_health_checked_at,update_state,
                            latest_available_version,tool_routing_state
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,
                                  'planned','not_installed','not_started','not_checked',
                                  NULL,'not_checked',NULL,'inactive')
                        """,
                        (
                            management_id,
                            command.request_id,
                            request_fingerprint,
                            command.catalog_id,
                            review.server.name,
                            review.server.title,
                            review.server.version,
                            review.server.status,
                            option.option_id,
                            review.plan_revision,
                            option.kind,
                            option.label,
                            option.registry_type,
                            option.package_identifier,
                            option.package_version,
                            option.runtime_hint,
                            option.transport,
                            option.endpoint_host,
                            option.endpoint_state,
                            None if option.secure_transport is None else int(option.secure_transport),
                            _canonical_json(required_permissions),
                            _canonical_json(option.risks),
                            stamp,
                            stamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_lifecycle_state(
                            management_id,lifecycle_state,installation_state,
                            installation_kind,operation_state,
                            installed_plan_revision,installed_at,
                            process_tree_cleanup,last_error_code,updated_at
                        ) VALUES (?, 'planned','not_installed','none','idle',
                                  NULL,NULL,'not_applicable',NULL,?)
                        """,
                        (management_id, stamp),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_tool_snapshot_state(
                            management_id,snapshot_id,updated_at
                        ) VALUES (?,NULL,?)
                        """,
                        (management_id, stamp),
                    )
                    for index, requirement in enumerate(option.requirements):
                        connection.execute(
                            """
                            INSERT INTO mcp_managed_requirements(
                                management_id,requirement_id,requirement_order,location,
                                name,required,secret,value_format,user_value_needed,
                                fixed_value_declared,default_declared
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                management_id,
                                requirement.requirement_id,
                                index,
                                requirement.location,
                                requirement.name,
                                int(requirement.required),
                                int(requirement.secret),
                                requirement.format,
                                int(requirement.user_value_needed),
                                int(requirement.fixed_value_declared),
                                int(requirement.default_declared),
                            ),
                        )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_create_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, str] | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT management_id,request_fingerprint
                    FROM mcp_managed_servers WHERE request_id=?
                    """,
                    (request_id,),
                ).fetchone()
                if row is None:
                    return None
                record = self._server(connection, str(row["management_id"]))
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                return record, str(row["request_fingerprint"])
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def list_servers(self, *, limit: int) -> Sequence[McpManagedServer]:
        if not 1 <= limit <= MAX_MCP_MANAGED_SERVERS:
            raise McpManagedServerError("mcp_managed_limit_invalid")
        try:
            with self._database.connect() as connection:
                ids = connection.execute(
                    """
                    SELECT management_id FROM mcp_managed_servers
                    ORDER BY updated_at DESC, management_id LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                records = [self._server(connection, str(row[0])) for row in ids]
                if any(record is None for record in records):
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                return tuple(cast(McpManagedServer, record) for record in records)
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_server(self, management_id: str) -> McpManagedServer | None:
        try:
            with self._database.connect() as connection:
                return self._server(connection, management_id)
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_tool_snapshot(
        self,
        management_id: str,
    ) -> McpManagedToolSnapshot | None:
        try:
            with self._database.connect() as connection:
                if connection.execute(
                    "SELECT 1 FROM mcp_managed_servers WHERE management_id=?",
                    (management_id,),
                ).fetchone() is None:
                    return None
                return self._tool_snapshot(connection, management_id)
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_secret_reference(
        self,
        management_id: str,
        requirement_id: str,
    ) -> str | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT reference_id FROM mcp_managed_secret_references
                    WHERE management_id=? AND requirement_id=?
                      AND reference_state='active'
                    """,
                    (management_id, requirement_id),
                ).fetchone()
                return None if row is None else str(row["reference_id"])
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_local_configuration_inspection_request(
        self,
        request_id: str,
    ) -> tuple[
        McpManagedServer,
        McpManagedLocalConfigurationInspection,
        str,
        str,
    ] | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_local_configuration_inspections "
                    "WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    if not self._request_is_unused(connection, request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    return None
                record = self._server(connection, str(row["management_id"]))
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(row["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                inspection = self._configuration_inspection(row)
                if record.local_configuration_inspection != inspection:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                return (
                    record,
                    inspection,
                    str(row["request_fingerprint"]),
                    str(row["preview_digest"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

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
    ]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_local_configuration_inspections "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) != management_id
                            or str(existing["request_fingerprint"])
                            != request_fingerprint
                            or str(existing["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError(
                                "mcp_managed_storage_corrupt"
                            )
                        if record.revision != int(existing["resulting_revision"]):
                            raise McpManagedServerError("mcp_managed_replay_stale")
                        inspection = self._configuration_inspection(existing)
                        connection.execute("COMMIT")
                        return record, inspection, True
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    row = self._server_row(connection, management_id)
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if lifecycle is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if (
                        str(row["option_kind"]) != "local_package"
                        or str(row["registry_type"]) != "mcpb"
                        or str(row["transport"]) != "stdio"
                        or str(lifecycle["installation_state"]) != "not_installed"
                        or str(lifecycle["operation_state"]) != "idle"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_configuration_inspection_transition_conflict"
                        )
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_configuration_inspections "
                        "WHERE management_id=? AND current_state=1",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_configuration_already_inspected"
                        )
                    existing_requirements = connection.execute(
                        "SELECT requirement_id FROM mcp_managed_requirements "
                        "WHERE management_id=? ORDER BY requirement_order",
                        (management_id,),
                    ).fetchall()
                    existing_ids = {
                        str(item["requirement_id"])
                        for item in existing_requirements
                    }
                    result_ids = tuple(
                        item.requirement_id for item in result.requirements
                    )
                    if (
                        len(existing_requirements) + len(result.requirements) > 64
                        or existing_ids & set(result_ids)
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_configuration_schema_invalid"
                        )

                    required_permissions = list(self._required_permissions(row))
                    if any(
                        item.format == "filepath" for item in result.requirements
                    ) and "filesystem_read" not in required_permissions:
                        required_permissions.append("filesystem_read")
                    if any(item.secret for item in result.requirements) and (
                        "credential_use" not in required_permissions
                    ):
                        required_permissions.append("credential_use")
                    required_permissions = [
                        item for item in _PERMISSIONS if item in required_permissions
                    ]
                    prior_permissions = self._required_permissions(row)
                    permissions_expanded = tuple(required_permissions) != prior_permissions

                    risks = list(
                        _json_tuple(row["risks_json"], allowed=_RISKS, maximum=8)
                    )
                    discovered_risks = (
                        (
                            "command_arguments_declared"
                            if any(
                                item.location == "package_argument"
                                for item in result.requirements
                            )
                            else None
                        ),
                        (
                            "filesystem_input_declared"
                            if any(
                                item.format == "filepath"
                                for item in result.requirements
                            )
                            else None
                        ),
                        (
                            "credential_input_declared"
                            if any(item.secret for item in result.requirements)
                            else None
                        ),
                    )
                    for risk in discovered_risks:
                        if risk is not None and risk not in risks:
                            risks.append(risk)

                    next_revision = int(row["revision"]) + 1
                    stamp = _iso(inspected_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_configuration_inspections(
                            management_id,request_id,request_fingerprint,
                            preview_digest,plan_revision,artifact_sha256,
                            artifact_bytes,manifest_digest,manifest_version,
                            configuration_schema_digest,requirement_ids_json,
                            resulting_revision,inspected_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            management_id,
                            command.request_id,
                            request_fingerprint,
                            command.preview_digest,
                            str(row["plan_revision"]),
                            result.artifact_sha256,
                            result.artifact_bytes,
                            result.manifest_digest,
                            result.manifest_version,
                            result.configuration_schema_digest,
                            _canonical_json(result_ids),
                            next_revision,
                            stamp,
                        ),
                    )
                    start_order = len(existing_requirements)
                    for offset, requirement in enumerate(result.requirements):
                        connection.execute(
                            """
                            INSERT INTO mcp_managed_requirements(
                                management_id,requirement_id,requirement_order,
                                location,name,required,secret,value_format,
                                user_value_needed,fixed_value_declared,
                                default_declared
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                management_id,
                                requirement.requirement_id,
                                start_order + offset,
                                requirement.location,
                                requirement.key,
                                int(requirement.required),
                                int(requirement.secret),
                                requirement.format,
                                int(requirement.user_value_needed),
                                0,
                                int(requirement.default_declared),
                            ),
                        )
                    if permissions_expanded:
                        connection.execute(
                            "DELETE FROM mcp_managed_project_tools "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_project_bindings
                            SET enabled=0,granted_permissions_json='[]',
                                updated_at=?,revision=revision+1
                            WHERE management_id=?
                              AND (enabled=1 OR granted_permissions_json!='[]')
                            """,
                            (stamp, management_id),
                        )
                    connection.execute(
                        """
                        UPDATE mcp_managed_servers
                        SET required_permissions_json=?,risks_json=?,
                            updated_at=?,revision=?
                        WHERE management_id=?
                        """,
                        (
                            _canonical_json(required_permissions),
                            _canonical_json(risks),
                            stamp,
                            next_revision,
                            management_id,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if (
                        record is None
                        or record.local_configuration_inspection is None
                    ):
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return (
                        record,
                        record.local_configuration_inspection,
                        False,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_probe_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, McpManagedHostProbe, str] | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_probe_receipts WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_servers WHERE request_id=?",
                        (request_id,),
                    ).fetchone() is not None or connection.execute(
                        "SELECT 1 FROM mcp_managed_mutations WHERE request_id=?",
                        (request_id,),
                    ).fetchone() is not None or connection.execute(
                        "SELECT 1 FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                        (request_id,),
                    ).fetchone() is not None or connection.execute(
                        "SELECT 1 FROM mcp_managed_local_configuration_inspections "
                        "WHERE request_id=?",
                        (request_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    return None
                record = self._server(connection, str(row["management_id"]))
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(row["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                retained = connection.execute(
                    "SELECT 1 FROM mcp_managed_tool_snapshots "
                    "WHERE management_id=? AND observation_id=?",
                    (str(row["management_id"]), request_id),
                ).fetchone() is not None
                return (
                    record,
                    self._probe(row, retained=retained),
                    str(row["request_fingerprint"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def record_probe(
        self,
        management_id: str,
        *,
        command: ProbeMcpManagedServer,
        request_fingerprint: str,
        result: McpHostProbeResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, McpManagedHostProbe, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_probe_receipts WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) != management_id
                            or str(existing["request_fingerprint"])
                            != request_fingerprint
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError(
                                "mcp_managed_storage_corrupt"
                            )
                        if record.revision != int(existing["resulting_revision"]):
                            raise McpManagedServerError("mcp_managed_replay_stale")
                        retained = connection.execute(
                            "SELECT 1 FROM mcp_managed_tool_snapshots "
                            "WHERE management_id=? AND observation_id=?",
                            (management_id, command.request_id),
                        ).fetchone() is not None
                        connection.execute("COMMIT")
                        return (
                            record,
                            self._probe(existing, retained=retained),
                            True,
                        )
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if str(row["transport"]) != result.transport:
                        raise McpManagedServerError("mcp_managed_probe_plan_changed")
                    next_revision = int(row["revision"]) + 1
                    stamp = _iso(checked_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_probe_receipts(
                            request_id,request_fingerprint,management_id,
                            resulting_revision,checked_at,transport,
                            protocol_version,tool_count,schema_digest,elapsed_ms,
                            process_started,process_tree_cleanup
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            next_revision,
                            stamp,
                            result.transport,
                            result.protocol_version,
                            result.tool_count,
                            result.schema_digest,
                            result.elapsed_ms,
                            int(result.process_started),
                            result.process_tree_cleanup,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_servers
                        SET updated_at=?,revision=? WHERE management_id=?
                        """,
                        (stamp, next_revision, management_id),
                    )
                    self._store_tool_snapshot(
                        connection,
                        management_id,
                        observation_id=command.request_id,
                        plan_revision=str(row["plan_revision"]),
                        source_tree_digest=None,
                        source_manifest_digest=None,
                        result=result,
                        reviewed_at=checked_at,
                    )
                    connection.execute(
                        """
                        DELETE FROM mcp_managed_probe_receipts
                        WHERE request_id IN (
                            SELECT request_id FROM mcp_managed_probe_receipts
                            WHERE management_id=?
                            ORDER BY resulting_revision DESC, request_id DESC
                            LIMIT -1 OFFSET 32
                        )
                        """,
                        (management_id,),
                    )
                    record = self._server(connection, management_id)
                    if record is None or record.last_probe is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, record.last_probe, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_lifecycle_request(
        self,
        request_id: str,
    ) -> tuple[
        McpManagedServer,
        Literal["install", "uninstall"],
        str,
        str,
    ] | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    if not self._request_is_unused(connection, request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    return None
                record = self._server(connection, str(row["management_id"]))
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(row["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                return (
                    record,
                    cast(Literal["install", "uninstall"], str(row["action"])),
                    str(row["request_fingerprint"]),
                    str(row["preview_digest"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def apply_remote_activation(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        action: Literal["install", "uninstall"],
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) != management_id
                            or str(existing["action"]) != action
                            or str(existing["request_fingerprint"])
                            != request_fingerprint
                            or str(existing["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError(
                                "mcp_managed_storage_corrupt"
                            )
                        if record.revision != int(existing["resulting_revision"]):
                            raise McpManagedServerError("mcp_managed_replay_stale")
                        connection.execute("COMMIT")
                        return record, True
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if str(row["option_kind"]) != "remote_server":
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if lifecycle is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    current_state = str(lifecycle["installation_state"])
                    expected_state = "not_installed" if action == "install" else "installed"
                    if current_state != expected_state or str(
                        lifecycle["operation_state"]
                    ) != "idle":
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    next_revision = int(row["revision"]) + 1
                    if action == "install":
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='installed',
                                installation_state='installed',
                                installation_kind='remote_activation',
                                operation_state='idle',installed_plan_revision=?,
                                installed_at=?,process_tree_cleanup='not_applicable',
                                last_error_code=NULL,updated_at=?
                            WHERE management_id=?
                            """,
                            (str(row["plan_revision"]), stamp, stamp, management_id),
                        )
                        resulting_state = "installed"
                    else:
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='planned',
                                installation_state='not_installed',
                                installation_kind='none',operation_state='idle',
                                installed_plan_revision=NULL,installed_at=NULL,
                                process_tree_cleanup='not_applicable',
                                last_error_code=NULL,updated_at=?
                            WHERE management_id=?
                            """,
                            (stamp, management_id),
                        )
                        connection.execute(
                            "DELETE FROM mcp_managed_project_tools "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                        resulting_state = "not_installed"
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, next_revision, management_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_lifecycle_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,
                            resulting_installation_state,created_at
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            action,
                            command.preview_digest,
                            next_revision,
                            resulting_state,
                            stamp,
                        ),
                    )
                    connection.execute(
                        """
                        DELETE FROM mcp_managed_lifecycle_receipts
                        WHERE request_id IN (
                            SELECT request_id FROM mcp_managed_lifecycle_receipts
                            WHERE management_id=?
                            ORDER BY resulting_revision DESC, request_id DESC
                            LIMIT -1 OFFSET 64
                        )
                        """,
                        (management_id,),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_install(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) == management_id
                            and str(existing["request_fingerprint"])
                            == request_fingerprint
                            and str(existing["preview_digest"])
                            == command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_operation_in_progress"
                            )
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if str(row["option_kind"]) != "local_package":
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        lifecycle is None
                        or str(lifecycle["installation_state"]) != "not_installed"
                        or str(lifecycle["operation_state"]) != "idle"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_packages(
                            management_id,request_id,request_fingerprint,
                            preview_digest,status,artifact_sha256,artifact_bytes,
                            tree_digest,manifest_digest,manifest_version,
                            license_state,runtime_kind,runtime_version,checked_at,
                            protocol_version,tool_count,schema_digest,elapsed_ms,
                            process_tree_cleanup,error_code,created_at,updated_at
                        ) VALUES (?,?,?,?, 'installing', NULL,NULL,NULL,NULL,NULL,
                                  NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,
                                  'not_applicable',NULL,?,?)
                        """,
                        (
                            management_id,
                            command.request_id,
                            request_fingerprint,
                            command.preview_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_install(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        result: McpLocalPackageInstallResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    receipt = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_receipts WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            str(receipt["management_id"]) != management_id
                            or str(receipt["action"]) != "install"
                            or str(receipt["request_fingerprint"])
                            != request_fingerprint
                            or str(receipt["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None or record.revision != int(
                            receipt["resulting_revision"]
                        ):
                            raise McpManagedServerError("mcp_managed_replay_stale")
                        connection.execute("COMMIT")
                        return record, True
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or str(operation["request_id"]) != command.request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["preview_digest"])
                        != command.preview_digest
                        or str(operation["status"]) != "installing"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        lifecycle is None
                        or str(lifecycle["installation_state"]) != "not_installed"
                        or str(lifecycle["operation_state"]) != "idle"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(checked_at)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_packages
                        SET status='installed',artifact_sha256=?,artifact_bytes=?,
                            tree_digest=?,manifest_digest=?,manifest_version=?,
                            license_state=?,runtime_kind=?,runtime_version=?,
                            checked_at=?,protocol_version=?,tool_count=?,
                            schema_digest=?,elapsed_ms=?,
                            process_tree_cleanup='verified',error_code=NULL,
                            updated_at=?
                        WHERE management_id=? AND status='installing'
                        """,
                        (
                            result.artifact_sha256,
                            result.artifact_bytes,
                            result.tree_digest,
                            result.manifest_digest,
                            result.manifest_version,
                            result.license_state,
                            result.runtime_kind,
                            result.runtime_version,
                            stamp,
                            result.probe.protocol_version,
                            result.probe.tool_count,
                            result.probe.schema_digest,
                            result.probe.elapsed_ms,
                            stamp,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='installed',installation_state='installed',
                            installation_kind='local_package',operation_state='idle',
                            installed_plan_revision=?,installed_at=?,
                            process_tree_cleanup='verified',last_error_code=NULL,
                            updated_at=?
                        WHERE management_id=?
                        """,
                        (str(row["plan_revision"]), stamp, stamp, management_id),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET revision=?,updated_at=? "
                        "WHERE management_id=?",
                        (next_revision, stamp, management_id),
                    )
                    self._store_tool_snapshot(
                        connection,
                        management_id,
                        observation_id=command.request_id,
                        plan_revision=str(row["plan_revision"]),
                        source_tree_digest=result.tree_digest,
                        source_manifest_digest=result.manifest_digest,
                        result=result.probe,
                        reviewed_at=checked_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_lifecycle_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,
                            resulting_installation_state,created_at
                        ) VALUES (?,?,?,'install',?,?, 'installed',?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

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
    ) -> None:
        safe_error = (
            error_code
            if re.fullmatch(r"[a-z][a-z0-9_]{2,95}", error_code)
            else "mcp_package_install_failed"
        )
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if operation is None:
                        connection.execute("COMMIT")
                        return
                    if (
                        str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                    ):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    if str(operation["status"]) != "installing":
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    if cleanup_required:
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_packages
                            SET status='cleanup_required',process_tree_cleanup=?,
                                error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (
                                process_tree_cleanup,
                                safe_error,
                                stamp,
                                management_id,
                            ),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup=?,last_error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (
                                process_tree_cleanup,
                                safe_error,
                                stamp,
                                management_id,
                            ),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? WHERE management_id=?",
                            (stamp, management_id),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM mcp_managed_local_packages "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_uninstall(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) == management_id
                            and str(existing["request_fingerprint"])
                            == request_fingerprint
                            and str(existing["preview_digest"])
                            == command.preview_digest
                            and str(existing["action"]) == "uninstall"
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_operation_in_progress"
                            )
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        str(row["option_kind"]) != "local_package"
                        or lifecycle is None
                        or str(lifecycle["installation_state"]) != "installed"
                        or str(lifecycle["installation_kind"]) != "local_package"
                        or str(lifecycle["operation_state"]) != "idle"
                        or package is None
                        or str(package["status"]) != "installed"
                        or str(package["tree_digest"]) != expected_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_operations(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,expected_revision,expected_tree_digest,
                            status,error_code,created_at,updated_at
                        ) VALUES (?,?,?,'uninstall',?,?,?,'reserved',NULL,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            command.expected_revision,
                            expected_tree_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def mark_local_uninstall_prepared(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "uninstall"
                        or str(operation["status"]) != "reserved"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    connection.execute(
                        "UPDATE mcp_managed_local_operations "
                        "SET status='prepared',updated_at=? WHERE management_id=?",
                        (_iso(updated_at), management_id),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_uninstall(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLifecycle,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or str(operation["request_id"]) != command.request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["preview_digest"])
                        != command.preview_digest
                        or str(operation["action"]) != "uninstall"
                        or str(operation["status"]) != "prepared"
                        or str(operation["expected_tree_digest"])
                        != expected_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        int(row["revision"]) != command.expected_revision
                        or package is None
                        or str(package["status"]) != "installed"
                        or str(package["tree_digest"]) != expected_tree_digest
                        or lifecycle is None
                        or str(lifecycle["installation_state"]) != "installed"
                        or str(lifecycle["installation_kind"]) != "local_package"
                        or str(lifecycle["operation_state"]) != "idle"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "DELETE FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='planned',
                            installation_state='not_installed',
                            installation_kind='none',operation_state='idle',
                            installed_plan_revision=NULL,installed_at=NULL,
                            process_tree_cleanup='not_applicable',
                            last_error_code=NULL,updated_at=?
                        WHERE management_id=?
                        """,
                        (stamp, management_id),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET revision=?,updated_at=? "
                        "WHERE management_id=?",
                        (next_revision, stamp, management_id),
                    )
                    self._set_current_tool_snapshot(
                        connection,
                        management_id,
                        snapshot_id=None,
                        updated_at=updated_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_lifecycle_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,
                            resulting_installation_state,created_at
                        ) VALUES (?,?,?,'uninstall',?,?,'not_installed',?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    connection.execute(
                        """
                        DELETE FROM mcp_managed_lifecycle_receipts
                        WHERE request_id IN (
                            SELECT request_id FROM mcp_managed_lifecycle_receipts
                            WHERE management_id=?
                            ORDER BY resulting_revision DESC, request_id DESC
                            LIMIT -1 OFFSET 64
                        )
                        """,
                        (management_id,),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def fail_local_uninstall(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        error_code: str,
        cleanup_required: bool,
        updated_at: datetime,
    ) -> None:
        safe_error = (
            error_code
            if re.fullmatch(r"[a-z][a-z0-9_]{2,95}", error_code)
            else "mcp_package_uninstall_failed"
        )
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if operation is None:
                        connection.execute("COMMIT")
                        return
                    if (
                        str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "uninstall"
                    ):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    stamp = _iso(updated_at)
                    if cleanup_required:
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_operations
                            SET status='cleanup_required',error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (safe_error, stamp, management_id),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup='verified',
                                last_error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (safe_error, stamp, management_id),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? WHERE management_id=?",
                            (stamp, management_id),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM mcp_managed_local_operations "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_local_operation(
        self,
        management_id: str,
    ) -> McpManagedLocalOperationRecovery | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    "SELECT request_id,action,status,expected_tree_digest "
                    "FROM mcp_managed_local_operations WHERE management_id=?",
                    (management_id,),
                ).fetchone()
                if row is None:
                    return None
                action = str(row["action"])
                if str(row["status"]) != "cleanup_required" or action not in {
                    "update",
                    "uninstall",
                    "rollback",
                    "cleanup",
                }:
                    return None
                alternate: str | None = None
                if action == "update":
                    payload = connection.execute(
                        "SELECT target_tree_digest FROM "
                        "mcp_managed_local_update_payloads "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if payload is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    if payload["target_tree_digest"] is not None:
                        alternate = str(payload["target_tree_digest"])
                elif action == "rollback":
                    generation = connection.execute(
                        "SELECT tree_digest FROM "
                        "mcp_managed_local_rollback_generations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if generation is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    alternate = str(generation["tree_digest"])
                return McpManagedLocalOperationRecovery(
                    operation_id=str(row["request_id"]),
                    action=action,
                    status="cleanup_required",
                    expected_tree_digest=str(row["expected_tree_digest"]),
                    alternate_tree_digest=alternate,
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_uninstall_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalCleanup,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_receipts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) != management_id
                            or str(existing["action"]) != "uninstall"
                            or str(existing["request_fingerprint"])
                            != request_fingerprint
                            or str(existing["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError(
                                "mcp_managed_storage_corrupt"
                            )
                        if record.revision != int(existing["resulting_revision"]):
                            raise McpManagedServerError(
                                "mcp_managed_replay_stale"
                            )
                        connection.execute("COMMIT")
                        return record, True
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    journal = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        journal is None
                        or str(journal["request_id"]) != operation.operation_id
                        or str(journal["action"]) != "uninstall"
                        or str(journal["status"]) != "cleanup_required"
                        or str(journal["expected_tree_digest"])
                        != operation.expected_tree_digest
                        or package is None
                        or str(package["status"]) != "installed"
                        or str(package["tree_digest"])
                        != operation.expected_tree_digest
                        or lifecycle is None
                        or str(lifecycle["installation_state"])
                        != "cleanup_required"
                        or str(lifecycle["operation_state"])
                        != "cleanup_required"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_cleanup_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "DELETE FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='planned',
                            installation_state='not_installed',
                            installation_kind='none',operation_state='idle',
                            installed_plan_revision=NULL,installed_at=NULL,
                            process_tree_cleanup='not_applicable',
                            last_error_code=NULL,updated_at=?
                        WHERE management_id=?
                        """,
                        (stamp, management_id),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET revision=?,updated_at=? "
                        "WHERE management_id=?",
                        (next_revision, stamp, management_id),
                    )
                    self._set_current_tool_snapshot(
                        connection,
                        management_id,
                        snapshot_id=None,
                        updated_at=updated_at,
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_lifecycle_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,
                            resulting_installation_state,created_at
                        ) VALUES (?,?,?,'uninstall',?,?,'not_installed',?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_local_update_request(
        self,
        request_id: str,
    ) -> tuple[McpManagedServer, str, str] | None:
        """Return one durable update receipt without replaying package work."""

        try:
            with self._database.connect() as connection:
                receipt = connection.execute(
                    "SELECT * FROM mcp_managed_local_swap_receipts "
                    "WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if receipt is None:
                    return None
                if str(receipt["action"]) != "update":
                    raise McpManagedServerError("mcp_managed_request_conflict")
                record = self._server(
                    connection, str(receipt["management_id"])
                )
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(receipt["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                return (
                    record,
                    str(receipt["request_fingerprint"]),
                    str(receipt["preview_digest"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_update(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalUpdate,
        request_fingerprint: str,
        target: McpManagedLocalUpdateTarget,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        """Reserve one exact old-plan/target-plan transition."""

        target_json = _model_json(target)
        target_digest = _text_digest(target_json)
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) == management_id
                            and str(existing["action"]) == "update"
                            and str(existing["request_fingerprint"])
                            == request_fingerprint
                            and str(existing["preview_digest"])
                            == command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_operation_in_progress"
                            )
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if not self._request_is_unused(
                        connection, command.request_id
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError(
                            "mcp_managed_revision_conflict"
                        )
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    requirement_count = int(
                        connection.execute(
                            "SELECT count(*) FROM mcp_managed_requirements "
                            "WHERE management_id=?",
                            (management_id,),
                        ).fetchone()[0]
                    )
                    if (
                        str(row["option_kind"]) != "local_package"
                        or str(row["registry_type"]) != "mcpb"
                        or str(row["transport"]) != "stdio"
                        or lifecycle is None
                        or str(lifecycle["installation_state"]) != "installed"
                        or str(lifecycle["installation_kind"])
                        != "local_package"
                        or str(lifecycle["operation_state"]) != "idle"
                        or str(lifecycle["installed_plan_revision"])
                        != str(row["plan_revision"])
                        or package is None
                        or str(package["status"]) != "installed"
                        or str(package["tree_digest"])
                        != expected_tree_digest
                        or requirement_count != 0
                        or connection.execute(
                            "SELECT 1 FROM "
                            "mcp_managed_local_rollback_generations "
                            "WHERE management_id=?",
                            (management_id,),
                        ).fetchone()
                        is not None
                        or target.server_name != str(row["server_name"])
                        or target.server_status_at_review != "active"
                        or target.plan_revision == str(row["plan_revision"])
                        or target.required_permissions
                        != self._required_permissions(row)
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_update_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_operations(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,expected_revision,expected_tree_digest,
                            status,error_code,created_at,updated_at
                        ) VALUES (?,?,?,'update',?,?,?,'reserved',NULL,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            command.expected_revision,
                            expected_tree_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_update_payloads(
                            request_id,management_id,target_plan_json,
                            target_plan_digest,target_result_json,
                            target_result_digest,target_tree_digest,
                            created_at,updated_at
                        ) VALUES (?,?,?,?,NULL,NULL,NULL,?,?)
                        """,
                        (
                            command.request_id,
                            management_id,
                            target_json,
                            target_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def mark_local_update_staged(
        self,
        management_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        result: McpLocalPackageStagedUpdateResult,
        updated_at: datetime,
    ) -> McpManagedServer:
        """Bind verified staging evidence before any directory swap."""

        result_json = _install_result_json(result)
        result_digest = _text_digest(result_json)
        if (
            result.probe.transport != "stdio"
            or not result.probe.process_started
            or result.probe.process_tree_cleanup != "verified"
        ):
            raise McpManagedServerError("mcp_managed_update_evidence_invalid")
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    payload = connection.execute(
                        "SELECT * FROM mcp_managed_local_update_payloads "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or payload is None
                        or str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "update"
                        or str(payload["request_id"]) != request_id
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_update_transition_conflict"
                        )
                    status = str(operation["status"])
                    if status == "prepared":
                        if (
                            str(payload["target_result_json"]) == result_json
                            and str(payload["target_result_digest"])
                            == result_digest
                            and str(payload["target_tree_digest"])
                            == result.tree_digest
                        ):
                            record = self._server(connection, management_id)
                            if record is None:
                                raise McpManagedServerError(
                                    "mcp_managed_storage_corrupt"
                                )
                            connection.execute("COMMIT")
                            return record
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if status != "reserved":
                        raise McpManagedServerError(
                            "mcp_managed_update_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_update_payloads
                        SET target_result_json=?,target_result_digest=?,
                            target_tree_digest=?,updated_at=?
                        WHERE management_id=? AND request_id=?
                        """,
                        (
                            result_json,
                            result_digest,
                            result.tree_digest,
                            stamp,
                            management_id,
                            request_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_operations
                        SET status='prepared',updated_at=?
                        WHERE management_id=? AND request_id=?
                        """,
                        (stamp, management_id, request_id),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_update(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalUpdate,
        request_fingerprint: str,
        target: McpManagedLocalUpdateTarget,
        result: McpLocalPackageStagedUpdateResult,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        """Commit exact target metadata after the filesystem swap succeeded."""

        target_json = _model_json(target)
        result_json = _install_result_json(result)
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    receipt = connection.execute(
                        "SELECT * FROM mcp_managed_local_swap_receipts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            str(receipt["management_id"]) != management_id
                            or str(receipt["action"]) != "update"
                            or str(receipt["request_fingerprint"])
                            != request_fingerprint
                            or str(receipt["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if (
                            record is None
                            or record.revision
                            != int(receipt["resulting_revision"])
                            or record.plan_revision != target.plan_revision
                            or record.local_package_evidence is None
                            or record.local_package_evidence.tree_digest
                            != result.tree_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_replay_stale"
                            )
                        connection.execute("COMMIT")
                        return record, True
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    payload = connection.execute(
                        "SELECT * FROM mcp_managed_local_update_payloads "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or payload is None
                        or str(operation["request_id"]) != command.request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "update"
                        or str(operation["status"]) != "prepared"
                        or str(operation["preview_digest"])
                        != command.preview_digest
                        or int(operation["expected_revision"])
                        != command.expected_revision
                        or str(payload["request_id"]) != command.request_id
                        or str(payload["target_plan_json"]) != target_json
                        or str(payload["target_plan_digest"])
                        != _text_digest(target_json)
                        or str(payload["target_result_json"]) != result_json
                        or str(payload["target_result_digest"])
                        != _text_digest(result_json)
                        or str(payload["target_tree_digest"])
                        != result.tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_update_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    current = self._server(connection, management_id)
                    if (
                        int(row["revision"]) != command.expected_revision
                        or lifecycle is None
                        or package is None
                        or current is None
                        or current.local_package_evidence is None
                        or current.last_probe is None
                        or current.installed_at is None
                        or current.rollback_generation is not None
                        or current.requirements
                        or str(lifecycle["installation_state"])
                        != "installed"
                        or str(lifecycle["installation_kind"])
                        != "local_package"
                        or str(lifecycle["installed_plan_revision"])
                        != str(row["plan_revision"])
                        or str(package["status"]) != "installed"
                        or str(package["tree_digest"])
                        != str(operation["expected_tree_digest"])
                        or target.server_name != current.server_name
                        or target.server_status_at_review != "active"
                        or target.plan_revision == current.plan_revision
                        or target.required_permissions
                        != current.required_permissions
                        or result.probe.transport != "stdio"
                        or not result.probe.process_started
                        or result.probe.process_tree_cleanup != "verified"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_update_transition_conflict"
                        )
                    stamp = _iso(checked_at)
                    generation = McpManagedLocalRollbackGeneration(
                        catalog_id=current.catalog_id,
                        server_name=current.server_name,
                        server_title=current.server_title,
                        server_version=current.server_version,
                        server_status_at_review=current.server_status_at_review,
                        option_id=current.option_id,
                        plan_revision=current.plan_revision,
                        option_label=current.option_label,
                        registry_type="mcpb",
                        package_identifier=cast(str, current.package_identifier),
                        package_version=current.package_version,
                        runtime_hint=current.runtime_hint,
                        transport="stdio",
                        required_permissions=current.required_permissions,
                        risks=current.risks,
                        generation_id=command.request_id,
                        local_package_evidence=current.local_package_evidence,
                        probe=current.last_probe,
                        installed_at=current.installed_at,
                        retained_at=checked_at,
                    )
                    generation_json = _model_json(generation)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_rollback_generations(
                            management_id,generation_id,generation_json,
                            generation_digest,plan_revision,server_version,
                            tree_digest,retained_at
                        ) VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            management_id,
                            generation.generation_id,
                            generation_json,
                            _text_digest(generation_json),
                            generation.plan_revision,
                            generation.server_version,
                            generation.local_package_evidence.tree_digest,
                            stamp,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_servers
                        SET catalog_id=?,server_title=?,server_version=?,
                            server_status_at_review=?,option_id=?,plan_revision=?,
                            option_label=?,registry_type='mcpb',
                            package_identifier=?,package_version=?,runtime_hint=?,
                            transport='stdio',endpoint_host=NULL,
                            endpoint_state='not_applicable',secure_transport=NULL,
                            required_permissions_json=?,risks_json=?,
                            updated_at=?,revision=?
                        WHERE management_id=?
                        """,
                        (
                            target.catalog_id,
                            target.server_title,
                            target.server_version,
                            target.server_status_at_review,
                            target.option_id,
                            target.plan_revision,
                            target.option_label,
                            target.package_identifier,
                            target.package_version,
                            target.runtime_hint,
                            json.dumps(list(target.required_permissions)),
                            json.dumps(list(target.risks)),
                            stamp,
                            next_revision,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_packages
                        SET request_id=?,request_fingerprint=?,preview_digest=?,
                            status='installed',artifact_sha256=?,artifact_bytes=?,
                            tree_digest=?,manifest_digest=?,manifest_version=?,
                            license_state=?,runtime_kind=?,runtime_version=?,
                            checked_at=?,protocol_version=?,tool_count=?,
                            schema_digest=?,elapsed_ms=?,
                            process_tree_cleanup='verified',error_code=NULL,
                            created_at=?,updated_at=?
                        WHERE management_id=? AND status='installed'
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            command.preview_digest,
                            result.artifact_sha256,
                            result.artifact_bytes,
                            result.tree_digest,
                            result.manifest_digest,
                            result.manifest_version,
                            result.license_state,
                            result.runtime_kind,
                            result.runtime_version,
                            stamp,
                            result.probe.protocol_version,
                            result.probe.tool_count,
                            result.probe.schema_digest,
                            result.probe.elapsed_ms,
                            stamp,
                            stamp,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='installed',
                            installation_state='installed',
                            installation_kind='local_package',
                            operation_state='idle',installed_plan_revision=?,
                            installed_at=?,process_tree_cleanup='verified',
                            last_error_code=NULL,updated_at=?
                        WHERE management_id=?
                        """,
                        (
                            target.plan_revision,
                            stamp,
                            stamp,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_swap_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,created_at
                        ) VALUES (?,?,?,'update',?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    self._store_tool_snapshot(
                        connection,
                        management_id,
                        observation_id=command.request_id,
                        plan_revision=target.plan_revision,
                        source_tree_digest=result.tree_digest,
                        source_manifest_digest=result.manifest_digest,
                        result=result.probe,
                        reviewed_at=checked_at,
                    )
                    connection.execute(
                        """
                        DELETE FROM mcp_managed_local_swap_receipts
                        WHERE request_id IN (
                            SELECT request_id
                            FROM mcp_managed_local_swap_receipts
                            WHERE management_id=?
                            ORDER BY resulting_revision DESC, request_id DESC
                            LIMIT -1 OFFSET 64
                        )
                        """,
                        (management_id,),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_local_configuration_inspections "
                        "SET current_state=0 "
                        "WHERE management_id=? AND current_state=1",
                        (management_id,),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error, ValueError):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

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
    ) -> None:
        """Release a compensated update or persist an explicit recovery state."""

        safe_error = (
            error_code
            if re.fullmatch(r"[a-z][a-z0-9_]{2,95}", error_code)
            else "mcp_package_update_failed"
        )
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if operation is None:
                        connection.execute("COMMIT")
                        return
                    if (
                        str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "update"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    stamp = _iso(updated_at)
                    if cleanup_required:
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_operations
                            SET status='cleanup_required',error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (safe_error, stamp, management_id),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup=?,last_error_code=?,
                                updated_at=?
                            WHERE management_id=?
                            """,
                            (
                                process_tree_cleanup,
                                safe_error,
                                stamp,
                                management_id,
                            ),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? "
                            "WHERE management_id=?",
                            (stamp, management_id),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM mcp_managed_local_operations "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_local_swap_request(
        self,
        request_id: str,
        *,
        action: Literal["rollback", "cleanup"],
    ) -> tuple[McpManagedServer, str, str] | None:
        try:
            with self._database.connect() as connection:
                receipt = connection.execute(
                    "SELECT * FROM mcp_managed_local_swap_receipts "
                    "WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if receipt is None:
                    return None
                if str(receipt["action"]) != action:
                    raise McpManagedServerError("mcp_managed_request_conflict")
                record = self._server(
                    connection, str(receipt["management_id"])
                )
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(receipt["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                return (
                    record,
                    str(receipt["request_fingerprint"]),
                    str(receipt["preview_digest"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_rollback(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollback,
        request_fingerprint: str,
        expected_current_tree_digest: str,
        expected_rollback_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if not self._request_is_unused(
                        connection, command.request_id
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    record = self._server(connection, management_id)
                    if (
                        int(row["revision"]) != command.expected_revision
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_revision_conflict"
                        )
                    if (
                        record is None
                        or record.option_kind != "local_package"
                        or record.registry_type != "mcpb"
                        or record.transport != "stdio"
                        or record.installation_state != "installed"
                        or record.operation_state != "idle"
                        or record.local_package_evidence is None
                        or record.rollback_generation is None
                        or record.requirements
                        or lifecycle is None
                        or str(lifecycle["installation_kind"])
                        != "local_package"
                        or package is None
                        or str(package["status"]) != "installed"
                        or record.local_package_evidence.tree_digest
                        != expected_current_tree_digest
                        or record.rollback_generation.local_package_evidence.tree_digest
                        != expected_rollback_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_rollback_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_operations(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,expected_revision,expected_tree_digest,
                            status,error_code,created_at,updated_at
                        ) VALUES (?,?,?,'rollback',?,?,?,'prepared',NULL,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            command.expected_revision,
                            expected_current_tree_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_rollback(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollback,
        request_fingerprint: str,
        checked_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    receipt = connection.execute(
                        "SELECT * FROM mcp_managed_local_swap_receipts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            str(receipt["management_id"]) != management_id
                            or str(receipt["action"]) != "rollback"
                            or str(receipt["request_fingerprint"])
                            != request_fingerprint
                            or str(receipt["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None or record.revision != int(
                            receipt["resulting_revision"]
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_replay_stale"
                            )
                        connection.execute("COMMIT")
                        return record, True
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    row = self._server_row(connection, management_id)
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    current = self._server(connection, management_id)
                    if (
                        operation is None
                        or str(operation["request_id"]) != command.request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "rollback"
                        or str(operation["status"]) != "prepared"
                        or str(operation["preview_digest"])
                        != command.preview_digest
                        or int(operation["expected_revision"])
                        != command.expected_revision
                        or int(row["revision"]) != command.expected_revision
                        or lifecycle is None
                        or package is None
                        or current is None
                        or current.local_package_evidence is None
                        or current.rollback_generation is None
                        or current.last_probe is None
                        or current.installed_at is None
                        or current.requirements
                        or str(package["status"]) != "installed"
                        or current.local_package_evidence.tree_digest
                        != str(operation["expected_tree_digest"])
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_rollback_transition_conflict"
                        )
                    target = current.rollback_generation
                    stamp = _iso(checked_at)
                    superseded = McpManagedLocalRollbackGeneration(
                        catalog_id=current.catalog_id,
                        server_name=current.server_name,
                        server_title=current.server_title,
                        server_version=current.server_version,
                        server_status_at_review=current.server_status_at_review,
                        option_id=current.option_id,
                        plan_revision=current.plan_revision,
                        option_label=current.option_label,
                        registry_type="mcpb",
                        package_identifier=cast(str, current.package_identifier),
                        package_version=current.package_version,
                        runtime_hint=current.runtime_hint,
                        transport="stdio",
                        required_permissions=current.required_permissions,
                        risks=current.risks,
                        generation_id=command.request_id,
                        local_package_evidence=current.local_package_evidence,
                        probe=current.last_probe,
                        installed_at=current.installed_at,
                        retained_at=checked_at,
                    )
                    superseded_json = _model_json(superseded)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        """
                        UPDATE mcp_managed_servers
                        SET catalog_id=?,server_title=?,server_version=?,
                            server_status_at_review=?,option_id=?,plan_revision=?,
                            option_label=?,registry_type='mcpb',
                            package_identifier=?,package_version=?,runtime_hint=?,
                            transport='stdio',endpoint_host=NULL,
                            endpoint_state='not_applicable',secure_transport=NULL,
                            required_permissions_json=?,risks_json=?,
                            updated_at=?,revision=?
                        WHERE management_id=?
                        """,
                        (
                            target.catalog_id,
                            target.server_title,
                            target.server_version,
                            target.server_status_at_review,
                            target.option_id,
                            target.plan_revision,
                            target.option_label,
                            target.package_identifier,
                            target.package_version,
                            target.runtime_hint,
                            json.dumps(list(target.required_permissions)),
                            json.dumps(list(target.risks)),
                            stamp,
                            next_revision,
                            management_id,
                        ),
                    )
                    target_evidence = target.local_package_evidence
                    target_probe = target.probe
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_packages
                        SET request_id=?,request_fingerprint=?,preview_digest=?,
                            status='installed',artifact_sha256=?,artifact_bytes=?,
                            tree_digest=?,manifest_digest=?,manifest_version=?,
                            license_state=?,runtime_kind=?,runtime_version=?,
                            checked_at=?,protocol_version=?,tool_count=?,
                            schema_digest=?,elapsed_ms=?,
                            process_tree_cleanup='verified',error_code=NULL,
                            created_at=?,updated_at=?
                        WHERE management_id=? AND status='installed'
                        """,
                        (
                            target_probe.request_id,
                            request_fingerprint,
                            command.preview_digest,
                            target_evidence.artifact_sha256,
                            target_evidence.artifact_bytes,
                            target_evidence.tree_digest,
                            target_evidence.manifest_digest,
                            target_evidence.manifest_version,
                            target_evidence.license_state,
                            target_evidence.runtime_kind,
                            target_evidence.runtime_version,
                            _iso(target_probe.checked_at),
                            target_probe.protocol_version,
                            target_probe.tool_count,
                            target_probe.schema_digest,
                            target_probe.elapsed_ms,
                            _iso(target.installed_at),
                            stamp,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='installed',
                            installation_state='installed',
                            installation_kind='local_package',
                            operation_state='idle',installed_plan_revision=?,
                            installed_at=?,process_tree_cleanup='verified',
                            last_error_code=NULL,updated_at=?
                        WHERE management_id=?
                        """,
                        (target.plan_revision, stamp, stamp, management_id),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_local_rollback_generations
                        SET generation_id=?,generation_json=?,generation_digest=?,
                            plan_revision=?,server_version=?,tree_digest=?,
                            retained_at=?
                        WHERE management_id=?
                        """,
                        (
                            superseded.generation_id,
                            superseded_json,
                            _text_digest(superseded_json),
                            superseded.plan_revision,
                            superseded.server_version,
                            superseded.local_package_evidence.tree_digest,
                            stamp,
                            management_id,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_swap_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,created_at
                        ) VALUES (?,?,?,'rollback',?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    self._activate_tool_snapshot_for_tree(
                        connection,
                        management_id,
                        plan_revision=target.plan_revision,
                        tree_digest=target_evidence.tree_digest,
                        manifest_digest=target_evidence.manifest_digest,
                        updated_at=checked_at,
                    )
                    connection.execute(
                        "UPDATE mcp_managed_local_configuration_inspections "
                        "SET current_state=0 "
                        "WHERE management_id=? AND current_state=1",
                        (management_id,),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_local_configuration_inspections "
                        "SET current_state=1 "
                        "WHERE request_id=("
                        "SELECT request_id "
                        "FROM mcp_managed_local_configuration_inspections "
                        "WHERE management_id=? AND plan_revision=? "
                        "ORDER BY inspected_at DESC LIMIT 1)",
                        (management_id, target.plan_revision),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error, ValueError):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_rollback_cleanup(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollbackCleanup,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> McpManagedServer:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if not self._request_is_unused(
                        connection, command.request_id
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_lifecycle_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    record = self._server(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError(
                            "mcp_managed_revision_conflict"
                        )
                    if (
                        record is None
                        or record.option_kind != "local_package"
                        or record.installation_state != "installed"
                        or record.operation_state != "idle"
                        or record.local_package_evidence is None
                        or record.rollback_generation is None
                        or record.rollback_generation.local_package_evidence.tree_digest
                        != expected_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_rollback_cleanup_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_operations(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,expected_revision,expected_tree_digest,
                            status,error_code,created_at,updated_at
                        ) VALUES (?,?,?,'cleanup',?,?,?,'prepared',NULL,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            command.expected_revision,
                            expected_tree_digest,
                            stamp,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_rollback_cleanup(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalRollbackCleanup,
        request_fingerprint: str,
        expected_tree_digest: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    receipt = connection.execute(
                        "SELECT * FROM mcp_managed_local_swap_receipts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            str(receipt["management_id"]) != management_id
                            or str(receipt["action"]) != "cleanup"
                            or str(receipt["request_fingerprint"])
                            != request_fingerprint
                            or str(receipt["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None or record.revision != int(
                            receipt["resulting_revision"]
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_replay_stale"
                            )
                        connection.execute("COMMIT")
                        return record, True
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    row = self._server_row(connection, management_id)
                    generation = connection.execute(
                        "SELECT * FROM mcp_managed_local_rollback_generations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if (
                        operation is None
                        or str(operation["request_id"]) != command.request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != "cleanup"
                        or str(operation["status"]) != "prepared"
                        or str(operation["preview_digest"])
                        != command.preview_digest
                        or int(operation["expected_revision"])
                        != command.expected_revision
                        or int(row["revision"]) != command.expected_revision
                        or str(operation["expected_tree_digest"])
                        != expected_tree_digest
                        or generation is None
                        or str(generation["tree_digest"])
                        != expected_tree_digest
                        or package is None
                        or str(package["status"]) != "installed"
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_rollback_cleanup_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "DELETE FROM mcp_managed_local_rollback_generations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='installed',
                            installation_state='installed',
                            installation_kind='local_package',
                            operation_state='idle',process_tree_cleanup='verified',
                            last_error_code=NULL,updated_at=?
                        WHERE management_id=?
                        """,
                        (stamp, management_id),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET revision=?,updated_at=? "
                        "WHERE management_id=?",
                        (next_revision, stamp, management_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_swap_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,created_at
                        ) VALUES (?,?,?,'cleanup',?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

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
    ) -> None:
        safe_error = (
            error_code
            if re.fullmatch(r"[a-z][a-z0-9_]{2,95}", error_code)
            else "mcp_package_local_swap_failed"
        )
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    operation = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if operation is None:
                        connection.execute("COMMIT")
                        return
                    if (
                        str(operation["request_id"]) != request_id
                        or str(operation["request_fingerprint"])
                        != request_fingerprint
                        or str(operation["action"]) != action
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    stamp = _iso(updated_at)
                    if cleanup_required:
                        connection.execute(
                            """
                            UPDATE mcp_managed_local_operations
                            SET status='cleanup_required',error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (safe_error, stamp, management_id),
                        )
                        connection.execute(
                            """
                            UPDATE mcp_managed_lifecycle_state
                            SET lifecycle_state='cleanup_required',
                                installation_state='cleanup_required',
                                installation_kind='local_package',
                                operation_state='cleanup_required',
                                process_tree_cleanup='verified',
                                last_error_code=?,updated_at=?
                            WHERE management_id=?
                            """,
                            (safe_error, stamp, management_id),
                        )
                        connection.execute(
                            "UPDATE mcp_managed_servers "
                            "SET revision=revision+1,updated_at=? "
                            "WHERE management_id=?",
                            (stamp, management_id),
                        )
                    else:
                        connection.execute(
                            "DELETE FROM mcp_managed_local_operations "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def get_local_recovery_request(
        self,
        request_id: str,
    ) -> tuple[
        McpManagedServer,
        Literal["update", "rollback", "cleanup"],
        str,
        str,
    ] | None:
        try:
            with self._database.connect() as connection:
                receipt = connection.execute(
                    "SELECT * FROM mcp_managed_local_swap_receipts "
                    "WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if receipt is None:
                    return None
                action_by_receipt = {
                    "recover_update": "update",
                    "recover_rollback": "rollback",
                    "recover_cleanup": "cleanup",
                }
                action = action_by_receipt.get(str(receipt["action"]))
                if action is None:
                    raise McpManagedServerError(
                        "mcp_managed_request_conflict"
                    )
                record = self._server(
                    connection, str(receipt["management_id"])
                )
                if record is None:
                    raise McpManagedServerError("mcp_managed_storage_corrupt")
                if record.revision != int(receipt["resulting_revision"]):
                    raise McpManagedServerError("mcp_managed_replay_stale")
                return (
                    record,
                    cast(Literal["update", "rollback", "cleanup"], action),
                    str(receipt["request_fingerprint"]),
                    str(receipt["preview_digest"]),
                )
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def begin_local_operation_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalOperationRecovery,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> McpManagedLocalOperationRecovery:
        if operation.action == "uninstall":
            raise McpManagedServerError(
                "mcp_managed_recovery_transition_conflict"
            )
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = connection.execute(
                        "SELECT * FROM mcp_managed_local_recovery_attempts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if existing is not None:
                        if (
                            str(existing["management_id"]) != management_id
                            or str(existing["operation_id"])
                            != operation.operation_id
                            or str(existing["action"]) != operation.action
                            or str(existing["request_fingerprint"])
                            != request_fingerprint
                            or str(existing["preview_digest"])
                            != command.preview_digest
                            or int(existing["expected_revision"])
                            != command.expected_revision
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        connection.execute("COMMIT")
                        return operation
                    if not self._request_is_unused(
                        connection, command.request_id
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_request_conflict"
                        )
                    if connection.execute(
                        "SELECT 1 FROM mcp_managed_local_recovery_attempts "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone() is not None:
                        raise McpManagedServerError(
                            "mcp_managed_recovery_transition_conflict"
                        )
                    row = self._server_row(connection, management_id)
                    journal = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError(
                            "mcp_managed_revision_conflict"
                        )
                    if (
                        journal is None
                        or str(journal["request_id"])
                        != operation.operation_id
                        or str(journal["action"]) != operation.action
                        or str(journal["status"]) != "cleanup_required"
                        or str(journal["expected_tree_digest"])
                        != operation.expected_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_recovery_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_recovery_attempts(
                            request_id,request_fingerprint,management_id,
                            operation_id,action,preview_digest,
                            expected_revision,created_at,updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            operation.operation_id,
                            operation.action,
                            command.preview_digest,
                            command.expected_revision,
                            stamp,
                            stamp,
                        ),
                    )
                    connection.execute("COMMIT")
                    return operation
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_local_operation_recovery(
        self,
        management_id: str,
        *,
        command: ApplyMcpManagedLocalOperationRecovery,
        request_fingerprint: str,
        operation: McpManagedLocalOperationRecovery,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        if operation.action == "uninstall":
            raise McpManagedServerError(
                "mcp_managed_recovery_transition_conflict"
            )
        receipt_action = f"recover_{operation.action}"
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    receipt = connection.execute(
                        "SELECT * FROM mcp_managed_local_swap_receipts "
                        "WHERE request_id=?",
                        (command.request_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            str(receipt["management_id"]) != management_id
                            or str(receipt["action"]) != receipt_action
                            or str(receipt["request_fingerprint"])
                            != request_fingerprint
                            or str(receipt["preview_digest"])
                            != command.preview_digest
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_request_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None or record.revision != int(
                            receipt["resulting_revision"]
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_replay_stale"
                            )
                        connection.execute("COMMIT")
                        return record, True
                    journal = connection.execute(
                        "SELECT * FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    attempt = connection.execute(
                        "SELECT * FROM mcp_managed_local_recovery_attempts "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    row = self._server_row(connection, management_id)
                    lifecycle = connection.execute(
                        "SELECT * FROM mcp_managed_lifecycle_state "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    package = connection.execute(
                        "SELECT * FROM mcp_managed_local_packages "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    generation = connection.execute(
                        "SELECT * FROM mcp_managed_local_rollback_generations "
                        "WHERE management_id=?",
                        (management_id,),
                    ).fetchone()
                    generation_expected = operation.action in {
                        "rollback",
                        "cleanup",
                    }
                    evidence_matches = (
                        generation is not None
                        and str(generation["tree_digest"])
                        == operation.expected_tree_digest
                        if operation.action == "cleanup"
                        else package is not None
                        and str(package["status"]) == "installed"
                        and str(package["tree_digest"])
                        == operation.expected_tree_digest
                    )
                    current_package_present = (
                        package is not None
                        and str(package["status"]) == "installed"
                    )
                    if (
                        int(row["revision"]) != command.expected_revision
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_revision_conflict"
                        )
                    if (
                        journal is None
                        or attempt is None
                        or str(attempt["request_id"]) != command.request_id
                        or str(attempt["request_fingerprint"])
                        != request_fingerprint
                        or str(attempt["operation_id"])
                        != operation.operation_id
                        or str(attempt["action"]) != operation.action
                        or str(attempt["preview_digest"])
                        != command.preview_digest
                        or int(attempt["expected_revision"])
                        != command.expected_revision
                        or str(journal["request_id"])
                        != operation.operation_id
                        or str(journal["action"]) != operation.action
                        or str(journal["status"]) != "cleanup_required"
                        or str(journal["expected_tree_digest"])
                        != operation.expected_tree_digest
                        or lifecycle is None
                        or str(lifecycle["installation_state"])
                        != "cleanup_required"
                        or str(lifecycle["operation_state"])
                        != "cleanup_required"
                        or not current_package_present
                        or not evidence_matches
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_recovery_transition_conflict"
                        )
                    if generation_expected != (generation is not None):
                        raise McpManagedServerError(
                            "mcp_managed_recovery_transition_conflict"
                        )
                    if operation.action == "rollback" and (
                        operation.alternate_tree_digest is None
                        or str(generation["tree_digest"])
                        != operation.alternate_tree_digest
                    ):
                        raise McpManagedServerError(
                            "mcp_managed_recovery_transition_conflict"
                        )
                    stamp = _iso(updated_at)
                    next_revision = int(row["revision"]) + 1
                    if operation.action == "cleanup":
                        connection.execute(
                            "DELETE FROM mcp_managed_local_rollback_generations "
                            "WHERE management_id=?",
                            (management_id,),
                        )
                    connection.execute(
                        "DELETE FROM mcp_managed_local_operations "
                        "WHERE management_id=?",
                        (management_id,),
                    )
                    connection.execute(
                        """
                        UPDATE mcp_managed_lifecycle_state
                        SET lifecycle_state='installed',
                            installation_state='installed',
                            installation_kind='local_package',
                            operation_state='idle',installed_plan_revision=?,
                            process_tree_cleanup='verified',last_error_code=NULL,
                            updated_at=?
                        WHERE management_id=?
                        """,
                        (str(row["plan_revision"]), stamp, management_id),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET revision=?,updated_at=? "
                        "WHERE management_id=?",
                        (next_revision, stamp, management_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO mcp_managed_local_swap_receipts(
                            request_id,request_fingerprint,management_id,action,
                            preview_digest,resulting_revision,created_at
                        ) VALUES (?,?,?,?,?,?,?)
                        """,
                        (
                            command.request_id,
                            request_fingerprint,
                            management_id,
                            receipt_action,
                            command.preview_digest,
                            next_revision,
                            stamp,
                        ),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError(
                            "mcp_managed_storage_corrupt"
                        )
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def set_project_binding(
        self,
        management_id: str,
        project_id: str,
        *,
        command: SetMcpManagedProjectBinding,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    replay = self._mutation_replay(
                        connection,
                        request_id=command.request_id,
                        request_fingerprint=request_fingerprint,
                        action="set_project_binding",
                        management_id=management_id,
                        target_id=project_id,
                    )
                    if replay is not None:
                        connection.execute("COMMIT")
                        return replay, True
                    row = self._server_row(connection, management_id)
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    project = connection.execute(
                        "SELECT archived_at FROM agent_projects WHERE project_id=?",
                        (project_id,),
                    ).fetchone()
                    if project is None:
                        raise McpManagedServerError("mcp_managed_project_not_found")
                    if project["archived_at"] is not None:
                        raise McpManagedServerError("mcp_managed_project_archived")
                    required = self._required_permissions(row)
                    expected = required if command.enabled else ()
                    if command.granted_permissions != expected:
                        raise McpManagedServerError("mcp_managed_permission_grants_incomplete")
                    tool_snapshot = self._tool_snapshot(connection, management_id)
                    if command.enabled:
                        if tool_snapshot is None:
                            raise McpManagedServerError(
                                "mcp_managed_tool_review_required"
                            )
                        if not command.admitted_tool_ids:
                            raise McpManagedServerError(
                                "mcp_managed_tool_admission_required"
                            )
                        available = {item.tool_id for item in tool_snapshot.tools}
                        if any(
                            tool_id not in available
                            for tool_id in command.admitted_tool_ids
                        ):
                            raise McpManagedServerError(
                                "mcp_managed_tool_admission_stale"
                            )
                    existing = connection.execute(
                        """
                        SELECT revision,created_at FROM mcp_managed_project_bindings
                        WHERE management_id=? AND project_id=?
                        """,
                        (management_id, project_id),
                    ).fetchone()
                    stamp = _iso(updated_at)
                    if existing is None:
                        connection.execute(
                            """
                            INSERT INTO mcp_managed_project_bindings(
                                management_id,project_id,enabled,
                                granted_permissions_json,created_at,updated_at,revision
                            ) VALUES (?,?,?,?,?,?,1)
                            """,
                            (
                                management_id,
                                project_id,
                                int(command.enabled),
                                _canonical_json(command.granted_permissions),
                                stamp,
                                stamp,
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE mcp_managed_project_bindings
                            SET enabled=?,granted_permissions_json=?,updated_at=?,revision=?
                            WHERE management_id=? AND project_id=?
                            """,
                            (
                                int(command.enabled),
                                _canonical_json(command.granted_permissions),
                                stamp,
                                int(existing["revision"]) + 1,
                                management_id,
                                project_id,
                            ),
                        )
                    connection.execute(
                        "DELETE FROM mcp_managed_project_tools "
                        "WHERE management_id=? AND project_id=?",
                        (management_id, project_id),
                    )
                    if command.enabled:
                        assert tool_snapshot is not None
                        for tool_id in command.admitted_tool_ids:
                            connection.execute(
                                """
                                INSERT INTO mcp_managed_project_tools(
                                    management_id,project_id,snapshot_id,
                                    tool_id,admitted_at
                                ) VALUES (?,?,?,?,?)
                                """,
                                (
                                    management_id,
                                    project_id,
                                    tool_snapshot.snapshot_id,
                                    tool_id,
                                    stamp,
                                ),
                            )
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, next_revision, management_id),
                    )
                    self._append_mutation(
                        connection,
                        request_id=command.request_id,
                        request_fingerprint=request_fingerprint,
                        action="set_project_binding",
                        management_id=management_id,
                        target_id=project_id,
                        resulting_revision=next_revision,
                        created_at=updated_at,
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def reserve_secret(
        self,
        management_id: str,
        requirement_id: str,
        *,
        command: McpManagedVaultStoreCommand,
        request_fingerprint: str,
        reference_id: str,
        vault_provider: str,
        updated_at: datetime,
    ) -> SecretReservation:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    replay = self._mutation_replay(
                        connection,
                        request_id=command.request_id,
                        request_fingerprint=request_fingerprint,
                        action="store_secret",
                        management_id=management_id,
                        target_id=requirement_id,
                    )
                    if replay is not None:
                        reference = connection.execute(
                            """
                            SELECT reference_id,reference_state,vault_provider
                            FROM mcp_managed_secret_references
                            WHERE management_id=? AND requirement_id=?
                            """,
                            (management_id, requirement_id),
                        ).fetchone()
                        if reference is None or str(reference["reference_state"]) != "active":
                            raise McpManagedServerError("mcp_managed_replay_stale")
                        if (
                            str(reference["reference_id"]) != reference_id
                            or str(reference["vault_provider"]) != vault_provider
                        ):
                            raise McpManagedServerError("mcp_managed_storage_corrupt")
                        connection.execute("COMMIT")
                        return SecretReservation(
                            reference_id=str(reference["reference_id"]),
                            state="active",
                            idempotent_replay=True,
                            server=replay,
                        )
                    row = self._server_row(connection, management_id)
                    requirement = connection.execute(
                        """
                        SELECT secret,user_value_needed FROM mcp_managed_requirements
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (management_id, requirement_id),
                    ).fetchone()
                    if requirement is None or not (
                        bool(requirement["secret"])
                        or bool(requirement["user_value_needed"])
                    ):
                        raise McpManagedServerError("mcp_managed_requirement_not_found")
                    existing = connection.execute(
                        """
                        SELECT * FROM mcp_managed_secret_references
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (management_id, requirement_id),
                    ).fetchone()
                    if existing is not None and (
                        str(existing["reference_id"]) != reference_id
                        or str(existing["vault_provider"]) != vault_provider
                    ):
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    if existing is not None and str(existing["request_id"]) == command.request_id:
                        if str(existing["reference_state"]) not in {
                            "pending_store",
                            "store_failed",
                        }:
                            raise McpManagedServerError(
                                "mcp_managed_secret_transition_conflict"
                            )
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError("mcp_managed_storage_corrupt")
                        connection.execute("COMMIT")
                        return SecretReservation(
                            reference_id=reference_id,
                            state=str(existing["reference_state"]),
                            idempotent_replay=True,
                            server=record,
                        )
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if existing is not None:
                        state = str(existing["reference_state"])
                        if state == "active":
                            raise McpManagedServerError("mcp_managed_secret_already_configured")
                        if state != "store_failed":
                            raise McpManagedServerError("mcp_managed_secret_operation_pending")
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    stamp = _iso(updated_at)
                    if existing is None:
                        connection.execute(
                            """
                            INSERT INTO mcp_managed_secret_references(
                                management_id,requirement_id,reference_id,vault_provider,
                                reference_state,request_id,created_at,updated_at,revision
                            ) VALUES (?,?,?,?, 'pending_store',?,?,?,1)
                            """,
                            (
                                management_id,
                                requirement_id,
                                reference_id,
                                vault_provider,
                                command.request_id,
                                stamp,
                                stamp,
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE mcp_managed_secret_references
                            SET reference_state='pending_store',request_id=?,updated_at=?,revision=?
                            WHERE management_id=? AND requirement_id=?
                            """,
                            (
                                command.request_id,
                                stamp,
                                int(existing["revision"]) + 1,
                                management_id,
                                requirement_id,
                            ),
                        )
                    self._invalidate_connection_review(
                        connection,
                        management_id,
                        updated_at=updated_at,
                    )
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, next_revision, management_id),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return SecretReservation(
                        reference_id=reference_id,
                        state="pending_store",
                        idempotent_replay=False,
                        server=record,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_secret_store(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        reference_id: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        return self._finish_secret_transition(
            management_id,
            requirement_id,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            reference_id=reference_id,
            updated_at=updated_at,
            action="store_secret",
            expected_states={"pending_store", "store_failed"},
            final_state="active",
            delete_reference=False,
        )

    def fail_secret_store(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        reference_id: str,
        updated_at: datetime,
    ) -> None:
        self._mark_secret_failure(
            management_id,
            requirement_id,
            request_id=request_id,
            reference_id=reference_id,
            from_states={"pending_store", "store_failed"},
            failure_state="store_failed",
            updated_at=updated_at,
        )

    def begin_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        command: McpManagedVaultRemoveCommand,
        request_fingerprint: str,
        updated_at: datetime,
    ) -> SecretRemoval:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    replay = self._mutation_replay(
                        connection,
                        request_id=command.request_id,
                        request_fingerprint=request_fingerprint,
                        action="remove_secret",
                        management_id=management_id,
                        target_id=requirement_id,
                    )
                    if replay is not None:
                        connection.execute("COMMIT")
                        return SecretRemoval(
                            reference_id=None,
                            state=None,
                            idempotent_replay=True,
                            server=replay,
                        )
                    row = self._server_row(connection, management_id)
                    existing = connection.execute(
                        """
                        SELECT * FROM mcp_managed_secret_references
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (management_id, requirement_id),
                    ).fetchone()
                    if existing is None:
                        raise McpManagedServerError("mcp_managed_secret_not_configured")
                    if str(existing["request_id"]) == command.request_id and str(
                        existing["reference_state"]
                    ) in {"pending_removal", "cleanup_required"}:
                        record = self._server(connection, management_id)
                        if record is None:
                            raise McpManagedServerError("mcp_managed_storage_corrupt")
                        connection.execute("COMMIT")
                        return SecretRemoval(
                            reference_id=str(existing["reference_id"]),
                            state=str(existing["reference_state"]),
                            idempotent_replay=True,
                            server=record,
                        )
                    if int(row["revision"]) != command.expected_revision:
                        raise McpManagedServerError("mcp_managed_revision_conflict")
                    if str(existing["reference_state"]) in {"pending_removal", "cleanup_required"}:
                        raise McpManagedServerError("mcp_managed_secret_operation_pending")
                    if not self._request_is_unused(connection, command.request_id):
                        raise McpManagedServerError("mcp_managed_request_conflict")
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        UPDATE mcp_managed_secret_references
                        SET reference_state='pending_removal',request_id=?,updated_at=?,revision=?
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (
                            command.request_id,
                            stamp,
                            int(existing["revision"]) + 1,
                            management_id,
                            requirement_id,
                        ),
                    )
                    self._invalidate_connection_review(
                        connection,
                        management_id,
                        updated_at=updated_at,
                    )
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, next_revision, management_id),
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return SecretRemoval(
                        reference_id=str(existing["reference_id"]),
                        state="pending_removal",
                        idempotent_replay=False,
                        server=record,
                    )
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def finish_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        reference_id: str,
        updated_at: datetime,
    ) -> tuple[McpManagedServer, bool]:
        return self._finish_secret_transition(
            management_id,
            requirement_id,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            reference_id=reference_id,
            updated_at=updated_at,
            action="remove_secret",
            expected_states={"pending_removal", "cleanup_required"},
            final_state=None,
            delete_reference=True,
        )

    def fail_secret_removal(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        reference_id: str,
        updated_at: datetime,
    ) -> None:
        self._mark_secret_failure(
            management_id,
            requirement_id,
            request_id=request_id,
            reference_id=reference_id,
            from_states={"pending_removal", "cleanup_required"},
            failure_state="cleanup_required",
            updated_at=updated_at,
        )

    def _finish_secret_transition(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        reference_id: str,
        updated_at: datetime,
        action: str,
        expected_states: set[str],
        final_state: str | None,
        delete_reference: bool,
    ) -> tuple[McpManagedServer, bool]:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    replay = self._mutation_replay(
                        connection,
                        request_id=request_id,
                        request_fingerprint=request_fingerprint,
                        action=action,
                        management_id=management_id,
                        target_id=requirement_id,
                    )
                    if replay is not None:
                        connection.execute("COMMIT")
                        return replay, True
                    row = self._server_row(connection, management_id)
                    reference = connection.execute(
                        """
                        SELECT * FROM mcp_managed_secret_references
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (management_id, requirement_id),
                    ).fetchone()
                    if (
                        reference is None
                        or str(reference["request_id"]) != request_id
                        or str(reference["reference_id"]) != reference_id
                        or str(reference["reference_state"]) not in expected_states
                    ):
                        raise McpManagedServerError("mcp_managed_secret_transition_conflict")
                    stamp = _iso(updated_at)
                    if delete_reference:
                        connection.execute(
                            """
                            DELETE FROM mcp_managed_secret_references
                            WHERE management_id=? AND requirement_id=?
                            """,
                            (management_id, requirement_id),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE mcp_managed_secret_references
                            SET reference_state=?,updated_at=?,revision=?
                            WHERE management_id=? AND requirement_id=?
                            """,
                            (
                                final_state,
                                stamp,
                                int(reference["revision"]) + 1,
                                management_id,
                                requirement_id,
                            ),
                        )
                    next_revision = int(row["revision"]) + 1
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, next_revision, management_id),
                    )
                    self._append_mutation(
                        connection,
                        request_id=request_id,
                        request_fingerprint=request_fingerprint,
                        action=action,
                        management_id=management_id,
                        target_id=requirement_id,
                        resulting_revision=next_revision,
                        created_at=updated_at,
                    )
                    record = self._server(connection, management_id)
                    if record is None:
                        raise McpManagedServerError("mcp_managed_storage_corrupt")
                    connection.execute("COMMIT")
                    return record, False
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None

    def _mark_secret_failure(
        self,
        management_id: str,
        requirement_id: str,
        *,
        request_id: str,
        reference_id: str,
        from_states: set[str],
        failure_state: str,
        updated_at: datetime,
    ) -> None:
        try:
            with self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    row = self._server_row(connection, management_id)
                    reference = connection.execute(
                        """
                        SELECT * FROM mcp_managed_secret_references
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (management_id, requirement_id),
                    ).fetchone()
                    if (
                        reference is None
                        or str(reference["request_id"]) != request_id
                        or str(reference["reference_id"]) != reference_id
                        or str(reference["reference_state"]) not in from_states
                    ):
                        connection.execute("ROLLBACK")
                        return
                    stamp = _iso(updated_at)
                    connection.execute(
                        """
                        UPDATE mcp_managed_secret_references
                        SET reference_state=?,updated_at=?,revision=?
                        WHERE management_id=? AND requirement_id=?
                        """,
                        (
                            failure_state,
                            stamp,
                            int(reference["revision"]) + 1,
                            management_id,
                            requirement_id,
                        ),
                    )
                    connection.execute(
                        "UPDATE mcp_managed_servers SET updated_at=?,revision=? WHERE management_id=?",
                        (stamp, int(row["revision"]) + 1, management_id),
                    )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except McpManagedServerError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise McpManagedServerError("mcp_managed_storage_unavailable") from None


__all__ = ("SqliteMcpManagedServerRepository",)
