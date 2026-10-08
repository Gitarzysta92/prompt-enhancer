"""Agent-08c deterministic soak and crash-boundary acceptance tests.

Every runtime and model in this module is an in-process synthetic double.  The
suite never launches a child process, opens a model, or touches owner data.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from prompt_enhancer.application.agent_artifacts import (
    AgentArtifactError,
    AgentArtifactService,
    CaptureAgentArtifact,
)
from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentRetentionPolicy,
    CreateAgentProject,
    ResumeAgentSession,
    StoredAgentEvent,
)
from prompt_enhancer.application.agent_hardening import AgentHardeningService
from prompt_enhancer.application.local_agent import (
    AgentSettings,
    LocalAgentError,
    LocalAgentService,
    SendMessage,
)
from prompt_enhancer.application.local_agent_editor import (
    WORKSPACE_APPLY_CONFIRMATION,
    WorkspaceApplyCommand,
    WorkspacePreviewCommand,
)
from prompt_enhancer.application.local_models import (
    ActivateLocalModel,
    AddLocalModel,
    ChatUpstream,
    DeviceMode,
    HardwareSummary,
    LocalModelService,
    RuntimeCapabilities,
    RuntimeCapabilityState,
    RuntimeCoordinatorState,
)
from prompt_enhancer.infrastructure.sqlite.agent_artifacts import (
    SqliteAgentArtifactRepository,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    _SCHEMA_V1,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.infrastructure.sqlite.agent_hardening import (
    SqliteAgentHardeningProbe,
)


T0 = datetime(2026, 8, 27, 21, 0, tzinfo=UTC)


def _catalog(database: AgentCatalogSqliteDatabase, start: int = 1) -> AgentCatalogService:
    ids = iter(f"{index:032x}" for index in range(start, start + 1_000))
    return AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=ids.__next__,
    )


def _wait_for_turn(service: LocalAgentService, session_id: str) -> None:
    worker = service._session(session_id).thread  # noqa: SLF001 - owned synthetic worker
    assert worker is not None
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert service.get(session_id).running is False


def _all_events(service: LocalAgentService, session_id: str):
    observed = []
    cursor = 0
    while True:
        page = service.events(session_id, after=cursor, limit=500)
        observed.extend(page.events)
        if not page.events or page.events[-1].seq >= page.last_seq:
            return tuple(observed)
        cursor = page.events[-1].seq


def _sse(choice: dict[str, object]) -> bytes:
    return (
        "data: " + json.dumps({"choices": [choice]}, separators=(",", ":")) + "\n\n"
    ).encode("utf-8")


def test_repeated_long_streams_remain_bounded_and_resume_cleanly_after_restart(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "synthetic-stream-workspace"
    workspace.mkdir()
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    catalog = _catalog(database)
    project = catalog.create_project(CreateAgentProject(name="Synthetic soak project"))
    turns_started = 0

    def open_chat(_alias: str, _body: bytes) -> ChatUpstream:
        nonlocal turns_started
        turn = turns_started
        turns_started += 1
        lines = [
            _sse(
                {
                    "delta": {"content": f"{turn:02d}:{index:02d} "},
                    "finish_reason": None,
                }
            )
            for index in range(64)
        ]
        lines.extend(
            (
                _sse({"delta": {}, "finish_reason": "stop"}),
                b"data: [DONE]\n\n",
            )
        )
        return ChatUpstream(200, "text/event-stream", lines=iter(lines))

    first = LocalAgentService(
        chat=lambda *_args: (503, b"{}", "application/json"),
        open_chat=open_chat,
        active_model=lambda: "synthetic-model",
        model_ready=lambda alias: alias == "synthetic-model",
        catalog=catalog,
        clock=lambda: T0,
    )
    created = first.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="synthetic-model",
            title="Synthetic stream soak",
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            max_steps=1,
        )
    )
    try:
        for turn in range(24):
            first.send(
                created.session_id,
                SendMessage(text=f"Synthetic bounded request {turn}."),
            )
            _wait_for_turn(first, created.session_id)
            view = first.get(created.session_id)
            assert view.pending_approval_id is None
            assert view.cleanup_unconfirmed is False

        events = _all_events(first, created.session_id)
        # Delta events are deliberately coalesced/retired as terminal answers
        # arrive; the terminal text proves every synthetic chunk was consumed.
        assert 0 < sum(event.kind == "assistant_delta" for event in events) < 24 * 64
        assistants = [event for event in events if event.kind == "assistant"]
        assert len(assistants) == 24
        assert all(len(event.text or "") == 64 * 6 - 1 for event in assistants)
        assert sum(event.kind == "done" for event in events) == 24
        assert len(events) < 4_000
        assert turns_started == 24

        persisted = SqliteAgentHardeningProbe(database).inspect()
        assert persisted.counts.history_events == 1 + 24 * 3
        assert persisted.counts.interrupted_retained_sessions == 0
        assert first.hardening_facts().running_turns == 0

        first.delete(created.session_id)
        restarted_catalog = _catalog(
            AgentCatalogSqliteDatabase(database.path),
            start=2_000,
        )
        record = restarted_catalog.get_session(created.session_id)
        restarted = LocalAgentService(
            chat=lambda *_args: (503, b"{}", "application/json"),
            active_model=lambda: "synthetic-model",
            model_ready=lambda alias: alias == "synthetic-model",
            catalog=restarted_catalog,
            clock=lambda: T0,
        )
        try:
            recovered = restarted.resume(
                project_id=project.project_id,
                session_id=created.session_id,
                command=ResumeAgentSession(
                    expected_catalog_revision=record.revision,
                    expected_history_revision=record.history_revision,
                ),
            )
            assert recovered.turns == 24
            assert recovered.recovery_state == "recovered"
            assert recovered.authority_revalidated is False
            assert recovered.pending_approval_id is None
            snapshot = AgentHardeningService(
                SqliteAgentHardeningProbe(
                    AgentCatalogSqliteDatabase(database.path)
                ),
                restarted,
            ).snapshot()
            assert snapshot.catalog.state == "ready"
            assert snapshot.catalog.counts is not None
            assert snapshot.catalog.counts.interrupted_retained_sessions == 0
            assert snapshot.recovery_actions == (
                "revalidate_recovered_authority",
            )
        finally:
            restarted.shutdown(timeout=1)
    finally:
        first.shutdown(timeout=1)


def test_approval_and_command_crash_phases_resume_without_pending_authority(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "synthetic-crash-workspace"
    workspace.mkdir()
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    catalog = _catalog(database)
    project = catalog.create_project(CreateAgentProject(name="Crash phase project"))
    session_ids = ("a" * 32, "b" * 32)
    for index, (session_id, tool) in enumerate(
        zip(session_ids, ("write_file", "run_command"), strict=True),
        start=1,
    ):
        settings = AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            model_alias="synthetic-model",
            allow_writes=True,
            allow_commands=True,
            allow_web=True,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
        profile = LocalAgentService._history_profile(settings)  # noqa: SLF001
        assert profile is not None
        catalog.register_live_session(
            session_id=session_id,
            project_id=project.project_id,
            title=f"Synthetic {tool} crash",
            workspace=workspace,
            model_alias="synthetic-model",
            created_at=T0,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
            profile_json=profile,
        )
        turn_id = f"{index + 20:032x}"
        catalog.append_history_event(
            project_id=project.project_id,
            session_id=session_id,
            expected_history_revision=0,
            event=StoredAgentEvent(
                seq=1,
                at=T0,
                kind="user",
                text=f"Synthetic {tool} request.",
                turn_id=turn_id,
            ),
        )
        catalog.append_history_event(
            project_id=project.project_id,
            session_id=session_id,
            expected_history_revision=1,
            event=StoredAgentEvent(
                seq=2,
                at=T0,
                kind="tool_call",
                tool=tool,
                call_id=f"synthetic-call-{index}",
                turn_id=turn_id,
            ),
        )

    observed = SqliteAgentHardeningProbe(database).inspect().counts
    assert observed.interrupted_retained_sessions == 2
    for session_id in session_ids:
        exported = catalog.export_history(
            project_id=project.project_id,
            session_id=session_id,
        ).model_dump_json()
        for prohibited in (
            "approval_id",
            "arguments",
            "preview",
            "SYNTHETIC_COMMAND_ARGUMENT_CANARY",
        ):
            assert prohibited not in exported

    restarted = LocalAgentService(
        chat=lambda *_args: (503, b"{}", "application/json"),
        active_model=lambda: "synthetic-model",
        model_ready=lambda alias: alias == "synthetic-model",
        catalog=_catalog(AgentCatalogSqliteDatabase(database.path), start=3_000),
        clock=lambda: T0,
    )
    try:
        for session_id in session_ids:
            record = restarted.catalog.get_session(session_id)  # type: ignore[union-attr]
            recovered = restarted.resume(
                project_id=project.project_id,
                session_id=session_id,
                command=ResumeAgentSession(
                    expected_catalog_revision=record.revision,
                    expected_history_revision=record.history_revision,
                ),
            )
            assert recovered.recovery_state == "interrupted"
            assert recovered.pending_approval_id is None
            assert recovered.authority_revalidated is False
            assert recovered.settings.allow_writes is False
            assert recovered.settings.allow_commands is False
            assert recovered.settings.allow_web is False
        facts = restarted.hardening_facts()
        assert facts.recovered_read_only == 2
        assert facts.pending_approvals == 0
    finally:
        restarted.shutdown(timeout=1)


def test_workspace_preview_capability_does_not_survive_a_restart(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "synthetic-preview-workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    catalog = _catalog(database)
    project = catalog.create_project(CreateAgentProject(name="Preview project"))
    first = LocalAgentService(
        chat=lambda *_args: (503, b"{}", "application/json"),
        active_model=lambda: "synthetic-model",
        catalog=catalog,
        clock=lambda: T0,
    )
    created = first.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        )
    )
    current = first.workspace_file(created.session_id, "notes.txt")
    preview = first.preview_workspace_edit(
        created.session_id,
        WorkspacePreviewCommand(
            path="notes.txt",
            content="after\n",
            expected_revision=current.revision,
            line_ending=current.line_ending,
        ),
    )

    first.shutdown(timeout=1)
    restarted_catalog = _catalog(
        AgentCatalogSqliteDatabase(database.path),
        start=4_000,
    )
    restarted = LocalAgentService(
        chat=lambda *_args: (503, b"{}", "application/json"),
        active_model=lambda: "synthetic-model",
        catalog=restarted_catalog,
        clock=lambda: T0,
    )
    try:
        record = restarted_catalog.get_session(created.session_id)
        recovered = restarted.resume(
            project_id=project.project_id,
            session_id=created.session_id,
            command=ResumeAgentSession(
                expected_catalog_revision=record.revision,
                expected_history_revision=record.history_revision,
            ),
        )
        with pytest.raises(LocalAgentError) as missing:
            restarted.apply_workspace_edit(
                recovered.session_id,
                preview.preview_id,
                WorkspaceApplyCommand(
                    path=preview.path,
                    content="after\n",
                    expected_revision=preview.expected_revision,
                    proposed_revision=preview.proposed_revision,
                    line_ending=preview.line_ending,
                    confirmation=WORKSPACE_APPLY_CONFIRMATION,
                ),
            )
        assert missing.value.code == "workspace_preview_not_found"
        assert target.read_text(encoding="utf-8") == "before\n"
        assert restarted.change_set(recovered.session_id).files == ()
        assert recovered.authority_revalidated is False
    finally:
        restarted.shutdown(timeout=1)


def test_artifact_restart_rehashes_bytes_and_rejects_a_stale_view(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "synthetic-artifact-workspace"
    workspace.mkdir()
    target = workspace / "report.md"
    payload = b"# Synthetic report\n"
    target.write_bytes(payload)
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    catalog = _catalog(database)
    project = catalog.create_project(CreateAgentProject(name="Artifact project"))
    session = catalog.register_live_session(
        session_id="c" * 32,
        project_id=project.project_id,
        title="Artifact crash chat",
        workspace=workspace,
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    ids = iter(f"{index:032x}" for index in range(5_000, 5_100))
    first = AgentArtifactService(
        SqliteAgentArtifactRepository(database),
        catalog,
        clock=lambda: T0,
        id_factory=ids.__next__,
    )
    captured = first.capture(
        project_id=project.project_id,
        session_id=session.session_id,
        workspace=workspace,
        command=CaptureAgentArtifact(
            path="report.md",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_byte_size=len(payload),
            title="Synthetic report",
        ),
    )

    restarted_catalog = _catalog(
        AgentCatalogSqliteDatabase(database.path),
        start=6_000,
    )
    restarted = AgentArtifactService(
        SqliteAgentArtifactRepository(
            AgentCatalogSqliteDatabase(database.path)
        ),
        restarted_catalog,
        clock=lambda: T0,
        id_factory=iter(f"{index:032x}" for index in range(7_000, 7_100)).__next__,
    )
    restored = restarted.content(
        project_id=project.project_id,
        session_id=session.session_id,
        artifact_id=captured.artifact_id,
        version_id=captured.latest_version.version_id,
        workspace=workspace,
        download=False,
    )
    assert restored.payload == payload

    target.write_bytes(b"# Changed after capture\n")
    with pytest.raises(AgentArtifactError) as stale:
        restarted.content(
            project_id=project.project_id,
            session_id=session.session_id,
            artifact_id=captured.artifact_id,
            version_id=captured.latest_version.version_id,
            workspace=workspace,
            download=False,
        )
    assert stale.value.code == "agent_artifact_stale"
    counts = SqliteAgentHardeningProbe(database).inspect().counts
    assert (counts.artifacts, counts.artifact_versions) == (1, 1)


class _SyntheticRuntimeProcess:
    next_pid = 20_000

    def __init__(self) -> None:
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("synthetic-runtime", timeout)
        return self.returncode


def test_thirty_two_runtime_load_unload_cycles_leave_no_synthetic_process(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "synthetic-runtime-binary"
    binary.write_text("synthetic", encoding="utf-8")
    weights = tmp_path / "synthetic.gguf"
    weights.write_bytes(b"GGUF" + b"\0" * 1_020)
    processes: list[_SyntheticRuntimeProcess] = []

    def fake_spawn(_command, **_options):
        process = _SyntheticRuntimeProcess()
        processes.append(process)
        return process

    runtime = LocalModelService(
        tmp_path / "models",
        llama_server=lambda: binary,
        hardware=lambda _binary: HardwareSummary(),
        popen=fake_spawn,
        clock=lambda: T0,
        health_timeout_seconds=0.01,
        capability_probe=lambda _handle, _alias, tools: RuntimeCapabilities(
            state=RuntimeCapabilityState.VERIFIED,
            text=True,
            tools=tools,
        ),
    )
    runtime.add(
        AddLocalModel(
            alias="synthetic-model",
            path=str(weights),
            default_device=DeviceMode.CPU,
            context_size=512,
        )
    )
    runtime._wait_healthy = lambda _handle: True  # type: ignore[method-assign]  # noqa: SLF001

    for _cycle in range(32):
        active = runtime.activate(
            "synthetic-model",
            ActivateLocalModel(
                device=DeviceMode.CPU,
                context_size=512,
                fast_attention=False,
            ),
        )
        assert active.runtime.state == "running"
        assert runtime.coordinator_status().state is RuntimeCoordinatorState.READY
        runtime.deactivate("synthetic-model")
        assert runtime.coordinator_status().state is RuntimeCoordinatorState.IDLE
        assert runtime.running_aliases() == ()

    assert len(processes) == 32
    assert all(process.poll() is not None for process in processes)
    assert runtime._processes == {}  # noqa: SLF001
    runtime.shutdown()


def test_interrupted_schema_migration_rolls_back_every_partial_alter(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE agent_catalog_schema_migrations (
                version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL
            ) STRICT
            """
        )
        for statement in _SCHEMA_V1.split(";"):
            if statement.strip():
                connection.execute(statement)
        connection.execute(
            "INSERT INTO agent_catalog_schema_migrations(version, applied_at) VALUES(1, ?)",
            (T0.isoformat(),),
        )
        connection.execute("PRAGMA user_version=1")
        # The v2 migration performs several ALTERs before creating this table.
        # This incompatible synthetic table forces that late statement to fail.
        connection.execute("CREATE TABLE agent_conversation_events(dummy TEXT)")

    database = AgentCatalogSqliteDatabase(path)
    with pytest.raises(AgentCatalogError) as interrupted:
        database.initialize()
    assert interrupted.value.code == "agent_catalog_storage_unavailable"

    with sqlite3.connect(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(agent_catalog_sessions)"
            ).fetchall()
        }
        version = connection.execute(
            "SELECT MAX(version) FROM agent_catalog_schema_migrations"
        ).fetchone()[0]
    assert "retention_policy" not in columns
    assert "history_revision" not in columns
    assert version == 1

    diagnostic = AgentHardeningService(
        SqliteAgentHardeningProbe(database),
        LocalAgentService(
            chat=lambda *_args: (503, b"{}", "application/json"),
            active_model=lambda: None,
        ),
    ).snapshot()
    assert diagnostic.catalog.state == "unavailable"
    assert diagnostic.catalog.reason_code == "catalog_storage_unavailable"
    assert diagnostic.catalog.counts is None
