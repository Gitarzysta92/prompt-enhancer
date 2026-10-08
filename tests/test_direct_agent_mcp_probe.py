"""Disposable live-listener acceptance for the direct Agent MCP probe."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from prompt_enhancer import desktop_overlay
from prompt_enhancer.application.agent_mcp_connections import (
    AgentMcpConnectionService,
    CreateAgentMcpConnection,
    RevokeAgentMcpConnection,
)
from prompt_enhancer.application.agent_catalog import (
    AgentCatalogService,
    CreateAgentProject,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
    SqliteAgentMcpConnectionRepository,
)


REPOSITORY = Path(__file__).resolve().parents[1]
PROBE = REPOSITORY / "tests" / "support" / "direct_agent_mcp_probe.py"


def _probe_environment(
    root: Path,
    *,
    endpoint: str,
    bearer: str,
) -> dict[str, str]:
    keep = {
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in keep
    }
    environment.update(
        {
            "PROMPT_ENHANCER_HOME": os.fspath(root / "isolated-application"),
            "PROMPT_ENHANCER_SESSION_READER": "disabled",
            "PROMPT_ENHANCER_AGENT_MCP_URL": endpoint,
            "PROMPT_ENHANCER_AGENT_MCP_TOKEN": bearer,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


def _run_probe(
    root: Path,
    *,
    endpoint: str,
    bearer: str,
    mode: str,
) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, PROBE, mode],
        cwd=root,
        env=_probe_environment(root, endpoint=endpoint, bearer=bearer),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert bearer not in completed.stdout
    prefix = "DIRECT_AGENT_MCP_PROBE="
    assert completed.stdout.startswith(prefix)
    payload = json.loads(completed.stdout.removeprefix(prefix))
    assert isinstance(payload, dict)
    return payload


def test_probe_uses_two_clients_then_proves_revocation_on_real_listener(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "direct-agent-mcp-probe"
    (root / "empty-provider").mkdir(parents=True)
    settings = AppSettings(
        home=root / "application",
        host="127.0.0.1",
        port=8766,
        session_reader_enabled=False,
    )
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        os.fspath(root / "empty-provider"),
    )
    owned = desktop_overlay._start_owned_server(settings, allow_ephemeral=True)
    origin = ""
    try:
        application_token = settings.api_token_path.read_text(
            encoding="utf-8"
        ).strip()
        origin = desktop_overlay._wait_for_owned_service(
            owned.endpoints,
            application_token,
            owned,
        )
        database = AgentCatalogSqliteDatabase(settings.agent_catalog_path)
        scope_project = AgentCatalogService(
            SqliteAgentCatalogRepository(database),
            id_factory=lambda: "8" * 32,
        ).create_project(CreateAgentProject(name="Synthetic live probe project"))
        service = AgentMcpConnectionService(
            SqliteAgentMcpConnectionRepository(database),
            token_pepper=application_token,
            id_factory=lambda: "9" * 32,
        )
        private = service.create(
            CreateAgentMcpConnection(
                request_id="8" * 32,
                label="Synthetic live probe",
                client_kind="other",
                project_id=scope_project.project_id,
                allow_model_lifecycle=False,
            ),
            endpoint_url=origin + "/mcp/agent",
        )

        active = _run_probe(
            root,
            endpoint=private.endpoint_url,
            bearer=private.bearer_token,
            mode="--expect-active",
        )
        assert active == {
            "catalog_mutation_requested": False,
            "contract": "direct-agent-mcp-live-probe.v1",
            "default_tool_surface_exact": True,
            "discovery_contract_valid": True,
            "error_code": None,
            "independent_clients": 2,
            "loopback_endpoint_valid": True,
            "mode": "active",
            "model_lifecycle_absent": True,
            "protocol_valid": True,
            "server_identity_valid": True,
            "tool_count": 19,
        }

        revoked_connection = service.revoke(
            private.connection.connection_id,
            RevokeAgentMcpConnection(
                expected_revision=private.connection.revision,
            ),
        )
        assert revoked_connection.state == "revoked"
        revoked = _run_probe(
            root,
            endpoint=private.endpoint_url,
            bearer=private.bearer_token,
            mode="--expect-revoked",
        )
        assert revoked == {
            "contract": "direct-agent-mcp-live-probe.v1",
            "credential_rejected": True,
            "error_code": None,
            "loopback_endpoint_valid": True,
            "mode": "revoked",
            "rejection_status": 401,
        }
    finally:
        owned.stop()

    assert owned.lifecycle.cleanup_finished is True
    assert owned.thread.is_alive() is False
    if origin:
        port = int(origin.rsplit(":", 1)[1])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
