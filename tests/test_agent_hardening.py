"""Agent-08c: content-free catalog health and restart-readiness evidence."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from prompt_enhancer.application.agent_catalog import (
    AgentCatalogError,
    AgentCatalogService,
    AgentRetentionPolicy,
    CreateAgentProject,
    StoredAgentEvent,
)
from prompt_enhancer.application.agent_hardening import (
    AgentHardeningService,
    AgentLiveHardeningFacts,
    AgentNativeAcceptanceStartReceipt,
    BeginAgentNativeAcceptance,
)
from prompt_enhancer.application.local_agent import LocalAgentService
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
)
from prompt_enhancer.infrastructure.sqlite.agent_hardening import (
    SqliteAgentHardeningProbe,
)
from prompt_enhancer.interfaces.http.agent_hardening_routes import (
    create_agent_hardening_router,
)


T0 = datetime(2026, 8, 27, 20, 0, tzinfo=UTC)


class _LiveSource:
    def __init__(self, facts: AgentLiveHardeningFacts | None = None) -> None:
        self._facts = facts or AgentLiveHardeningFacts(
            sessions=0,
            running_turns=0,
            closing_sessions=0,
            pending_approvals=0,
            cleanup_unconfirmed=0,
            command_cleanup_quarantined=False,
            recovered_read_only=0,
            history_write_failures=0,
            shutting_down=False,
        )

    def hardening_facts(self) -> AgentLiveHardeningFacts:
        return self._facts


class _UnavailableLiveSource:
    def hardening_facts(self) -> AgentLiveHardeningFacts:
        raise RuntimeError("synthetic live-state failure")


class _UnavailableProbe:
    def __init__(self, code: str = "agent_catalog_storage_unavailable") -> None:
        self._code = code

    def inspect(self):
        raise AgentCatalogError(self._code)


def _catalog(tmp_path: Path):
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    ids = iter(f"{index:032x}" for index in range(1, 100))
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: T0,
        id_factory=ids.__next__,
    )
    return database, catalog


def test_on_demand_snapshot_reports_interrupted_recovery_without_content(
    tmp_path: Path,
) -> None:
    database, catalog = _catalog(tmp_path)
    project = catalog.create_project(
        CreateAgentProject(name="Synthetic private project canary")
    )
    retained = catalog.register_live_session(
        session_id="a" * 32,
        project_id=project.project_id,
        title="Synthetic private retained chat",
        workspace=tmp_path / "private-workspace-canary",
        model_alias="private-model-canary",
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    catalog.append_history_event(
        project_id=project.project_id,
        session_id=retained.session_id,
        expected_history_revision=0,
        event=StoredAgentEvent(
            seq=1,
            at=T0,
            kind="user",
            text="SYNTHETIC_PRIVATE_PROMPT_CANARY",
            turn_id="b" * 32,
        ),
    )
    catalog.register_live_session(
        session_id="c" * 32,
        project_id=project.project_id,
        title="Synthetic metadata chat",
        workspace=tmp_path / "metadata-workspace",
        model_alias=None,
        created_at=T0,
    )

    service = AgentHardeningService(
        SqliteAgentHardeningProbe(database),
        _LiveSource(),
    )
    snapshot = service.snapshot()
    payload = snapshot.model_dump_json()

    assert snapshot.catalog.state == "ready"
    assert snapshot.catalog.schema_version == AGENT_CATALOG_SCHEMA_VERSION
    assert snapshot.catalog.counts is not None
    assert snapshot.catalog.counts.projects == 1
    assert snapshot.catalog.counts.sessions == 2
    assert snapshot.catalog.counts.retained_sessions == 1
    assert snapshot.catalog.counts.metadata_only_sessions == 1
    assert snapshot.catalog.counts.interrupted_retained_sessions == 1
    assert snapshot.recovery_state == "attention_required"
    assert snapshot.recovery_actions == ("resume_interrupted_read_only",)
    assert snapshot.contains_content is False
    for prohibited in (
        "Synthetic private project canary",
        "Synthetic private retained chat",
        "private-workspace-canary",
        "private-model-canary",
        "SYNTHETIC_PRIVATE_PROMPT_CANARY",
        project.project_id,
        retained.session_id,
        T0.isoformat(),
    ):
        assert prohibited not in payload


def test_projection_mismatch_is_degraded_without_returning_database_detail(
    tmp_path: Path,
) -> None:
    database, catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Synthetic project"))
    session = catalog.register_live_session(
        session_id="d" * 32,
        project_id=project.project_id,
        title="Synthetic retained chat",
        workspace=tmp_path / "workspace",
        model_alias=None,
        created_at=T0,
        retention_policy=AgentRetentionPolicy.LOCAL_HISTORY,
        profile_json="{}",
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE agent_catalog_sessions SET history_revision=1 WHERE session_id=?",
            (session.session_id,),
        )

    snapshot = AgentHardeningService(
        SqliteAgentHardeningProbe(database),
        _LiveSource(),
    ).snapshot()

    assert snapshot.catalog.state == "degraded"
    assert snapshot.catalog.reason_code == "catalog_projection_mismatch"
    assert snapshot.catalog.projection_violations == 1
    assert snapshot.recovery_actions == ("inspect_local_catalog",)
    assert "UPDATE" not in snapshot.model_dump_json()


def test_unavailable_sources_fail_closed_and_keep_diagnostic_private() -> None:
    snapshot = AgentHardeningService(
        _UnavailableProbe(),
        _UnavailableLiveSource(),
    ).snapshot()

    assert snapshot.catalog.state == "unavailable"
    assert snapshot.catalog.reason_code == "catalog_storage_unavailable"
    assert snapshot.catalog.counts is None
    assert snapshot.live.state == "unavailable"
    assert snapshot.live.counts is None
    assert snapshot.recovery_state == "unknown"
    assert snapshot.recovery_actions == ("verify_live_state",)
    assert "synthetic live-state failure" not in snapshot.model_dump_json()


@pytest.mark.parametrize(
    "code",
    (
        "agent_catalog_migration_history_incomplete",
        "agent_catalog_migration_checksum_mismatch",
        "agent_catalog_schema_version_mismatch",
    ),
)
def test_migration_corruption_has_one_fixed_content_free_diagnostic(code: str) -> None:
    snapshot = AgentHardeningService(
        _UnavailableProbe(code),
        _LiveSource(),
    ).snapshot()

    assert snapshot.catalog.state == "unavailable"
    assert snapshot.catalog.reason_code == "catalog_migration_invalid"
    assert snapshot.catalog.schema_version is None
    assert code not in snapshot.model_dump_json()


def test_live_hardening_facts_do_not_probe_or_start_a_model(tmp_path: Path) -> None:
    probes = 0

    def active_model() -> str | None:
        nonlocal probes
        probes += 1
        return None

    service = LocalAgentService(
        chat=lambda _alias, _body: (503, b"{}", "application/json"),
        active_model=active_model,
        allowed_roots=(tmp_path,),
    )

    facts = service.hardening_facts()

    assert facts.sessions == 0
    assert facts.running_turns == 0
    assert facts.command_cleanup_quarantined is False
    assert probes == 0


def test_session_delete_cascade_is_visible_in_exact_aggregate_counts(
    tmp_path: Path,
) -> None:
    database, catalog = _catalog(tmp_path)
    project = catalog.create_project(CreateAgentProject(name="Cascade project"))
    session = catalog.register_live_session(
        session_id="e" * 32,
        project_id=project.project_id,
        title="Cascade chat",
        workspace=tmp_path / "cascade-workspace",
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
            text="Synthetic cascade request.",
            turn_id="f" * 32,
        ),
    )
    payload = b"synthetic attachment bytes"
    digest = hashlib.sha256(payload).hexdigest()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO agent_artifacts(
                artifact_id,session_id,title,artifact_kind,relative_path,
                created_at,updated_at,revision,latest_version_number
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "1" * 32,
                session.session_id,
                "Synthetic artifact",
                "text",
                "artifact.txt",
                T0.isoformat(),
                T0.isoformat(),
                1,
                1,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_artifact_versions(
                version_id,artifact_id,version_number,created_at,relative_path,
                media_type,preview_kind,provenance,sha256,byte_size,
                source_turn_id,source_event_seq
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "2" * 32,
                "1" * 32,
                1,
                T0.isoformat(),
                "artifact.txt",
                "text/plain",
                "text",
                "verified_output",
                digest,
                len(payload),
                None,
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO agent_attachments(
                attachment_id,session_id,model_alias,capability_probe_version,
                attachment_kind,media_type,display_name,source_kind,
                attachment_state,retention_policy,created_at,expires_at,
                attached_event_seq,sha256,byte_size,width,height,duration_ms,
                sample_rate_hz,channels,routing,omitted_features_json,payload
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "3" * 32,
                session.session_id,
                "example-model",
                "synthetic-probe.v1",
                "image",
                "image/png",
                "synthetic.png",
                "file",
                "attached",
                "local_history",
                T0.isoformat(),
                None,
                1,
                digest,
                len(payload),
                1,
                1,
                None,
                None,
                None,
                "native_multimodal",
                "[]",
                payload,
            ),
        )
        connection.execute("COMMIT")

    probe = SqliteAgentHardeningProbe(database)
    before = probe.inspect().counts
    assert (before.sessions, before.history_events) == (1, 1)
    assert (before.artifacts, before.artifact_versions) == (1, 1)
    assert before.attached_attachments == 1

    current = catalog.get_session(session.session_id)
    catalog.delete_session(
        session.session_id,
        expected_catalog_revision=current.revision,
        expected_history_revision=current.history_revision,
    )

    after = probe.inspect().counts
    assert after.sessions == 0
    assert after.history_events == 0
    assert after.artifacts == 0
    assert after.artifact_versions == 0
    assert after.attached_attachments == 0


def test_http_diagnostic_is_authenticated_by_composition_and_never_cached(
    tmp_path: Path,
) -> None:
    database, _catalog_service = _catalog(tmp_path)
    service = AgentHardeningService(
        SqliteAgentHardeningProbe(database),
        _LiveSource(),
    )
    application = FastAPI()

    def require_synthetic_token(
        x_synthetic_token: str | None = Header(default=None),
    ) -> None:
        if x_synthetic_token != "synthetic-local-token":
            raise HTTPException(status_code=401, detail="authentication required")

    async def require_synthetic_native_owner(request: Request) -> None:
        if request.headers.get("X-Synthetic-Presence") != "confirmed":
            raise HTTPException(status_code=403, detail="native owner required")
        assert await request.body() == (
            b'{"confirmation":"begin_guarded_agent_native_acceptance"}'
        )

    application.include_router(
        create_agent_hardening_router(
            require_synthetic_token,
            require_synthetic_native_owner,
            service,
        )
    )

    with TestClient(application, base_url="http://127.0.0.1") as client:
        rejected = client.get("/v1/diagnostics/agent-hardening")
        response = client.get(
            "/v1/diagnostics/agent-hardening",
            headers={"X-Synthetic-Token": "synthetic-local-token"},
        )
        presence_rejected = client.post(
            "/v1/diagnostics/agent-native-acceptance/start",
            headers={"X-Synthetic-Token": "synthetic-local-token"},
            json={"confirmation": "begin_guarded_agent_native_acceptance"},
        )
        acceptance = client.post(
            "/v1/diagnostics/agent-native-acceptance/start",
            headers={
                "X-Synthetic-Presence": "confirmed",
                "X-Synthetic-Token": "synthetic-local-token",
            },
            json={"confirmation": "begin_guarded_agent_native_acceptance"},
        )

    assert rejected.status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["contains_content"] is False
    assert presence_rejected.status_code == 403
    assert acceptance.status_code == 200
    assert acceptance.headers["cache-control"] == "no-store, private"
    assert acceptance.headers["pragma"] == "no-cache"
    assert acceptance.json() == {
        "contract_version": "agent-native-acceptance-start.v1",
        "owner_presence_confirmed": True,
        "model_execution_started": False,
        "process_spawn_requested": False,
        "workspace_access_requested": False,
        "content_persisted": False,
        "expires_on_reload": True,
    }


def test_native_acceptance_contract_is_exact_and_content_free() -> None:
    request = BeginAgentNativeAcceptance()
    receipt = AgentNativeAcceptanceStartReceipt()

    assert request.model_dump() == {
        "confirmation": "begin_guarded_agent_native_acceptance"
    }
    payload = receipt.model_dump()
    assert not set(payload).intersection(
        {
        "model_alias",
        "workspace_path",
        "prompt",
        "absolute_path",
        "session_id",
        "project_id",
        "timestamp",
        "pid",
        }
    )
    assert not any(isinstance(value, str) and "D:\\" in value for value in payload.values())

    with pytest.raises(ValueError):
        BeginAgentNativeAcceptance.model_validate(
            {
                "confirmation": "begin_guarded_agent_native_acceptance",
                "extra": True,
            }
        )
