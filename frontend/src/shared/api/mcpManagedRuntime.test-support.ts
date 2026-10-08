import type {
  McpManagedHostBinding,
  McpManagedHostStartPreview,
  McpManagedHostStatus,
  McpManagedProjectRuntime,
} from "./contracts";

export function syntheticMcpManagedHostBinding(
  overrides: Partial<McpManagedHostBinding> = {},
): McpManagedHostBinding {
  return {
    contract_version: "mcp-managed-host.v2",
    management_id: "9".repeat(32),
    project_id: "f".repeat(32),
    server_revision: 4,
    project_binding_revision: 2,
    plan_revision: "d".repeat(64),
    option_kind: "remote_server",
    transport: "streamable-http",
    tool_snapshot_id: "3".repeat(32),
    tool_schema_digest: "1".repeat(64),
    reviewed_tool_count: 2,
    admitted_tool_ids: ["1".repeat(32), "2".repeat(32)],
    granted_permissions: ["network_egress"],
    execution_scope: "current_app_run_owner_start_only",
    tool_calls_available: true,
    tool_routing_state: "project_scoped_fresh_approval",
    ...overrides,
  };
}

export function syntheticMcpManagedHostStartPreview(
  overrides: Partial<McpManagedHostStartPreview> = {},
): McpManagedHostStartPreview {
  const binding = overrides.binding ?? syntheticMcpManagedHostBinding();
  const local = binding.option_kind === "local_package";
  return {
    contract_version: "mcp-managed-host-start-preview.v2",
    binding,
    binding_digest: "a".repeat(64),
    execution_kind: local ? "local_native_process" : "reviewed_remote_connection",
    risk_notice: local
      ? "local_native_code_uses_current_user_os_authority"
      : "remote_connection_uses_reviewed_configuration",
    effects: local ? [
      "execute_reviewed_local_package",
      "run_with_current_user_os_permissions",
      "own_hidden_process_tree",
      "enumerate_exact_tool_contracts",
      "retain_connection_for_current_app_run",
      "periodic_contract_health_check",
      "register_admitted_project_tools",
      "tool_calls_require_fresh_native_approval",
      "no_automatic_restart",
    ] : [
      "open_reviewed_remote_connection",
      "enumerate_exact_tool_contracts",
      "retain_connection_for_current_app_run",
      "periodic_contract_health_check",
      "register_admitted_project_tools",
      "tool_calls_require_fresh_native_approval",
      "no_automatic_restart",
    ],
    availability: "available",
    reason: "ready_for_native_confirmation",
    native_confirmation_required: true,
    preview_starts_host: false,
    current_app_run_only: true,
    automatic_start: false,
    automatic_restart: false,
    persists_across_app_restart: false,
    model_tool_registration_available: true,
    tool_calls_available: true,
    tool_routing_state: "project_scoped_fresh_approval",
    connection_material_in_preview: false,
    preview_digest: "b".repeat(64),
    ...overrides,
  };
}

export function syntheticMcpManagedHostStatus(
  overrides: Partial<McpManagedHostStatus> = {},
): McpManagedHostStatus {
  return {
    contract_version: "mcp-managed-host.v2",
    management_id: "9".repeat(32),
    project_id: "f".repeat(32),
    state: "not_started",
    reason: "never_started",
    binding: null,
    instance_id: null,
    observed_tool_count: null,
    observed_schema_digest: null,
    started_at: null,
    last_checked_at: null,
    stopped_at: null,
    last_transition_at: "2040-01-01T10:00:00Z",
    process_started: false,
    cleanup_state: "not_applicable",
    host_lease_active: false,
    error_code: null,
    tool_calls_available: false,
    tool_routing_state: "inactive",
    connection_material_retained_in_status: false,
    ...overrides,
  };
}

export function syntheticReadyMcpManagedHostStatus(
  overrides: Partial<McpManagedHostStatus> = {},
): McpManagedHostStatus {
  const binding = overrides.binding ?? syntheticMcpManagedHostBinding();
  return syntheticMcpManagedHostStatus({
    management_id: binding.management_id,
    project_id: binding.project_id,
    state: "ready",
    reason: "healthy",
    binding,
    instance_id: "8".repeat(32),
    observed_tool_count: binding.reviewed_tool_count,
    observed_schema_digest: binding.tool_schema_digest,
    started_at: "2040-01-01T10:01:00Z",
    last_checked_at: "2040-01-01T10:01:01Z",
    last_transition_at: "2040-01-01T10:01:01Z",
    process_started: binding.transport === "stdio",
    cleanup_state: binding.transport === "stdio" ? "pending" : "not_applicable",
    host_lease_active: true,
    tool_calls_available: true,
    tool_routing_state: "project_scoped_fresh_approval",
    ...overrides,
  });
}

export function syntheticMcpManagedProjectRuntime(
  overrides: Partial<McpManagedProjectRuntime> = {},
): McpManagedProjectRuntime {
  const projectId = overrides.project_id ?? "f".repeat(32);
  const tools = overrides.tools ?? [{
    management_id: "9".repeat(32),
    project_id: projectId,
    host_instance_id: "8".repeat(32),
    server_title: "Synthetic Files",
    tool_id: "1".repeat(32),
    name: "synthetic_read",
    model_alias: "mcp_99999999_synthetic_read",
    title: "Synthetic read",
    description: "Reads fictional example data.",
    model_input_schema: {
      type: "object",
      properties: { query: { type: "string" } },
      required: ["query"],
      additionalProperties: false,
    },
  }];
  return {
    contract_version: "mcp-managed-runtime.v1",
    project_id: projectId,
    ready_host_count: tools.length === 0 ? 0 : 1,
    ready_tool_count: tools.length,
    tools,
    automatic_start: false,
    remembered_call_approval: false,
    every_call_requires_native_approval: true,
    ...overrides,
  };
}
