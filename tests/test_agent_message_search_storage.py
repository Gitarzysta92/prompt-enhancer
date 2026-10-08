"""Synthetic storage-only regressions for retained Agent message search."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentMessageSearchRequest,
    AgentRetentionPolicy,
    CreateAgentProject,
    StoredAgentEvent,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)


STAMP = datetime(2026, 1, 1, tzinfo=UTC)
SESSION_ID = "a" * 32


def _catalog(tmp_path: Path) -> AgentCatalogService:
    database = AgentCatalogSqliteDatabase(tmp_path / AGENT_CATALOG_DATABASE_FILENAME)
    return AgentCatalogService(
        SqliteAgentCatalogRepository(database), clock=lambda: STAMP
    )


def _saved_chat(catalog: AgentCatalogService) -> str:
    project = catalog.create_project(CreateAgentProject(name="Synthetic search"))
    catalog.register_live_session(
        session_id=SESSION_ID,
        project_id=project.project_id,
        title="Saved synthetic chat",
        workspace=Path("C:/synthetic/workspace"),
        model_alias="fixture",
        created_at=STAMP,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
    )
    return project.project_id


def _append(catalog: AgentCatalogService, project_id: str, text: str) -> None:
    catalog.append_history_event(
        project_id=project_id,
        session_id=SESSION_ID,
        expected_history_revision=catalog.get_session(SESSION_ID).history_revision,
        event=StoredAgentEvent(seq=1, at=STAMP, kind="user", text=text),
    )


def test_literal_query_and_restart_find_only_retained_visible_text(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project_id = _saved_chat(catalog)
    _append(catalog, project_id, "Synthetic Żółw speaks in saved history")
    found = _catalog(tmp_path).search_messages(
        request=AgentMessageSearchRequest(query="Żółw speaks")
    )
    assert found.total == 1
    assert found.matches[0].session_id == SESSION_ID
    assert found.matches[0].match_event_seq == 1
    assert "Żółw" in found.matches[0].excerpt
    assert _catalog(tmp_path).search_messages(
        request=AgentMessageSearchRequest(query='Żółw" OR impossible')
    ).total == 0


def test_deleting_saved_chat_removes_its_search_projection(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project_id = _saved_chat(catalog)
    _append(catalog, project_id, "Synthetic removable needle")
    assert catalog.search_messages(
        request=AgentMessageSearchRequest(query="removable needle")
    ).total == 1
    session = catalog.get_session(SESSION_ID)
    catalog.delete_session(
        SESSION_ID,
        expected_catalog_revision=session.revision,
        expected_history_revision=session.history_revision,
    )
    assert _catalog(tmp_path).search_messages(
        request=AgentMessageSearchRequest(query="removable needle")
    ).total == 0


def test_corrupt_external_index_fails_closed_as_search_unavailable(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    project_id = _saved_chat(catalog)
    _append(catalog, project_id, "Synthetic integrity needle")
    database = catalog._repository._database  # noqa: SLF001 - synthetic corruption fixture
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO agent_message_search_fts(rowid,text) VALUES(?,?)",
            (999, "synthetic orphan posting"),
        )
    with pytest.raises(AgentCatalogError) as failure:
        catalog.search_messages(
            request=AgentMessageSearchRequest(query="integrity needle")
        )
    assert failure.value.code == "agent_message_search_unavailable"
