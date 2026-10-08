"""Provider-neutral local Agent controller discovery stays bounded and private."""

from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.agent_orchestration import (
    agent_orchestration_manifest,
)
from prompt_enhancer.application.local_agent import LocalAgentService
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings


def test_orchestration_manifest_is_content_free_and_marks_native_boundaries() -> None:
    manifest = agent_orchestration_manifest()
    payload = manifest.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["contract_version"] == "local-agent-orchestration.v22"
    assert payload["transport"] == "loopback_http"
    assert payload["route_coverage"] == (
        "all_agent_routes_plus_controller_runtime_routes"
    )
    assert payload["authentication"] == {
        "primary_scheme": "bearer",
        "authorization_header": "Authorization: Bearer <token>",
        "alternate_header": "X-Prompt-Enhancer-Token: <token>",
        "token_in_manifest": False,
    }
    assert payload["boundaries"] == {
        "listener_scope": "loopback_only",
        "provider_neutral": True,
        "catalog_retention": "local_metadata",
        "conversation_retention": "explicit_metadata_only_or_bounded_local_history",
        "recovered_authority": "read_only_until_native_revalidation",
        "protected_effects": "native_user_presence_only",
        "event_payload_sensitivity": "sensitive",
        "remote_context_egress": (
            "explicit_instruction_and_redaction_preview_required"
        ),
        "token_controller_may_approve": False,
        "raw_transcript_mcp_exposed": False,
        "remote_listener_supported": False,
    }
    assert payload["protocol"] == {
        "session_identity": "project_id_and_session_id_are_both_required",
        "message_admission": "one_message_only_when_session_is_idle",
        "message_retry_semantics": "not_idempotent_do_not_retry_ambiguous_submission",
        "progress_cursor": "monotonic_event_sequence_pass_last_seen_as_after",
        "terminal_condition": "idle_pending_approval_null_cursor_at_last_seq_and_cleanup_confirmed",
        "pending_approval": "surface_to_native_user_never_approve_from_token_controller",
        "approval_continuation": "resume_from_cursor_without_message_resubmission_or_stop",
        "cleanup_quarantine": "return_cleanup_unconfirmed_never_report_settled",
        "retained_resume": "revision_bound_and_read_only_until_native_revalidation",
        "session_forking": "idempotent_revision_bound_settled_history_only_without_authority",
        "artifact_truth": "metadata_is_lineage_only_content_is_rehashed_on_every_read",
        "external_write_artifacts": (
            "saved_chats_retain_verified_receipts_only_for_artifact_lineage"
        ),
        "artifact_file_moves": (
            "verified_move_preserves_matching_artifact_identity_as_immutable_path_version"
        ),
        "workspace_reads": (
            "bounded_to_the_admitted_workspace_and_reparse_points_fail_closed"
        ),
        "workspace_mutation": (
            "token_controller_may_propose_native_user_must_apply"
        ),
        "attachment_staging": (
            "exact_project_and_session_inline_bytes_only_no_path_or_read_authority"
        ),
        "controller_ownership": (
            "one_active_project_scoped_connection_per_live_session"
        ),
        "controller_reconnect": (
            "same_connection_recovers_by_session_and_cursor_without_resubmission"
        ),
        "controller_handoff": (
            "two_party_revision_bound_same_project_no_native_authority_transfer"
        ),
    }
    operations = [endpoint["operation"] for endpoint in payload["endpoints"]]
    assert len(operations) == len(set(operations))
    assert {
        "get_local_runtime",
        "list_projects_page",
        "list_project_sessions_page",
        "list_catalog_sessions_page",
        "list_artifacts_page",
        "switch_local_runtime",
        "stop_local_runtime",
        "switch_session_model",
        "get_session_context",
        "read_retained_history",
        "fork_retained_session",
        "resume_retained_session",
        "export_retained_history",
        "revalidate_recovered_authority",
        "list_artifacts",
        "preview_artifact_capture",
        "get_artifact",
        "export_artifact_lineage",
        "update_artifact",
        "remove_artifact",
        "read_artifact_content",
        "preview_artifact_document",
        "capture_artifact",
        "list_workspace_tree",
        "search_workspace_text",
        "read_workspace_file",
        "preview_file_create",
        "apply_file_create",
        "preview_workspace_transaction",
        "apply_workspace_transaction",
        "propose_file_write",
        "propose_file_transaction",
        "list_attachments",
        "stage_attachment",
        "stage_attachment_inline",
        "read_attachment_content",
        "preview_attachment_document",
        "delete_attachment",
    }.issubset(operations)
    approval = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "approve_protected_action"
    )
    assert approval["access"] == "native_user_presence_only"
    revalidation = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "revalidate_recovered_authority"
    )
    assert revalidation["access"] == "native_user_presence_only"
    capture = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "capture_artifact"
    )
    assert capture["access"] == "native_user_presence_only"
    assert next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "read_artifact_content"
    )["response"] == "binary"
    assert next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "read_attachment_content"
    )["response"] == "binary"
    assert next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "remove_artifact"
    )["access"] == "native_user_presence_only"
    stream = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "stream_events"
    )
    assert stream["response"] == "sse"
    assert "cleanup-quarantine page" in stream["purpose"]
    assert "EOF alone is not success" in stream["purpose"]
    fork = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "fork_retained_session"
    )
    assert fork == {
        "operation": "fork_retained_session",
        "method": "POST",
        "path_template": (
            "/v1/agent/projects/{project_id}/sessions/{session_id}/forks"
        ),
        "access": "token_authenticated",
        "response": "json",
        "purpose": (
            "Idempotently branch one revision-bound settled history prefix "
            "without copying live authority."
        ),
    }
    delete_project = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "delete_project"
    )
    assert delete_project["path_template"].endswith(
        "?expected_revision={expected_revision}"
    )
    delete_chat = next(
        endpoint
        for endpoint in payload["endpoints"]
        if endpoint["operation"] == "delete_catalog_session"
    )
    assert delete_chat["path_template"].endswith(
        "?expected_catalog_revision={expected_catalog_revision}"
        "&expected_history_revision={expected_history_revision}"
    )
    assert all(endpoint["path_template"].startswith("/") for endpoint in payload["endpoints"])
    assert "127.0.0.1" not in serialized
    assert "localhost" not in serialized
    assert "workspace\\" not in serialized.casefold()
    assert "session transcript" not in serialized.casefold()


def test_orchestration_manifest_covers_every_agent_route_and_only_real_routes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = AppSettings(
        home=tmp_path / "app-home",
        session_reader_enabled=False,
    )
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        str(tmp_path / "provider-empty"),
    )
    application = bootstrap_local_application(settings)
    schema = application.create_http_app().openapi()
    actual_agent_routes = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        if path.startswith("/v1/agent")
        for method in operations
        if method in {"get", "post", "patch", "delete"}
    }
    manifest = agent_orchestration_manifest()
    declared_agent_routes = {
        (endpoint.method, endpoint.path_template.split("?", 1)[0])
        for endpoint in manifest.endpoints
        if endpoint.path_template.startswith("/v1/agent")
    }
    assert len(actual_agent_routes) == 72
    assert declared_agent_routes == actual_agent_routes

    actual_routes = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method in {"get", "post", "patch", "delete"}
    }
    declared_routes = {
        (endpoint.method, endpoint.path_template.split("?", 1)[0])
        for endpoint in manifest.endpoints
    }
    assert len(declared_routes) == len(manifest.endpoints) == 77
    assert declared_routes <= actual_routes

    native_routes = {
        (endpoint.method, endpoint.path_template.split("?", 1)[0])
        for endpoint in manifest.endpoints
        if endpoint.access == "native_user_presence_only"
    }
    assert native_routes == {
        ("POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts"),
        ("POST", "/v1/agent/projects/{project_id}/sessions/{session_id}/artifacts/{artifact_id}/remove"),
        ("POST", "/v1/agent/sessions/{session_id}/authority"),
        ("POST", "/v1/agent/sessions/{session_id}/changes/restores/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/creates/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/directories/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/directory-moves/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/file-trash/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/moves/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/previews/{preview_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/workspace/transactions/{plan_id}/apply"),
        ("POST", "/v1/agent/sessions/{session_id}/approvals/{approval_id}"),
    }


def test_orchestration_discovery_accepts_local_controller_auth_but_not_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = AppSettings(
        home=tmp_path / "app-home",
        session_reader_enabled=False,
    )
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        str(tmp_path / "provider-empty"),
    )
    application = bootstrap_local_application(settings)

    with TestClient(
        application.create_http_app(), base_url="http://127.0.0.1"
    ) as client:
        token = settings.api_token_path.read_text(encoding="utf-8").strip()
        assert client.get("/v1/agent/orchestration").status_code == 401

        bearer = {"Authorization": f"Bearer {token}"}
        discovered = client.get("/v1/agent/orchestration", headers=bearer)
        assert discovered.status_code == 200
        assert discovered.headers["cache-control"] == "no-store, private"
        assert discovered.headers["pragma"] == "no-cache"
        assert discovered.json()["authentication"]["token_in_manifest"] is False
        assert token not in discovered.text
        assert str(tmp_path) not in discovered.text

        project = client.post(
            "/v1/agent/projects",
            headers=bearer,
            json={"name": "Synthetic controller project"},
        )
        assert project.status_code == 201, project.text

        alternate = client.get(
            "/v1/agent/orchestration",
            headers={API_TOKEN_HEADER: token},
        )
        assert alternate.status_code == 200

        protected = client.post(
            f"/v1/agent/sessions/{'a' * 32}/approvals/{'b' * 32}",
            headers=bearer,
            json={"approved": True},
        )
        assert protected.status_code == 403
        assert protected.json()["detail"] == "owned native confirmation required"


def test_token_controller_completes_a_bounded_project_chat_and_preview_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "synthetic-workspace"
    workspace.mkdir()
    (workspace / "example.txt").write_text(
        "synthetic controller fixture\n", encoding="utf-8"
    )
    settings = AppSettings(
        home=tmp_path / "app-home",
        session_reader_enabled=False,
    )
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
                            "message": {
                                "content": "Synthetic controller answer."
                            },
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
            application.create_http_app(), base_url="http://127.0.0.1"
        ) as client:
            token = settings.api_token_path.read_text(encoding="utf-8").strip()
            bearer = {"Authorization": f"Bearer {token}"}

            project_response = client.post(
                "/v1/agent/projects",
                headers=bearer,
                json={"name": "Synthetic controller project"},
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["project_id"]

            session_response = client.post(
                "/v1/agent/sessions",
                headers=bearer,
                json={
                    "workspace": str(workspace),
                    "project_id": project_id,
                    "model_alias": "example-model",
                    "title": "Synthetic controller chat",
                    "retention_policy": "local_history",
                    "allow_writes": True,
                    "allow_commands": False,
                    "allow_web": False,
                },
            )
            assert session_response.status_code == 201, session_response.text
            session_id = session_response.json()["session_id"]

            submitted = client.post(
                f"/v1/agent/sessions/{session_id}/messages",
                headers=bearer,
                json={"text": "Reply to this synthetic request."},
            )
            assert submitted.status_code == 202, submitted.text

            deadline = time.monotonic() + 3
            cursor = 0
            seen_sequences: list[int] = []
            seen_events: list[dict[str, object]] = []
            terminal = None
            while time.monotonic() < deadline:
                page_response = client.get(
                    f"/v1/agent/sessions/{session_id}/events",
                    headers=bearer,
                    params={"after": cursor},
                )
                assert page_response.status_code == 200, page_response.text
                page = page_response.json()
                sequences = [event["seq"] for event in page["events"]]
                assert sequences == sorted(sequences)
                assert all(sequence > cursor for sequence in sequences)
                seen_sequences.extend(sequences)
                seen_events.extend(page["events"])
                if sequences:
                    cursor = sequences[-1]
                if (
                    page["running"] is False
                    and page["closing"] is False
                    and page["stopping"] is False
                    and page["cleanup_unconfirmed"] is False
                    and page["pending_approval_id"] is None
                    and cursor >= page["last_seq"]
                ):
                    terminal = page
                    break
                time.sleep(0.01)
            assert terminal is not None
            assert seen_sequences == sorted(set(seen_sequences))
            assert any(
                event["kind"] == "assistant"
                and event["text"] == "Synthetic controller answer."
                for event in seen_events
            )

            tree = client.get(
                f"/v1/agent/sessions/{session_id}/workspace/tree",
                headers=bearer,
            )
            assert tree.status_code == 200, tree.text
            assert any(
                entry["path"] == "example.txt" for entry in tree.json()["entries"]
            )
            file_response = client.get(
                f"/v1/agent/sessions/{session_id}/workspace/file",
                headers=bearer,
                params={"path": "example.txt"},
            )
            assert file_response.status_code == 200, file_response.text
            assert file_response.json()["content"] == "synthetic controller fixture\n"

            preview_response = client.post(
                f"/v1/agent/sessions/{session_id}/workspace/creates",
                headers=bearer,
                json={
                    "path": "proposed.txt",
                    "content": "reviewed synthetic proposal\n",
                    "line_ending": "lf",
                },
            )
            assert preview_response.status_code == 201, preview_response.text
            preview = preview_response.json()
            rejected_apply = client.post(
                f"/v1/agent/sessions/{session_id}/workspace/creates/"
                f"{preview['preview_id']}/apply",
                headers=bearer,
                json={
                    "path": preview["path"],
                    "content": "reviewed synthetic proposal\n",
                    "proposed_revision": preview["proposed_revision"],
                    "line_ending": preview["line_ending"],
                    "confirmation": "apply_reviewed_workspace_create",
                },
            )
            assert rejected_apply.status_code == 403
            assert not (workspace / "proposed.txt").exists()

            closed = client.delete(
                f"/v1/agent/sessions/{session_id}", headers=bearer
            )
            assert closed.status_code == 204, closed.text
            catalog_response = client.get(
                f"/v1/agent/catalog/sessions/{session_id}", headers=bearer
            )
            assert catalog_response.status_code == 200, catalog_response.text
            catalog = catalog_response.json()
            assert catalog["conversation_available"] is True

            resumed = client.post(
                f"/v1/agent/projects/{project_id}/sessions/{session_id}/resume",
                headers=bearer,
                json={
                    "expected_catalog_revision": catalog["revision"],
                    "expected_history_revision": catalog["history_revision"],
                },
            )
            assert resumed.status_code == 200, resumed.text
            recovered = resumed.json()
            assert recovered["recovered"] is True
            assert recovered["authority_revalidated"] is False
            assert recovered["settings"]["allow_writes"] is False

            assert client.delete(
                f"/v1/agent/sessions/{session_id}", headers=bearer
            ).status_code == 204
            current_catalog = client.get(
                f"/v1/agent/catalog/sessions/{session_id}", headers=bearer
            ).json()
            assert client.delete(
                f"/v1/agent/catalog/sessions/{session_id}",
                headers=bearer,
                params={
                    "expected_catalog_revision": current_catalog["revision"],
                    "expected_history_revision": current_catalog["history_revision"],
                },
            ).status_code == 204
            current_project = client.get(
                f"/v1/agent/projects/{project_id}", headers=bearer
            ).json()
            assert client.delete(
                f"/v1/agent/projects/{project_id}",
                headers=bearer,
                params={"expected_revision": current_project["revision"]},
            ).status_code == 204
    finally:
        service.shutdown(timeout=2)
