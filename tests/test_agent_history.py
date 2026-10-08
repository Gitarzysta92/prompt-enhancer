"""Agent-04: bounded local history, truthful restart recovery, and isolation."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentHistoryState,
    AgentRetentionPolicy,
    CreateAgentProject,
    ResumeAgentSession,
    StoredAgentEvent,
)
from prompt_enhancer.application.local_agent import (
    AgentEvent,
    AgentSettings,
    LocalAgentError,
    LocalAgentService,
    RevalidateAgentAuthority,
    SendMessage,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.interfaces.http.local_agent_routes import create_local_agent_router


T0 = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
PROJECT_ID = "1" * 32


def _repository(root: Path) -> SqliteAgentCatalogRepository:
    return SqliteAgentCatalogRepository(
        AgentCatalogSqliteDatabase(root / AGENT_CATALOG_DATABASE_FILENAME)
    )


def _catalog(root: Path, ids: tuple[str, ...] = (PROJECT_ID,)) -> AgentCatalogService:
    values = iter(ids)
    return AgentCatalogService(
        _repository(root),
        clock=lambda: T0,
        id_factory=values.__next__,
    )


def _chat(_alias: str, _body: bytes) -> tuple[int, bytes, str]:
    return (
        200,
        json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": "Synthetic retained answer."},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode("utf-8"),
        "application/json",
    )


def _wait_until_done(service: LocalAgentService, session_id: str) -> None:
    deadline = time.monotonic() + 3
    while service.get(session_id).running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(session_id).running is False


def test_durable_chat_reopens_after_restart_with_visible_context_and_no_authority(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    store = tmp_path / "catalog"
    first_catalog = _catalog(store)
    project = first_catalog.create_project(CreateAgentProject(name="Example project"))
    first = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        fetcher=lambda _url: "synthetic public page",
        catalog=first_catalog,
        clock=lambda: T0,
    )
    created = first.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="example-model",
            title="Retained example",
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            allow_writes=True,
            allow_commands=True,
            allow_web=True,
        )
    )
    first.send(created.session_id, SendMessage(text="Remember this synthetic request."))
    _wait_until_done(first, created.session_id)
    record = first_catalog.get_session(created.session_id)
    assert record.history_state is AgentHistoryState.DURABLE_LOCAL
    assert record.history_revision == 4
    assert record.last_event_seq == 4
    assert record.turn_count == 1
    first.delete(created.session_id)

    restarted_catalog = _catalog(store, ("2" * 32,))
    restarted = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        catalog=restarted_catalog,
        clock=lambda: T0,
    )
    restored_record = restarted_catalog.get_session(created.session_id)
    assert restarted.catalog_session_availability(restored_record).conversation_available
    page = restarted.catalog_events(
        project_id=project.project_id,
        session_id=created.session_id,
    )
    assert [(event.kind, event.text) for event in page.events] == [
        ("status", "Session ready in example-workspace/ - reads are free; every enabled protected action waits for separate approval."),
        ("user", "Remember this synthetic request."),
        ("assistant", "Synthetic retained answer."),
        ("done", None),
    ]

    recovered = restarted.resume(
        project_id=project.project_id,
        session_id=created.session_id,
        command=ResumeAgentSession(
            expected_catalog_revision=restored_record.revision,
            expected_history_revision=restored_record.history_revision,
        ),
    )
    assert recovered.recovered is True
    assert recovered.authority_revalidated is False
    assert recovered.recovery_state == "recovered"
    assert recovered.settings.allow_writes is False
    assert recovered.settings.allow_commands is False
    assert recovered.settings.allow_web is False
    recovered_context = restarted.session_context(created.session_id)
    assert recovered_context.binding_state == "unmeasured"
    assert recovered_context.unknown_reason == "recovered_without_context_receipt"
    assert recovered_context.context is None
    model_history = restarted._session(created.session_id).messages  # noqa: SLF001
    assert [message["role"] for message in model_history] == ["system", "user", "assistant"]
    assert all("tool_calls" not in message for message in model_history)

    current = restarted_catalog.get_session(created.session_id)
    revalidated = restarted.revalidate_authority(
        created.session_id,
        RevalidateAgentAuthority(
            expected_catalog_revision=current.revision,
            allow_writes=True,
            allow_commands=False,
            allow_web=False,
        ),
    )
    assert revalidated.authority_revalidated is True
    assert revalidated.settings.allow_writes is True
    assert revalidated.settings.allow_commands is False


def test_history_http_surface_is_private_restart_bound_and_native_gated(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "example-http-workspace"
    workspace.mkdir()
    store = tmp_path / "http-catalog"
    first_catalog = _catalog(store)
    project = first_catalog.create_project(CreateAgentProject(name="HTTP history project"))
    first = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        fetcher=lambda _url: "synthetic public page",
        catalog=first_catalog,
        clock=lambda: T0,
    )
    created = first.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="example-model",
            title="HTTP retained chat",
            allow_writes=True,
            allow_commands=True,
            allow_web=True,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
    )
    first.send(created.session_id, SendMessage(text="Synthetic HTTP retained request."))
    _wait_until_done(first, created.session_id)

    restarted_catalog = _catalog(store)
    restarted = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        catalog=restarted_catalog,
        clock=lambda: T0,
    )
    confirmations: list[str] = []

    def require_native_confirmation(request: Request) -> None:
        if request.headers.get("X-Synthetic-Native-Confirmation") != "confirmed":
            raise HTTPException(status_code=403, detail="synthetic native confirmation required")
        confirmations.append("confirmed")

    application = FastAPI()
    application.include_router(
        create_local_agent_router(
            lambda: None,
            require_native_confirmation,
            restarted,
        )
    )
    record = restarted_catalog.get_session(created.session_id)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        events_response = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{created.session_id}/events"
        )
        assert events_response.status_code == 200
        assert events_response.headers["cache-control"] == "no-store, private"
        assert events_response.headers["pragma"] == "no-cache"
        events = events_response.json()["events"]
        assert any(item["kind"] == "user" for item in events)
        assert any(item["kind"] == "assistant" for item in events)
        assert not any(item["kind"].startswith("approval_") for item in events)

        export_response = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{created.session_id}/export",
            params={
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )
        assert export_response.status_code == 200
        assert export_response.headers["cache-control"] == "no-store, private"
        assert export_response.headers["content-disposition"].startswith("attachment;")
        export_text = export_response.text
        assert '"approval_id"' not in export_text
        assert '"arguments"' not in export_text
        assert '"preview"' not in export_text

        stale_catalog_export = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{created.session_id}/export",
            params={
                "expected_catalog_revision": record.revision + 1,
                "expected_history_revision": record.history_revision,
            },
        )
        assert stale_catalog_export.status_code == 409
        stale_history_export = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{created.session_id}/export",
            params={
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision + 1,
            },
        )
        assert stale_history_export.status_code == 409

        resumed_response = client.post(
            f"/v1/agent/projects/{project.project_id}/sessions/{created.session_id}/resume",
            json={
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )
        assert resumed_response.status_code == 200, resumed_response.text
        assert resumed_response.headers["cache-control"] == "no-store, private"
        resumed = resumed_response.json()
        assert resumed["recovered"] is True
        assert resumed["authority_revalidated"] is False
        assert resumed["settings"]["allow_writes"] is False
        assert resumed["settings"]["allow_commands"] is False
        assert resumed["settings"]["allow_web"] is False
        assert resumed["pending_approval_id"] is None

        rejected = client.post(
            f"/v1/agent/sessions/{created.session_id}/authority",
            json={
                "expected_catalog_revision": record.revision,
                "allow_writes": True,
                "allow_commands": False,
                "allow_web": False,
            },
        )
        assert rejected.status_code == 403
        assert confirmations == []

        revalidated_response = client.post(
            f"/v1/agent/sessions/{created.session_id}/authority",
            headers={"X-Synthetic-Native-Confirmation": "confirmed"},
            json={
                "expected_catalog_revision": record.revision,
                "allow_writes": True,
                "allow_commands": False,
                "allow_web": False,
            },
        )
        assert revalidated_response.status_code == 200
        assert revalidated_response.headers["cache-control"] == "no-store, private"
        assert revalidated_response.json()["authority_revalidated"] is True
        assert confirmations == ["confirmed"]


def test_exact_live_close_rejects_stale_or_partial_identity_and_retains_history(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "exact-close-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "exact-close-catalog")
    project = catalog.create_project(CreateAgentProject(name="Exact close project"))
    service = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        catalog=catalog,
        clock=lambda: T0,
    )
    created = service.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="example-model",
            title="Exact close chat",
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
    )
    service.send(
        created.session_id,
        SendMessage(text="Retain this synthetic close request."),
    )
    _wait_until_done(service, created.session_id)
    record = catalog.get_session(created.session_id)
    application = FastAPI()
    application.include_router(
        create_local_agent_router(lambda: None, lambda _request: None, service)
    )

    with TestClient(application, base_url="http://127.0.0.1") as client:
        partial = client.delete(
            f"/v1/agent/sessions/{created.session_id}",
            params={"expected_project_id": project.project_id},
        )
        assert partial.status_code == 422
        stale = client.delete(
            f"/v1/agent/sessions/{created.session_id}",
            params={
                "expected_project_id": project.project_id,
                "expected_catalog_revision": record.revision + 1,
                "expected_history_revision": record.history_revision,
            },
        )
        assert stale.status_code == 409
        cross_project = client.delete(
            f"/v1/agent/sessions/{created.session_id}",
            params={
                "expected_project_id": "2" * 32,
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )
        assert cross_project.status_code == 404
        assert client.get(f"/v1/agent/sessions/{created.session_id}").status_code == 200

        internal = service._session(created.session_id)  # noqa: SLF001
        with internal.lock:
            internal.running = True
        busy = client.delete(
            f"/v1/agent/sessions/{created.session_id}",
            params={
                "expected_project_id": project.project_id,
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )
        assert busy.status_code == 409
        with internal.lock:
            internal.running = False

        closed = client.delete(
            f"/v1/agent/sessions/{created.session_id}",
            params={
                "expected_project_id": project.project_id,
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )
        assert closed.status_code == 204
        assert client.get(f"/v1/agent/sessions/{created.session_id}").status_code == 404

    retained = catalog.get_session(created.session_id)
    assert retained.project_id == project.project_id
    assert retained.revision == record.revision
    assert retained.history_revision == record.history_revision
    assert service.catalog_session_availability(retained).conversation_available is True
    history = catalog.read_history(
        project_id=project.project_id,
        session_id=created.session_id,
    )
    assert [event.kind for event in history.events] == [
        "status",
        "user",
        "assistant",
        "done",
    ]
    assert history.events[1].text == "Retain this synthetic close request."


def test_history_is_project_isolated_revision_bound_and_deleted_with_chat(
    tmp_path: Path,
) -> None:
    store = tmp_path / "catalog"
    catalog = _catalog(store, (PROJECT_ID, "2" * 32))
    first_project = catalog.create_project(CreateAgentProject(name="First project"))
    second_project = catalog.create_project(CreateAgentProject(name="Second project"))
    session = catalog.register_live_session(
        session_id="a" * 32,
        project_id=first_project.project_id,
        title="Example chat",
        workspace=tmp_path / "example-workspace",
        model_alias="example-model",
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    event = StoredAgentEvent(seq=1, at=T0, kind="status", text="Synthetic ready state.")
    revision = catalog.append_history_event(
        project_id=first_project.project_id,
        session_id=session.session_id,
        expected_history_revision=0,
        event=event,
    )
    assert revision == 1

    with pytest.raises(AgentCatalogError) as cross_project:
        catalog.read_history(
            project_id=second_project.project_id,
            session_id=session.session_id,
        )
    assert cross_project.value.code == "agent_catalog_session_not_found"
    with pytest.raises(AgentCatalogError) as stale:
        catalog.append_history_event(
            project_id=first_project.project_id,
            session_id=session.session_id,
            expected_history_revision=0,
            event=StoredAgentEvent(seq=2, at=T0, kind="status", text="Stale writer."),
        )
    assert stale.value.code == "agent_history_revision_conflict"

    current = catalog.get_session(session.session_id)
    catalog.delete_session(
        session.session_id,
        expected_catalog_revision=current.revision,
        expected_history_revision=current.history_revision,
    )
    with sqlite3.connect(store / AGENT_CATALOG_DATABASE_FILENAME) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_conversation_events"
        ).fetchone()[0] == 0


def test_metadata_only_chat_never_claims_reopenable_history(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Metadata project"))
    session = catalog.register_live_session(
        session_id="b" * 32,
        project_id=project.project_id,
        title="Metadata chat",
        workspace=tmp_path / "example-workspace",
        model_alias=None,
        created_at=T0,
    )
    assert session.retention_policy is AgentRetentionPolicy.METADATA_ONLY
    assert session.history_state is AgentHistoryState.MEMORY_ONLY
    with pytest.raises(AgentCatalogError) as unavailable:
        catalog.read_history(project_id=project.project_id, session_id=session.session_id)
    assert unavailable.value.code == "agent_history_not_retained"


def test_durable_projection_excludes_approval_data_arguments_and_raw_tool_output() -> None:
    turn_id = "c" * 32
    approval = AgentEvent(
        seq=1,
        at=T0,
        kind="approval_required",
        approval_id="d" * 32,
        tool="run_command",
        arguments={"command": "EXAMPLE_PRIVATE_COMMAND_CANARY"},
        preview="EXAMPLE_PRIVATE_PREVIEW_CANARY",
        turn_id=turn_id,
    )
    assert LocalAgentService._stored_event(approval) is None  # noqa: SLF001

    tool_call = AgentEvent(
        seq=2,
        at=T0,
        kind="tool_call",
        tool="run_command",
        call_id="example-call",
        arguments={"command": "EXAMPLE_PRIVATE_COMMAND_CANARY"},
        turn_id=turn_id,
    )
    stored_call = LocalAgentService._stored_event(tool_call)  # noqa: SLF001
    assert stored_call is not None
    assert "arguments" not in stored_call.model_dump_json()
    assert "EXAMPLE_PRIVATE_COMMAND_CANARY" not in stored_call.model_dump_json()

    tool_result = AgentEvent(
        seq=3,
        at=T0,
        kind="tool_result",
        tool="run_command",
        call_id="example-call",
        ok=True,
        tool_state="succeeded",
        execution_receipt={
            "approval_state": "approved",
            "evidence_state": "untracked_external_effect",
            "elapsed_ms": 25,
        },
        text="EXAMPLE_PRIVATE_OUTPUT_CANARY",
        turn_id=turn_id,
    )
    stored_result = LocalAgentService._stored_event(tool_result)  # noqa: SLF001
    assert stored_result is not None
    assert stored_result.text is None
    assert stored_result.execution_receipt == tool_result.execution_receipt
    assert "EXAMPLE_PRIVATE_OUTPUT_CANARY" not in stored_result.model_dump_json()

    mcp_result = AgentEvent(
        seq=4,
        at=T0,
        kind="tool_result",
        tool="mcp_99999999_synthetic_read",
        call_id="synthetic-mcp-call",
        ok=True,
        tool_state="succeeded",
        execution_receipt={
            "approval_state": "approved",
            "evidence_state": "untracked_external_effect",
            "elapsed_ms": 30,
        },
        mcp_tool={
            "server_title": "Synthetic Files",
            "tool_name": "read_example",
            "tool_title": "Read example",
            "model_alias": "mcp_99999999_synthetic_read",
        },
        mcp_result={
            "managed_call_id": "e" * 32,
            "outcome": "succeeded",
            "content_mode": "text",
            "result_bytes": 33,
            "result_digest": "f" * 64,
            "cleanup_verified": True,
        },
        text="EXAMPLE_PRIVATE_MCP_RESULT_CANARY",
        turn_id=turn_id,
    )
    stored_mcp = LocalAgentService._stored_event(mcp_result)  # noqa: SLF001
    assert stored_mcp is not None
    assert stored_mcp.text is None
    assert stored_mcp.mcp_tool == mcp_result.mcp_tool
    assert stored_mcp.mcp_result == mcp_result.mcp_result
    serialized = stored_mcp.model_dump_json()
    assert "EXAMPLE_PRIVATE_MCP_RESULT_CANARY" not in serialized
    assert '"arguments":' not in serialized
    assert "EXAMPLE_PRIVATE_COMMAND_CANARY" not in serialized


def test_mcp_result_canary_never_reaches_history_http_export_or_database(
    tmp_path: Path,
) -> None:
    store = tmp_path / "mcp-history-catalog"
    catalog = _catalog(store)
    project = catalog.create_project(CreateAgentProject(name="MCP history project"))
    session = catalog.register_live_session(
        session_id="a" * 32,
        project_id=project.project_id,
        title="MCP retained chat",
        workspace=tmp_path / "example-workspace",
        model_alias="example-model",
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    canary = "EXAMPLE_PRIVATE_MCP_HTTP_EXPORT_CANARY"
    live_event = AgentEvent(
        seq=1,
        at=T0,
        kind="tool_result",
        tool="mcp_99999999_synthetic_read",
        call_id="synthetic-mcp-call",
        ok=True,
        tool_state="succeeded",
        execution_receipt={
            "approval_state": "approved",
            "evidence_state": "untracked_external_effect",
            "elapsed_ms": 30,
        },
        mcp_tool={
            "server_title": "Synthetic Files",
            "tool_name": "read_example",
            "tool_title": "Read example",
            "model_alias": "mcp_99999999_synthetic_read",
        },
        mcp_result={
            "managed_call_id": "e" * 32,
            "outcome": "succeeded",
            "content_mode": "text",
            "result_bytes": len(canary.encode("utf-8")),
            "result_digest": "f" * 64,
            "cleanup_verified": True,
        },
        text=canary,
        turn_id="d" * 32,
    )
    stored_event = LocalAgentService._stored_event(live_event)  # noqa: SLF001
    assert stored_event is not None
    catalog.append_history_event(
        project_id=project.project_id,
        session_id=session.session_id,
        expected_history_revision=0,
        event=stored_event,
    )
    record = catalog.get_session(session.session_id)
    service = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda _alias: True,
        catalog=catalog,
        clock=lambda: T0,
    )
    application = FastAPI()
    application.include_router(
        create_local_agent_router(lambda: None, lambda _request: None, service)
    )

    with TestClient(application, base_url="http://127.0.0.1") as client:
        events_response = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{session.session_id}/events"
        )
        export_response = client.get(
            f"/v1/agent/projects/{project.project_id}/sessions/{session.session_id}/export",
            params={
                "expected_catalog_revision": record.revision,
                "expected_history_revision": record.history_revision,
            },
        )

    assert events_response.status_code == 200
    assert export_response.status_code == 200
    assert canary not in events_response.text
    assert canary not in export_response.text
    assert events_response.json()["events"][0]["text"] is None
    assert events_response.json()["events"][0]["mcp_result"]["result_text_persisted"] is False
    assert canary.encode("utf-8") not in (
        store / AGENT_CATALOG_DATABASE_FILENAME
    ).read_bytes()


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "status", "text": "Synthetic ready state.", "approval_id": "d" * 32},
        {"kind": "assistant", "text": "Synthetic answer.", "tool": "run_command", "call_id": "synthetic-call"},
        {"kind": "tool_result", "tool": "read_file", "call_id": "synthetic-call", "text": "Synthetic output."},
        {"kind": "approval_required", "tool": "run_command", "approval_id": "d" * 32},
    ],
)
def test_agent_event_rejects_cross_kind_or_incomplete_activity_fields(payload) -> None:
    with pytest.raises(ValueError):
        AgentEvent(seq=1, at=T0, **payload)


def test_interrupted_history_is_labelled_and_never_invents_a_done_receipt(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Interrupted project"))
    session = catalog.register_live_session(
        session_id="e" * 32,
        project_id=project.project_id,
        title="Interrupted chat",
        workspace=tmp_path / "example-workspace",
        model_alias="example-model",
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    catalog.append_history_event(
        project_id=project.project_id,
        session_id=session.session_id,
        expected_history_revision=0,
        event=StoredAgentEvent(
            seq=1,
            at=T0,
            kind="user",
            text="Synthetic interrupted request.",
            turn_id="f" * 32,
        ),
    )
    snapshot = catalog.load_history(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert snapshot.interrupted is True
    assert snapshot.turn_count == 0
    assert [event.kind for event in snapshot.events] == ["user"]


def test_recovered_authority_rejects_a_stale_catalog_revision(tmp_path: Path) -> None:
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Authority project"))
    service = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda _alias: True,
        catalog=catalog,
        clock=lambda: T0,
    )
    created = service.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
    )
    record = catalog.get_session(created.session_id)
    with pytest.raises(LocalAgentError) as stale:
        service.revalidate_authority(
            created.session_id,
            RevalidateAgentAuthority(
                expected_catalog_revision=record.revision + 1,
                allow_writes=True,
            ),
        )
    assert stale.value.code == "agent_catalog_session_revision_conflict"
