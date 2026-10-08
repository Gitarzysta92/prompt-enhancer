from __future__ import annotations

import json
from pathlib import Path

from scripts.export_openapi import build_openapi_schema, export_openapi


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_build_time_schema_contains_bounded_queries_and_review_commands() -> None:
    schema = build_openapi_schema()
    paths = schema["paths"]

    assert "/v1/discovery/candidates" in paths
    assert "/v1/tasks/{task_id}/revisions/{revision}" in paths
    assert "/v1/analysis/runs/{run_id}" in paths
    assert "/v1/task-decisions/accept" in paths
    assert "/v1/task-decisions/reject" in paths
    assert "/v1/task-decisions/merge" in paths
    assert "/v1/task-decisions/split" in paths
    assert (
        "/v1/tasks/{task_id}/revisions/{revision}/analysis-runs" in paths
    )
    assert "/v1/sql" not in paths
    assert "/v1/local-sources/codex" in paths
    assert "/v1/local-sources/codex/consents/local-history" in paths
    assert "/v1/local-sources/codex/index" in paths
    assert "/v1/local-sources/codex/analysis" in paths
    assert "/v1/local-sources/codex/display-labels/enrich" in paths
    assert "/v1/catalog/projects/{project_id}/display-label" in paths
    assert "/v1/catalog/sessions/{session_id}/display-label" in paths
    assert "/v1/research/text-analysis-methods" in paths
    assert "/v1/providers/{provider}/capabilities" in paths
    assert "/v1/sessions/{session_id}/metric-readiness" in paths
    verification_base = (
        "/v1/sessions/{session_id}/requirement-verification-evidence"
    )
    assert {
        path for path in paths if path.startswith(verification_base)
    } == {
        f"{verification_base}/opportunity-sets/current",
        (
            f"{verification_base}/opportunity-sets/"
            "{opportunity_set_fingerprint}"
        ),
        f"{verification_base}/objective-results",
        f"{verification_base}/acceptances",
    }
    acceptance_operation = paths[f"{verification_base}/acceptances"]["post"]
    acceptance_parameters = {
        parameter["name"]: parameter
        for parameter in acceptance_operation["parameters"]
    }
    native_proofs = {
        "prompt_enhancer_session",
        "Origin",
        "X-Prompt-Enhancer-CSRF",
        "X-Prompt-Enhancer-User-Presence",
    }
    assert set(acceptance_parameters) == {
        "session_id",
        "Idempotency-Key",
        *native_proofs,
    }
    assert all(
        acceptance_parameters[name]["required"] is True
        for name in native_proofs
    )
    assert acceptance_parameters["prompt_enhancer_session"]["in"] == "cookie"
    assert "X-Prompt-Enhancer-Token" not in acceptance_parameters
    assert "Authorization" not in acceptance_parameters
    assert acceptance_operation["security"] == []
    assert set(acceptance_operation["responses"]) == {
        "200",
        "201",
        "401",
        "403",
        "404",
        "409",
        "422",
        "503",
    }
    response_schema = acceptance_operation["responses"]["422"]["content"][
        "application/json"
    ]["schema"]
    assert {item["$ref"] for item in response_schema["anyOf"]} == {
        "#/components/schemas/RequirementVerificationMessageErrorDto",
        "#/components/schemas/RequirementVerificationServiceErrorDto",
    }
    verification_schema = json.dumps(
        {
            name: value
            for name, value in schema["components"]["schemas"].items()
            if "RequirementVerification" in name
            or "RequirementAcceptance" in name
        }
    ).casefold()
    for prohibited in (
        "assistant_claim",
        "prompt",
        "transcript",
        "excerpt",
        "file_path",
        "raw_content",
        "idempotency_key_digest",
        "command_fingerprint",
    ):
        assert prohibited not in verification_schema
    assert "/v1/analysis-jobs" in paths
    assert "/v1/analysis-jobs/{job_id}" in paths
    assert "/v1/analysis-jobs/{job_id}/cancellation" in paths
    assert "/v1/sessions/{session_id}/analysis-jobs/latest" in paths
    assert set(paths["/v1/estimators/plans"]) == {"get"}
    assert set(paths["/v1/control-plane/readiness"]) == {"get"}
    assert set(paths["/v1/agent/sessions/{session_id}/events/stream"]) == {"get"}
    hardening_path = "/v1/diagnostics/agent-hardening"
    assert set(paths[hardening_path]) == {"get"}
    hardening_response = paths[hardening_path]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert hardening_response == {
        "$ref": "#/components/schemas/AgentHardeningSnapshot"
    }
    hardening_schema = schema["components"]["schemas"]["AgentHardeningSnapshot"]
    assert hardening_schema["properties"]["contract_version"]["const"] == (
        "agent-hardening.v1"
    )
    assert hardening_schema["properties"]["generated_on_demand"]["const"] is True
    assert hardening_schema["properties"]["contains_content"]["const"] is False
    assert set(hardening_schema["properties"]) == {
        "contract_version",
        "generated_on_demand",
        "contains_content",
        "recovery_state",
        "recovery_actions",
        "catalog",
        "live",
    }
    native_acceptance_path = "/v1/diagnostics/agent-native-acceptance/start"
    assert set(paths[native_acceptance_path]) == {"post"}
    native_acceptance_operation = paths[native_acceptance_path]["post"]
    assert native_acceptance_operation["requestBody"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/BeginAgentNativeAcceptance"
    }
    assert native_acceptance_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/AgentNativeAcceptanceStartReceipt"
    }
    native_receipt = schema["components"]["schemas"][
        "AgentNativeAcceptanceStartReceipt"
    ]
    assert set(native_receipt["properties"]) == {
        "contract_version",
        "owner_presence_confirmed",
        "model_execution_started",
        "process_spawn_requested",
        "workspace_access_requested",
        "content_persisted",
        "expires_on_reload",
    }
    assert native_receipt["properties"]["contract_version"]["const"] == (
        "agent-native-acceptance-start.v1"
    )
    for key in (
        "model_execution_started",
        "process_spawn_requested",
        "workspace_access_requested",
        "content_persisted",
    ):
        assert native_receipt["properties"][key]["const"] is False
    assert native_receipt["properties"]["owner_presence_confirmed"]["const"] is True
    assert native_receipt["properties"]["expires_on_reload"]["const"] is True
    discovery_path = "/v1/agent/sessions/{session_id}/workspace/discovery"
    assert set(paths[discovery_path]) == {"get"}
    discovery_schema = schema["components"]["schemas"]["WorkspaceDiscovery"]
    assert discovery_schema["properties"]["contract_version"]["const"] == "local-agent-workspace-discovery.v1"
    serialized_discovery = json.dumps({
        name: value
        for name, value in schema["components"]["schemas"].items()
        if name.startswith("WorkspaceDiscovery") or name.startswith("WorkspaceGit")
    }).casefold()
    for prohibited in ("content", "revision", "sha256", "branch", "remote", "absolute_path", "stderr"):
        assert prohibited not in serialized_discovery
    transaction_preview_path = "/v1/agent/sessions/{session_id}/workspace/transactions"
    transaction_apply_path = (
        "/v1/agent/sessions/{session_id}/workspace/transactions/{plan_id}/apply"
    )
    assert set(paths[transaction_preview_path]) == {"post"}
    assert set(paths[transaction_apply_path]) == {"post"}
    transaction_preview = schema["components"]["schemas"]["WorkspaceTransactionPreview"]
    transaction_apply = schema["components"]["schemas"]["WorkspaceTransactionApplyCommand"]
    assert transaction_preview["additionalProperties"] is False
    assert transaction_preview["properties"]["contract_version"]["const"] == (
        "local-agent-workspace-transaction.v2"
    )
    assert transaction_preview["properties"]["files"]["minItems"] == 2
    assert transaction_preview["properties"]["files"]["maxItems"] == 8
    assert transaction_apply["additionalProperties"] is False
    assert transaction_apply["properties"]["confirmation"]["const"] == (
        "apply_reviewed_workspace_transaction"
    )
    transaction_change = schema["components"]["schemas"][
        "WorkspaceTransactionChangeCommand"
    ]
    assert transaction_change["properties"]["operation"]["enum"] == [
        "create",
        "edit",
    ]
    assert transaction_change["properties"]["expected_revision"]["anyOf"][-1] == {
        "type": "null"
    }
    transaction_file_result = schema["components"]["schemas"][
        "WorkspaceTransactionFileResult"
    ]
    assert "removed" in transaction_file_result["properties"]["state"]["enum"]
    apply_parameters = {
        item["name"]: item
        for item in paths[transaction_apply_path]["post"]["parameters"]
    }
    assert "X-Prompt-Enhancer-User-Presence" in apply_parameters
    assert paths[transaction_apply_path]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/WorkspaceTransactionApplyResult"}
    agent_contract = schema["components"]["schemas"]["AgentEvents"]["properties"]["contract_version"]
    assert agent_contract["const"] == "local-agent.v9"
    agent_event = schema["components"]["schemas"]["AgentEvent"]
    assert agent_event["properties"]["mcp_tool"]["anyOf"][0] == {
        "$ref": "#/components/schemas/AgentMcpToolDescriptor"
    }
    assert agent_event["properties"]["mcp_result"]["anyOf"][0] == {
        "$ref": "#/components/schemas/AgentMcpToolResultReceipt"
    }
    mcp_descriptor = schema["components"]["schemas"]["AgentMcpToolDescriptor"]
    assert mcp_descriptor["properties"]["source"]["const"] == "managed_mcp"
    assert mcp_descriptor["properties"]["every_call_requires_native_approval"][
        "const"
    ] is True
    mcp_result = schema["components"]["schemas"]["AgentMcpToolResultReceipt"]
    for field in (
        "arguments_persisted",
        "result_text_persisted",
        "reusable_approval_persisted",
    ):
        assert mcp_result["properties"][field]["const"] is False
    for name in ("AgentEvents", "AgentSessionView"):
        assert "closing" in schema["components"]["schemas"][name]["required"]
        assert schema["components"]["schemas"][name]["properties"]["closing"]["type"] == "boolean"
        assert "cleanup_unconfirmed" in schema["components"]["schemas"][name]["required"]
        assert schema["components"]["schemas"][name]["properties"]["cleanup_unconfirmed"]["type"] == "boolean"
    assert "text/event-stream" in paths["/v1/agent/sessions/{session_id}/events/stream"]["get"]["responses"]["200"]["content"]
    managed_base = "/v1/integrations/mcp-store/managed"
    managed_paths = {
        managed_base,
        f"{managed_base}/{{management_id}}",
        f"{managed_base}/{{management_id}}/tools",
        f"{managed_base}/{{management_id}}/probe",
        f"{managed_base}/{{management_id}}/install-preview",
        f"{managed_base}/{{management_id}}/install",
        f"{managed_base}/{{management_id}}/configuration-inspection-preview",
        f"{managed_base}/{{management_id}}/configuration-inspection",
        f"{managed_base}/{{management_id}}/uninstall-preview",
        f"{managed_base}/{{management_id}}/uninstall",
        f"{managed_base}/{{management_id}}/cleanup-preview",
        f"{managed_base}/{{management_id}}/update-preview",
        f"{managed_base}/{{management_id}}/update",
        f"{managed_base}/{{management_id}}/rollback-preview",
        f"{managed_base}/{{management_id}}/rollback",
        f"{managed_base}/{{management_id}}/rollback-cleanup-preview",
        f"{managed_base}/{{management_id}}/rollback-cleanup",
        f"{managed_base}/{{management_id}}/recovery-preview",
        f"{managed_base}/{{management_id}}/recovery",
        f"{managed_base}/{{management_id}}/cleanup",
        f"{managed_base}/{{management_id}}/projects/{{project_id}}",
        f"{managed_base}/{{management_id}}/secrets/{{requirement_id}}",
        (
            f"{managed_base}/{{management_id}}/secrets/"
            "{requirement_id}/remove"
        ),
        (
            f"{managed_base}/{{management_id}}/configuration/"
            "{requirement_id}"
        ),
        (
            f"{managed_base}/{{management_id}}/configuration/"
            "{requirement_id}/remove"
        ),
    }
    assert {path for path in paths if path.startswith(managed_base)} == managed_paths
    assert set(paths[managed_base]) == {"get", "post"}
    assert set(paths[f"{managed_base}/{{management_id}}"]) == {"get"}
    managed_tools_path = f"{managed_base}/{{management_id}}/tools"
    assert set(paths[managed_tools_path]) == {"get"}
    managed_tools_operation = paths[managed_tools_path]["get"]
    assert managed_tools_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/McpManagedToolSnapshot"
    }
    assert "X-Prompt-Enhancer-User-Presence" not in {
        parameter["name"]
        for parameter in managed_tools_operation["parameters"]
    }
    lifecycle_preview_paths = {
        f"{managed_base}/{{management_id}}/install-preview",
        f"{managed_base}/{{management_id}}/uninstall-preview",
    }
    cleanup_preview_path = f"{managed_base}/{{management_id}}/cleanup-preview"
    configuration_inspection_preview_path = (
        f"{managed_base}/{{management_id}}/configuration-inspection-preview"
    )
    update_preview_path = f"{managed_base}/{{management_id}}/update-preview"
    rollback_preview_path = (
        f"{managed_base}/{{management_id}}/rollback-preview"
    )
    rollback_cleanup_preview_path = (
        f"{managed_base}/{{management_id}}/rollback-cleanup-preview"
    )
    recovery_preview_path = (
        f"{managed_base}/{{management_id}}/recovery-preview"
    )
    preview_paths = {
        *lifecycle_preview_paths,
        configuration_inspection_preview_path,
        cleanup_preview_path,
        update_preview_path,
        rollback_preview_path,
        rollback_cleanup_preview_path,
        recovery_preview_path,
    }
    for path in preview_paths:
        assert set(paths[path]) == {"get"}
    for path in managed_paths - {
        managed_base,
        f"{managed_base}/{{management_id}}",
        managed_tools_path,
        *preview_paths,
    }:
        assert set(paths[path]) == {"post"}
    for path in managed_paths:
        for method, operation in paths[path].items():
            if method != "post":
                continue
            assert "X-Prompt-Enhancer-User-Presence" in {
                parameter["name"] for parameter in operation["parameters"]
            }
            assert operation["responses"]["200"]["content"][
                "application/json"
            ]["schema"] == {
                "$ref": (
                    "#/components/schemas/McpManagedProbeReceipt"
                    if path.endswith("/probe")
                    else "#/components/schemas/McpManagedLocalConfigurationInspectionReceipt"
                    if path.endswith("/configuration-inspection")
                    else "#/components/schemas/McpManagedLocalUpdateReceipt"
                    if path.endswith("/update")
                    else "#/components/schemas/McpManagedLocalRollbackCleanupReceipt"
                    if path.endswith("/rollback-cleanup")
                    else "#/components/schemas/McpManagedLocalRollbackReceipt"
                    if path.endswith("/rollback")
                    else "#/components/schemas/McpManagedLocalOperationRecoveryReceipt"
                    if path.endswith("/recovery")
                    else "#/components/schemas/McpManagedLocalCleanupReceipt"
                    if path.endswith("/cleanup")
                    else "#/components/schemas/McpManagedLifecycleReceipt"
                    if path.endswith(("/install", "/uninstall"))
                    else "#/components/schemas/McpManagedServerReceipt"
                )
            }
    for path in lifecycle_preview_paths:
        assert paths[path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"] == {
            "$ref": "#/components/schemas/McpManagedLifecyclePreview"
        }
    assert paths[configuration_inspection_preview_path]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalConfigurationInspectionPreview"
    }
    assert paths[cleanup_preview_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalCleanupPreview"
    }
    assert paths[update_preview_path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalUpdatePreview"
    }
    assert paths[rollback_preview_path]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalRollbackPreview"
    }
    assert paths[rollback_cleanup_preview_path]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalRollbackCleanupPreview"
    }
    assert paths[recovery_preview_path]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/McpManagedLocalOperationRecoveryPreview"
    }
    managed_receipt = schema["components"]["schemas"][
        "McpManagedServerReceipt"
    ]
    assert managed_receipt["properties"]["contract_version"]["const"] == (
        "mcp-managed-server.v2"
    )
    for field in (
        "process_started",
        "endpoint_connected",
        "package_changed",
        "tool_authority_granted",
    ):
        assert managed_receipt["properties"][field]["const"] is False
    managed_probe = schema["components"]["schemas"]["McpManagedProbeReceipt"]
    for field in (
        "connection_retained",
        "package_changed",
        "tool_results_requested",
        "tool_authority_granted",
    ):
        assert managed_probe["properties"][field]["const"] is False
    managed_lifecycle = schema["components"]["schemas"][
        "McpManagedLifecycleReceipt"
    ]
    for field in (
        "endpoint_connected",
        "connection_retained",
        "persistent_host_started",
        "tool_authority_granted",
    ):
        assert managed_lifecycle["properties"][field]["const"] is False
    for field in ("package_changed", "process_started"):
        assert managed_lifecycle["properties"][field]["type"] == "boolean"
    assert managed_lifecycle["properties"]["process_tree_cleanup"]["enum"] == [
        "verified",
        "not_applicable",
    ]
    lifecycle_preview = schema["components"]["schemas"][
        "McpManagedLifecyclePreview"
    ]
    assert lifecycle_preview["properties"]["native_confirmation_required"][
        "const"
    ] is True
    assert lifecycle_preview["properties"]["preview_digest"]["pattern"] == (
        "^[0-9a-f]{64}$"
    )
    configuration_inspection_preview = schema["components"]["schemas"][
        "McpManagedLocalConfigurationInspectionPreview"
    ]
    assert configuration_inspection_preview["properties"]["action"]["const"] == (
        "inspect_configuration"
    )
    assert configuration_inspection_preview["properties"][
        "native_confirmation_required"
    ]["const"] is True
    configuration_inspection_receipt = schema["components"]["schemas"][
        "McpManagedLocalConfigurationInspectionReceipt"
    ]
    for field in (
        "archive_retained",
        "process_started",
        "endpoint_connected",
        "connection_retained",
        "persistent_host_started",
        "tool_authority_granted",
        "configuration_values_persisted",
    ):
        assert configuration_inspection_receipt["properties"][field]["const"] is False
    configuration_inspection = schema["components"]["schemas"][
        "McpManagedLocalConfigurationInspection"
    ]
    assert configuration_inspection["properties"]["requirement_ids"][
        "maxItems"
    ] == 32
    for field in (
        "archive_retained",
        "process_started",
        "configuration_values_persisted",
        "manifest_content_persisted",
    ):
        assert configuration_inspection["properties"][field]["const"] is False
    assert "value" not in configuration_inspection["properties"]
    assert "default" not in configuration_inspection["properties"]
    serialized_configuration_inspection = json.dumps(
        {
            "preview": configuration_inspection_preview,
            "receipt": configuration_inspection_receipt,
            "inspection": configuration_inspection,
        }
    ).casefold()
    for prohibited in (
        '"value":',
        '"manifest_content":',
        '"archive_path":',
        '"command":',
        '"environment":',
    ):
        assert prohibited not in serialized_configuration_inspection
    cleanup_preview = schema["components"]["schemas"][
        "McpManagedLocalCleanupPreview"
    ]
    assert cleanup_preview["properties"]["action"]["const"] == (
        "complete_interrupted_uninstall"
    )
    assert cleanup_preview["properties"]["native_confirmation_required"][
        "const"
    ] is True
    update_preview = schema["components"]["schemas"][
        "McpManagedLocalUpdatePreview"
    ]
    assert update_preview["properties"]["action"]["const"] == "update"
    assert update_preview["properties"]["native_confirmation_required"][
        "const"
    ] is True
    assert update_preview["properties"]["target_plan_revision"]["anyOf"][0][
        "pattern"
    ] == "^[0-9a-f]{64}$"
    update_receipt = schema["components"]["schemas"][
        "McpManagedLocalUpdateReceipt"
    ]
    assert update_receipt["properties"]["process_tree_cleanup"]["const"] == (
        "verified"
    )
    assert update_receipt["properties"]["rollback_generation_retained"][
        "const"
    ] is True
    rollback_preview = schema["components"]["schemas"][
        "McpManagedLocalRollbackPreview"
    ]
    assert rollback_preview["properties"]["action"]["const"] == "rollback"
    rollback_cleanup_preview = schema["components"]["schemas"][
        "McpManagedLocalRollbackCleanupPreview"
    ]
    assert rollback_cleanup_preview["properties"]["action"]["const"] == (
        "cleanup_rollback_generation"
    )
    recovery_preview = schema["components"]["schemas"][
        "McpManagedLocalOperationRecoveryPreview"
    ]
    assert recovery_preview["properties"]["action"]["const"] == (
        "recover_interrupted_local_operation"
    )
    recovery_receipt = schema["components"]["schemas"][
        "McpManagedLocalOperationRecoveryReceipt"
    ]
    assert recovery_receipt["properties"]["filesystem_state_verified"][
        "const"
    ] is True
    cleanup_receipt = schema["components"]["schemas"][
        "McpManagedLocalCleanupReceipt"
    ]
    assert cleanup_receipt["properties"]["package_presence"]["const"] == (
        "absent"
    )
    assert cleanup_receipt["properties"]["filesystem_changed"]["type"] == (
        "boolean"
    )
    for field in (
        "process_started",
        "endpoint_connected",
        "connection_retained",
        "persistent_host_started",
        "tool_authority_granted",
    ):
        assert cleanup_receipt["properties"][field]["const"] is False
    probe_evidence = schema["components"]["schemas"]["McpManagedHostProbe"]
    assert probe_evidence["properties"]["connection_state"]["const"] == (
        "closed_after_probe"
    )
    for field in ("tool_results_requested", "tool_authority_granted"):
        assert probe_evidence["properties"][field]["const"] is False
    for field in ("tool_names_persisted", "tool_schemas_persisted"):
        assert probe_evidence["properties"][field]["type"] == "boolean"
    tool_snapshot = schema["components"]["schemas"][
        "McpManagedToolSnapshot"
    ]
    assert tool_snapshot["additionalProperties"] is False
    assert tool_snapshot["properties"]["contract_version"]["const"] == (
        "mcp-managed-tool-snapshot.v1"
    )
    assert tool_snapshot["properties"]["connection_retained"]["const"] is False
    assert tool_snapshot["properties"]["tool_authority_granted"]["const"] is False
    assert tool_snapshot["properties"]["tools"]["maxItems"] == 256
    assert tool_snapshot["properties"]["source_manifest_digest"]["anyOf"][0][
        "pattern"
    ] == "^[0-9a-f]{64}$"
    tool_snapshot_summary = schema["components"]["schemas"][
        "McpManagedToolSnapshotSummary"
    ]
    assert tool_snapshot_summary["properties"]["source_manifest_digest"][
        "anyOf"
    ][0]["pattern"] == "^[0-9a-f]{64}$"
    reviewed_tool = schema["components"]["schemas"]["McpManagedReviewedTool"]
    assert reviewed_tool["additionalProperties"] is False
    assert reviewed_tool["properties"]["input_schema"]["additionalProperties"] is True
    serialized_probe = json.dumps({
        "receipt": managed_probe,
        "evidence": probe_evidence,
    }).casefold()
    for prohibited in (
        '"endpoint":',
        '"headers":',
        '"tool_names":',
        '"tool_schemas":',
        '"input_schema":',
        '"output_schema":',
        '"tool_result":',
    ):
        assert prohibited not in serialized_probe
    local_evidence = schema["components"]["schemas"][
        "McpManagedLocalPackageEvidence"
    ]
    assert set(local_evidence["properties"]) == {
        "artifact_sha256",
        "artifact_bytes",
        "tree_digest",
        "manifest_digest",
        "manifest_version",
        "license_state",
        "runtime_kind",
        "runtime_version",
    }
    assert local_evidence["properties"]["artifact_bytes"]["maximum"] == (
        64 * 1024 * 1024
    )
    assert local_evidence["properties"]["license_state"]["const"] == "declared"
    serialized_local_evidence = json.dumps(local_evidence).casefold()
    for prohibited in (
        '"path":',
        '"command":',
        '"arguments":',
        '"environment":',
        '"tool_names":',
        '"tool_schemas":',
    ):
        assert prohibited not in serialized_local_evidence
    managed_secret = schema["components"]["schemas"]["StoreMcpManagedSecret"]
    assert managed_secret["properties"]["value"]["writeOnly"] is True
    assert managed_secret["properties"]["value"]["format"] == "password"
    managed_configuration = schema["components"]["schemas"][
        "StoreMcpManagedConfiguration"
    ]
    assert managed_configuration["properties"]["value"]["writeOnly"] is True
    assert managed_configuration["properties"]["value"]["format"] == "password"
    managed_requirement = schema["components"]["schemas"][
        "McpManagedRequirement"
    ]
    assert "value_vault_provider" in managed_requirement["properties"]
    assert "value" not in schema["components"]["schemas"][
        "McpManagedRequirement"
    ]["properties"]
    assert "value" not in schema["components"]["schemas"][
        "McpManagedServer"
    ]["properties"]
    artifact_base = "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts"
    artifact_detail = f"{artifact_base}/{{artifact_id}}"
    artifact_export = f"{artifact_detail}/export"
    artifact_remove = f"{artifact_detail}/remove"
    artifact_content = f"{artifact_detail}/versions/{{version_id}}/content"
    assert set(paths[artifact_base]) == {"get", "post"}
    assert set(paths[artifact_detail]) == {"get", "patch"}
    assert set(paths[artifact_export]) == {"post"}
    assert set(paths[artifact_remove]) == {"post"}
    assert set(paths[artifact_content]) == {"get"}
    artifact_schema = schema["components"]["schemas"]["AgentArtifactDetail"]
    assert artifact_schema["properties"]["contract_version"]["const"] == (
        "agent-artifact.v3"
    )
    assert artifact_schema["properties"]["lifecycle_state"]["enum"] == [
        "active",
        "archived",
        "removed",
    ]
    assert artifact_schema["properties"]["versions"]["minItems"] == 1
    artifact_capture_parameters = {
        item["name"]: item
        for item in paths[artifact_base]["post"]["parameters"]
    }
    assert "X-Prompt-Enhancer-User-Presence" in artifact_capture_parameters
    artifact_remove_parameters = {
        item["name"]: item
        for item in paths[artifact_remove]["post"]["parameters"]
    }
    assert "X-Prompt-Enhancer-User-Presence" in artifact_remove_parameters
    assert paths[artifact_detail]["patch"]["requestBody"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/UpdateAgentArtifact"}
    artifact_export_operation = paths[artifact_export]["post"]
    assert artifact_export_operation["requestBody"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ExportAgentArtifact"}
    assert artifact_export_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/AgentArtifactExport"}
    assert "X-Prompt-Enhancer-User-Presence" not in {
        item["name"] for item in artifact_export_operation["parameters"]
    }
    artifact_export_schema = schema["components"]["schemas"][
        "AgentArtifactExport"
    ]
    assert artifact_export_schema["properties"]["content_included"][
        "const"
    ] is False
    assert artifact_export_schema["properties"]["absolute_path_included"][
        "const"
    ] is False
    assert artifact_export_schema["properties"]["sensitivity"]["const"] == (
        "sensitive_local_metadata"
    )
    orchestration_schema = schema["components"]["schemas"][
        "AgentOrchestrationManifest"
    ]
    assert orchestration_schema["properties"]["contract_version"]["const"] == (
            "local-agent-orchestration.v22"
    )
    fork_path = (
        "/v1/agent/projects/{project_id}/sessions/{session_id}/forks"
    )
    assert set(paths[fork_path]) == {"post"}
    fork_operation = paths[fork_path]["post"]
    assert fork_operation["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ForkAgentSession"}
    assert fork_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AgentSessionForkReceipt"}
    fork_request = schema["components"]["schemas"]["ForkAgentSession"]
    assert fork_request["additionalProperties"] is False
    assert fork_request["properties"]["request_id"]["pattern"] == (
        "^[0-9a-f]{32}$"
    )
    fork_receipt = schema["components"]["schemas"][
        "AgentSessionForkReceipt"
    ]
    assert fork_receipt["properties"]["contract_version"]["const"] == (
        "agent-session-fork.v1"
    )
    for field in (
        "approvals_copied",
        "mutation_authority_copied",
        "pending_tool_state_copied",
        "staged_attachments_copied",
        "artifacts_copied",
    ):
        assert fork_receipt["properties"][field]["const"] is False
    catalog_session = schema["components"]["schemas"][
        "AgentCatalogSessionRecord"
    ]
    assert "lineage" in catalog_session["required"]
    assert catalog_session["properties"]["lineage"]["anyOf"] == [
        {"$ref": "#/components/schemas/AgentSessionLineage"},
        {"type": "null"},
    ]
    assert {
        path for path in paths if path.startswith("/v1/control-plane/")
    } == {"/v1/control-plane/readiness"}

    readiness = paths["/v1/control-plane/readiness"]["get"]
    assert "requestBody" not in readiness
    assert all(
        parameter["name"] != "X-Control-Plane-Credential"
        for parameter in readiness.get("parameters", [])
    )
    readiness_schema = readiness["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert readiness_schema == {
        "$ref": "#/components/schemas/ControlPlaneReadiness"
    }
    assert "X-Control-Plane-Credential" not in json.dumps(schema)

    analysis_limit = schema["components"]["schemas"]["CodexAnalysisRequest"][
        "properties"
    ]["max_sessions"]
    assert analysis_limit["default"] == 10
    assert analysis_limit["maximum"] == 100

    label_limit = schema["components"]["schemas"]["CodexLabelEnrichmentRequest"][
        "properties"
    ]["max_sessions"]
    assert label_limit["default"] == 10
    assert label_limit["maximum"] == 25

    session_parameters = paths["/v1/sessions"]["get"]["parameters"]
    provider_parameter = next(
        parameter
        for parameter in session_parameters
        if parameter["name"] == "provider"
    )
    assert provider_parameter["in"] == "query"
    assert provider_parameter["required"] is False
    # ADR 0011: exactly one owner-authorized, read-only transcript route, GET only,
    # returning the bounded SessionTranscript whose persisted flag is fixed false.
    transcript_paths = [path for path in paths if "transcript" in path]
    assert transcript_paths == ["/v1/sessions/{session_id}/transcript"]
    assert set(paths["/v1/sessions/{session_id}/transcript"]) == {"get"}
    transcript_schema = schema["components"]["schemas"]["SessionTranscript"]["properties"]
    assert transcript_schema["persisted"].get("const") is False or transcript_schema["persisted"].get("enum") == [False]
    assert transcript_schema["turns"]["maxItems"] == 2000


def test_exporter_writes_reproducible_json_without_runtime_state(tmp_path) -> None:
    first = tmp_path / "contract.json"
    second = tmp_path / "contract-copy.json"

    export_openapi(first)
    export_openapi(second)

    assert first.read_bytes() == second.read_bytes()
    document = json.loads(first.read_text(encoding="utf-8"))
    serialized = json.dumps(document).casefold()
    assert document["info"]["title"] == "Prompt Enhancer Local API"
    assert "example-state" not in serialized
    assert "schema_token" not in serialized
    assert "openapi.json" not in document["paths"]


def test_onboarding_schema_keeps_unknowns_explicit_and_json_safe() -> None:
    schemas = build_openapi_schema()["components"]["schemas"]
    status = schemas["OnboardingStatus"]
    provider = schemas["ProviderDetection"]
    result = schemas["OnboardingResult"]

    assert {"last_refresh_at", "refresh_interval_seconds"}.issubset(
        status["required"]
    )
    assert status["properties"]["refresh_interval_seconds"] == {
        "maximum": 9_007_199_254_740_991,
        "minimum": 60,
        "title": "Refresh Interval Seconds",
        "type": "integer",
    }
    assert "transcript_files" in provider["required"]
    for field in ("indexed_sessions", "transcript_files"):
        choices = provider["properties"][field]["anyOf"]
        assert {choice.get("type") for choice in choices} == {"integer", "null"}
        integer = next(choice for choice in choices if choice.get("type") == "integer")
        assert integer["minimum"] == 0
        assert integer["maximum"] == 9_007_199_254_740_991
    result_choices = result["properties"]["indexed_sessions"]["anyOf"]
    assert {choice.get("type") for choice in result_choices} == {"integer", "null"}
    result_integer = next(
        choice for choice in result_choices if choice.get("type") == "integer"
    )
    assert result_integer["minimum"] == 0
    assert result_integer["maximum"] == 9_007_199_254_740_991
    assert "claude_transcript_count_capped" in schemas["DetectionSignal"]["enum"]


def test_overlapping_provider_and_domain_failures_remain_in_openapi() -> None:
    paths = build_openapi_schema()["paths"]

    def refs(path: str, method: str, status: int) -> set[str]:
        response_schema = paths[path][method]["responses"][str(status)][
            "content"
        ]["application/json"]["schema"]
        choices = response_schema.get("anyOf", [response_schema])
        return {choice["$ref"] for choice in choices}

    provider = "#/components/schemas/SessionProviderFailureResponse"
    assert refs(
        "/v1/sessions/{session_id}/model-ensemble-runs", "post", 404
    ) == {
        provider,
        "#/components/schemas/ModelEnsembleSelectionFailureResponse",
    }
    assert refs(
        "/v1/sessions/{session_id}/model-ensemble-runs", "post", 503
    ) == {
        provider,
        "#/components/schemas/ModelEnsembleUnavailableFailureResponse",
    }
    assert refs(
        "/v1/sessions/{session_id}/model-ensemble-watch", "put", 404
    ) == {
        provider,
        "#/components/schemas/ModelEnsembleWatchSelectionFailureResponse",
    }
    assert refs(
        "/v1/sessions/{session_id}/model-ensemble-watch", "put", 503
    ) == {
        provider,
        "#/components/schemas/ModelEnsembleWatchUnavailableFailureResponse",
    }
    profile_path = "/v1/sessions/{session_id}/declared-task-profile"
    assert refs(profile_path, "get", 404) == {provider}
    assert refs(profile_path, "get", 503) == {
        provider,
        "#/components/schemas/DeclaredTaskProfileUnavailableFailureResponse",
    }
    assert refs(profile_path, "post", 404) == {
        provider,
        "#/components/schemas/DeclaredTaskProfileNotFoundFailureResponse",
    }
    assert refs(profile_path, "post", 503) == {
        provider,
        "#/components/schemas/DeclaredTaskProfileUnavailableFailureResponse",
    }


def test_local_model_lifecycle_failures_are_declared_in_openapi() -> None:
    paths = build_openapi_schema()["paths"]
    base = "/v1/local-models/{alias}"

    def ref(operation: dict[str, object], status: int) -> str:
        return operation["responses"][str(status)]["content"][
            "application/json"
        ]["schema"]["$ref"]

    remove = paths[base]["delete"]
    assert ref(remove, 404).endswith("/LocalModelNotFoundFailureResponse")
    assert ref(remove, 503).endswith("/LocalModelStopFailureResponse")

    activate = paths[f"{base}/activate"]["post"]
    assert ref(activate, 404).endswith("/LocalModelNotFoundFailureResponse")
    assert ref(activate, 409).endswith(
        "/LocalModelActivationConflictFailureResponse"
    )
    assert ref(activate, 502).endswith("/LocalModelActivationFailureResponse")
    assert ref(activate, 503).endswith("/LocalModelStopFailureResponse")

    deactivate = paths[f"{base}/deactivate"]["post"]
    assert ref(deactivate, 404).endswith("/LocalModelNotFoundFailureResponse")
    assert ref(deactivate, 503).endswith("/LocalModelStopFailureResponse")

    start_download = paths["/v1/local-models/downloads"]["post"]
    assert ref(start_download, 409).endswith("/LocalModelDownloadConflictFailureResponse")
    assert ref(start_download, 502).endswith("/LocalModelDownloadUpstreamFailureResponse")
    assert ref(start_download, 503).endswith("/LocalModelDownloadUnavailableFailureResponse")
    for action in ("pause", "resume", "retry", "cancel"):
        operation = paths[f"/v1/local-models/downloads/{{download_id}}/{action}"]["post"]
        assert ref(operation, 404).endswith("/LocalModelDownloadNotFoundFailureResponse")
        assert ref(operation, 409).endswith("/LocalModelDownloadConflictFailureResponse")
        assert ref(operation, 503).endswith("/LocalModelDownloadUnavailableFailureResponse")


def test_committed_openapi_artifact_is_byte_exact_to_current_schema() -> None:
    expected = (
        json.dumps(build_openapi_schema(), indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    actual = (REPOSITORY_ROOT / "docs" / "openapi.json").read_bytes()

    assert actual == expected
