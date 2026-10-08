import type {
  McpManagedHostBinding,
  McpManagedHostCleanupState,
  McpManagedHostStartEffect,
  McpManagedHostStartPreview,
  McpManagedHostState,
  McpManagedHostStatus,
  McpManagedPermission,
  McpManagedProjectRuntime,
  McpManagedReadyTool,
} from "./contracts";

export class McpManagedRuntimePayloadError extends Error {
  constructor() {
    super("MCP managed runtime response was invalid");
    this.name = "McpManagedRuntimePayloadError";
  }
}

function fail(): never {
  throw new McpManagedRuntimePayloadError();
}

function row(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).sort().join("\u0000") === [...keys].sort().join("\u0000");
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): value is T {
  return typeof value === "string" && values.includes(value as T);
}

function boundedText(value: unknown, min: number, max: number): value is string {
  return typeof value === "string"
    && value.length >= min
    && value.length <= max
    && value.trim() === value
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

function timestamp(value: unknown, nullable = true): value is string | null {
  return (nullable && value === null)
    || (boundedText(value, 20, 40) && !Number.isNaN(Date.parse(value)));
}

const ID = /^[0-9a-f]{32}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;
// Host failures are a closed, content-free taxonomy.  Do not accept an
// arbitrary server/SDK `.code` value merely because it looks identifier-like:
// this projection is consumed by UI diagnostics and must never become an
// attacker-controlled text channel.
const SAFE_HOST_ERROR_CODES = new Set([
  "mcp_host_cleanup_unconfirmed",
  "mcp_host_content_encoding_unsupported",
  "mcp_host_deadline_exceeded",
  "mcp_host_deadline_invalid",
  "mcp_host_egress_origin_changed",
  "mcp_host_endpoint_address_invalid",
  "mcp_host_endpoint_identity_changed",
  "mcp_host_endpoint_invalid",
  "mcp_host_endpoint_not_public",
  "mcp_host_endpoint_unreachable",
  "mcp_host_endpoint_unresolvable",
  "mcp_host_headers_invalid",
  "mcp_host_headers_too_large",
  "mcp_host_jsonrpc_invalid",
  "mcp_host_management_identity_invalid",
  "mcp_host_probe_failed",
  "mcp_host_probe_receipt_invalid",
  "mcp_host_process_output_limit",
  "mcp_host_process_truth_invalid",
  "mcp_host_process_visibility_unconfirmed",
  "mcp_host_protocol_unsupported",
  "mcp_host_redirect_refused",
  "mcp_host_request_too_large",
  "mcp_host_response_count_exceeded",
  "mcp_host_response_too_large",
  "mcp_host_sse_event_count_exceeded",
  "mcp_host_stdio_arguments_invalid",
  "mcp_host_stdio_environment_invalid",
  "mcp_host_stdio_executable_invalid",
  "mcp_host_stdio_identity_invalid",
  "mcp_host_stdio_pipes_unavailable",
  "mcp_host_stdio_start_failed",
  "mcp_host_stdio_transport_failed",
  "mcp_host_stdio_working_directory_invalid",
  "mcp_host_tls_policy_invalid",
  "mcp_host_tool_count_exceeded",
  "mcp_host_tool_alias_collision",
  "mcp_host_tool_cursor_invalid",
  "mcp_host_tool_identity_conflict",
  "mcp_host_tool_identity_invalid",
  "mcp_host_tool_listing_incomplete",
  "mcp_host_tool_metadata_invalid",
  "mcp_host_tool_metadata_total_exceeded",
  "mcp_host_tool_pages_exceeded",
  "mcp_host_tool_schema_dialect_unsupported",
  "mcp_host_tool_schema_external_ref",
  "mcp_host_tool_schema_format_unsupported",
  "mcp_host_tool_schema_invalid",
  "mcp_host_tool_schema_keyword_unsupported",
  "mcp_host_tool_schema_pattern_unsafe",
  "mcp_host_tool_schema_recursive",
  "mcp_host_tool_schema_ref_invalid",
  "mcp_host_tool_schema_too_complex",
  "mcp_host_tool_schema_too_large",
  "mcp_host_tool_schema_total_exceeded",
  "mcp_host_transport_auth_unsupported",
  "mcp_host_transport_mismatch",
  "mcp_host_visible_window_detected",
  "mcp_managed_host_binding_changed",
  "mcp_managed_host_connection_unavailable",
  "mcp_managed_host_contract_drift",
  "mcp_managed_host_failed",
  "mcp_managed_host_health_failed",
  "mcp_managed_host_process_evidence_missing",
  "mcp_managed_host_start_cancelled",
  "mcp_managed_host_start_failed",
  "mcp_managed_host_start_timeout",
  "mcp_managed_host_stop_failed",
  "mcp_managed_host_stop_timeout",
  "mcp_managed_host_tool_snapshot_conflict",
  "mcp_managed_runtime_shutdown",
  "mcp_managed_runtime_unavailable",
  "mcp_tool_admission_stale",
  "mcp_tool_arguments_changed",
  "mcp_tool_call_failed",
  "mcp_tool_call_interrupted",
  "mcp_tool_cancelled",
  "mcp_tool_deadline_exceeded",
  "mcp_tool_host_not_ready",
  "mcp_tool_result_content_unsupported",
  "mcp_tool_result_incomplete",
  "mcp_tool_result_malformed",
  "mcp_tool_result_schema_mismatch",
  "mcp_tool_result_too_complex",
  "mcp_tool_result_too_large",
]);
const ALIAS = /^[A-Za-z0-9_-]+$/u;
const PERMISSIONS: readonly McpManagedPermission[] = [
  "process_spawn",
  "filesystem_read",
  "filesystem_write",
  "network_egress",
  "credential_use",
];
const HOST_STATES: readonly McpManagedHostState[] = [
  "not_started",
  "starting",
  "ready",
  "unhealthy",
  "stopping",
  "cleanup_required",
];
const CLEANUP_STATES: readonly McpManagedHostCleanupState[] = [
  "not_applicable",
  "pending",
  "verified",
  "unconfirmed",
];
const REASONS_BY_STATE: Record<McpManagedHostState, readonly string[]> = {
  not_started: ["never_started", "stopped_by_owner", "stopped_after_restart", "start_cancelled", "app_shutdown"],
  starting: ["start_requested"],
  ready: ["healthy"],
  unhealthy: ["transport_failed", "process_exited", "health_timeout", "contract_drift", "binding_changed", "server_changed"],
  stopping: ["owner_stop", "app_shutdown", "binding_changed", "server_changed"],
  cleanup_required: ["cleanup_unconfirmed"],
};

function canonicalPermissions(value: unknown): McpManagedPermission[] {
  if (!Array.isArray(value) || value.length > PERMISSIONS.length
    || value.some((item) => !oneOf(item, PERMISSIONS))) fail();
  const result = value as McpManagedPermission[];
  if (new Set(result).size !== result.length
    || PERMISSIONS.filter((item) => result.includes(item)).join("\u0000") !== result.join("\u0000")) fail();
  return result;
}

function canonicalIds(value: unknown, min: number, max: number): string[] {
  if (!Array.isArray(value) || value.length < min || value.length > max
    || value.some((item) => typeof item !== "string" || !ID.test(item))) fail();
  const result = value as string[];
  if (new Set(result).size !== result.length
    || [...result].sort().join("\u0000") !== result.join("\u0000")) fail();
  return result;
}

function parseBinding(value: unknown): McpManagedHostBinding {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "management_id", "project_id", "server_revision",
    "project_binding_revision", "plan_revision", "option_kind", "transport",
    "tool_snapshot_id", "tool_schema_digest", "reviewed_tool_count",
    "admitted_tool_ids", "granted_permissions", "execution_scope",
    "tool_calls_available", "tool_routing_state",
  ])
    || item.contract_version !== "mcp-managed-host.v2"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || typeof item.project_id !== "string" || !ID.test(item.project_id)
    || !Number.isInteger(item.server_revision) || Number(item.server_revision) < 1
    || !Number.isInteger(item.project_binding_revision) || Number(item.project_binding_revision) < 1
    || typeof item.plan_revision !== "string" || !DIGEST.test(item.plan_revision)
    || !oneOf(item.option_kind, ["local_package", "remote_server"])
    || !oneOf(item.transport, ["stdio", "streamable-http", "sse"])
    || (item.option_kind === "local_package") !== (item.transport === "stdio")
    || typeof item.tool_snapshot_id !== "string" || !ID.test(item.tool_snapshot_id)
    || typeof item.tool_schema_digest !== "string" || !DIGEST.test(item.tool_schema_digest)
    || !Number.isInteger(item.reviewed_tool_count)
    || Number(item.reviewed_tool_count) < 1 || Number(item.reviewed_tool_count) > 256
    || item.execution_scope !== "current_app_run_owner_start_only"
    || item.tool_calls_available !== true
    || item.tool_routing_state !== "project_scoped_fresh_approval") fail();
  const admitted = canonicalIds(item.admitted_tool_ids, 1, 256);
  const permissions = canonicalPermissions(item.granted_permissions);
  if (admitted.length > Number(item.reviewed_tool_count)) fail();
  return {
    ...(item as unknown as McpManagedHostBinding),
    admitted_tool_ids: admitted,
    granted_permissions: permissions,
  };
}

const COMMON_EFFECTS: readonly McpManagedHostStartEffect[] = [
  "enumerate_exact_tool_contracts",
  "retain_connection_for_current_app_run",
  "periodic_contract_health_check",
  "register_admitted_project_tools",
  "tool_calls_require_fresh_native_approval",
  "no_automatic_restart",
];
const LOCAL_EFFECTS: readonly McpManagedHostStartEffect[] = [
  "execute_reviewed_local_package",
  "run_with_current_user_os_permissions",
  "own_hidden_process_tree",
  ...COMMON_EFFECTS,
];
const REMOTE_EFFECTS: readonly McpManagedHostStartEffect[] = [
  "open_reviewed_remote_connection",
  ...COMMON_EFFECTS,
];

export function parseMcpManagedHostStartPreview(value: unknown): McpManagedHostStartPreview {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "binding", "binding_digest", "execution_kind", "risk_notice",
    "effects", "availability", "reason", "native_confirmation_required",
    "preview_starts_host", "current_app_run_only", "automatic_start",
    "automatic_restart", "persists_across_app_restart",
    "model_tool_registration_available", "tool_calls_available", "tool_routing_state",
    "connection_material_in_preview", "preview_digest",
  ])
    || item.contract_version !== "mcp-managed-host-start-preview.v2"
    || typeof item.binding_digest !== "string" || !DIGEST.test(item.binding_digest)
    || typeof item.preview_digest !== "string" || !DIGEST.test(item.preview_digest)
    || item.availability !== "available"
    || item.reason !== "ready_for_native_confirmation"
    || item.native_confirmation_required !== true
    || item.preview_starts_host !== false
    || item.current_app_run_only !== true
    || item.automatic_start !== false
    || item.automatic_restart !== false
    || item.persists_across_app_restart !== false
    || item.model_tool_registration_available !== true
    || item.tool_calls_available !== true
    || item.tool_routing_state !== "project_scoped_fresh_approval"
    || item.connection_material_in_preview !== false
    || !Array.isArray(item.effects)) fail();
  const binding = parseBinding(item.binding);
  const local = binding.option_kind === "local_package";
  const effects = item.effects as McpManagedHostStartEffect[];
  const expected = local ? LOCAL_EFFECTS : REMOTE_EFFECTS;
  if (effects.join("\u0000") !== expected.join("\u0000")
    || item.execution_kind !== (local ? "local_native_process" : "reviewed_remote_connection")
    || item.risk_notice !== (local
      ? "local_native_code_uses_current_user_os_authority"
      : "remote_connection_uses_reviewed_configuration")) fail();
  return { ...(item as unknown as McpManagedHostStartPreview), binding, effects };
}

export function parseMcpManagedHostStatus(value: unknown): McpManagedHostStatus {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "management_id", "project_id", "state", "reason", "binding",
    "instance_id", "observed_tool_count", "observed_schema_digest", "started_at",
    "last_checked_at", "stopped_at", "last_transition_at", "process_started",
    "cleanup_state", "host_lease_active", "error_code", "tool_calls_available",
    "tool_routing_state", "connection_material_retained_in_status",
  ])
    || item.contract_version !== "mcp-managed-host.v2"
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || typeof item.project_id !== "string" || !ID.test(item.project_id)
    || !oneOf(item.state, HOST_STATES)
    || typeof item.reason !== "string" || !REASONS_BY_STATE[item.state].includes(item.reason)
    || (item.instance_id !== null && (typeof item.instance_id !== "string" || !ID.test(item.instance_id)))
    || (item.observed_tool_count !== null && (!Number.isInteger(item.observed_tool_count)
      || Number(item.observed_tool_count) < 0 || Number(item.observed_tool_count) > 256))
    || (item.observed_schema_digest !== null
      && (typeof item.observed_schema_digest !== "string" || !DIGEST.test(item.observed_schema_digest)))
    || (item.observed_tool_count === null) !== (item.observed_schema_digest === null)
    || !timestamp(item.started_at) || !timestamp(item.last_checked_at) || !timestamp(item.stopped_at)
    || !timestamp(item.last_transition_at, false)
    || typeof item.process_started !== "boolean"
    || !oneOf(item.cleanup_state, CLEANUP_STATES)
    || typeof item.host_lease_active !== "boolean"
    || (item.error_code !== null
      && (typeof item.error_code !== "string" || !SAFE_HOST_ERROR_CODES.has(item.error_code)))
    || typeof item.tool_calls_available !== "boolean"
    || !oneOf(item.tool_routing_state, ["inactive", "project_scoped_fresh_approval"])
    || item.connection_material_retained_in_status !== false) fail();
  const binding = item.binding === null ? null : parseBinding(item.binding);
  if (binding !== null
    && (binding.management_id !== item.management_id || binding.project_id !== item.project_id)) fail();
  const activeRouting = item.tool_calls_available === true
    && item.tool_routing_state === "project_scoped_fresh_approval";
  if ((item.state === "ready") !== activeRouting) fail();
  if (item.state === "not_started" && (item.instance_id !== null || item.started_at !== null
    || item.last_checked_at !== null || item.process_started !== false
    || item.host_lease_active !== false || item.error_code !== null
    || !["not_applicable", "verified"].includes(item.cleanup_state))) fail();
  if (item.state !== "not_started" && (binding === null || item.instance_id === null || item.started_at === null)) fail();
  if (item.state === "ready" && (item.host_lease_active !== true
    || item.last_checked_at === null || item.stopped_at !== null || item.error_code !== null
    || item.observed_tool_count !== binding?.reviewed_tool_count
    || item.observed_schema_digest !== binding?.tool_schema_digest
    || item.process_started !== (binding?.transport === "stdio")
    || item.cleanup_state !== (binding?.transport === "stdio" ? "pending" : "not_applicable"))) fail();
  if (item.state === "cleanup_required" && (item.host_lease_active !== false
    || item.cleanup_state !== "unconfirmed" || item.stopped_at === null || item.error_code === null)) fail();
  return { ...(item as unknown as McpManagedHostStatus), binding };
}

function parseReadyTool(value: unknown, projectId: string): McpManagedReadyTool {
  const item = row(value);
  if (!exactKeys(item, [
    "management_id", "project_id", "host_instance_id", "server_title", "tool_id",
    "name", "model_alias", "title", "description", "model_input_schema",
  ])
    || typeof item.management_id !== "string" || !ID.test(item.management_id)
    || item.project_id !== projectId
    || typeof item.host_instance_id !== "string" || !ID.test(item.host_instance_id)
    || !boundedText(item.server_title, 1, 100)
    || typeof item.tool_id !== "string" || !ID.test(item.tool_id)
    || !boundedText(item.name, 1, 128)
    || !boundedText(item.model_alias, 1, 64) || !ALIAS.test(item.model_alias)
    || (item.title !== null && !boundedText(item.title, 1, 256))
    || (item.description !== null && !boundedText(item.description, 1, 4_096))) fail();
  const schema = row(item.model_input_schema);
  return { ...(item as unknown as McpManagedReadyTool), model_input_schema: schema };
}

export function parseMcpManagedProjectRuntime(value: unknown): McpManagedProjectRuntime {
  const item = row(value);
  if (!exactKeys(item, [
    "contract_version", "project_id", "ready_host_count", "ready_tool_count", "tools",
    "automatic_start", "remembered_call_approval", "every_call_requires_native_approval",
  ])
    || item.contract_version !== "mcp-managed-runtime.v1"
    || typeof item.project_id !== "string" || !ID.test(item.project_id)
    || !Number.isInteger(item.ready_host_count) || Number(item.ready_host_count) < 0 || Number(item.ready_host_count) > 4
    || !Number.isInteger(item.ready_tool_count) || Number(item.ready_tool_count) < 0 || Number(item.ready_tool_count) > 256
    || !Array.isArray(item.tools) || item.tools.length !== item.ready_tool_count
    || item.automatic_start !== false || item.remembered_call_approval !== false
    || item.every_call_requires_native_approval !== true) fail();
  const tools = item.tools.map((tool) => parseReadyTool(tool, item.project_id as string));
  if (new Set(tools.map((tool) => tool.model_alias)).size !== tools.length
    || new Set(tools.map((tool) => tool.host_instance_id)).size > Number(item.ready_host_count)) fail();
  return { ...(item as unknown as McpManagedProjectRuntime), tools };
}
