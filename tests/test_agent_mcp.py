"""Standard Agent MCP bridge: bounded orchestration without process ownership."""

from __future__ import annotations

import io
import base64
import hashlib
import json
from typing import Any

import pytest

from prompt_enhancer.application.agent_controller_client import (
    AgentControllerError,
    AgentControllerInvocationResult,
)
from prompt_enhancer.application.agent_attachment_contracts import (
    AGENT_DOCUMENT_MEDIA_TYPES,
    AgentAttachment,
)
from prompt_enhancer.application.agent_mcp_surface import (
    AGENT_MCP_CONTRACT_VERSION,
    AgentMcpSurface,
    AgentMcpSurfaceError,
)
from prompt_enhancer.application.agent_orchestration import agent_orchestration_manifest
from prompt_enhancer.application.agent_surface import AgentSurfaceError, ToolSpec
from prompt_enhancer.cli import main
from prompt_enhancer.interfaces import agent_mcp
from prompt_enhancer.interfaces.mcp import McpStdioServer, handle_message


SESSION_ID = "a" * 32
PROJECT_ID = "b" * 32
OTHER_PROJECT_ID = "c" * 32
OTHER_SESSION_ID = "f" * 32
ARTIFACT_ID = "d" * 32
VERSION_ID = "e" * 32
SYNTHETIC_TIME = "2026-01-02T03:04:05Z"
SYNTHETIC_EXPIRY = "2026-01-02T04:04:05Z"


def _project_record(
    *,
    project_id: str = PROJECT_ID,
    name: str = "Synthetic project",
    revision: int = 1,
    pinned: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    return {
        "contract_version": "agent-catalog.v2",
        "project_id": project_id,
        "name": name,
        "created_at": SYNTHETIC_TIME,
        "updated_at": SYNTHETIC_TIME,
        "revision": revision,
        "pinned": pinned,
        "archived_at": SYNTHETIC_TIME if archived else None,
        "session_count": 1,
        "is_default": False,
    }


def _chat_record(
    *,
    session_id: str = SESSION_ID,
    project_id: str = PROJECT_ID,
    title: str = "Synthetic chat",
    model_alias: str | None = "example-model",
    revision: int = 1,
    pinned: bool = False,
    archived: bool = False,
) -> dict[str, Any]:
    return {
        "contract_version": "agent-catalog.v2",
        "session_id": session_id,
        "project_id": project_id,
        "title": title,
        "workspace": "/example/workspace",
        "model_alias": model_alias,
        "created_at": SYNTHETIC_TIME,
        "updated_at": SYNTHETIC_TIME,
        "last_opened_at": SYNTHETIC_TIME,
        "revision": revision,
        "pinned": pinned,
        "archived_at": SYNTHETIC_TIME if archived else None,
        "history_state": "durable_local",
        "retention_policy": "local_history",
        "history_revision": 0,
        "last_event_seq": 0,
        "turn_count": 0,
        "conversation_available": True,
        "lineage": None,
    }


def _retained_events(*, session_id: str = SESSION_ID) -> dict[str, Any]:
    return {
        "contract_version": "local-agent.v9",
        "session_id": session_id,
        "events": [
            {
                "seq": 1,
                "at": SYNTHETIC_TIME,
                "kind": "status",
                "text": "Synthetic retained status.",
            }
        ],
        "running": False,
        "closing": False,
        "stopping": False,
        "cleanup_unconfirmed": False,
        "pending_approval_id": None,
        "last_seq": 1,
        "first_seq": 1,
    }


def _artifact_version() -> dict[str, Any]:
    return {
        "contract_version": "agent-artifact.v3",
        "version_id": VERSION_ID,
        "artifact_id": ARTIFACT_ID,
        "version_number": 1,
        "created_at": SYNTHETIC_TIME,
        "path": "notes.md",
        "media_type": "text/markdown",
        "preview_kind": "text",
        "provenance": "generated_unverified",
        "sha256": "1" * 64,
        "byte_size": 10,
        "source_turn_id": None,
        "source_event_seq": None,
    }


def _artifact_record(
    *,
    project_id: str = PROJECT_ID,
    session_id: str = SESSION_ID,
    detail: bool = False,
) -> dict[str, Any]:
    version = _artifact_version()
    result = {
        "contract_version": "agent-artifact.v3",
        "artifact_id": ARTIFACT_ID,
        "project_id": project_id,
        "session_id": session_id,
        "title": "Synthetic notes",
        "kind": "markdown",
        "path": "notes.md",
        "created_at": SYNTHETIC_TIME,
        "updated_at": SYNTHETIC_TIME,
        "revision": 1,
        "version_count": 1,
        "availability": "available",
        "lifecycle_state": "active",
        "archived_at": None,
        "removed_at": None,
        "latest_version": version,
    }
    if detail:
        result["versions"] = [version]
    return result


def _artifact_export_record(
    *,
    project_id: str = PROJECT_ID,
    session_id: str = SESSION_ID,
) -> dict[str, Any]:
    return {
        "contract_version": "agent-artifact-export.v1",
        "exported_at": SYNTHETIC_TIME,
        "artifact": _artifact_record(
            project_id=project_id,
            session_id=session_id,
            detail=True,
        ),
        "selected_version": _artifact_version(),
        "evidence": {
            "verification": "exact_current_workspace_readback",
            "algorithm": "sha256",
            "sha256": "1" * 64,
            "byte_size": 10,
            "verified": True,
        },
        "content_included": False,
        "absolute_path_included": False,
        "sensitivity": "sensitive_local_metadata",
    }


def _artifact_capture_preview(
    *,
    project_id: str = PROJECT_ID,
    session_id: str = SESSION_ID,
    path: str = "reports/synthetic.pdf",
    title: str = "Synthetic report",
) -> dict[str, Any]:
    return {
        "contract_version": "agent-artifact-capture-preview.v1",
        "project_id": project_id,
        "session_id": session_id,
        "path": path,
        "title": title,
        "kind": "pdf",
        "media_type": "application/pdf",
        "preview_kind": "pdf",
        "sha256": "2" * 64,
        "byte_size": 256,
        "requires_native_confirmation": True,
        "file_content_included": False,
    }


def _runtime_status() -> dict[str, Any]:
    selection = {
        "alias": "example-model",
        "device": "split",
        "gpu_layers": 4,
        "context_size": 8192,
    }
    return {
        "contract_version": "local-runtime-coordinator.v2",
        "revision": 7,
        "state": "ready",
        "requested": selection,
        "served": {
            **selection,
            "started_at": SYNTHETIC_TIME,
            "pid": 4321,
        },
        "cleanup": {
            "state": "not_required",
            "process_exit_confirmed": True,
            "gpu_memory_free_before_mb": None,
            "gpu_memory_free_after_mb": None,
            "gpu_memory_released_mb": None,
        },
        "capabilities": {
            "state": "verified",
            "probe_version": "local-runtime-multimodal-probe.v2",
            "text": True,
            "tools": True,
            "vision": True,
            "audio": True,
            "recording": True,
            "structured_output": True,
            "error_code": None,
        },
        "context": {
            "state": "known",
            "used_tokens": 1024,
            "limit_tokens": 8192,
            "requested_output_tokens": 1400,
            "available_output_tokens": 7168,
            "source": "runtime_chat_input_tokens",
            "scope": "last_request",
            "policy": "exact_admitted",
            "compacted_messages": 0,
            "reason_code": None,
        },
        "active_requests": 0,
        "last_error_code": None,
    }


def _compatibility_catalog() -> dict[str, Any]:
    return {
        "contract_version": "local-model-compatibility.v1",
        "adapter": {
            "adapter_id": "llama.cpp-openai-gguf",
            "adapter_version": "llama.cpp-openai-gguf.v1",
            "runtime_version": "synthetic-runtime-v1",
            "runtime_identity_state": "unknown",
            "runtime_binary_sha256": None,
            "capability_probe_version": "local-runtime-multimodal-probe.v2",
        },
        "models": [
            {
                "alias": "example-model",
                "state": "supported",
                "reason_code": "live_text_probe_verified",
                "format": "gguf",
                "architecture": "example-architecture",
                "tokenizer_model": "example-tokenizer",
                "training_context_size": 8192,
                "metadata_reader_version": "gguf-metadata-v1",
                "artifact_identity_state": "unverified",
                "artifact_sha256": None,
                "source_revision": None,
                "source_license": None,
                "source_license_policy": None,
                "execution_state": "verified",
                "context_counter_state": "verified",
            }
        ],
    }


def _live_session(*, project_id: str = PROJECT_ID) -> dict[str, Any]:
    return {
        "contract_version": "local-agent.v9",
        "session_id": SESSION_ID,
        "settings": {
            "workspace": "/example/workspace",
            "project_id": project_id,
            "model_alias": "example-model",
            "parameters": {
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 1400,
                "enable_thinking": True,
            },
            "instructions": "Synthetic instruction that must not cross MCP context output.",
            "allow_writes": True,
            "allow_commands": False,
            "allow_web": False,
            "max_steps": 10,
            "command_timeout_seconds": 30,
            "title": "Synthetic live chat",
            "retention_policy": "local_history",
        },
        "created_at": SYNTHETIC_TIME,
        "running": False,
        "closing": False,
        "stopping": False,
        "cleanup_unconfirmed": False,
        "last_seq": 2,
        "pending_approval_id": None,
        "model_alias": "example-model",
        "turns": 1,
        "history_revision": 2,
        "recovered": False,
        "authority_revalidated": True,
        "history_write_failed": False,
        "recovery_state": "current",
    }


def _session_context(*, session_id: str = SESSION_ID) -> dict[str, Any]:
    return {
        "contract_version": "agent-session-context.v1",
        "session_id": session_id,
        "revision": 2,
        "binding_state": "bound",
        "source": "runtime_chat_template_preflight",
        "unknown_reason": None,
        "turn_id": "7" * 32,
        "turn_number": 1,
        "model_alias": "example-model",
        "observed_at": SYNTHETIC_TIME,
        "context": _runtime_status()["context"],
    }


def _attachment_list(*, session_id: str = SESSION_ID) -> dict[str, Any]:
    return {
        "contract_version": "agent-attachment.v2",
        "session_id": session_id,
        "attachments": [
            {
                "contract_version": "agent-attachment.v2",
                "attachment_id": "9" * 32,
                "kind": "image",
                "media_type": "image/png",
                "display_name": "synthetic-image.png",
                "sha256": "8" * 64,
                "byte_size": 128,
                "width": 8,
                "height": 8,
                "duration_ms": None,
                "sample_rate_hz": None,
                "channels": None,
                "routing": "native_multimodal",
                "document_format": None,
                "projected_characters": None,
                "projection_truncated": None,
                "omitted_features": [],
                "context_tokens": None,
                "context_cost_source": "runtime_unreported",
                "session_id": session_id,
                "model_alias": "example-model",
                "capability_probe_version": "local-runtime-multimodal-probe.v2",
                "source": "file",
                "state": "staged",
                "retention": "local_history",
                "created_at": SYNTHETIC_TIME,
                "expires_at": SYNTHETIC_EXPIRY,
                "attached_event_seq": None,
            },
            {
                "contract_version": "agent-attachment.v2",
                "attachment_id": "6" * 32,
                "kind": "document",
                "media_type": "text/markdown",
                "display_name": "synthetic-notes.md",
                "sha256": "5" * 64,
                "byte_size": 96,
                "width": None,
                "height": None,
                "duration_ms": None,
                "sample_rate_hz": None,
                "channels": None,
                "routing": "local_text_projection",
                "document_format": "markdown",
                "projected_characters": 72,
                "projection_truncated": False,
                "omitted_features": [],
                "context_tokens": None,
                "context_cost_source": "runtime_unreported",
                "session_id": session_id,
                "model_alias": "example-model",
                "capability_probe_version": "local-runtime-multimodal-probe.v2",
                "source": "file",
                "state": "staged",
                "retention": "local_history",
                "created_at": SYNTHETIC_TIME,
                "expires_at": SYNTHETIC_EXPIRY,
                "attached_event_seq": None,
            }
        ],
    }


class _Result:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.payload


class _FakeController:
    def __init__(self) -> None:
        self.turn_options: dict[str, Any] | None = None
        self.resume_requests: list[Any] = []
        self.fork_requests: list[Any] = []
        self.export_requests: list[Any] = []
        self.close_requests: list[Any] = []
        self.stop_options: dict[str, Any] | None = None
        self.wait_options: dict[str, Any] | None = None
        self.runtime_calls = 0
        self.invocations: list[Any] = []
        self.attachment_staging: list[Any] = []
        self.write_proposals: list[Any] = []
        self.write_transaction_proposals: list[Any] = []
        self.lifecycle_proposals: list[Any] = []

    def discover(self, *, refresh: bool = False):
        assert isinstance(refresh, bool)
        return agent_orchestration_manifest()

    def invoke(self, request):
        self.invocations.append(request)
        session_id = request.path_parameters.get("session_id", SESSION_ID)
        status_code = 200
        if request.operation == "list_projects":
            response = {
                "contract_version": "agent-catalog.v2",
                "projects": [_project_record()],
            }
        elif request.operation == "get_project":
            response = _project_record(
                project_id=request.path_parameters["project_id"]
            )
        elif request.operation == "create_project":
            status_code = 201
            response = _project_record(name=request.body["name"])
        elif request.operation == "update_project":
            response = _project_record(
                project_id=request.path_parameters["project_id"],
                name=request.body.get("name") or "Synthetic project",
                revision=request.body["expected_revision"] + 1,
                pinned=request.body.get("pinned") or False,
                archived=request.body.get("archived") or False,
            )
        elif request.operation in {"list_project_sessions", "list_catalog_sessions"}:
            project_id = request.path_parameters.get("project_id", PROJECT_ID)
            response = {
                "contract_version": "agent-catalog.v2",
                "sessions": [_chat_record(project_id=project_id)],
            }
        elif request.operation == "get_catalog_session":
            response = _chat_record(
                session_id=request.path_parameters["session_id"]
            )
        elif request.operation == "update_catalog_session":
            response = _chat_record(
                session_id=request.path_parameters["session_id"],
                project_id=request.body.get("project_id") or PROJECT_ID,
                title=request.body.get("title") or "Synthetic chat",
                model_alias=request.body.get("model_alias") or "example-model",
                revision=request.body["expected_revision"] + 1,
                pinned=request.body.get("pinned") or False,
                archived=request.body.get("archived") or False,
            )
        elif request.operation == "read_retained_history":
            response = _retained_events(session_id=session_id)
        elif request.operation == "list_artifacts":
            project_id = request.path_parameters["project_id"]
            response = {
                "contract_version": "agent-artifact.v3",
                "project_id": project_id,
                "session_id": session_id,
                "view": "active",
                "counts": {
                    "active": 1,
                    "archived": 0,
                    "removed": 0,
                    "total": 1,
                },
                "artifacts": [
                    _artifact_record(
                        project_id=project_id,
                        session_id=session_id,
                    )
                ],
            }
        elif request.operation == "get_artifact":
            response = _artifact_record(
                project_id=request.path_parameters["project_id"],
                session_id=session_id,
                detail=True,
            )
        elif request.operation == "preview_artifact_capture":
            response = _artifact_capture_preview(
                project_id=request.path_parameters["project_id"],
                session_id=session_id,
                path=request.body["path"],
                title=request.body.get("title") or request.body["path"].rsplit("/", 1)[-1],
            )
        elif request.operation == "export_artifact_lineage":
            response = _artifact_export_record(
                project_id=request.path_parameters["project_id"],
                session_id=session_id,
            )
        elif request.operation == "get_local_runtime":
            response = _runtime_status()
        elif request.operation == "get_local_model_compatibility":
            response = _compatibility_catalog()
        elif request.operation == "get_live_session":
            response = _live_session()
        elif request.operation == "get_session_context":
            response = _session_context(session_id=session_id)
        elif request.operation == "list_attachments":
            response = _attachment_list(session_id=session_id)
        elif request.operation == "inspect_workspace":
            response = {
                "contract_version": "local-agent-workspace-discovery.v1",
                "session_id": session_id,
                "scope": "selected_workspace",
                "inventory_coverage": "complete",
                "inventory_reasons": [],
                "scanned_entry_count": 0,
                "observed_file_count": 0,
                "files": [],
                "git_state": "not_repository",
                "git_coverage": "not_applicable",
                "git_reasons": [],
                "git_change_count": 0,
                "git_changes": [],
            }
        elif request.operation == "list_workspace_tree":
            response = {
                "contract_version": "local-agent-workspace.v1",
                "session_id": session_id,
                "path": request.query["path"],
                "entries": [],
                "complete": True,
            }
        elif request.operation == "read_workspace_file":
            response = {
                "contract_version": "local-agent-workspace.v1",
                "session_id": session_id,
                "path": request.query["path"],
                "content": "synthetic\n",
                "revision": "1" * 64,
                "byte_size": 10,
                "line_ending": "lf",
                "editable": True,
            }
        elif request.operation == "search_workspace_text":
            response = {
                "contract_version": "local-agent-workspace-search.v1",
                "session_id": session_id,
                "scope": "application_readable_utf8_text",
                "coverage": "complete",
                "reasons": [],
                "reason_code": None,
                "scanned_entry_count": 3,
                "inspected_byte_count": 10,
                "skipped_entry_count": 0,
                "match_count": 1,
                "matches": [
                    {
                        "path": "src/app.py",
                        "line_number": 1,
                        "preview": "synthetic",
                    }
                ],
            }
        elif request.operation == "review_changes":
            response = {
                "contract_version": "agent-change-set.v1",
                "session_id": session_id,
                "scope": "reviewed_paths_only",
                "coverage": "complete",
                "settled": True,
                "reviewed_writes": 0,
                "verified_writes": 0,
                "unverified_writes": 0,
                "agent_writes": 0,
                "manual_writes": 0,
                "reviewed_noops": 0,
                "command_attempts": 0,
                "omitted_write_receipts": 0,
                "tracking_failed": False,
                "files": [],
            }
        elif request.operation == "read_change_diff":
            path = request.query["path"]
            response = {
                "contract_version": "agent-change-set.v1",
                "session_id": session_id,
                "summary": {
                    "path": path,
                    "net_effect": "modified",
                    "verification": "verified",
                    "reason": None,
                    "reviewed_writes": 1,
                    "agent_writes": 1,
                    "manual_writes": 0,
                    "current_byte_size": 10,
                    "diff_available": True,
                },
                "diff_state": "available",
                "diff": f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new",
                "added_lines": 1,
                "removed_lines": 1,
            }
        else:
            response = {"selected": True}
        return AgentControllerInvocationResult(
            operation=request.operation,
            status_code=status_code,
            response=response,
        )

    def stage_attachment(self, request):
        self.attachment_staging.append(request)
        declared = request.attachment
        image = declared.media_type.startswith("image/")
        audio = declared.media_type == "audio/wav"
        document_format = next(
            (
                format_name
                for format_name, media_type in AGENT_DOCUMENT_MEDIA_TYPES.items()
                if media_type == declared.media_type
            ),
            None,
        )
        return AgentAttachment(
            attachment_id="7" * 32,
            session_id=request.session_id,
            model_alias="example-model",
            capability_probe_version="local-runtime-multimodal-probe.v2",
            kind="image" if image else "audio" if audio else "document",
            media_type=declared.media_type,
            display_name=declared.display_name,
            source="external_agent",
            state="staged",
            retention="local_history",
            created_at=SYNTHETIC_TIME,
            expires_at=SYNTHETIC_EXPIRY,
            sha256=declared.sha256,
            byte_size=declared.byte_size,
            width=1 if image else None,
            height=1 if image else None,
            duration_ms=100 if audio else None,
            sample_rate_hz=16_000 if audio else None,
            channels=1 if audio else None,
            routing="local_text_projection" if document_format else "native_multimodal",
            document_format=document_format,
            projected_characters=declared.byte_size if document_format else None,
            projection_truncated=False if document_format else None,
            omitted_features=(),
        )

    def propose_write(self, request):
        self.write_proposals.append(request)
        return _Result(
            {
                "contract_version": "agent-write-proposal.v1",
                "request_id": request.proposal.request_id,
                "session_id": request.session_id,
                "operation": request.proposal.operation,
                "path": request.proposal.path,
                "proposed_revision": "e" * 64,
                "state": "pending_native_review",
                "approval_id": "d" * 32,
                "cursor": 3,
                "write_receipt": None,
            }
        )

    def propose_write_transaction(self, request):
        self.write_transaction_proposals.append(request)
        files = sorted(
            (
                {
                    "operation": change.operation,
                    "path": change.path,
                    "proposed_revision": hashlib.sha256(
                        (
                            change.content.replace("\n", "\r\n")
                            if change.line_ending.value == "crlf"
                            else change.content
                        ).encode("utf-8")
                    ).hexdigest(),
                }
                for change in request.proposal.changes
            ),
            key=lambda item: item["path"].encode("utf-8"),
        )
        return _Result(
            {
                "contract_version": "agent-write-transaction-proposal.v2",
                "request_id": request.proposal.request_id,
                "session_id": request.session_id,
                "state": "pending_native_review",
                "file_count": len(files),
                "files": files,
                "approval_id": "f" * 32,
                "cursor": 4,
                "transaction_result": None,
            }
        )

    def propose_lifecycle(self, request):
        self.lifecycle_proposals.append(request)
        proposal = request.proposal
        recoverable = proposal.operation == "trash_file"
        return _Result(
            {
                "contract_version": "agent-lifecycle-proposal.v1",
                "request_id": proposal.request_id,
                "session_id": request.session_id,
                "operation": proposal.operation,
                "path": proposal.path,
                "source_path": proposal.source_path,
                "target_path": proposal.target_path,
                "expected_revision": proposal.expected_revision,
                "state": "pending_native_review",
                "approval_id": "a" * 32,
                "cursor": 5,
                "verified": False,
                "permanent": False if recoverable else None,
                "recovery": "windows_recycle_bin" if recoverable else None,
            }
        )

    def open_chat(self, request):
        return _Result(
            {
                "outcome": "ready",
                "project_name": request.project_name,
                "workspace": request.settings.workspace,
                "session_id": SESSION_ID,
            }
        )

    def run_turn(self, request, **options):
        self.turn_options = options
        return _Result(
            {
                "outcome": "settled",
                "session_id": request.session_id,
                "message": request.message.text,
                "cursor": 4,
            }
        )

    def resume_chat(self, request):
        self.resume_requests.append(request)
        return _Result(
            {
                "outcome": "resumed",
                "project_id": request.project_id,
                "session_id": request.session_id,
                "mutation_state": "accepted",
            }
        )

    def fork_chat(self, request):
        self.fork_requests.append(request)
        return _Result(
            {
                "outcome": "forked",
                "source_project_id": request.project_id,
                "source_session_id": request.session_id,
                "request_id": request.request_id,
                "mutation_state": "accepted",
                "attempts": 1,
            }
        )

    def export_chat(self, request):
        self.export_requests.append(request)
        return _Result(
            {
                "project_id": request.project_id,
                "session_id": request.session_id,
                "catalog_revision": request.expected_catalog_revision,
                "history_revision": request.expected_history_revision,
                "event_count": request.expected_history_revision,
                "complete": True,
                "workspace_path_included": False,
                "attachment_bytes_included": False,
                "live_approval_state_included": False,
                "raw_tool_payloads_included": False,
                "mutation_authority_included": False,
            }
        )

    def close_chat(self, request):
        self.close_requests.append(request)
        return _Result(
            {
                "outcome": "closed",
                "project_id": request.project_id,
                "session_id": request.session_id,
                "catalog_revision_checked": request.expected_catalog_revision,
                "history_revision_checked": request.expected_history_revision,
                "mutation_state": "accepted",
                "live_session_present": False,
                "catalog_session_retained": True,
                "permanent_delete_requested": False,
                "retained_history_delete_requested": False,
                "protected_authority_granted": False,
            }
        )

    def wait_turn(self, request, **options):
        self.wait_options = options
        return _Result(
            {
                "outcome": "settled",
                "session_id": request.session_id,
                "cursor": request.after,
            }
        )

    def stop_turn(self, request, **options):
        self.stop_options = options
        return _Result(
            {
                "outcome": "stopped",
                "session_id": request.session_id,
                "stop_request_state": "accepted",
                "cursor": request.after,
            }
        )

    def coordinate_runtime(self, request):
        self.runtime_calls += 1
        return _Result(
            {
                "outcome": request.desired_state,
                "alias": request.alias,
            }
        )


class _ProjectScopedController(_FakeController):
    """Synthetic two-project catalog used only for isolation assertions."""

    def invoke(self, request):
        self.invocations.append(request)
        if request.operation == "get_project":
            project_id = request.path_parameters["project_id"]
            return AgentControllerInvocationResult(
                operation=request.operation,
                status_code=200,
                response=_project_record(
                    project_id=project_id,
                    name=(
                        "Synthetic project A"
                        if project_id == PROJECT_ID
                        else "Synthetic project B"
                    ),
                ),
            )
        if request.operation == "get_catalog_session":
            session_id = request.path_parameters["session_id"]
            project_id = (
                PROJECT_ID if session_id == SESSION_ID else OTHER_PROJECT_ID
            )
            return AgentControllerInvocationResult(
                operation=request.operation,
                status_code=200,
                response=_chat_record(
                    session_id=session_id,
                    project_id=project_id,
                    title=(
                        "Synthetic chat A"
                        if session_id == SESSION_ID
                        else "Synthetic chat B"
                    ),
                ),
            )
        if request.operation == "list_project_sessions":
            project_id = request.path_parameters["project_id"]
            session_id = (
                SESSION_ID if project_id == PROJECT_ID else OTHER_SESSION_ID
            )
            return AgentControllerInvocationResult(
                operation=request.operation,
                status_code=200,
                response={
                    "contract_version": "agent-catalog.v2",
                    "sessions": [
                        _chat_record(
                            session_id=session_id,
                            project_id=project_id,
                        )
                    ],
                },
            )
        self.invocations.pop()
        return super().invoke(request)


def _egress() -> dict[str, Any]:
    return {
        "task_authorized": True,
        "redaction_previewed": True,
        "destination": "model_context",
    }


def _stage_attachment_arguments() -> dict[str, Any]:
    payload = b"synthetic-mcp-media"
    return {
        "egress": _egress(),
        "mutation_authorized": True,
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
        "attachment": {
            "display_name": "mcp-synthetic.png",
            "media_type": "image/png",
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "data_base64": base64.b64encode(payload).decode("ascii"),
        },
    }


def _stage_document_attachment_arguments() -> dict[str, Any]:
    payload = b"# Synthetic MCP document\n\nBounded local projection."
    return {
        "egress": _egress(),
        "mutation_authorized": True,
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
        "attachment": {
            "display_name": "mcp-synthetic.md",
            "media_type": "text/markdown",
            "byte_size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "data_base64": base64.b64encode(payload).decode("ascii"),
        },
    }


def test_default_surface_lists_finite_tools_and_hides_model_lifecycle() -> None:
    surface = AgentMcpSurface(_FakeController())

    assert [tool.name for tool in surface.tools()] == [
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
    ]
    for tool in surface.tools():
        schema = tool.input_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
    try:
        surface.call("agent_runtime", {})
    except AgentMcpSurfaceError as error:
        assert error.code == "unknown_tool"
    else:
        raise AssertionError("runtime tool was callable without server opt-in")


def test_project_scoped_surfaces_are_disjoint_and_content_free_on_cross_scope() -> None:
    client = _ProjectScopedController()
    surface_a = AgentMcpSurface(client, scope_project_id=PROJECT_ID)
    surface_b = AgentMcpSurface(client, scope_project_id=OTHER_PROJECT_ID)

    for surface in (surface_a, surface_b):
        tool_names = {tool.name for tool in surface.tools()}
        assert len(tool_names) == 18
        assert "agent_invoke" not in tool_names
        with pytest.raises(AgentMcpSurfaceError) as generic:
            surface.call(
                "agent_invoke",
                {"egress": _egress(), "request": {"operation": "list_projects"}},
            )
        assert generic.value.code == "unknown_tool"

    projects_a = surface_a.call(
        "agent_catalog",
        {"egress": _egress(), "request": {"action": "list_projects"}},
    )["result"]["response"]["projects"]
    projects_b = surface_b.call(
        "agent_catalog",
        {"egress": _egress(), "request": {"action": "list_projects"}},
    )["result"]["response"]["projects"]
    assert [project["project_id"] for project in projects_a] == [PROJECT_ID]
    assert [project["project_id"] for project in projects_b] == [OTHER_PROJECT_ID]

    chats_a = surface_a.call(
        "agent_catalog",
        {"egress": _egress(), "request": {"action": "list_chats"}},
    )["result"]["response"]["sessions"]
    chats_b = surface_b.call(
        "agent_catalog",
        {"egress": _egress(), "request": {"action": "list_chats"}},
    )["result"]["response"]["sessions"]
    assert [(chat["project_id"], chat["session_id"]) for chat in chats_a] == [
        (PROJECT_ID, SESSION_ID)
    ]
    assert [(chat["project_id"], chat["session_id"]) for chat in chats_b] == [
        (OTHER_PROJECT_ID, OTHER_SESSION_ID)
    ]

    cross_scope_calls = (
        (
            "agent_open",
            {
                "egress": _egress(),
                "request": {
                    "project_id": OTHER_PROJECT_ID,
                    "settings": {"workspace": "/example/workspace"},
                },
            },
        ),
        (
            "agent_catalog",
            {
                "egress": _egress(),
                "request": {
                    "action": "get_project",
                    "project_id": OTHER_PROJECT_ID,
                },
            },
        ),
        (
            "agent_catalog",
            {
                "egress": _egress(),
                "request": {
                    "action": "list_chats",
                    "project_id": OTHER_PROJECT_ID,
                },
            },
        ),
        (
            "agent_history",
            {
                "egress": _egress(),
                "project_id": OTHER_PROJECT_ID,
                "session_id": OTHER_SESSION_ID,
            },
        ),
        (
            "agent_workspace",
            {
                "egress": _egress(),
                "session_id": OTHER_SESSION_ID,
                "action": "inspect",
            },
        ),
        (
            "agent_turn",
            {
                "egress": _egress(),
                "request": {
                    "session_id": OTHER_SESSION_ID,
                    "message": {"text": "Synthetic cross-scope request."},
                },
            },
        ),
    )
    for tool_name, arguments in cross_scope_calls:
        with pytest.raises(AgentMcpSurfaceError) as rejected:
            surface_a.call(tool_name, arguments)
        assert rejected.value.code == "agent_mcp_scope_violation"
        assert rejected.value.details == {}
        assert "Synthetic project B" not in str(rejected.value)
        assert "/example/workspace" not in str(rejected.value)

    invoked_operations = [request.operation for request in client.invocations]
    assert "inspect_workspace" not in invoked_operations
    assert client.turn_options is None


def test_every_sensitive_tool_requires_exact_per_call_egress_receipt() -> None:
    surface = AgentMcpSurface(_FakeController(), allow_model_lifecycle=True)
    calls = {
        "agent_invoke": {"request": {"operation": "list_projects"}},
        "agent_open": {
            "request": {
                "project_name": "Synthetic MCP project",
                "settings": {"workspace": "/example/workspace"},
            }
        },
        "agent_resume": {
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 1,
                "expected_history_revision": 0,
            },
        },
        "agent_fork": {
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "request_id": "8" * 32,
                "expected_catalog_revision": 1,
                "expected_history_revision": 0,
            },
        },
        "agent_export": {
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 1,
                "expected_history_revision": 0,
                "max_events": 100,
            },
        },
        "agent_close": {
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 1,
                "expected_history_revision": 0,
            },
        },
        "agent_catalog": {"request": {"action": "list_projects"}},
        "agent_history": {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
        },
        "agent_artifacts": {
            "request": {
                "action": "list",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
            }
        },
        "agent_stage_attachment": {
            **_stage_attachment_arguments(),
            "egress": _egress(),
        },
        "agent_context": {"request": {"action": "runtime"}},
        "agent_workspace": {
            "session_id": SESSION_ID,
            "action": "inspect",
        },
        "agent_propose": {
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "6" * 32,
                    "operation": "create",
                    "path": "synthetic.txt",
                    "content": "Synthetic proposal.\n",
                },
            },
        },
        "agent_propose_transaction": {
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "7" * 32,
                    "changes": [
                        {
                            "operation": "edit",
                            "path": "alpha.txt",
                            "content": "alpha after\n",
                            "expected_revision": "1" * 64,
                            "line_ending": "lf",
                        },
                        {
                            "operation": "create",
                            "path": "new.txt",
                            "content": "new file\n",
                            "line_ending": "lf",
                        },
                    ],
                },
            },
        },
        "agent_propose_lifecycle": {
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "8" * 32,
                    "operation": "move_file",
                    "source_path": "alpha.txt",
                    "target_path": "archive/alpha.txt",
                    "expected_revision": "1" * 64,
                },
            },
        },
        "agent_turn": {
            "request": {
                "session_id": SESSION_ID,
                "message": {"text": "Synthetic request"},
            }
        },
        "agent_stop": {
            "mutation_authorized": True,
            "request": {"session_id": SESSION_ID, "after": 0},
        },
        "agent_wait": {"request": {"session_id": SESSION_ID, "after": 0}},
        "agent_runtime": {
            "model_lifecycle_authorized": True,
            "request": {"desired_state": "stopped", "alias": "example-model"},
        },
    }
    for name, arguments in calls.items():
        arguments["egress"] = {
            "task_authorized": True,
            "redaction_previewed": False,
            "destination": "model_context",
        }
        try:
            surface.call(name, arguments)
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments", name
        else:
            raise AssertionError(f"{name} accepted an incomplete egress receipt")

    try:
        surface.call(
            "agent_catalog",
            {
                "egress": {
                    "task_authorized": 1,
                    "redaction_previewed": True,
                    "destination": "model_context",
                },
                "request": {"action": "list_projects"},
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "invalid_arguments"
    else:
        raise AssertionError("numeric truth bypassed the exact egress receipt")


def test_stage_attachment_tool_is_path_free_integrity_bound_and_metadata_only() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    arguments = _stage_attachment_arguments()

    payload = surface.call("agent_stage_attachment", arguments)

    assert payload["contract_version"] == AGENT_MCP_CONTRACT_VERSION
    result = payload["result"]
    assert result["operation"] == "stage_attachment_inline"
    assert result["status_code"] == 201
    assert result["project_id"] == PROJECT_ID
    assert result["session_id"] == SESSION_ID
    assert result["attachment_bytes_returned"] is False
    assert result["attachment"]["source"] == "external_agent"
    assert result["attachment"]["attachment_id"] == "7" * 32
    serialized = json.dumps(payload)
    assert arguments["attachment"]["data_base64"] not in serialized
    assert arguments["attachment"]["sha256"] not in serialized
    assert "data_base64" not in result["attachment"]
    assert len(client.attachment_staging) == 1

    for bad in (
        {**arguments, "mutation_authorized": False},
        {
            **arguments,
            "attachment": {**arguments["attachment"], "path": "private.png"},
        },
        {
            **arguments,
            "attachment": {**arguments["attachment"], "sha256": "0" * 64},
        },
    ):
        try:
            surface.call("agent_stage_attachment", bad)
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("unsafe attachment staging arguments were accepted")
    assert len(client.attachment_staging) == 1

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "stage_attachment_inline",
                    "path_parameters": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                    },
                    "body": arguments["attachment"],
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "attachment_staging_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the staging tool")


def test_stage_attachment_tool_admits_document_metadata_without_returning_text() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    arguments = _stage_document_attachment_arguments()

    payload = surface.call("agent_stage_attachment", arguments)

    attachment = payload["result"]["attachment"]
    assert attachment == {
        "attachment_id": "7" * 32,
        "model_alias": "example-model",
        "kind": "document",
        "media_type": "text/markdown",
        "display_name": "mcp-synthetic.md",
        "byte_size": arguments["attachment"]["byte_size"],
        "width": None,
        "height": None,
        "duration_ms": None,
        "sample_rate_hz": None,
        "channels": None,
        "routing": "local_text_projection",
        "document_format": "markdown",
        "projected_characters": arguments["attachment"]["byte_size"],
        "projection_truncated": False,
        "omitted_features": [],
        "source": "external_agent",
        "expires_at": "2026-01-02T04:04:05Z",
    }
    serialized = json.dumps(payload)
    assert "Bounded local projection" not in serialized
    assert arguments["attachment"]["data_base64"] not in serialized
    assert arguments["attachment"]["sha256"] not in serialized


def test_discover_open_resume_fork_export_close_propose_turn_stop_and_wait_are_typed_and_bounded() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    discovered = surface.call("agent_discover", {"refresh": True})
    assert discovered["contract_version"] == AGENT_MCP_CONTRACT_VERSION
    assert discovered["result"]["contract_version"] == "local-agent-orchestration.v22"

    invoked = surface.call(
        "agent_invoke",
        {
            "egress": _egress(),
            "request": {"operation": "list_projects"},
        },
    )
    assert invoked["result"] == {
        "operation": "list_projects",
        "status_code": 200,
        "response": {
            "contract_version": "agent-catalog.v2",
            "projects": [_project_record()],
        },
    }

    opened = surface.call(
        "agent_open",
        {
            "egress": _egress(),
            "request": {
                "project_name": "Synthetic MCP project",
                "settings": {"workspace": "/example/workspace"},
            },
        },
    )
    assert opened["result"]["session_id"] == SESSION_ID

    resumed = surface.call(
        "agent_resume",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 2,
                "expected_history_revision": 4,
            },
        },
    )
    assert resumed["result"]["outcome"] == "resumed"
    assert len(client.resume_requests) == 1
    assert client.resume_requests[0].expected_catalog_revision == 2
    assert client.resume_requests[0].expected_history_revision == 4

    forked = surface.call(
        "agent_fork",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "request_id": "8" * 32,
                "expected_catalog_revision": 2,
                "expected_history_revision": 4,
                "through_event_seq": 3,
                "title": "  Synthetic   branch  ",
            },
        },
    )
    assert forked["result"]["outcome"] == "forked"
    assert len(client.fork_requests) == 1
    assert client.fork_requests[0].request_id == "8" * 32
    assert client.fork_requests[0].through_event_seq == 3
    assert client.fork_requests[0].title == "Synthetic branch"

    exported = surface.call(
        "agent_export",
        {
            "egress": _egress(),
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 2,
                "expected_history_revision": 4,
                "max_events": 10,
            },
        },
    )
    assert exported["result"]["complete"] is True
    assert exported["result"]["workspace_path_included"] is False
    assert len(client.export_requests) == 1
    assert client.export_requests[0].max_events == 10

    closed = surface.call(
        "agent_close",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "expected_catalog_revision": 2,
                "expected_history_revision": 4,
            },
        },
    )
    assert closed["result"]["outcome"] == "closed"
    assert closed["result"]["catalog_session_retained"] is True
    assert len(client.close_requests) == 1
    assert client.close_requests[0].expected_catalog_revision == 2
    assert client.close_requests[0].expected_history_revision == 4

    proposed = surface.call(
        "agent_propose",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "6" * 32,
                    "operation": "edit",
                    "path": "src/example.py",
                    "content": "print('synthetic')\n",
                    "expected_revision": "5" * 64,
                },
            },
        },
    )
    assert proposed["result"]["state"] == "pending_native_review"
    assert proposed["result"]["approval_id"] == "d" * 32
    assert len(client.write_proposals) == 1
    assert client.write_proposals[0].proposal.content == "print('synthetic')\n"
    proposed_transaction = surface.call(
        "agent_propose_transaction",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "7" * 32,
                    "changes": [
                        {
                            "operation": "edit",
                            "path": "src/alpha.py",
                            "content": "alpha = 2\n",
                            "expected_revision": "1" * 64,
                            "line_ending": "lf",
                        },
                        {
                            "operation": "create",
                            "path": "src/new.py",
                            "content": "created = True\n",
                            "line_ending": "lf",
                        },
                    ],
                },
            },
        },
    )
    assert proposed_transaction["result"]["state"] == "pending_native_review"
    assert proposed_transaction["result"]["file_count"] == 2
    assert [item["operation"] for item in proposed_transaction["result"]["files"]] == [
        "edit",
        "create",
    ]
    assert proposed_transaction["result"]["approval_id"] == "f" * 32
    assert len(client.write_transaction_proposals) == 1
    proposed_lifecycle = surface.call(
        "agent_propose_lifecycle",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_ID,
                "proposal": {
                    "request_id": "8" * 32,
                    "operation": "trash_file",
                    "path": "src/obsolete.py",
                    "expected_revision": "3" * 64,
                },
            },
        },
    )
    assert proposed_lifecycle["result"]["state"] == "pending_native_review"
    assert proposed_lifecycle["result"]["permanent"] is False
    assert proposed_lifecycle["result"]["recovery"] == "windows_recycle_bin"
    assert len(client.lifecycle_proposals) == 1
    with pytest.raises(AgentMcpSurfaceError) as generic:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "propose_file_write",
                    "path_parameters": {"session_id": SESSION_ID},
                    "body": client.write_proposals[0].proposal.model_dump(mode="json"),
                },
            },
        )
    assert generic.value.code == "write_proposal_requires_dedicated_tool"
    with pytest.raises(AgentMcpSurfaceError) as generic_transaction:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "propose_file_transaction",
                    "path_parameters": {"session_id": SESSION_ID},
                    "body": client.write_transaction_proposals[
                        0
                    ].proposal.model_dump(mode="json"),
                },
            },
        )
    assert (
        generic_transaction.value.code
        == "write_proposal_requires_dedicated_tool"
    )
    with pytest.raises(AgentMcpSurfaceError) as generic_lifecycle:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "propose_workspace_lifecycle",
                    "path_parameters": {"session_id": SESSION_ID},
                    "body": client.lifecycle_proposals[0].proposal.model_dump(
                        mode="json"
                    ),
                },
            },
        )
    assert generic_lifecycle.value.code == "write_proposal_requires_dedicated_tool"

    turned = surface.call(
        "agent_turn",
        {
            "egress": _egress(),
            "request": {
                "session_id": SESSION_ID,
                "message": {"text": "Synthetic selected request"},
            },
            "deadline_seconds": 12,
            "drain_timeout_seconds": 3,
        },
    )
    assert turned["result"]["message"] == "Synthetic selected request"
    assert client.turn_options == {
        "deadline_seconds": 12.0,
        "poll_interval_seconds": 0.1,
        "drain_timeout_seconds": 3.0,
    }

    stopped = surface.call(
        "agent_stop",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {"session_id": SESSION_ID, "after": 4},
            "drain_timeout_seconds": 2,
        },
    )
    assert stopped["result"]["stop_request_state"] == "accepted"
    assert client.stop_options == {
        "drain_timeout_seconds": 2.0,
        "poll_interval_seconds": 0.1,
    }

    waited = surface.call(
        "agent_wait",
        {
            "egress": _egress(),
            "request": {"session_id": SESSION_ID, "after": 4},
            "deadline_seconds": 9,
        },
    )
    assert waited["result"]["cursor"] == 4
    assert client.wait_options == {
        "deadline_seconds": 9.0,
        "poll_interval_seconds": 0.1,
    }


def test_stop_requires_exact_authority_and_cannot_use_generic_invoke() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    base = {
        "egress": _egress(),
        "request": {"session_id": SESSION_ID, "after": 0},
    }

    for authorization in (False, 1):
        try:
            surface.call(
                "agent_stop",
                {**base, "mutation_authorized": authorization},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("turn Stop accepted inexact mutation authority")
    assert client.stop_options is None

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "stop_turn",
                    "path_parameters": {"session_id": SESSION_ID},
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "stop_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the bounded Stop tool")
    assert client.invocations == []


def test_resume_requires_exact_authority_and_cannot_use_generic_invoke() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    base = {
        "egress": _egress(),
        "request": {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "expected_catalog_revision": 1,
            "expected_history_revision": 0,
        },
    }

    for authorization in (False, 1):
        try:
            surface.call(
                "agent_resume",
                {**base, "mutation_authorized": authorization},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("chat Resume accepted inexact mutation authority")
    assert client.resume_requests == []

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "resume_retained_session",
                    "path_parameters": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                    },
                    "body": {
                        "expected_catalog_revision": 1,
                        "expected_history_revision": 0,
                    },
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "resume_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the safe Resume tool")
    assert client.invocations == []


def test_fork_requires_exact_authority_and_cannot_use_generic_invoke() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    base = {
        "egress": _egress(),
        "request": {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "request_id": "8" * 32,
            "expected_catalog_revision": 1,
            "expected_history_revision": 0,
        },
    }

    for authorization in (False, 1):
        try:
            surface.call(
                "agent_fork",
                {**base, "mutation_authorized": authorization},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("chat Fork accepted inexact mutation authority")
    assert client.fork_requests == []

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "fork_retained_session",
                    "path_parameters": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                    },
                    "body": {
                        "request_id": "8" * 32,
                        "expected_catalog_revision": 1,
                        "expected_history_revision": 0,
                    },
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "fork_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the safe Fork tool")
    assert client.invocations == []


def test_export_is_dedicated_path_free_and_cannot_use_generic_invoke() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    for bad_request in (
        {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "expected_catalog_revision": 1,
            "expected_history_revision": 0,
            "max_events": 4_001,
        },
        {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "expected_catalog_revision": 1,
            "expected_history_revision": 0,
            "workspace": "/example/workspace",
        },
    ):
        try:
            surface.call(
                "agent_export",
                {"egress": _egress(), "request": bad_request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("unsafe Agent export request was accepted")
    assert client.export_requests == []

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "request": {
                    "operation": "export_retained_history",
                    "path_parameters": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                    },
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "export_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the safe Export tool")
    assert client.invocations == []


def test_close_requires_exact_authority_and_cannot_use_generic_delete() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    base = {
        "egress": _egress(),
        "request": {
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "expected_catalog_revision": 1,
            "expected_history_revision": 0,
        },
    }

    for authorization in (False, 1):
        try:
            surface.call(
                "agent_close",
                {**base, "mutation_authorized": authorization},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError("chat Close accepted inexact mutation authority")
    try:
        surface.call(
            "agent_close",
            {
                **base,
                "mutation_authorized": True,
                "request": {**base["request"], "workspace": "/example/workspace"},
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "invalid_arguments"
    else:
        raise AssertionError("chat Close accepted an undeclared workspace path")
    assert client.close_requests == []

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "close_live_session",
                    "path_parameters": {"session_id": SESSION_ID},
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "close_requires_dedicated_tool"
    else:
        raise AssertionError("generic MCP invocation bypassed the safe Close tool")
    assert client.invocations == []


def test_catalog_tool_maps_seven_strict_actions_and_validates_results() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    calls = (
        (
            {
                "action": "list_projects",
                "search": "  Synthetic   project ",
                "include_archived": True,
                "limit": 10,
            },
            "list_projects",
        ),
        (
            {"action": "get_project", "project_id": PROJECT_ID},
            "get_project",
        ),
        (
            {
                "action": "create_project",
                "mutation_authorized": True,
                "name": "  Created   project ",
            },
            "create_project",
        ),
        (
            {
                "action": "update_project",
                "mutation_authorized": True,
                "project_id": PROJECT_ID,
                "expected_revision": 1,
                "name": " Renamed   project ",
                "pinned": True,
            },
            "update_project",
        ),
        (
            {
                "action": "list_chats",
                "project_id": PROJECT_ID,
                "search": " Synthetic ",
                "limit": 12,
            },
            "list_project_sessions",
        ),
        (
            {"action": "get_chat", "session_id": SESSION_ID},
            "get_catalog_session",
        ),
        (
            {
                "action": "update_chat",
                "mutation_authorized": True,
                "session_id": SESSION_ID,
                "expected_revision": 1,
                "title": " Renamed   chat ",
                "project_id": OTHER_PROJECT_ID,
                "pinned": True,
            },
            "update_catalog_session",
        ),
    )
    results = []
    for request, operation in calls:
        result = surface.call(
            "agent_catalog",
            {"egress": _egress(), "request": request},
        )["result"]
        assert result["action"] == request["action"]
        assert result["operation"] == operation
        results.append(result)

    assert results[0]["response"]["projects"][0]["project_id"] == PROJECT_ID
    assert results[2]["status_code"] == 201
    assert results[2]["response"]["name"] == "Created project"
    assert results[3]["response"]["name"] == "Renamed project"
    assert results[3]["response"]["pinned"] is True
    assert results[4]["response"]["sessions"][0]["project_id"] == PROJECT_ID
    assert results[6]["response"]["title"] == "Renamed chat"
    assert results[6]["response"]["project_id"] == OTHER_PROJECT_ID
    assert results[6]["response"]["revision"] == 2

    assert [item.operation for item in client.invocations] == [
        operation for _, operation in calls
    ]
    assert client.invocations[0].query == {
        "include_archived": True,
        "limit": 10,
        "search": "Synthetic project",
    }
    assert client.invocations[2].body == {"name": "Created project"}
    assert client.invocations[3].body["expected_revision"] == 1
    assert client.invocations[6].body["title"] == "Renamed chat"


def test_catalog_mutations_and_action_shapes_fail_closed_before_http() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    rejected = (
        {"action": "create_project", "name": "Synthetic project"},
        {
            "action": "create_project",
            "mutation_authorized": False,
            "name": "Synthetic project",
        },
        {
            "action": "create_project",
            "mutation_authorized": 1,
            "name": "Synthetic project",
        },
        {
            "action": "update_project",
            "mutation_authorized": True,
            "project_id": PROJECT_ID,
            "expected_revision": 1,
        },
        {
            "action": "list_projects",
            "session_id": SESSION_ID,
        },
        {
            "action": "get_chat",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
        },
        {
            "action": "delete_chat",
            "mutation_authorized": True,
            "session_id": SESSION_ID,
        },
        {
            "action": "list_chats",
            "include_archived": "false",
        },
    )
    for request in rejected:
        try:
            surface.call(
                "agent_catalog",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError(f"catalog accepted invalid request {request['action']}")
    assert client.invocations == []


class _InvalidCatalogController(_FakeController):
    def __init__(self, defect: str) -> None:
        super().__init__()
        self.defect = defect

    def invoke(self, request):
        result = super().invoke(request)
        assert isinstance(result.response, dict)
        if self.defect == "project_identity":
            result.response["project_id"] = OTHER_PROJECT_ID
        elif self.defect == "chat_scope":
            result.response["sessions"][0]["project_id"] = OTHER_PROJECT_ID
        elif self.defect == "revision":
            result.response["revision"] = request.body["expected_revision"] + 2
        elif self.defect == "undeclared":
            result.response["local_secret"] = "must-not-cross"
        return result


def test_catalog_rejects_cross_identity_revision_and_undeclared_responses() -> None:
    calls = (
        (
            "project_identity",
            {"action": "get_project", "project_id": PROJECT_ID},
        ),
        (
            "chat_scope",
            {"action": "list_chats", "project_id": PROJECT_ID},
        ),
        (
            "revision",
            {
                "action": "update_chat",
                "mutation_authorized": True,
                "session_id": SESSION_ID,
                "expected_revision": 1,
                "pinned": True,
            },
        ),
        (
            "undeclared",
            {"action": "get_chat", "session_id": SESSION_ID},
        ),
    )
    for defect, request in calls:
        surface = AgentMcpSurface(_InvalidCatalogController(defect))
        try:
            surface.call(
                "agent_catalog",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "catalog_response_invalid"
        else:
            raise AssertionError(f"catalog accepted {defect} response")


def test_history_tool_reads_one_bounded_sanitized_retained_page() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    result = surface.call(
        "agent_history",
        {
            "egress": _egress(),
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "after": 0,
            "limit": 25,
        },
    )

    assert result["contract_version"] == AGENT_MCP_CONTRACT_VERSION
    page = result["result"]
    assert page["operation"] == "read_retained_history"
    assert page["project_id"] == PROJECT_ID
    assert page["session_id"] == SESSION_ID
    assert page["response"]["events"][0]["text"] == "Synthetic retained status."
    invocation = client.invocations[0]
    assert invocation.operation == "read_retained_history"
    assert invocation.path_parameters == {
        "project_id": PROJECT_ID,
        "session_id": SESSION_ID,
    }
    assert invocation.query == {"after": 0, "limit": 25}
    assert invocation.body is None


def test_history_input_is_strict_and_fails_before_http() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    invalid = (
        {"after": -1},
        {"after": "0"},
        {"limit": 0},
        {"limit": "25"},
        {"limit": 501},
        {"action": "export"},
    )
    for extra in invalid:
        try:
            surface.call(
                "agent_history",
                {
                    "egress": _egress(),
                    "project_id": PROJECT_ID,
                    "session_id": SESSION_ID,
                    **extra,
                },
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError(f"history accepted invalid input {extra}")
    assert client.invocations == []


class _InvalidHistoryController(_FakeController):
    def __init__(self, defect: str) -> None:
        super().__init__()
        self.defect = defect

    def invoke(self, request):
        result = super().invoke(request)
        assert isinstance(result.response, dict)
        if self.defect == "session":
            result.response["session_id"] = "f" * 32
        elif self.defect == "raw_arguments":
            result.response["events"][0]["arguments"] = {"path": "synthetic.txt"}
        elif self.defect == "live":
            result.response["running"] = True
        elif self.defect == "cursor":
            result.response["events"][0]["seq"] = 0
        elif self.defect == "undeclared":
            result.response["private_payload"] = "must-not-cross"
        return result


def test_history_rejects_cross_session_live_raw_and_incoherent_responses() -> None:
    for defect in ("session", "raw_arguments", "live", "cursor", "undeclared"):
        surface = AgentMcpSurface(_InvalidHistoryController(defect))
        try:
            surface.call(
                "agent_history",
                {
                    "egress": _egress(),
                    "project_id": PROJECT_ID,
                    "session_id": SESSION_ID,
                },
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "history_response_invalid"
        else:
            raise AssertionError(f"history accepted {defect} response")


def test_artifact_tool_lists_gets_and_previews_metadata_without_content_bytes() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    listed = surface.call(
        "agent_artifacts",
        {
            "egress": _egress(),
            "request": {
                "action": "list",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "limit": 12,
            },
        },
    )["result"]
    detail = surface.call(
        "agent_artifacts",
        {
            "egress": _egress(),
            "request": {
                "action": "get",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "artifact_id": ARTIFACT_ID,
            },
        },
    )["result"]
    preview = surface.call(
        "agent_artifacts",
        {
            "egress": _egress(),
            "request": {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
                "title": "Synthetic report",
            },
        },
    )["result"]
    default_title_preview = surface.call(
        "agent_artifacts",
        {
            "egress": _egress(),
            "request": {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/default-title.pdf",
            },
        },
    )["result"]
    exported = surface.call(
        "agent_artifacts",
        {
            "egress": _egress(),
            "request": {
                "action": "export",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "artifact_id": ARTIFACT_ID,
                "expected_revision": 1,
                "version_id": VERSION_ID,
            },
        },
    )["result"]

    assert listed["action"] == "list"
    assert listed["operation"] == "list_artifacts"
    assert listed["response"]["artifacts"][0]["path"] == "notes.md"
    assert detail["action"] == "get"
    assert detail["operation"] == "get_artifact"
    assert detail["response"]["artifact_id"] == ARTIFACT_ID
    assert detail["response"]["versions"][0]["version_id"] == VERSION_ID
    assert preview["action"] == "preview_capture"
    assert preview["operation"] == "preview_artifact_capture"
    assert preview["response"] == _artifact_capture_preview()
    assert default_title_preview["response"]["title"] == "default-title.pdf"
    assert exported["action"] == "export"
    assert exported["operation"] == "export_artifact_lineage"
    assert exported["response"] == _artifact_export_record()
    assert exported["response"]["content_included"] is False
    assert exported["response"]["absolute_path_included"] is False
    assert preview["response"]["requires_native_confirmation"] is True
    assert preview["response"]["file_content_included"] is False
    serialized = json.dumps(
        [listed, detail, preview, default_title_preview, exported],
        sort_keys=True,
    )
    assert "payload" not in serialized
    assert "data_base64" not in serialized
    assert client.invocations[0].query == {"limit": 12}
    assert client.invocations[1].query == {}
    assert client.invocations[0].body is None
    assert client.invocations[1].body is None
    assert client.invocations[2].query == {}
    assert client.invocations[2].body == {
        "path": "reports/synthetic.pdf",
        "title": "Synthetic report",
    }
    assert client.invocations[3].query == {}
    assert client.invocations[3].body == {"path": "reports/default-title.pdf"}
    assert client.invocations[4].query == {}
    assert client.invocations[4].body == {
        "expected_revision": 1,
        "version_id": VERSION_ID,
    }


def test_artifact_action_shapes_fail_closed_before_http() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    invalid = (
        {
            "action": "get",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
        },
        {
            "action": "get",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
            "limit": 1,
        },
        {
            "action": "list",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
        },
        {
            "action": "export",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
            "version_id": VERSION_ID,
        },
        {
            "action": "export",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
            "expected_revision": 0,
            "version_id": VERSION_ID,
        },
        {
            "action": "export",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
            "expected_revision": 1,
            "version_id": "not-a-version",
        },
        {
            "action": "export",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
            "expected_revision": 1,
            "version_id": VERSION_ID,
            "limit": 1,
        },
        {
            "action": "read_content",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "artifact_id": ARTIFACT_ID,
        },
        {
            "action": "list",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "limit": "12",
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "C:/example/synthetic.pdf",
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "../synthetic.pdf",
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "reports\\synthetic.pdf",
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "reports/synthetic.pdf",
            "title": " untrimmed",
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "reports/synthetic.pdf",
            "title": "x" * 121,
        },
        {
            "action": "preview_capture",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "path": "reports/synthetic.pdf",
            "artifact_id": ARTIFACT_ID,
        },
    )
    for request in invalid:
        try:
            surface.call(
                "agent_artifacts",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError(f"artifacts accepted invalid action {request['action']}")
    assert client.invocations == []


class _InvalidArtifactController(_FakeController):
    def __init__(self, defect: str) -> None:
        super().__init__()
        self.defect = defect

    def invoke(self, request):
        result = super().invoke(request)
        assert isinstance(result.response, dict)
        if request.operation == "list_artifacts":
            if self.defect == "scope":
                result.response["artifacts"][0]["project_id"] = OTHER_PROJECT_ID
            elif self.defect == "duplicate":
                result.response["artifacts"].append(
                    dict(result.response["artifacts"][0])
                )
        elif request.operation == "get_artifact":
            if self.defect == "identity":
                result.response["artifact_id"] = "f" * 32
            elif self.defect == "bytes":
                result.response["payload"] = "must-not-cross"
        elif request.operation == "preview_artifact_capture":
            if self.defect == "preview_scope":
                result.response["project_id"] = OTHER_PROJECT_ID
            elif self.defect == "preview_path":
                result.response["path"] = "reports/different.pdf"
            elif self.defect == "preview_title":
                result.response["title"] = "Different title"
            elif self.defect == "preview_bytes":
                result.response["payload"] = "must-not-cross"
            elif self.defect == "preview_native":
                result.response["requires_native_confirmation"] = False
        elif request.operation == "export_artifact_lineage":
            if self.defect == "export_scope":
                result.response["artifact"]["project_id"] = OTHER_PROJECT_ID
            elif self.defect == "export_identity":
                result.response["artifact"]["artifact_id"] = "f" * 32
            elif self.defect == "export_revision":
                result.response["artifact"]["revision"] = 2
            elif self.defect == "export_version":
                result.response["selected_version"]["version_id"] = "f" * 32
            elif self.defect == "export_digest":
                result.response["evidence"]["sha256"] = "f" * 64
            elif self.defect == "export_content":
                result.response["content_included"] = True
            elif self.defect == "export_path":
                result.response["absolute_path_included"] = True
            elif self.defect == "export_bytes":
                result.response["payload"] = "must-not-cross"
        return result


def test_artifacts_reject_cross_scope_duplicate_identity_and_byte_responses() -> None:
    calls = (
        (
            "scope",
            {"action": "list", "project_id": PROJECT_ID, "session_id": SESSION_ID},
        ),
        (
            "duplicate",
            {"action": "list", "project_id": PROJECT_ID, "session_id": SESSION_ID},
        ),
        (
            "identity",
            {
                "action": "get",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "artifact_id": ARTIFACT_ID,
            },
        ),
        (
            "bytes",
            {
                "action": "get",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "artifact_id": ARTIFACT_ID,
            },
        ),
        (
            "preview_scope",
            {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
            },
        ),
        (
            "preview_path",
            {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
            },
        ),
        (
            "preview_title",
            {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
            },
        ),
        (
            "preview_bytes",
            {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
            },
        ),
        (
            "preview_native",
            {
                "action": "preview_capture",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "path": "reports/synthetic.pdf",
            },
        ),
        *(
            (
                defect,
                {
                    "action": "export",
                    "project_id": PROJECT_ID,
                    "session_id": SESSION_ID,
                    "artifact_id": ARTIFACT_ID,
                    "expected_revision": 1,
                    "version_id": VERSION_ID,
                },
            )
            for defect in (
                "export_scope",
                "export_identity",
                "export_revision",
                "export_version",
                "export_digest",
                "export_content",
                "export_path",
                "export_bytes",
            )
        ),
    )
    for defect, request in calls:
        surface = AgentMcpSurface(_InvalidArtifactController(defect))
        try:
            surface.call(
                "agent_artifacts",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "artifact_response_invalid"
        else:
            raise AssertionError(f"artifacts accepted {defect} response")


def test_artifact_capture_preview_cannot_use_generic_invoke() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    with pytest.raises(AgentMcpSurfaceError) as blocked:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {
                    "operation": "preview_artifact_capture",
                    "path_parameters": {
                        "project_id": PROJECT_ID,
                        "session_id": SESSION_ID,
                    },
                    "body": {"path": "reports/synthetic.pdf"},
                },
            },
        )

    assert blocked.value.code == "artifact_preview_requires_dedicated_tool"
    assert client.invocations == []


def test_context_tool_reports_truthful_runtime_chat_and_media_without_private_fields() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    runtime_result = surface.call(
        "agent_context",
        {
            "egress": _egress(),
            "request": {"action": "runtime"},
        },
    )["result"]
    assert runtime_result["operations"] == [
        "get_local_runtime",
        "get_local_model_compatibility",
    ]
    runtime_view = runtime_result["view"]
    assert runtime_view["contract_version"] == "agent-mcp-context.v3"
    assert runtime_view["snapshot_consistency"] == "sequential_non_atomic"
    assert runtime_view["runtime"]["state"] == "ready"
    assert runtime_view["runtime"]["served"] == {
        "alias": "example-model",
        "device": "split",
        "gpu_layers": 4,
        "context_size": 8192,
    }
    assert runtime_view["runtime"]["context"]["used_tokens"] == 1024
    assert runtime_view["runtime"]["context_binding"] == (
        "runtime_global_last_request"
    )
    assert "selected_chat_context_proven" not in runtime_view["runtime"]
    assert runtime_view["runtime"]["accepted_placements"] == [
        "gpu",
        "split",
        "cpu",
    ]
    assert runtime_view["models"]["installed_count"] == 1
    assert runtime_view["models"]["adapter"] == {
        "adapter_id": "llama.cpp-openai-gguf",
        "adapter_version": "llama.cpp-openai-gguf.v1",
        "runtime_version": "synthetic-runtime-v1",
        "runtime_identity_state": "unknown",
        "capability_probe_version": "local-runtime-multimodal-probe.v2",
    }
    assert runtime_view["models"]["models"][0]["alias"] == "example-model"
    assert runtime_view["attachments"] == {
        "image_input": True,
        "audio_input": True,
        "document_input": True,
        "microphone_recording": True,
        "image_media_types": ["image/png", "image/jpeg"],
        "audio_media_types": ["audio/wav"],
        "document_media_types": [
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
            "text/tab-separated-values",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.oasis.opendocument.text",
        ],
        "document_formats": [
            "plain_text",
            "markdown",
            "json",
            "csv",
            "tsv",
            "docx",
            "pptx",
            "xlsx",
            "odt",
        ],
        "document_routing": "local_text_projection",
        "pdf_input": False,
        "original_document_bytes_to_model": False,
        "max_message_attachments": 4,
        "max_staged_attachments": 16,
        "max_message_bytes": 16 * 1024 * 1024,
        "max_session_bytes": 64 * 1024 * 1024,
        "max_image_bytes": 8 * 1024 * 1024,
        "max_image_dimension": 8192,
        "max_image_pixels": 33_554_432,
        "max_audio_bytes": 12 * 1024 * 1024,
        "max_audio_duration_ms": 5 * 60 * 1000,
        "max_document_bytes": 12 * 1024 * 1024,
        "max_text_document_bytes": 2 * 1024 * 1024,
        "max_document_projection_characters": 100_000,
        "max_document_preview_characters": 12_000,
        "max_document_message_characters": 200_000,
    }
    assert runtime_view["chat"] is None

    chat_result = surface.call(
        "agent_context",
        {
            "egress": _egress(),
            "request": {
                "action": "chat",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
            },
        },
    )["result"]
    assert chat_result["operations"] == [
        "get_local_runtime",
        "get_local_model_compatibility",
        "get_live_session",
        "get_session_context",
        "list_attachments",
    ]
    chat = chat_result["view"]["chat"]
    assert chat["project_id"] == PROJECT_ID
    assert chat["session_id"] == SESSION_ID
    assert chat["configured_model_alias"] == "example-model"
    assert chat["effective_model_alias"] == "example-model"
    assert chat["selected_model_ready"] is True
    assert chat["parameters"]["enable_thinking"] is True
    assert chat["approval_pending"] is False
    assert chat["selected_chat_context_proven"] is True
    assert chat["context"]["session_id"] == SESSION_ID
    assert chat["context"]["turn_id"] == "7" * 32
    assert chat["context"]["context"]["used_tokens"] == 1024
    assert chat["staged_attachments"] == [
        {
            "attachment_id": "9" * 32,
            "model_alias": "example-model",
            "kind": "image",
            "media_type": "image/png",
            "display_name": "synthetic-image.png",
            "byte_size": 128,
            "width": 8,
            "height": 8,
            "duration_ms": None,
            "sample_rate_hz": None,
            "channels": None,
            "routing": "native_multimodal",
            "document_format": None,
            "projected_characters": None,
            "projection_truncated": None,
            "omitted_features": [],
            "source": "file",
            "expires_at": "2026-01-02T04:04:05Z",
        },
        {
            "attachment_id": "6" * 32,
            "model_alias": "example-model",
            "kind": "document",
            "media_type": "text/markdown",
            "display_name": "synthetic-notes.md",
            "byte_size": 96,
            "width": None,
            "height": None,
            "duration_ms": None,
            "sample_rate_hz": None,
            "channels": None,
            "routing": "local_text_projection",
            "document_format": "markdown",
            "projected_characters": 72,
            "projection_truncated": False,
            "omitted_features": [],
            "source": "file",
            "expires_at": "2026-01-02T04:04:05Z",
        },
    ]
    serialized = json.dumps(chat_result)
    for forbidden in (
        "/example/workspace",
        "Synthetic instruction that must not cross",
        '"pid"',
        '"sha256"',
        '"payload"',
        "Bounded local projection",
        '"pending_approval_id"',
    ):
        assert forbidden not in serialized


def test_context_action_shapes_are_strict_before_http() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)
    invalid = (
        {"action": "runtime", "session_id": SESSION_ID},
        {"action": "chat", "session_id": SESSION_ID},
        {"action": "chat", "project_id": PROJECT_ID},
        {
            "action": "chat",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "include_bytes": True,
        },
        {"action": "count_tokens"},
    )
    for request in invalid:
        try:
            surface.call(
                "agent_context",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError(f"context accepted invalid request {request}")
    assert client.invocations == []


class _InvalidContextController(_FakeController):
    def __init__(self, defect: str) -> None:
        super().__init__()
        self.defect = defect

    def invoke(self, request):
        result = super().invoke(request)
        assert isinstance(result.response, dict)
        if request.operation == "get_local_runtime" and self.defect == "runtime_private":
            result.response["private_path"] = "/must-not-cross"
        elif request.operation == "get_local_model_compatibility" and self.defect == "duplicate_model":
            result.response["models"].append(dict(result.response["models"][0]))
        elif request.operation == "get_live_session" and self.defect == "project_scope":
            result.response["settings"]["project_id"] = OTHER_PROJECT_ID
        elif request.operation == "get_session_context" and self.defect == "context_scope":
            result.response["session_id"] = "f" * 32
        elif request.operation == "get_session_context" and self.defect == "context_private":
            result.response["private_path"] = "/must-not-cross"
        elif request.operation == "list_attachments" and self.defect == "attachment_scope":
            result.response["session_id"] = "f" * 32
        elif request.operation == "list_attachments" and self.defect == "attachment_bytes":
            result.response["attachments"][0]["payload"] = "must-not-cross"
        elif request.operation == "list_attachments" and self.defect == "attachment_model":
            result.response["attachments"][0]["model_alias"] = "other-model"
        return result


def test_context_rejects_private_extensions_duplicates_and_cross_scope_metadata() -> None:
    for defect in (
        "runtime_private",
        "duplicate_model",
        "project_scope",
        "context_scope",
        "context_private",
        "attachment_scope",
        "attachment_bytes",
        "attachment_model",
    ):
        action = "runtime" if defect in {"runtime_private", "duplicate_model"} else "chat"
        request: dict[str, Any] = {"action": action}
        if action == "chat":
            request.update({"project_id": PROJECT_ID, "session_id": SESSION_ID})
        surface = AgentMcpSurface(_InvalidContextController(defect))
        try:
            surface.call(
                "agent_context",
                {"egress": _egress(), "request": request},
            )
        except AgentMcpSurfaceError as error:
            assert error.code == "context_response_invalid"
        else:
            raise AssertionError(f"context accepted {defect} response")


def test_workspace_tool_maps_six_read_only_actions_and_validates_responses() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    calls = (
        ("inspect", None, "inspect_workspace"),
        ("list", "src", "list_workspace_tree"),
        ("search", None, "search_workspace_text"),
        ("read", "src/app.py", "read_workspace_file"),
        ("changes", None, "review_changes"),
        ("diff", "src/app.py", "read_change_diff"),
    )
    for action, path, operation in calls:
        arguments: dict[str, Any] = {
            "egress": _egress(),
            "session_id": SESSION_ID,
            "action": action,
        }
        if path is not None:
            arguments["path"] = path
        if action == "search":
            arguments.update({"query": "synthetic", "glob": "src/**/*.py"})
        result = surface.call("agent_workspace", arguments)
        assert result["contract_version"] == AGENT_MCP_CONTRACT_VERSION
        assert result["result"]["action"] == action
        assert result["result"]["operation"] == operation
        assert result["result"]["response"]["session_id"] == SESSION_ID

    assert [request.operation for request in client.invocations] == [
        "inspect_workspace",
        "list_workspace_tree",
        "search_workspace_text",
        "read_workspace_file",
        "review_changes",
        "read_change_diff",
    ]
    assert all(request.body is None for request in client.invocations)
    search_request = client.invocations[2]
    assert search_request.query == {
        "query": "synthetic",
        "glob": "src/**/*.py",
        "regex": "false",
    }


def test_workspace_tool_rejects_unsafe_or_incoherent_paths_before_http() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    for action, path in (
        ("read", "../secret.txt"),
        ("read", "C:/secret.txt"),
        ("read", "src\\secret.txt"),
        ("diff", None),
        ("inspect", "src"),
        ("search", "src"),
    ):
        arguments: dict[str, Any] = {
            "egress": _egress(),
            "session_id": SESSION_ID,
            "action": action,
        }
        if path is not None:
            arguments["path"] = path
        try:
            surface.call("agent_workspace", arguments)
        except AgentMcpSurfaceError as error:
            assert error.code == "invalid_arguments"
        else:
            raise AssertionError(f"workspace action {action} accepted path {path!r}")
    assert client.invocations == []


def test_workspace_search_rejects_missing_query_unsafe_glob_and_cross_action_fields() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client)

    invalid = (
        {"action": "search"},
        {"action": "search", "query": "synthetic", "glob": "../**/*"},
        {"action": "search", "query": "synthetic", "glob": "C:/**"},
        {"action": "read", "path": "src/app.py", "query": "synthetic"},
        {"action": "list", "path": ".", "regex": True},
    )
    for fields in invalid:
        with pytest.raises(AgentMcpSurfaceError) as raised:
            surface.call(
                "agent_workspace",
                {
                    "egress": _egress(),
                    "session_id": SESSION_ID,
                    **fields,
                },
            )
        assert raised.value.code == "invalid_arguments"
    assert client.invocations == []


class _CrossSessionWorkspaceController(_FakeController):
    def invoke(self, request):
        result = super().invoke(request)
        assert isinstance(result.response, dict)
        result.response["session_id"] = "c" * 32
        return result


def test_workspace_tool_rejects_cross_session_response() -> None:
    surface = AgentMcpSurface(_CrossSessionWorkspaceController())
    try:
        surface.call(
            "agent_workspace",
            {
                "egress": _egress(),
                "session_id": SESSION_ID,
                "action": "read",
                "path": "src/app.py",
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "workspace_response_invalid"
    else:
        raise AssertionError("workspace tool accepted another session's response")


def test_generic_invoke_requires_mutation_and_refuses_all_delete_calls() -> None:
    surface = AgentMcpSurface(_FakeController())

    for operation, extra, expected in (
        ("create_project", {}, "mutation_authorization_required"),
        (
            "delete_project",
            {"mutation_authorized": True},
            "destructive_action_requires_agent_ui",
        ),
    ):
        try:
            surface.call(
                "agent_invoke",
                {
                    "egress": _egress(),
                    "request": {
                        "operation": operation,
                        "path_parameters": (
                            {"project_id": PROJECT_ID}
                            if operation == "delete_project"
                            else {}
                        ),
                        "body": ({"name": "Synthetic"} if operation == "create_project" else None),
                    },
                    **extra,
                },
            )
        except AgentMcpSurfaceError as error:
            assert error.code == expected
        else:
            raise AssertionError(f"{operation} bypassed its authorization gate")

    try:
        surface.call(
            "agent_invoke",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "destructive_action_authorized": True,
                "request": {
                    "operation": "delete_project",
                    "path_parameters": {"project_id": PROJECT_ID},
                },
            },
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "invalid_arguments"
    else:
        raise AssertionError("obsolete caller-provided delete authority was accepted")


def test_runtime_requires_server_and_per_call_opt_in() -> None:
    client = _FakeController()
    surface = AgentMcpSurface(client, allow_model_lifecycle=True)
    assert [tool.name for tool in surface.tools()][-1] == "agent_runtime"

    incomplete = {
        "egress": _egress(),
        "model_lifecycle_authorized": False,
        "request": {"desired_state": "stopped", "alias": "example-model"},
    }
    try:
        surface.call("agent_runtime", incomplete)
    except AgentMcpSurfaceError as error:
        assert error.code == "invalid_arguments"
    else:
        raise AssertionError("runtime call accepted false lifecycle authorization")
    assert client.runtime_calls == 0

    try:
        surface.call(
            "agent_runtime",
            {**incomplete, "model_lifecycle_authorized": 1},
        )
    except AgentMcpSurfaceError as error:
        assert error.code == "invalid_arguments"
    else:
        raise AssertionError("numeric truth bypassed lifecycle authorization")
    assert client.runtime_calls == 0

    result = surface.call(
        "agent_runtime",
        {
            **incomplete,
            "model_lifecycle_authorized": True,
        },
    )
    assert result["result"] == {"outcome": "stopped", "alias": "example-model"}
    assert client.runtime_calls == 1


class _FailingController(_FakeController):
    def discover(self, *, refresh: bool = False):
        raise AgentControllerError(
            "controller_http_error",
            http_status=503,
            retryable=True,
        )


def test_mcp_serializes_only_closed_controller_error_facts() -> None:
    surface = AgentMcpSurface(_FailingController())
    reply = handle_message(
        surface,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "agent_discover", "arguments": {}},
        },
        server_name="prompt-enhancer-agent",
        instructions="Synthetic safe instructions.",
    )
    assert reply is not None
    failure = reply["result"]["structuredContent"]
    assert failure == {
        "error": "controller_http_error",
        "http_status": 503,
        "retryable": True,
    }
    assert "exception" not in json.dumps(reply).lower()


class _UntrustedErrorSurface:
    def tools(self) -> tuple[ToolSpec, ...]:
        return ()

    def call(self, name, arguments):
        raise AgentSurfaceError(
            "closed_failure",
            details={
                "error": "overwritten",
                "secret": "SYNTHETIC_SECRET_MUST_NOT_CROSS",
                "http_status": "503",
                "retryable": "true",
            },
        )


def test_transport_allowlists_error_detail_fields_and_types() -> None:
    reply = handle_message(
        _UntrustedErrorSurface(),
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "synthetic", "arguments": {}},
        },
    )
    assert reply is not None
    assert reply["result"]["structuredContent"] == {"error": "closed_failure"}
    assert "SYNTHETIC_SECRET_MUST_NOT_CROSS" not in json.dumps(reply)


def test_custom_server_identity_round_trips_without_starting_a_process() -> None:
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
    )
    stdout = io.StringIO()
    server = McpStdioServer(
        AgentMcpSurface(_FakeController()),
        stdin=stdin,
        stdout=stdout,
        version="9.9",
        server_name="prompt-enhancer-agent",
        instructions="Synthetic safe instructions.",
    )
    assert server.serve_forever() == 0
    response = json.loads(stdout.getvalue())
    assert response["result"]["serverInfo"] == {
        "name": "prompt-enhancer-agent",
        "version": "9.9",
    }
    assert response["result"]["instructions"] == "Synthetic safe instructions."


def test_config_is_token_free_and_model_lifecycle_is_opt_in(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    document = agent_mcp.agent_mcp_config_document()
    assert len(agent_mcp.AGENT_MCP_INSTRUCTIONS) <= 512
    for marker in (
        "Start with agent_discover",
        "agent_open",
        "agent_context",
        "agent_turn",
        "agent_wait",
        "agent_stop",
        "agent_workspace",
        "agent_artifacts",
        "agent_propose_transaction",
        "agent_propose_lifecycle",
        "native review",
        "verified receipt",
        "verified output artifact",
        "agent_control",
        "egress receipt",
        "agent_runtime is opt-in",
        "agent_close retains history",
    ):
        assert marker in agent_mcp.AGENT_MCP_INSTRUCTIONS
    assert document["contract_version"] == AGENT_MCP_CONTRACT_VERSION
    assert document["advertised_tools"] == [
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
    ]
    assert len(document["advertised_tools"]) == 19
    assert document["safeguards"]["exact_project_scope_required"] is True
    assert document["safeguards"]["cross_project_access_available"] is False
    assert document["safeguards"]["generic_invoke_available"] is False
    assert document["safeguards"]["native_approval_inherited"] is False
    assert document["safeguards"]["durable_controller_ownership"] is True
    assert document["safeguards"][
        "same_connection_reconnect_without_resubmission"
    ] is True
    assert document["safeguards"]["owner_only_wait_and_stop"] is True
    assert document["safeguards"][
        "handoff_two_party_revision_bound_same_project"
    ] is True
    assert document["safeguards"]["handoff_inherits_native_approval"] is False
    assert document["safeguards"][
        "native_release_requires_settled_backend_evidence"
    ] is True
    assert document["safeguards"]["delete_available_through_mcp"] is False
    assert document["safeguards"]["destructive_catalog_delete_requires_agent_ui"] is True
    assert document["safeguards"]["dedicated_catalog_tool_strict"] is True
    assert document["safeguards"]["dedicated_history_tool_read_only"] is True
    assert document["safeguards"]["retained_history_excludes_raw_tool_payloads"] is True
    assert document["safeguards"]["dedicated_artifact_tool_metadata_only"] is True
    assert document["safeguards"]["artifact_capture_preview_content_free"] is True
    assert document["safeguards"]["artifact_capture_requires_native_agent_ui"] is True
    assert document["safeguards"]["artifact_bytes_available_through_mcp"] is False
    assert document["safeguards"]["dedicated_context_tool_read_only"] is True
    assert document["safeguards"]["context_snapshot_sequential_non_atomic"] is True
    assert document["safeguards"][
        "context_omits_workspace_paths_instructions_process_ids"
    ] is True
    assert document["safeguards"]["attachment_inline_staging_available"] is True
    assert document["safeguards"]["attachment_bytes_returned_through_mcp"] is False
    assert document["safeguards"]["attachment_path_authority_available"] is False
    assert document["safeguards"]["dedicated_workspace_tool_read_only"] is True
    assert document["safeguards"]["external_write_proposal_native_review_required"] is True
    assert document["safeguards"]["external_write_proposal_direct_apply"] is False
    assert document["safeguards"]["external_write_proposal_auto_retry"] is False
    assert document["safeguards"]["external_proposal_content_retained"] is False
    assert document["safeguards"]["external_verified_write_artifact_projection"] is True
    assert document["safeguards"]["external_verified_write_receipt_retention"] == (
        "saved_chats_only"
    )
    assert document["safeguards"]["verified_file_move_artifact_identity"] == (
        "matching_saved_artifact_only"
    )
    assert agent_mcp.agent_mcp_config_document(transport="stdio")["safeguards"][
        "verified_file_move_artifact_identity"
    ] == "matching_saved_artifact_only"
    assert document["safeguards"]["external_write_transaction_failure_atomic"] is True
    assert document["safeguards"]["external_write_transaction_mixed_create_edit"] is True
    assert document["safeguards"][
        "external_write_transaction_create_rollback_identity_bound"
    ] is True
    assert document["safeguards"][
        "external_lifecycle_proposal_native_review_required"
    ] is True
    assert document["safeguards"]["external_lifecycle_proposal_direct_apply"] is False
    assert document["safeguards"]["external_lifecycle_permanent_delete"] is False
    assert document["safeguards"]["dedicated_resume_restores_authority"] is False
    assert document["safeguards"]["resume_mutation_auto_retry"] is False
    assert document["safeguards"]["dedicated_fork_copies_authority"] is False
    assert document["safeguards"]["fork_ambiguous_retry_same_request_only"] is True
    assert document["safeguards"]["fork_ambiguous_retry_limit"] == 1
    assert document["safeguards"]["dedicated_export_exact_revision"] is True
    assert document["safeguards"]["export_max_events"] == 4_000
    assert document["safeguards"]["export_workspace_path_included"] is False
    assert document["safeguards"]["export_attachment_bytes_included"] is False
    assert document["safeguards"]["export_live_approval_state_included"] is False
    assert document["safeguards"]["export_raw_tool_payloads_included"] is False
    assert document["safeguards"]["dedicated_close_exact_revision"] is True
    assert document["safeguards"]["close_live_session_only"] is True
    assert document["safeguards"]["close_retained_catalog_deleted"] is False
    assert document["safeguards"]["close_mutation_auto_retry"] is False
    assert document["safeguards"]["turn_stop_auto_retry"] is False
    assert document["safeguards"][
        "dedicated_turn_stop_requires_authorization"
    ] is True

    assert main(["agent-mcp-config"]) == 0
    plain = capsys.readouterr()
    assert "[mcp_servers.prompt-enhancer-agent]" in plain.out
    assert 'url = "http://127.0.0.1:8765/mcp/agent"' in plain.out
    assert 'bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"' in plain.out
    assert "tool_timeout_sec = 330" in plain.out
    assert 'default_tools_approval_mode = "prompt"' in plain.out
    assert '"type": "http"' in plain.out
    assert '"Authorization": "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}"' in plain.out
    assert (
        "codex mcp add prompt-enhancer-agent --url "
        "http://127.0.0.1:8765/mcp/agent "
        "--bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN"
    ) in plain.out
    assert (
        "claude mcp add --transport http --scope local "
        "--header 'Authorization: Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' "
        "prompt-enhancer-agent http://127.0.0.1:8765/mcp/agent"
    ) in plain.out
    assert "pemcp1." not in plain.out
    assert "pemcp2." not in plain.out
    assert "prompt-enhancer agent-mcp" not in plain.out
    assert "--acknowledge-model-lifecycle" not in plain.out
    assert str(tmp_path) not in plain.out + plain.err
    assert not (tmp_path / "api.token").exists()

    assert main(["agent-mcp-config", "--with-model-lifecycle"]) == 1
    rejected = capsys.readouterr()
    assert "failed safely" in rejected.err

    assert main(
        [
            "agent-mcp-config",
            "--transport",
            "stdio",
            "--with-model-lifecycle",
        ]
    ) == 0
    lifecycle = capsys.readouterr()
    assert 'command = "prompt-enhancer"' in lifecycle.out
    assert "--acknowledge-model-lifecycle" in lifecycle.out
    assert not (tmp_path / "api.token").exists()


def test_cli_refuses_before_token_read_and_serves_when_acknowledged(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_mcp,
        "create_agent_mcp_surface",
        lambda *_args, **_kwargs: AgentMcpSurface(_FakeController()),
    )

    assert main(["agent-mcp"]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "acknowledge-sensitive-context-egress" in refused.err

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            + "\n"
        ),
    )
    assert main(["agent-mcp", "--acknowledge-sensitive-context-egress"]) == 0
    served = capsys.readouterr()
    reply = json.loads(served.out)
    assert [tool["name"] for tool in reply["result"]["tools"]] == [
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
    ]
    assert served.err == ""


def test_cli_missing_token_fails_closed_without_creating_private_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))

    assert main(["agent-mcp", "--acknowledge-sensitive-context-egress"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": "controller_token_unavailable",
        "http_status": None,
        "retryable": False,
    }
    assert str(tmp_path) not in captured.err
    assert not (tmp_path / "api.token").exists()


def test_cli_lifecycle_flag_changes_only_the_advertised_toolset(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))

    def create_surface(*_args, allow_model_lifecycle: bool, **_kwargs):
        return AgentMcpSurface(
            _FakeController(),
            allow_model_lifecycle=allow_model_lifecycle,
        )

    monkeypatch.setattr(agent_mcp, "create_agent_mcp_surface", create_surface)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            + "\n"
        ),
    )

    assert main(
        [
            "agent-mcp",
            "--acknowledge-sensitive-context-egress",
            "--acknowledge-model-lifecycle",
        ]
    ) == 0
    reply = json.loads(capsys.readouterr().out)
    assert [tool["name"] for tool in reply["result"]["tools"]][-1] == (
        "agent_runtime"
    )
