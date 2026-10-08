"""Provider-neutral loopback contract for local Agent controllers.

The manifest contains no token, workspace path, transcript, or provider
credential.  It only describes the already-authenticated local HTTP surface
and its user-presence boundary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..domain import StrictModel


AgentOrchestrationMethod = Literal["GET", "POST", "PATCH", "DELETE"]
AgentOrchestrationAccess = Literal[
    "token_authenticated",
    "native_user_presence_only",
]
AgentOrchestrationResponse = Literal["json", "binary", "sse", "no_content"]


class AgentOrchestrationAuthentication(StrictModel):
    primary_scheme: Literal["bearer"] = "bearer"
    authorization_header: Literal["Authorization: Bearer <token>"] = (
        "Authorization: Bearer <token>"
    )
    alternate_header: Literal["X-Prompt-Enhancer-Token: <token>"] = (
        "X-Prompt-Enhancer-Token: <token>"
    )
    token_in_manifest: Literal[False] = False


class AgentOrchestrationBoundary(StrictModel):
    listener_scope: Literal["loopback_only"] = "loopback_only"
    provider_neutral: Literal[True] = True
    catalog_retention: Literal["local_metadata"] = "local_metadata"
    conversation_retention: Literal[
        "explicit_metadata_only_or_bounded_local_history"
    ] = "explicit_metadata_only_or_bounded_local_history"
    recovered_authority: Literal["read_only_until_native_revalidation"] = (
        "read_only_until_native_revalidation"
    )
    protected_effects: Literal["native_user_presence_only"] = (
        "native_user_presence_only"
    )
    event_payload_sensitivity: Literal["sensitive"] = "sensitive"
    remote_context_egress: Literal[
        "explicit_instruction_and_redaction_preview_required"
    ] = "explicit_instruction_and_redaction_preview_required"
    token_controller_may_approve: Literal[False] = False
    raw_transcript_mcp_exposed: Literal[False] = False
    remote_listener_supported: Literal[False] = False


class AgentOrchestrationEndpoint(StrictModel):
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    method: AgentOrchestrationMethod
    path_template: str = Field(min_length=1, max_length=240, pattern=r"^/")
    access: AgentOrchestrationAccess = "token_authenticated"
    response: AgentOrchestrationResponse = "json"
    purpose: str = Field(min_length=1, max_length=240)


class AgentOrchestrationProtocol(StrictModel):
    session_identity: Literal["project_id_and_session_id_are_both_required"] = (
        "project_id_and_session_id_are_both_required"
    )
    message_admission: Literal["one_message_only_when_session_is_idle"] = (
        "one_message_only_when_session_is_idle"
    )
    message_retry_semantics: Literal[
        "not_idempotent_do_not_retry_ambiguous_submission"
    ] = "not_idempotent_do_not_retry_ambiguous_submission"
    progress_cursor: Literal["monotonic_event_sequence_pass_last_seen_as_after"] = (
        "monotonic_event_sequence_pass_last_seen_as_after"
    )
    terminal_condition: Literal[
        "idle_pending_approval_null_cursor_at_last_seq_and_cleanup_confirmed"
    ] = "idle_pending_approval_null_cursor_at_last_seq_and_cleanup_confirmed"
    pending_approval: Literal[
        "surface_to_native_user_never_approve_from_token_controller"
    ] = "surface_to_native_user_never_approve_from_token_controller"
    approval_continuation: Literal[
        "resume_from_cursor_without_message_resubmission_or_stop"
    ] = "resume_from_cursor_without_message_resubmission_or_stop"
    cleanup_quarantine: Literal[
        "return_cleanup_unconfirmed_never_report_settled"
    ] = "return_cleanup_unconfirmed_never_report_settled"
    retained_resume: Literal[
        "revision_bound_and_read_only_until_native_revalidation"
    ] = "revision_bound_and_read_only_until_native_revalidation"
    session_forking: Literal[
        "idempotent_revision_bound_settled_history_only_without_authority"
    ] = "idempotent_revision_bound_settled_history_only_without_authority"
    artifact_truth: Literal[
        "metadata_is_lineage_only_content_is_rehashed_on_every_read"
    ] = "metadata_is_lineage_only_content_is_rehashed_on_every_read"
    external_write_artifacts: Literal[
        "saved_chats_retain_verified_receipts_only_for_artifact_lineage"
    ] = "saved_chats_retain_verified_receipts_only_for_artifact_lineage"
    artifact_file_moves: Literal[
        "verified_move_preserves_matching_artifact_identity_as_immutable_path_version"
    ] = "verified_move_preserves_matching_artifact_identity_as_immutable_path_version"
    workspace_reads: Literal[
        "bounded_to_the_admitted_workspace_and_reparse_points_fail_closed"
    ] = "bounded_to_the_admitted_workspace_and_reparse_points_fail_closed"
    workspace_mutation: Literal[
        "token_controller_may_propose_native_user_must_apply"
    ] = "token_controller_may_propose_native_user_must_apply"
    attachment_staging: Literal[
        "exact_project_and_session_inline_bytes_only_no_path_or_read_authority"
    ] = "exact_project_and_session_inline_bytes_only_no_path_or_read_authority"
    controller_ownership: Literal[
        "one_active_project_scoped_connection_per_live_session"
    ] = "one_active_project_scoped_connection_per_live_session"
    controller_reconnect: Literal[
        "same_connection_recovers_by_session_and_cursor_without_resubmission"
    ] = "same_connection_recovers_by_session_and_cursor_without_resubmission"
    controller_handoff: Literal[
        "two_party_revision_bound_same_project_no_native_authority_transfer"
    ] = "two_party_revision_bound_same_project_no_native_authority_transfer"


class AgentOrchestrationManifest(StrictModel):
    contract_version: Literal["local-agent-orchestration.v22"] = (
        "local-agent-orchestration.v22"
    )
    transport: Literal["loopback_http"] = "loopback_http"
    route_coverage: Literal[
        "all_agent_routes_plus_controller_runtime_routes"
    ] = "all_agent_routes_plus_controller_runtime_routes"
    authentication: AgentOrchestrationAuthentication = Field(
        default_factory=AgentOrchestrationAuthentication
    )
    boundaries: AgentOrchestrationBoundary = Field(
        default_factory=AgentOrchestrationBoundary
    )
    protocol: AgentOrchestrationProtocol = Field(
        default_factory=AgentOrchestrationProtocol
    )
    openapi_path: Literal["/openapi.json"] = "/openapi.json"
    endpoints: tuple[AgentOrchestrationEndpoint, ...]

    @model_validator(mode="after")
    def validate_complete_v22_surface(self) -> "AgentOrchestrationManifest":
        """Reject a downgraded or internally inconsistent discovery document.

        The same strict model is used by the bundled controller client, so a
        process cannot silently replace the complete v22 contract with a small
        allowlist or relabel native-only operations as bearer-authorized.
        """

        if len(self.endpoints) != 77:
            raise ValueError("the v22 controller surface must declare 77 routes")
        operations = [item.operation for item in self.endpoints]
        if len(operations) != len(set(operations)):
            raise ValueError("controller operation names must be unique")
        routes = [
            (item.method, item.path_template.partition("?")[0])
            for item in self.endpoints
        ]
        if len(routes) != len(set(routes)):
            raise ValueError("controller method and path pairs must be unique")

        agent_routes = 0
        runtime_routes = 0
        for item in self.endpoints:
            path, separator, query = item.path_template.partition("?")
            if any(character in item.path_template for character in ("\\", "#", "\r", "\n", "\x00")):
                raise ValueError("controller path templates must be local relative paths")
            if any(part == ".." for part in path.split("/")):
                raise ValueError("controller path templates cannot traverse")
            if separator and query not in {
                "after={sequence}",
                "expected_revision={expected_revision}",
                (
                    "expected_catalog_revision={expected_catalog_revision}"
                    "&expected_history_revision={expected_history_revision}"
                ),
            }:
                raise ValueError("controller path template query is unsupported")
            if path.startswith("/v1/agent/"):
                agent_routes += 1
            elif path.startswith("/v1/local-models/"):
                runtime_routes += 1
            else:
                raise ValueError("controller routes must stay on the declared local API")
        if agent_routes != 72 or runtime_routes != 5:
            raise ValueError("the v22 controller route groups are incomplete")

        native_operations = {
            item.operation
            for item in self.endpoints
            if item.access == "native_user_presence_only"
        }
        if native_operations != {
            "capture_artifact",
            "remove_artifact",
            "revalidate_recovered_authority",
            "apply_file_create",
            "apply_directory_create",
            "apply_directory_move",
            "apply_file_trash",
            "apply_file_move",
            "apply_file_edit",
            "apply_workspace_transaction",
            "apply_change_restore",
            "approve_protected_action",
        }:
            raise ValueError("the v5 native review boundary is incomplete")

        required = {
            "discover",
            "create_project",
            "list_projects_page",
            "get_managed_mcp_project_runtime",
            "list_project_sessions_page",
            "list_catalog_sessions_page",
            "list_artifacts_page",
            "create_live_session",
            "get_live_session",
            "get_session_context",
            "stage_attachment_inline",
            "send_message",
            "propose_workspace_lifecycle",
            "propose_file_transaction",
            "propose_file_write",
            "preview_artifact_document",
            "preview_artifact_capture",
            "export_artifact_lineage",
            "update_artifact",
            "remove_artifact",
            "preview_attachment_document",
            "poll_events",
            "stop_turn",
            "close_live_session",
            "read_workspace_file",
            "search_workspace_text",
            "preview_file_create",
            "preview_file_edit",
            "review_changes",
            "preview_change_restore",
            "apply_change_restore",
            "fork_retained_session",
            "switch_local_runtime",
            "stop_local_runtime",
        }
        if not required.issubset(operations):
            raise ValueError("the v22 controller lifecycle is incomplete")
        return self


def agent_orchestration_manifest() -> AgentOrchestrationManifest:
    """Return the content-free v22 controller discovery document."""

    endpoint = AgentOrchestrationEndpoint
    return AgentOrchestrationManifest(
        endpoints=(
            endpoint(
                operation="discover",
                method="GET",
                path_template="/v1/agent/orchestration",
                purpose="Discover this stable contract and its safety boundaries.",
            ),
            endpoint(
                operation="get_managed_mcp_project_runtime",
                method="GET",
                path_template="/v1/agent/mcp/projects/{project_id}/runtime",
                purpose=(
                    "Read content-free ready-host and admitted-tool routing truth "
                    "for one exact Agent project."
                ),
            ),
            endpoint(
                operation="list_projects",
                method="GET",
                path_template="/v1/agent/projects",
                purpose="List durable Agent project metadata.",
            ),
            endpoint(
                operation="list_projects_page",
                method="GET",
                path_template="/v1/agent/projects/page",
                purpose="Page durable Agent project metadata through one exact snapshot.",
            ),
            endpoint(
                operation="create_project",
                method="POST",
                path_template="/v1/agent/projects",
                purpose="Create a durable Agent project.",
            ),
            endpoint(
                operation="get_project",
                method="GET",
                path_template="/v1/agent/projects/{project_id}",
                purpose="Read one exact durable Agent project record.",
            ),
            endpoint(
                operation="update_project",
                method="PATCH",
                path_template="/v1/agent/projects/{project_id}",
                purpose="Rename, pin, archive, or restore one project.",
            ),
            endpoint(
                operation="delete_project",
                method="DELETE",
                path_template=(
                    "/v1/agent/projects/{project_id}"
                    "?expected_revision={expected_revision}"
                ),
                response="no_content",
                purpose="Revision-bound deletion of one empty project after an explicit controller request.",
            ),
            endpoint(
                operation="list_project_sessions",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions",
                purpose="List durable chat metadata for one project.",
            ),
            endpoint(
                operation="list_project_sessions_page",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/page",
                purpose="Page one project's durable chat metadata through one exact snapshot.",
            ),
            endpoint(
                operation="list_catalog_sessions",
                method="GET",
                path_template="/v1/agent/catalog/sessions",
                purpose="Search durable chat metadata across projects.",
            ),
            endpoint(
                operation="list_catalog_sessions_page",
                method="GET",
                path_template="/v1/agent/catalog/sessions/page",
                purpose="Page searched durable chat metadata through one exact snapshot.",
            ),
            endpoint(
                operation="get_catalog_session",
                method="GET",
                path_template="/v1/agent/catalog/sessions/{session_id}",
                purpose="Read one exact durable chat record and its availability.",
            ),
            endpoint(
                operation="update_catalog_session",
                method="PATCH",
                path_template="/v1/agent/catalog/sessions/{session_id}",
                purpose="Rename, pin, archive, restore, or move chat metadata.",
            ),
            endpoint(
                operation="delete_catalog_session",
                method="DELETE",
                path_template=(
                    "/v1/agent/catalog/sessions/{session_id}"
                    "?expected_catalog_revision={expected_catalog_revision}"
                    "&expected_history_revision={expected_history_revision}"
                ),
                response="no_content",
                purpose="Revision-bound deletion of one durable chat record and its exact retained-history head.",
            ),
            endpoint(
                operation="list_live_sessions",
                method="GET",
                path_template="/v1/agent/sessions",
                purpose="List the currently live, memory-backed chats.",
            ),
            endpoint(
                operation="read_retained_history",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/events",
                purpose="Read the bounded retained event journal for one exact project and chat.",
            ),
            endpoint(
                operation="fork_retained_session",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/forks",
                purpose="Idempotently branch one revision-bound settled history prefix without copying live authority.",
            ),
            endpoint(
                operation="resume_retained_session",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/resume",
                purpose="Recover a revision-bound chat without restoring approvals or mutation authority.",
            ),
            endpoint(
                operation="export_retained_history",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/export",
                purpose="Explicitly export one bounded local chat journal as JSON.",
            ),
            endpoint(
                operation="list_artifacts",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts",
                purpose="List immutable artifact lineage projected from reviewed writes and native captures.",
            ),
            endpoint(
                operation="list_artifacts_page",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/page",
                purpose="Page immutable artifact lineage through one exact chat snapshot.",
            ),
            endpoint(
                operation="preview_artifact_capture",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/capture-preview",
                purpose="Inspect one bounded workspace file revision for a later native-only artifact capture without returning its bytes.",
            ),
            endpoint(
                operation="get_artifact",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}",
                purpose="Read one artifact lineage and its current availability without returning file bytes.",
            ),
            endpoint(
                operation="export_artifact_lineage",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/export",
                purpose="Export exact-revision artifact lineage metadata after digest-verifying one selected workspace version, without returning file bytes.",
            ),
            endpoint(
                operation="update_artifact",
                method="PATCH",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}",
                purpose="Revision-safely rename, archive, restore, or recover one artifact lineage record.",
            ),
            endpoint(
                operation="remove_artifact",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/remove",
                access="native_user_presence_only",
                purpose="Move one exact archived artifact lineage record to removed after native confirmation.",
            ),
            endpoint(
                operation="preview_artifact_document",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/preview",
                purpose="Read one bounded local document preview with exact artifact lineage and no reusable file authority.",
            ),
            endpoint(
                operation="read_artifact_content",
                method="GET",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/versions/{version_id}/content",
                response="binary",
                purpose="Read digest-revalidated workspace bytes for one exact immutable artifact version.",
            ),
            endpoint(
                operation="capture_artifact",
                method="POST",
                path_template="/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts",
                access="native_user_presence_only",
                purpose="Capture one exact digest-bound workspace file after native confirmation.",
            ),
            endpoint(
                operation="get_local_runtime",
                method="GET",
                path_template="/v1/local-models/runtime",
                purpose="Read requested, served, cleanup, capability, and context truth for the global model runtime.",
            ),
            endpoint(
                operation="get_local_model_compatibility",
                method="GET",
                path_template="/v1/local-models/compatibility",
                purpose="Read path-free GGUF identity, runtime adapter, and live executable compatibility receipts.",
            ),
            endpoint(
                operation="count_local_chat_input_tokens",
                method="POST",
                path_template="/v1/local-models/{alias}/v1/chat/completions/input_tokens",
                purpose="Apply the exact served model chat template and return its input-token count without inference.",
            ),
            endpoint(
                operation="switch_local_runtime",
                method="POST",
                path_template="/v1/local-models/runtime/switch",
                purpose="Revision-safely unload the current model and load one selected model and placement.",
            ),
            endpoint(
                operation="stop_local_runtime",
                method="POST",
                path_template="/v1/local-models/runtime/stop",
                purpose="Revision-safely stop the served model and report cleanup evidence.",
            ),
            endpoint(
                operation="create_live_session",
                method="POST",
                path_template="/v1/agent/sessions",
                purpose="Open a live chat for an admitted workspace and local model.",
            ),
            endpoint(
                operation="get_live_session",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}",
                purpose="Read current chat and runtime state.",
            ),
            endpoint(
                operation="get_session_context",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/context",
                purpose="Read the exact session-and-turn-bound context preflight receipt without message content.",
            ),
            endpoint(
                operation="send_message",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/messages",
                purpose="Start one asynchronous Agent turn.",
            ),
            endpoint(
                operation="propose_file_write",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/write-proposals",
                purpose="Offer one exact revision-bound file create or edit for native diff review without direct apply authority.",
            ),
            endpoint(
                operation="propose_file_transaction",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/write-transaction-proposals",
                purpose="Offer two to eight exact absence-bound creates or revision-bound edits for one native review and failure-atomic publication without direct apply authority.",
            ),
            endpoint(
                operation="propose_workspace_lifecycle",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/lifecycle-proposals",
                purpose="Offer one exact directory create, directory move, revision-bound file move, or recoverable file trash for native review without direct apply authority.",
            ),
            endpoint(
                operation="switch_session_model",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/model",
                purpose="Bind an idle live chat to the exact capability-verified served model.",
            ),
            endpoint(
                operation="revalidate_recovered_authority",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/authority",
                access="native_user_presence_only",
                purpose="Revalidate workspace mutation capabilities for one recovered idle chat.",
            ),
            endpoint(
                operation="list_attachments",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/attachments",
                purpose="List capability-bound image, audio, and locally projected document attachments staged for one live chat.",
            ),
            endpoint(
                operation="stage_attachment",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/attachments",
                purpose="Stage bounded image, audio, or supported document bytes for a capability-verified live chat.",
            ),
            endpoint(
                operation="stage_attachment_inline",
                method="POST",
                path_template=(
                    "/v1/agent/projects/{project_id}/sessions/{session_id}/"
                    "attachments/stage-inline"
                ),
                purpose=(
                    "Stage caller-supplied, integrity-bound image, audio, or supported document "
                    "bytes for one exact project and live chat without accepting a filesystem path."
                ),
            ),
            endpoint(
                operation="delete_attachment",
                method="DELETE",
                path_template="/v1/agent/sessions/{session_id}/attachments/{attachment_id}",
                response="no_content",
                purpose="Remove one staged attachment before it is referenced by a turn.",
            ),
            endpoint(
                operation="preview_attachment_document",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/attachments/{attachment_id}/document-preview",
                purpose="Read a bounded no-store excerpt of one locally projected staged document without returning original bytes.",
            ),
            endpoint(
                operation="read_attachment_content",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/attachments/{attachment_id}/content",
                response="binary",
                purpose="Read one exact staged native image or audio attachment through the authenticated no-store boundary.",
            ),
            endpoint(
                operation="poll_events",
                method="GET",
                path_template=(
                    "/v1/agent/sessions/{session_id}/events?after={sequence}"
                ),
                purpose="Read a bounded event page after a known sequence.",
            ),
            endpoint(
                operation="stream_events",
                method="GET",
                path_template=(
                    "/v1/agent/sessions/{session_id}/events/stream?after={sequence}"
                ),
                response="sse",
                purpose=(
                    "Stream event pages through settled success or an explicit "
                    "cleanup-quarantine page; EOF alone is not success."
                ),
            ),
            endpoint(
                operation="stop_turn",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/stop",
                purpose="Request cancellation of the current turn without unloading the model.",
            ),
            endpoint(
                operation="close_live_session",
                method="DELETE",
                path_template="/v1/agent/sessions/{session_id}",
                response="no_content",
                purpose=(
                    "Close one exact idle live chat while retaining its durable catalog "
                    "record and any locally retained history."
                ),
            ),
            endpoint(
                operation="inspect_workspace",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/workspace/discovery",
                purpose="Read the bounded workspace inventory and provenance state.",
            ),
            endpoint(
                operation="list_workspace_tree",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/workspace/tree",
                purpose="List one bounded directory page inside the admitted workspace.",
            ),
            endpoint(
                operation="search_workspace_text",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/workspace/search",
                purpose=(
                    "Search bounded application-readable UTF-8 text with exact "
                    "coverage and limit evidence."
                ),
            ),
            endpoint(
                operation="read_workspace_file",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/workspace/file",
                purpose="Read one bounded UTF-8 text file inside the admitted workspace.",
            ),
            endpoint(
                operation="preview_file_create",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/creates",
                purpose="Prepare a digest-bound file-create preview without changing the workspace.",
            ),
            endpoint(
                operation="apply_file_create",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/creates/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged file-create preview after native confirmation.",
            ),
            endpoint(
                operation="preview_directory_create",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/directories",
                purpose="Prepare a directory-create preview without changing the workspace.",
            ),
            endpoint(
                operation="apply_directory_create",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/directories/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged directory-create preview after native confirmation.",
            ),
            endpoint(
                operation="preview_directory_move",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/directory-moves",
                purpose="Prepare a no-overwrite directory-move preview without changing the workspace.",
            ),
            endpoint(
                operation="apply_directory_move",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/directory-moves/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged directory-move preview after native confirmation.",
            ),
            endpoint(
                operation="preview_file_trash",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/file-trash",
                purpose="Prepare a recoverable file-trash preview without changing the workspace.",
            ),
            endpoint(
                operation="apply_file_trash",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/file-trash/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Move one unchanged file preview to the platform trash after native confirmation.",
            ),
            endpoint(
                operation="preview_file_move",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/moves",
                purpose="Prepare a no-overwrite file-move preview without changing the workspace.",
            ),
            endpoint(
                operation="apply_file_move",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/moves/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged file-move preview after native confirmation.",
            ),
            endpoint(
                operation="preview_file_edit",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/previews",
                purpose="Prepare a base-digest-bound text edit and unified diff without writing it.",
            ),
            endpoint(
                operation="apply_file_edit",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/previews/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged text-edit preview after native confirmation.",
            ),
            endpoint(
                operation="preview_workspace_transaction",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/transactions",
                purpose="Prepare an atomic multi-file transaction and diffs without writing them.",
            ),
            endpoint(
                operation="apply_workspace_transaction",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/workspace/transactions/{plan_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged atomic transaction after native confirmation.",
            ),
            endpoint(
                operation="review_changes",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/changes",
                purpose="Read the reviewed change-set projection for the live chat.",
            ),
            endpoint(
                operation="read_change_diff",
                method="GET",
                path_template="/v1/agent/sessions/{session_id}/changes/diff",
                purpose="Read one bounded unified diff for the reviewed live-chat change set.",
            ),
            endpoint(
                operation="preview_change_restore",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/changes/restores",
                purpose="Prepare one inverse reviewed-path restore without changing the workspace.",
            ),
            endpoint(
                operation="apply_change_restore",
                method="POST",
                path_template="/v1/agent/sessions/{session_id}/changes/restores/{preview_id}/apply",
                access="native_user_presence_only",
                purpose="Apply one unchanged restore preview and verify the exact filesystem result after native confirmation.",
            ),
            endpoint(
                operation="approve_protected_action",
                method="POST",
                path_template=(
                    "/v1/agent/sessions/{session_id}/approvals/{approval_id}"
                ),
                access="native_user_presence_only",
                purpose="Record the human decision for one pending protected action.",
            ),
        )
    )


__all__ = (
    "AgentOrchestrationAuthentication",
    "AgentOrchestrationBoundary",
    "AgentOrchestrationEndpoint",
    "AgentOrchestrationManifest",
    "AgentOrchestrationProtocol",
    "agent_orchestration_manifest",
)
