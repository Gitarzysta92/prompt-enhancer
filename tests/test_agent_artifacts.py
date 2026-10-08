"""Agent-05: immutable, workspace-bound authored artifact lineage."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import time
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from prompt_enhancer.application.agent_artifacts import (
    AgentArtifactError,
    AgentArtifactService,
    CaptureAgentArtifact,
    ExportAgentArtifact,
    PreviewAgentArtifactCapture,
    RemoveAgentArtifact,
    UpdateAgentArtifact,
)
from prompt_enhancer.application.agent_catalog import (
    AgentCatalogService,
    AgentRetentionPolicy,
    CreateAgentProject,
    ForkAgentSession,
    StoredAgentEvent,
)
from prompt_enhancer.application.local_agent_receipts import AgentWriteReceipt
from prompt_enhancer.application.local_agent import (
    AgentSettings,
    ApprovalDecision,
    LocalAgentError,
    LocalAgentService,
    SendMessage,
)
from prompt_enhancer.application.local_agent_file_lifecycle import (
    WORKSPACE_MOVE_CONFIRMATION,
    WorkspaceMoveApplyCommand,
    WorkspaceMovePreviewCommand,
)
from prompt_enhancer.infrastructure.sqlite.agent_artifacts import (
    SqliteAgentArtifactRepository,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.interfaces.http.local_agent_routes import create_local_agent_router
from prompt_enhancer.interfaces.http.user_presence import UserPresenceApprovalManager


T0 = datetime(2026, 8, 27, 15, 0, tzinfo=UTC)


def _ids(start: int = 1):
    value = start
    while True:
        yield f"{value:032x}"
        value += 1


def _fixture(tmp_path: Path, *, retained: bool = True):
    store = tmp_path / "catalog"
    database = AgentCatalogSqliteDatabase(store / AGENT_CATALOG_DATABASE_FILENAME)
    catalog_ids = _ids(1)
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=catalog_ids.__next__,
    )
    project = catalog.create_project(CreateAgentProject(name="Synthetic artifact project"))
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    session = catalog.register_live_session(
        session_id="a" * 32,
        project_id=project.project_id,
        title="Synthetic artifact chat",
        workspace=workspace,
        model_alias="example-model",
        created_at=T0,
        retention_policy=(
            AgentRetentionPolicy.LOCAL_HISTORY
            if retained
            else AgentRetentionPolicy.METADATA_ONLY
        ),
        profile_json="{}" if retained else None,
    )
    artifact_ids = _ids(100)
    service = AgentArtifactService(
        SqliteAgentArtifactRepository(database),
        catalog,
        clock=lambda: T0,
        id_factory=artifact_ids.__next__,
    )
    return database, catalog, service, project, session, workspace


def _receipt(
    *,
    path: str,
    payload: bytes,
    before: bytes | None = None,
) -> AgentWriteReceipt:
    digest = hashlib.sha256(payload).hexdigest()
    before_digest = None if before is None else hashlib.sha256(before).hexdigest()
    return AgentWriteReceipt(
        path=path,
        state="verified",
        operation="created" if before is None else "modified",
        before_sha256=before_digest,
        after_sha256=digest,
        added_lines=1,
        removed_lines=0 if before is None else 1,
        byte_size=len(payload),
    )


def _append_write(catalog, project_id: str, session_id: str, *, seq: int, receipt) -> None:
    catalog.append_history_event(
        project_id=project_id,
        session_id=session_id,
        expected_history_revision=seq - 1,
        event=StoredAgentEvent(
            seq=seq,
            at=T0,
            kind="tool_result",
            tool="write_file",
            call_id=f"synthetic-call-{seq}",
            ok=True,
            tool_state="succeeded",
            write_receipt=receipt,
            turn_id=f"{seq + 500:032x}",
        ),
    )


def _faulting_artifact_service(
    database: AgentCatalogSqliteDatabase,
    catalog: AgentCatalogService,
    *,
    stage: str,
    id_start: int,
) -> AgentArtifactService:
    identifiers = _ids(id_start)

    def interrupt(current: str) -> None:
        if current == stage:
            raise RuntimeError("synthetic artifact transaction interruption")

    return AgentArtifactService(
        SqliteAgentArtifactRepository(database, fault_hook=interrupt),
        catalog,
        clock=lambda: T0,
        id_factory=identifiers.__next__,
    )


def _synthetic_docx() -> bytes:
    output = BytesIO()
    document = b"""<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Synthetic reviewed document.</w:t></w:r></w:p></w:body>
</w:document>"""
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def test_session_fork_never_inherits_artifact_lineage(tmp_path: Path) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"synthetic source artifact\n"
    (workspace / "source.md").write_bytes(payload)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="source.md", payload=payload),
    )
    source_artifacts = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert len(source_artifacts.artifacts) == 1
    source = catalog.get_session(session.session_id)

    forked = catalog.fork_session(
        source_project_id=project.project_id,
        source_session_id=session.session_id,
        command=ForkAgentSession(
            request_id="f" * 32,
            expected_catalog_revision=source.revision,
            expected_history_revision=source.history_revision,
            through_event_seq=0,
        ),
    )
    assert forked.artifacts_copied is False
    assert artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=forked.session.session_id,
    ).artifacts == ()
    assert len(artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    ).artifacts) == 1


@pytest.mark.parametrize(
    ("stage", "committed_before_restart"),
    [
        ("after_head_insert", False),
        ("after_version_insert", False),
        ("before_commit", False),
        ("after_commit", True),
    ],
)
def test_interrupted_new_artifact_transaction_rolls_back_or_replays_once(
    tmp_path: Path,
    stage: str,
    committed_before_restart: bool,
) -> None:
    database, catalog, _artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"synthetic restart-safe artifact\n"
    (workspace / "restart.md").write_bytes(payload)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="restart.md", payload=payload),
    )
    faulting = _faulting_artifact_service(
        database,
        catalog,
        stage=stage,
        id_start=500,
    )

    with pytest.raises(RuntimeError, match="synthetic artifact transaction interruption"):
        faulting.list_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
        )

    with database.connect() as connection:
        head_count = int(connection.execute("SELECT COUNT(*) FROM agent_artifacts").fetchone()[0])
        version_count = int(
            connection.execute("SELECT COUNT(*) FROM agent_artifact_versions").fetchone()[0]
        )
    expected = 1 if committed_before_restart else 0
    assert (head_count, version_count) == (expected, expected)

    identifiers = _ids(700)
    restarted = AgentArtifactService(
        SqliteAgentArtifactRepository(
            AgentCatalogSqliteDatabase(database.path),
        ),
        catalog,
        clock=lambda: T0,
        id_factory=identifiers.__next__,
    )
    recovered = restarted.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    repeated = restarted.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert len(recovered.artifacts) == 1
    assert recovered.artifacts[0].version_count == 1
    assert repeated.artifacts == recovered.artifacts


@pytest.mark.parametrize(
    ("stage", "committed_before_restart"),
    [
        ("after_version_insert", False),
        ("after_head_update", False),
        ("before_commit", False),
        ("after_commit", True),
    ],
)
def test_interrupted_artifact_append_keeps_head_atomic_and_replays_once(
    tmp_path: Path,
    stage: str,
    committed_before_restart: bool,
) -> None:
    database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    first = b"synthetic first artifact version\n"
    second = b"synthetic second artifact version\n"
    target = workspace / "lineage.md"
    target.write_bytes(first)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="lineage.md", payload=first),
    )
    initial = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    ).artifacts[0]
    target.write_bytes(second)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=2,
        receipt=_receipt(path="lineage.md", payload=second, before=first),
    )
    faulting = _faulting_artifact_service(
        database,
        catalog,
        stage=stage,
        id_start=800,
    )

    with pytest.raises(RuntimeError, match="synthetic artifact transaction interruption"):
        faulting.list_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
        )

    with database.connect() as connection:
        stored = connection.execute(
            "SELECT revision,latest_version_number FROM agent_artifacts WHERE artifact_id=?",
            (initial.artifact_id,),
        ).fetchone()
        version_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_artifact_versions WHERE artifact_id=?",
                (initial.artifact_id,),
            ).fetchone()[0]
        )
    expected = 2 if committed_before_restart else 1
    assert stored is not None
    assert (int(stored["revision"]), int(stored["latest_version_number"])) == (
        expected,
        expected,
    )
    assert version_count == expected

    identifiers = _ids(1_000)
    restarted = AgentArtifactService(
        SqliteAgentArtifactRepository(
            AgentCatalogSqliteDatabase(database.path),
        ),
        catalog,
        clock=lambda: T0,
        id_factory=identifiers.__next__,
    )
    recovered = restarted.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    repeated = restarted.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert len(recovered.artifacts) == 1
    assert recovered.artifacts[0].artifact_id == initial.artifact_id
    assert recovered.artifacts[0].version_count == 2
    assert repeated.artifacts == recovered.artifacts


def test_reviewed_writes_form_idempotent_immutable_lineage_and_revalidate_bytes(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    first = b"first synthetic revision\n"
    target = workspace / "notes.md"
    target.write_bytes(first)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="notes.md", payload=first),
    )

    listed = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert len(listed.artifacts) == 1
    head = listed.artifacts[0]
    assert head.kind == "markdown"
    assert head.version_count == 1
    assert head.latest_version.provenance == "reviewed_write"
    assert head.availability == "unchecked"

    # Repeated projections consume no duplicate lineage.
    again = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    )
    assert again.artifacts[0].version_count == 1

    second = b"second synthetic revision\n"
    target.write_bytes(second)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=2,
        receipt=_receipt(path="notes.md", payload=second, before=first),
    )
    detail = artifacts.get_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=head.artifact_id,
        workspace=workspace,
    )
    assert detail.version_count == 2
    assert [version.version_number for version in detail.versions] == [1, 2]
    assert detail.availability == "available"
    content = artifacts.content(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=detail.artifact_id,
        version_id=detail.latest_version.version_id,
        workspace=workspace,
        download=False,
    )
    assert content.payload == second
    assert content.content_type == "text/plain; charset=utf-8"

    first_version = detail.versions[0]
    with pytest.raises(AgentArtifactError) as historical_changed:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=detail.artifact_id,
            version_id=first_version.version_id,
            workspace=workspace,
            download=False,
        )
    assert historical_changed.value.code == "agent_artifact_stale"

    # Historical bytes are never copied into application storage. If the
    # workspace is explicitly restored to that exact digest, the requested
    # immutable version becomes reviewable again.
    target.write_bytes(first)
    restored = artifacts.content(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=detail.artifact_id,
        version_id=first_version.version_id,
        workspace=workspace,
        download=False,
    )
    assert restored.payload == first
    target.write_bytes(second)

    target.write_bytes(b"tamper synthetic revision\n")
    stale = artifacts.get_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=head.artifact_id,
        workspace=workspace,
    )
    assert stale.availability == "stale"
    with pytest.raises(AgentArtifactError) as changed:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=head.artifact_id,
            version_id=detail.latest_version.version_id,
            workspace=workspace,
            download=False,
        )
    assert changed.value.code == "agent_artifact_stale"

    target.unlink()
    missing = artifacts.get_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=head.artifact_id,
        workspace=workspace,
    )
    assert missing.availability == "missing"


def test_verified_reviewed_file_move_preserves_artifact_identity_after_restart(
    tmp_path: Path,
) -> None:
    database, catalog, artifacts, project, _session, workspace = _fixture(tmp_path)
    payload = b"Synthetic movable artifact.\n"
    source = workspace / "draft.md"
    source.write_bytes(payload)
    (workspace / "archive").mkdir()

    agent = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
        artifacts=artifacts,
        clock=lambda: T0,
    )
    live = agent.create(AgentSettings(
        workspace=str(workspace),
        project_id=project.project_id,
        title="Synthetic move chat",
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    ))
    captured = agent.capture_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        command=CaptureAgentArtifact(
            path="draft.md",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )

    preview = agent.preview_workspace_move(
        live.session_id,
        WorkspaceMovePreviewCommand(
            source_path="draft.md",
            target_path="archive/final.md",
            expected_revision=hashlib.sha256(payload).hexdigest(),
        ),
    )
    moved = agent.apply_workspace_move(
        live.session_id,
        preview.preview_id,
        WorkspaceMoveApplyCommand(
            source_path=preview.source_path,
            target_path=preview.target_path,
            expected_revision=preview.expected_revision,
            confirmation=WORKSPACE_MOVE_CONFIRMATION,
        ),
    )
    assert moved.revision == captured.latest_version.sha256
    assert not source.exists()

    relocated = agent.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=captured.artifact_id,
    )
    assert relocated.artifact_id == captured.artifact_id
    assert relocated.path == "archive/final.md"
    assert relocated.availability == "available"
    assert relocated.version_count == 2
    assert [version.path for version in relocated.versions] == [
        "draft.md",
        "archive/final.md",
    ]
    assert [version.provenance for version in relocated.versions] == [
        "verified_output",
        "reviewed_move",
    ]

    restarted_catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(AgentCatalogSqliteDatabase(database.path)),
        clock=lambda: T0,
        id_factory=_ids(800).__next__,
    )
    restarted_artifacts = AgentArtifactService(
        SqliteAgentArtifactRepository(AgentCatalogSqliteDatabase(database.path)),
        restarted_catalog,
        clock=lambda: T0,
        id_factory=_ids(900).__next__,
    )
    recovered = restarted_artifacts.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=captured.artifact_id,
        workspace=workspace,
    )
    assert recovered.path == "archive/final.md"
    assert recovered.version_count == 2
    content = restarted_artifacts.content(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=captured.artifact_id,
        version_id=recovered.latest_version.version_id,
        workspace=workspace,
        download=False,
    )
    assert content.payload == payload


def test_local_model_reviewed_move_advances_matching_artifact_lineage(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, _session, workspace = _fixture(tmp_path)
    payload = b"Synthetic model-moved artifact.\n"
    (workspace / "source.md").write_bytes(payload)
    (workspace / "archive").mkdir()
    replies = [
        {
            "tool_calls": [{
                "id": "synthetic-move",
                "type": "function",
                "function": {
                    "name": "move_file",
                    "arguments": json.dumps({
                        "source_path": "source.md",
                        "target_path": "archive/source.md",
                    }),
                },
            }],
        },
        {"content": "Synthetic move complete."},
    ]

    def chat(_alias: str, _body: bytes):
        reply = replies.pop(0)
        message = {
            "role": "assistant",
            "content": reply.get("content"),
            "tool_calls": reply.get("tool_calls"),
        }
        response = {
            "choices": [{
                "message": message,
                "finish_reason": "tool_calls" if reply.get("tool_calls") else "stop",
            }],
        }
        return 200, json.dumps(response).encode(), "application/json"

    agent = LocalAgentService(
        chat=chat,
        active_model=lambda: "example-model",
        allowed_roots=(tmp_path,),
        catalog=catalog,
        artifacts=artifacts,
        clock=lambda: T0,
        approval_wait_seconds=5,
    )
    live = agent.create(AgentSettings(
        workspace=str(workspace),
        project_id=project.project_id,
        title="Synthetic model move chat",
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        allow_writes=True,
    ))
    captured = agent.capture_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        command=CaptureAgentArtifact(
            path="source.md",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )

    agent.send(live.session_id, SendMessage(text="Move the synthetic artifact."))
    deadline = time.monotonic() + 5
    approval_id = None
    while time.monotonic() < deadline and approval_id is None:
        approval_id = agent.events(live.session_id).pending_approval_id
        if approval_id is None:
            time.sleep(0.02)
    assert approval_id is not None
    approval_event = [
        event
        for event in agent.events(live.session_id).events
        if event.kind == "approval_required"
    ][-1]
    assert approval_event.tool == "move_file"
    agent.approve(
        live.session_id,
        approval_id,
        ApprovalDecision(approved=True),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and agent.get(live.session_id).running:
        time.sleep(0.02)
    assert agent.get(live.session_id).running is False

    moved = agent.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=captured.artifact_id,
    )
    assert moved.artifact_id == captured.artifact_id
    assert moved.path == "archive/source.md"
    assert moved.availability == "available"
    assert [version.provenance for version in moved.versions] == [
        "verified_output",
        "reviewed_move",
    ]
    agent.shutdown()


def test_verified_move_does_not_relocate_stale_artifact_lineage(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, _session, workspace = _fixture(tmp_path)
    captured_payload = b"Synthetic captured revision.\n"
    moved_payload = b"Synthetic changed revision.\n"
    source = workspace / "draft.md"
    source.write_bytes(captured_payload)
    (workspace / "archive").mkdir()

    agent = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
        artifacts=artifacts,
        clock=lambda: T0,
    )
    live = agent.create(AgentSettings(
        workspace=str(workspace),
        project_id=project.project_id,
        title="Synthetic stale move chat",
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    ))
    captured = agent.capture_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        command=CaptureAgentArtifact(
            path="draft.md",
            expected_sha256=hashlib.sha256(captured_payload).hexdigest(),
            expected_byte_size=len(captured_payload),
        ),
    )

    source.write_bytes(moved_payload)
    moved_digest = hashlib.sha256(moved_payload).hexdigest()
    preview = agent.preview_workspace_move(
        live.session_id,
        WorkspaceMovePreviewCommand(
            source_path="draft.md",
            target_path="archive/final.md",
            expected_revision=moved_digest,
        ),
    )
    result = agent.apply_workspace_move(
        live.session_id,
        preview.preview_id,
        WorkspaceMoveApplyCommand(
            source_path=preview.source_path,
            target_path=preview.target_path,
            expected_revision=preview.expected_revision,
            confirmation=WORKSPACE_MOVE_CONFIRMATION,
        ),
    )
    assert result.revision == moved_digest

    stale = agent.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=captured.artifact_id,
    )
    assert stale.path == "draft.md"
    assert stale.version_count == 1
    assert stale.availability == "missing"
    assert (workspace / "archive" / "final.md").read_bytes() == moved_payload


def test_verified_move_refuses_to_merge_distinct_artifact_lineages(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, _session, workspace = _fixture(tmp_path)
    source_payload = b"Synthetic source lineage.\n"
    target_payload = b"Synthetic target lineage.\n"
    source_path = workspace / "source.md"
    target_path = workspace / "target.md"
    source_path.write_bytes(source_payload)
    target_path.write_bytes(target_payload)

    agent = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
        artifacts=artifacts,
        clock=lambda: T0,
    )
    live = agent.create(AgentSettings(
        workspace=str(workspace),
        project_id=project.project_id,
        title="Synthetic collision move chat",
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    ))
    source_artifact = agent.capture_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        command=CaptureAgentArtifact(
            path="source.md",
            expected_sha256=hashlib.sha256(source_payload).hexdigest(),
            expected_byte_size=len(source_payload),
        ),
    )
    target_artifact = agent.capture_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        command=CaptureAgentArtifact(
            path="target.md",
            expected_sha256=hashlib.sha256(target_payload).hexdigest(),
            expected_byte_size=len(target_payload),
        ),
    )

    # The workspace target is absent, so the reviewed move itself is valid,
    # but a stale artifact card still owns the target path. The lineages must
    # never be silently merged or overwritten after the filesystem effect.
    target_path.unlink()
    source_digest = hashlib.sha256(source_payload).hexdigest()
    preview = agent.preview_workspace_move(
        live.session_id,
        WorkspaceMovePreviewCommand(
            source_path="source.md",
            target_path="target.md",
            expected_revision=source_digest,
        ),
    )
    with pytest.raises(LocalAgentError) as conflict:
        agent.apply_workspace_move(
            live.session_id,
            preview.preview_id,
            WorkspaceMoveApplyCommand(
                source_path=preview.source_path,
                target_path=preview.target_path,
                expected_revision=preview.expected_revision,
                confirmation=WORKSPACE_MOVE_CONFIRMATION,
            ),
        )
    assert conflict.value.code == "agent_artifact_relocation_target_conflict"
    assert not source_path.exists()
    assert target_path.read_bytes() == source_payload

    source_after = agent.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=source_artifact.artifact_id,
    )
    target_after = agent.get_artifact(
        project_id=project.project_id,
        session_id=live.session_id,
        artifact_id=target_artifact.artifact_id,
    )
    assert (source_after.path, source_after.version_count, source_after.availability) == (
        "source.md",
        1,
        "missing",
    )
    assert (target_after.path, target_after.version_count, target_after.availability) == (
        "target.md",
        1,
        "stale",
    )
    change_set = agent.change_set(live.session_id)
    assert change_set.tracking_failed is True
    assert change_set.coverage == "partial"


def test_suffixes_do_not_claim_binary_preview_without_byte_validation(tmp_path: Path) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    disguised = b"synthetic text, not an image\n"
    (workspace / "pretend.png").write_bytes(disguised)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="pretend.png", payload=disguised),
    )
    head = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    ).artifacts[0]
    assert head.kind == "binary"
    assert head.latest_version.preview_kind == "download_only"
    with pytest.raises(AgentArtifactError) as unsupported:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=head.artifact_id,
            version_id=head.latest_version.version_id,
            workspace=workspace,
            download=False,
        )
    assert unsupported.value.code == "agent_artifact_preview_unsupported"


def test_native_capture_classifies_bounded_image_pdf_text_and_active_content(
    tmp_path: Path,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    cases = (
        ("picture.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (2).to_bytes(4, "big") + (3).to_bytes(4, "big"), "image", "image"),
        ("report.pdf", b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", "pdf", "pdf"),
        ("guide.md", b"# Synthetic guide\n", "markdown", "text"),
        ("page.html", b"<script>synthetic()</script>\n", "document", "download_only"),
    )
    for path, payload, expected_kind, expected_preview in cases:
        (workspace / path).write_bytes(payload)
        capture_preview = artifacts.preview_capture(
            project_id=project.project_id,
            session_id=session.session_id,
            workspace=workspace,
            command=PreviewAgentArtifactCapture(path=path),
        )
        assert capture_preview.kind == expected_kind
        assert capture_preview.preview_kind == expected_preview
        assert capture_preview.sha256 == hashlib.sha256(payload).hexdigest()
        assert capture_preview.byte_size == len(payload)
        assert capture_preview.requires_native_confirmation is True
        assert capture_preview.file_content_included is False
        detail = artifacts.capture(
            project_id=project.project_id,
            session_id=session.session_id,
            workspace=workspace,
            command=CaptureAgentArtifact(
                path=path,
                expected_sha256=capture_preview.sha256,
                expected_byte_size=capture_preview.byte_size,
            ),
        )
        assert detail.kind == expected_kind
        assert detail.latest_version.preview_kind == expected_preview
        assert detail.availability == "available"
        if expected_preview == "download_only":
            with pytest.raises(AgentArtifactError) as unsupported:
                artifacts.content(
                    project_id=project.project_id,
                    session_id=session.session_id,
                    artifact_id=detail.artifact_id,
                    version_id=detail.latest_version.version_id,
                    workspace=workspace,
                    download=False,
                )
            assert unsupported.value.code == "agent_artifact_preview_unsupported"
            downloaded = artifacts.content(
                project_id=project.project_id,
                session_id=session.session_id,
                artifact_id=detail.artifact_id,
                version_id=detail.latest_version.version_id,
                workspace=workspace,
                download=True,
            )
            assert downloaded.content_type == "application/octet-stream"


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        (
            "encrypted.pdf",
            b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Encrypt 2 0 R >>\nendobj\n%%EOF\n",
        ),
        (
            "truncated.pdf",
            b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
        ),
        (
            "trailing-spoof.pdf",
            b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\nnot-pdf-trailer",
        ),
        (
            "header-spoof.pdf",
            b"%PDF-9.9\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n",
        ),
    ),
)
def test_pdf_preview_admission_refuses_encrypted_truncated_and_spoofed_bytes(
    tmp_path: Path,
    path: str,
    payload: bytes,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    (workspace / path).write_bytes(payload)

    capture_preview = artifacts.preview_capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=PreviewAgentArtifactCapture(path=path),
    )
    assert capture_preview.kind == "binary"
    assert capture_preview.media_type == "application/octet-stream"
    assert capture_preview.preview_kind == "download_only"

    detail = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path=path,
            expected_sha256=capture_preview.sha256,
            expected_byte_size=capture_preview.byte_size,
        ),
    )
    with pytest.raises(AgentArtifactError) as inert:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=detail.artifact_id,
            version_id=detail.latest_version.version_id,
            workspace=workspace,
            download=False,
        )
    assert inert.value.code == "agent_artifact_preview_unsupported"
    exact_download = artifacts.content(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=detail.artifact_id,
        version_id=detail.latest_version.version_id,
        workspace=workspace,
        download=True,
    )
    assert exact_download.payload == payload
    assert exact_download.content_type == "application/octet-stream"


def test_modern_office_artifact_has_exact_inert_preview_and_separate_download(
    tmp_path: Path,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = _synthetic_docx()
    target = workspace / "reviewed.docx"
    target.write_bytes(payload)
    detail = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="reviewed.docx",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )

    version = detail.latest_version
    assert detail.kind == "document"
    assert version.preview_kind == "document"
    assert version.media_type == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    preview = artifacts.document_preview(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=detail.artifact_id,
        version_id=version.version_id,
        workspace=workspace,
    )
    assert preview.source_sha256 == version.sha256
    assert preview.source_byte_size == version.byte_size
    assert preview.sections[0].paragraphs == ("Synthetic reviewed document.",)

    with pytest.raises(AgentArtifactError) as raw_preview:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=detail.artifact_id,
            version_id=version.version_id,
            workspace=workspace,
            download=False,
        )
    assert raw_preview.value.code == "agent_artifact_preview_unsupported"
    download = artifacts.content(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=detail.artifact_id,
        version_id=version.version_id,
        workspace=workspace,
        download=True,
    )
    assert download.payload == payload
    assert download.content_type == "application/octet-stream"

    target.write_bytes(payload + b"stale")
    with pytest.raises(AgentArtifactError) as stale:
        artifacts.document_preview(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=detail.artifact_id,
            version_id=version.version_id,
            workspace=workspace,
        )
    assert stale.value.code == "agent_artifact_stale"


def test_lineage_export_is_revision_bound_content_free_and_exact_byte_verified(
    tmp_path: Path,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"synthetic portable artifact\n"
    target = workspace / "portable.md"
    target.write_bytes(payload)
    captured = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="portable.md",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
            title="Portable synthetic artifact",
        ),
    )

    exported = artifacts.export_lineage(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=captured.artifact_id,
        workspace=workspace,
        command=ExportAgentArtifact(
            expected_revision=captured.revision,
            version_id=captured.latest_version.version_id,
        ),
    )
    body = exported.model_dump(mode="json")
    serialized = json.dumps(body, sort_keys=True)
    assert body["contract_version"] == "agent-artifact-export.v1"
    assert body["exported_at"] == T0.isoformat().replace("+00:00", "Z")
    assert body["artifact"]["artifact_id"] == captured.artifact_id
    assert body["selected_version"]["version_id"] == captured.latest_version.version_id
    assert body["evidence"] == {
        "verification": "exact_current_workspace_readback",
        "algorithm": "sha256",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
        "verified": True,
    }
    assert body["content_included"] is False
    assert body["absolute_path_included"] is False
    assert body["sensitivity"] == "sensitive_local_metadata"
    assert str(workspace) not in serialized
    assert payload.decode().strip() not in serialized

    renamed = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=captured.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=captured.revision,
            operation="rename",
            title="Renamed portable artifact",
        ),
    )
    with pytest.raises(AgentArtifactError) as stale_revision:
        artifacts.export_lineage(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=captured.artifact_id,
            workspace=workspace,
            command=ExportAgentArtifact(
                expected_revision=captured.revision,
                version_id=captured.latest_version.version_id,
            ),
        )
    assert stale_revision.value.code == "agent_artifact_revision_conflict"

    target.write_bytes(payload + b"changed")
    with pytest.raises(AgentArtifactError) as stale_bytes:
        artifacts.export_lineage(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=captured.artifact_id,
            workspace=workspace,
            command=ExportAgentArtifact(
                expected_revision=renamed.revision,
                version_id=captured.latest_version.version_id,
            ),
        )
    assert stale_bytes.value.code == "agent_artifact_stale"


def test_lineage_export_refuses_metadata_change_after_exact_byte_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"synthetic race-safe export\n"
    (workspace / "race.md").write_bytes(payload)
    captured = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="race.md",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )
    original_content = artifacts.content

    def content_then_rename(**kwargs):
        content = original_content(**kwargs)
        artifacts.update_artifact(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=captured.artifact_id,
            command=UpdateAgentArtifact(
                expected_revision=captured.revision,
                operation="rename",
                title="Changed during synthetic export",
            ),
        )
        return content

    monkeypatch.setattr(artifacts, "content", content_then_rename)
    with pytest.raises(AgentArtifactError) as changed:
        artifacts.export_lineage(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=captured.artifact_id,
            workspace=workspace,
            command=ExportAgentArtifact(
                expected_revision=captured.revision,
                version_id=captured.latest_version.version_id,
            ),
        )
    assert changed.value.code == "agent_artifact_revision_conflict"


def test_capture_is_revision_bound_and_metadata_only_sessions_are_ineligible(
    tmp_path: Path,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"synthetic capture\n"
    (workspace / "result.txt").write_bytes(payload)
    with pytest.raises(AgentArtifactError) as changed:
        artifacts.capture(
            project_id=project.project_id,
            session_id=session.session_id,
            workspace=workspace,
            command=CaptureAgentArtifact(
                path="result.txt",
                expected_sha256="0" * 64,
                expected_byte_size=len(payload),
            ),
        )
    assert changed.value.code == "agent_artifact_revision_changed"

    _db2, _cat2, metadata_artifacts, project2, session2, workspace2 = _fixture(
        tmp_path / "metadata",
        retained=False,
    )
    (workspace2 / "result.txt").write_bytes(payload)
    with pytest.raises(AgentArtifactError) as retention:
        metadata_artifacts.capture(
            project_id=project2.project_id,
            session_id=session2.session_id,
            workspace=workspace2,
            command=CaptureAgentArtifact(
                path="result.txt",
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                expected_byte_size=len(payload),
            ),
        )
    assert retention.value.code == "agent_artifact_retention_required"


def test_capture_preview_is_content_free_and_changed_revision_is_refused(
    tmp_path: Path,
) -> None:
    _database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    target = workspace / "reports" / "result.txt"
    target.parent.mkdir()
    target.write_bytes(b"Synthetic result v1.\n")

    preview = artifacts.preview_capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=PreviewAgentArtifactCapture(
            path="reports/result.txt",
            title="Reviewed result",
        ),
    )
    assert preview.model_dump() == {
        "contract_version": "agent-artifact-capture-preview.v1",
        "project_id": project.project_id,
        "session_id": session.session_id,
        "path": "reports/result.txt",
        "title": "Reviewed result",
        "kind": "text",
        "media_type": "text/plain; charset=utf-8",
        "preview_kind": "text",
        "sha256": hashlib.sha256(b"Synthetic result v1.\n").hexdigest(),
        "byte_size": len(b"Synthetic result v1.\n"),
        "requires_native_confirmation": True,
        "file_content_included": False,
    }

    target.write_bytes(b"Synthetic result v2.\n")
    with pytest.raises(AgentArtifactError) as changed:
        artifacts.capture(
            project_id=project.project_id,
            session_id=session.session_id,
            workspace=workspace,
            command=CaptureAgentArtifact(
                path=preview.path,
                title=preview.title,
                expected_sha256=preview.sha256,
                expected_byte_size=preview.byte_size,
            ),
        )
    assert changed.value.code == "agent_artifact_revision_changed"


def test_artifacts_are_exact_project_bound_and_deleted_with_the_chat(tmp_path: Path) -> None:
    database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    other = catalog.create_project(CreateAgentProject(name="Other synthetic project"))
    payload = b"synthetic isolated artifact\n"
    (workspace / "isolated.txt").write_bytes(payload)
    created = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="isolated.txt",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )
    with pytest.raises(AgentArtifactError) as isolated:
        artifacts.get_artifact(
            project_id=other.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            workspace=workspace,
        )
    assert isolated.value.code == "agent_catalog_session_not_found"

    with database.connect() as connection:
        with pytest.raises(AgentArtifactError):
            # Application repository maps immutable-trigger failures to a
            # closed error; direct SQL below proves the trigger itself.
            try:
                connection.execute(
                    "UPDATE agent_artifact_versions SET byte_size=byte_size+1"
                )
            except sqlite3.IntegrityError as error:
                raise AgentArtifactError("agent_artifact_conflict") from error
    current = catalog.get_session(session.session_id)
    catalog.delete_session(
        session.session_id,
        expected_catalog_revision=current.revision,
        expected_history_revision=current.history_revision,
    )
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM agent_artifacts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM agent_artifact_versions").fetchone()[0] == 0


def test_artifact_lifecycle_is_revision_bound_recoverable_and_survives_restart(
    tmp_path: Path,
) -> None:
    database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    first = b"Synthetic lifecycle v1.\n"
    target = workspace / "lifecycle.txt"
    target.write_bytes(first)
    created = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="lifecycle.txt",
            expected_sha256=hashlib.sha256(first).hexdigest(),
            expected_byte_size=len(first),
        ),
    )

    renamed = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=created.revision,
            operation="rename",
            title="Reviewed lifecycle output",
        ),
    )
    assert renamed.title == "Reviewed lifecycle output"
    assert renamed.version_count == 1
    assert renamed.revision == 2

    second = b"Synthetic lifecycle v2.\n"
    target.write_bytes(second)
    updated = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="lifecycle.txt",
            expected_sha256=hashlib.sha256(second).hexdigest(),
            expected_byte_size=len(second),
        ),
    )
    assert updated.title == "Reviewed lifecycle output"
    assert updated.version_count == 2
    assert updated.revision == 3

    archived = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=updated.revision,
            operation="archive",
        ),
    )
    assert archived.lifecycle_state == "archived"
    assert archived.archived_at == T0
    active = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        view="active",
    )
    assert active.artifacts == ()
    assert active.counts.model_dump() == {
        "active": 0,
        "archived": 1,
        "removed": 0,
        "total": 1,
    }

    removed = artifacts.remove_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=RemoveAgentArtifact(
            expected_revision=archived.revision,
            confirmation="move_archived_artifact_record_to_removed",
        ),
    )
    assert removed.lifecycle_state == "removed"
    assert removed.removed_at == T0
    assert target.read_bytes() == second
    with pytest.raises(AgentArtifactError) as unavailable:
        artifacts.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            version_id=updated.latest_version.version_id,
            workspace=workspace,
            download=True,
        )
    assert unavailable.value.code == "agent_artifact_removed"

    restarted = AgentArtifactService(
        SqliteAgentArtifactRepository(AgentCatalogSqliteDatabase(database.path)),
        catalog,
        clock=lambda: T0,
        id_factory=_ids(500).__next__,
    )
    removed_list = restarted.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        view="removed",
    )
    assert [item.artifact_id for item in removed_list.artifacts] == [created.artifact_id]
    recovered = restarted.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=removed.revision,
            operation="recover",
        ),
    )
    assert recovered.lifecycle_state == "archived"
    restored = restarted.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=recovered.revision,
            operation="restore",
        ),
    )
    assert restored.lifecycle_state == "active"
    assert restored.archived_at is None
    assert restored.removed_at is None
    assert restarted.get_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        workspace=workspace,
    ).availability == "available"


def test_artifact_lifecycle_rejects_stale_cross_scope_and_invalid_transitions(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    other = catalog.create_project(CreateAgentProject(name="Other lifecycle project"))
    payload = b"Synthetic lifecycle guard.\n"
    (workspace / "guard.txt").write_bytes(payload)
    created = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="guard.txt",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )
    with pytest.raises(AgentArtifactError) as cross_scope:
        artifacts.update_artifact(
            project_id=other.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            command=UpdateAgentArtifact(
                expected_revision=created.revision,
                operation="archive",
            ),
        )
    assert cross_scope.value.code == "agent_catalog_session_not_found"

    with pytest.raises(AgentArtifactError) as archive_required:
        artifacts.remove_artifact(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            command=RemoveAgentArtifact(
                expected_revision=created.revision,
                confirmation="move_archived_artifact_record_to_removed",
            ),
        )
    assert archive_required.value.code == "agent_artifact_archive_required"

    archived = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=created.revision,
            operation="archive",
        ),
    )
    with pytest.raises(AgentArtifactError) as stale:
        artifacts.update_artifact(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            command=UpdateAgentArtifact(
                expected_revision=created.revision,
                operation="restore",
            ),
        )
    assert stale.value.code == "agent_artifact_revision_conflict"
    with pytest.raises(AgentArtifactError) as wrong_state:
        artifacts.update_artifact(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=created.artifact_id,
            command=UpdateAgentArtifact(
                expected_revision=archived.revision,
                operation="archive",
            ),
        )
    assert wrong_state.value.code == "agent_artifact_state_conflict"


def test_removed_reviewed_artifact_does_not_resurrect_until_explicit_recovery(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    first = b"Synthetic reviewed lifecycle v1.\n"
    target = workspace / "reviewed.md"
    target.write_bytes(first)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=1,
        receipt=_receipt(path="reviewed.md", payload=first),
    )
    created = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
    ).artifacts[0]
    renamed = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=created.revision,
            operation="rename",
            title="Reviewed lifecycle record",
        ),
    )
    archived = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=renamed.revision,
            operation="archive",
        ),
    )
    removed = artifacts.remove_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=RemoveAgentArtifact(
            expected_revision=archived.revision,
            confirmation="move_archived_artifact_record_to_removed",
        ),
    )

    second = b"Synthetic reviewed lifecycle v2.\n"
    target.write_bytes(second)
    _append_write(
        catalog,
        project.project_id,
        session.session_id,
        seq=2,
        receipt=_receipt(path="reviewed.md", payload=second, before=first),
    )
    still_removed = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        view="removed",
    ).artifacts[0]
    assert still_removed.artifact_id == created.artifact_id
    assert still_removed.lifecycle_state == "removed"
    assert still_removed.version_count == 1
    assert still_removed.revision == removed.revision
    assert still_removed.title == "Reviewed lifecycle record"
    with pytest.raises(AgentArtifactError) as preview_blocked:
        artifacts.preview_capture(
            project_id=project.project_id,
            session_id=session.session_id,
            workspace=workspace,
            command=PreviewAgentArtifactCapture(path="reviewed.md"),
        )
    assert preview_blocked.value.code == "agent_artifact_removed"

    recovered = artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=still_removed.revision,
            operation="recover",
        ),
    )
    artifacts.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=created.artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=recovered.revision,
            operation="restore",
        ),
    )
    resynchronized = artifacts.list_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        view="active",
    ).artifacts[0]
    assert resynchronized.lifecycle_state == "active"
    assert resynchronized.version_count == 2
    assert resynchronized.latest_version.source_event_seq == 2
    assert resynchronized.title == "Reviewed lifecycle record"


def test_artifact_path_contract_rejects_traversal_and_absolute_paths() -> None:
    for path in ("../outside.txt", "/absolute.txt", r"C:\outside.txt", r"folder\file.txt"):
        with pytest.raises(ValidationError):
            CaptureAgentArtifact(
                path=path,
                expected_sha256="0" * 64,
                expected_byte_size=0,
            )
        with pytest.raises(ValidationError):
            PreviewAgentArtifactCapture(path=path)

    for title in ("", " ", " padded"):
        with pytest.raises(ValidationError):
            PreviewAgentArtifactCapture(path="result.txt", title=title)


def test_artifact_pages_cover_full_capacity_and_reject_mutation_and_scope_replay(
    tmp_path: Path,
) -> None:
    database, catalog, artifacts, project, session, _workspace = _fixture(tmp_path)
    for index in range(205):
        payload = f"Synthetic artifact {index:03d}.\n".encode()
        _append_write(
            catalog,
            project.project_id,
            session.session_id,
            seq=index + 1,
            receipt=_receipt(path=f"generated/item-{index:03d}.md", payload=payload),
        )

    first = artifacts.page_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        limit=100,
    )
    second = artifacts.page_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        limit=100,
        offset=first.next_offset,
        snapshot=first.snapshot,
    )
    third = artifacts.page_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        limit=100,
        offset=second.next_offset,
        snapshot=first.snapshot,
    )
    loaded = tuple(
        artifact.artifact_id
        for page in (first, second, third)
        for artifact in page.artifacts
    )
    assert first.total == 205
    assert first.counts.active == 205
    assert len(loaded) == len(set(loaded)) == 205
    assert third.complete is True and third.next_offset is None

    restarted_catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=lambda: "f" * 32,
    )
    restarted = AgentArtifactService(
        SqliteAgentArtifactRepository(database),
        restarted_catalog,
        clock=lambda: T0,
        id_factory=_ids(10_000).__next__,
    )
    assert restarted.page_artifacts(
        project_id=project.project_id,
        session_id=session.session_id,
        limit=100,
    ).snapshot == first.snapshot
    with pytest.raises(AgentArtifactError) as cross_view:
        restarted.page_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
            view="all",
            limit=100,
            offset=100,
            snapshot=first.snapshot,
        )
    assert cross_view.value.code == "agent_artifact_page_snapshot_conflict"
    with pytest.raises(AgentArtifactError) as missing_snapshot:
        restarted.page_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
            limit=100,
            offset=100,
        )
    assert missing_snapshot.value.code == "agent_artifact_page_snapshot_required"
    with pytest.raises(AgentArtifactError) as out_of_range:
        restarted.page_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
            limit=100,
            offset=206,
            snapshot=first.snapshot,
        )
    assert out_of_range.value.code == "agent_artifact_page_out_of_range"

    changed = restarted.update_artifact(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=first.artifacts[0].artifact_id,
        command=UpdateAgentArtifact(
            expected_revision=first.artifacts[0].revision,
            operation="archive",
        ),
    )
    assert changed.lifecycle_state == "archived"
    with pytest.raises(AgentArtifactError) as stale:
        restarted.page_artifacts(
            project_id=project.project_id,
            session_id=session.session_id,
            limit=100,
            offset=100,
            snapshot=first.snapshot,
        )
    assert stale.value.code == "agent_artifact_page_snapshot_conflict"


def test_artifact_http_surface_is_private_native_gated_range_bound_and_inert(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    service = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        catalog=catalog,
        artifacts=artifacts,
    )
    confirmations: list[str] = []

    def native(request: Request) -> None:
        if request.headers.get("X-Synthetic-Native") != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append(request.url.path)

    application = FastAPI()
    application.include_router(create_local_agent_router(lambda: None, native, service))
    payload = b"Synthetic artifact preview.\n"
    target = workspace / "preview.md"
    target.write_bytes(payload)
    path = (
        f"/v1/agent/projects/{project.project_id}/sessions/"
        f"{session.session_id}/artifacts"
    )
    capture = {
        "path": "preview.md",
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_byte_size": len(payload),
    }
    with TestClient(application, base_url="http://127.0.0.1") as client:
        capture_preview_response = client.post(
            f"{path}/capture-preview",
            json={"path": "preview.md", "title": "Synthetic preview"},
        )
        assert capture_preview_response.status_code == 200
        assert capture_preview_response.headers["cache-control"] == "no-store, private"
        capture_preview = capture_preview_response.json()
        assert capture_preview["contract_version"] == "agent-artifact-capture-preview.v1"
        assert capture_preview["project_id"] == project.project_id
        assert capture_preview["session_id"] == session.session_id
        assert capture_preview["title"] == "Synthetic preview"
        assert capture_preview["sha256"] == capture["expected_sha256"]
        assert capture_preview["byte_size"] == capture["expected_byte_size"]
        assert capture_preview["file_content_included"] is False
        assert confirmations == []

        assert client.post(path, json=capture).status_code == 403
        created_response = client.post(
            path,
            headers={"X-Synthetic-Native": "confirmed"},
            json=capture,
        )
        assert created_response.status_code == 201, created_response.text
        assert created_response.headers["cache-control"] == "no-store, private"
        created = created_response.json()
        assert created["availability"] == "available"
        assert confirmations == [path]

        listed = client.get(path)
        assert listed.status_code == 200
        assert listed.headers["cache-control"] == "no-store, private"
        assert len(listed.json()["artifacts"]) == 1

        page_response = client.get(f"{path}/page?limit=1")
        assert page_response.status_code == 200
        assert page_response.headers["cache-control"] == "no-store, private"
        page = page_response.json()
        assert page["contract_version"] == "agent-artifact-page.v1"
        assert page["total"] == 1
        assert page["complete"] is True
        assert page["artifacts"][0]["artifact_id"] == created["artifact_id"]

        detail_path = f"{path}/{created['artifact_id']}"
        detail = client.get(detail_path)
        assert detail.status_code == 200
        assert detail.json()["availability"] == "available"
        version = detail.json()["latest_version"]
        content_path = (
            f"{detail_path}/versions/{version['version_id']}/content"
        )
        partial = client.get(content_path, headers={"Range": "bytes=0-8"})
        assert partial.status_code == 206
        assert partial.content == payload[:9]
        assert partial.headers["content-range"] == f"bytes 0-8/{len(payload)}"
        assert partial.headers["accept-ranges"] == "bytes"
        assert partial.headers["cache-control"] == "no-store, private"
        assert partial.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert partial.headers["x-content-type-options"] == "nosniff"
        assert partial.headers["content-type"] == "text/plain; charset=utf-8"
        assert partial.headers["content-disposition"].startswith("inline;")

        exported = client.post(
            f"{detail_path}/export",
            json={
                "expected_revision": created["revision"],
                "version_id": version["version_id"],
            },
        )
        assert exported.status_code == 200
        assert exported.headers["cache-control"] == "no-store, private"
        assert exported.headers["pragma"] == "no-cache"
        export_body = exported.json()
        assert export_body["contract_version"] == "agent-artifact-export.v1"
        assert export_body["artifact"]["artifact_id"] == created["artifact_id"]
        assert export_body["selected_version"] == version
        assert export_body["evidence"]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert export_body["evidence"]["verified"] is True
        assert export_body["content_included"] is False
        assert export_body["absolute_path_included"] is False
        assert confirmations == [path]

        invalid = client.get(content_path, headers={"Range": "bytes=0-1,4-5"})
        assert invalid.status_code == 416
        assert invalid.headers["content-range"] == f"bytes */{len(payload)}"

        target.write_bytes(b"Changed artifact preview.\n")
        stale = client.get(content_path)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "agent_artifact_stale"
        stale_export = client.post(
            f"{detail_path}/export",
            json={
                "expected_revision": created["revision"],
                "version_id": version["version_id"],
            },
        )
        assert stale_export.status_code == 409
        assert stale_export.json()["detail"]["code"] == "agent_artifact_stale"

    assert UserPresenceApprovalManager.action_label("POST", path) is not None


def test_artifact_http_lifecycle_is_private_scoped_and_recoverable(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    service = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        catalog=catalog,
        artifacts=artifacts,
    )
    confirmations: list[str] = []

    def native(request: Request) -> None:
        if request.headers.get("X-Synthetic-Native") != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")
        confirmations.append(request.url.path)

    application = FastAPI()
    application.include_router(create_local_agent_router(lambda: None, native, service))
    payload = b"Synthetic lifecycle API artifact.\n"
    (workspace / "api-lifecycle.txt").write_bytes(payload)
    collection = (
        f"/v1/agent/projects/{project.project_id}/sessions/"
        f"{session.session_id}/artifacts"
    )
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created_response = client.post(
            collection,
            headers={"X-Synthetic-Native": "confirmed"},
            json={
                "path": "api-lifecycle.txt",
                "expected_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_byte_size": len(payload),
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        artifact_path = f"{collection}/{created['artifact_id']}"

        renamed = client.patch(
            artifact_path,
            json={
                "expected_revision": created["revision"],
                "operation": "rename",
                "title": "API lifecycle output",
            },
        )
        assert renamed.status_code == 200
        assert renamed.headers["cache-control"] == "no-store, private"
        assert renamed.json()["title"] == "API lifecycle output"
        archived = client.patch(
            artifact_path,
            json={
                "expected_revision": renamed.json()["revision"],
                "operation": "archive",
            },
        )
        assert archived.status_code == 200
        assert archived.json()["lifecycle_state"] == "archived"

        active = client.get(collection)
        assert active.json()["view"] == "active"
        assert active.json()["artifacts"] == []
        assert active.json()["counts"] == {
            "active": 0,
            "archived": 1,
            "removed": 0,
            "total": 1,
        }
        archived_list = client.get(f"{collection}?view=archived")
        assert [item["artifact_id"] for item in archived_list.json()["artifacts"]] == [
            created["artifact_id"]
        ]

        remove_path = f"{artifact_path}/remove"
        remove_body = {
            "expected_revision": archived.json()["revision"],
            "confirmation": "move_archived_artifact_record_to_removed",
        }
        assert client.post(remove_path, json=remove_body).status_code == 403
        removed = client.post(
            remove_path,
            headers={"X-Synthetic-Native": "confirmed"},
            json=remove_body,
        )
        assert removed.status_code == 200
        assert removed.json()["lifecycle_state"] == "removed"
        assert workspace.joinpath("api-lifecycle.txt").read_bytes() == payload
        assert confirmations == [collection, remove_path]
        assert client.get(artifact_path).status_code == 410
        removed_list = client.get(f"{collection}?view=removed")
        assert removed_list.json()["counts"]["removed"] == 1

        recovered = client.patch(
            artifact_path,
            json={
                "expected_revision": removed.json()["revision"],
                "operation": "recover",
            },
        )
        assert recovered.status_code == 200
        assert recovered.json()["lifecycle_state"] == "archived"
        restored = client.patch(
            artifact_path,
            json={
                "expected_revision": recovered.json()["revision"],
                "operation": "restore",
            },
        )
        assert restored.status_code == 200
        assert restored.json()["lifecycle_state"] == "active"

    assert UserPresenceApprovalManager.action_label("POST", remove_path) is not None


def test_document_preview_http_surface_is_private_exact_and_content_free(
    tmp_path: Path,
) -> None:
    _database, catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    service = LocalAgentService(
        chat=lambda _alias, _body: (200, b"{}", "application/json"),
        active_model=lambda: None,
        catalog=catalog,
        artifacts=artifacts,
    )

    def native(request: Request) -> None:
        if request.headers.get("X-Synthetic-Native") != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")

    application = FastAPI()
    application.include_router(create_local_agent_router(lambda: None, native, service))
    payload = _synthetic_docx()
    (workspace / "reviewed.docx").write_bytes(payload)
    collection = (
        f"/v1/agent/projects/{project.project_id}/sessions/"
        f"{session.session_id}/artifacts"
    )
    capture = {
        "path": "reviewed.docx",
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_byte_size": len(payload),
    }
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created_response = client.post(
            collection,
            headers={"X-Synthetic-Native": "confirmed"},
            json=capture,
        )
        assert created_response.status_code == 201
        created = created_response.json()
        version = created["latest_version"]
        base = (
            f"{collection}/{created['artifact_id']}/versions/"
            f"{version['version_id']}"
        )
        preview = client.get(f"{base}/preview")
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "no-store, private"
        assert preview.headers["pragma"] == "no-cache"
        body = preview.json()
        assert body["contract_version"] == "agent-document-preview.v1"
        assert body["project_id"] == project.project_id
        assert body["session_id"] == session.session_id
        assert body["artifact_id"] == created["artifact_id"]
        assert body["version_id"] == version["version_id"]
        assert body["source_sha256"] == version["sha256"]
        assert body["source_byte_size"] == version["byte_size"]
        assert body["sections"][0]["paragraphs"] == [
            "Synthetic reviewed document."
        ]

        raw = client.get(f"{base}/content")
        assert raw.status_code == 415
        assert raw.json()["detail"]["code"] == "agent_artifact_preview_unsupported"
        downloaded = client.get(f"{base}/content?download=true")
        assert downloaded.status_code == 200
        assert downloaded.content == payload
        assert downloaded.headers["content-type"] == "application/octet-stream"

        (workspace / "reviewed.docx").write_bytes(payload + b"changed")
        stale = client.get(f"{base}/preview")
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "agent_artifact_stale"


def test_catalog_v7_artifact_lineage_migrates_to_document_preview_without_rewrite(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    database, _catalog, artifacts, project, session, workspace = _fixture(tmp_path)
    payload = b"Synthetic retained artifact.\n"
    (workspace / "retained.txt").write_bytes(payload)
    existing = artifacts.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="retained.txt",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
        ),
    )

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        downgrade_agent_catalog_post_v20(connection)
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP TABLE mcp_managed_tool_call_receipts;
            DROP TABLE mcp_managed_project_tools;
            DROP TABLE mcp_managed_tool_snapshot_state;
            DROP TABLE mcp_managed_tools;
            DROP TABLE mcp_managed_tool_snapshots;
            DROP TABLE mcp_managed_local_swap_receipts;
            DROP TABLE mcp_managed_local_recovery_attempts;
            DROP TABLE mcp_managed_local_rollback_generations;
            DROP TABLE mcp_managed_local_update_payloads;
            DROP TABLE mcp_managed_local_operations;
            DROP TABLE mcp_managed_local_packages;
            DROP TABLE mcp_managed_lifecycle_receipts;
            DROP TABLE mcp_managed_lifecycle_state;
            DROP TABLE mcp_managed_probe_receipts;
            DROP TABLE mcp_managed_mutations;
            DROP TABLE mcp_managed_secret_references;
            DROP TABLE mcp_managed_project_bindings;
            DROP TABLE mcp_managed_requirements;
            DROP TABLE mcp_managed_servers;
            DROP TRIGGER agent_artifact_versions_immutable;
            DROP INDEX agent_artifact_source_event_idx;
            DROP INDEX agent_artifact_versions_order_idx;
            ALTER TABLE agent_artifact_versions RENAME TO agent_artifact_versions_v8;
            CREATE TABLE agent_artifact_versions (
                version_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL REFERENCES agent_artifacts(artifact_id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL CHECK(version_number >= 1),
                created_at TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                preview_kind TEXT NOT NULL CHECK(preview_kind IN ('text','image','pdf','download_only')),
                provenance TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                source_turn_id TEXT,
                source_event_seq INTEGER,
                UNIQUE(artifact_id, version_number)
            ) STRICT;
            INSERT INTO agent_artifact_versions SELECT * FROM agent_artifact_versions_v8;
            DROP TABLE agent_artifact_versions_v8;
            CREATE UNIQUE INDEX agent_artifact_source_event_idx
                ON agent_artifact_versions(artifact_id, source_event_seq)
                WHERE source_event_seq IS NOT NULL;
            CREATE INDEX agent_artifact_versions_order_idx
                ON agent_artifact_versions(artifact_id, version_number);
            CREATE TRIGGER agent_artifact_versions_immutable
                BEFORE UPDATE ON agent_artifact_versions
                BEGIN SELECT RAISE(ABORT, 'agent artifact versions are immutable'); END;
            ALTER TABLE agent_mcp_connections DROP COLUMN last_auth_rejected_at;
            ALTER TABLE agent_mcp_connections DROP COLUMN last_tool_source;
            ALTER TABLE agent_mcp_connections DROP COLUMN last_tool_outcome;
            ALTER TABLE agent_mcp_connections DROP COLUMN last_tool_name;
            ALTER TABLE agent_mcp_connections DROP COLUMN last_tool_at;
            DROP TABLE IF EXISTS agent_catalog_migration_checksums;
            DELETE FROM agent_catalog_schema_migrations WHERE version>=8;
            PRAGMA user_version = 7;
            COMMIT;
            """
        )

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        row = connection.execute(
            "SELECT version_id,sha256 FROM agent_artifact_versions"
        ).fetchone()
        assert tuple(row) == (
            existing.latest_version.version_id,
            existing.latest_version.sha256,
        )
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='agent_artifact_versions'"
        ).fetchone()[0]
        assert "'document'" in table_sql
        assert "'reviewed_move'" in table_sql
        artifact_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_artifacts)")
        }
        assert {"archived_at", "removed_at"}.issubset(artifact_columns)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            AGENT_CATALOG_SCHEMA_VERSION
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE agent_artifact_versions SET byte_size=byte_size+1"
            )
