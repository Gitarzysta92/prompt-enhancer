"""Durable authored-Agent project/session metadata with no transcript storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Event

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentHistoryState,
    AgentRetentionPolicy,
    CreateAgentProject,
    ResumeAgentSession,
    StoredAgentEvent,
    UpdateAgentCatalogSession,
    UpdateAgentProject,
)
from prompt_enhancer.application.local_agent import (
    AgentSettings,
    LocalAgentError,
    LocalAgentService,
    SwitchAgentSessionModel,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.sqlite import agent_catalog as agent_catalog_sqlite
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)


T0 = datetime(2026, 8, 27, 8, 0, tzinfo=UTC)


def _catalog(tmp_path: Path, ids: list[str] | None = None) -> AgentCatalogService:
    values = iter(ids or [f"{index:032x}" for index in range(1, 20)])
    repository = SqliteAgentCatalogRepository(
        AgentCatalogSqliteDatabase(tmp_path / AGENT_CATALOG_DATABASE_FILENAME)
    )
    return AgentCatalogService(repository, clock=lambda: T0, id_factory=values.__next__)


def _write_supported_agent_schema(path: Path, source_version: int) -> None:
    """Build one exact historical schema from the frozen synthetic migrations."""

    assert 1 <= source_version < AGENT_CATALOG_SCHEMA_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = T0.isoformat()
    with sqlite3.connect(path, isolation_level=None) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE agent_catalog_schema_migrations (
                version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL
            ) STRICT
            """
        )
        for version, statements in agent_catalog_sqlite._AGENT_CATALOG_MIGRATIONS:
            if version > source_version:
                break
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO agent_catalog_schema_migrations(version, applied_at)
                VALUES (?, ?)
                """,
                (version, stamp),
            )
            if version == 1:
                connection.execute(
                    """
                    INSERT INTO agent_projects(
                        project_id,name,created_at,updated_at,revision,pinned,
                        archived_at,is_default
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    ("1" * 32, "Synthetic migration project", stamp, stamp, 1, 1, None, 1),
                )
                connection.execute(
                    """
                    INSERT INTO agent_catalog_sessions(
                        session_id,project_id,title,workspace,model_alias,
                        created_at,updated_at,last_opened_at,revision,pinned,
                        archived_at,history_state
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "2" * 32,
                        "1" * 32,
                        "Synthetic migration chat",
                        "D:/example/synthetic-workspace",
                        None,
                        stamp,
                        stamp,
                        stamp,
                        1,
                        0,
                        None,
                        "memory_only",
                    ),
                )
        connection.execute(f"PRAGMA user_version={source_version}")
        connection.execute("COMMIT")


def test_project_and_session_catalog_supports_search_revisions_and_safe_deletion(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    alpha = catalog.create_project(CreateAgentProject(name="  Alpha   Project  "))
    beta = catalog.create_project(CreateAgentProject(name="Beta Project"))
    assert alpha.name == "Alpha Project"
    assert [project.project_id for project in catalog.list_projects().projects] == [
        alpha.project_id,
        beta.project_id,
    ]
    assert catalog.list_projects(search="ALPHA").projects == (alpha,)

    alpha = catalog.update_project(
        alpha.project_id,
        UpdateAgentProject(
            expected_revision=alpha.revision,
            name="Alpha Renamed",
            pinned=True,
        ),
    )
    assert alpha.name == "Alpha Renamed" and alpha.pinned and alpha.revision == 2
    with pytest.raises(AgentCatalogError) as stale:
        catalog.update_project(
            alpha.project_id,
            UpdateAgentProject(expected_revision=1, pinned=False),
        )
    assert stale.value.code == "agent_project_revision_conflict"

    beta = catalog.update_project(
        beta.project_id,
        UpdateAgentProject(expected_revision=beta.revision, archived=True),
    )
    assert beta.archived_at == T0
    assert all(project.project_id != beta.project_id for project in catalog.list_projects().projects)
    assert any(
        project.project_id == beta.project_id
        for project in catalog.list_projects(include_archived=True).projects
    )
    beta = catalog.update_project(
        beta.project_id,
        UpdateAgentProject(expected_revision=beta.revision, archived=False),
    )

    session = catalog.register_live_session(
        session_id="a" * 32,
        project_id=alpha.project_id,
        title="  First   durable index  ",
        workspace=tmp_path / "example-workspace",
        model_alias="synthetic-model",
        created_at=T0,
    )
    assert session.title == "First durable index"
    assert session.history_state is AgentHistoryState.MEMORY_ONLY
    assert session.conversation_available is False
    assert catalog.list_sessions(project_id=alpha.project_id).sessions == (session,)
    assert catalog.list_sessions(search="DURABLE").sessions == (session,)
    assert [
        project.project_id for project in catalog.list_projects(search="DURABLE").projects
    ] == [alpha.project_id]

    moved = catalog.update_session(
        session.session_id,
        UpdateAgentCatalogSession(
            expected_revision=session.revision,
            title="Renamed chat",
            project_id=beta.project_id,
            model_alias="second-model",
            pinned=True,
        ),
    )
    assert moved.project_id == beta.project_id and moved.pinned and moved.revision == 2
    assert moved.model_alias == "second-model"
    with pytest.raises(AgentCatalogError) as nonempty:
        current_beta = catalog.get_project(beta.project_id)
        catalog.delete_project(
            beta.project_id,
            expected_revision=current_beta.revision,
        )
    assert nonempty.value.code == "agent_project_not_empty"

    archived = catalog.update_session(
        moved.session_id,
        UpdateAgentCatalogSession(expected_revision=moved.revision, archived=True),
    )
    assert catalog.list_sessions(project_id=beta.project_id).sessions == ()
    assert catalog.list_sessions(
        project_id=beta.project_id, include_archived=True
    ).sessions == (archived,)
    assert catalog.list_projects(search="Renamed chat").projects == ()
    assert [
        project.project_id
        for project in catalog.list_projects(
            search="Renamed chat", include_archived=True
        ).projects
    ] == [beta.project_id]
    restored = catalog.update_session(
        archived.session_id,
        UpdateAgentCatalogSession(expected_revision=archived.revision, archived=False),
    )
    catalog.delete_session(
        restored.session_id,
        expected_catalog_revision=restored.revision,
        expected_history_revision=restored.history_revision,
    )
    current_beta = catalog.get_project(beta.project_id)
    catalog.delete_project(
        beta.project_id,
        expected_revision=current_beta.revision,
    )
    with pytest.raises(AgentCatalogError) as missing:
        catalog.get_project(beta.project_id)
    assert missing.value.code == "agent_project_not_found"

    default = catalog.resolve_project(None)
    assert catalog.resolve_project(None).project_id == default.project_id
    with pytest.raises(AgentCatalogError) as protected:
        catalog.delete_project(
            default.project_id,
            expected_revision=default.revision,
        )
    assert protected.value.code == "agent_default_project_protected"
    with pytest.raises(AgentCatalogError) as archive_protected:
        catalog.update_project(
            default.project_id,
            UpdateAgentProject(expected_revision=default.revision, archived=True),
        )
    assert archive_protected.value.code == "agent_default_project_protected"


def test_catalog_restart_preserves_metadata_without_claiming_conversation_history(
    tmp_path: Path,
) -> None:
    first = _catalog(tmp_path, ["1" * 32])
    project = first.create_project(CreateAgentProject(name="Restart fixture"))
    created = first.register_live_session(
        session_id="b" * 32,
        project_id=project.project_id,
        title="Memory-only conversation",
        workspace=tmp_path / "restart-workspace",
        model_alias=None,
        created_at=T0,
    )

    restarted = _catalog(tmp_path, ["2" * 32])
    restored = restarted.get_session(created.session_id)
    assert restored.title == "Memory-only conversation"
    assert restored.history_state is AgentHistoryState.MEMORY_ONLY
    assert restored.conversation_available is False
    assert restarted.get_project(project.project_id).session_count == 1


def test_permanent_catalog_deletion_requires_exact_metadata_and_history_heads(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Revision fixture"))
    renamed = catalog.update_project(
        project.project_id,
        UpdateAgentProject(expected_revision=project.revision, name="Current project"),
    )
    with pytest.raises(AgentCatalogError) as stale_project:
        catalog.delete_project(
            project.project_id,
            expected_revision=project.revision,
        )
    assert stale_project.value.code == "agent_project_revision_conflict"
    assert catalog.get_project(project.project_id) == renamed

    workspace = tmp_path / "revision-workspace"
    workspace.mkdir()
    session = catalog.register_live_session(
        session_id="e" * 32,
        project_id=project.project_id,
        title="Revision chat",
        workspace=workspace,
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    changed = catalog.update_session(
        session.session_id,
        UpdateAgentCatalogSession(
            expected_revision=session.revision,
            title="Current chat",
        ),
    )
    with pytest.raises(AgentCatalogError) as stale_catalog:
        catalog.delete_session(
            session.session_id,
            expected_catalog_revision=session.revision,
            expected_history_revision=session.history_revision,
        )
    assert stale_catalog.value.code == "agent_catalog_session_revision_conflict"

    next_history_revision = catalog.append_history_event(
        project_id=project.project_id,
        session_id=session.session_id,
        expected_history_revision=changed.history_revision,
        event=StoredAgentEvent(seq=1, at=T0, kind="status", text="Synthetic event."),
    )
    assert next_history_revision == 1
    with pytest.raises(AgentCatalogError) as stale_history:
        catalog.delete_session(
            session.session_id,
            expected_catalog_revision=changed.revision,
            expected_history_revision=changed.history_revision,
        )
    assert stale_history.value.code == "agent_history_revision_conflict"
    current = catalog.get_session(session.session_id)
    catalog.delete_session(
        session.session_id,
        expected_catalog_revision=current.revision,
        expected_history_revision=current.history_revision,
    )
    assert catalog.list_sessions(project_id=project.project_id).sessions == ()


def test_resume_wins_delete_race_without_publishing_a_ghost_chat(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "resume-wins-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Resume wins"))
    record = catalog.register_live_session(
        session_id="d" * 32,
        project_id=project.project_id,
        title="Retained chat",
        workspace=workspace,
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
    )
    entered = Event()
    release = Event()
    original_load = catalog.load_history

    def blocking_load(*, project_id: str, session_id: str):
        entered.set()
        assert release.wait(5)
        return original_load(project_id=project_id, session_id=session_id)

    monkeypatch.setattr(catalog, "load_history", blocking_load)
    command = ResumeAgentSession(
        expected_catalog_revision=record.revision,
        expected_history_revision=record.history_revision,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        resumed_future = pool.submit(
            service.resume,
            project_id=project.project_id,
            session_id=record.session_id,
            command=command,
        )
        assert entered.wait(5)
        deleted_future = pool.submit(
            service.delete_catalog_session,
            record.session_id,
            expected_catalog_revision=record.revision,
            expected_history_revision=record.history_revision,
        )
        release.set()
        resumed = resumed_future.result(timeout=5)
        with pytest.raises(LocalAgentError) as blocked:
            deleted_future.result(timeout=5)
    assert blocked.value.code == "agent_catalog_session_live"
    assert resumed.session_id == record.session_id
    assert catalog.get_session(record.session_id).session_id == record.session_id


def test_delete_wins_resume_race_without_recovering_deleted_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "delete-wins-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Delete wins"))
    record = catalog.register_live_session(
        session_id="c" * 32,
        project_id=project.project_id,
        title="Retained chat",
        workspace=workspace,
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
    )
    entered = Event()
    release = Event()
    original_delete = catalog.delete_session

    def blocking_delete(
        session_id: str,
        *,
        expected_catalog_revision: int,
        expected_history_revision: int,
    ) -> None:
        entered.set()
        assert release.wait(5)
        original_delete(
            session_id,
            expected_catalog_revision=expected_catalog_revision,
            expected_history_revision=expected_history_revision,
        )

    monkeypatch.setattr(catalog, "delete_session", blocking_delete)
    command = ResumeAgentSession(
        expected_catalog_revision=record.revision,
        expected_history_revision=record.history_revision,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleted_future = pool.submit(
            service.delete_catalog_session,
            record.session_id,
            expected_catalog_revision=record.revision,
            expected_history_revision=record.history_revision,
        )
        assert entered.wait(5)
        resumed_future = pool.submit(
            service.resume,
            project_id=project.project_id,
            session_id=record.session_id,
            command=command,
        )
        release.set()
        assert deleted_future.result(timeout=5) is None
        with pytest.raises(LocalAgentError) as missing:
            resumed_future.result(timeout=5)
    assert missing.value.code == "agent_catalog_session_not_found"
    assert service.list() == ()


def test_resume_and_catalog_update_publish_one_current_live_view(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "resume-update-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Resume update"))
    record = catalog.register_live_session(
        session_id="b" * 32,
        project_id=project.project_id,
        title="Original title",
        workspace=workspace,
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    service = LocalAgentService(
        chat=lambda *_: (200, b"{}", "application/json"),
        active_model=lambda: None,
        allowed_roots=(tmp_path,),
        catalog=catalog,
    )
    entered = Event()
    release = Event()
    original_load = catalog.load_history

    def blocking_load(*, project_id: str, session_id: str):
        entered.set()
        assert release.wait(5)
        return original_load(project_id=project_id, session_id=session_id)

    monkeypatch.setattr(catalog, "load_history", blocking_load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resumed_future = pool.submit(
            service.resume,
            project_id=project.project_id,
            session_id=record.session_id,
            command=ResumeAgentSession(
                expected_catalog_revision=record.revision,
                expected_history_revision=record.history_revision,
            ),
        )
        assert entered.wait(5)
        updated_future = pool.submit(
            service.update_catalog_session,
            record.session_id,
            UpdateAgentCatalogSession(
                expected_revision=record.revision,
                title="Current title",
            ),
        )
        release.set()
        assert resumed_future.result(timeout=5).session_id == record.session_id
        updated = updated_future.result(timeout=5)
    assert updated.title == "Current title"
    assert catalog.get_session(record.session_id).title == "Current title"
    assert service.list()[0].settings.title == "Current title"


def test_idle_live_chat_model_switch_is_ready_checked_revision_bound_and_durable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "switch-workspace"
    workspace.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    project = catalog.create_project(CreateAgentProject(name="Switch fixture"))
    ready = {"first-model", "second-model"}
    service = LocalAgentService(
        chat=lambda _alias, _body: (
            200,
            b'{"choices":[{"message":{"content":"ok"}}]}',
            "application/json",
        ),
        active_model=lambda: "first-model",
        model_ready=lambda alias: alias in ready,
        clock=lambda: T0,
        catalog=catalog,
    )
    created = service.create(
        AgentSettings(
            workspace=str(workspace),
            project_id=project.project_id,
            title="Stable draft fixture",
            model_alias="first-model",
        )
    )
    before = catalog.get_session(created.session_id)
    internal = service._sessions[created.session_id]  # noqa: SLF001
    original_messages = list(internal.messages)

    with internal.lock:
        internal.running = True
    with pytest.raises(LocalAgentError) as busy:
        service.switch_model(
            created.session_id,
            SwitchAgentSessionModel(
                model_alias="second-model",
                expected_revision=before.revision,
            ),
        )
    assert busy.value.code == "turn_in_progress"
    with internal.lock:
        internal.running = False

    ready.remove("second-model")
    with pytest.raises(LocalAgentError) as not_ready:
        service.switch_model(
            created.session_id,
            SwitchAgentSessionModel(
                model_alias="second-model",
                expected_revision=before.revision,
            ),
        )
    assert not_ready.value.code == "model_not_ready"
    ready.add("second-model")

    switched = service.switch_model(
        created.session_id,
        SwitchAgentSessionModel(
            model_alias="second-model",
            expected_revision=before.revision,
        ),
    )
    durable = catalog.get_session(created.session_id)
    assert switched.model_alias == "second-model"
    assert switched.settings.model_alias == "second-model"
    assert durable.model_alias == "second-model"
    assert durable.revision == before.revision + 1
    assert internal.messages == original_messages
    switched_context = service.session_context(created.session_id)
    assert switched_context.binding_state == "unmeasured"
    assert switched_context.unknown_reason == "model_changed"
    assert switched_context.model_alias is None

    with pytest.raises(LocalAgentError) as stale:
        service.switch_model(
            created.session_id,
            SwitchAgentSessionModel(
                model_alias="first-model",
                expected_revision=before.revision,
            ),
        )
    assert stale.value.code == "agent_catalog_session_revision_conflict"


def test_catalog_database_is_fixed_name_versioned_and_closes_connections(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from prompt_enhancer.infrastructure.sqlite import agent_catalog

    opened: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def capture(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(agent_catalog.sqlite3, "connect", capture)
    database = AgentCatalogSqliteDatabase(
        tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    )
    repository = SqliteAgentCatalogRepository(database)
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    assert repository.list_projects(search=None, include_archived=False, limit=10) == ()
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")

    with pytest.raises(AgentCatalogError) as wrong_name:
        AgentCatalogSqliteDatabase(tmp_path / "wrong.sqlite3").initialize()
    assert wrong_name.value.code == "agent_catalog_path_invalid"


def test_catalog_refuses_a_newer_schema_without_mutating_it(tmp_path: Path) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE agent_catalog_schema_migrations (
                version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL
            ) STRICT
            """
        )
        connection.execute(
            "INSERT INTO agent_catalog_schema_migrations(version, applied_at) VALUES (?, ?)",
            (AGENT_CATALOG_SCHEMA_VERSION + 1, T0.isoformat()),
        )

    with pytest.raises(AgentCatalogError) as newer:
        AgentCatalogSqliteDatabase(path).initialize()
    assert newer.value.code == "agent_catalog_schema_newer"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT MAX(version) FROM agent_catalog_schema_migrations"
        ).fetchone()[0] == AGENT_CATALOG_SCHEMA_VERSION + 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='agent_projects'"
        ).fetchone() is None


@pytest.mark.parametrize(
    "source_version",
    range(1, AGENT_CATALOG_SCHEMA_VERSION),
)
def test_every_supported_agent_catalog_schema_upgrades_with_exact_provenance(
    tmp_path: Path,
    source_version: int,
) -> None:
    path = tmp_path / f"schema-{source_version}" / AGENT_CATALOG_DATABASE_FILENAME
    _write_supported_agent_schema(path, source_version)

    database = AgentCatalogSqliteDatabase(path)
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    record = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=lambda: "3" * 32,
    ).get_session("2" * 32)
    assert record.project_id == "1" * 32
    assert record.title == "Synthetic migration chat"
    assert record.history_state is AgentHistoryState.MEMORY_ONLY

    with sqlite3.connect(path) as connection:
        versions = tuple(
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM agent_catalog_schema_migrations ORDER BY version"
            ).fetchall()
        )
        checksums = {
            int(row[0]): str(row[1])
            for row in connection.execute(
                """
                SELECT version, checksum
                FROM agent_catalog_migration_checksums
                ORDER BY version
                """
            ).fetchall()
        }
        assert versions == tuple(range(1, AGENT_CATALOG_SCHEMA_VERSION + 1))
        assert checksums == agent_catalog_sqlite._AGENT_CATALOG_MIGRATION_CHECKSUMS
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            AGENT_CATALOG_SCHEMA_VERSION
        )
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_catalog_refuses_gapped_or_checksums_changed_migration_history(
    tmp_path: Path,
) -> None:
    gap_path = tmp_path / "gap" / AGENT_CATALOG_DATABASE_FILENAME
    AgentCatalogSqliteDatabase(gap_path).initialize()
    with sqlite3.connect(gap_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version=15"
        )
    with pytest.raises(AgentCatalogError) as gap:
        AgentCatalogSqliteDatabase(gap_path).initialize()
    assert gap.value.code == "agent_catalog_migration_history_incomplete"
    with sqlite3.connect(gap_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_catalog_schema_migrations WHERE version=15"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA user_version").fetchone() == (
            AGENT_CATALOG_SCHEMA_VERSION,
        )

    checksum_path = tmp_path / "checksum" / AGENT_CATALOG_DATABASE_FILENAME
    AgentCatalogSqliteDatabase(checksum_path).initialize()
    with sqlite3.connect(checksum_path) as connection:
        connection.execute(
            """
            UPDATE agent_catalog_migration_checksums
            SET checksum=?
            WHERE version=29
            """,
            ("0" * 64,),
        )
    with pytest.raises(AgentCatalogError) as checksum:
        AgentCatalogSqliteDatabase(checksum_path).initialize()
    assert checksum.value.code == "agent_catalog_migration_checksum_mismatch"
    with sqlite3.connect(checksum_path) as connection:
        assert connection.execute(
            "SELECT checksum FROM agent_catalog_migration_checksums WHERE version=29"
        ).fetchone() == ("0" * 64,)


def test_catalog_refuses_schema_head_disagreement_and_unledgered_tables(
    tmp_path: Path,
) -> None:
    mismatch_path = tmp_path / "mismatch" / AGENT_CATALOG_DATABASE_FILENAME
    AgentCatalogSqliteDatabase(mismatch_path).initialize()
    with sqlite3.connect(mismatch_path) as connection:
        connection.execute("PRAGMA user_version=29")
    with pytest.raises(AgentCatalogError) as mismatch:
        AgentCatalogSqliteDatabase(mismatch_path).initialize()
    assert mismatch.value.code == "agent_catalog_schema_version_mismatch"
    with sqlite3.connect(mismatch_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (29,)

    stray_path = tmp_path / "stray" / AGENT_CATALOG_DATABASE_FILENAME
    stray_path.parent.mkdir(parents=True)
    with sqlite3.connect(stray_path) as connection:
        connection.execute("CREATE TABLE agent_projects(dummy TEXT) STRICT")
    with pytest.raises(AgentCatalogError) as stray:
        AgentCatalogSqliteDatabase(stray_path).initialize()
    assert stray.value.code == "agent_catalog_migration_history_incomplete"
    with sqlite3.connect(stray_path) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name='agent_projects'"
        ).fetchone() == ("agent_projects",)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='agent_catalog_schema_migrations'"
        ).fetchone() is None


def test_schema_30_checksum_migration_rolls_back_as_one_unit(tmp_path: Path) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    _write_supported_agent_schema(path, 29)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_schema_30
            BEFORE INSERT ON agent_catalog_schema_migrations
            WHEN NEW.version=30
            BEGIN
                SELECT RAISE(ABORT, 'synthetic schema 30 interruption');
            END
            """
        )

    with pytest.raises(AgentCatalogError) as interrupted:
        AgentCatalogSqliteDatabase(path).initialize()
    assert interrupted.value.code == "agent_catalog_storage_unavailable"
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (29,)
        assert connection.execute(
            "SELECT MAX(version) FROM agent_catalog_schema_migrations"
        ).fetchone() == (29,)
        assert connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='agent_catalog_migration_checksums'"
        ).fetchone() is None


def test_catalog_v4_migrates_to_lineage_schema_without_changing_existing_chats(
    tmp_path: Path,
    downgrade_agent_catalog_post_v20,
) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Migration fixture"))
    existing = catalog.register_live_session(
        session_id="9" * 32,
        project_id=project.project_id,
        title="Pre-lineage chat",
        workspace=tmp_path / "migration-workspace",
        model_alias=None,
        created_at=T0,
    )
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    with sqlite3.connect(path) as connection:
        downgrade_agent_catalog_post_v20(connection)
        for table in (
            "mcp_managed_tool_call_receipts",
            "mcp_managed_project_tools",
            "mcp_managed_tool_snapshot_state",
            "mcp_managed_tools",
            "mcp_managed_tool_snapshots",
            "mcp_managed_local_swap_receipts",
            "mcp_managed_local_recovery_attempts",
            "mcp_managed_local_rollback_generations",
            "mcp_managed_local_update_payloads",
            "mcp_managed_local_operations",
            "mcp_managed_local_packages",
            "mcp_managed_lifecycle_receipts",
            "mcp_managed_lifecycle_state",
            "mcp_managed_probe_receipts",
            "mcp_managed_mutations",
            "mcp_managed_secret_references",
            "mcp_managed_project_bindings",
            "mcp_managed_requirements",
            "mcp_managed_servers",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP TABLE agent_session_lineage")
        connection.execute("DROP TABLE agent_mcp_connection_rotations")
        connection.execute("DROP TABLE agent_mcp_connections")
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=5"
        )
        connection.execute("PRAGMA user_version = 4")

    migrated = AgentCatalogSqliteDatabase(path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    restored = AgentCatalogService(
        SqliteAgentCatalogRepository(migrated),
        clock=lambda: T0,
        id_factory=lambda: "a" * 32,
    ).get_session(existing.session_id)
    assert restored == existing
    assert restored.lineage is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == AGENT_CATALOG_SCHEMA_VERSION
        assert connection.execute(
            "SELECT version FROM agent_catalog_schema_migrations WHERE version=5"
        ).fetchone() == (5,)
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='agent_session_lineage'"
        ).fetchone()[0]
    assert "fork_request_id TEXT NOT NULL UNIQUE" in table_sql


def test_concurrent_default_project_resolution_creates_exactly_one_default(
    tmp_path: Path,
) -> None:
    for attempt in range(8):
        root = tmp_path / f"attempt-{attempt}"
        first = _catalog(root, ["1" * 32])
        second = _catalog(root, ["2" * 32])
        with ThreadPoolExecutor(max_workers=2) as executor:
            projects = tuple(
                executor.map(
                    lambda service: service.resolve_project(None),
                    (first, second),
                )
            )
        assert projects[0].project_id == projects[1].project_id
        listed = first.list_projects(include_archived=True).projects
        assert len(listed) == 1 and listed[0].is_default is True


def test_catalog_pages_cover_bounded_capacity_and_reject_stale_or_cross_scope_tokens(
    tmp_path: Path,
) -> None:
    project_ids = [f"{index:032x}" for index in range(1, 130)]
    catalog = _catalog(tmp_path, project_ids)
    projects = tuple(
        catalog.create_project(CreateAgentProject(name=f"Synthetic project {index:03d}"))
        for index in range(125)
    )

    first_projects = catalog.page_projects(limit=60)
    assert first_projects.total == 125
    assert first_projects.offset == 0
    assert first_projects.next_offset == 60
    assert first_projects.complete is False
    second_projects = catalog.page_projects(
        limit=60,
        offset=first_projects.next_offset,
        snapshot=first_projects.snapshot,
    )
    last_projects = catalog.page_projects(
        limit=60,
        offset=second_projects.next_offset,
        snapshot=first_projects.snapshot,
    )
    project_page_ids = tuple(
        project.project_id
        for page in (first_projects, second_projects, last_projects)
        for project in page.projects
    )
    assert project_page_ids == tuple(project.project_id for project in projects)
    assert len(set(project_page_ids)) == 125
    assert last_projects.next_offset is None and last_projects.complete is True

    restarted = _catalog(tmp_path, ["f" * 32])
    restarted_first = restarted.page_projects(limit=60)
    assert restarted_first.snapshot == first_projects.snapshot
    with pytest.raises(AgentCatalogError) as cross_scope:
        restarted.page_projects(
            include_archived=True,
            limit=60,
            offset=60,
            snapshot=first_projects.snapshot,
        )
    assert cross_scope.value.code == "agent_catalog_page_snapshot_conflict"
    with pytest.raises(AgentCatalogError) as missing_snapshot:
        restarted.page_projects(limit=60, offset=60)
    assert missing_snapshot.value.code == "agent_catalog_page_snapshot_required"
    with pytest.raises(AgentCatalogError) as out_of_range:
        restarted.page_projects(
            limit=60,
            offset=126,
            snapshot=first_projects.snapshot,
        )
    assert out_of_range.value.code == "agent_catalog_page_out_of_range"

    changed = restarted.update_project(
        projects[-1].project_id,
        UpdateAgentProject(
            expected_revision=projects[-1].revision,
            name="Synthetic changed project",
        ),
    )
    assert changed.revision == projects[-1].revision + 1
    with pytest.raises(AgentCatalogError) as stale:
        restarted.page_projects(
            limit=60,
            offset=60,
            snapshot=first_projects.snapshot,
        )
    assert stale.value.code == "agent_catalog_page_snapshot_conflict"


def test_session_pages_browse_past_two_hundred_and_bind_project_and_restart(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path, ["1" * 32, "2" * 32])
    project = catalog.create_project(CreateAgentProject(name="Synthetic session project"))
    other_project = catalog.create_project(CreateAgentProject(name="Synthetic other project"))
    sessions = tuple(
        catalog.register_live_session(
            session_id=f"{index + 1_000:032x}",
            project_id=project.project_id,
            title=f"Synthetic chat {index:03d}",
            workspace=tmp_path / "synthetic-workspace",
            model_alias=None,
            created_at=T0,
        )
        for index in range(245)
    )

    first = catalog.page_sessions(project_id=project.project_id, limit=100)
    second = catalog.page_sessions(
        project_id=project.project_id,
        limit=100,
        offset=first.next_offset,
        snapshot=first.snapshot,
    )
    third = catalog.page_sessions(
        project_id=project.project_id,
        limit=100,
        offset=second.next_offset,
        snapshot=first.snapshot,
    )
    loaded = tuple(
        session.session_id
        for page in (first, second, third)
        for session in page.sessions
    )
    assert first.total == 245
    assert loaded == tuple(session.session_id for session in sessions)
    assert len(set(loaded)) == 245
    assert third.complete is True and third.next_offset is None

    restarted = _catalog(tmp_path, ["3" * 32])
    assert (
        restarted.page_sessions(project_id=project.project_id, limit=100).snapshot
        == first.snapshot
    )
    with pytest.raises(AgentCatalogError) as cross_project:
        restarted.page_sessions(
            project_id=other_project.project_id,
            limit=100,
            offset=1,
            snapshot=first.snapshot,
        )
    assert cross_project.value.code == "agent_catalog_page_snapshot_conflict"

    changed = restarted.update_session(
        sessions[-1].session_id,
        UpdateAgentCatalogSession(
            expected_revision=sessions[-1].revision,
            title="Synthetic changed chat",
        ),
    )
    assert changed.revision == sessions[-1].revision + 1
    with pytest.raises(AgentCatalogError) as stale:
        restarted.page_sessions(
            project_id=project.project_id,
            limit=100,
            offset=100,
            snapshot=first.snapshot,
        )
    assert stale.value.code == "agent_catalog_page_snapshot_conflict"


def test_agent_catalog_http_hierarchy_survives_restart_and_live_state_is_truthful(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "app-home"
    workspace = tmp_path / "example-workspace"
    workspace.mkdir()
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(tmp_path / "provider-empty"))
    settings = AppSettings(home=home, session_reader_enabled=False)

    application = bootstrap_local_application(settings)
    with TestClient(
        application.create_http_app(), base_url="http://127.0.0.1"
    ) as client:
        token = settings.api_token_path.read_text(encoding="utf-8").strip()
        headers = {API_TOKEN_HEADER: token}
        assert client.get("/v1/agent/projects", headers=headers).json()["projects"] == []

        created_project = client.post(
            "/v1/agent/projects",
            headers=headers,
            json={"name": "Example authored project"},
        )
        assert created_project.status_code == 201
        project = created_project.json()

        created_session = client.post(
            "/v1/agent/sessions",
            headers=headers,
            json={
                "workspace": str(workspace),
                "project_id": project["project_id"],
                "title": "Example chat",
                "allow_writes": False,
                "allow_commands": False,
                "allow_web": False,
            },
        )
        assert created_session.status_code == 201, created_session.text
        live = created_session.json()
        assert live["settings"]["project_id"] == project["project_id"]

        project_page_response = client.get(
            "/v1/agent/projects/page?limit=1",
            headers=headers,
        )
        assert project_page_response.status_code == 200
        assert project_page_response.headers["cache-control"] == "no-store, private"
        assert project_page_response.json()["contract_version"] == (
            "agent-catalog-page.v1"
        )
        assert project_page_response.json()["total"] == 1

        session_page_response = client.get(
            f"/v1/agent/projects/{project['project_id']}/sessions/page?limit=1",
            headers=headers,
        )
        assert session_page_response.status_code == 200
        assert session_page_response.headers["cache-control"] == "no-store, private"
        assert session_page_response.json()["sessions"][0]["conversation_available"] is True
        global_page_response = client.get(
            "/v1/agent/catalog/sessions/page?limit=1",
            headers=headers,
        )
        assert global_page_response.status_code == 200
        assert global_page_response.json()["sessions"][0]["session_id"] == live["session_id"]
        missing_page_snapshot = client.get(
            "/v1/agent/catalog/sessions/page?limit=1&offset=1",
            headers=headers,
        )
        assert missing_page_snapshot.status_code == 422
        assert missing_page_snapshot.json()["detail"]["code"] == (
            "agent_catalog_page_snapshot_required"
        )

        catalog_session = client.get(
            f"/v1/agent/catalog/sessions/{live['session_id']}", headers=headers
        )
        assert catalog_session.status_code == 200
        record = catalog_session.json()
        assert record["conversation_available"] is True
        assert record["history_state"] == "memory_only"

        renamed = client.patch(
            f"/v1/agent/catalog/sessions/{live['session_id']}",
            headers=headers,
            json={
                "expected_revision": record["revision"],
                "title": "Renamed example chat",
                "pinned": True,
            },
        )
        assert renamed.status_code == 200
        archive_live = client.patch(
            f"/v1/agent/catalog/sessions/{live['session_id']}",
            headers=headers,
            json={
                "expected_revision": renamed.json()["revision"],
                "archived": True,
            },
        )
        assert archive_live.status_code == 409
        assert archive_live.json()["detail"]["code"] == "agent_catalog_session_live"
        refreshed_live = client.get(
            f"/v1/agent/sessions/{live['session_id']}", headers=headers
        ).json()
        assert refreshed_live["settings"]["title"] == "Renamed example chat"
        assert refreshed_live["settings"]["project_id"] == project["project_id"]
        stale = client.patch(
            f"/v1/agent/catalog/sessions/{live['session_id']}",
            headers=headers,
            json={"expected_revision": record["revision"], "pinned": False},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "agent_catalog_session_revision_conflict"

        renamed_record = renamed.json()
        blocked_delete = client.delete(
            f"/v1/agent/catalog/sessions/{live['session_id']}",
            headers=headers,
            params={
                "expected_catalog_revision": renamed_record["revision"],
                "expected_history_revision": renamed_record["history_revision"],
            },
        )
        assert blocked_delete.status_code == 409
        assert blocked_delete.json()["detail"]["code"] == "agent_catalog_session_live"
        assert client.delete(
            f"/v1/agent/sessions/{live['session_id']}", headers=headers
        ).status_code == 204

    restarted = bootstrap_local_application(settings)
    with TestClient(
        restarted.create_http_app(), base_url="http://127.0.0.1"
    ) as client:
        token = settings.api_token_path.read_text(encoding="utf-8").strip()
        headers = {API_TOKEN_HEADER: token}
        projects = client.get(
            "/v1/agent/projects?search=AUTHORED", headers=headers
        ).json()["projects"]
        assert [item["project_id"] for item in projects] == [project["project_id"]]
        sessions = client.get(
            f"/v1/agent/projects/{project['project_id']}/sessions", headers=headers
        ).json()["sessions"]
        assert len(sessions) == 1
        assert sessions[0]["title"] == "Renamed example chat"
        assert sessions[0]["conversation_available"] is False
        assert sessions[0]["history_state"] == "memory_only"

        delete_chat_url = f"/v1/agent/catalog/sessions/{sessions[0]['session_id']}"
        assert client.delete(delete_chat_url, headers=headers).status_code == 422
        stale_delete = client.delete(
            delete_chat_url,
            headers=headers,
            params={
                "expected_catalog_revision": sessions[0]["revision"] - 1,
                "expected_history_revision": sessions[0]["history_revision"],
            },
        )
        assert stale_delete.status_code == 409
        assert stale_delete.json()["detail"]["code"] == (
            "agent_catalog_session_revision_conflict"
        )
        assert client.delete(
            delete_chat_url,
            headers=headers,
            params={
                "expected_catalog_revision": sessions[0]["revision"],
                "expected_history_revision": sessions[0]["history_revision"],
            },
        ).status_code == 204
        current_project = client.get(
            f"/v1/agent/projects/{project['project_id']}", headers=headers
        ).json()
        delete_project_url = f"/v1/agent/projects/{project['project_id']}"
        assert client.delete(delete_project_url, headers=headers).status_code == 422
        stale_project_delete = client.delete(
            delete_project_url,
            headers=headers,
            params={"expected_revision": current_project["revision"] - 1},
        )
        assert stale_project_delete.status_code == 409
        assert stale_project_delete.json()["detail"]["code"] == (
            "agent_project_revision_conflict"
        )
        assert client.delete(
            delete_project_url,
            headers=headers,
            params={"expected_revision": current_project["revision"]},
        ).status_code == 204


def test_catalog_timestamps_remain_utc_and_session_order_is_stable(tmp_path: Path) -> None:
    ticks = iter((T0, T0 + timedelta(seconds=1), T0 + timedelta(seconds=2)))
    ids = iter(("1" * 32,))
    repository = SqliteAgentCatalogRepository(
        AgentCatalogSqliteDatabase(tmp_path / AGENT_CATALOG_DATABASE_FILENAME)
    )
    catalog = AgentCatalogService(
        repository,
        clock=ticks.__next__,
        id_factory=ids.__next__,
    )
    project = catalog.create_project(CreateAgentProject(name="Time fixture"))
    first = catalog.register_live_session(
        session_id="c" * 32,
        project_id=project.project_id,
        title="First",
        workspace=tmp_path / "workspace-one",
        model_alias=None,
        created_at=T0 + timedelta(seconds=1),
    )
    second = catalog.register_live_session(
        session_id="d" * 32,
        project_id=project.project_id,
        title="Second",
        workspace=tmp_path / "workspace-two",
        model_alias=None,
        created_at=T0 + timedelta(seconds=2),
    )
    listed = catalog.list_sessions(project_id=project.project_id).sessions
    assert listed == (second, first)
    assert all(item.created_at.utcoffset() == timedelta(0) for item in listed)
