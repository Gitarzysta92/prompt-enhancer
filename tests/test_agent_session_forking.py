"""Agent-08f: durable, authority-free session branching and forking."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentRetentionPolicy,
    CreateAgentProject,
    ForkAgentSession,
    StoredAgentEvent,
)
from prompt_enhancer.application.local_agent import (
    AgentSettings,
    LocalAgentService,
    SendMessage,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.interfaces.http.local_agent_routes import (
    create_local_agent_router,
)


T0 = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)


def _catalog(root: Path, ids: tuple[str, ...]) -> AgentCatalogService:
    values = iter(ids)
    return AgentCatalogService(
        SqliteAgentCatalogRepository(
            AgentCatalogSqliteDatabase(root / AGENT_CATALOG_DATABASE_FILENAME)
        ),
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
                        "message": {"content": "Synthetic branchable answer."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            }
        ).encode("utf-8"),
        "application/json",
    )


def _wait(service: LocalAgentService, session_id: str) -> None:
    deadline = time.monotonic() + 3
    while service.get(session_id).running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.get(session_id).running is False


def _retained_source(tmp_path: Path):
    store = tmp_path / "catalog"
    workspace = tmp_path / "synthetic-workspace"
    workspace.mkdir()
    catalog = _catalog(
        store,
        tuple(f"{value:032x}" for value in range(1, 30)),
    )
    project = catalog.create_project(CreateAgentProject(name="Synthetic branch project"))
    service = LocalAgentService(
        chat=_chat,
        active_model=lambda: "example-model",
        model_ready=lambda alias: alias == "example-model",
        fetcher=lambda _url: "synthetic public page",
        catalog=catalog,
        clock=lambda: T0,
    )
    session = service.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="example-model",
            title="Synthetic source chat",
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            allow_writes=True,
            allow_commands=True,
            allow_web=True,
        )
    )
    service.send(session.session_id, SendMessage(text="Synthetic first turn."))
    _wait(service, session.session_id)
    return store, workspace, catalog, project, service, session


def test_latest_settled_fork_is_durable_idempotent_and_omits_interrupted_tail(
    tmp_path: Path,
) -> None:
    store, _workspace, catalog, project, service, session = _retained_source(tmp_path)
    settled = catalog.get_session(session.session_id)
    catalog.append_history_event(
        project_id=project.project_id,
        session_id=session.session_id,
        expected_history_revision=settled.history_revision,
        event=StoredAgentEvent(
            seq=settled.last_event_seq + 1,
            at=T0,
            kind="user",
            text="Synthetic interrupted tail that must not cross the branch.",
            turn_id="d" * 32,
        ),
    )
    source = catalog.get_session(session.session_id)
    service.delete(session.session_id)
    command = ForkAgentSession(
        request_id="a" * 32,
        expected_catalog_revision=source.revision,
        expected_history_revision=source.history_revision,
    )

    receipt = catalog.fork_session(
        source_project_id=project.project_id,
        source_session_id=session.session_id,
        command=command,
    )
    assert receipt.idempotent_replay is False
    assert receipt.source_tail_omitted is True
    assert receipt.approvals_copied is False
    assert receipt.mutation_authority_copied is False
    assert receipt.pending_tool_state_copied is False
    assert receipt.staged_attachments_copied is False
    assert receipt.artifacts_copied is False
    assert receipt.session.session_id != session.session_id
    assert receipt.session.retention_policy is AgentRetentionPolicy.LOCAL_HISTORY
    assert receipt.session.lineage is not None
    assert receipt.session.lineage.source_session_id == session.session_id
    assert receipt.session.lineage.source_project_id == project.project_id
    assert receipt.session.lineage.source_catalog_revision == source.revision
    assert receipt.session.lineage.source_history_revision == source.history_revision
    assert receipt.session.lineage.copied_turn_count == 1
    assert receipt.session.turn_count == 1

    copied = catalog.load_history(
        project_id=project.project_id,
        session_id=receipt.session.session_id,
    )
    assert copied.interrupted is False
    assert copied.history_revision == receipt.session.lineage.copied_event_count
    assert copied.last_seq == receipt.session.lineage.branch_event_seq
    assert not any(
        event.text == "Synthetic interrupted tail that must not cross the branch."
        for event in copied.events
    )
    assert not any(event.kind.startswith("approval_") for event in copied.events)

    replay = catalog.fork_session(
        source_project_id=project.project_id,
        source_session_id=session.session_id,
        command=command,
    )
    assert replay.idempotent_replay is True
    assert replay.session.session_id == receipt.session.session_id
    with pytest.raises(AgentCatalogError) as reused:
        catalog.fork_session(
            source_project_id=project.project_id,
            source_session_id=session.session_id,
            command=command.model_copy(update={"title": "Different request"}),
        )
    assert reused.value.code == "agent_session_fork_request_conflict"

    source_record = catalog.get_session(session.session_id)
    catalog.delete_session(
        session.session_id,
        expected_catalog_revision=source_record.revision,
        expected_history_revision=source_record.history_revision,
    )
    restarted = _catalog(store, ("f" * 32,))
    durable_child = restarted.get_session(receipt.session.session_id)
    assert durable_child.lineage is not None
    assert durable_child.lineage.source_session_id == session.session_id
    assert restarted.load_history(
        project_id=project.project_id,
        session_id=durable_child.session_id,
    ).events == copied.events
    replay_after_parent_deletion = restarted.fork_session(
        source_project_id=project.project_id,
        source_session_id=session.session_id,
        command=command,
    )
    assert replay_after_parent_deletion.idempotent_replay is True
    assert replay_after_parent_deletion.session.session_id == durable_child.session_id


def test_fork_point_and_revisions_fail_closed_without_creating_partial_chat(
    tmp_path: Path,
) -> None:
    _store, _workspace, catalog, project, service, session = _retained_source(tmp_path)
    service.send(session.session_id, SendMessage(text="Synthetic second turn."))
    _wait(service, session.session_id)
    source = catalog.get_session(session.session_id)
    history = catalog.load_history(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    done_points = [event.seq for event in history.events if event.kind == "done"]
    assert len(done_points) == 2
    before = catalog.list_sessions(project_id=project.project_id).sessions

    with pytest.raises(AgentCatalogError) as invalid_point:
        catalog.fork_session(
            source_project_id=project.project_id,
            source_session_id=session.session_id,
            command=ForkAgentSession(
                request_id="b" * 32,
                expected_catalog_revision=source.revision,
                expected_history_revision=source.history_revision,
                through_event_seq=done_points[0] - 1,
            ),
        )
    assert invalid_point.value.code == "agent_session_fork_point_invalid"
    with pytest.raises(AgentCatalogError) as stale_history:
        catalog.fork_session(
            source_project_id=project.project_id,
            source_session_id=session.session_id,
            command=ForkAgentSession(
                request_id="c" * 32,
                expected_catalog_revision=source.revision,
                expected_history_revision=source.history_revision - 1,
            ),
        )
    assert stale_history.value.code == "agent_history_revision_conflict"
    assert catalog.list_sessions(project_id=project.project_id).sessions == before

    branch = catalog.fork_session(
        source_project_id=project.project_id,
        source_session_id=session.session_id,
        command=ForkAgentSession(
            request_id="d" * 32,
            expected_catalog_revision=source.revision,
            expected_history_revision=source.history_revision,
            through_event_seq=done_points[0],
            title="First-turn branch",
        ),
    )
    assert branch.session.title == "First-turn branch"
    assert branch.session.turn_count == 1
    assert branch.session.lineage is not None
    assert branch.session.lineage.branch_event_seq == done_points[0]
    assert branch.source_tail_omitted is True


def test_metadata_only_source_and_archived_destination_are_rejected(
    tmp_path: Path,
) -> None:
    store = tmp_path / "catalog"
    catalog = _catalog(store, tuple(f"{value:032x}" for value in range(1, 10)))
    source_project = catalog.create_project(CreateAgentProject(name="Metadata source"))
    destination = catalog.create_project(CreateAgentProject(name="Destination"))
    source = catalog.register_live_session(
        session_id="e" * 32,
        project_id=source_project.project_id,
        title="Metadata-only chat",
        workspace=tmp_path / "synthetic-workspace",
        model_alias=None,
        created_at=T0,
    )
    with pytest.raises(AgentCatalogError) as not_retained:
        catalog.fork_session(
            source_project_id=source_project.project_id,
            source_session_id=source.session_id,
            command=ForkAgentSession(
                request_id="1" * 32,
                expected_catalog_revision=source.revision,
                expected_history_revision=0,
            ),
        )
    assert not_retained.value.code == "agent_history_not_retained"

    from prompt_enhancer.application.agent_catalog import UpdateAgentProject

    destination = catalog.update_project(
        destination.project_id,
        UpdateAgentProject(expected_revision=destination.revision, archived=True),
    )
    retained = catalog.register_live_session(
        session_id="f" * 32,
        project_id=source_project.project_id,
        title="Retained empty chat",
        workspace=tmp_path / "synthetic-workspace",
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    with pytest.raises(AgentCatalogError) as archived:
        catalog.fork_session(
            source_project_id=source_project.project_id,
            source_session_id=retained.session_id,
            command=ForkAgentSession(
                request_id="2" * 32,
                expected_catalog_revision=retained.revision,
                expected_history_revision=0,
                destination_project_id=destination.project_id,
            ),
        )
    assert archived.value.code == "agent_project_archived"


def test_same_fork_request_is_atomic_across_repository_instances(tmp_path: Path) -> None:
    store, _workspace, catalog, project, service, session = _retained_source(tmp_path)
    source = catalog.get_session(session.session_id)
    service.delete(session.session_id)
    command = ForkAgentSession(
        request_id="3" * 32,
        expected_catalog_revision=source.revision,
        expected_history_revision=source.history_revision,
    )
    first = _catalog(store, ("a" * 32,))
    second = _catalog(store, ("b" * 32,))
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(
            executor.map(
                lambda item: item.fork_session(
                    source_project_id=project.project_id,
                    source_session_id=session.session_id,
                    command=command,
                ),
                (first, second),
            )
        )
    assert receipts[0].session.session_id == receipts[1].session.session_id
    assert sorted(receipt.idempotent_replay for receipt in receipts) == [False, True]
    assert len(catalog.list_sessions(project_id=project.project_id).sessions) == 2


def test_fork_http_contract_is_private_controller_safe_and_exact(tmp_path: Path) -> None:
    _store, _workspace, catalog, project, service, session = _retained_source(tmp_path)
    source = catalog.get_session(session.session_id)
    application = FastAPI()
    application.include_router(
        create_local_agent_router(lambda: None, lambda: None, service)
    )
    path = (
        f"/v1/agent/projects/{project.project_id}/sessions/"
        f"{session.session_id}/forks"
    )
    payload = {
        "request_id": "4" * 32,
        "expected_catalog_revision": source.revision,
        "expected_history_revision": source.history_revision,
        "destination_project_id": None,
        "through_event_seq": None,
        "title": "HTTP synthetic branch",
    }
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.post(path, json=payload)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["pragma"] == "no-cache"
        body = response.json()
        assert set(body) == {
            "contract_version",
            "request_id",
            "idempotent_replay",
            "session",
            "source_tail_omitted",
            "approvals_copied",
            "mutation_authority_copied",
            "pending_tool_state_copied",
            "staged_attachments_copied",
            "artifacts_copied",
        }
        assert body["contract_version"] == "agent-session-fork.v1"
        assert body["session"]["conversation_available"] is True
        assert body["session"]["lineage"]["source_session_id"] == session.session_id
        assert all(
            body[field] is False
            for field in (
                "approvals_copied",
                "mutation_authority_copied",
                "pending_tool_state_copied",
                "staged_attachments_copied",
                "artifacts_copied",
            )
        )
        replay = client.post(path, json=payload)
        assert replay.status_code == 200
        assert replay.json()["idempotent_replay"] is True
        assert replay.json()["session"]["session_id"] == body["session"]["session_id"]
