"""Standard MCP bridge for the already-running Prompt Enhancer Agent API."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from typing import Any

from .. import __version__
from ..application.agent_controller_client import (
    AgentControllerClient,
    AgentControllerError,
)
from ..application.agent_catalog import MAX_AGENT_HISTORY_EVENTS
from ..application.agent_mcp_client_config import (
    AGENT_MCP_BEARER_ENV,
    AGENT_MCP_HTTP_PATH,
    AGENT_MCP_SERVER_NAME,
    AGENT_MCP_TOOL_TIMEOUT_SECONDS,
    build_agent_mcp_client_configs,
)
from ..application.agent_mcp_surface import (
    AGENT_MCP_CONTRACT_VERSION,
    AgentMcpSurface,
)
from ..config import AppSettings
from ..infrastructure.agent_controller_http import LoopbackAgentControllerTransport
from ..privacy import PrivacyBoundaryError, load_api_token
from .mcp import McpStdioServer


AGENT_MCP_INSTRUCTIONS = (
    "Start with agent_discover. Use agent_open, agent_context, agent_turn, agent_wait, "
    "agent_stop, agent_workspace, and agent_artifacts. agent_propose, agent_propose_transaction, "
    "and agent_propose_lifecycle stage native review; verified receipt required. Saved chats "
    "keep verified output artifact evidence. Calls need egress receipts. MCP cannot "
    "approve/delete/start shell/model. HTTP agent_control: durable owner, two-party handoff, "
    "no approval transfer. "
    "agent_runtime is opt-in; agent_close retains history."
)
AGENT_MCP_CONTEXT_EGRESS_NOTICE = (
    "prompt-enhancer agent-mcp: selected Agent messages, relative workspace data, runtime identity, "
    "and derived output may enter the connected model's context. Start with "
    "--acknowledge-sensitive-context-egress only after authorizing this integration and reviewing "
    "its redaction boundary. Every sensitive tool call still requires its own egress receipt."
)


def _base_url(settings: AppSettings, override: str | None) -> str:
    if override:
        return override
    host = f"[{settings.host}]" if ":" in settings.host else settings.host
    return f"http://{host}:{settings.port}"


def create_agent_mcp_surface(
    settings: AppSettings,
    *,
    base_url: str | None = None,
    request_timeout_seconds: float = 10.0,
    allow_model_lifecycle: bool = False,
) -> AgentMcpSurface:
    """Create a loopback-only surface without creating a token or process."""

    try:
        token = load_api_token(settings.api_token_path)
    except (OSError, PrivacyBoundaryError):
        raise AgentControllerError("controller_token_unavailable") from None
    transport = LoopbackAgentControllerTransport(
        _base_url(settings, base_url),
        token,
        timeout_seconds=request_timeout_seconds,
    )
    return AgentMcpSurface(
        AgentControllerClient(transport),
        allow_model_lifecycle=allow_model_lifecycle,
    )


def run_agent_mcp(settings: AppSettings, args: argparse.Namespace) -> int:
    """Serve Agent controller tools on the current stdio streams."""

    if not bool(args.acknowledge_sensitive_context_egress):
        print(AGENT_MCP_CONTEXT_EGRESS_NOTICE, file=sys.stderr)
        return 2
    try:
        surface = create_agent_mcp_surface(
            settings,
            base_url=args.base_url,
            request_timeout_seconds=float(args.request_timeout_seconds),
            allow_model_lifecycle=bool(args.acknowledge_model_lifecycle),
        )
    except AgentControllerError as error:
        print(
            json.dumps(
                {
                    "error": error.code,
                    "http_status": error.http_status,
                    "retryable": error.retryable,
                },
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    return McpStdioServer(
        surface,
        version=__version__,
        server_name=AGENT_MCP_SERVER_NAME,
        instructions=AGENT_MCP_INSTRUCTIONS,
    ).serve_forever()


def agent_mcp_config_document(
    settings: AppSettings | None = None,
    *,
    transport: str = "http",
    with_model_lifecycle: bool = False,
) -> dict[str, Any]:
    """Return token-free setup metadata without reading or writing private state."""

    if transport not in {"http", "stdio"}:
        raise ValueError("unsupported Agent MCP transport")
    if transport == "http" and with_model_lifecycle:
        raise ValueError(
            "HTTP model lifecycle authority is selected per scoped connection"
        )
    if transport == "http":
        resolved = settings or AppSettings.from_env()
        endpoint = _base_url(resolved, None) + AGENT_MCP_HTTP_PATH
        return {
            "contract_version": AGENT_MCP_CONTRACT_VERSION,
            "server_name": AGENT_MCP_SERVER_NAME,
            "transport": "streamable-http",
            "url": endpoint,
            "bearer_token_env_var": AGENT_MCP_BEARER_ENV,
            "tool_timeout_seconds": AGENT_MCP_TOOL_TIMEOUT_SECONDS,
            "advertised_tools": [
                "agent_discover",
                "agent_open",
                "agent_resume",
                "agent_fork",
                "agent_export",
                "agent_close",
                "agent_catalog",
                "agent_history",
                "agent_artifacts",
                "agent_stage_attachment",
                "agent_context",
                "agent_workspace",
                "agent_propose",
                "agent_propose_transaction",
                "agent_propose_lifecycle",
                "agent_turn",
                "agent_stop",
                "agent_wait",
                "agent_control",
            ],
            "safeguards": {
                "starts_prompt_enhancer_or_agent": False,
                "starts_shell_or_terminal": False,
                "starts_subprocess": False,
                "token_in_arguments_or_output": False,
                "loopback_only": True,
                "scoped_connection_required": True,
                "exact_project_scope_required": True,
                "cross_project_access_available": False,
                "generic_invoke_available": False,
                "native_approval_inherited": False,
                "revocable_connection": True,
                "durable_controller_ownership": True,
                "same_connection_reconnect_without_resubmission": True,
                "owner_only_wait_and_stop": True,
                "handoff_two_party_revision_bound_same_project": True,
                "handoff_inherits_native_approval": False,
                "native_release_requires_settled_backend_evidence": True,
                "per_sensitive_call_egress_receipt": True,
                "generic_mutation_requires_authorization": True,
                "delete_available_through_mcp": False,
                "destructive_catalog_delete_requires_agent_ui": True,
                "dedicated_catalog_tool_strict": True,
                "dedicated_resume_restores_authority": False,
                "resume_mutation_auto_retry": False,
                "dedicated_fork_copies_authority": False,
                "fork_ambiguous_retry_same_request_only": True,
                "fork_ambiguous_retry_limit": 1,
                "dedicated_export_exact_revision": True,
                "export_max_events": MAX_AGENT_HISTORY_EVENTS,
                "export_workspace_path_included": False,
                "export_attachment_bytes_included": False,
                "export_live_approval_state_included": False,
                "export_raw_tool_payloads_included": False,
                "dedicated_close_exact_revision": True,
                "close_live_session_only": True,
                "close_retained_catalog_deleted": False,
                "close_mutation_auto_retry": False,
                "dedicated_history_tool_read_only": True,
                "retained_history_excludes_raw_tool_payloads": True,
                "dedicated_artifact_tool_metadata_only": True,
                "artifact_capture_preview_content_free": True,
                "artifact_capture_requires_native_agent_ui": True,
                "artifact_bytes_available_through_mcp": False,
                "dedicated_context_tool_read_only": True,
                "context_snapshot_sequential_non_atomic": True,
                "context_omits_workspace_paths_instructions_process_ids": True,
                "attachment_inline_staging_available": True,
                "attachment_bytes_returned_through_mcp": False,
                "attachment_path_authority_available": False,
                "dedicated_workspace_tool_read_only": True,
                "external_write_proposal_native_review_required": True,
                "external_write_proposal_direct_apply": False,
                "external_write_proposal_auto_retry": False,
                "external_proposal_content_retained": False,
                "external_verified_write_artifact_projection": True,
                "external_verified_write_receipt_retention": "saved_chats_only",
                "verified_file_move_artifact_identity": "matching_saved_artifact_only",
                "external_write_transaction_failure_atomic": True,
                "external_write_transaction_mixed_create_edit": True,
                "external_write_transaction_create_rollback_identity_bound": True,
                "external_lifecycle_proposal_native_review_required": True,
                "external_lifecycle_proposal_direct_apply": False,
                "external_lifecycle_permanent_delete": False,
                "native_review_can_be_approved": False,
                "runtime_tool_advertised": "connection_scoped",
                "runtime_mutation_auto_retry": False,
                "message_submission_auto_retry": False,
                "turn_stop_auto_retry": False,
                "dedicated_turn_stop_requires_authorization": True,
            },
            "notice": AGENT_MCP_CONTEXT_EGRESS_NOTICE,
        }

    args = ["agent-mcp", "--acknowledge-sensitive-context-egress"]
    if with_model_lifecycle:
        args.append("--acknowledge-model-lifecycle")
    return {
        "contract_version": AGENT_MCP_CONTRACT_VERSION,
        "server_name": AGENT_MCP_SERVER_NAME,
        "transport": "stdio",
        "command": "prompt-enhancer",
        "args": args,
        "tool_timeout_seconds": AGENT_MCP_TOOL_TIMEOUT_SECONDS,
        "advertised_tools": [
            "agent_discover",
            "agent_invoke",
            "agent_open",
            "agent_resume",
            "agent_fork",
            "agent_export",
            "agent_close",
            "agent_catalog",
            "agent_history",
            "agent_artifacts",
            "agent_stage_attachment",
            "agent_context",
            "agent_workspace",
            "agent_propose",
            "agent_propose_transaction",
            "agent_propose_lifecycle",
            "agent_turn",
            "agent_stop",
            "agent_wait",
            *(["agent_runtime"] if with_model_lifecycle else []),
        ],
        "safeguards": {
            "starts_prompt_enhancer_or_agent": False,
            "starts_shell_or_terminal": False,
            "starts_subprocess": True,
            "token_in_arguments_or_output": False,
            "loopback_only": True,
            "per_sensitive_call_egress_receipt": True,
            "generic_mutation_requires_authorization": True,
            "delete_available_through_mcp": False,
            "destructive_catalog_delete_requires_agent_ui": True,
            "dedicated_catalog_tool_strict": True,
            "dedicated_resume_restores_authority": False,
            "resume_mutation_auto_retry": False,
            "dedicated_fork_copies_authority": False,
            "fork_ambiguous_retry_same_request_only": True,
            "fork_ambiguous_retry_limit": 1,
            "dedicated_export_exact_revision": True,
            "export_max_events": MAX_AGENT_HISTORY_EVENTS,
            "export_workspace_path_included": False,
            "export_attachment_bytes_included": False,
            "export_live_approval_state_included": False,
            "export_raw_tool_payloads_included": False,
            "dedicated_close_exact_revision": True,
            "close_live_session_only": True,
            "close_retained_catalog_deleted": False,
            "close_mutation_auto_retry": False,
            "dedicated_history_tool_read_only": True,
            "retained_history_excludes_raw_tool_payloads": True,
            "dedicated_artifact_tool_metadata_only": True,
            "artifact_capture_preview_content_free": True,
            "artifact_capture_requires_native_agent_ui": True,
            "artifact_bytes_available_through_mcp": False,
            "dedicated_context_tool_read_only": True,
            "context_snapshot_sequential_non_atomic": True,
            "context_omits_workspace_paths_instructions_process_ids": True,
            "attachment_inline_staging_available": True,
            "attachment_bytes_returned_through_mcp": False,
            "attachment_path_authority_available": False,
            "dedicated_workspace_tool_read_only": True,
            "external_write_proposal_native_review_required": True,
            "external_write_proposal_direct_apply": False,
            "external_write_proposal_auto_retry": False,
            "external_proposal_content_retained": False,
            "external_verified_write_artifact_projection": True,
            "external_verified_write_receipt_retention": "saved_chats_only",
            "verified_file_move_artifact_identity": "matching_saved_artifact_only",
            "external_write_transaction_failure_atomic": True,
            "external_write_transaction_mixed_create_edit": True,
            "external_write_transaction_create_rollback_identity_bound": True,
            "external_lifecycle_proposal_native_review_required": True,
            "external_lifecycle_proposal_direct_apply": False,
            "external_lifecycle_permanent_delete": False,
            "native_review_can_be_approved": False,
            "runtime_tool_advertised": with_model_lifecycle,
            "runtime_mutation_auto_retry": False,
            "message_submission_auto_retry": False,
            "turn_stop_auto_retry": False,
            "dedicated_turn_stop_requires_authorization": True,
        },
        "notice": AGENT_MCP_CONTEXT_EGRESS_NOTICE,
    }


def run_agent_mcp_config(
    settings: AppSettings | None = None,
    *,
    transport: str = "http",
    with_model_lifecycle: bool = False,
) -> int:
    """Print copyable Claude Code and Codex snippets; edit no provider config."""

    document = agent_mcp_config_document(
        settings,
        transport=transport,
        with_model_lifecycle=with_model_lifecycle
    )
    if document["transport"] == "streamable-http":
        endpoint = str(document["url"])
        token_env = str(document["bearer_token_env_var"])
        client_configs = build_agent_mcp_client_configs(endpoint)
        print("# Claude Code CLI (PowerShell or POSIX shell; token-free):")
        print(client_configs.claude_add_command)
        print()
        print("# Codex CLI (token-free):")
        print(client_configs.codex_add_command)
        print()
        print("# Claude Code (.mcp.json, direct HTTP):")
        print(client_configs.claude_json)
        print()
        print("# Codex (~/.codex/config.toml or trusted project .codex/config.toml):")
        print(client_configs.codex_toml)
        notes = (
            "",
            "# Recommended: create a scoped connection in Agent > External controllers,",
            "# then use its one-time private config. This template reads the scoped token",
            f"# from {token_env}; it never prints or creates a credential.",
            "# Direct HTTP starts no bridge process, shell, or visible terminal.",
            "# Protected Agent effects remain pending for native approval.",
        )
        print("\n".join(notes), file=sys.stderr)
        return 0

    command = str(document["command"])
    args = list(document["args"])
    claude = {
        "mcpServers": {
            AGENT_MCP_SERVER_NAME: {
                "command": command,
                "args": args,
                "env": {},
            }
        }
    }
    print("# Claude Code (.mcp.json, advanced stdio fallback):")
    print(json.dumps(claude, indent=2))
    print()
    print("# Claude Code one-liner:")
    print(
        f"claude mcp add {AGENT_MCP_SERVER_NAME} -- "
        + " ".join(shlex.quote(part) for part in [command, *args])
    )
    print()
    print("# Codex (~/.codex/config.toml or trusted project .codex/config.toml):")
    print(f"[mcp_servers.{AGENT_MCP_SERVER_NAME}]")
    print(f"command = {json.dumps(command)}")
    print(f"args = {json.dumps(args)}")
    print(f"tool_timeout_sec = {AGENT_MCP_TOOL_TIMEOUT_SECONDS}")
    print('default_tools_approval_mode = "prompt"')
    notes = (
        "",
        "# Advanced fallback: this configuration starts one headless stdio bridge process.",
        "# Prompt Enhancer must already be running; it never launches Codex, Claude, or a model.",
        "# Protected Agent effects remain pending until the person approves them in the native window.",
        "# Keep MCP tool approval in prompt mode; inspect generic invoke operation and arguments.",
        "# Copy these snippets only after reviewing the context-egress notice above.",
    )
    print("\n".join(notes), file=sys.stderr)
    return 0


__all__ = (
    "AGENT_MCP_CONTEXT_EGRESS_NOTICE",
    "AGENT_MCP_INSTRUCTIONS",
    "AGENT_MCP_SERVER_NAME",
    "AGENT_MCP_TOOL_TIMEOUT_SECONDS",
    "agent_mcp_config_document",
    "create_agent_mcp_surface",
    "run_agent_mcp",
    "run_agent_mcp_config",
)
