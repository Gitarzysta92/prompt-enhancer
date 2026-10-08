"""Bounded controller client tests use only synthetic local fixtures."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.application.agent_controller_client import (
    AgentControllerAttachmentStageRequest,
    AgentControllerClient,
    AgentControllerCloseChatRequest,
    AgentControllerCloseChatResult,
    AgentControllerError,
    AgentControllerExportChatRequest,
    AgentControllerExportChatResult,
    AgentControllerForkChatRequest,
    AgentControllerForkChatResult,
    AgentControllerHttpResponse,
    AgentControllerInvokeRequest,
    AgentControllerLifecycleProposalRequest,
    AgentControllerOpenChatRequest,
    AgentControllerResumeChatRequest,
    AgentControllerResumeChatResult,
    AgentControllerRuntimeRequest,
    AgentControllerRuntimeResult,
    AgentControllerStopRequest,
    AgentControllerStopResult,
    AgentControllerTransportUnavailable,
    AgentControllerTurnRequest,
    AgentControllerWaitRequest,
    AgentControllerWriteProposalRequest,
    AgentControllerWriteTransactionProposalRequest,
    MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES,
)
from prompt_enhancer.application.agent_attachment_contracts import (
    StageInlineAgentAttachment,
)
from prompt_enhancer.application.agent_orchestration import (
    agent_orchestration_manifest,
)
from prompt_enhancer.application.local_agent import (
    AgentLifecycleProposal,
    AgentWriteProposal,
    AgentWriteTransactionProposal,
    LocalAgentService,
)
from prompt_enhancer.application.local_agent_transactions import (
    WorkspaceTransactionChangeCommand,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


SESSION_ID = "a" * 32
APPROVAL_ID = "b" * 32
PROJECT_ID = "c" * 32
TOKEN = "example_controller_token_do_not_use_123456789"


def _json_response(payload: Any, status: int = 200) -> AgentControllerHttpResponse:
    return AgentControllerHttpResponse(
        status_code=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload).encode("utf-8"),
    )


def _session(
    *,
    running: bool = False,
    closing: bool = False,
    stopping: bool = False,
    last_seq: int = 0,
    pending_approval_id: str | None = None,
    cleanup_unconfirmed: bool = False,
    project_id: str | None = None,
    recovered: bool = False,
    authority_revalidated: bool = True,
) -> dict[str, Any]:
    return {
        "contract_version": "local-agent.v9",
        "session_id": SESSION_ID,
        "settings": {
            "workspace": "/example/workspace",
            "project_id": project_id,
            "model_alias": "example-model",
            "allow_writes": False,
            "allow_commands": False,
            "allow_web": False,
        },
        "created_at": "2026-01-01T00:00:00Z",
        "running": running,
        "closing": closing,
        "stopping": stopping,
        "cleanup_unconfirmed": cleanup_unconfirmed,
        "last_seq": last_seq,
        "pending_approval_id": pending_approval_id,
        "model_alias": "example-model",
        "turns": 0,
        "history_revision": last_seq,
        "recovered": recovered,
        "authority_revalidated": authority_revalidated,
    }


def _project(project_id: str = PROJECT_ID) -> dict[str, Any]:
    return {
        "contract_version": "agent-catalog.v2",
        "project_id": project_id,
        "name": "Synthetic controller project",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "revision": 1,
        "pinned": False,
        "archived_at": None,
        "session_count": 0,
        "is_default": False,
    }


def _catalog_session(
    *,
    project_id: str = PROJECT_ID,
    session_id: str = SESSION_ID,
    revision: int = 3,
    history_revision: int = 5,
    archived: bool = False,
    retained: bool = True,
    turn_count: int = 1,
) -> dict[str, Any]:
    return {
        "contract_version": "agent-catalog.v2",
        "session_id": session_id,
        "project_id": project_id,
        "title": "Synthetic retained chat",
        "workspace": "/example/workspace",
        "model_alias": "example-model",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "last_opened_at": "2026-01-01T00:00:00Z",
        "revision": revision,
        "pinned": False,
        "archived_at": "2026-01-02T00:00:00Z" if archived else None,
        "history_state": "durable_local" if retained else "memory_only",
        "retention_policy": "local_history" if retained else "metadata_only",
        "history_revision": history_revision if retained else 0,
        "last_event_seq": history_revision if retained else 0,
        "turn_count": turn_count if retained else 0,
        "conversation_available": retained,
        "lineage": None,
    }


def _history_export(
    *,
    project_id: str = PROJECT_ID,
    session_id: str = SESSION_ID,
    title: str = "Synthetic retained chat",
    workspace: str = "/example/workspace",
    model_alias: str | None = "example-model",
    history_revision: int = 5,
    turn_count: int = 0,
) -> dict[str, Any]:
    return {
        "contract_version": "agent-history.v1",
        "exported_at": "2026-01-04T00:00:00Z",
        "project_id": project_id,
        "session_id": session_id,
        "title": title,
        "workspace": workspace,
        "model_alias": model_alias,
        "history_revision": history_revision,
        "turn_count": turn_count,
        "interrupted": history_revision > 0,
        "events": [
            {
                "seq": sequence,
                "at": "2026-01-01T00:00:00Z",
                "kind": "status",
                "text": f"Synthetic retained status {sequence}.",
            }
            for sequence in range(1, history_revision + 1)
        ],
    }


def _fork_receipt(
    *,
    source_project_id: str = PROJECT_ID,
    source_session_id: str = SESSION_ID,
    request_id: str = "d" * 32,
    destination_project_id: str | None = None,
    child_session_id: str = "e" * 32,
    source_catalog_revision: int = 3,
    source_history_revision: int = 5,
    branch_event_seq: int = 4,
    idempotent_replay: bool = False,
) -> dict[str, Any]:
    destination = destination_project_id or source_project_id
    created_at = "2026-01-03T00:00:00Z"
    return {
        "contract_version": "agent-session-fork.v1",
        "request_id": request_id,
        "idempotent_replay": idempotent_replay,
        "session": {
            "contract_version": "agent-catalog.v2",
            "session_id": child_session_id,
            "project_id": destination,
            "title": "Synthetic controller branch",
            "workspace": "/example/workspace",
            "model_alias": "example-model",
            "created_at": created_at,
            "updated_at": created_at,
            "last_opened_at": created_at,
            "revision": 1,
            "pinned": False,
            "archived_at": None,
            "history_state": "durable_local",
            "retention_policy": "local_history",
            "history_revision": branch_event_seq,
            "last_event_seq": branch_event_seq,
            "turn_count": 1 if branch_event_seq else 0,
            "conversation_available": True,
            "lineage": {
                "contract_version": "agent-session-lineage.v1",
                "source_project_id": source_project_id,
                "source_session_id": source_session_id,
                "source_catalog_revision": source_catalog_revision,
                "source_history_revision": source_history_revision,
                "branch_event_seq": branch_event_seq,
                "copied_event_count": branch_event_seq,
                "copied_turn_count": 1 if branch_event_seq else 0,
                "copied_attachment_count": 0,
                "created_at": created_at,
            },
        },
        "source_tail_omitted": branch_event_seq < source_history_revision,
        "approvals_copied": False,
        "mutation_authority_copied": False,
        "pending_tool_state_copied": False,
        "staged_attachments_copied": False,
        "artifacts_copied": False,
    }


def _runtime_idle(*, revision: int = 1) -> dict[str, Any]:
    return {
        "contract_version": "local-runtime-coordinator.v2",
        "revision": revision,
        "state": "idle",
        "requested": None,
        "served": None,
        "cleanup": {
            "state": "not_required",
            "process_exit_confirmed": True,
        },
        "capabilities": {"state": "not_probed"},
        "context": {"state": "unknown"},
        "active_requests": 0,
        "last_error_code": None,
    }


def _runtime_ready(
    *,
    alias: str = "example-model",
    revision: int = 2,
    device: str = "gpu",
    gpu_layers: int = 40,
    context_size: int = 8_192,
) -> dict[str, Any]:
    selection = {
        "alias": alias,
        "device": device,
        "gpu_layers": gpu_layers,
        "context_size": context_size,
    }
    return {
        "contract_version": "local-runtime-coordinator.v2",
        "revision": revision,
        "state": "ready",
        "requested": selection,
        "served": {
            **selection,
            "started_at": "2026-01-01T00:00:00Z",
            "pid": 4242,
        },
        "cleanup": {
            "state": "not_required",
            "process_exit_confirmed": True,
        },
        "capabilities": {
            "state": "verified",
            "text": True,
            "tools": True,
        },
        "context": {
            "state": "unknown",
            "limit_tokens": context_size,
            "reason_code": "no_request_measured",
        },
        "active_requests": 0,
        "last_error_code": None,
    }


def _runtime_cleanup_unknown(*, revision: int = 3) -> dict[str, Any]:
    return {
        "contract_version": "local-runtime-coordinator.v2",
        "revision": revision,
        "state": "cleanup_unknown",
        "requested": None,
        "served": None,
        "cleanup": {
            "state": "unknown",
            "process_exit_confirmed": False,
        },
        "capabilities": {"state": "not_probed"},
        "context": {"state": "unknown"},
        "active_requests": 0,
        "last_error_code": "runtime_cleanup_unconfirmed",
    }


def _event(seq: int, kind: str, text: str | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "seq": seq,
        "at": "2026-01-01T00:00:00Z",
        "kind": kind,
    }
    if kind == "done":
        return event
    if kind == "approval_resolved":
        event.update(
            text=text,
            tool="write_file",
            approval_id=APPROVAL_ID,
            ok=True,
        )
        return event
    event["text"] = text
    return event


def _page(
    events: list[dict[str, Any]],
    *,
    running: bool,
    last_seq: int,
    pending_approval_id: str | None = None,
    first_seq: int = 0,
    cleanup_unconfirmed: bool = False,
) -> dict[str, Any]:
    return {
        "contract_version": "local-agent.v9",
        "session_id": SESSION_ID,
        "events": events,
        "running": running,
        "closing": False,
        "stopping": False,
        "cleanup_unconfirmed": cleanup_unconfirmed,
        "pending_approval_id": pending_approval_id,
        "last_seq": last_seq,
        "first_seq": first_seq,
    }


class _ScriptedTransport:
    def __init__(
        self,
        handler: Callable[
            [str, str, Mapping[str, str | int | bool] | None, Any | None],
            AgentControllerHttpResponse,
        ],
    ) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, Mapping[str, str | int | bool] | None, Any | None]] = []
        self.request_limits: list[int | None] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | int | bool] | None = None,
        json_body: Any | None = None,
        max_request_bytes: int | None = None,
    ) -> AgentControllerHttpResponse:
        self.calls.append((method, path, query, json_body))
        self.request_limits.append(max_request_bytes)
        return self.handler(method, path, query, json_body)


def _manifest_response() -> AgentControllerHttpResponse:
    return _json_response(agent_orchestration_manifest().model_dump(mode="json"))


def test_discovery_accepts_only_the_complete_v22_native_boundary() -> None:
    valid = _ScriptedTransport(lambda *_args: _manifest_response())
    manifest = AgentControllerClient(valid).discover()
    assert manifest.contract_version == "local-agent-orchestration.v22"
    assert len(manifest.endpoints) == 77

    downgraded = manifest.model_dump(mode="json")
    downgraded["endpoints"] = downgraded["endpoints"][:-1]
    invalid = _ScriptedTransport(lambda *_args: _json_response(downgraded))
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid).discover()
    assert captured.value.code == "controller_contract_invalid"

    relabelled = manifest.model_dump(mode="json")
    for endpoint in relabelled["endpoints"]:
        if endpoint["operation"] == "apply_file_create":
            endpoint["access"] = "token_authenticated"
    invalid_native = _ScriptedTransport(lambda *_args: _json_response(relabelled))
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid_native).discover()
    assert captured.value.code == "controller_contract_invalid"


def test_specialized_controller_stages_inline_attachment_once_and_revalidates_response() -> None:
    raw = b"synthetic-inline-media"
    digest = hashlib.sha256(raw).hexdigest()
    declared = StageInlineAgentAttachment(
        display_name="synthetic.png",
        media_type="image/png",
        byte_size=len(raw),
        sha256=digest,
        data_base64=base64.b64encode(raw).decode("ascii"),
    )
    response = {
        "contract_version": "agent-attachment.v1",
        "attachment_id": "d" * 32,
        "session_id": SESSION_ID,
        "model_alias": "example-model",
        "capability_probe_version": "runtime-capabilities.v1",
        "kind": "image",
        "media_type": "image/png",
        "display_name": declared.display_name,
        "source": "external_agent",
        "state": "staged",
        "retention": "memory_only",
        "created_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-01T01:00:00Z",
        "attached_event_seq": None,
        "sha256": digest,
        "byte_size": len(raw),
        "width": 1,
        "height": 1,
        "duration_ms": None,
        "sample_rate_hz": None,
        "channels": None,
        "context_tokens": None,
        "context_cost_source": "runtime_unreported",
    }

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert method == "POST"
        assert path == (
            f"/v1/agent/projects/{PROJECT_ID}/sessions/{SESSION_ID}/"
            "attachments/stage-inline"
        )
        assert body == declared.model_dump(mode="json")
        assert "path" not in body and "url" not in body
        return _json_response(response, 201)

    transport = _ScriptedTransport(handler)
    client = AgentControllerClient(transport)
    staged = client.stage_attachment(
        AgentControllerAttachmentStageRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            attachment=declared,
        )
    )
    assert staged.attachment_id == "d" * 32
    assert staged.source == "external_agent"
    assert transport.request_limits == [None, MAX_CONTROLLER_ATTACHMENT_REQUEST_BYTES]

    invalid_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response({**response, "session_id": "e" * 32}, 201)
        )
    )
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid_transport).stage_attachment(
            AgentControllerAttachmentStageRequest(
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                attachment=declared,
            )
        )
    assert captured.value.code == "controller_attachment_response_invalid"

    generic = AgentControllerClient(_ScriptedTransport(lambda *_args: _manifest_response()))
    with pytest.raises(AgentControllerError) as captured:
        generic.invoke(
            AgentControllerInvokeRequest(
                operation="stage_attachment_inline",
                path_parameters={"project_id": PROJECT_ID, "session_id": SESSION_ID},
                body=declared.model_dump(mode="json"),
            )
        )
    assert captured.value.code == "controller_specialized_operation_required"


def test_specialized_controller_proposes_write_once_and_revalidates_receipt() -> None:
    proposal = AgentWriteProposal(
        request_id="d" * 32,
        operation="create",
        path="synthetic-note.md",
        content="# Synthetic note\n",
    )
    response = {
        "contract_version": "agent-write-proposal.v1",
        "request_id": proposal.request_id,
        "session_id": SESSION_ID,
        "operation": proposal.operation,
        "path": proposal.path,
        "proposed_revision": hashlib.sha256(
            proposal.content.encode("utf-8")
        ).hexdigest(),
        "state": "pending_native_review",
        "approval_id": "e" * 32,
        "cursor": 2,
        "write_receipt": None,
    }

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert method == "POST"
        assert path == f"/v1/agent/sessions/{SESSION_ID}/write-proposals"
        assert body == proposal.model_dump(mode="json")
        return _json_response(response, 202)

    transport = _ScriptedTransport(handler)
    receipt = AgentControllerClient(transport).propose_write(
        AgentControllerWriteProposalRequest(
            session_id=SESSION_ID,
            proposal=proposal,
        )
    )
    assert receipt.state == "pending_native_review"
    assert receipt.approval_id == "e" * 32
    assert [call[1] for call in transport.calls].count(
        f"/v1/agent/sessions/{SESSION_ID}/write-proposals"
    ) == 1

    invalid_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response({**response, "request_id": "f" * 32}, 202)
        )
    )
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid_transport).propose_write(
            AgentControllerWriteProposalRequest(
                session_id=SESSION_ID,
                proposal=proposal,
            )
        )
    assert captured.value.code == "controller_write_proposal_response_invalid"

    generic = AgentControllerClient(
        _ScriptedTransport(lambda *_args: _manifest_response())
    )
    with pytest.raises(AgentControllerError) as captured:
        generic.invoke(
            AgentControllerInvokeRequest(
                operation="propose_file_write",
                path_parameters={"session_id": SESSION_ID},
                body=proposal.model_dump(mode="json"),
            )
        )
    assert captured.value.code == "controller_specialized_operation_required"


def test_specialized_controller_proposes_transaction_once_and_revalidates_files() -> None:
    proposal = AgentWriteTransactionProposal(
        request_id="7" * 32,
        changes=(
            WorkspaceTransactionChangeCommand(
                path="alpha.txt",
                content="alpha after\n",
                expected_revision="1" * 64,
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                path="beta.txt",
                content="beta after\n",
                expected_revision="2" * 64,
                line_ending="lf",
            ),
        ),
    )
    files = [
        {
            "operation": change.operation,
            "path": change.path,
            "proposed_revision": hashlib.sha256(
                change.content.encode("utf-8")
            ).hexdigest(),
        }
        for change in proposal.changes
    ]
    response = {
        "contract_version": "agent-write-transaction-proposal.v2",
        "request_id": proposal.request_id,
        "session_id": SESSION_ID,
        "state": "pending_native_review",
        "file_count": 2,
        "files": files,
        "approval_id": "8" * 32,
        "cursor": 3,
        "transaction_result": None,
    }

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert method == "POST"
        assert path == (
            f"/v1/agent/sessions/{SESSION_ID}/write-transaction-proposals"
        )
        assert body == proposal.model_dump(mode="json")
        return _json_response(response, 202)

    transport = _ScriptedTransport(handler)
    receipt = AgentControllerClient(transport).propose_write_transaction(
        AgentControllerWriteTransactionProposalRequest(
            session_id=SESSION_ID,
            proposal=proposal,
        )
    )
    assert receipt.state == "pending_native_review"
    assert [item.path for item in receipt.files] == ["alpha.txt", "beta.txt"]
    assert [call[1] for call in transport.calls].count(
        f"/v1/agent/sessions/{SESSION_ID}/write-transaction-proposals"
    ) == 1

    invalid = {
        **response,
        "files": [{**files[0], "proposed_revision": "f" * 64}, files[1]],
    }
    invalid_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(invalid, 202)
        )
    )
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid_transport).propose_write_transaction(
            AgentControllerWriteTransactionProposalRequest(
                session_id=SESSION_ID,
                proposal=proposal,
            )
        )
    assert (
        captured.value.code
        == "controller_write_transaction_proposal_response_invalid"
    )

    generic = AgentControllerClient(
        _ScriptedTransport(lambda *_args: _manifest_response())
    )
    with pytest.raises(AgentControllerError) as captured:
        generic.invoke(
            AgentControllerInvokeRequest(
                operation="propose_file_transaction",
                path_parameters={"session_id": SESSION_ID},
                body=proposal.model_dump(mode="json"),
            )
        )
    assert captured.value.code == "controller_specialized_operation_required"


def test_specialized_controller_proposes_lifecycle_once_and_revalidates_scope() -> None:
    proposal = AgentLifecycleProposal(
        request_id="9" * 32,
        operation="move_file",
        source_path="source.txt",
        target_path="archive/source.txt",
        expected_revision="4" * 64,
    )
    response = {
        "contract_version": "agent-lifecycle-proposal.v1",
        "request_id": proposal.request_id,
        "session_id": SESSION_ID,
        "operation": proposal.operation,
        "path": None,
        "source_path": proposal.source_path,
        "target_path": proposal.target_path,
        "expected_revision": proposal.expected_revision,
        "state": "pending_native_review",
        "approval_id": "8" * 32,
        "cursor": 4,
        "verified": False,
        "permanent": None,
        "recovery": None,
    }

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert method == "POST"
        assert path == f"/v1/agent/sessions/{SESSION_ID}/lifecycle-proposals"
        assert body == proposal.model_dump(mode="json")
        return _json_response(response, 202)

    transport = _ScriptedTransport(handler)
    receipt = AgentControllerClient(transport).propose_lifecycle(
        AgentControllerLifecycleProposalRequest(
            session_id=SESSION_ID,
            proposal=proposal,
        )
    )
    assert receipt.state == "pending_native_review"
    assert receipt.verified is False
    assert [call[1] for call in transport.calls].count(
        f"/v1/agent/sessions/{SESSION_ID}/lifecycle-proposals"
    ) == 1

    invalid_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(
                {**response, "target_path": "different.txt"},
                202,
            )
        )
    )
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(invalid_transport).propose_lifecycle(
            AgentControllerLifecycleProposalRequest(
                session_id=SESSION_ID,
                proposal=proposal,
            )
        )
    assert captured.value.code == "controller_lifecycle_proposal_response_invalid"

    generic = AgentControllerClient(
        _ScriptedTransport(lambda *_args: _manifest_response())
    )
    with pytest.raises(AgentControllerError) as captured:
        generic.invoke(
            AgentControllerInvokeRequest(
                operation="propose_workspace_lifecycle",
                path_parameters={"session_id": SESSION_ID},
                body=proposal.model_dump(mode="json"),
            )
        )
    assert captured.value.code == "controller_specialized_operation_required"


def test_manifest_invocation_resolves_json_routes_and_refuses_native_or_binary() -> None:
    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        body: Any | None,
    ) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert (method, path, query, body) == (
            "POST",
            "/v1/agent/projects",
            {},
            {"name": "Synthetic project"},
        )
        return _json_response(
            {"project_id": "example-project", "name": "Synthetic project"},
            201,
        )

    transport = _ScriptedTransport(handler)
    client = AgentControllerClient(transport)
    result = client.invoke(
        AgentControllerInvokeRequest(
            operation="create_project",
            body={"name": "Synthetic project"},
        )
    )
    assert result.status_code == 201
    assert result.response["name"] == "Synthetic project"

    with pytest.raises(AgentControllerError) as protected:
        client.invoke(AgentControllerInvokeRequest(operation="apply_file_create"))
    assert protected.value.code == "controller_native_review_required"

    with pytest.raises(AgentControllerError) as binary:
        client.invoke(
            AgentControllerInvokeRequest(
                operation="read_attachment_content",
                path_parameters={
                    "session_id": SESSION_ID,
                    "attachment_id": "c" * 32,
                },
            )
        )
    assert binary.value.code == "controller_response_mode_unsupported"
    with pytest.raises(AgentControllerError) as specialized:
        client.invoke(
            AgentControllerInvokeRequest(
                operation="switch_local_runtime",
                body={"alias": "example-model", "expected_revision": 0},
            )
        )
    assert specialized.value.code == "controller_specialized_operation_required"
    assert len(transport.calls) == 2


def test_generic_controller_requires_and_forwards_exact_delete_revisions() -> None:
    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        body: Any | None,
    ) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert (method, path, query, body) == (
            "DELETE",
            f"/v1/agent/catalog/sessions/{SESSION_ID}",
            {
                "expected_catalog_revision": 4,
                "expected_history_revision": 9,
            },
            None,
        )
        return AgentControllerHttpResponse(status_code=204, content_type=None, body=b"")

    transport = _ScriptedTransport(handler)
    client = AgentControllerClient(transport)
    with pytest.raises(AgentControllerError) as incomplete:
        client.invoke(
            AgentControllerInvokeRequest(
                operation="delete_catalog_session",
                path_parameters={"session_id": SESSION_ID},
                query={"expected_catalog_revision": 4},
            )
        )
    assert incomplete.value.code == "controller_query_parameters_invalid"
    result = client.invoke(
        AgentControllerInvokeRequest(
            operation="delete_catalog_session",
            path_parameters={"session_id": SESSION_ID},
            query={
                "expected_catalog_revision": 4,
                "expected_history_revision": 9,
            },
        )
    )
    assert result.status_code == 204
    assert result.response is None


def test_runtime_request_rejects_placement_on_stop() -> None:
    with pytest.raises(ValueError):
        AgentControllerRuntimeRequest(
            desired_state="stopped",
            alias="example-model",
            device="cpu",
        )


def test_runtime_result_rejects_false_terminal_evidence() -> None:
    with pytest.raises(ValueError):
        AgentControllerRuntimeResult(
            desired_state="ready",
            alias="example-model",
            outcome="ready",
            mutation_attempted=True,
            status=_runtime_idle(),
        )
    with pytest.raises(ValueError):
        AgentControllerRuntimeResult(
            desired_state="stopped",
            alias="example-model",
            outcome="stopped",
            mutation_attempted=True,
            status=_runtime_cleanup_unknown(),
        )


def test_runtime_ready_preflight_is_idempotent_without_mutation() -> None:
    transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(_runtime_ready())
        )
    )
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="ready",
            alias="example-model",
            device="gpu",
            gpu_layers=40,
            context_size=8_192,
        )
    )

    assert result.outcome == "ready"
    assert result.mutation_attempted is False
    assert [call[:2] for call in transport.calls] == [
        ("GET", "/v1/agent/orchestration"),
        ("GET", "/v1/local-models/runtime"),
    ]


def test_runtime_switch_is_revision_bound_and_validates_exact_placement() -> None:
    def handler(method, path, _query, body):
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == "/v1/local-models/runtime":
            return _json_response(_runtime_idle(revision=7))
        if method == "POST" and path == "/v1/local-models/runtime/switch":
            assert body == {
                "device": "split",
                "gpu_layers": 24,
                "context_size": 16_384,
                "remember": False,
                "fast_attention": True,
                "tool_calling": True,
                "alias": "example-model",
                "expected_revision": 7,
            }
            return _json_response(
                _runtime_ready(
                    revision=8,
                    device="split",
                    gpu_layers=24,
                    context_size=16_384,
                )
            )
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="ready",
            alias="example-model",
            device="split",
            gpu_layers=24,
            context_size=16_384,
        )
    )

    assert result.outcome == "ready"
    assert result.mutation_attempted is True
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime/switch"
    ) == 1


def test_runtime_switch_reconciles_one_ambiguous_response_without_retry() -> None:
    runtime_reads = 0

    def handler(method, path, _query, _body):
        nonlocal runtime_reads
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == "/v1/local-models/runtime":
            runtime_reads += 1
            return _json_response(
                _runtime_idle(revision=4)
                if runtime_reads == 1
                else _runtime_ready(revision=5, device="cpu", gpu_layers=0)
            )
        if method == "POST" and path == "/v1/local-models/runtime/switch":
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="ready",
            alias="example-model",
            device="cpu",
            gpu_layers=0,
        )
    )

    assert result.outcome == "ready_reconciled"
    assert result.mutation_attempted is True
    assert runtime_reads == 2
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime/switch"
    ) == 1


def test_runtime_switch_reports_uncertainty_when_reconciliation_is_unavailable() -> None:
    runtime_reads = 0

    def handler(method, path, _query, _body):
        nonlocal runtime_reads
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == "/v1/local-models/runtime":
            runtime_reads += 1
            if runtime_reads == 1:
                return _json_response(_runtime_idle(revision=11))
            raise AgentControllerTransportUnavailable()
        if method == "POST" and path == "/v1/local-models/runtime/switch":
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="ready",
            alias="example-model",
        )
    )

    assert result.outcome == "activation_uncertain"
    assert result.status is None
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime/switch"
    ) == 1


def test_runtime_switch_does_not_retry_or_reconcile_a_trustworthy_rejection() -> None:
    def handler(method, path, _query, _body):
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == "/v1/local-models/runtime":
            return _json_response(_runtime_idle(revision=21))
        if method == "POST" and path == "/v1/local-models/runtime/switch":
            return _json_response(
                {"detail": {"code": "runtime_revision_conflict"}},
                409,
            )
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as rejected:
        AgentControllerClient(transport).coordinate_runtime(
            AgentControllerRuntimeRequest(
                desired_state="ready",
                alias="example-model",
            )
        )
    assert rejected.value.http_status == 409
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime"
    ) == 1
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime/switch"
    ) == 1


def test_runtime_cleanup_quarantine_blocks_mutation() -> None:
    transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(_runtime_cleanup_unknown())
        )
    )
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="ready",
            alias="example-model",
        )
    )

    assert result.outcome == "cleanup_unconfirmed"
    assert result.mutation_attempted is False
    assert all(call[0] != "POST" for call in transport.calls)


def test_runtime_stop_is_alias_safe_and_revision_bound() -> None:
    wrong_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(_runtime_ready(alias="other-model"))
        )
    )
    with pytest.raises(AgentControllerError) as mismatch:
        AgentControllerClient(wrong_transport).coordinate_runtime(
            AgentControllerRuntimeRequest(
                desired_state="stopped",
                alias="example-model",
            )
        )
    assert mismatch.value.code == "controller_runtime_alias_mismatch"
    assert all(call[0] != "POST" for call in wrong_transport.calls)

    def handler(method, path, _query, body):
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == "/v1/local-models/runtime":
            return _json_response(_runtime_ready(revision=12))
        if method == "POST" and path == "/v1/local-models/runtime/stop":
            assert body == {"alias": "example-model", "expected_revision": 12}
            return _json_response(_runtime_idle(revision=13))
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).coordinate_runtime(
        AgentControllerRuntimeRequest(
            desired_state="stopped",
            alias="example-model",
        )
    )
    assert result.outcome == "stopped"
    assert result.mutation_attempted is True
    assert [call[1] for call in transport.calls].count(
        "/v1/local-models/runtime/stop"
    ) == 1


def test_manifest_invocation_routes_revision_bound_fork_without_native_authority() -> None:
    project_id = "c" * 32
    request_id = "d" * 32
    body = {
        "request_id": request_id,
        "expected_catalog_revision": 2,
        "expected_history_revision": 7,
        "destination_project_id": None,
        "through_event_seq": 6,
        "title": "Synthetic controller branch",
    }

    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        json_body: Any | None,
    ) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert (method, path, query, json_body) == (
            "POST",
            (
                f"/v1/agent/projects/{project_id}/sessions/"
                f"{SESSION_ID}/forks"
            ),
            {},
            body,
        )
        return _json_response(
            {
                "contract_version": "agent-session-fork.v1",
                "request_id": request_id,
                "idempotent_replay": False,
                "source_tail_omitted": True,
                "approvals_copied": False,
                "mutation_authority_copied": False,
                "pending_tool_state_copied": False,
                "staged_attachments_copied": False,
                "artifacts_copied": False,
                "session": {"session_id": "e" * 32},
            }
        )

    transport = _ScriptedTransport(handler)
    response = AgentControllerClient(transport).invoke(
        AgentControllerInvokeRequest(
            operation="fork_retained_session",
            path_parameters={
                "project_id": project_id,
                "session_id": SESSION_ID,
            },
            body=body,
        )
    ).response
    assert response["request_id"] == request_id
    assert response["approvals_copied"] is False
    assert response["mutation_authority_copied"] is False
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "payload",
    (
        {"settings": {"workspace": "/example/workspace"}},
        {
            "project_id": PROJECT_ID,
            "project_name": "Synthetic controller project",
            "settings": {"workspace": "/example/workspace"},
        },
        {
            "project_id": PROJECT_ID,
            "settings": {
                "workspace": "/example/workspace",
                "project_id": PROJECT_ID,
            },
        },
    ),
)
def test_open_chat_request_requires_one_unambiguous_project_source(payload) -> None:
    with pytest.raises(ValueError):
        AgentControllerOpenChatRequest.model_validate(payload)


def test_open_chat_creates_one_project_and_one_validated_live_session() -> None:
    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            assert body == {"name": "Synthetic controller project"}
            return _json_response(_project(), 201)
        if method == "POST" and path == "/v1/agent/sessions":
            assert body["project_id"] == PROJECT_ID
            assert body["workspace"] == "/example/workspace"
            assert body["retention_policy"] == "local_history"
            return _json_response(_session(project_id=PROJECT_ID), 201)
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).open_chat(
        AgentControllerOpenChatRequest(
            project_name="  Synthetic   controller project  ",
            settings={
                "workspace": "/example/workspace",
                "model_alias": "example-model",
                "retention_policy": "local_history",
            },
        )
    )

    assert result.outcome == "ready"
    assert result.project_created is True
    assert result.project.project_id == PROJECT_ID
    assert result.session is not None
    assert result.session.settings.project_id == PROJECT_ID
    assert [call[:2] for call in transport.calls] == [
        ("GET", "/v1/agent/orchestration"),
        ("POST", "/v1/agent/projects"),
        ("POST", "/v1/agent/sessions"),
    ]


def test_open_chat_uses_one_exact_existing_project_without_creating_another() -> None:
    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == f"/v1/agent/projects/{PROJECT_ID}":
            return _json_response(_project())
        if method == "POST" and path == "/v1/agent/sessions":
            assert body["project_id"] == PROJECT_ID
            return _json_response(_session(project_id=PROJECT_ID), 201)
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).open_chat(
        AgentControllerOpenChatRequest(
            project_id=PROJECT_ID,
            settings={"workspace": "/example/workspace"},
        )
    )

    assert result.outcome == "ready"
    assert result.project_created is False
    assert all(call[1] != "/v1/agent/projects" for call in transport.calls)


def test_open_chat_never_retries_an_ambiguous_session_creation() -> None:
    def handler(method: str, path: str, _query, _body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            return _json_response(_project(), 201)
        if method == "POST" and path == "/v1/agent/sessions":
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).open_chat(
        AgentControllerOpenChatRequest(
            project_name="Synthetic controller project",
            settings={"workspace": "/example/workspace"},
        )
    )

    assert result.outcome == "session_creation_uncertain"
    assert result.project.project_id == PROJECT_ID
    assert result.session is None
    assert [call[1] for call in transport.calls].count("/v1/agent/sessions") == 1
    assert all(call[0] != "DELETE" for call in transport.calls)


def test_open_chat_treats_a_mismatched_created_session_as_uncertain() -> None:
    def handler(method: str, path: str, _query, _body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            return _json_response(_project(), 201)
        if method == "POST" and path == "/v1/agent/sessions":
            return _json_response(_session(project_id="d" * 32), 201)
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).open_chat(
        AgentControllerOpenChatRequest(
            project_name="Synthetic controller project",
            settings={"workspace": "/example/workspace"},
        )
    )

    assert result.outcome == "session_creation_uncertain"
    assert result.session is None
    assert all(call[0] != "DELETE" for call in transport.calls)


def test_open_chat_does_not_retry_an_ambiguous_project_creation() -> None:
    def handler(method: str, path: str, _query, _body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as caught:
        AgentControllerClient(transport).open_chat(
            AgentControllerOpenChatRequest(
                project_name="Synthetic controller project",
                settings={"workspace": "/example/workspace"},
            )
        )

    assert caught.value.code == "controller_project_creation_uncertain"
    assert [call[1] for call in transport.calls].count("/v1/agent/projects") == 1


def test_open_chat_rolls_back_a_new_empty_project_after_a_trustworthy_rejection() -> None:
    def handler(method: str, path: str, _query, _body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            return _json_response(_project(), 201)
        if method == "POST" and path == "/v1/agent/sessions":
            return _json_response({"detail": {"code": "model_not_ready"}}, 409)
        if method == "DELETE" and path == f"/v1/agent/projects/{PROJECT_ID}":
            return AgentControllerHttpResponse(204, None, b"")
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as caught:
        AgentControllerClient(transport).open_chat(
            AgentControllerOpenChatRequest(
                project_name="Synthetic controller project",
                settings={"workspace": "/example/workspace"},
            )
        )

    assert caught.value.http_status == 409
    assert [call[:2] for call in transport.calls][-1] == (
        "DELETE",
        f"/v1/agent/projects/{PROJECT_ID}",
    )


def test_open_chat_reports_unconfirmed_empty_project_cleanup() -> None:
    def handler(method: str, path: str, _query, _body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "POST" and path == "/v1/agent/projects":
            return _json_response(_project(), 201)
        if method == "POST" and path == "/v1/agent/sessions":
            return _json_response({"detail": {"code": "model_not_ready"}}, 409)
        if method == "DELETE" and path == f"/v1/agent/projects/{PROJECT_ID}":
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    result = AgentControllerClient(_ScriptedTransport(handler)).open_chat(
        AgentControllerOpenChatRequest(
            project_name="Synthetic controller project",
            settings={"workspace": "/example/workspace"},
        )
    )

    assert result.outcome == "project_cleanup_unconfirmed"
    assert result.project_created is True
    assert result.session is None


def test_resume_chat_is_revision_bound_and_restores_no_authority() -> None:
    post_calls = 0

    def handler(
        method: str,
        path: str,
        _query: Mapping[str, str | int | bool] | None,
        body: Any | None,
    ) -> AgentControllerHttpResponse:
        nonlocal post_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            return _json_response({"detail": "synthetic not live"}, 404)
        if method == "POST" and path.endswith("/resume"):
            post_calls += 1
            assert body == {
                "expected_catalog_revision": 3,
                "expected_history_revision": 5,
            }
            return _json_response(
                _session(
                    project_id=PROJECT_ID,
                    last_seq=5,
                    recovered=True,
                    authority_revalidated=False,
                )
            )
        raise AssertionError((method, path))

    result = AgentControllerClient(_ScriptedTransport(handler)).resume_chat(
        AgentControllerResumeChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert isinstance(result, AgentControllerResumeChatResult)
    assert result.contract_version == "prompt-enhancer-agent-controller-resume.v1"
    assert result.outcome == "resumed"
    assert result.mutation_state == "accepted"
    assert result.session is not None
    assert result.session.recovered is True
    assert result.session.authority_revalidated is False
    assert result.session.settings.allow_writes is False
    assert result.session.settings.allow_commands is False
    assert result.session.settings.allow_web is False
    assert post_calls == 1


def test_resume_chat_observes_an_existing_live_session_without_mutation() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            return _json_response(_session(project_id=PROJECT_ID, last_seq=5))
        raise AssertionError("an already-live chat must not receive Resume")

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).resume_chat(
        AgentControllerResumeChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "already_live"
    assert result.mutation_state == "not_attempted"
    assert result.session is not None
    assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_ambiguous_resume_is_reconciled_once_without_repeating_mutation() -> None:
    live_reads = 0
    post_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal live_reads, post_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            live_reads += 1
            if live_reads == 1:
                return _json_response({"detail": "synthetic not live"}, 404)
            return _json_response(
                _session(
                    project_id=PROJECT_ID,
                    last_seq=5,
                    recovered=True,
                    authority_revalidated=False,
                )
            )
        if method == "POST" and path.endswith("/resume"):
            post_calls += 1
            raise AgentControllerTransportUnavailable()
        raise AssertionError(path)

    result = AgentControllerClient(_ScriptedTransport(handler)).resume_chat(
        AgentControllerResumeChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "resumed_reconciled"
    assert result.mutation_state == "reconciled"
    assert post_calls == 1
    assert live_reads == 2


def test_unreconciled_or_authority_unsafe_resume_stays_uncertain() -> None:
    for resumed_payload in (
        None,
        _session(
            project_id=PROJECT_ID,
            last_seq=5,
            recovered=True,
            authority_revalidated=True,
        ),
    ):
        live_reads = 0
        post_calls = 0

        def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
            nonlocal live_reads, post_calls
            if path == "/v1/agent/orchestration":
                return _manifest_response()
            if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
                return _json_response(_catalog_session())
            if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
                live_reads += 1
                return _json_response({"detail": "synthetic not live"}, 404)
            if method == "POST" and path.endswith("/resume"):
                post_calls += 1
                if resumed_payload is None:
                    raise AgentControllerTransportUnavailable()
                return _json_response(resumed_payload)
            raise AssertionError(path)

        result = AgentControllerClient(_ScriptedTransport(handler)).resume_chat(
            AgentControllerResumeChatRequest(
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                expected_catalog_revision=3,
                expected_history_revision=5,
            )
        )
        assert result.outcome == "resume_uncertain"
        assert result.mutation_state == "uncertain"
        assert result.session is None
        assert post_calls == 1
        assert live_reads == 2


def test_resume_chat_rejects_stale_or_unavailable_catalog_before_mutation() -> None:
    cases = (
        (_catalog_session(revision=4), 5, "controller_resume_revision_mismatch"),
        (_catalog_session(archived=True), 5, "controller_resume_unavailable"),
        (_catalog_session(retained=False), 0, "controller_resume_unavailable"),
        (
            _catalog_session(project_id="d" * 32),
            5,
            "controller_catalog_response_invalid",
        ),
    )
    for catalog_payload, expected_history_revision, expected_code in cases:
        def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
            if path == "/v1/agent/orchestration":
                return _manifest_response()
            if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
                return _json_response(catalog_payload)
            raise AssertionError("invalid resume preflight must not reach live or POST")

        transport = _ScriptedTransport(handler)
        with pytest.raises(AgentControllerError) as captured:
            AgentControllerClient(transport).resume_chat(
                AgentControllerResumeChatRequest(
                    project_id=PROJECT_ID,
                    session_id=SESSION_ID,
                    expected_catalog_revision=3,
                    expected_history_revision=expected_history_revision,
                )
            )
        assert captured.value.code == expected_code
        assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_fork_chat_validates_lineage_and_copies_no_authority() -> None:
    posted: list[dict[str, Any]] = []

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert (method, path) == (
            "POST",
            f"/v1/agent/projects/{PROJECT_ID}/sessions/{SESSION_ID}/forks",
        )
        posted.append(body)
        return _json_response(_fork_receipt())

    result = AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
        AgentControllerForkChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            request_id="d" * 32,
            expected_catalog_revision=3,
            expected_history_revision=5,
            through_event_seq=4,
            title="  Synthetic   controller branch  ",
        )
    )

    assert isinstance(result, AgentControllerForkChatResult)
    assert result.contract_version == "prompt-enhancer-agent-controller-fork.v1"
    assert result.outcome == "forked"
    assert result.mutation_state == "accepted"
    assert result.attempts == 1
    assert result.receipt is not None
    assert result.receipt.session.session_id == "e" * 32
    assert result.receipt.approvals_copied is False
    assert result.receipt.mutation_authority_copied is False
    assert result.receipt.pending_tool_state_copied is False
    assert result.receipt.staged_attachments_copied is False
    assert result.receipt.artifacts_copied is False
    assert posted == [
        {
            "request_id": "d" * 32,
            "expected_catalog_revision": 3,
            "expected_history_revision": 5,
            "destination_project_id": None,
            "through_event_seq": 4,
            "title": "Synthetic controller branch",
        }
    ]


def test_fork_chat_reports_an_existing_idempotent_replay() -> None:
    def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        return _json_response(_fork_receipt(idempotent_replay=True))

    result = AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
        AgentControllerForkChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            request_id="d" * 32,
            expected_catalog_revision=3,
            expected_history_revision=5,
            through_event_seq=4,
        )
    )

    assert result.outcome == "idempotent_replay"
    assert result.mutation_state == "idempotent_replay"
    assert result.attempts == 1
    assert result.receipt is not None
    assert result.receipt.idempotent_replay is True


def test_ambiguous_fork_retries_once_with_the_exact_idempotency_binding() -> None:
    posted: list[dict[str, Any]] = []

    def handler(method: str, path: str, _query, body) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        assert method == "POST" and path.endswith("/forks")
        posted.append(body)
        if len(posted) == 1:
            raise AgentControllerTransportUnavailable()
        return _json_response(_fork_receipt(idempotent_replay=True))

    result = AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
        AgentControllerForkChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            request_id="d" * 32,
            expected_catalog_revision=3,
            expected_history_revision=5,
            through_event_seq=4,
        )
    )

    assert result.outcome == "forked_reconciled"
    assert result.mutation_state == "reconciled"
    assert result.attempts == 2
    assert result.receipt is not None
    assert result.receipt.idempotent_replay is True
    assert len(posted) == 2
    assert posted[0] == posted[1]


def test_fork_chat_bounds_uncertainty_and_does_not_third_retry() -> None:
    post_calls = 0

    def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal post_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        post_calls += 1
        raise AgentControllerTransportUnavailable()

    result = AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
        AgentControllerForkChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            request_id="d" * 32,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "fork_uncertain"
    assert result.mutation_state == "uncertain"
    assert result.attempts == 2
    assert result.receipt is None
    assert post_calls == 2


def test_fork_chat_does_not_retry_a_trusted_client_rejection() -> None:
    post_calls = 0

    def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal post_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        post_calls += 1
        return _json_response({"detail": {"code": "synthetic_conflict"}}, 409)

    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
            AgentControllerForkChatRequest(
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                request_id="d" * 32,
                expected_catalog_revision=3,
                expected_history_revision=5,
            )
        )
    assert captured.value.http_status == 409
    assert post_calls == 1


@pytest.mark.parametrize(
    "receipt",
    (
        _fork_receipt(destination_project_id="f" * 32),
        _fork_receipt(source_session_id="f" * 32),
        _fork_receipt(source_catalog_revision=4),
        _fork_receipt(branch_event_seq=3),
        _fork_receipt(child_session_id=SESSION_ID),
        {**_fork_receipt(), "mutation_authority_copied": True},
    ),
)
def test_fork_chat_never_accepts_mismatched_or_authority_unsafe_receipts(
    receipt: dict[str, Any],
) -> None:
    post_calls = 0

    def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal post_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        post_calls += 1
        return _json_response(receipt)

    result = AgentControllerClient(_ScriptedTransport(handler)).fork_chat(
        AgentControllerForkChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            request_id="d" * 32,
            expected_catalog_revision=3,
            expected_history_revision=5,
            through_event_seq=4,
        )
    )
    assert result.outcome == "fork_uncertain"
    assert result.receipt is None
    assert post_calls == 2


def test_export_chat_is_exact_revision_complete_and_path_free() -> None:
    export_calls = 0

    def handler(method: str, path: str, query, body) -> AgentControllerHttpResponse:
        nonlocal export_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session(turn_count=0))
        assert (method, path, query, body) == (
            "GET",
            f"/v1/agent/projects/{PROJECT_ID}/sessions/{SESSION_ID}/export",
            {
                "expected_catalog_revision": 3,
                "expected_history_revision": 5,
            },
            None,
        )
        export_calls += 1
        return _json_response(_history_export())

    result = AgentControllerClient(_ScriptedTransport(handler)).export_chat(
        AgentControllerExportChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
            max_events=5,
        )
    )

    assert isinstance(result, AgentControllerExportChatResult)
    assert result.contract_version == "prompt-enhancer-agent-controller-export.v1"
    assert result.complete is True
    assert result.event_count == 5
    assert result.history_revision == 5
    assert [event.seq for event in result.events] == [1, 2, 3, 4, 5]
    assert result.workspace_path_included is False
    assert result.attachment_bytes_included is False
    assert result.live_approval_state_included is False
    assert result.raw_tool_payloads_included is False
    assert result.mutation_authority_included is False
    serialized = result.model_dump_json()
    assert "/example/workspace" not in serialized
    assert '"workspace"' not in serialized
    assert "approval_id" not in serialized
    assert "arguments" not in serialized
    assert "preview" not in serialized
    assert export_calls == 1


def test_export_chat_fails_preflight_before_returning_stale_or_oversized_history() -> None:
    cases = (
        (
            _catalog_session(revision=4, turn_count=0),
            5,
            5,
            "controller_export_revision_mismatch",
        ),
        (
            _catalog_session(history_revision=6, turn_count=0),
            5,
            6,
            "controller_export_revision_mismatch",
        ),
        (
            _catalog_session(retained=False, turn_count=0),
            0,
            0,
            "controller_export_unavailable",
        ),
        (
            _catalog_session(project_id="f" * 32, turn_count=0),
            5,
            5,
            "controller_catalog_response_invalid",
        ),
        (
            _catalog_session(turn_count=0),
            5,
            4,
            "controller_export_limit_exceeded",
        ),
    )
    for catalog_payload, expected_history, max_events, expected_code in cases:
        def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
            if path == "/v1/agent/orchestration":
                return _manifest_response()
            if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
                return _json_response(catalog_payload)
            raise AssertionError("invalid export preflight reached the export endpoint")

        with pytest.raises(AgentControllerError) as captured:
            AgentControllerClient(_ScriptedTransport(handler)).export_chat(
                AgentControllerExportChatRequest(
                    project_id=PROJECT_ID,
                    session_id=SESSION_ID,
                    expected_catalog_revision=3,
                    expected_history_revision=expected_history,
                    max_events=max_events,
                )
            )
        assert captured.value.code == expected_code


def test_export_chat_rejects_mismatched_incomplete_or_raw_payloads() -> None:
    base = _history_export()
    sequence_gap = json.loads(json.dumps(base))
    sequence_gap["events"][2]["seq"] = 7
    raw_arguments = json.loads(json.dumps(base))
    raw_arguments["events"][0]["arguments"] = {"path": "synthetic.txt"}
    cases = (
        {**base, "project_id": "f" * 32},
        {**base, "session_id": "f" * 32},
        {**base, "title": "Wrong title"},
        {**base, "workspace": "/wrong/workspace"},
        {**base, "model_alias": "wrong-model"},
        _history_export(history_revision=4),
        {**base, "turn_count": 1},
        sequence_gap,
        raw_arguments,
    )
    for export_payload in cases:
        def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
            if path == "/v1/agent/orchestration":
                return _manifest_response()
            if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
                return _json_response(_catalog_session(turn_count=0))
            return _json_response(export_payload)

        with pytest.raises(AgentControllerError) as captured:
            AgentControllerClient(_ScriptedTransport(handler)).export_chat(
                AgentControllerExportChatRequest(
                    project_id=PROJECT_ID,
                    session_id=SESSION_ID,
                    expected_catalog_revision=3,
                    expected_history_revision=5,
                    max_events=5,
                )
            )
        assert captured.value.code == "controller_export_response_invalid"


def test_close_chat_is_exact_idle_live_only_and_path_free() -> None:
    delete_calls = 0

    def handler(method: str, path: str, query, body) -> AgentControllerHttpResponse:
        nonlocal delete_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            return _json_response(_session(last_seq=5, project_id=PROJECT_ID))
        assert (method, path, query, body) == (
            "DELETE",
            f"/v1/agent/sessions/{SESSION_ID}",
            {
                "expected_project_id": PROJECT_ID,
                "expected_catalog_revision": 3,
                "expected_history_revision": 5,
            },
            None,
        )
        delete_calls += 1
        return AgentControllerHttpResponse(204, None, b"")

    result = AgentControllerClient(_ScriptedTransport(handler)).close_chat(
        AgentControllerCloseChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert isinstance(result, AgentControllerCloseChatResult)
    assert result.contract_version == "prompt-enhancer-agent-controller-close.v1"
    assert result.outcome == "closed"
    assert result.mutation_state == "accepted"
    assert result.live_session_present is False
    assert result.catalog_session_retained is True
    assert result.permanent_delete_requested is False
    assert result.retained_history_delete_requested is False
    assert result.protected_authority_granted is False
    assert "/example/workspace" not in result.model_dump_json()
    assert delete_calls == 1


def test_close_chat_observes_an_already_closed_chat_without_mutation() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        assert method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}"
        return _json_response({"detail": "synthetic not found"}, 404)

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).close_chat(
        AgentControllerCloseChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "already_closed"
    assert result.mutation_state == "not_attempted"
    assert not any(method == "DELETE" for method, *_rest in transport.calls)


def test_ambiguous_close_reconciles_once_without_repeating_delete() -> None:
    delete_calls = 0
    live_reads = 0
    catalog_reads = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal delete_calls, live_reads, catalog_reads
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            catalog_reads += 1
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            live_reads += 1
            if live_reads == 1:
                return _json_response(_session(last_seq=5, project_id=PROJECT_ID))
            return _json_response({"detail": "synthetic not found"}, 404)
        if method == "DELETE":
            delete_calls += 1
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    result = AgentControllerClient(_ScriptedTransport(handler)).close_chat(
        AgentControllerCloseChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "closed_reconciled"
    assert result.mutation_state == "reconciled"
    assert result.live_session_present is False
    assert result.catalog_session_retained is True
    assert delete_calls == 1
    assert live_reads == 2
    assert catalog_reads == 2


def test_unreconciled_close_stays_uncertain_and_never_retries_delete() -> None:
    delete_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal delete_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            return _json_response(_session(last_seq=5, project_id=PROJECT_ID))
        if method == "DELETE":
            delete_calls += 1
            raise AgentControllerTransportUnavailable()
        raise AssertionError((method, path))

    result = AgentControllerClient(_ScriptedTransport(handler)).close_chat(
        AgentControllerCloseChatRequest(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            expected_catalog_revision=3,
            expected_history_revision=5,
        )
    )

    assert result.outcome == "close_uncertain"
    assert result.mutation_state == "uncertain"
    assert result.live_session_present is True
    assert result.catalog_session_retained is True
    assert delete_calls == 1


def test_close_chat_does_not_reconcile_or_retry_a_trusted_client_rejection() -> None:
    delete_calls = 0
    live_reads = 0
    catalog_reads = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal delete_calls, live_reads, catalog_reads
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            catalog_reads += 1
            return _json_response(_catalog_session())
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            live_reads += 1
            return _json_response(_session(last_seq=5, project_id=PROJECT_ID))
        if method == "DELETE":
            delete_calls += 1
            return _json_response({"detail": "synthetic revision conflict"}, 409)
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(transport).close_chat(
            AgentControllerCloseChatRequest(
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                expected_catalog_revision=3,
                expected_history_revision=5,
            )
        )
    assert captured.value.code == "controller_http_error"
    assert captured.value.http_status == 409
    assert delete_calls == 1
    assert live_reads == 1
    assert catalog_reads == 1


@pytest.mark.parametrize(
    ("catalog_payload", "live_payload", "expected_code"),
    (
        (_catalog_session(revision=4), None, "controller_close_revision_mismatch"),
        (
            _catalog_session(project_id="f" * 32),
            None,
            "controller_catalog_response_invalid",
        ),
        (
            _catalog_session(),
            _session(last_seq=4, project_id=PROJECT_ID),
            "controller_close_revision_mismatch",
        ),
        (
            _catalog_session(),
            _session(running=True, last_seq=5, project_id=PROJECT_ID),
            "controller_close_not_idle",
        ),
        (
            _catalog_session(),
            _session(cleanup_unconfirmed=True, last_seq=5, project_id=PROJECT_ID),
            "controller_close_cleanup_unconfirmed",
        ),
    ),
)
def test_close_chat_rejects_invalid_preflight_before_delete(
    catalog_payload: dict[str, Any],
    live_payload: dict[str, Any] | None,
    expected_code: str,
) -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if path == f"/v1/agent/catalog/sessions/{SESSION_ID}":
            return _json_response(catalog_payload)
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            assert live_payload is not None
            return _json_response(live_payload)
        raise AssertionError("invalid close preflight reached DELETE")

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(transport).close_chat(
            AgentControllerCloseChatRequest(
                project_id=PROJECT_ID,
                session_id=SESSION_ID,
                expected_catalog_revision=3,
                expected_history_revision=5,
            )
        )
    assert captured.value.code == expected_code
    assert not any(method == "DELETE" for method, *_rest in transport.calls)


def test_generic_controller_invocation_cannot_bypass_dedicated_close() -> None:
    transport = _ScriptedTransport(lambda *_args: _manifest_response())
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(transport).invoke(
            AgentControllerInvokeRequest(
                operation="close_live_session",
                path_parameters={"session_id": SESSION_ID},
            )
        )
    assert captured.value.code == "controller_specialized_operation_required"
    assert len(transport.calls) == 1


def test_http_failure_discards_sensitive_server_body_from_diagnostics() -> None:
    sensitive_body = {
        "detail": {
            "token": TOKEN,
            "workspace": "/example/private-workspace",
            "message": "Synthetic private response text",
        }
    }

    def handler(_method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        return _json_response(sensitive_body, 503)

    client = AgentControllerClient(_ScriptedTransport(handler))
    with pytest.raises(AgentControllerError) as captured:
        client.invoke(AgentControllerInvokeRequest(operation="list_projects"))

    error = captured.value
    assert error.code == "controller_http_error"
    assert error.http_status == 503
    assert error.retryable is True
    diagnostic = str(error)
    assert TOKEN not in diagnostic
    assert "/example/private-workspace" not in diagnostic
    assert "Synthetic private response text" not in diagnostic


def test_turn_runner_settles_on_monotonic_terminal_events() -> None:
    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        body: Any | None,
    ) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and path == f"/v1/agent/sessions/{SESSION_ID}":
            return _json_response(_session(last_seq=2))
        if method == "POST" and path.endswith("/messages"):
            assert body == {"text": "Synthetic request", "attachment_ids": []}
            return _json_response(_session(running=True, last_seq=3), 202)
        if method == "GET" and path.endswith("/events"):
            assert query == {"after": 2, "limit": 500}
            return _json_response(
                _page(
                    [
                        _event(3, "user", "Synthetic request"),
                        _event(4, "assistant", "Synthetic answer"),
                        _event(5, "done", "Response complete"),
                    ],
                    running=False,
                    last_seq=5,
                    first_seq=1,
                )
            )
        raise AssertionError((method, path, query))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )
    assert result.outcome == "settled"
    assert result.contract_version == "prompt-enhancer-agent-controller-turn.v2"
    assert result.submission_state == "accepted"
    assert result.cursor == result.last_seq == 5
    assert [event.kind for event in result.events] == ["user", "assistant", "done"]
    assert not any(path.endswith("/stop") for _, path, _, _ in transport.calls)


def test_pending_native_approval_prevents_message_submission() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET":
            return _json_response(
                _session(last_seq=7, pending_approval_id=APPROVAL_ID)
            )
        raise AssertionError("message submission must not occur")

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )
    assert result.outcome == "needs_native_approval"
    assert result.submission_state == "not_attempted"
    assert result.pending_approval_id == APPROVAL_ID
    assert len(transport.calls) == 2


def test_wait_continues_after_native_approval_without_resubmitting_or_stopping() -> None:
    event_calls = 0

    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        _body: Any | None,
    ) -> AgentControllerHttpResponse:
        nonlocal event_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(running=True, last_seq=4))
        if method == "GET" and path.endswith("/events"):
            event_calls += 1
            if event_calls == 1:
                assert query == {"after": 4, "limit": 500}
                return _json_response(
                    _page(
                        [_event(5, "approval_resolved", "Approved")],
                        running=True,
                        last_seq=5,
                        first_seq=1,
                    )
                )
            assert query == {"after": 5, "limit": 500}
            return _json_response(
                _page(
                    [
                        _event(6, "assistant", "Synthetic continued answer"),
                        _event(7, "done", "Response complete"),
                    ],
                    running=False,
                    last_seq=7,
                    first_seq=1,
                )
            )
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).wait_turn(
        AgentControllerWaitRequest(session_id=SESSION_ID, after=4),
        deadline_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert result.outcome == "settled"
    assert result.submission_state == "not_attempted"
    assert result.stop_requested is False
    assert result.cursor == result.last_seq == 7
    assert [event.kind for event in result.events] == [
        "approval_resolved",
        "assistant",
        "done",
    ]
    assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_wait_surfaces_still_pending_native_approval_without_mutation() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(
                _session(
                    running=True,
                    last_seq=7,
                    pending_approval_id=APPROVAL_ID,
                )
            )
        if method == "GET" and path.endswith("/events"):
            return _json_response(
                _page(
                    [],
                    running=True,
                    last_seq=7,
                    first_seq=1,
                    pending_approval_id=APPROVAL_ID,
                )
            )
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).wait_turn(
        AgentControllerWaitRequest(session_id=SESSION_ID, after=7),
    )

    assert result.outcome == "needs_native_approval"
    assert result.pending_approval_id == APPROVAL_ID
    assert result.submission_state == "not_attempted"
    assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_cleanup_uncertainty_is_never_reported_as_a_settled_turn() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET":
            return _json_response(_session(last_seq=9, cleanup_unconfirmed=True))
        raise AssertionError("cleanup quarantine must prevent message submission")

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )

    assert result.outcome == "cleanup_unconfirmed"
    assert result.submission_state == "not_attempted"
    assert result.stop_requested is False
    assert len(transport.calls) == 2


def test_cleanup_uncertainty_during_a_turn_returns_without_requesting_stop() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session())
        if method == "POST" and path.endswith("/messages"):
            return _json_response(_session(running=True), 202)
        if method == "GET" and path.endswith("/events"):
            return _json_response(
                _page(
                    [_event(1, "error", "Command cleanup is unconfirmed")],
                    running=False,
                    last_seq=1,
                    first_seq=1,
                    cleanup_unconfirmed=True,
                )
            )
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(transport).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )

    assert result.outcome == "cleanup_unconfirmed"
    assert result.submission_state == "accepted"
    assert result.stop_requested is False
    assert result.cursor == result.last_seq == 1
    assert not any(path.endswith("/stop") for _method, path, _query, _body in transport.calls)


def test_ambiguous_submission_is_reconciled_without_retrying_the_message() -> None:
    message_calls = 0
    event_calls = 0

    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        _body: Any | None,
    ) -> AgentControllerHttpResponse:
        nonlocal message_calls, event_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session())
        if path.endswith("/messages"):
            message_calls += 1
            raise AgentControllerTransportUnavailable()
        if path.endswith("/events"):
            event_calls += 1
            if event_calls == 1:
                assert query == {"after": 0, "limit": 500}
                return _json_response(
                    _page(
                        [
                            _event(1, "user", "Synthetic request"),
                            _event(2, "assistant", "Synthetic answer"),
                            _event(3, "done", "Response complete"),
                        ],
                        running=False,
                        last_seq=3,
                        first_seq=1,
                    )
                )
            return _json_response(
                _page([], running=False, last_seq=3, first_seq=1)
            )
        raise AssertionError(path)

    result = AgentControllerClient(_ScriptedTransport(handler)).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )
    assert result.outcome == "settled"
    assert result.submission_state == "reconciled"
    assert message_calls == 1


def test_unreconciled_ambiguous_submission_returns_without_retry() -> None:
    message_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal message_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session())
        if path.endswith("/messages"):
            message_calls += 1
            raise AgentControllerTransportUnavailable()
        return _json_response(_page([], running=False, last_seq=0))

    result = AgentControllerClient(_ScriptedTransport(handler)).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        )
    )
    assert result.outcome == "submission_uncertain"
    assert result.submission_state == "uncertain"
    assert message_calls == 1


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_wait_deadline_returns_cursor_without_sending_message_or_stop() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(running=True))
        if method == "GET" and path.endswith("/events"):
            return _json_response(_page([], running=True, last_seq=0))
        raise AssertionError((method, path))

    clock = _Clock()
    transport = _ScriptedTransport(handler)
    result = AgentControllerClient(
        transport,
        clock=clock,
        sleeper=clock.sleep,
    ).wait_turn(
        AgentControllerWaitRequest(session_id=SESSION_ID, after=0),
        deadline_seconds=0.05,
        poll_interval_seconds=0.01,
    )

    assert result.outcome == "incomplete"
    assert result.stop_requested is False
    assert result.cursor == result.last_seq == 0
    assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_wait_rejects_a_cursor_ahead_of_the_live_session() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET":
            return _json_response(_session(last_seq=3))
        raise AssertionError((method, path))

    transport = _ScriptedTransport(handler)
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(transport).wait_turn(
            AgentControllerWaitRequest(session_id=SESSION_ID, after=4),
        )

    assert captured.value.code == "controller_event_cursor_invalid"
    assert len(transport.calls) == 2


def test_deadline_requests_stop_exactly_once_and_drains_terminal_events() -> None:
    stopped = False
    stop_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal stopped, stop_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session())
        if path.endswith("/messages"):
            return _json_response(_session(running=True), 202)
        if path.endswith("/stop"):
            stop_calls += 1
            stopped = True
            return _json_response(_session(running=False, last_seq=1))
        if path.endswith("/events"):
            if stopped:
                return _json_response(
                    _page(
                        [_event(1, "done", "Stopped")],
                        running=False,
                        last_seq=1,
                        first_seq=1,
                    )
                )
            return _json_response(_page([], running=True, last_seq=0))
        raise AssertionError(path)

    clock = _Clock()
    result = AgentControllerClient(
        _ScriptedTransport(handler),
        clock=clock,
        sleeper=clock.sleep,
    ).run_turn(
        AgentControllerTurnRequest(
            session_id=SESSION_ID,
            message={"text": "Synthetic request"},
        ),
        deadline_seconds=0.05,
        poll_interval_seconds=0.01,
        drain_timeout_seconds=0.1,
    )
    assert result.outcome == "stopped"
    assert result.stop_requested is True
    assert stop_calls == 1


def test_explicit_stop_of_active_turn_is_once_only_and_terminal_evidence_bound() -> None:
    stop_calls = 0

    def handler(
        method: str,
        path: str,
        query: Mapping[str, str | int | bool] | None,
        _body: Any | None,
    ) -> AgentControllerHttpResponse:
        nonlocal stop_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(running=True, last_seq=2))
        if method == "POST" and path.endswith("/stop"):
            stop_calls += 1
            return _json_response(
                _session(running=True, stopping=True, last_seq=3)
            )
        if method == "GET" and path.endswith("/events"):
            assert query == {"after": 2, "limit": 500}
            return _json_response(
                _page(
                    [_event(3, "status", "Stopping"), _event(4, "done", "Stopped")],
                    running=False,
                    last_seq=4,
                    first_seq=1,
                )
            )
        raise AssertionError((method, path))

    result = AgentControllerClient(_ScriptedTransport(handler)).stop_turn(
        AgentControllerStopRequest(session_id=SESSION_ID, after=2)
    )

    assert isinstance(result, AgentControllerStopResult)
    assert result.contract_version == "prompt-enhancer-agent-controller-stop.v1"
    assert result.outcome == "stopped"
    assert result.stop_request_state == "accepted"
    assert result.cursor == result.last_seq == 4
    assert [event.kind for event in result.events] == ["status", "done"]
    assert stop_calls == 1


def test_explicit_stop_observes_idle_or_already_stopping_without_duplicate_mutation() -> None:
    cases = (
        (_session(last_seq=1), "already_settled"),
        (_session(running=True, stopping=True, last_seq=1), "stopped"),
    )
    for session_payload, expected_outcome in cases:
        def handler(
            method: str,
            path: str,
            _query: Mapping[str, str | int | bool] | None,
            _body: Any | None,
        ) -> AgentControllerHttpResponse:
            if path == "/v1/agent/orchestration":
                return _manifest_response()
            if method == "GET" and not path.endswith("/events"):
                return _json_response(session_payload)
            if method == "GET" and path.endswith("/events"):
                return _json_response(
                    _page(
                        [_event(1, "done", "Synthetic terminal event")],
                        running=False,
                        last_seq=1,
                        first_seq=1,
                    )
                )
            raise AssertionError("already-settled or stopping session must not receive Stop")

        transport = _ScriptedTransport(handler)
        result = AgentControllerClient(transport).stop_turn(
            AgentControllerStopRequest(session_id=SESSION_ID, after=0)
        )

        assert result.outcome == expected_outcome
        assert result.stop_request_state == "not_attempted"
        assert all(method == "GET" for method, _path, _query, _body in transport.calls)


def test_transport_ambiguous_stop_is_reconciled_without_retry() -> None:
    stop_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal stop_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(running=True))
        if method == "POST" and path.endswith("/stop"):
            stop_calls += 1
            raise AgentControllerTransportUnavailable()
        if method == "GET" and path.endswith("/events"):
            return _json_response(
                _page(
                    [_event(1, "done", "Stopped after ambiguous delivery")],
                    running=False,
                    last_seq=1,
                    first_seq=1,
                )
            )
        raise AssertionError(path)

    result = AgentControllerClient(_ScriptedTransport(handler)).stop_turn(
        AgentControllerStopRequest(session_id=SESSION_ID, after=0)
    )

    assert result.outcome == "stopped"
    assert result.stop_request_state == "reconciled"
    assert stop_calls == 1


def test_transport_ambiguous_stop_without_terminal_evidence_stays_uncertain() -> None:
    stop_calls = 0

    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        nonlocal stop_calls
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(running=True))
        if method == "POST" and path.endswith("/stop"):
            stop_calls += 1
            raise AgentControllerTransportUnavailable()
        if method == "GET" and path.endswith("/events"):
            return _json_response(_page([], running=True, last_seq=0))
        raise AssertionError(path)

    clock = _Clock()
    result = AgentControllerClient(
        _ScriptedTransport(handler),
        clock=clock,
        sleeper=clock.sleep,
    ).stop_turn(
        AgentControllerStopRequest(session_id=SESSION_ID, after=0),
        drain_timeout_seconds=0.1,
        poll_interval_seconds=0.01,
    )

    assert result.outcome == "stop_uncertain"
    assert result.stop_request_state == "uncertain"
    assert stop_calls == 1


def test_explicit_stop_rejects_future_cursor_and_preserves_cleanup_quarantine() -> None:
    cursor_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(_session(last_seq=3))
        )
    )
    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(cursor_transport).stop_turn(
            AgentControllerStopRequest(session_id=SESSION_ID, after=4)
        )
    assert captured.value.code == "controller_event_cursor_invalid"
    assert len(cursor_transport.calls) == 2

    cleanup_transport = _ScriptedTransport(
        lambda _method, path, _query, _body: (
            _manifest_response()
            if path == "/v1/agent/orchestration"
            else _json_response(
                _session(running=True, last_seq=3, cleanup_unconfirmed=True)
            )
        )
    )
    cleanup = AgentControllerClient(cleanup_transport).stop_turn(
        AgentControllerStopRequest(session_id=SESSION_ID, after=3)
    )
    assert cleanup.outcome == "cleanup_unconfirmed"
    assert cleanup.stop_request_state == "not_attempted"
    assert all(
        method != "POST"
        for method, _path, _query, _body in cleanup_transport.calls
    )


def test_event_cursor_gap_fails_closed() -> None:
    def handler(method: str, path: str, *_args) -> AgentControllerHttpResponse:
        if path == "/v1/agent/orchestration":
            return _manifest_response()
        if method == "GET" and not path.endswith("/events"):
            return _json_response(_session(last_seq=2))
        if path.endswith("/messages"):
            return _json_response(_session(running=True, last_seq=2), 202)
        return _json_response(
            _page([_event(5, "done", "Done")], running=False, last_seq=5, first_seq=5)
        )

    with pytest.raises(AgentControllerError) as captured:
        AgentControllerClient(_ScriptedTransport(handler)).run_turn(
            AgentControllerTurnRequest(
                session_id=SESSION_ID,
                message={"text": "Synthetic request"},
            )
        )
    assert captured.value.code == "controller_event_cursor_gap"


class _TestClientTransport:
    def __init__(self, client: TestClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | int | bool] | None = None,
        json_body: Any | None = None,
    ) -> AgentControllerHttpResponse:
        response = self.client.request(
            method,
            path,
            params=query,
            json=json_body,
            headers=self.headers,
        )
        return AgentControllerHttpResponse(
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=response.content,
        )


def test_controller_client_completes_real_synthetic_api_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "synthetic-workspace"
    workspace.mkdir()
    (workspace / "example.txt").write_text("synthetic fixture\n", encoding="utf-8")
    settings = AppSettings(home=tmp_path / "app-home", session_reader_enabled=False)
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        str(tmp_path / "provider-empty"),
    )
    application = bootstrap_local_application(settings)

    def synthetic_chat(_alias: str, _body: bytes) -> tuple[int, bytes, str]:
        return (
            200,
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": "Synthetic controller answer."},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ).encode("utf-8"),
            "application/json",
        )

    service = LocalAgentService(
        chat=synthetic_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        catalog=application.create_agent_catalog_service(),
    )
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None: service,
    )

    try:
        with TestClient(
            application.create_http_app(),
            base_url="http://127.0.0.1",
        ) as http:
            token = settings.api_token_path.read_text(encoding="utf-8").strip()
            controller = AgentControllerClient(_TestClientTransport(http, token))
            opened = controller.open_chat(
                AgentControllerOpenChatRequest(
                    project_name="Synthetic controller project",
                    settings={
                        "workspace": str(workspace),
                        "model_alias": "example-model",
                        "title": "Synthetic controller chat",
                        "retention_policy": "local_history",
                        "allow_writes": True,
                        "allow_commands": False,
                        "allow_web": False,
                    },
                )
            )
            assert opened.outcome == "ready"
            assert opened.session is not None
            project_id = opened.project.project_id
            session_id = opened.session.session_id

            turn = controller.run_turn(
                AgentControllerTurnRequest(
                    session_id=session_id,
                    message={"text": "Reply to this synthetic request."},
                ),
                deadline_seconds=3,
                poll_interval_seconds=0.01,
            )
            assert turn.outcome == "settled"
            assert any(
                event.kind == "assistant"
                and event.text == "Synthetic controller answer."
                for event in turn.events
            )

            file_result = controller.invoke(
                AgentControllerInvokeRequest(
                    operation="read_workspace_file",
                    path_parameters={"session_id": session_id},
                    query={"path": "example.txt"},
                )
            )
            assert file_result.response["content"] == "synthetic fixture\n"

            preview = controller.invoke(
                AgentControllerInvokeRequest(
                    operation="preview_file_create",
                    path_parameters={"session_id": session_id},
                    body={
                        "path": "proposed.txt",
                        "content": "reviewed proposal\n",
                        "line_ending": "lf",
                    },
                )
            ).response
            with pytest.raises(AgentControllerError) as protected:
                controller.invoke(
                    AgentControllerInvokeRequest(
                        operation="apply_file_create",
                        path_parameters={
                            "session_id": session_id,
                            "preview_id": preview["preview_id"],
                        },
                        body={},
                    )
                )
            assert protected.value.code == "controller_native_review_required"
            assert not (workspace / "proposed.txt").exists()

            close_source = controller.invoke(
                AgentControllerInvokeRequest(
                    operation="get_catalog_session",
                    path_parameters={"session_id": session_id},
                )
            ).response
            closed = controller.close_chat(
                AgentControllerCloseChatRequest(
                    project_id=project_id,
                    session_id=session_id,
                    expected_catalog_revision=close_source["revision"],
                    expected_history_revision=close_source["history_revision"],
                )
            )
            assert closed.outcome == "closed"
            assert closed.catalog_session_retained is True
            assert closed.permanent_delete_requested is False

            catalog = controller.invoke(
                AgentControllerInvokeRequest(
                    operation="get_catalog_session",
                    path_parameters={"session_id": session_id},
                )
            ).response
            resumed = controller.resume_chat(
                AgentControllerResumeChatRequest(
                    project_id=project_id,
                    session_id=session_id,
                    expected_catalog_revision=catalog["revision"],
                    expected_history_revision=catalog["history_revision"],
                )
            )
            assert resumed.outcome == "resumed"
            assert resumed.session is not None
            assert resumed.session.recovered is True
            assert resumed.session.authority_revalidated is False
            assert resumed.session.settings.allow_writes is False
            assert resumed.session.settings.allow_commands is False
            assert resumed.session.settings.allow_web is False

            resumed_catalog = controller.invoke(
                AgentControllerInvokeRequest(
                    operation="get_catalog_session",
                    path_parameters={"session_id": session_id},
                )
            ).response
            exported = controller.export_chat(
                AgentControllerExportChatRequest(
                    project_id=project_id,
                    session_id=session_id,
                    expected_catalog_revision=resumed_catalog["revision"],
                    expected_history_revision=resumed_catalog["history_revision"],
                    max_events=100,
                )
            )
            assert exported.complete is True
            assert exported.project_id == project_id
            assert exported.session_id == session_id
            assert exported.event_count == resumed_catalog["history_revision"]
            assert str(workspace) not in exported.model_dump_json()
            assert exported.workspace_path_included is False
            assert exported.live_approval_state_included is False
            assert exported.raw_tool_payloads_included is False

            forked = controller.fork_chat(
                AgentControllerForkChatRequest(
                    project_id=project_id,
                    session_id=session_id,
                    request_id="f" * 32,
                    expected_catalog_revision=resumed_catalog["revision"],
                    expected_history_revision=resumed_catalog["history_revision"],
                    title="Synthetic controller branch",
                )
            )
            assert forked.outcome == "forked"
            assert forked.receipt is not None
            assert forked.receipt.session.session_id != session_id
            assert forked.receipt.session.project_id == project_id
            assert forked.receipt.session.lineage is not None
            assert forked.receipt.session.lineage.source_session_id == session_id
            assert forked.receipt.approvals_copied is False
            assert forked.receipt.mutation_authority_copied is False
            assert forked.receipt.pending_tool_state_copied is False
            assert forked.receipt.staged_attachments_copied is False
            assert forked.receipt.artifacts_copied is False
    finally:
        service.shutdown(timeout=2)
