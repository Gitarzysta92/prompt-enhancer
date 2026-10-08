import type { AgentOrchestrationManifest } from "./contracts";

const ROOT_KEYS = new Set([
  "contract_version", "transport", "route_coverage", "authentication",
  "boundaries", "protocol", "openapi_path", "endpoints",
]);
const AUTHENTICATION_KEYS = new Set([
  "primary_scheme", "authorization_header", "alternate_header", "token_in_manifest",
]);
const BOUNDARY_KEYS = new Set([
  "listener_scope", "provider_neutral", "catalog_retention", "conversation_retention",
  "recovered_authority", "protected_effects", "event_payload_sensitivity",
  "remote_context_egress", "token_controller_may_approve", "raw_transcript_mcp_exposed",
  "remote_listener_supported",
]);
const PROTOCOL_KEYS = new Set([
  "session_identity", "message_admission", "message_retry_semantics", "progress_cursor",
  "terminal_condition", "pending_approval", "approval_continuation", "cleanup_quarantine",
  "retained_resume", "artifact_truth", "external_write_artifacts",
  "artifact_file_moves",
  "session_forking", "workspace_reads", "workspace_mutation", "attachment_staging",
  "controller_ownership", "controller_reconnect", "controller_handoff",
]);
const ENDPOINT_KEYS = new Set([
  "operation", "method", "path_template", "access", "response", "purpose",
]);
const METHODS = new Set(["GET", "POST", "PATCH", "DELETE"]);
const ACCESS = new Set(["token_authenticated", "native_user_presence_only"]);
const RESPONSES = new Set(["json", "binary", "sse", "no_content"]);
const OPERATION = /^[a-z][a-z0-9_]{0,63}$/u;
const REQUIRED_OPERATIONS = new Set([
  "discover", "list_projects", "create_project", "delete_project",
  "list_projects_page", "list_project_sessions_page", "list_catalog_sessions_page",
  "get_managed_mcp_project_runtime",
  "list_project_sessions", "fork_retained_session", "create_live_session", "send_message", "poll_events",
  "propose_file_transaction", "propose_file_write", "propose_workspace_lifecycle",
  "get_session_context",
  "stage_attachment_inline",
  "stream_events", "stop_turn", "list_workspace_tree", "read_workspace_file",
  "search_workspace_text",
  "preview_file_edit", "apply_file_edit", "preview_workspace_transaction",
  "apply_workspace_transaction", "list_artifacts", "list_artifacts_page", "preview_artifact_capture", "read_artifact_content",
  "preview_artifact_document", "export_artifact_lineage", "update_artifact", "remove_artifact",
  "preview_attachment_document",
  "preview_change_restore", "apply_change_restore",
  "get_local_runtime", "switch_local_runtime", "stop_local_runtime",
]);

export class AgentOrchestrationPayloadError extends Error {
  constructor() {
    super("Agent controller manifest was invalid");
    this.name = "AgentOrchestrationPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && Array.from(value).length >= 1
    && Array.from(value).length <= maximum;
}

function validAuthentication(value: unknown): boolean {
  return record(value)
    && exact(value, AUTHENTICATION_KEYS)
    && value.primary_scheme === "bearer"
    && value.authorization_header === "Authorization: Bearer <token>"
    && value.alternate_header === "X-Prompt-Enhancer-Token: <token>"
    && value.token_in_manifest === false;
}

function validBoundaries(value: unknown): boolean {
  return record(value)
    && exact(value, BOUNDARY_KEYS)
    && value.listener_scope === "loopback_only"
    && value.provider_neutral === true
    && value.catalog_retention === "local_metadata"
    && value.conversation_retention === "explicit_metadata_only_or_bounded_local_history"
    && value.recovered_authority === "read_only_until_native_revalidation"
    && value.protected_effects === "native_user_presence_only"
    && value.event_payload_sensitivity === "sensitive"
    && value.remote_context_egress === "explicit_instruction_and_redaction_preview_required"
    && value.token_controller_may_approve === false
    && value.raw_transcript_mcp_exposed === false
    && value.remote_listener_supported === false;
}

function validProtocol(value: unknown): boolean {
  return record(value)
    && exact(value, PROTOCOL_KEYS)
    && value.session_identity === "project_id_and_session_id_are_both_required"
    && value.message_admission === "one_message_only_when_session_is_idle"
    && value.message_retry_semantics === "not_idempotent_do_not_retry_ambiguous_submission"
    && value.progress_cursor === "monotonic_event_sequence_pass_last_seen_as_after"
    && value.terminal_condition === "idle_pending_approval_null_cursor_at_last_seq_and_cleanup_confirmed"
    && value.pending_approval === "surface_to_native_user_never_approve_from_token_controller"
    && value.approval_continuation === "resume_from_cursor_without_message_resubmission_or_stop"
    && value.cleanup_quarantine === "return_cleanup_unconfirmed_never_report_settled"
    && value.retained_resume === "revision_bound_and_read_only_until_native_revalidation"
    && value.session_forking === "idempotent_revision_bound_settled_history_only_without_authority"
    && value.artifact_truth === "metadata_is_lineage_only_content_is_rehashed_on_every_read"
    && value.external_write_artifacts === "saved_chats_retain_verified_receipts_only_for_artifact_lineage"
    && value.artifact_file_moves === "verified_move_preserves_matching_artifact_identity_as_immutable_path_version"
    && value.workspace_reads === "bounded_to_the_admitted_workspace_and_reparse_points_fail_closed"
    && value.workspace_mutation === "token_controller_may_propose_native_user_must_apply"
    && value.attachment_staging === "exact_project_and_session_inline_bytes_only_no_path_or_read_authority"
    && value.controller_ownership === "one_active_project_scoped_connection_per_live_session"
    && value.controller_reconnect === "same_connection_recovers_by_session_and_cursor_without_resubmission"
    && value.controller_handoff === "two_party_revision_bound_same_project_no_native_authority_transfer";
}

function validPathTemplate(value: unknown): value is string {
  if (!boundedText(value, 240) || /[\\#\u0000-\u001f]/u.test(value) || value.includes("..")) {
    return false;
  }
  const [path, query, ...rest] = value.split("?");
  if (rest.length > 0) return false;
  if (!(path.startsWith("/v1/agent/") || path.startsWith("/v1/local-models/"))) {
    return false;
  }
  if (query === undefined) return true;
  if (query === "after={sequence}") {
    return path.endsWith("/events") || path.endsWith("/events/stream");
  }
  if (query === "expected_revision={expected_revision}") {
    return path === "/v1/agent/projects/{project_id}";
  }
  return query === (
    "expected_catalog_revision={expected_catalog_revision}"
    + "&expected_history_revision={expected_history_revision}"
  ) && path === "/v1/agent/catalog/sessions/{session_id}";
}

function validEndpoint(value: unknown): value is Record<string, unknown> {
  if (
    !record(value) || !exact(value, ENDPOINT_KEYS)
    || typeof value.operation !== "string" || !OPERATION.test(value.operation)
    || !METHODS.has(String(value.method))
    || !validPathTemplate(value.path_template)
    || !ACCESS.has(String(value.access))
    || !RESPONSES.has(String(value.response))
    || !boundedText(value.purpose, 240) || value.purpose !== value.purpose.trim()
  ) return false;
  if (value.response === "sse" && value.method !== "GET") return false;
  if (value.response === "binary" && value.method !== "GET") return false;
  if (value.response === "no_content" && value.method !== "DELETE") return false;
  return value.access !== "native_user_presence_only" || value.method === "POST";
}

export function parseAgentOrchestrationManifest(value: unknown): AgentOrchestrationManifest {
  if (
    !record(value) || !exact(value, ROOT_KEYS)
    || value.contract_version !== "local-agent-orchestration.v22"
    || value.transport !== "loopback_http"
    || value.route_coverage !== "all_agent_routes_plus_controller_runtime_routes"
    || value.openapi_path !== "/openapi.json"
    || !validAuthentication(value.authentication)
    || !validBoundaries(value.boundaries)
    || !validProtocol(value.protocol)
    || !Array.isArray(value.endpoints)
    || value.endpoints.length !== 77
    || !value.endpoints.every(validEndpoint)
  ) throw new AgentOrchestrationPayloadError();

  const endpoints = value.endpoints as Record<string, unknown>[];
  const operations = new Set(endpoints.map((endpoint) => endpoint.operation as string));
  const routes = new Set(endpoints.map((endpoint) => (
    `${endpoint.method} ${String(endpoint.path_template).split("?", 1)[0]}`
  )));
  const agentRoutes = endpoints.filter((endpoint) => (
    String(endpoint.path_template).startsWith("/v1/agent/")
  ));
  const nativeRoutes = endpoints.filter((endpoint) => (
    endpoint.access === "native_user_presence_only"
  ));
  if (
    operations.size !== endpoints.length
    || routes.size !== endpoints.length
    || agentRoutes.length !== 72
    || nativeRoutes.length !== 12
    || [...REQUIRED_OPERATIONS].some((operation) => !operations.has(operation))
  ) throw new AgentOrchestrationPayloadError();

  return value as unknown as AgentOrchestrationManifest;
}
