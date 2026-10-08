"""External-controller file proposals remain native-reviewed and revision-bound."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.application.local_agent import (
    AgentLifecycleProposal,
    AgentSettings,
    AgentWriteProposal,
    AgentWriteTransactionProposal,
    ApprovalDecision,
    LocalAgentError,
    LocalAgentService,
)
from prompt_enhancer.application.agent_artifacts import AgentArtifactService
from prompt_enhancer.application.local_agent_transactions import (
    LocalAgentWorkspaceTransactionEditor,
    WorkspaceTransactionChangeCommand,
)
from prompt_enhancer.application.local_agent_workspace import ToolOutcome
from prompt_enhancer.application.agent_catalog import (
    AgentCatalogService,
    AgentRetentionPolicy,
    CreateAgentProject,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.infrastructure.sqlite.agent_artifacts import (
    SqliteAgentArtifactRepository,
)
from prompt_enhancer.interfaces.http.local_agent_routes import (
    create_local_agent_router,
)


REQUEST_ID = "a" * 32


def _revision(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _service(root: Path, *, approval_wait_seconds: float = 3) -> LocalAgentService:
    return LocalAgentService(
        chat=lambda *_args: pytest.fail("a file proposal must not call the model"),
        active_model=lambda: None,
        allowed_roots=(root.parent,),
        approval_wait_seconds=approval_wait_seconds,
    )


def _session(service: LocalAgentService, root: Path, *, allow_writes: bool = True) -> str:
    return service.create(
        AgentSettings(
            workspace=str(root),
            allow_writes=allow_writes,
            allow_commands=False,
            allow_web=False,
        )
    ).session_id


def _wait_settled(service: LocalAgentService, session_id: str) -> None:
    deadline = time.monotonic() + 4
    while service.get(session_id).running and time.monotonic() < deadline:
        time.sleep(0.01)
    view = service.get(session_id)
    assert view.running is False
    assert view.pending_approval_id is None


def _transaction(
    request_id: str,
    changes: dict[str, tuple[str, str]],
) -> AgentWriteTransactionProposal:
    return AgentWriteTransactionProposal(
        request_id=request_id,
        changes=tuple(
            WorkspaceTransactionChangeCommand(
                path=path,
                content=content,
                expected_revision=_revision(before),
                line_ending="lf",
            )
            for path, (before, content) in changes.items()
        ),
    )


def test_external_edit_waits_for_native_approval_and_returns_verified_receipt(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_bytes(b"before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = AgentWriteProposal(
        request_id=REQUEST_ID,
        operation="edit",
        path="note.txt",
        content="after\n",
        expected_revision=_revision("before\n"),
    )

    pending = service.propose_write(session_id, command)

    assert pending.state == "pending_native_review"
    assert pending.approval_id is not None
    assert target.read_text(encoding="utf-8") == "before\n"
    view = service.get(session_id)
    assert view.running is True
    assert view.pending_approval_id == pending.approval_id
    page = service.events(session_id)
    call = next(event for event in page.events if event.kind == "tool_call")
    approval = next(event for event in page.events if event.kind == "approval_required")
    assert call.call_id == REQUEST_ID
    assert call.arguments == {
        "path": "note.txt",
        "operation": "edit",
        "source": "external_controller",
    }
    assert "after" not in str(call.arguments)
    assert approval.preview is not None and "+after" in approval.preview

    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    assert target.read_text(encoding="utf-8") == "after\n"
    settled = service.propose_write(session_id, command)
    assert settled.state == "applied"
    assert settled.approval_id is None
    assert settled.write_receipt is not None
    assert settled.write_receipt.state == "verified"
    assert settled.write_receipt.before_sha256 == _revision("before\n")
    assert settled.write_receipt.after_sha256 == _revision("after\n")
    events = service.events(session_id).events
    result = next(event for event in events if event.kind == "tool_result")
    assert result.call_id == REQUEST_ID
    assert result.tool_state == "succeeded"
    assert result.write_receipt == settled.write_receipt
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == "approved"
    assert result.execution_receipt.evidence_state == "verified_workspace_effect"
    assert events[-1].kind == "status"
    assert events[-1].text == "External file proposal applied after native approval."


def test_external_create_denial_and_idempotent_replay_never_change_workspace(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = _service(root)
    session_id = _session(service, root)
    command = AgentWriteProposal(
        request_id=REQUEST_ID,
        operation="create",
        path="draft.md",
        content="# Synthetic draft\n",
    )

    first = service.propose_write(session_id, command)
    replay_pending = service.propose_write(session_id, command)
    assert replay_pending == first
    assert not (root / "draft.md").exists()

    assert first.approval_id is not None
    service.approve(
        session_id,
        first.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)

    replay_settled = service.propose_write(session_id, command)
    assert replay_settled.state == "not_approved"
    assert replay_settled.write_receipt is None
    assert not (root / "draft.md").exists()


def test_external_file_move_waits_for_native_review_and_verifies_exact_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "archive").mkdir()
    source = root / "note.txt"
    target = root / "archive" / "note.txt"
    source.write_bytes(b"reviewed\n")
    service = _service(root)
    session_id = _session(service, root)
    command = AgentLifecycleProposal(
        request_id="1" * 32,
        operation="move_file",
        source_path="note.txt",
        target_path="archive/note.txt",
        expected_revision=_revision("reviewed\n"),
    )

    pending = service.propose_lifecycle(session_id, command)

    assert pending.state == "pending_native_review"
    assert pending.verified is False
    assert pending.approval_id is not None
    assert source.read_bytes() == b"reviewed\n"
    assert not target.exists()
    approval = next(
        event
        for event in service.events(session_id).events
        if event.kind == "approval_required"
    )
    assert approval.tool == "move_file"
    assert approval.arguments == {
        "source_path": "note.txt",
        "target_path": "archive/note.txt",
        "expected_revision": _revision("reviewed\n"),
        "operation": "move_file",
        "source": "external_controller",
    }
    assert approval.preview is not None
    assert "Move file without overwrite" in approval.preview

    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    settled = service.propose_lifecycle(session_id, command)
    assert settled.state == "applied"
    assert settled.verified is True
    assert settled.approval_id is None
    assert settled.permanent is None
    assert settled.recovery is None
    assert not source.exists()
    assert target.read_bytes() == b"reviewed\n"
    lifecycle_result = next(
        event for event in service.events(session_id).events
        if event.kind == "tool_result" and event.call_id == command.request_id
    )
    assert lifecycle_result.execution_receipt is not None
    assert lifecycle_result.execution_receipt.approval_state == "approved"
    assert lifecycle_result.execution_receipt.evidence_state == "verified_workspace_effect"


def test_external_lifecycle_rebind_refuses_a_source_changed_after_review(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    source = root / "source.txt"
    target = root / "moved.txt"
    source.write_bytes(b"reviewed\n")
    service = _service(root)
    session_id = _session(service, root)
    command = AgentLifecycleProposal(
        request_id="2" * 32,
        operation="move_file",
        source_path="source.txt",
        target_path="moved.txt",
        expected_revision=_revision("reviewed\n"),
    )

    pending = service.propose_lifecycle(session_id, command)
    source.write_bytes(b"changed outside review\n")
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    settled = service.propose_lifecycle(session_id, command)
    assert settled.state == "failed"
    assert settled.verified is False
    assert source.read_bytes() == b"changed outside review\n"
    assert not target.exists()


def test_external_directory_and_recoverable_trash_proposals_are_shape_bound_and_inert_on_denial(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    target = root / "reviewed.txt"
    target.write_bytes(b"synthetic\n")
    service = _service(root)
    session_id = _session(service, root)

    create = AgentLifecycleProposal(
        request_id="3" * 32,
        operation="create_directory",
        path="docs",
    )
    pending_create = service.propose_lifecycle(session_id, create)
    assert pending_create.approval_id is not None
    service.approve(
        session_id,
        pending_create.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)
    assert service.propose_lifecycle(session_id, create).state == "not_approved"
    assert not (root / "docs").exists()

    trash = AgentLifecycleProposal(
        request_id="4" * 32,
        operation="trash_file",
        path="reviewed.txt",
        expected_revision=_revision("synthetic\n"),
    )
    pending_trash = service.propose_lifecycle(session_id, trash)
    assert pending_trash.permanent is False
    assert pending_trash.recovery == "windows_recycle_bin"
    assert pending_trash.approval_id is not None
    service.approve(
        session_id,
        pending_trash.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)
    assert service.propose_lifecycle(session_id, trash).state == "not_approved"
    assert target.read_bytes() == b"synthetic\n"

    with pytest.raises(ValueError):
        AgentLifecycleProposal(
            request_id="5" * 32,
            operation="trash_file",
            path="reviewed.txt",
        )
    with pytest.raises(ValueError):
        AgentLifecycleProposal(
            request_id="6" * 32,
            operation="create_directory",
            path="docs",
            target_path="unexpected",
        )


def test_lifecycle_proposal_http_contract_never_applies_and_request_ids_are_cross_lane_unique(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = _service(root)
    session_id = _session(service, root)
    app = FastAPI()
    app.include_router(create_local_agent_router(lambda: None, lambda: None, service))
    client = TestClient(app)

    response = client.post(
        f"/v1/agent/sessions/{session_id}/lifecycle-proposals",
        json={
            "request_id": "7" * 32,
            "operation": "create_directory",
            "path": "review-me",
        },
    )

    assert response.status_code == 202
    assert response.json()["contract_version"] == "agent-lifecycle-proposal.v1"
    assert response.json()["state"] == "pending_native_review"
    assert not (root / "review-me").exists()
    with pytest.raises(LocalAgentError, match="agent_write_proposal_request_conflict"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id="7" * 32,
                operation="create",
                path="collision.txt",
                content="synthetic\n",
            ),
        )
    service.stop(session_id)
    _wait_settled(service, session_id)
    assert not (root / "review-me").exists()


def test_write_proposal_refuses_stale_wrong_mode_noop_and_altered_replay(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "note.txt").write_bytes(b"before\n")
    service = _service(root)
    session_id = _session(service, root)

    with pytest.raises(LocalAgentError, match="workspace_revision_changed"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id="1" * 32,
                operation="edit",
                path="note.txt",
                content="after\n",
                expected_revision="0" * 64,
            ),
        )
    with pytest.raises(LocalAgentError, match="workspace_lifecycle_target_exists"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id="2" * 32,
                operation="create",
                path="note.txt",
                content="after\n",
            ),
        )
    with pytest.raises(LocalAgentError, match="workspace_existing_file_required"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id="3" * 32,
                operation="edit",
                path="missing.txt",
                content="after\n",
                expected_revision="0" * 64,
            ),
        )
    with pytest.raises(LocalAgentError, match="workspace_no_change"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id="4" * 32,
                operation="edit",
                path="note.txt",
                content="before\n",
                expected_revision=_revision("before\n"),
            ),
        )

    pending = service.propose_write(
        session_id,
        AgentWriteProposal(
            request_id=REQUEST_ID,
            operation="edit",
            path="note.txt",
            content="after\n",
            expected_revision=_revision("before\n"),
        ),
    )
    with pytest.raises(LocalAgentError, match="agent_write_proposal_request_conflict"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id=REQUEST_ID,
                operation="edit",
                path="note.txt",
                content="different\n",
                expected_revision=_revision("before\n"),
            ),
        )
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)


def test_write_proposal_stop_and_timeout_settle_without_publication(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = _service(root, approval_wait_seconds=0.05)
    session_id = _session(service, root)
    command = AgentWriteProposal(
        request_id=REQUEST_ID,
        operation="create",
        path="cancelled.txt",
        content="synthetic\n",
    )

    service.propose_write(session_id, command)
    service.stop(session_id)
    _wait_settled(service, session_id)
    assert service.propose_write(session_id, command).state == "cancelled"
    cancelled_result = next(
        event for event in service.events(session_id).events
        if event.kind == "tool_result" and event.call_id == REQUEST_ID
    )
    assert cancelled_result.execution_receipt is not None
    assert cancelled_result.execution_receipt.approval_state == "cancelled_before_decision"
    assert cancelled_result.execution_receipt.evidence_state == "no_effect"
    assert not (root / "cancelled.txt").exists()

    timed_out = AgentWriteProposal(
        request_id="b" * 32,
        operation="create",
        path="timed-out.txt",
        content="synthetic\n",
    )
    service.propose_write(session_id, timed_out)
    _wait_settled(service, session_id)
    assert service.propose_write(session_id, timed_out).state == "not_approved"
    timeout_result = next(
        event for event in service.events(session_id).events
        if event.kind == "tool_result" and event.call_id == timed_out.request_id
    )
    assert timeout_result.execution_receipt is not None
    assert timeout_result.execution_receipt.approval_state == "timed_out"
    assert timeout_result.execution_receipt.evidence_state == "no_effect"
    assert not (root / "timed-out.txt").exists()


def test_write_proposal_http_contract_is_accepted_but_never_auto_applied(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = _service(root)
    session_id = _session(service, root)
    app = FastAPI()
    app.include_router(create_local_agent_router(lambda: None, lambda: None, service))
    client = TestClient(app)

    response = client.post(
        f"/v1/agent/sessions/{session_id}/write-proposals",
        json={
            "request_id": REQUEST_ID,
            "operation": "create",
            "path": "review-me.txt",
            "content": "synthetic\n",
        },
    )

    assert response.status_code == 202
    assert response.json()["state"] == "pending_native_review"
    assert not (root / "review-me.txt").exists()
    service.stop(session_id)
    _wait_settled(service, session_id)


def test_write_transaction_proposal_http_contract_waits_for_native_review(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    (root / "beta.txt").write_bytes(b"beta before\n")
    service = _service(root)
    session_id = _session(service, root)
    app = FastAPI()
    app.include_router(create_local_agent_router(lambda: None, lambda: None, service))
    client = TestClient(app)
    proposal = _transaction(
        "9" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha after\n"),
            "beta.txt": ("beta before\n", "beta after\n"),
        },
    )

    response = client.post(
        f"/v1/agent/sessions/{session_id}/write-transaction-proposals",
        json=proposal.model_dump(mode="json"),
    )

    assert response.status_code == 202
    assert response.json()["state"] == "pending_native_review"
    assert response.json()["file_count"] == 2
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"
    service.stop(session_id)
    _wait_settled(service, session_id)


def test_write_proposal_requires_live_native_write_authority(tmp_path: Path) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    service = _service(root)
    session_id = _session(service, root, allow_writes=False)

    with pytest.raises(LocalAgentError, match="agent_write_proposal_not_allowed"):
        service.propose_write(
            session_id,
            AgentWriteProposal(
                request_id=REQUEST_ID,
                operation="create",
                path="blocked.txt",
                content="synthetic\n",
            ),
        )
    assert not (root / "blocked.txt").exists()


def test_denied_proposal_content_and_path_never_enter_durable_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    store = tmp_path / "catalog"
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(
            AgentCatalogSqliteDatabase(store / AGENT_CATALOG_DATABASE_FILENAME)
        ),
        id_factory=iter(("1" * 32,)).__next__,
    )
    project = catalog.create_project(CreateAgentProject(name="Synthetic project"))
    service = LocalAgentService(
        chat=lambda *_args: pytest.fail("a file proposal must not call the model"),
        active_model=lambda: None,
        allowed_roots=(root.parent,),
        approval_wait_seconds=3,
        catalog=catalog,
    )
    session_id = service.create(
        AgentSettings(
            workspace=str(root),
            project_id=project.project_id,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            allow_writes=True,
        )
    ).session_id
    proposal = AgentWriteProposal(
        request_id=REQUEST_ID,
        operation="create",
        path="private-proposal-canary.txt",
        content="EXTERNAL_PROPOSAL_SECRET_CANARY\n",
    )

    pending = service.propose_write(session_id, proposal)
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)

    durable = service.catalog_events(
        project_id=project.project_id,
        session_id=session_id,
    )
    serialized = json.dumps(durable.model_dump(mode="json"))
    assert "EXTERNAL_PROPOSAL_SECRET_CANARY" not in serialized
    assert "private-proposal-canary.txt" not in serialized
    assert catalog.get_session(session_id).history_revision == 1
    assert [event.kind for event in durable.events] == ["status"]
    assert not (root / proposal.path).exists()


def test_approved_external_writes_survive_restart_as_reviewable_artifact_lineage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    store = tmp_path / "catalog"
    database = AgentCatalogSqliteDatabase(store / AGENT_CATALOG_DATABASE_FILENAME)
    catalog = AgentCatalogService(SqliteAgentCatalogRepository(database))
    artifacts = AgentArtifactService(
        SqliteAgentArtifactRepository(database),
        catalog,
    )
    project = catalog.create_project(CreateAgentProject(name="Synthetic project"))
    service = LocalAgentService(
        chat=lambda *_args: pytest.fail("a file proposal must not call the model"),
        active_model=lambda: None,
        allowed_roots=(root.parent,),
        approval_wait_seconds=3,
        catalog=catalog,
        artifacts=artifacts,
    )
    session_id = service.create(
        AgentSettings(
            workspace=str(root),
            project_id=project.project_id,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            allow_writes=True,
        )
    ).session_id

    first_content = "# Synthetic report\n\nFirst reviewed revision.\n"
    create = AgentWriteProposal(
        request_id="d" * 32,
        operation="create",
        path="report.md",
        content=first_content,
    )
    pending_create = service.propose_write(session_id, create)
    assert pending_create.approval_id is not None
    create_approval_id = pending_create.approval_id
    service.approve(
        session_id,
        create_approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    second_content = "# Synthetic report\n\nSecond reviewed revision.\n"
    edit = AgentWriteProposal(
        request_id="e" * 32,
        operation="edit",
        path="report.md",
        content=second_content,
        expected_revision=_revision(first_content),
    )
    pending_edit = service.propose_write(session_id, edit)
    assert pending_edit.approval_id is not None
    edit_approval_id = pending_edit.approval_id
    service.approve(
        session_id,
        edit_approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    durable = service.catalog_events(
        project_id=project.project_id,
        session_id=session_id,
    )
    assert [event.kind for event in durable.events] == [
        "status",
        "tool_result",
        "tool_result",
    ]
    assert all(
        event.write_receipt is not None
        and event.write_receipt.state == "verified"
        for event in durable.events[1:]
    )
    serialized = json.dumps(durable.model_dump(mode="json"))
    assert first_content.strip() not in serialized
    assert second_content.strip() not in serialized
    assert create_approval_id not in serialized
    assert edit_approval_id not in serialized

    restarted_database = AgentCatalogSqliteDatabase(
        store / AGENT_CATALOG_DATABASE_FILENAME
    )
    restarted_catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(restarted_database)
    )
    restarted_artifacts = AgentArtifactService(
        SqliteAgentArtifactRepository(restarted_database),
        restarted_catalog,
    )
    listed = restarted_artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session_id,
    )
    assert len(listed.artifacts) == 1
    artifact = listed.artifacts[0]
    assert artifact.title == "report.md"
    assert artifact.path == "report.md"
    assert artifact.kind == "markdown"
    assert artifact.version_count == 2
    assert artifact.latest_version.provenance == "reviewed_write"
    assert artifact.latest_version.sha256 == _revision(second_content)
    assert artifact.latest_version.byte_size == len(second_content.encode("utf-8"))

    detail = restarted_artifacts.get_artifact(
        project_id=project.project_id,
        session_id=session_id,
        artifact_id=artifact.artifact_id,
        workspace=root,
    )
    assert [version.sha256 for version in detail.versions] == [
        _revision(first_content),
        _revision(second_content),
    ]
    viewed = restarted_artifacts.content(
        project_id=project.project_id,
        session_id=session_id,
        artifact_id=artifact.artifact_id,
        version_id=artifact.latest_version.version_id,
        workspace=root,
        download=False,
    )
    assert viewed.payload == second_content.encode("utf-8")
    assert viewed.content_type == "text/plain; charset=utf-8"


def test_external_transaction_uses_one_review_and_returns_per_file_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    (root / "beta.txt").write_bytes(b"beta before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = _transaction(
        "c" * 32,
        {
            "beta.txt": ("beta before\n", "beta after\n"),
            "alpha.txt": ("alpha before\n", "alpha after\n"),
        },
    )

    pending = service.propose_write_transaction(session_id, command)

    assert pending.state == "pending_native_review"
    assert pending.file_count == 2
    assert [item.path for item in pending.files] == ["alpha.txt", "beta.txt"]
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"
    page = service.events(session_id)
    calls = [event for event in page.events if event.kind == "tool_call"]
    approvals = [event for event in page.events if event.kind == "approval_required"]
    assert len(calls) == len(approvals) == 1
    assert calls[0].arguments == {
        "file_count": 2,
        "create_count": 0,
        "edit_count": 2,
        "paths": ["alpha.txt", "beta.txt"],
        "transaction": "failure_atomic_create_edit",
        "source": "external_controller",
    }
    assert "Transaction file 1/2 [edit]: alpha.txt" in (approvals[0].preview or "")
    assert "Transaction file 2/2 [edit]: beta.txt" in (approvals[0].preview or "")
    assert pending.approval_id is not None

    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    replay = service.propose_write_transaction(session_id, command)
    assert replay.state == "applied"
    assert replay.approval_id is None
    assert replay.transaction_result is not None
    assert replay.transaction_result.state == "committed"
    assert (root / "alpha.txt").read_bytes() == b"alpha after\n"
    assert (root / "beta.txt").read_bytes() == b"beta after\n"
    results = [
        event for event in service.events(session_id).events
        if event.kind == "tool_result"
    ]
    assert [event.call_id for event in results] == ["c" * 32 + ":1", "c" * 32 + ":2"]
    assert all(
        event.tool_state == "succeeded"
        and event.write_receipt is not None
        and event.write_receipt.state == "verified"
        for event in results
    )
    change_set = service.change_set(session_id)
    assert change_set.reviewed_writes == 2
    assert change_set.agent_writes == 2
    assert change_set.manual_writes == 0


def test_external_transaction_commits_mixed_create_and_edit_with_exact_receipts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = AgentWriteTransactionProposal(
        request_id="6" * 32,
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="new.txt",
                content="new reviewed\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="alpha.txt",
                content="alpha reviewed\n",
                expected_revision=_revision("alpha before\n"),
                line_ending="lf",
            ),
        ),
    )

    pending = service.propose_write_transaction(session_id, command)

    assert [(item.path, item.operation) for item in pending.files] == [
        ("alpha.txt", "edit"),
        ("new.txt", "create"),
    ]
    approval = next(
        event
        for event in service.events(session_id).events
        if event.kind == "approval_required"
    )
    assert approval.arguments == {
        "file_count": 2,
        "create_count": 1,
        "edit_count": 1,
        "paths": ["alpha.txt", "new.txt"],
        "transaction": "failure_atomic_create_edit",
        "source": "external_controller",
    }
    assert "Transaction file 1/2 [edit]: alpha.txt" in (approval.preview or "")
    assert "Transaction file 2/2 [create]: new.txt" in (approval.preview or "")
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    settled = service.propose_write_transaction(session_id, command)
    assert settled.contract_version == "agent-write-transaction-proposal.v2"
    assert settled.state == "applied"
    assert (root / "alpha.txt").read_bytes() == b"alpha reviewed\n"
    assert (root / "new.txt").read_bytes() == b"new reviewed\n"
    results = [
        event
        for event in service.events(session_id).events
        if event.kind == "tool_result"
    ]
    assert [event.write_receipt.operation for event in results] == [
        "modified",
        "created",
    ]
    assert all(
        event.write_receipt is not None
        and event.write_receipt.state == "verified"
        for event in results
    )
    assert all(
        event.execution_receipt is not None
        and event.execution_receipt.approval_state == "approved"
        and event.execution_receipt.evidence_state == "verified_workspace_effect"
        for event in results
    )


def test_external_transaction_denial_stop_and_altered_replay_never_publish(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    (root / "beta.txt").write_bytes(b"beta before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = _transaction(
        "d" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha after\n"),
            "beta.txt": ("beta before\n", "beta after\n"),
        },
    )

    pending = service.propose_write_transaction(session_id, command)
    assert service.propose_write_transaction(session_id, command) == pending
    with pytest.raises(LocalAgentError, match="agent_write_proposal_request_conflict"):
        service.propose_write_transaction(
            session_id,
            command.model_copy(
                update={
                    "changes": (
                        command.changes[0].model_copy(update={"content": "altered\n"}),
                        command.changes[1],
                    )
                }
            ),
        )
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)
    assert service.propose_write_transaction(session_id, command).state == "not_approved"
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"

    stopped = _transaction(
        "e" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha stopped\n"),
            "beta.txt": ("beta before\n", "beta stopped\n"),
        },
    )
    service.propose_write_transaction(session_id, stopped)
    service.stop(session_id)
    _wait_settled(service, session_id)
    assert service.propose_write_transaction(session_id, stopped).state == "cancelled"
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"


def test_external_transaction_revalidates_after_review_and_rolls_back_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    (root / "beta.txt").write_bytes(b"beta before\n")
    service = _service(root)
    session_id = _session(service, root)
    stale = _transaction(
        "f" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha proposed\n"),
            "beta.txt": ("beta before\n", "beta proposed\n"),
        },
    )
    pending = service.propose_write_transaction(session_id, stale)
    (root / "alpha.txt").write_bytes(b"external change\n")
    assert pending.approval_id is not None
    service.approve(session_id, pending.approval_id, ApprovalDecision(approved=True))
    _wait_settled(service, session_id)
    assert service.propose_write_transaction(session_id, stale).state == "failed"
    assert (root / "alpha.txt").read_bytes() == b"external change\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"

    (root / "alpha.txt").write_bytes(b"alpha before\n")
    rollback = _transaction(
        "1" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha proposed\n"),
            "beta.txt": ("beta before\n", "beta proposed\n"),
        },
    )
    tracked = service._session(session_id)  # noqa: SLF001 - exact atomic lane under test
    original_apply = tracked.tools.apply_prepared_write
    calls = 0

    def reject_second(prepared):
        nonlocal calls
        calls += 1
        if calls == 2:
            return ToolOutcome(False, "synthetic publication refused", "workspace_write_failed")
        return original_apply(prepared)

    monkeypatch.setattr(tracked.tools, "apply_prepared_write", reject_second)
    pending = service.propose_write_transaction(session_id, rollback)
    assert pending.approval_id is not None
    service.approve(session_id, pending.approval_id, ApprovalDecision(approved=True))
    _wait_settled(service, session_id)
    receipt = service.propose_write_transaction(session_id, rollback)
    assert receipt.state == "rolled_back"
    assert receipt.transaction_result is not None
    assert receipt.transaction_result.state == "rolled_back"
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "beta.txt").read_bytes() == b"beta before\n"


def test_external_transaction_rebuilds_identical_review_after_preview_expiry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    (root / "beta.txt").write_bytes(b"beta before\n")
    monotonic_now = [0.0]
    service = _service(root)
    service._transactions = LocalAgentWorkspaceTransactionEditor(  # noqa: SLF001
        monotonic=lambda: monotonic_now[0],
        ttl_seconds=1,
    )
    session_id = _session(service, root)
    command = _transaction(
        "5" * 32,
        {
            "alpha.txt": ("alpha before\n", "alpha after\n"),
            "beta.txt": ("beta before\n", "beta after\n"),
        },
    )

    pending = service.propose_write_transaction(session_id, command)
    monotonic_now[0] = 2.0
    assert pending.approval_id is not None
    service.approve(session_id, pending.approval_id, ApprovalDecision(approved=True))
    _wait_settled(service, session_id)

    receipt = service.propose_write_transaction(session_id, command)
    assert receipt.state == "applied"
    assert (root / "alpha.txt").read_bytes() == b"alpha after\n"
    assert (root / "beta.txt").read_bytes() == b"beta after\n"


def test_external_transaction_never_reinterprets_a_missing_edit_as_create(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = _transaction(
        "2" * 32,
        {
            "alpha.txt": ("alpha before\n", "ALPHA_PRIVATE_CANARY\n"),
            "missing.txt": ("", "MISSING_PRIVATE_CANARY\n"),
        },
    )

    with pytest.raises(LocalAgentError, match="workspace_existing_file_required"):
        service.propose_write_transaction(session_id, command)
    serialized = json.dumps(
        service.events(session_id).model_dump(mode="json"),
        sort_keys=True,
    )
    assert "PRIVATE_CANARY" not in serialized
    assert not (root / "missing.txt").exists()


def test_external_transaction_create_collision_after_review_never_overwrites(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "alpha.txt").write_bytes(b"alpha before\n")
    service = _service(root)
    session_id = _session(service, root)
    command = AgentWriteTransactionProposal(
        request_id="8" * 32,
        changes=(
            WorkspaceTransactionChangeCommand(
                operation="create",
                path="new.txt",
                content="reviewed create\n",
                line_ending="lf",
            ),
            WorkspaceTransactionChangeCommand(
                operation="edit",
                path="alpha.txt",
                content="alpha reviewed\n",
                expected_revision=_revision("alpha before\n"),
                line_ending="lf",
            ),
        ),
    )

    pending = service.propose_write_transaction(session_id, command)
    (root / "new.txt").write_bytes(b"external owner file\n")
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=True),
    )
    _wait_settled(service, session_id)

    receipt = service.propose_write_transaction(session_id, command)
    assert receipt.state == "failed"
    assert (root / "alpha.txt").read_bytes() == b"alpha before\n"
    assert (root / "new.txt").read_bytes() == b"external owner file\n"


def test_denied_transaction_paths_diffs_and_content_never_enter_durable_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-workspace"
    root.mkdir()
    (root / "private-alpha.txt").write_bytes(b"alpha before\n")
    (root / "private-beta.txt").write_bytes(b"beta before\n")
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(
            AgentCatalogSqliteDatabase(
                tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
            )
        ),
        id_factory=iter(("3" * 32,)).__next__,
    )
    project = catalog.create_project(CreateAgentProject(name="Synthetic project"))
    service = LocalAgentService(
        chat=lambda *_args: pytest.fail("a transaction proposal must not call the model"),
        active_model=lambda: None,
        allowed_roots=(root.parent,),
        approval_wait_seconds=3,
        catalog=catalog,
    )
    session_id = service.create(
        AgentSettings(
            workspace=str(root),
            project_id=project.project_id,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            allow_writes=True,
        )
    ).session_id
    proposal = _transaction(
        "4" * 32,
        {
            "private-alpha.txt": (
                "alpha before\n",
                "TRANSACTION_ALPHA_SECRET_CANARY\n",
            ),
            "private-beta.txt": (
                "beta before\n",
                "TRANSACTION_BETA_SECRET_CANARY\n",
            ),
        },
    )

    pending = service.propose_write_transaction(session_id, proposal)
    assert pending.approval_id is not None
    service.approve(
        session_id,
        pending.approval_id,
        ApprovalDecision(approved=False),
    )
    _wait_settled(service, session_id)

    durable = service.catalog_events(
        project_id=project.project_id,
        session_id=session_id,
    )
    serialized = json.dumps(durable.model_dump(mode="json"), sort_keys=True)
    assert "TRANSACTION_" not in serialized
    assert "private-alpha.txt" not in serialized
    assert "private-beta.txt" not in serialized
    assert [event.kind for event in durable.events] == ["status"]
