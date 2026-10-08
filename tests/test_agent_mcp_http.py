"""Streamable HTTP conformance and authority tests for the Agent MCP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import json
import subprocess
from threading import Event, Thread

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from prompt_enhancer.application.agent_mcp_connections import (
    AgentMcpConnectionError,
    AgentMcpConnectionService,
    CreateAgentMcpConnection,
)
from prompt_enhancer.application.agent_catalog import AgentCatalogService, CreateAgentProject
from prompt_enhancer.application.agent_surface import EmptyInput, ToolSpec
from prompt_enhancer.api import create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
    SqliteAgentMcpConnectionRepository,
)
from prompt_enhancer.interfaces.http.agent_mcp_routes import (
    AGENT_MCP_SELF_TEST_HEADER,
    AGENT_MCP_SELF_TEST_HEADER_VALUE,
    create_agent_mcp_router,
)
from prompt_enhancer.interfaces.mcp.server import (
    MAX_MESSAGE_BYTES,
    MCP_PROTOCOL_VERSION,
)
from prompt_enhancer.interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
    UserPresenceApprovalManager,
)


T0 = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
MASTER = "m" * 64
MAIN_API_TOKEN = "application-token-that-must-not-authenticate-mcp"
PROJECT_ID = "f" * 32
SESSION_ID = "e" * 32


class _EmptyReadStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self):
        return []

    def list_sessions(self, **_kwargs):
        return []

    def count_sessions(self, **_kwargs):
        return 0

    def get_session_metrics(self, _session_id: str):
        return []


class _SyntheticSurface:
    def __init__(self, *, lifecycle: bool) -> None:
        self.lifecycle = lifecycle

    def tools(self) -> tuple[ToolSpec, ...]:
        tools = (
            ToolSpec(
                name="agent_discover",
                description="Synthetic content-free discovery tool.",
                input_model=EmptyInput,
            ),
        )
        if self.lifecycle:
            tools += (
                ToolSpec(
                    name="agent_runtime",
                    description="Synthetic lifecycle-scoped tool.",
                    input_model=EmptyInput,
                ),
            )
        return tools

    def call(self, name: str, arguments):  # noqa: ANN001
        if name not in {tool.name for tool in self.tools()}:
            raise RuntimeError("synthetic unknown tool")
        return {"tool": name, "arguments": dict(arguments)}


def _harness(tmp_path: Path, *, session_settled=None):  # noqa: ANN001
    now = [T0]
    identities = iter(f"{index:032x}" for index in range(1, 64))
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    catalog = AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: now[0],
        id_factory=lambda: PROJECT_ID,
    )
    catalog.create_project(CreateAgentProject(name="Synthetic HTTP scope"))
    catalog.register_live_session(
        session_id=SESSION_ID,
        project_id=PROJECT_ID,
        title="Synthetic HTTP controller chat",
        workspace=tmp_path / "synthetic-workspace",
        model_alias="synthetic-model",
        created_at=T0,
    )
    service = AgentMcpConnectionService(
        SqliteAgentMcpConnectionRepository(database),
        token_pepper=MASTER,
        clock=lambda: now[0],
        id_factory=identities.__next__,
    )
    surface_requests: list[tuple[str, bool]] = []

    def require_local_auth(request: Request) -> None:
        if request.headers.get("x-synthetic-local-auth") != "accepted":
            raise HTTPException(status_code=401, detail="authentication required")

    async def require_native_confirmation(request: Request) -> None:
        if request.headers.get("x-synthetic-native-confirmation") != "accepted":
            raise HTTPException(status_code=403, detail="native confirmation required")

    def surface_factory(base_url: str, principal) -> _SyntheticSurface:  # noqa: ANN001
        surface_requests.append((base_url, principal.allow_model_lifecycle))
        return _SyntheticSurface(lifecycle=principal.allow_model_lifecycle)

    app = FastAPI()
    app.include_router(
        create_agent_mcp_router(
            require_local_auth,
            require_native_confirmation,
            service,
            surface_factory,
            session_settled,
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return client, service, now, surface_requests


def _credential(
    service: AgentMcpConnectionService,
    *,
    request_id: str = "a" * 32,
    lifecycle: bool = False,
    expires_in_days: int = 90,
):
    return service.create(
        CreateAgentMcpConnection(
            request_id=request_id,
            label="Synthetic MCP client",
            client_kind="other",
            project_id=PROJECT_ID,
            allow_model_lifecycle=lifecycle,
            expires_in_days=expires_in_days,
        ),
        endpoint_url="http://127.0.0.1:8765/mcp/agent",
    )


def _headers(token: str, *, protocol: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if protocol:
        headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
    return headers


def test_token_free_setup_preview_is_exact_authenticated_and_non_authorizing(
    tmp_path: Path,
) -> None:
    client, _service, _now, _surface_requests = _harness(tmp_path)
    path = "/v1/integrations/agent-mcp/setup"

    unauthenticated = client.get(path)
    assert unauthenticated.status_code == 401

    previewed = client.get(
        path,
        headers={"X-Synthetic-Local-Auth": "accepted"},
    )
    assert previewed.status_code == 200
    assert previewed.headers["cache-control"] == "no-store, private"
    preview = previewed.json()
    endpoint = "http://127.0.0.1:8765/mcp/agent"
    assert preview == {
        "contract_version": "agent-mcp-client-setup.v1",
        "endpoint_url": endpoint,
        "bearer_token_env_var": "PROMPT_ENHANCER_AGENT_MCP_TOKEN",
        "codex_toml": "\n".join(
            (
                "[mcp_servers.prompt-enhancer-agent]",
                f'url = "{endpoint}"',
                'bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"',
                "tool_timeout_sec = 330",
                'default_tools_approval_mode = "prompt"',
            )
        ),
        "claude_json": json.dumps(
            {
                "mcpServers": {
                    "prompt-enhancer-agent": {
                        "type": "http",
                        "url": endpoint,
                        "headers": {
                            "Authorization": (
                                "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}"
                            )
                        },
                    }
                }
            },
            indent=2,
        ),
        "codex_add_command": (
            "codex mcp add prompt-enhancer-agent "
            f"--url {endpoint} "
            "--bearer-token-env-var PROMPT_ENHANCER_AGENT_MCP_TOKEN"
        ),
        "claude_add_command": (
            "claude mcp add --transport http --scope local "
            "--header 'Authorization: Bearer "
            "${PROMPT_ENHANCER_AGENT_MCP_TOKEN}' "
            f"prompt-enhancer-agent {endpoint}"
        ),
        "credential_included": False,
        "connection_authority_granted": False,
        "native_connection_required": True,
        "starts_process": False,
        "starts_terminal": False,
        "provider_configuration_changed": False,
    }
    assert "pemcp2." not in previewed.text
    assert MASTER not in previewed.text

    non_loopback = client.get(
        path,
        headers={
            "Host": "example.invalid",
            "X-Synthetic-Local-Auth": "accepted",
        },
    )
    assert non_loopback.status_code == 403
    assert non_loopback.json() == {"detail": "exact loopback authority required"}


def test_native_management_creates_lists_rotates_and_revokes_connection(
    tmp_path: Path,
) -> None:
    client, service, now, _surface_requests = _harness(tmp_path)
    native_headers = {
        "X-Synthetic-Local-Auth": "accepted",
        "X-Synthetic-Native-Confirmation": "accepted",
    }
    create_body = {
        "request_id": "a" * 32,
        "label": "Synthetic Claude connection",
        "client_kind": "claude",
        "project_id": PROJECT_ID,
        "allow_model_lifecycle": False,
        "expires_in_days": 30,
    }

    refused = client.post("/v1/integrations/agent-mcp/connections", json=create_body)
    assert refused.status_code == 401

    created = client.post(
        "/v1/integrations/agent-mcp/connections",
        headers=native_headers,
        json=create_body,
    )
    assert created.status_code == 200
    private = created.json()
    connection = private["connection"]
    assert connection["scope"] == {
        "contract_version": "agent-mcp-scope.v1",
        "state": "bound",
        "project_id": PROJECT_ID,
        "project_name": "Synthetic HTTP scope",
        "catalog_access": "project_only",
        "chat_access": "project_only",
        "workspace_access": "project_only",
        "native_approval_inherited": False,
    }
    assert private["endpoint_url"] == "http://127.0.0.1:8765/mcp/agent"
    assert private["starts_process"] is False
    assert private["starts_terminal"] is False
    assert private["bearer_token"] not in private["codex_toml"]
    assert private["bearer_token"] not in private["claude_json"]
    assert (
        'bearer_token_env_var = "PROMPT_ENHANCER_AGENT_MCP_TOKEN"'
        in private["codex_toml"]
    )
    assert (
        "Bearer ${PROMPT_ENHANCER_AGENT_MCP_TOKEN}"
        in private["claude_json"]
    )
    assert created.headers["cache-control"] == "no-store, private"

    listed = client.get(
        "/v1/integrations/agent-mcp/connections",
        headers={"X-Synthetic-Local-Auth": "accepted"},
    )
    assert listed.status_code == 200
    assert listed.json()["active_count"] == 1
    assert "bearer_token" not in listed.text

    rotated = client.post(
        f"/v1/integrations/agent-mcp/connections/{connection['connection_id']}/rotate",
        headers=native_headers,
        json={
            "request_id": "b" * 32,
            "expected_revision": connection["revision"],
            "expires_in_days": 60,
        },
    )
    assert rotated.status_code == 200
    rotated_private = rotated.json()
    assert rotated_private["bearer_token"] != private["bearer_token"]

    revoked = client.post(
        f"/v1/integrations/agent-mcp/connections/{connection['connection_id']}/revoke",
        headers=native_headers,
        json={"expected_revision": rotated_private["connection"]["revision"]},
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert "bearer_token" not in revoked.text
    now[0] += timedelta(seconds=1)
    assert client.post(
        "/mcp/agent",
        headers=_headers(rotated_private["bearer_token"]),
        json={"jsonrpc": "2.0", "id": 7, "method": "ping"},
    ).status_code == 401
    rejected = service.list().connections[0]
    assert rejected.last_auth_rejected_at == now[0]
    assert rejected.revoked_at is not None
    assert rejected.last_auth_rejected_at > rejected.revoked_at


def test_native_controller_release_requires_confirmation_revision_and_settlement(
    tmp_path: Path,
) -> None:
    settled = [False]
    client, service, _now, _surface_requests = _harness(
        tmp_path,
        session_settled=lambda session_id: (
            session_id == SESSION_ID and settled[0]
        ),
    )
    private = _credential(service)
    claimed = service.ownership.claim(
        connection_id=private.connection.connection_id,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        operation="turn",
    )
    path = "/v1/integrations/agent-mcp/connections/ownerships/release"
    payload = {
        "session_id": SESSION_ID,
        "expected_revision": claimed.revision,
    }

    assert client.post(path, json=payload).status_code == 401
    local_only = client.post(
        path,
        headers={"X-Synthetic-Local-Auth": "accepted"},
        json=payload,
    )
    assert local_only.status_code == 403
    headers = {
        "X-Synthetic-Local-Auth": "accepted",
        "X-Synthetic-Native-Confirmation": "accepted",
    }
    active = client.post(path, headers=headers, json=payload)
    assert active.status_code == 409
    assert active.json() == {
        "detail": "agent_controller_session_not_settled"
    }
    assert service.ownership.get(SESSION_ID) is not None

    settled[0] = True
    released = client.post(path, headers=headers, json=payload)
    assert released.status_code == 200
    assert released.headers["cache-control"] == "no-store, private"
    assert released.json()["released_by"] == "native"
    assert released.json()["session_settled"] is True
    assert released.json()["native_approval_inherited"] is False
    assert service.ownership.get(SESSION_ID) is None

    stale = client.post(path, headers=headers, json=payload)
    assert stale.status_code == 404
    assert stale.json() == {
        "detail": "agent_controller_ownership_not_found"
    }


def test_mcp_authentication_is_scoped_and_failures_are_indistinguishable(
    tmp_path: Path,
) -> None:
    client, service, _now, _surface_requests = _harness(tmp_path)
    private = _credential(service)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    failures = []
    for authorization in (
        None,
        "Bearer wrong",
        f"Bearer {MAIN_API_TOKEN}",
        "Basic ignored",
    ):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if authorization is not None:
            headers["Authorization"] = authorization
        response = client.post("/mcp/agent", headers=headers, json=payload)
        failures.append((response.status_code, response.json(), response.headers.get("www-authenticate")))
    assert len(set((status, str(body), challenge) for status, body, challenge in failures)) == 1
    assert failures[0][0] == 401
    assert failures[0][2] == 'Bearer realm="prompt-enhancer-agent-mcp"'

    accepted = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        json=payload,
    )
    assert accepted.status_code == 200
    assert accepted.json()["result"] == {}


def test_initialize_notification_and_tool_call_follow_streamable_http_contract(
    tmp_path: Path,
) -> None:
    client, service, _now, surface_requests = _harness(tmp_path)
    private = _credential(service)

    initialized = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token, protocol=False),
        json={
            "jsonrpc": "2.0",
            "id": "initialize-1",
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "synthetic-client", "version": "1"},
            },
        },
    )
    assert initialized.status_code == 200
    assert initialized.headers["mcp-protocol-version"] == MCP_PROTOCOL_VERSION
    assert initialized.json()["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert initialized.json()["result"]["serverInfo"]["name"] == "prompt-enhancer-agent"
    instructions = initialized.json()["result"]["instructions"]
    assert len(instructions) <= 512
    for marker in (
        "Start with agent_discover",
        "agent_open",
        "agent_context",
        "agent_turn",
        "agent_wait",
        "agent_workspace",
        "agent_artifacts",
        "agent_propose_transaction",
        "agent_propose_lifecycle",
        "native review",
        "verified receipt",
        "verified output artifact",
        "agent_runtime is opt-in",
        "agent_close retains history",
    ):
        assert marker in instructions

    notification = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notification.status_code == 202
    assert notification.content == b""

    tool_call = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "agent_discover", "arguments": {}},
        },
    )
    assert tool_call.status_code == 200
    result = tool_call.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["tool"] == "agent_discover"
    assert surface_requests[-1] == ("http://127.0.0.1:8765", False)
    activity = service.list().connections[0]
    assert activity.last_tool_at == T0
    assert activity.last_tool_name == "agent_discover"
    assert activity.last_tool_outcome == "succeeded"
    assert activity.last_tool_source == "external_client"
    assert service.list().tool_activity_sequences[0].sequence == 1

    self_test_headers = _headers(private.bearer_token)
    self_test_headers[AGENT_MCP_SELF_TEST_HEADER] = AGENT_MCP_SELF_TEST_HEADER_VALUE
    unknown = client.post(
        "/mcp/agent",
        headers=self_test_headers,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "untrusted/arbitrary-name", "arguments": {}},
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["result"]["isError"] is True
    failed_activity = service.list().connections[0]
    assert failed_activity.last_tool_name == "unknown_tool"
    assert failed_activity.last_tool_outcome == "failed"
    assert failed_activity.last_tool_source == "native_self_test"
    assert service.list().tool_activity_sequences[0].sequence == 2


def test_tool_admission_is_visible_before_the_blocking_http_call_completes(
    tmp_path: Path,
    monkeypatch,
) -> None:  # noqa: ANN001
    entered = Event()
    release = Event()
    original_call = _SyntheticSurface.call

    def blocking_call(self, name: str, arguments):  # noqa: ANN001
        entered.set()
        if not release.wait(timeout=5):
            raise RuntimeError("synthetic release timeout")
        return original_call(self, name, arguments)

    monkeypatch.setattr(_SyntheticSurface, "call", blocking_call)
    client, service, _now, _surface_requests = _harness(tmp_path)
    private = _credential(service)
    responses = []

    def invoke() -> None:
        responses.append(client.post(
            "/mcp/agent",
            headers=_headers(private.bearer_token),
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "agent_discover", "arguments": {}},
            },
        ))

    request_thread = Thread(target=invoke, daemon=True)
    request_thread.start()
    try:
        assert entered.wait(timeout=3)
        admitted = service.list().tool_activity_sequences[0]
        assert admitted.sequence == 1
        assert admitted.tool_name == "agent_discover"
        assert admitted.tool_source == "external_client"
        assert admitted.started_at == T0
        assert admitted.completed_at is None
        assert admitted.outcome is None
        assert service.list().connections[0].last_tool_at is None
    finally:
        release.set()
        request_thread.join(timeout=5)

    assert not request_thread.is_alive()
    assert responses[0].status_code == 200
    completed = service.list().tool_activity_sequences[0]
    assert completed.completed_at == T0
    assert completed.outcome == "succeeded"


def test_lifecycle_tool_is_scoped_per_connection(tmp_path: Path) -> None:
    client, service, _now, _surface_requests = _harness(tmp_path)
    ordinary = _credential(service, request_id="a" * 32)
    lifecycle = _credential(service, request_id="b" * 32, lifecycle=True)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

    ordinary_tools = client.post(
        "/mcp/agent",
        headers=_headers(ordinary.bearer_token),
        json=request,
    ).json()["result"]["tools"]
    lifecycle_tools = client.post(
        "/mcp/agent",
        headers=_headers(lifecycle.bearer_token),
        json=request,
    ).json()["result"]["tools"]

    assert [tool["name"] for tool in ordinary_tools] == ["agent_discover"]
    assert [tool["name"] for tool in lifecycle_tools] == [
        "agent_discover",
        "agent_runtime",
    ]


def test_activity_storage_failure_never_turns_a_settled_tool_into_ambiguity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, service, _now, _surface_requests = _harness(tmp_path)
    private = _credential(service)

    def unavailable(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AgentMcpConnectionError("agent_mcp_connection_storage_unavailable")

    monkeypatch.setattr(service, "record_tool_call", unavailable)
    response = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "agent_discover", "arguments": {}},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False


def test_rotation_revocation_and_expiry_immediately_close_http_access(
    tmp_path: Path,
) -> None:
    client, service, now, _surface_requests = _harness(tmp_path)
    created = _credential(service, expires_in_days=1)
    request = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    rotated_response = client.post(
        f"/v1/integrations/agent-mcp/connections/{created.connection.connection_id}/rotate",
        headers={
            "X-Synthetic-Local-Auth": "accepted",
            "X-Synthetic-Native-Confirmation": "accepted",
        },
        json={
            "request_id": "b" * 32,
            "expected_revision": created.connection.revision,
            "expires_in_days": 1,
        },
    )
    assert rotated_response.status_code == 200
    rotated = rotated_response.json()
    assert client.post(
        "/mcp/agent", headers=_headers(created.bearer_token), json=request
    ).status_code == 401
    rejected_rotation = service.list().connections[0]
    assert rejected_rotation.last_auth_rejected_at == now[0]
    assert client.post(
        "/mcp/agent", headers=_headers(rotated["bearer_token"]), json=request
    ).status_code == 200

    now[0] += timedelta(days=1)
    assert client.post(
        "/mcp/agent", headers=_headers(rotated["bearer_token"]), json=request
    ).status_code == 401
    rejected_expiry = service.list().connections[0]
    assert rejected_expiry.last_auth_rejected_at == now[0]


def test_mcp_rejects_bad_media_version_batch_encoding_and_oversize(
    tmp_path: Path,
) -> None:
    client, service, _now, _surface_requests = _harness(tmp_path)
    private = _credential(service)
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}

    no_stream = _headers(private.bearer_token)
    no_stream["Accept"] = "application/json"
    assert client.post("/mcp/agent", headers=no_stream, json=ping).status_code == 406

    wrong_type = _headers(private.bearer_token)
    wrong_type["Content-Type"] = "text/plain"
    assert client.post("/mcp/agent", headers=wrong_type, content="{}").status_code == 415

    encoded = _headers(private.bearer_token)
    encoded["Content-Encoding"] = "gzip"
    assert client.post("/mcp/agent", headers=encoded, content=b"{}").status_code == 415

    missing_version = _headers(private.bearer_token, protocol=False)
    assert client.post("/mcp/agent", headers=missing_version, json=ping).status_code == 400

    batch = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        json=[ping],
    )
    assert batch.status_code == 400
    assert batch.json()["error"]["code"] == -32600

    malformed = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        content=b"{",
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == -32700

    oversized = client.post(
        "/mcp/agent",
        headers=_headers(private.bearer_token),
        content=b"{" + (b" " * MAX_MESSAGE_BYTES) + b"}",
    )
    assert oversized.status_code == 413


def test_http_transport_supports_only_authenticated_post_and_spawns_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, service, _now, _surface_requests = _harness(tmp_path)
    private = _credential(service)

    def fail_spawn(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("direct MCP transport must not spawn a process")

    monkeypatch.setattr(subprocess, "Popen", fail_spawn)
    valid_headers = {"Authorization": f"Bearer {private.bearer_token}"}
    get_response = client.get("/mcp/agent", headers=valid_headers)
    delete_response = client.delete("/mcp/agent", headers=valid_headers)
    unknown_get = client.get("/mcp/agent")

    assert get_response.status_code == 405
    assert delete_response.status_code == 405
    assert get_response.headers["allow"] == "POST"
    assert unknown_get.status_code == 401


def test_production_app_wiring_uses_browser_csrf_and_one_shot_native_confirmation(
    tmp_path: Path,
) -> None:
    now = [T0]
    database = AgentCatalogSqliteDatabase(
        tmp_path / "catalog" / AGENT_CATALOG_DATABASE_FILENAME
    )
    AgentCatalogService(
        SqliteAgentCatalogRepository(database),
        clock=lambda: now[0],
        id_factory=lambda: PROJECT_ID,
    ).create_project(CreateAgentProject(name="Synthetic production scope"))
    service = AgentMcpConnectionService(
        SqliteAgentMcpConnectionRepository(database),
        token_pepper=MASTER,
        clock=lambda: now[0],
        id_factory=iter(["1" * 32, "2" * 32]).__next__,
    )
    approvals = UserPresenceApprovalManager()

    def confirm(request: Request, body: bytes) -> None:
        if not approvals.consume(
            token=request.headers.get(USER_PRESENCE_HEADER),
            method=request.method,
            path=request.url.path,
            body=body,
        ):
            raise HTTPException(status_code=403, detail="native confirmation failed")

    app = create_app(
        settings=AppSettings(home=tmp_path / "app"),
        database=_EmptyReadStore(),
        api_token=MAIN_API_TOKEN,
        agent_mcp_connection_service=service,
        user_presence_confirmation=confirm,
        user_presence_confirmation_mode="native_bridge_bound_token",
    )
    path = "/v1/integrations/agent-mcp/connections"
    payload = {
        "request_id": "a" * 32,
        "label": "Synthetic production connection",
        "client_kind": "codex",
        "project_id": PROJECT_ID,
        "allow_model_lifecycle": False,
        "expires_in_days": 30,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        browser = client.get("/auth/session")
        csrf = browser.json()["csrf_token"]
        approval = approvals.issue(
            method="POST",
            path=path,
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
        headers = {
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:8765",
            "X-Prompt-Enhancer-CSRF": csrf,
            USER_PRESENCE_HEADER: approval,
        }
        created = client.post(path, headers=headers, content=body)
        assert created.status_code == 200
        private = created.json()
        assert private["endpoint_url"] == "http://127.0.0.1:8765/mcp/agent"

        # The native capability is one-shot even for the identical body.
        repeated = client.post(path, headers=headers, content=body)
        assert repeated.status_code == 403

        ping = client.post(
            "/mcp/agent",
            headers=_headers(private["bearer_token"]),
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert ping.status_code == 200
        assert ping.json()["result"] == {}

        # The broad app API token cannot substitute for the scoped MCP token.
        broad = client.post(
            "/mcp/agent",
            headers=_headers(MAIN_API_TOKEN),
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )
        assert broad.status_code == 401
