"""Durable, content-free ownership for project-scoped Agent controllers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogService,
    CreateAgentProject,
)
from prompt_enhancer.application.agent_controller_ownership import (
    AcceptAgentControllerHandoff,
    AgentControllerOwnershipError,
    OfferAgentControllerHandoff,
    ReleaseAgentControllerOwnership,
)
from prompt_enhancer.application.agent_controller_client import (
    AgentControllerInvocationResult,
    AgentControllerStopResult,
    AgentControllerTurnResult,
)
from prompt_enhancer.application.agent_mcp_connections import (
    AgentMcpConnectionService,
    CreateAgentMcpConnection,
    RevokeAgentMcpConnection,
)
from prompt_enhancer.application.agent_mcp_surface import (
    AgentMcpSurface,
    AgentMcpSurfaceError,
)
from prompt_enhancer.application.local_agent import AgentWriteProposalReceipt
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
    SqliteAgentMcpConnectionRepository,
)


T0 = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
MASTER = "synthetic-controller-pepper-" * 3
ENDPOINT = "http://127.0.0.1:8765/mcp/agent"
PROJECT_A = "1" * 32
PROJECT_B = "2" * 32
SESSION_A = "3" * 32
CONNECTION_A = "a" * 32
CONNECTION_B = "b" * 32
CONNECTION_OTHER_PROJECT = "c" * 32


def _database(tmp_path: Path) -> AgentCatalogSqliteDatabase:
    return AgentCatalogSqliteDatabase(
        tmp_path / "synthetic-private" / AGENT_CATALOG_DATABASE_FILENAME
    )


def _catalog(
    database: AgentCatalogSqliteDatabase,
    *,
    now: list[datetime],
) -> AgentCatalogService:
    return AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: now[0],
        id_factory=iter((PROJECT_A, PROJECT_B)).__next__,
    )


def _connection_service(
    database: AgentCatalogSqliteDatabase,
    *,
    now: list[datetime],
    ids: tuple[str, ...] = (
        CONNECTION_A,
        CONNECTION_B,
        CONNECTION_OTHER_PROJECT,
    ),
) -> AgentMcpConnectionService:
    return AgentMcpConnectionService(
        SqliteAgentMcpConnectionRepository(database),
        token_pepper=MASTER,
        clock=lambda: now[0],
        id_factory=iter(ids).__next__,
    )


def _seed(
    tmp_path: Path,
) -> tuple[
    AgentCatalogSqliteDatabase,
    list[datetime],
    AgentMcpConnectionService,
]:
    now = [T0]
    database = _database(tmp_path)
    catalog = _catalog(database, now=now)
    project_a = catalog.create_project(CreateAgentProject(name="Synthetic alpha"))
    project_b = catalog.create_project(CreateAgentProject(name="Synthetic beta"))
    assert project_a.project_id == PROJECT_A
    assert project_b.project_id == PROJECT_B
    catalog.register_live_session(
        session_id=SESSION_A,
        project_id=PROJECT_A,
        title="Synthetic controller chat",
        workspace=tmp_path / "synthetic-workspace",
        model_alias="synthetic-model",
        created_at=T0,
    )

    service = _connection_service(database, now=now)
    for request_id, label, kind, project_id in (
        ("d" * 32, "Synthetic owner", "codex", PROJECT_A),
        ("e" * 32, "Synthetic recipient", "claude", PROJECT_A),
        ("f" * 32, "Synthetic other project", "other", PROJECT_B),
    ):
        service.create(
            CreateAgentMcpConnection(
                request_id=request_id,
                label=label,
                client_kind=kind,
                project_id=project_id,
            ),
            endpoint_url=ENDPOINT,
        )
    return database, now, service


def test_explicit_app_restart_reconciles_only_non_live_controller_authority(
    tmp_path: Path,
) -> None:
    database, now, service = _seed(tmp_path)
    claimed = service.ownership.claim(
        connection_id=CONNECTION_A,
        project_id=PROJECT_A,
        session_id=SESSION_A,
        operation="turn",
    )
    updated = service.ownership.update(
        SESSION_A,
        owner_connection_id=CONNECTION_A,
        state="waiting_native_approval",
        cursor=7,
        last_seq=8,
        approval_pending=True,
    )

    assert claimed.revision == 1
    assert updated.revision == 2
    assert updated.native_approval_inherited is False
    projected = service.list()
    assert projected.contract_version == "agent-mcp-management.v2"
    assert projected.controller_ownerships.active_count == 1
    assert projected.controller_ownerships.ownerships == (updated,)

    offered = service.ownership.offer(
        owner_connection_id=CONNECTION_A,
        command=OfferAgentControllerHandoff(
            session_id=SESSION_A,
            target_connection_id=CONNECTION_B,
            expected_revision=updated.revision,
        ),
    )
    assert offered.handoff is not None

    now[0] += timedelta(minutes=2)
    restarted = _connection_service(
        AgentCatalogSqliteDatabase(database.path),
        now=now,
        ids=("9" * 32,),
    )
    recovered = restarted.ownership.get(SESSION_A)
    assert recovered is not None
    assert recovered.owner_connection_id == CONNECTION_A
    assert recovered.state == "waiting_native_approval"
    assert recovered.cursor == 7
    assert recovered.last_seq == 8
    assert recovered.approval_pending is True
    assert recovered.handoff is not None

    live_receipt = restarted.ownership.reconcile_after_restart(
        live_session_ids=(SESSION_A,),
    )
    assert live_receipt.observed_ownerships == 1
    assert live_receipt.live_ownerships_preserved == 1
    assert live_receipt.changed_ownerships == 0
    assert restarted.ownership.get(SESSION_A) == recovered

    stale_receipt = restarted.ownership.reconcile_after_restart(
        live_session_ids=(),
    )
    assert stale_receipt.observed_ownerships == 1
    assert stale_receipt.live_ownerships_preserved == 0
    assert stale_receipt.non_live_submission_uncertain == 1
    assert stale_receipt.changed_ownerships == 1
    assert stale_receipt.native_approvals_cleared == 1
    assert stale_receipt.handoffs_cleared == 1
    assert stale_receipt.stale_native_approval_retained is False
    assert stale_receipt.stale_handoff_retained is False
    reconciled = restarted.ownership.get(SESSION_A)
    assert reconciled is not None
    assert reconciled.state == "submission_uncertain"
    assert reconciled.approval_pending is False
    assert reconciled.handoff is None
    assert reconciled.revision == offered.revision + 1

    repeated = restarted.ownership.reconcile_after_restart(
        live_session_ids=(),
    )
    assert repeated.changed_ownerships == 0
    assert repeated.native_approvals_cleared == 0
    assert repeated.handoffs_cleared == 0
    assert restarted.ownership.get(SESSION_A) == reconciled


@pytest.mark.parametrize(
    ("initial_state", "expected_state", "expected_changed"),
    [
        ("claimed", "submission_uncertain", 1),
        ("running", "submission_uncertain", 1),
        ("waiting_native_approval", "submission_uncertain", 1),
        ("reconnecting", "submission_uncertain", 1),
        ("submission_uncertain", "submission_uncertain", 0),
        ("stopping", "cleanup_unconfirmed", 1),
        ("stop_uncertain", "cleanup_unconfirmed", 1),
        ("cleanup_unconfirmed", "cleanup_unconfirmed", 0),
        ("revoked", "revoked", 0),
    ],
)
def test_controller_restart_state_matrix_is_fail_closed_and_idempotent(
    tmp_path: Path,
    initial_state: str,
    expected_state: str,
    expected_changed: int,
) -> None:
    _database_value, _now, service = _seed(tmp_path)
    current = service.ownership.claim(
        connection_id=CONNECTION_A,
        project_id=PROJECT_A,
        session_id=SESSION_A,
        operation="turn",
    )
    if initial_state != "claimed":
        current = service.ownership.update(
            SESSION_A,
            owner_connection_id=CONNECTION_A,
            state=initial_state,  # type: ignore[arg-type]
            cursor=0,
            last_seq=0,
            approval_pending=initial_state == "waiting_native_approval",
        )

    receipt = service.ownership.reconcile_after_restart(live_session_ids=())
    recovered = service.ownership.get(SESSION_A)

    assert recovered is not None
    assert recovered.state == expected_state
    assert recovered.approval_pending is False
    assert recovered.handoff is None
    assert receipt.changed_ownerships == expected_changed
    assert recovered.revision == current.revision + expected_changed
    if expected_state == "submission_uncertain":
        assert receipt.non_live_submission_uncertain == 1
    elif expected_state == "cleanup_unconfirmed":
        assert receipt.non_live_cleanup_unconfirmed == 1
    else:
        assert receipt.non_live_revoked == 1

    repeated = service.ownership.reconcile_after_restart(live_session_ids=())
    assert repeated.changed_ownerships == 0
    assert service.ownership.get(SESSION_A) == recovered


def test_http_composition_reconciles_catalog_ownership_before_serving(
    tmp_path: Path,
) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))
    database = AgentCatalogSqliteDatabase(application.settings.agent_catalog_path)
    now = [T0]
    catalog = _catalog(database, now=now)
    project = catalog.create_project(CreateAgentProject(name="Synthetic boot project"))
    catalog.register_live_session(
        session_id=SESSION_A,
        project_id=project.project_id,
        title="Synthetic prior-run chat",
        workspace=tmp_path / "synthetic-boot-workspace",
        model_alias="synthetic-model",
        created_at=T0,
    )
    seeded = _connection_service(
        database,
        now=now,
        ids=(CONNECTION_A,),
    )
    seeded.create(
        CreateAgentMcpConnection(
            request_id="d" * 32,
            label="Synthetic prior-run owner",
            client_kind="codex",
            project_id=project.project_id,
        ),
        endpoint_url=ENDPOINT,
    )
    claimed = seeded.ownership.claim(
        connection_id=CONNECTION_A,
        project_id=project.project_id,
        session_id=SESSION_A,
        operation="turn",
    )
    seeded.ownership.update(
        SESSION_A,
        owner_connection_id=CONNECTION_A,
        state="waiting_native_approval",
        cursor=0,
        last_seq=0,
        approval_pending=True,
    )

    http_app = application.create_http_app()

    assert http_app is not None
    recovered = _connection_service(
        AgentCatalogSqliteDatabase(application.settings.agent_catalog_path),
        now=now,
        ids=("9" * 32,),
    ).ownership.get(SESSION_A)
    assert recovered is not None
    assert recovered.state == "submission_uncertain"
    assert recovered.approval_pending is False
    assert recovered.revision == claimed.revision + 2


def test_claim_is_exactly_once_under_race_and_cross_project_fails_closed(
    tmp_path: Path,
) -> None:
    database, now, _service = _seed(tmp_path)
    owner_a = _connection_service(
        AgentCatalogSqliteDatabase(database.path),
        now=now,
        ids=("8" * 32,),
    ).ownership
    owner_b = _connection_service(
        AgentCatalogSqliteDatabase(database.path),
        now=now,
        ids=("7" * 32,),
    ).ownership

    def claim(connection_id: str, ownership) -> tuple[str, str]:
        try:
            result = ownership.claim(
                connection_id=connection_id,
                project_id=PROJECT_A,
                session_id=SESSION_A,
                operation="turn",
            )
        except AgentControllerOwnershipError as error:
            return "error", error.code
        return "owner", result.owner_connection_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda item: claim(*item),
                ((CONNECTION_A, owner_a), (CONNECTION_B, owner_b)),
            )
        )
    assert sorted(kind for kind, _value in outcomes) == ["error", "owner"]
    assert next(value for kind, value in outcomes if kind == "error") == (
        "agent_controller_session_owned"
    )
    winner = next(value for kind, value in outcomes if kind == "owner")
    assert winner in {CONNECTION_A, CONNECTION_B}

    owner_a.release_owner(
        owner_connection_id=winner,
        session_id=SESSION_A,
    )
    with pytest.raises(AgentControllerOwnershipError) as mismatch:
        owner_a.claim(
            connection_id=CONNECTION_OTHER_PROJECT,
            project_id=PROJECT_B,
            session_id=SESSION_A,
            operation="turn",
        )
    assert mismatch.value.code == "agent_controller_scope_mismatch"


def test_handoff_is_two_party_revision_bound_same_project_and_expires(
    tmp_path: Path,
) -> None:
    _database_value, now, service = _seed(tmp_path)
    ownership = service.ownership
    claimed = ownership.claim(
        connection_id=CONNECTION_A,
        project_id=PROJECT_A,
        session_id=SESSION_A,
        operation="turn",
    )

    with pytest.raises(AgentControllerOwnershipError) as self_target:
        ownership.offer(
            owner_connection_id=CONNECTION_A,
            command=OfferAgentControllerHandoff(
                session_id=SESSION_A,
                target_connection_id=CONNECTION_A,
                expected_revision=claimed.revision,
            ),
        )
    assert self_target.value.code == "agent_controller_handoff_target_invalid"
    with pytest.raises(AgentControllerOwnershipError) as cross_project:
        ownership.offer(
            owner_connection_id=CONNECTION_A,
            command=OfferAgentControllerHandoff(
                session_id=SESSION_A,
                target_connection_id=CONNECTION_OTHER_PROJECT,
                expected_revision=claimed.revision,
            ),
        )
    assert cross_project.value.code == "agent_controller_handoff_target_invalid"

    offered = ownership.offer(
        owner_connection_id=CONNECTION_A,
        command=OfferAgentControllerHandoff(
            session_id=SESSION_A,
            target_connection_id=CONNECTION_B,
            expected_revision=claimed.revision,
        ),
    )
    assert offered.handoff is not None
    assert offered.handoff.target_connection_id == CONNECTION_B
    assert offered.native_approval_inherited is False
    with pytest.raises(AgentControllerOwnershipError) as wrong_target:
        ownership.accept(
            target_connection_id=CONNECTION_OTHER_PROJECT,
            command=AcceptAgentControllerHandoff(
                session_id=SESSION_A,
                expected_revision=offered.revision,
            ),
        )
    assert wrong_target.value.code == "agent_controller_handoff_not_target"
    with pytest.raises(AgentControllerOwnershipError) as stale:
        ownership.accept(
            target_connection_id=CONNECTION_B,
            command=AcceptAgentControllerHandoff(
                session_id=SESSION_A,
                expected_revision=claimed.revision,
            ),
        )
    assert stale.value.code == "agent_controller_ownership_revision_conflict"

    accepted = ownership.accept(
        target_connection_id=CONNECTION_B,
        command=AcceptAgentControllerHandoff(
            session_id=SESSION_A,
            expected_revision=offered.revision,
        ),
    )
    assert accepted.owner_connection_id == CONNECTION_B
    assert accepted.owner_since == now[0]
    assert accepted.handoff is None
    assert accepted.native_approval_inherited is False

    ownership.release_owner(
        owner_connection_id=CONNECTION_B,
        session_id=SESSION_A,
    )
    claimed_again = ownership.claim(
        connection_id=CONNECTION_A,
        project_id=PROJECT_A,
        session_id=SESSION_A,
        operation="turn",
    )
    expiring = ownership.offer(
        owner_connection_id=CONNECTION_A,
        command=OfferAgentControllerHandoff(
            session_id=SESSION_A,
            target_connection_id=CONNECTION_B,
            expected_revision=claimed_again.revision,
        ),
    )
    now[0] += timedelta(minutes=11)
    assert ownership.get(SESSION_A).handoff is None  # type: ignore[union-attr]
    with pytest.raises(AgentControllerOwnershipError) as expired:
        ownership.accept(
            target_connection_id=CONNECTION_B,
            command=AcceptAgentControllerHandoff(
                session_id=SESSION_A,
                expected_revision=expiring.revision,
            ),
        )
    assert expired.value.code == "agent_controller_handoff_expired"


def test_revocation_is_visible_until_proof_gated_native_release(
    tmp_path: Path,
) -> None:
    _database_value, _now, service = _seed(tmp_path)
    ownership = service.ownership
    ownership.claim(
        connection_id=CONNECTION_A,
        project_id=PROJECT_A,
        session_id=SESSION_A,
        operation="turn",
    )
    connection = next(
        item for item in service.list().connections if item.connection_id == CONNECTION_A
    )
    service.revoke(
        CONNECTION_A,
        RevokeAgentMcpConnection(expected_revision=connection.revision),
    )

    revoked = ownership.get(SESSION_A)
    assert revoked is not None
    assert revoked.state == "revoked"
    assert revoked.handoff is None
    with pytest.raises(AgentControllerOwnershipError) as active_release:
        ownership.release_native(
            ReleaseAgentControllerOwnership(
                session_id=SESSION_A,
                expected_revision=revoked.revision,
            ),
            session_settled=False,
        )
    assert active_release.value.code == "agent_controller_session_not_settled"
    receipt = ownership.release_native(
        ReleaseAgentControllerOwnership(
            session_id=SESSION_A,
            expected_revision=revoked.revision,
        ),
        session_settled=True,
    )
    assert receipt.released_by == "native"
    assert receipt.released_connection_id == CONNECTION_A
    assert receipt.session_settled is True
    assert receipt.native_approval_inherited is False
    assert ownership.get(SESSION_A) is None


def test_schema_twenty_three_migrates_without_inventing_ownership(
    tmp_path: Path,
) -> None:
    database, _now, service = _seed(tmp_path)
    assert service.list().controller_ownerships.ownerships == ()

    expected_rows = {
        "projects": (PROJECT_A, PROJECT_B),
        "sessions": ((SESSION_A, PROJECT_A),),
        "connections": (
            (CONNECTION_A, PROJECT_A),
            (CONNECTION_B, PROJECT_A),
            (CONNECTION_OTHER_PROJECT, PROJECT_B),
        ),
    }

    def preserved_rows(connection: sqlite3.Connection) -> dict[str, tuple]:
        return {
            "projects": tuple(
                row[0]
                for row in connection.execute(
                    "SELECT project_id FROM agent_projects ORDER BY project_id"
                )
            ),
            "sessions": tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT session_id,project_id FROM agent_catalog_sessions "
                    "ORDER BY session_id"
                )
            ),
            "connections": tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT connection_id,scope_project_id FROM agent_mcp_connections "
                    "ORDER BY connection_id"
                )
            ),
        }

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        # Schemas 32/31 must be absent from a genuine v23 fixture. Leaving these
        # current tables behind makes the forward migration fail on duplicate DDL.
        connection.execute(
            "DROP TABLE IF EXISTS agent_artifact_directory_move_resolutions"
        )
        connection.execute(
            "DROP TABLE IF EXISTS agent_artifact_directory_move_intent_children"
        )
        connection.execute(
            "DROP TABLE IF EXISTS agent_artifact_directory_move_intents"
        )
        connection.execute("DROP TABLE IF EXISTS agent_message_search_fts")
        connection.execute("DROP TABLE IF EXISTS agent_message_search_messages")
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_receipts_immutable"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_receipts_claim_insert"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_claims_immutable"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_claims_scope_insert"
        )
        connection.execute("DROP TABLE mcp_managed_tool_call_claims")
        connection.execute(
            "DROP TABLE mcp_managed_local_configuration_inspections"
        )
        connection.execute("DROP TABLE mcp_managed_host_cleanup_blocks")
        connection.execute("DROP TABLE mcp_managed_host_action_receipts")
        connection.execute("DROP TABLE mcp_managed_tool_call_receipts")
        connection.execute("DROP TABLE agent_controller_ownerships")
        connection.execute("DROP TABLE IF EXISTS agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=24"
        )
        connection.execute("PRAGMA user_version=23")

        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert tables.isdisjoint(
            {
                "agent_controller_ownerships",
                "mcp_managed_tool_call_receipts",
                "mcp_managed_host_action_receipts",
                "mcp_managed_host_cleanup_blocks",
                "mcp_managed_local_configuration_inspections",
                "mcp_managed_tool_call_claims",
                "agent_catalog_migration_checksums",
                "agent_message_search_messages",
                "agent_message_search_fts",
                "agent_artifact_directory_move_intents",
                "agent_artifact_directory_move_intent_children",
                "agent_artifact_directory_move_resolutions",
            }
        )
        assert "scope_project_id" in {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(agent_mcp_connections)")
        }
        assert connection.execute(
            "SELECT MIN(version),MAX(version),COUNT(*) "
            "FROM agent_catalog_schema_migrations"
        ).fetchone() == (1, 23, 23)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 23
        assert preserved_rows(connection) == expected_rows

    migrated = AgentCatalogSqliteDatabase(database.path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    restarted = _connection_service(migrated, now=[T0], ids=("6" * 32,))
    assert restarted.list().controller_ownerships.ownerships == ()
    with migrated.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_controller_ownerships"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            AGENT_CATALOG_SCHEMA_VERSION
        )
        assert preserved_rows(connection) == expected_rows


class _SyntheticOwnedController:
    def __init__(self, catalog_record) -> None:  # noqa: ANN001
        self._catalog_record = catalog_record
        self.wait_calls = 0
        self.stop_calls = 0
        self.turn_calls = 0
        self.proposal_calls = 0

    def invoke(self, request) -> AgentControllerInvocationResult:  # noqa: ANN001
        assert request.operation == "get_catalog_session"
        assert request.path_parameters == {"session_id": SESSION_A}
        return AgentControllerInvocationResult(
            operation=request.operation,
            status_code=200,
            response=self._catalog_record.model_dump(mode="json"),
        )

    def live_session(self, session_id: str):  # noqa: ANN201
        assert session_id == SESSION_A
        return SimpleNamespace(
            settings=SimpleNamespace(project_id=PROJECT_A),
            running=False,
            closing=False,
            stopping=False,
            cleanup_unconfirmed=False,
            pending_approval_id=None,
            last_seq=0,
        )

    def run_turn(self, request, **_options) -> AgentControllerTurnResult:  # noqa: ANN001
        self.turn_calls += 1
        return AgentControllerTurnResult(
            outcome="incomplete",
            session_id=request.session_id,
            submission_state="accepted",
            cursor=2,
            last_seq=2,
        )

    def wait_turn(self, request, **_options) -> AgentControllerTurnResult:  # noqa: ANN001
        self.wait_calls += 1
        outcome = "incomplete" if self.wait_calls == 1 else "settled"
        return AgentControllerTurnResult(
            outcome=outcome,
            session_id=request.session_id,
            submission_state="not_attempted",
            cursor=max(request.after, 2),
            last_seq=max(request.after, 2),
        )

    def stop_turn(self, request, **_options) -> AgentControllerStopResult:  # noqa: ANN001
        self.stop_calls += 1
        return AgentControllerStopResult(
            outcome="stopped",
            session_id=request.session_id,
            stop_request_state="accepted",
            cursor=max(request.after, 2),
            last_seq=max(request.after, 2),
        )

    def propose_write(self, request) -> AgentWriteProposalReceipt:  # noqa: ANN001
        self.proposal_calls += 1
        return AgentWriteProposalReceipt(
            request_id=request.proposal.request_id,
            session_id=request.session_id,
            operation=request.proposal.operation,
            path=request.proposal.path,
            proposed_revision="4" * 64,
            state="pending_native_review",
            approval_id="5" * 32,
            cursor=3,
        )


def _egress() -> dict[str, object]:
    return {
        "task_authorized": True,
        "redaction_previewed": True,
        "destination": "model_context",
    }


def test_scoped_surfaces_enforce_owner_reconnect_handoff_wait_stop_and_proposal(
    tmp_path: Path,
) -> None:
    database, _now, service = _seed(tmp_path)
    catalog_record = AgentCatalogService(
        SqliteAgentCatalogRepository(database)
    ).get_session(SESSION_A)
    controller = _SyntheticOwnedController(catalog_record)
    surface_a = AgentMcpSurface(
        controller,  # type: ignore[arg-type]
        scope_project_id=PROJECT_A,
        controller_connection_id=CONNECTION_A,
        controller_ownership=service.ownership,
    )
    surface_b = AgentMcpSurface(
        controller,  # type: ignore[arg-type]
        scope_project_id=PROJECT_A,
        controller_connection_id=CONNECTION_B,
        controller_ownership=service.ownership,
    )
    assert len(surface_a.tools()) == 19
    assert "agent_control" in {tool.name for tool in surface_a.tools()}
    assert "agent_invoke" not in {tool.name for tool in surface_a.tools()}

    turn = surface_a.call(
        "agent_turn",
        {
            "egress": _egress(),
            "request": {
                "session_id": SESSION_A,
                "message": {"text": "Synthetic bounded request."},
            },
        },
    )
    assert turn["result"]["outcome"] == "incomplete"
    first_owner = service.ownership.get(SESSION_A)
    assert first_owner is not None
    assert first_owner.owner_connection_id == CONNECTION_A
    assert first_owner.state == "reconnecting"

    # A newly constructed surface with the same credential recovers the exact
    # durable owner and cursor without sending the message a second time.
    reconnected_a = AgentMcpSurface(
        controller,  # type: ignore[arg-type]
        scope_project_id=PROJECT_A,
        controller_connection_id=CONNECTION_A,
        controller_ownership=service.ownership,
    )
    status = reconnected_a.call(
        "agent_control",
        {
            "egress": _egress(),
            "action": "status",
            "session_id": SESSION_A,
        },
    )
    assert status["result"]["ownership"]["owner_connection_id"] == CONNECTION_A
    assert controller.turn_calls == 1

    with pytest.raises(AgentMcpSurfaceError) as foreign_wait:
        surface_b.call(
            "agent_wait",
            {
                "egress": _egress(),
                "request": {"session_id": SESSION_A, "after": 2},
            },
        )
    assert foreign_wait.value.code == "agent_controller_session_owned"
    continued = reconnected_a.call(
        "agent_wait",
        {
            "egress": _egress(),
            "request": {"session_id": SESSION_A, "after": 2},
        },
    )
    assert continued["result"]["outcome"] == "incomplete"
    current = service.ownership.get(SESSION_A)
    assert current is not None and current.owner_connection_id == CONNECTION_A

    offered = reconnected_a.call(
        "agent_control",
        {
            "egress": _egress(),
            "action": "offer_handoff",
            "session_id": SESSION_A,
            "expected_revision": current.revision,
            "target_connection_id": CONNECTION_B,
            "mutation_authorized": True,
        },
    )["result"]["ownership"]
    accepted = surface_b.call(
        "agent_control",
        {
            "egress": _egress(),
            "action": "accept_handoff",
            "session_id": SESSION_A,
            "expected_revision": offered["revision"],
            "mutation_authorized": True,
        },
    )["result"]["ownership"]
    assert accepted["owner_connection_id"] == CONNECTION_B
    assert accepted["native_approval_inherited"] is False

    with pytest.raises(AgentMcpSurfaceError) as previous_owner:
        reconnected_a.call(
            "agent_wait",
            {
                "egress": _egress(),
                "request": {"session_id": SESSION_A, "after": 2},
            },
        )
    assert previous_owner.value.code == "agent_controller_session_owned"
    settled = surface_b.call(
        "agent_wait",
        {
            "egress": _egress(),
            "request": {"session_id": SESSION_A, "after": 2},
        },
    )
    assert settled["result"]["outcome"] == "settled"
    assert service.ownership.get(SESSION_A) is None

    surface_a.call(
        "agent_turn",
        {
            "egress": _egress(),
            "request": {
                "session_id": SESSION_A,
                "message": {"text": "Synthetic stoppable request."},
            },
        },
    )
    with pytest.raises(AgentMcpSurfaceError) as foreign_stop:
        surface_b.call(
            "agent_stop",
            {
                "egress": _egress(),
                "mutation_authorized": True,
                "request": {"session_id": SESSION_A, "after": 2},
            },
        )
    assert foreign_stop.value.code == "agent_controller_session_owned"
    stopped = surface_a.call(
        "agent_stop",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {"session_id": SESSION_A, "after": 2},
        },
    )
    assert stopped["result"]["outcome"] == "stopped"
    assert controller.stop_calls == 1
    assert service.ownership.get(SESSION_A) is None

    proposal = surface_a.call(
        "agent_propose",
        {
            "egress": _egress(),
            "mutation_authorized": True,
            "request": {
                "session_id": SESSION_A,
                "proposal": {
                    "request_id": "6" * 32,
                    "operation": "create",
                    "path": "synthetic.txt",
                    "content": "Synthetic content.\n",
                },
            },
        },
    )
    assert proposal["result"]["state"] == "pending_native_review"
    pending = service.ownership.get(SESSION_A)
    assert pending is not None
    assert pending.state == "waiting_native_approval"
    assert pending.approval_pending is True
    assert controller.proposal_calls == 1
    with pytest.raises(AgentMcpSurfaceError) as proposal_foreign_wait:
        surface_b.call(
            "agent_wait",
            {
                "egress": _egress(),
                "request": {"session_id": SESSION_A, "after": 3},
            },
        )
    assert proposal_foreign_wait.value.code == "agent_controller_session_owned"
    surface_a.call(
        "agent_wait",
        {
            "egress": _egress(),
            "request": {"session_id": SESSION_A, "after": 3},
        },
    )
    assert service.ownership.get(SESSION_A) is None
