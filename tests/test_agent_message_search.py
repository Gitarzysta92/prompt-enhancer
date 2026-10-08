"""Synthetic privacy and durability tests for saved-message search."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentMessageSearchRequest,
    AgentRetentionPolicy,
    CreateAgentProject,
    ForkAgentSession,
    StoredAgentEvent,
    UpdateAgentCatalogSession,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.infrastructure.sqlite import agent_catalog as agent_catalog_sqlite
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.api import CSRF_HEADER
from prompt_enhancer.application.local_agent_receipts import AgentTokenUsage, AgentTurnSummary


T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _catalog(tmp_path: Path) -> AgentCatalogService:
    ids = iter((f"{value:032x}" for value in range(1, 40)))
    return AgentCatalogService(
        SqliteAgentCatalogRepository(
            AgentCatalogSqliteDatabase(tmp_path / AGENT_CATALOG_DATABASE_FILENAME)
        ),
        clock=lambda: T0,
        id_factory=ids.__next__,
    )


def _retained(catalog: AgentCatalogService, project_id: str, session_id: str, title: str) -> None:
    catalog.register_live_session(
        session_id=session_id, project_id=project_id, title=title,
        workspace=Path("C:/synthetic/workspace"), model_alias="fixture",
        created_at=T0, retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )


def _append(catalog: AgentCatalogService, project_id: str, session_id: str, seq: int, role: str, text: str) -> None:
    catalog.append_history_event(
        project_id=project_id, session_id=session_id,
        expected_history_revision=catalog.get_session(session_id).history_revision,
        event=StoredAgentEvent(seq=seq, at=T0, kind=role, text=text),
    )


def _downgrade_catalog_to_v30(database: AgentCatalogSqliteDatabase) -> None:
    """Build a valid synthetic pre-v31 database from the current schema."""
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Optional later schema objects may exist in a newer working tree.
        # Remove them before restoring the exact pre-v31 migration ledger.
        connection.execute("DROP TABLE IF EXISTS agent_artifact_directory_move_resolutions")
        connection.execute("DROP TABLE IF EXISTS agent_artifact_directory_move_intent_children")
        connection.execute("DROP TABLE IF EXISTS agent_artifact_directory_move_intents")
        connection.execute("DROP TABLE IF EXISTS agent_message_search_fts")
        connection.execute("DROP TABLE IF EXISTS agent_message_search_messages")
        connection.execute("DELETE FROM agent_catalog_migration_checksums WHERE version >= 31")
        connection.execute("DELETE FROM agent_catalog_schema_migrations WHERE version >= 31")
        connection.execute("PRAGMA user_version=30")
        connection.execute("COMMIT")


def test_message_search_is_retention_gated_literal_and_paged(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    alpha = catalog.create_project(CreateAgentProject(name="Synthetic Alpha"))
    beta = catalog.create_project(CreateAgentProject(name="Synthetic Beta"))
    _retained(catalog, alpha.project_id, "a" * 32, "First saved chat")
    _retained(catalog, beta.project_id, "b" * 32, "Second saved chat")
    catalog.register_live_session(
        session_id="c" * 32, project_id=alpha.project_id, title="Metadata only",
        workspace=Path("C:/synthetic/workspace"), model_alias="fixture", created_at=T0,
    )
    _append(catalog, alpha.project_id, "a" * 32, 1, "user", "Before: Żółw speaks.")
    _append(catalog, beta.project_id, "b" * 32, 1, "assistant", "A Żółw speaks later.")
    first = catalog.search_messages(request=AgentMessageSearchRequest(query="Żółw speaks", limit=1))
    assert first.total == 2
    assert len(first.matches) == 1
    assert first.matches[0].session_id == "a" * 32
    assert first.matches[0].role == "user"
    assert "Żółw" in first.matches[0].excerpt
    assert "query" not in first.model_dump()
    second = catalog.search_messages(request=AgentMessageSearchRequest(
        query="Żółw speaks", limit=1, offset=1, snapshot=first.snapshot,
    ))
    assert second.total == 2 and len(second.matches) == 1
    assert second.matches[0].session_id == "b" * 32
    assert second.matches[0].role == "assistant"
    scoped = catalog.search_messages(request=AgentMessageSearchRequest(
        query="Żółw speaks", project_id=alpha.project_id,
    ))
    assert [match.session_id for match in scoped.matches] == ["a" * 32]
    assert catalog.search_messages(request=AgentMessageSearchRequest(query='Żółw" OR impossible')).total == 0
    with pytest.raises(AgentCatalogError) as stale:
        catalog.search_messages(request=AgentMessageSearchRequest(
            query="Żółw speaks", limit=1, offset=1, snapshot="0" * 64,
        ))
    assert stale.value.code == "agent_message_search_snapshot_conflict"


def test_message_search_delete_removes_private_index_projection(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic project"))
    _retained(catalog, project.project_id, "a" * 32, "Saved chat")
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic needle survives fork")
    assert catalog.search_messages(request=AgentMessageSearchRequest(query="needle survives")).total == 1
    source = catalog.get_session("a" * 32)
    catalog.delete_session("a" * 32, expected_catalog_revision=source.revision,
                           expected_history_revision=source.history_revision)
    page = catalog.search_messages(request=AgentMessageSearchRequest(query="needle survives"))
    assert page.total == 0 and page.matches == ()


def test_message_search_keeps_sparse_event_sequence_distinct_from_history_revision(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic sparse project"))
    _retained(catalog, project.project_id, "a" * 32, "Sparse saved chat")
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic first message")
    _append(catalog, project.project_id, "a" * 32, 9, "assistant", "Synthetic sparse needle")
    page = catalog.search_messages(request=AgentMessageSearchRequest(query="sparse needle"))
    assert page.matches[0].match_event_seq == 9
    assert page.matches[0].history_revision == 2


def test_message_search_archive_move_and_delete_invalidate_snapshot(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    first = catalog.create_project(CreateAgentProject(name="Synthetic first"))
    second = catalog.create_project(CreateAgentProject(name="Synthetic second"))
    _retained(catalog, first.project_id, "a" * 32, "Movable saved chat")
    _append(catalog, first.project_id, "a" * 32, 1, "user", "Synthetic snapshot needle")
    page = catalog.search_messages(request=AgentMessageSearchRequest(query="snapshot needle"))
    before = catalog.get_session("a" * 32)
    catalog.update_session("a" * 32, UpdateAgentCatalogSession(
        expected_revision=before.revision, project_id=second.project_id,
    ))
    with pytest.raises(AgentCatalogError) as moved:
        catalog.search_messages(request=AgentMessageSearchRequest(
            query="snapshot needle", offset=1, snapshot=page.snapshot,
        ))
    assert moved.value.code == "agent_message_search_snapshot_conflict"
    current = catalog.get_session("a" * 32)
    catalog.update_session("a" * 32, UpdateAgentCatalogSession(
        expected_revision=current.revision, archived=True,
    ))
    assert catalog.search_messages(request=AgentMessageSearchRequest(query="snapshot needle")).total == 0
    assert catalog.search_messages(request=AgentMessageSearchRequest(
        query="snapshot needle", include_archived=True,
    )).total == 1


def test_message_search_fails_closed_for_missing_index_and_marker_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic integrity"))
    _retained(catalog, project.project_id, "a" * 32, "Saved chat")
    marker = "f" * 32
    _append(catalog, project.project_id, "a" * 32, 1, "user", f"__agent_search_open_{marker}__ needle")
    monkeypatch.setattr(agent_catalog_sqlite.uuid, "uuid4", lambda: type("U", (), {"hex": marker})())
    with pytest.raises(AgentCatalogError) as collision:
        catalog.search_messages(request=AgentMessageSearchRequest(query="needle"))
    assert collision.value.code == "agent_message_search_corrupt"
    database = catalog._repository._database  # noqa: SLF001 - synthetic corruption fixture
    with database.connect() as connection:
        connection.execute("DROP TABLE agent_message_search_fts")
    with pytest.raises(AgentCatalogError) as unavailable:
        catalog.search_messages(request=AgentMessageSearchRequest(query="needle"))
    assert unavailable.value.code == "agent_message_search_unavailable"


def test_message_search_late_unicode_and_punctuation_are_literal(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic literal"))
    _retained(catalog, project.project_id, "a" * 32, "Late saved chat")
    _append(catalog, project.project_id, "a" * 32, 1, "assistant", "prefix " + "x" * 500 + " Żółw, says: OR (not grammar).")
    page = catalog.search_messages(request=AgentMessageSearchRequest(query="Żółw, says: OR (not grammar)"))
    assert page.total == 1
    assert "Żółw" in page.matches[0].excerpt
    assert page.matches[0].excerpt != "prefix "
    assert catalog.search_messages(request=AgentMessageSearchRequest(query="OR impossible")).total == 0


def test_message_search_detects_corrupt_external_content_index(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic corrupt index"))
    _retained(catalog, project.project_id, "a" * 32, "Saved chat")
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic integrity needle")
    database = catalog._repository._database  # noqa: SLF001 - synthetic corruption fixture
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO agent_message_search_fts(rowid,text) VALUES(?,?)",
            (999, "synthetic orphan posting"),
        )
    with pytest.raises(AgentCatalogError) as failure:
        catalog.search_messages(request=AgentMessageSearchRequest(query="integrity needle"))
    assert failure.value.code == "agent_message_search_unavailable"


def test_v30_upgrade_backfills_retained_visible_text_but_not_metadata_only(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic v30"))
    _retained(catalog, project.project_id, "a" * 32, "Retained")
    catalog.register_live_session(
        session_id="b" * 32, project_id=project.project_id, title="Metadata",
        workspace=Path("C:/synthetic/workspace"), model_alias="fixture", created_at=T0,
    )
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic v30 backfill needle")
    # Simulate the exact pre-v31 durable state after events already existed.
    database = catalog._repository._database  # noqa: SLF001 - migration fixture
    _downgrade_catalog_to_v30(database)
    restarted = _catalog(tmp_path)
    page = restarted.search_messages(request=AgentMessageSearchRequest(query="backfill needle"))
    assert [match.session_id for match in page.matches] == ["a" * 32]


def test_message_search_production_browser_auth_csrf_and_noecho(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(tmp_path / "provider-empty"))
    settings = AppSettings(home=tmp_path / "app-home", session_reader_enabled=False)
    application = bootstrap_local_application(settings)
    catalog = application.create_agent_catalog_service()
    project = catalog.create_project(CreateAgentProject(name="Synthetic HTTP"))
    _retained(catalog, project.project_id, "a" * 32, "Saved")
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic protected needle")
    secret = "synthetic private query"
    with TestClient(application.create_http_app(), base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert browser.status_code == 200
        csrf = browser.json()["csrf_token"]
        missing_csrf = client.post("/v1/agent/catalog/sessions/message-search", headers={"Origin": "http://127.0.0.1"}, json={"query": secret})
        foreign = client.post("/v1/agent/catalog/sessions/message-search", headers={CSRF_HEADER: csrf, "Origin": "http://foreign.invalid"}, json={"query": secret})
        invalid = client.post("/v1/agent/catalog/sessions/message-search", headers={CSRF_HEADER: csrf, "Origin": "http://127.0.0.1"}, json={"query": secret, "limit": 0})
        success = client.post("/v1/agent/catalog/sessions/message-search", headers={CSRF_HEADER: csrf, "Origin": "http://127.0.0.1"}, json={"query": "protected needle"})
        assert missing_csrf.status_code == 403
        assert foreign.status_code == 403
        assert invalid.status_code == 422
        assert success.status_code == 200
        for response in (missing_csrf, foreign, invalid, success):
            assert response.headers["cache-control"] == "no-store, private"
            assert secret not in response.text
        assert "protected needle" not in str(success.request.url)


def test_message_search_timeout_is_service_unavailable_without_query_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(tmp_path / "provider-empty"))
    application = bootstrap_local_application(
        AppSettings(home=tmp_path / "app-home", session_reader_enabled=False)
    )
    secret = "synthetic private timeout query"

    def timed_out(*_args: object, **_kwargs: object) -> None:
        raise AgentCatalogError("agent_message_search_timed_out")

    monkeypatch.setattr(AgentCatalogService, "search_messages", timed_out)
    with TestClient(application.create_http_app(), base_url="http://127.0.0.1") as client:
        browser = client.get("/auth/session", headers={"Sec-Fetch-Site": "same-origin"})
        csrf = browser.json()["csrf_token"]
        response = client.post(
            "/v1/agent/catalog/sessions/message-search",
            headers={CSRF_HEADER: csrf, "Origin": "http://127.0.0.1"},
            json={"query": secret},
        )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json() == {"detail": {"code": "agent_message_search_timed_out"}}
    assert secret not in response.text


def test_completed_turn_fork_and_branch_delete_keep_search_index_exact(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic fork"))
    _retained(catalog, project.project_id, "a" * 32, "Source")
    _append(catalog, project.project_id, "a" * 32, 1, "user", "Synthetic fork needle")
    _append(catalog, project.project_id, "a" * 32, 2, "assistant", "Synthetic fork answer")
    summary = AgentTurnSummary(
        turn_id="e" * 32, turn_number=1, model_alias="fixture", status="completed",
        reason="answer_complete", started_at=T0, finished_at=T0, duration_ms=0,
        model_wait_ms=0, time_to_first_text_ms=0,
        usage=AgentTokenUsage(source="runtime_reported", state="unavailable", model_requests=0, reported_requests=0),
        tools_requested=0, tools_succeeded=0, tools_failed=0, tools_not_approved=0,
        tools_cancelled=0, tools_unverified=0, untracked_command_calls=0, writes=(),
    )
    catalog.append_history_event(
        project_id=project.project_id, session_id="a" * 32,
        expected_history_revision=catalog.get_session("a" * 32).history_revision,
        event=StoredAgentEvent(seq=3, at=T0, kind="done", turn_id="e" * 32, turn_summary=summary),
    )
    source = catalog.get_session("a" * 32)
    receipt = catalog.fork_session(
        source_project_id=project.project_id, source_session_id="a" * 32,
        command=ForkAgentSession(request_id="d" * 32, expected_catalog_revision=source.revision,
                                expected_history_revision=source.history_revision),
    )
    assert catalog.search_messages(request=AgentMessageSearchRequest(query="fork needle")).total == 2
    branch = catalog.get_session(receipt.session.session_id)
    catalog.delete_session(branch.session_id, expected_catalog_revision=branch.revision,
                           expected_history_revision=branch.history_revision)
    assert catalog.search_messages(request=AgentMessageSearchRequest(query="fork needle")).total == 1


def test_v31_fts_creation_failure_rolls_back_to_v30(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog(tmp_path)
    database = catalog._repository._database  # noqa: SLF001 - migration rollback fixture
    _downgrade_catalog_to_v30(database)
    broken = (*agent_catalog_sqlite._AGENT_CATALOG_MIGRATIONS[:30], (31, ("CREATE VIRTUAL TABLE broken USING no_such_module(text)",)))
    monkeypatch.setattr(agent_catalog_sqlite, "_AGENT_CATALOG_MIGRATIONS", broken)
    with pytest.raises(AgentCatalogError) as failed:
        AgentCatalogSqliteDatabase(database.path).initialize()
    assert failed.value.code == "agent_catalog_storage_unavailable"
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 30
        assert connection.execute("SELECT COUNT(*) FROM agent_catalog_schema_migrations WHERE version=31").fetchone()[0] == 0
