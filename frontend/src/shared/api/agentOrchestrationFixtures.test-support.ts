import type { AgentOrchestrationManifest } from "./contracts";

type Endpoint = AgentOrchestrationManifest["endpoints"][number];

function endpoint(
  operation: string,
  method: Endpoint["method"],
  path: string,
  options: Partial<Pick<Endpoint, "access" | "response">> = {},
): Endpoint {
  return {
    operation,
    method,
    path_template: path,
    access: options.access ?? "token_authenticated",
    response: options.response ?? "json",
    purpose: `Synthetic purpose for ${operation}.`,
  };
}

export function exampleAgentOrchestrationManifest(): AgentOrchestrationManifest {
  const agentEndpoints: Endpoint[] = [
    endpoint("discover", "GET", "/v1/agent/orchestration"),
    endpoint("get_managed_mcp_project_runtime", "GET", "/v1/agent/mcp/projects/{project_id}/runtime"),
    endpoint("list_projects", "GET", "/v1/agent/projects"),
    endpoint("list_projects_page", "GET", "/v1/agent/projects/page"),
    endpoint("create_project", "POST", "/v1/agent/projects"),
    endpoint(
      "delete_project",
      "DELETE",
      "/v1/agent/projects/{project_id}?expected_revision={expected_revision}",
      { response: "no_content" },
    ),
    endpoint("list_project_sessions", "GET", "/v1/agent/projects/{project_id}/sessions"),
    endpoint("list_project_sessions_page", "GET", "/v1/agent/projects/{project_id}/sessions/page"),
    endpoint("list_catalog_sessions_page", "GET", "/v1/agent/catalog/sessions/page"),
    endpoint("fork_retained_session", "POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/forks"),
    endpoint("create_live_session", "POST", "/v1/agent/sessions"),
    endpoint("get_session_context", "GET", "/v1/agent/sessions/{session_id}/context"),
    endpoint("stage_attachment_inline", "POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/attachments/stage-inline"),
    endpoint("send_message", "POST", "/v1/agent/sessions/{session_id}/messages"),
    endpoint("propose_file_write", "POST", "/v1/agent/sessions/{session_id}/write-proposals"),
    endpoint("propose_file_transaction", "POST", "/v1/agent/sessions/{session_id}/write-transaction-proposals"),
    endpoint("propose_workspace_lifecycle", "POST", "/v1/agent/sessions/{session_id}/lifecycle-proposals"),
    endpoint("poll_events", "GET", "/v1/agent/sessions/{session_id}/events?after={sequence}"),
    endpoint("stream_events", "GET", "/v1/agent/sessions/{session_id}/events/stream?after={sequence}", { response: "sse" }),
    endpoint("stop_turn", "POST", "/v1/agent/sessions/{session_id}/stop"),
    endpoint("list_workspace_tree", "GET", "/v1/agent/sessions/{session_id}/workspace/tree"),
    endpoint("read_workspace_file", "GET", "/v1/agent/sessions/{session_id}/workspace/file"),
    endpoint("search_workspace_text", "GET", "/v1/agent/sessions/{session_id}/workspace/search"),
    endpoint("preview_file_edit", "POST", "/v1/agent/sessions/{session_id}/workspace/previews"),
    endpoint("apply_file_edit", "POST", "/v1/agent/sessions/{session_id}/workspace/previews/{preview_id}/apply", { access: "native_user_presence_only" }),
    endpoint("preview_workspace_transaction", "POST", "/v1/agent/sessions/{session_id}/workspace/transactions"),
    endpoint("apply_workspace_transaction", "POST", "/v1/agent/sessions/{session_id}/workspace/transactions/{plan_id}/apply", { access: "native_user_presence_only" }),
    endpoint("list_artifacts", "GET", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts"),
    endpoint("list_artifacts_page", "GET", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/page"),
    endpoint("preview_artifact_capture", "POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/capture-preview"),
    endpoint("update_artifact", "PATCH", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}"),
    endpoint("remove_artifact", "POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/remove", { access: "native_user_presence_only" }),
    endpoint("read_artifact_content", "GET", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/content", { response: "binary" }),
    endpoint("preview_artifact_document", "GET", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/preview"),
    endpoint("export_artifact_lineage", "POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/export"),
    endpoint("preview_attachment_document", "GET", "/v1/agent/sessions/{session_id}/attachments/{attachment_id}/document-preview"),
    endpoint("preview_change_restore", "POST", "/v1/agent/sessions/{session_id}/changes/restores"),
    endpoint("apply_change_restore", "POST", "/v1/agent/sessions/{session_id}/changes/restores/{preview_id}/apply", { access: "native_user_presence_only" }),
  ];
  for (let index = 0; index < 8; index += 1) {
    agentEndpoints.push(endpoint(
      `native_effect_${index}`,
      "POST",
      `/v1/agent/sessions/{session_id}/synthetic-native-${index}`,
      { access: "native_user_presence_only" },
    ));
  }
  while (agentEndpoints.length < 72) {
    const index = agentEndpoints.length;
    agentEndpoints.push(endpoint(
      `agent_route_${index}`,
      "GET",
      `/v1/agent/synthetic-route-${index}`,
    ));
  }

  const runtimeEndpoints = [
    endpoint("get_local_runtime", "GET", "/v1/local-models/runtime"),
    endpoint("switch_local_runtime", "POST", "/v1/local-models/runtime/switch"),
    endpoint("stop_local_runtime", "POST", "/v1/local-models/runtime/stop"),
    endpoint("get_local_model_compatibility", "GET", "/v1/local-models/compatibility"),
    endpoint("count_local_chat_input_tokens", "POST", "/v1/local-models/{alias}/v1/chat/completions/input_tokens"),
  ];

  return {
    contract_version: "local-agent-orchestration.v22",
    transport: "loopback_http",
    route_coverage: "all_agent_routes_plus_controller_runtime_routes",
    authentication: {
      primary_scheme: "bearer",
      authorization_header: "Authorization: Bearer <token>",
      alternate_header: "X-Prompt-Enhancer-Token: <token>",
      token_in_manifest: false,
    },
    boundaries: {
      listener_scope: "loopback_only",
      provider_neutral: true,
      catalog_retention: "local_metadata",
      conversation_retention: "explicit_metadata_only_or_bounded_local_history",
      recovered_authority: "read_only_until_native_revalidation",
      protected_effects: "native_user_presence_only",
      event_payload_sensitivity: "sensitive",
      remote_context_egress: "explicit_instruction_and_redaction_preview_required",
      token_controller_may_approve: false,
      raw_transcript_mcp_exposed: false,
      remote_listener_supported: false,
    },
    protocol: {
      session_identity: "project_id_and_session_id_are_both_required",
      message_admission: "one_message_only_when_session_is_idle",
      message_retry_semantics: "not_idempotent_do_not_retry_ambiguous_submission",
      progress_cursor: "monotonic_event_sequence_pass_last_seen_as_after",
      terminal_condition: "idle_pending_approval_null_cursor_at_last_seq_and_cleanup_confirmed",
      pending_approval: "surface_to_native_user_never_approve_from_token_controller",
      approval_continuation: "resume_from_cursor_without_message_resubmission_or_stop",
      cleanup_quarantine: "return_cleanup_unconfirmed_never_report_settled",
      retained_resume: "revision_bound_and_read_only_until_native_revalidation",
      session_forking: "idempotent_revision_bound_settled_history_only_without_authority",
      artifact_truth: "metadata_is_lineage_only_content_is_rehashed_on_every_read",
      external_write_artifacts: "saved_chats_retain_verified_receipts_only_for_artifact_lineage",
      artifact_file_moves: "verified_move_preserves_matching_artifact_identity_as_immutable_path_version",
      workspace_reads: "bounded_to_the_admitted_workspace_and_reparse_points_fail_closed",
      workspace_mutation: "token_controller_may_propose_native_user_must_apply",
      attachment_staging: "exact_project_and_session_inline_bytes_only_no_path_or_read_authority",
      controller_ownership: "one_active_project_scoped_connection_per_live_session",
      controller_reconnect: "same_connection_recovers_by_session_and_cursor_without_resubmission",
      controller_handoff: "two_party_revision_bound_same_project_no_native_authority_transfer",
    },
    openapi_path: "/openapi.json",
    endpoints: [...agentEndpoints, ...runtimeEndpoints],
  };
}
