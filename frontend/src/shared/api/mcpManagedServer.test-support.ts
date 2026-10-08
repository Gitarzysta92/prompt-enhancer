import type {
  McpManagedServer,
  McpManagedLifecyclePreview,
  McpManagedLifecycleReceipt,
  McpManagedLocalConfigurationInspection,
  McpManagedLocalConfigurationInspectionPreview,
  McpManagedLocalConfigurationInspectionReceipt,
  McpManagedLocalCleanupPreview,
  McpManagedLocalCleanupReceipt,
  McpManagedLocalUpdatePreview,
  McpManagedLocalUpdateReceipt,
  McpManagedLocalRollbackGeneration,
  McpManagedLocalRollbackPreview,
  McpManagedLocalRollbackReceipt,
  McpManagedLocalRollbackCleanupPreview,
  McpManagedLocalRollbackCleanupReceipt,
  McpManagedLocalOperationRecoveryPreview,
  McpManagedLocalOperationRecoveryReceipt,
  McpManagedServerList,
  McpManagedProbeReceipt,
  McpManagedServerReceipt,
  McpManagedReviewedTool,
  McpManagedToolSnapshot,
  McpManagedToolSnapshotSummary,
} from "./contracts";

function syntheticMcpManagedTools(count: number): McpManagedReviewedTool[] {
  return Array.from({ length: count }, (_, index) => {
    const digest = String((index % 9) + 1).repeat(64);
    return {
      tool_id: digest.slice(0, 32),
      name: `synthetic_tool_${index + 1}`,
      title: `Synthetic tool ${index + 1}`,
      description: "Reads fictional example data without external effects.",
      model_alias: `mcp_99999999_synthetic_${index + 1}`,
      input_schema: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
        additionalProperties: false,
      },
      input_schema_digest: "a".repeat(64),
      model_input_schema: {
        type: "object",
        properties: { query: { type: "string" } },
        required: ["query"],
        additionalProperties: false,
      },
      output_schema: null,
      output_schema_digest: null,
      contract_digest: digest,
    };
  });
}

export function syntheticMcpManagedToolSnapshot(
  overrides: Partial<McpManagedToolSnapshot> = {},
): McpManagedToolSnapshot {
  const tools = overrides.tools ?? syntheticMcpManagedTools(overrides.tool_count ?? 2);
  return {
    contract_version: "mcp-managed-tool-snapshot.v1",
    management_id: "9".repeat(32),
    snapshot_id: "3".repeat(32),
    plan_revision: "d".repeat(64),
    source: "remote_probe",
    source_tree_digest: null,
    source_manifest_digest: null,
    protocol_version: "2026-07-28",
    tool_count: tools.length,
    schema_digest: "1".repeat(64),
    reviewed_at: "2040-01-01T10:01:00Z",
    tool_names_retained_locally: true,
    tool_schemas_retained_locally: true,
    connection_retained: false,
    tool_authority_granted: false,
    ...overrides,
    tools,
  };
}

function syntheticToolSnapshotSummary(
  snapshot: McpManagedToolSnapshot,
): McpManagedToolSnapshotSummary {
  return {
    snapshot_id: snapshot.snapshot_id,
    plan_revision: snapshot.plan_revision,
    source: snapshot.source,
    source_tree_digest: snapshot.source_tree_digest,
    source_manifest_digest: snapshot.source_manifest_digest,
    protocol_version: snapshot.protocol_version,
    tool_count: snapshot.tool_count,
    schema_digest: snapshot.schema_digest,
    reviewed_at: snapshot.reviewed_at,
    tool_names_retained_locally: true,
    tool_schemas_retained_locally: true,
    connection_retained: false,
    tool_authority_granted: false,
  };
}

export function syntheticMcpManagedServer(
  overrides: Partial<McpManagedServer> = {},
): McpManagedServer {
  return {
    contract_version: "mcp-managed-server.v2",
    management_id: "9".repeat(32),
    catalog_id: "a".repeat(32),
    server_name: "com.example/synthetic-files",
    server_title: "Synthetic Files",
    server_version: "1.2.3",
    server_status_at_review: "active",
    option_id: "b".repeat(32),
    plan_revision: "d".repeat(64),
    option_kind: "local_package",
    option_label: "NPM package",
    registry_type: "npm",
    package_identifier: "@example/synthetic-files",
    package_version: "1.2.3",
    runtime_hint: "npx",
    transport: "stdio",
    endpoint_host: null,
    endpoint_state: "not_applicable",
    secure_transport: null,
    required_permissions: [
      "process_spawn",
      "filesystem_read",
      "filesystem_write",
      "credential_use",
    ],
    risks: [
      "downloads_package",
      "executes_local_code",
      "filesystem_input_declared",
      "credential_input_declared",
    ],
    requirements: [
      {
        requirement_id: "c".repeat(32),
        location: "runtime_argument",
        name: "--workspace",
        required: true,
        secret: false,
        format: "filepath",
        user_value_needed: true,
        configuration_state: "value_required",
        secret_vault_provider: null,
        value_vault_provider: null,
      },
      {
        requirement_id: "e".repeat(32),
        location: "environment_variable",
        name: "EXAMPLE_TOKEN",
        required: true,
        secret: true,
        format: "string",
        user_value_needed: true,
        configuration_state: "secret_missing",
        secret_vault_provider: null,
        value_vault_provider: null,
      },
    ],
    project_bindings: [],
    created_at: "2040-01-01T10:00:00Z",
    updated_at: "2040-01-01T10:00:00Z",
    revision: 1,
    lifecycle_state: "planned",
    installation_state: "not_installed",
    installation_kind: "none",
    operation_state: "idle",
    installed_plan_revision: null,
    installed_at: null,
    local_package_evidence: null,
    local_configuration_inspection: null,
    rollback_generation: null,
    process_tree_cleanup: "not_applicable",
    host_state: "not_started",
    health_state: "not_checked",
    last_health_checked_at: null,
    last_probe: null,
    tool_snapshot: null,
    tool_review_state: "probe_required",
    update_state: "not_checked",
    latest_available_version: null,
    tool_routing_state: "inactive",
    install_action: "unavailable_package_registry_not_supported",
    uninstall_action: "not_applicable_not_installed",
    probe_action: "unavailable_install_required",
    ...overrides,
  };
}

export function syntheticMcpManagedServerList(
  servers: McpManagedServer[] = [syntheticMcpManagedServer()],
): McpManagedServerList {
  return {
    contract_version: "mcp-managed-server.v2",
    servers,
    total: servers.length,
    secret_vault: {
      provider: "windows_credential_manager",
      availability: "available",
      values_in_database: false,
      values_in_api_responses: false,
      values_in_model_context: false,
    },
    execution_truth: "reviewed_tool_admission_without_persistent_host_or_tool_authority",
  };
}

export function syntheticMcpManagedProbeReceipt(
  base: McpManagedServer = syntheticMcpManagedServer({
    option_kind: "remote_server",
    option_label: "Remote · mcp.example.com",
    registry_type: null,
    package_identifier: null,
    package_version: null,
    runtime_hint: null,
    transport: "streamable-http",
    endpoint_host: "mcp.example.com",
    endpoint_state: "fixed_host",
    secure_transport: true,
    required_permissions: ["network_egress"],
    risks: ["remote_network_egress"],
    requirements: [],
    updated_at: "2040-01-01T10:01:00Z",
    revision: 2,
    health_state: "compatible",
    last_health_checked_at: "2040-01-01T10:01:00Z",
    install_action: "available_native_confirmation_required",
    probe_action: "available_native_confirmation_required",
  }),
): McpManagedProbeReceipt {
  const snapshot = syntheticMcpManagedToolSnapshot();
  const probe = {
    request_id: "f".repeat(32),
    checked_at: "2040-01-01T10:01:00Z",
    transport: "streamable-http" as const,
    protocol_version: "2026-07-28",
    tool_count: 2,
    schema_digest: "1".repeat(64),
    elapsed_ms: 41,
    connection_state: "closed_after_probe" as const,
    process_started: false,
    process_tree_cleanup: "not_applicable" as const,
    tool_names_persisted: true,
    tool_schemas_persisted: true,
    tool_results_requested: false as const,
    tool_authority_granted: false as const,
  };
  const server = {
    ...base,
    last_probe: probe,
    tool_snapshot: syntheticToolSnapshotSummary(snapshot),
    tool_review_state: "reviewable" as const,
  };
  return {
    contract_version: "mcp-managed-server.v2",
    server,
    probe,
    idempotent_replay: false,
    endpoint_connection_attempted: true,
    connection_retained: false,
    package_changed: false,
    tool_results_requested: false,
    tool_authority_granted: false,
  };
}

export function syntheticMcpManagedServerReceipt(
  server: McpManagedServer = syntheticMcpManagedServer(),
): McpManagedServerReceipt {
  return {
    contract_version: "mcp-managed-server.v2",
    server,
    idempotent_replay: false,
    process_started: false,
    endpoint_connected: false,
    package_changed: false,
    tool_authority_granted: false,
  };
}

export function syntheticMcpManagedLifecyclePreview(
  overrides: Partial<McpManagedLifecyclePreview> = {},
): McpManagedLifecyclePreview {
  return {
    contract_version: "mcp-managed-lifecycle-preview.v1",
    action: "install",
    management_id: "9".repeat(32),
    expected_revision: 2,
    plan_revision: "d".repeat(64),
    installation_kind: "remote_activation",
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
      "persist_remote_activation",
      "no_package_change",
      "no_process_start",
      "no_connection_retained",
      "no_tool_authority",
    ],
    preview_digest: "2".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLifecycleReceipt(
  overrides: Partial<McpManagedLifecycleReceipt> = {},
): McpManagedLifecycleReceipt {
  const server = syntheticMcpManagedServer({
    option_kind: "remote_server",
    option_label: "Remote · mcp.example.com",
    registry_type: null,
    package_identifier: null,
    package_version: null,
    runtime_hint: null,
    transport: "streamable-http",
    endpoint_host: "mcp.example.com",
    endpoint_state: "fixed_host",
    secure_transport: true,
    required_permissions: ["network_egress"],
    risks: ["remote_network_egress"],
    requirements: [],
    lifecycle_state: "installed",
    installation_state: "installed",
    installation_kind: "remote_activation",
    installed_plan_revision: "d".repeat(64),
    installed_at: "2040-01-01T10:02:00Z",
    health_state: "compatible",
    last_health_checked_at: "2040-01-01T10:01:00Z",
    last_probe: syntheticMcpManagedProbeReceipt().probe,
    revision: 3,
    install_action: "not_applicable_already_installed",
    uninstall_action: "available_native_confirmation_required",
    probe_action: "available_native_confirmation_required",
  });
  return {
    contract_version: "mcp-managed-lifecycle-receipt.v2",
    action: "install",
    installation_kind: "remote_activation",
    server,
    preview_digest: "2".repeat(64),
    idempotent_replay: false,
    package_changed: false,
    process_started: false,
    process_tree_cleanup: "not_applicable",
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalConfigurationInspection(
  overrides: Partial<McpManagedLocalConfigurationInspection> = {},
): McpManagedLocalConfigurationInspection {
  return {
    plan_revision: "d".repeat(64),
    artifact_sha256: "8".repeat(64),
    artifact_bytes: 4096,
    manifest_digest: "6".repeat(64),
    manifest_version: "0.4",
    configuration_schema_digest: "5".repeat(64),
    requirement_ids: ["c".repeat(32), "e".repeat(32)],
    inspected_at: "2040-01-01T10:01:00Z",
    archive_retained: false,
    process_started: false,
    configuration_values_persisted: false,
    manifest_content_persisted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalConfigurationInspectionPreview(
  overrides: Partial<McpManagedLocalConfigurationInspectionPreview> = {},
): McpManagedLocalConfigurationInspectionPreview {
  return {
    contract_version: "mcp-managed-local-configuration-inspection-preview.v1",
    action: "inspect_configuration",
    management_id: "9".repeat(32),
    expected_revision: 1,
    plan_revision: "d".repeat(64),
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
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
    preview_digest: "4".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalConfigurationInspectionReceipt(
  overrides: Partial<McpManagedLocalConfigurationInspectionReceipt> = {},
): McpManagedLocalConfigurationInspectionReceipt {
  const inspection = syntheticMcpManagedLocalConfigurationInspection();
  const server = syntheticMcpManagedServer({
    option_label: "MCPB release",
    registry_type: "mcpb",
    package_identifier: "https://registry.example.invalid/synthetic.mcpb",
    runtime_hint: "node",
    revision: 2,
    updated_at: inspection.inspected_at,
    local_configuration_inspection: inspection,
    install_action: "unavailable_configuration_required",
  });
  return {
    contract_version: "mcp-managed-local-configuration-inspection-receipt.v1",
    action: "inspect_configuration",
    server,
    inspection,
    preview_digest: "4".repeat(64),
    idempotent_replay: false,
    archive_retained: false,
    process_started: false,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    configuration_values_persisted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalLifecycleReceipt(
  overrides: Partial<McpManagedLifecycleReceipt> = {},
): McpManagedLifecycleReceipt {
  const checkedAt = "2040-01-01T10:02:00Z";
  const snapshot = syntheticMcpManagedToolSnapshot({
    snapshot_id: "4".repeat(32),
    source: "local_package_probe",
    source_tree_digest: "5".repeat(64),
    source_manifest_digest: "6".repeat(64),
    reviewed_at: checkedAt,
  });
  const probe = {
    request_id: "7".repeat(32),
    checked_at: checkedAt,
    transport: "stdio" as const,
    protocol_version: "2026-07-28",
    tool_count: 2,
    schema_digest: "1".repeat(64),
    elapsed_ms: 41,
    connection_state: "closed_after_probe" as const,
    process_started: true,
    process_tree_cleanup: "verified" as const,
    tool_names_persisted: true,
    tool_schemas_persisted: true,
    tool_results_requested: false as const,
    tool_authority_granted: false as const,
  };
  const server = syntheticMcpManagedServer({
    option_label: "MCPB release",
    registry_type: "mcpb",
    package_identifier: "https://github.com/example/synthetic/releases/download/v1/synthetic.mcpb",
    package_version: "1.2.3",
    runtime_hint: "node",
    requirements: [],
    lifecycle_state: "installed",
    installation_state: "installed",
    installation_kind: "local_package",
    installed_plan_revision: "d".repeat(64),
    installed_at: checkedAt,
    local_package_evidence: {
      artifact_sha256: "4".repeat(64),
      artifact_bytes: 4096,
      tree_digest: "5".repeat(64),
      manifest_digest: "6".repeat(64),
      manifest_version: "0.3",
      license_state: "declared",
      runtime_kind: "node",
      runtime_version: "v24.0.0",
    },
    process_tree_cleanup: "verified",
    health_state: "compatible",
    last_health_checked_at: checkedAt,
    last_probe: probe,
    tool_snapshot: syntheticToolSnapshotSummary(snapshot),
    tool_review_state: "reviewable",
    revision: 3,
    install_action: "not_applicable_already_installed",
    uninstall_action: "available_native_confirmation_required",
    probe_action: "not_applicable_verified_during_install",
  });
  return {
    contract_version: "mcp-managed-lifecycle-receipt.v2",
    action: "install",
    installation_kind: "local_package",
    server,
    preview_digest: "2".repeat(64),
    idempotent_replay: false,
    package_changed: true,
    process_started: true,
    process_tree_cleanup: "verified",
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalUninstallReceipt(
  overrides: Partial<McpManagedLifecycleReceipt> = {},
): McpManagedLifecycleReceipt {
  const installed = syntheticMcpManagedLocalLifecycleReceipt();
  const server = syntheticMcpManagedServer({
    ...installed.server,
    updated_at: "2040-01-01T10:03:00Z",
    revision: installed.server.revision + 1,
    lifecycle_state: "planned",
    installation_state: "not_installed",
    installation_kind: "none",
    operation_state: "idle",
    installed_plan_revision: null,
    installed_at: null,
    local_package_evidence: null,
    process_tree_cleanup: "not_applicable",
    health_state: "not_checked",
    last_health_checked_at: null,
    last_probe: null,
    tool_snapshot: null,
    tool_review_state: "probe_required",
    install_action: "unavailable_configuration_inspection_required",
    uninstall_action: "not_applicable_not_installed",
    probe_action: "unavailable_install_required",
  });
  return {
    contract_version: "mcp-managed-lifecycle-receipt.v2",
    action: "uninstall",
    installation_kind: "local_package",
    server,
    preview_digest: "3".repeat(64),
    idempotent_replay: false,
    package_changed: true,
    process_started: false,
    process_tree_cleanup: "not_applicable",
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalCleanupPreview(
  overrides: Partial<McpManagedLocalCleanupPreview> = {},
): McpManagedLocalCleanupPreview {
  return {
    contract_version: "mcp-managed-local-cleanup-preview.v1",
    action: "complete_interrupted_uninstall",
    management_id: "9".repeat(32),
    expected_revision: 4,
    plan_revision: "d".repeat(64),
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
      "verify_operation_journal",
      "verify_installed_or_quarantined_tree_digest",
      "finish_quarantined_removal",
      "clear_cleanup_state",
      "no_process_start",
      "no_connection_retained",
      "no_tool_authority",
    ],
    preview_digest: "7".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalUpdatePreview(
  overrides: Partial<McpManagedLocalUpdatePreview> = {},
): McpManagedLocalUpdatePreview {
  return {
    contract_version: "mcp-managed-local-update-preview.v1",
    action: "update",
    management_id: "9".repeat(32),
    expected_revision: 3,
    current_version: "1.2.3",
    current_plan_revision: "d".repeat(64),
    target_version: "2.0.0",
    target_catalog_id: "a".repeat(32),
    target_option_id: "8".repeat(32),
    target_plan_revision: "9".repeat(64),
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
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
    preview_digest: "a".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalCleanupReceipt(
  overrides: Partial<McpManagedLocalCleanupReceipt> = {},
): McpManagedLocalCleanupReceipt {
  return {
    contract_version: "mcp-managed-local-cleanup-receipt.v1",
    action: "complete_interrupted_uninstall",
    server: syntheticMcpManagedLocalUninstallReceipt().server,
    preview_digest: "7".repeat(64),
    idempotent_replay: false,
    package_presence: "absent",
    filesystem_changed: true,
    process_started: false,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedRollbackGeneration(
  overrides: Partial<McpManagedLocalRollbackGeneration> = {},
): McpManagedLocalRollbackGeneration {
  const installed = syntheticMcpManagedLocalLifecycleReceipt().server;
  if (!installed.local_package_evidence || !installed.last_probe || !installed.installed_at) {
    throw new Error("Synthetic installed MCP fixture is incomplete");
  }
  return {
    catalog_id: installed.catalog_id,
    server_name: installed.server_name,
    server_title: installed.server_title,
    server_version: installed.server_version,
    server_status_at_review: installed.server_status_at_review,
    option_id: installed.option_id,
    plan_revision: installed.plan_revision,
    option_label: installed.option_label,
    registry_type: "mcpb",
    package_identifier: installed.package_identifier ?? "https://example.com/synthetic.mcpb",
    package_version: installed.package_version,
    runtime_hint: installed.runtime_hint,
    transport: "stdio",
    required_permissions: installed.required_permissions,
    risks: installed.risks,
    generation_id: "8".repeat(32),
    local_package_evidence: installed.local_package_evidence,
    probe: installed.last_probe,
    installed_at: installed.installed_at,
    retained_at: "2040-01-01T10:03:00Z",
    ...overrides,
  };
}

export function syntheticMcpManagedLocalUpdateReceipt(
  overrides: Partial<McpManagedLocalUpdateReceipt> = {},
): McpManagedLocalUpdateReceipt {
  const installed = syntheticMcpManagedLocalLifecycleReceipt().server;
  const checkedAt = "2040-01-01T10:03:00Z";
  const snapshot = syntheticMcpManagedToolSnapshot({
    snapshot_id: "6".repeat(32),
    plan_revision: "9".repeat(64),
    source: "local_package_probe",
    source_tree_digest: "b".repeat(64),
    source_manifest_digest: "c".repeat(64),
    tool_count: 4,
    schema_digest: "e".repeat(64),
    reviewed_at: checkedAt,
  });
  const server = syntheticMcpManagedServer({
    ...installed,
    server_version: "2.0.0",
    option_id: "8".repeat(32),
    plan_revision: "9".repeat(64),
    package_version: "2.0.0",
    updated_at: checkedAt,
    revision: 4,
    installed_plan_revision: "9".repeat(64),
    installed_at: checkedAt,
    local_package_evidence: {
      artifact_sha256: "a".repeat(64),
      artifact_bytes: 8192,
      tree_digest: "b".repeat(64),
      manifest_digest: "c".repeat(64),
      manifest_version: "0.4",
      license_state: "declared",
      runtime_kind: "node",
      runtime_version: "v24.0.0",
    },
    rollback_generation: syntheticMcpManagedRollbackGeneration(),
    last_health_checked_at: checkedAt,
    last_probe: {
      ...(installed.last_probe ?? syntheticMcpManagedRollbackGeneration().probe),
      request_id: "8".repeat(32),
      checked_at: checkedAt,
      tool_count: 4,
      schema_digest: "e".repeat(64),
      elapsed_ms: 83,
    },
    tool_snapshot: syntheticToolSnapshotSummary(snapshot),
    tool_review_state: "reviewable",
  });
  return {
    contract_version: "mcp-managed-local-update-receipt.v1",
    action: "update",
    server,
    preview_digest: "a".repeat(64),
    idempotent_replay: false,
    package_changed: true,
    process_started: true,
    process_tree_cleanup: "verified",
    rollback_generation_retained: true,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalRollbackPreview(
  overrides: Partial<McpManagedLocalRollbackPreview> = {},
): McpManagedLocalRollbackPreview {
  return {
    contract_version: "mcp-managed-local-rollback-preview.v1",
    action: "rollback",
    management_id: "9".repeat(32),
    expected_revision: 4,
    current_version: "2.0.0",
    current_plan_revision: "9".repeat(64),
    target_version: "1.2.3",
    target_plan_revision: "d".repeat(64),
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
      "verify_current_tree_digest",
      "verify_rollback_tree_digest",
      "atomically_swap_verified_generations",
      "retain_superseded_current_generation",
      "no_process_start",
      "no_connection_retained",
      "no_tool_authority",
    ],
    preview_digest: "f".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalRollbackReceipt(
  overrides: Partial<McpManagedLocalRollbackReceipt> = {},
): McpManagedLocalRollbackReceipt {
  const updated = syntheticMcpManagedLocalUpdateReceipt().server;
  const old = syntheticMcpManagedRollbackGeneration();
  const oldSnapshot = syntheticMcpManagedToolSnapshot({
    snapshot_id: "4".repeat(32),
    source: "local_package_probe",
    source_tree_digest: old.local_package_evidence.tree_digest,
    source_manifest_digest: old.local_package_evidence.manifest_digest,
    protocol_version: old.probe.protocol_version,
    tool_count: old.probe.tool_count,
    schema_digest: old.probe.schema_digest,
    reviewed_at: old.probe.checked_at,
  });
  const currentGeneration = syntheticMcpManagedRollbackGeneration({
    generation_id: "9".repeat(32),
    catalog_id: updated.catalog_id,
    server_version: updated.server_version,
    option_id: updated.option_id,
    plan_revision: updated.plan_revision,
    package_version: updated.package_version,
    local_package_evidence: updated.local_package_evidence ?? old.local_package_evidence,
    probe: updated.last_probe ?? old.probe,
    installed_at: updated.installed_at ?? old.installed_at,
    retained_at: "2040-01-01T10:04:00Z",
  });
  const server = syntheticMcpManagedServer({
    ...updated,
    catalog_id: old.catalog_id,
    server_version: old.server_version,
    option_id: old.option_id,
    plan_revision: old.plan_revision,
    option_label: old.option_label,
    package_identifier: old.package_identifier,
    package_version: old.package_version,
    runtime_hint: old.runtime_hint,
    risks: old.risks,
    updated_at: "2040-01-01T10:04:00Z",
    revision: 5,
    installed_plan_revision: old.plan_revision,
    installed_at: "2040-01-01T10:04:00Z",
    local_package_evidence: old.local_package_evidence,
    last_health_checked_at: old.probe.checked_at,
    last_probe: old.probe,
    tool_snapshot: syntheticToolSnapshotSummary(oldSnapshot),
    tool_review_state: "reviewable",
    rollback_generation: currentGeneration,
  });
  return {
    contract_version: "mcp-managed-local-rollback-receipt.v1",
    action: "rollback",
    server,
    preview_digest: "f".repeat(64),
    idempotent_replay: false,
    package_changed: true,
    process_started: false,
    process_tree_cleanup: "not_applicable",
    rollback_generation_retained: true,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalRollbackCleanupPreview(
  overrides: Partial<McpManagedLocalRollbackCleanupPreview> = {},
): McpManagedLocalRollbackCleanupPreview {
  return {
    contract_version: "mcp-managed-local-rollback-cleanup-preview.v1",
    action: "cleanup_rollback_generation",
    management_id: "9".repeat(32),
    expected_revision: 4,
    rollback_version: "1.2.3",
    rollback_plan_revision: "d".repeat(64),
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
      "verify_rollback_tree_digest",
      "quarantine_verified_rollback_generation",
      "remove_quarantined_rollback_generation",
      "keep_current_generation_installed",
      "no_process_start",
      "no_connection_retained",
      "no_tool_authority",
    ],
    preview_digest: "1".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalRollbackCleanupReceipt(
  overrides: Partial<McpManagedLocalRollbackCleanupReceipt> = {},
): McpManagedLocalRollbackCleanupReceipt {
  const server = syntheticMcpManagedServer({
    ...syntheticMcpManagedLocalUpdateReceipt().server,
    updated_at: "2040-01-01T10:04:00Z",
    revision: 5,
    rollback_generation: null,
  });
  return {
    contract_version: "mcp-managed-local-rollback-cleanup-receipt.v1",
    action: "cleanup_rollback_generation",
    server,
    preview_digest: "1".repeat(64),
    idempotent_replay: false,
    filesystem_changed: true,
    rollback_generation_retained: false,
    process_started: false,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalOperationRecoveryPreview(
  overrides: Partial<McpManagedLocalOperationRecoveryPreview> = {},
): McpManagedLocalOperationRecoveryPreview {
  return {
    contract_version: "mcp-managed-local-operation-recovery-preview.v1",
    action: "recover_interrupted_local_operation",
    management_id: "9".repeat(32),
    expected_revision: 5,
    interrupted_action: "update",
    availability: "available",
    reason: "ready_for_native_confirmation",
    effects: [
      "verify_operation_journal",
      "restore_durable_current_generation",
      "discard_verified_staged_target",
      "clear_cleanup_state",
      "no_process_start",
      "no_connection_retained",
      "no_tool_authority",
    ],
    preview_digest: "2".repeat(64),
    native_confirmation_required: true,
    ...overrides,
  };
}

export function syntheticMcpManagedLocalOperationRecoveryReceipt(
  overrides: Partial<McpManagedLocalOperationRecoveryReceipt> = {},
): McpManagedLocalOperationRecoveryReceipt {
  return {
    contract_version: "mcp-managed-local-operation-recovery-receipt.v1",
    action: "recover_interrupted_local_operation",
    recovered_action: "update",
    server: syntheticMcpManagedLocalLifecycleReceipt().server,
    preview_digest: "2".repeat(64),
    idempotent_replay: false,
    filesystem_state_verified: true,
    process_started: false,
    endpoint_connected: false,
    connection_retained: false,
    persistent_host_started: false,
    tool_authority_granted: false,
    ...overrides,
  };
}
