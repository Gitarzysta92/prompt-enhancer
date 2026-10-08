"""Scoped, durable credentials for direct loopback Agent MCP clients."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    CreateAgentProject,
)
from prompt_enhancer.application.agent_mcp_connections import (
    AGENT_MCP_BEARER_ENV,
    MAX_AGENT_MCP_CONNECTIONS,
    AgentMcpConnectionError,
    AgentMcpConnectionService,
    CreateAgentMcpConnection,
    RevokeAgentMcpConnection,
    RotateAgentMcpConnection,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
    SqliteAgentMcpConnectionRepository,
)
from prompt_enhancer.infrastructure.sqlite import agent_catalog as agent_catalog_sqlite


T0 = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
MASTER = "x" * 64
OTHER_MASTER = "y" * 64
ENDPOINT = "http://127.0.0.1:8765/mcp/agent"
PROJECT_ID = "9" * 32


def _database(tmp_path: Path) -> AgentCatalogSqliteDatabase:
    return AgentCatalogSqliteDatabase(
        tmp_path / "private-catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )


def _service(
    database: AgentCatalogSqliteDatabase,
    *,
    now: list[datetime],
    ids: list[str] | None = None,
    master: str = MASTER,
    activity_epoch: str | None = None,
) -> AgentMcpConnectionService:
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: now[0],
        id_factory=lambda: PROJECT_ID,
    )
    try:
        catalog.get_project(PROJECT_ID)
    except AgentCatalogError as error:
        if error.code != "agent_project_not_found":
            raise
        catalog.create_project(CreateAgentProject(name="Synthetic scope project"))
    identities = iter(ids or ["c" * 32])
    options = (
        {"activity_epoch_factory": lambda: activity_epoch}
        if activity_epoch is not None
        else {}
    )
    return AgentMcpConnectionService(
        SqliteAgentMcpConnectionRepository(database),
        token_pepper=master,
        clock=lambda: now[0],
        id_factory=identities.__next__,
        **options,
    )


def _create(
    service: AgentMcpConnectionService,
    *,
    request_id: str = "a" * 32,
    label: str = "Synthetic Codex connection",
    client_kind: str = "codex",
    allow_model_lifecycle: bool = False,
    expires_in_days: int = 90,
    project_id: str = PROJECT_ID,
):
    return service.create(
        CreateAgentMcpConnection(
            request_id=request_id,
            label=label,
            client_kind=client_kind,
            project_id=project_id,
            allow_model_lifecycle=allow_model_lifecycle,
            expires_in_days=expires_in_days,
        ),
        endpoint_url=ENDPOINT,
    )


def test_connection_survives_restart_and_stores_no_bearer_secret(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    created = _create(_service(database, now=now))

    assert created.connection.state == "active"
    assert created.connection.allow_model_lifecycle is False
    assert created.secret_stored_by_server is False
    assert created.starts_process is False
    assert created.starts_terminal is False
    assert created.bearer_token.startswith("pemcp2.")
    assert created.connection.scope.project_id == PROJECT_ID
    assert created.connection.scope.project_name == "Synthetic scope project"
    assert created.connection.scope.native_approval_inherited is False
    assert created.bearer_token not in created.codex_toml
    assert created.bearer_token not in created.claude_json
    assert 'url = "http://127.0.0.1:8765/mcp/agent"' in created.codex_toml
    assert f'bearer_token_env_var = "{AGENT_MCP_BEARER_ENV}"' in created.codex_toml
    assert '"type": "http"' in created.claude_json
    assert f'Bearer ${{{AGENT_MCP_BEARER_ENV}}}' in created.claude_json

    with database.connect() as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(agent_mcp_connections)"
            ).fetchall()
        }
        row = connection.execute(
            "SELECT * FROM agent_mcp_connections"
        ).fetchone()
    assert row is not None
    assert "token" not in " ".join(columns)
    assert created.bearer_token not in " ".join(str(value) for value in row)

    now[0] += timedelta(minutes=2)
    restarted = _service(database, now=now, ids=["d" * 32])
    principal = restarted.authenticate(created.bearer_token)
    assert principal.connection_id == created.connection.connection_id
    assert principal.client_kind == "codex"
    assert principal.allow_model_lifecycle is False
    assert principal.project_id == PROJECT_ID
    listed = restarted.list()
    assert listed.active_count == 1
    assert listed.connections[0].last_used_at == now[0]
    assert listed.connections[0].last_tool_at is None
    assert listed.connections[0].last_tool_name is None
    assert listed.connections[0].last_tool_outcome is None
    assert listed.connections[0].last_tool_source is None
    assert listed.connections[0].last_auth_rejected_at is None

    now[0] += timedelta(seconds=1)
    restarted.record_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        tool_name="agent_open",
        outcome="succeeded",
        source="external_client",
    )
    activity = restarted.list().connections[0]
    assert activity.last_tool_at == now[0]
    assert activity.last_tool_name == "agent_open"
    assert activity.last_tool_outcome == "succeeded"
    assert activity.last_tool_source == "external_client"

    wrong_owner = _service(
        database,
        now=now,
        ids=["e" * 32],
        master=OTHER_MASTER,
    )
    with pytest.raises(AgentMcpConnectionError) as rejected:
        wrong_owner.authenticate(created.bearer_token)
    assert rejected.value.code == "agent_mcp_authentication_failed"
    assert wrong_owner.list().connections[0].last_auth_rejected_at is None


def test_tool_activity_rejects_unbounded_names_and_preserves_latest_receipt(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now)
    created = _create(service)
    service.authenticate(created.bearer_token)

    with pytest.raises(AgentMcpConnectionError) as invalid:
        service.record_tool_call(
            created.connection.connection_id,
            credential_revision=created.connection.credential_revision,
            tool_name="unsafe/tool/name",
            outcome="failed",
            source="external_client",
        )
    assert invalid.value.code == "agent_mcp_tool_activity_invalid"

    with pytest.raises(AgentMcpConnectionError) as invalid_source:
        service.record_tool_call(
            created.connection.connection_id,
            credential_revision=created.connection.credential_revision,
            tool_name="agent_open",
            outcome="failed",
            source="untrusted",  # type: ignore[arg-type]
        )
    assert invalid_source.value.code == "agent_mcp_tool_activity_invalid"

    service.record_tool_call(
        created.connection.connection_id,
        credential_revision=created.connection.credential_revision,
        tool_name="unknown_tool",
        outcome="failed",
        source="native_self_test",
    )
    now[0] += timedelta(seconds=1)
    service.record_tool_call(
        created.connection.connection_id,
        credential_revision=created.connection.credential_revision,
        tool_name="agent_turn",
        outcome="succeeded",
        source="external_client",
    )
    observed = service.list().connections[0]
    assert observed.last_tool_name == "agent_turn"
    assert observed.last_tool_outcome == "succeeded"
    assert observed.last_tool_source == "external_client"
    assert observed.last_tool_at == now[0]


def test_tool_activity_sequence_is_exact_content_free_and_process_bound(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(
        database,
        now=now,
        activity_epoch="f" * 32,
    )
    created = _create(service)
    principal = service.authenticate(created.bearer_token)

    baseline = service.list()
    assert baseline.contract_version == "agent-mcp-management.v2"
    assert baseline.activity_epoch == "f" * 32
    assert baseline.tool_activity_sequences[0].model_dump() == {
        "contract_version": "agent-mcp-tool-activity-sequence.v1",
        "connection_id": created.connection.connection_id,
        "credential_revision": 1,
        "sequence": 0,
        "tool_name": None,
        "tool_source": None,
        "started_at": None,
        "completed_at": None,
        "outcome": None,
    }

    admitted_sequence = service.begin_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        tool_name="unknown_tool",
        source="native_self_test",
    )
    admitted = service.list().tool_activity_sequences[0]
    assert admitted.sequence == admitted_sequence == 1
    assert admitted.tool_name == "unknown_tool"
    assert admitted.tool_source == "native_self_test"
    assert admitted.started_at == now[0]
    assert admitted.completed_at is None
    assert admitted.outcome is None
    assert service.list().connections[0].last_tool_at is None
    service.finish_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        sequence=admitted_sequence,
        tool_name="unknown_tool",
        outcome="failed",
        source="native_self_test",
    )
    service.record_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        tool_name="agent_turn",
        outcome="succeeded",
        source="external_client",
    )
    assert service.list().tool_activity_sequences[0].sequence == 2

    restarted = _service(
        database,
        now=now,
        ids=["d" * 32],
        activity_epoch="e" * 32,
    )
    after_restart = restarted.list()
    assert after_restart.activity_epoch == "e" * 32
    assert after_restart.tool_activity_sequences[0].sequence == 0
    assert after_restart.connections[0].last_tool_name == "agent_turn"


def test_tool_activity_sequence_rejects_a_stale_credential_revision(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now)
    created = _create(service)
    rotated = service.rotate(
        created.connection.connection_id,
        RotateAgentMcpConnection(
            request_id="b" * 32,
            expected_revision=created.connection.revision,
        ),
        endpoint_url=ENDPOINT,
    )

    with pytest.raises(AgentMcpConnectionError) as stale:
        service.record_tool_call(
            created.connection.connection_id,
            credential_revision=created.connection.credential_revision,
            tool_name="agent_discover",
            outcome="succeeded",
            source="external_client",
        )
    assert stale.value.code == "agent_mcp_tool_activity_stale"
    cursor = service.list().tool_activity_sequences[0]
    assert cursor.credential_revision == rotated.connection.credential_revision
    assert cursor.sequence == 0


def test_late_completion_cannot_overwrite_a_newer_admitted_tool(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now)
    created = _create(service)
    principal = service.authenticate(created.bearer_token)

    turn_sequence = service.begin_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        tool_name="agent_turn",
        source="external_client",
    )
    now[0] += timedelta(seconds=1)
    stop_sequence = service.begin_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        tool_name="agent_stop",
        source="external_client",
    )
    service.finish_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        sequence=stop_sequence,
        tool_name="agent_stop",
        outcome="succeeded",
        source="external_client",
    )
    now[0] += timedelta(seconds=1)
    service.finish_tool_call(
        principal.connection_id,
        credential_revision=principal.credential_revision,
        sequence=turn_sequence,
        tool_name="agent_turn",
        outcome="succeeded",
        source="external_client",
    )

    latest = service.list()
    assert latest.tool_activity_sequences[0].sequence == stop_sequence == 2
    assert latest.tool_activity_sequences[0].tool_name == "agent_stop"
    assert latest.tool_activity_sequences[0].outcome == "succeeded"
    assert latest.connections[0].last_tool_name == "agent_stop"


def test_create_is_idempotent_and_conflicting_reuse_fails_closed(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(
        database,
        now=now,
        ids=["1" * 32, "2" * 32, "3" * 32],
    )

    first = _create(service)
    replay = _create(service)

    assert replay.idempotent_replay is True
    assert replay.connection.connection_id == first.connection.connection_id
    assert replay.bearer_token == first.bearer_token
    assert service.list().active_count == 1

    with pytest.raises(AgentMcpConnectionError) as conflict:
        _create(service, label="Different synthetic label")
    assert conflict.value.code == "agent_mcp_connection_request_conflict"


def test_invalid_endpoint_cannot_create_or_rotate_durable_authority(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now, ids=["1" * 32, "2" * 32])
    command = CreateAgentMcpConnection(
        request_id="a" * 32,
        label="Synthetic connection",
        client_kind="other",
        project_id=PROJECT_ID,
    )

    with pytest.raises(AgentMcpConnectionError) as create_rejected:
        service.create(
            command,
            endpoint_url="http://example.invalid:8765/mcp/agent",
        )
    assert create_rejected.value.code == "agent_mcp_endpoint_invalid"
    assert service.list().connections == ()

    created = service.create(command, endpoint_url=ENDPOINT)
    with pytest.raises(AgentMcpConnectionError) as rotate_rejected:
        service.rotate(
            created.connection.connection_id,
            RotateAgentMcpConnection(
                request_id="b" * 32,
                expected_revision=created.connection.revision,
            ),
            endpoint_url="http://0.0.0.0:8765/mcp/agent",
        )
    assert rotate_rejected.value.code == "agent_mcp_endpoint_invalid"
    unchanged = service.list().connections[0]
    assert unchanged.revision == created.connection.revision
    assert unchanged.credential_revision == created.connection.credential_revision


def test_rotation_is_idempotent_and_invalidates_the_previous_credential(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(
        database,
        now=now,
        ids=["c" * 32, "d" * 32],
    )
    created = _create(service, allow_model_lifecycle=True)
    now[0] += timedelta(hours=1)
    command = RotateAgentMcpConnection(
        request_id="b" * 32,
        expected_revision=created.connection.revision,
        expires_in_days=30,
    )

    rotated = service.rotate(
        created.connection.connection_id,
        command,
        endpoint_url=ENDPOINT,
    )
    replay = service.rotate(
        created.connection.connection_id,
        command,
        endpoint_url=ENDPOINT,
    )

    assert rotated.connection.revision == 2
    assert rotated.connection.credential_revision == 2
    assert rotated.bearer_token != created.bearer_token
    assert replay.idempotent_replay is True
    assert replay.bearer_token == rotated.bearer_token
    assert service.authenticate(rotated.bearer_token).allow_model_lifecycle is True
    now[0] += timedelta(seconds=1)
    with pytest.raises(AgentMcpConnectionError):
        service.authenticate(created.bearer_token)
    observed = service.list().connections[0]
    assert observed.state == "active"
    assert observed.last_auth_rejected_at == now[0]


def test_revocation_is_restart_durable_and_safe_to_repeat(tmp_path: Path) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now, ids=["c" * 32, "d" * 32])
    created = _create(service)
    now[0] += timedelta(minutes=5)

    revoked = service.revoke(
        created.connection.connection_id,
        RevokeAgentMcpConnection(
            expected_revision=created.connection.revision
        ),
    )
    repeated = service.revoke(
        created.connection.connection_id,
        RevokeAgentMcpConnection(
            expected_revision=created.connection.revision
        ),
    )

    assert revoked.state == "revoked"
    assert revoked.revision == 2
    assert repeated == revoked
    assert service.list().active_count == 0
    restarted = _service(database, now=now, ids=["d" * 32])
    now[0] += timedelta(seconds=1)
    with pytest.raises(AgentMcpConnectionError) as rejected:
        restarted.authenticate(created.bearer_token)
    assert rejected.value.code == "agent_mcp_authentication_failed"
    observed = restarted.list().connections[0]
    assert observed.last_auth_rejected_at == now[0]
    assert observed.revoked_at is not None
    assert observed.last_auth_rejected_at > observed.revoked_at


def test_two_project_credentials_remain_independently_scoped_and_revocable(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    other_project_id = "8" * 32
    AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: now[0],
        id_factory=lambda: other_project_id,
    ).create_project(CreateAgentProject(name="Synthetic second scope"))
    service = _service(
        database,
        now=now,
        ids=["c" * 32, "d" * 32],
    )
    first = _create(
        service,
        request_id="1" * 32,
        label="Synthetic project A client",
        project_id=PROJECT_ID,
    )
    second = _create(
        service,
        request_id="2" * 32,
        label="Synthetic project B client",
        project_id=other_project_id,
    )

    assert service.authenticate(first.bearer_token).project_id == PROJECT_ID
    assert service.authenticate(second.bearer_token).project_id == other_project_id
    assert first.bearer_token != second.bearer_token
    assert first.connection.scope.native_approval_inherited is False
    assert second.connection.scope.native_approval_inherited is False

    revoked = service.revoke(
        first.connection.connection_id,
        RevokeAgentMcpConnection(
            expected_revision=first.connection.revision,
        ),
    )
    assert revoked.state == "revoked"
    with pytest.raises(AgentMcpConnectionError) as first_rejected:
        service.authenticate(first.bearer_token)
    assert first_rejected.value.code == "agent_mcp_authentication_failed"
    assert service.authenticate(second.bearer_token).project_id == other_project_id
    listed = service.list()
    assert listed.active_count == 1
    assert {item.scope.project_id for item in listed.connections} == {
        PROJECT_ID,
        other_project_id,
    }


def test_expired_or_malformed_credentials_fail_with_one_closed_error(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(
        database,
        now=now,
        ids=["c" * 32, "d" * 32, "e" * 32],
    )
    created = _create(service, expires_in_days=1)
    now[0] += timedelta(days=1)

    for candidate in (created.bearer_token, "not-a-credential", ""):
        with pytest.raises(AgentMcpConnectionError) as rejected:
            service.authenticate(candidate)
        assert rejected.value.code == "agent_mcp_authentication_failed"
    expired = service.list().connections[0]
    assert expired.state == "expired"
    assert expired.last_auth_rejected_at == now[0]
    with pytest.raises(AgentMcpConnectionError) as replay:
        _create(service, expires_in_days=1)
    assert replay.value.code == "agent_mcp_connection_replay_inactive"

    with pytest.raises(AgentMcpConnectionError) as rotation:
        service.rotate(
            created.connection.connection_id,
            RotateAgentMcpConnection(
                request_id="b" * 32,
                expected_revision=created.connection.revision,
                expires_in_days=30,
            ),
            endpoint_url=ENDPOINT,
        )
    assert rotation.value.code == "agent_mcp_connection_inactive"

    replacement = _create(
        service,
        request_id="c" * 32,
        label="Synthetic replacement connection",
        expires_in_days=30,
    )
    assert replacement.connection.connection_id != created.connection.connection_id
    assert replacement.connection.state == "active"
    assert service.list().active_count == 1


def test_active_connection_limit_counts_neither_expired_nor_revoked(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    ids = [f"{index:032x}" for index in range(1, MAX_AGENT_MCP_CONNECTIONS + 3)]
    service = _service(database, now=now, ids=ids)
    for index in range(MAX_AGENT_MCP_CONNECTIONS):
        _create(
            service,
            request_id=f"{index + 100:032x}",
            label=f"Synthetic connection {index + 1}",
            client_kind="other",
        )
    with pytest.raises(AgentMcpConnectionError) as full:
        _create(
            service,
            request_id="f" * 32,
            label="One connection too many",
            client_kind="other",
        )
    assert full.value.code == "too_many_agent_mcp_connections"


def test_schema_five_migrates_without_changing_existing_agent_projects(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    database.path.parent.mkdir(parents=True)
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE agent_catalog_schema_migrations (
                version INTEGER PRIMARY KEY CHECK(version > 0),
                applied_at TEXT NOT NULL
            ) STRICT
            """
        )
        for statement in agent_catalog_sqlite._SCHEMA_V1.split(";"):
            if statement.strip():
                connection.execute(statement)
        for version, statements in (
            (2, agent_catalog_sqlite._SCHEMA_V2),
            (3, agent_catalog_sqlite._SCHEMA_V3),
            (4, agent_catalog_sqlite._SCHEMA_V4),
            (5, agent_catalog_sqlite._SCHEMA_V5),
        ):
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO agent_catalog_schema_migrations(version, applied_at) "
                "VALUES (?, ?)",
                (version, T0.isoformat()),
            )
        connection.execute(
            "INSERT INTO agent_catalog_schema_migrations(version, applied_at) "
            "VALUES (1, ?)",
            (T0.isoformat(),),
        )
        connection.execute(
            """
            INSERT INTO agent_projects(
                project_id,name,created_at,updated_at,revision,pinned,archived_at,is_default
            ) VALUES(?,?,?,?,1,0,NULL,0)
            """,
            (PROJECT_ID, "Migration project", T0.isoformat(), T0.isoformat()),
        )
        connection.execute("PRAGMA user_version=5")

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    assert AgentCatalogService(
        SqliteAgentCatalogRepository(migrated)
    ).get_project(PROJECT_ID).name == "Migration project"
    assert _service(migrated, now=[T0]).list().connections == ()
    with migrated.connect() as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(agent_mcp_connections)"
            ).fetchall()
        }
    assert {
        "last_tool_at",
        "last_tool_name",
        "last_tool_outcome",
        "last_tool_source",
        "last_auth_rejected_at",
        "scope_project_id",
    } <= columns


def test_legacy_unscoped_connection_fails_closed_and_cannot_rotate(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = _database(tmp_path)
    service = _service(database, now=now)
    created = _create(service)
    with database.connect() as connection:
        connection.execute(
            "UPDATE agent_mcp_connections SET scope_project_id=NULL "
            "WHERE connection_id=?",
            (created.connection.connection_id,),
        )

    observed = service.list().connections[0]
    assert observed.state == "scope_missing"
    assert observed.scope.state == "missing"
    assert observed.scope.catalog_access == "none"
    assert service.list().active_count == 0
    with pytest.raises(AgentMcpConnectionError) as authentication:
        service.authenticate(created.bearer_token)
    assert authentication.value.code == "agent_mcp_authentication_failed"
    with pytest.raises(AgentMcpConnectionError) as rotation:
        service.rotate(
            observed.connection_id,
            RotateAgentMcpConnection(
                request_id="b" * 32,
                expected_revision=observed.revision,
            ),
            endpoint_url=ENDPOINT,
        )
    assert rotation.value.code == "agent_mcp_connection_inactive"


def test_connection_commands_reject_unsafe_labels_and_expiry_values() -> None:
    for label in ("", "   ", "bad\nlabel", "x" * 81):
        with pytest.raises(ValidationError):
            CreateAgentMcpConnection(
                request_id="a" * 32,
                label=label,
                client_kind="other",
                project_id=PROJECT_ID,
            )
    with pytest.raises(ValidationError):
        CreateAgentMcpConnection(
            request_id="a" * 32,
            label="Synthetic",
            client_kind="other",
            project_id=PROJECT_ID,
            expires_in_days=366,
        )
