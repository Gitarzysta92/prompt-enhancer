"""Full Agent MCP composition over a disposable authenticated TCP listener."""

from __future__ import annotations

import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import (
    HTTPCookieProcessor,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

import pytest

from prompt_enhancer.config import AppSettings
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
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AgentCatalogSqliteDatabase,
    SqliteAgentCatalogRepository,
    SqliteAgentMcpConnectionRepository,
)
from prompt_enhancer.interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
)
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER


REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY / "src"
DEFAULT_AGENT_MCP_TOOLS = frozenset(
    {
        "agent_artifacts",
        "agent_catalog",
        "agent_control",
        "agent_context",
        "agent_discover",
        "agent_history",
        "agent_open",
        "agent_propose",
        "agent_propose_transaction",
        "agent_propose_lifecycle",
        "agent_resume",
        "agent_fork",
        "agent_export",
        "agent_close",
        "agent_stage_attachment",
        "agent_stop",
        "agent_turn",
        "agent_wait",
        "agent_workspace",
    }
)
pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:websockets.legacy is deprecated:DeprecationWarning"
    ),
    pytest.mark.filterwarnings(
        "ignore:websockets.server.WebSocketServerProtocol is deprecated:DeprecationWarning"
    ),
]


def _child_environment(root: Path) -> dict[str, str]:
    """Minimal environment with private/provider homes redirected to fixtures."""

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
            "PYTHONPATH": os.fspath(SOURCE_ROOT),
            "PROMPT_ENHANCER_HOME": os.fspath(root / "application"),
            "PROMPT_ENHANCER_HOST": "127.0.0.1",
            "PROMPT_ENHANCER_PORT": "8766",
            "PROMPT_ENHANCER_SESSION_READER": "disabled",
            "PROMPT_ENHANCER_CLAUDE_HOME": os.fspath(root / "empty-provider"),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


def _tool_call(identifier: int, name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _run_mcp(
    *,
    origin: str,
    environment: dict[str, str],
    requests: list[dict],
) -> list[dict]:
    payload = "\n".join(
        json.dumps(request, separators=(",", ":")) for request in requests
    ) + "\n"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "prompt_enhancer",
            "agent-mcp",
            "--base-url",
            origin,
            "--acknowledge-sensitive-context-egress",
        ],
        cwd=REPOSITORY,
        env=environment,
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    return [json.loads(line) for line in completed.stdout.splitlines()]


def _http_mcp(
    endpoint: str,
    bearer: str,
    message: dict,
    *,
    opener: OpenerDirector | None = None,
) -> dict:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }
    request = Request(endpoint, data=body, headers=headers, method="POST")
    transport = opener or build_opener(ProxyHandler({}))
    with transport.open(request, timeout=30) as response:
        assert response.status == 200
        return json.loads(response.read())


def test_direct_mcp_transaction_survives_native_review_and_reads_back_both_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Prove the real controller-to-native-review-to-workspace loop without a model."""

    root = tmp_path / "agent-mcp-reviewed-composition"
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "archive").mkdir()
    existing = workspace / "existing.txt"
    existing.write_bytes(b"before\n")
    provider_home = root / "empty-provider"
    provider_home.mkdir()
    settings = AppSettings(
        home=root / "application",
        host="127.0.0.1",
        port=8766,
        session_reader_enabled=False,
    )
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(provider_home))
    owned = desktop_overlay._start_owned_server(settings, allow_ephemeral=True)
    origin = ""
    try:
        app_token = settings.api_token_path.read_text(encoding="utf-8").strip()
        origin = desktop_overlay._wait_for_owned_service(
            owned.endpoints,
            app_token,
            owned,
        )
        database = AgentCatalogSqliteDatabase(settings.agent_catalog_path)
        scope_project = AgentCatalogService(
            SqliteAgentCatalogRepository(database),
            id_factory=lambda: "3" * 32,
        ).create_project(CreateAgentProject(name="Synthetic reviewed project"))
        connection_service = AgentMcpConnectionService(
            SqliteAgentMcpConnectionRepository(database),
            token_pepper=app_token,
            id_factory=lambda: "4" * 32,
        )
        private = connection_service.create(
            CreateAgentMcpConnection(
                request_id="1" * 32,
                label="Synthetic reviewed file client",
                client_kind="other",
                project_id=scope_project.project_id,
            ),
            endpoint_url=origin + "/mcp/agent",
        )

        def fail_spawn(*_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("the reviewed direct MCP flow must not spawn a process")

        monkeypatch.setattr(subprocess, "Popen", fail_spawn)
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        session_request = Request(
            origin + "/auth/session",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with opener.open(session_request, timeout=30) as browser_session:
            assert browser_session.status == 200
            csrf_token = json.loads(browser_session.read())["csrf_token"]
        initialized = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-reviewed-client", "version": "1"},
                },
            },
            opener=opener,
        )
        assert initialized["result"]["serverInfo"]["name"] == "prompt-enhancer-agent"

        egress = {
            "task_authorized": True,
            "redaction_previewed": True,
            "destination": "local_controller",
        }
        opened = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                2,
                "agent_open",
                {
                    "egress": egress,
                    "request": {
                        "project_id": scope_project.project_id,
                        "settings": {
                            "workspace": str(workspace),
                            "title": "Synthetic reviewed chat",
                            "retention_policy": "local_history",
                            "allow_writes": True,
                            "allow_commands": False,
                            "allow_web": False,
                        },
                    },
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert opened["outcome"] == "ready"
        session_id = opened["session"]["session_id"]

        proposal_arguments = {
            "egress": egress,
            "mutation_authorized": True,
            "request": {
                "session_id": session_id,
                "proposal": {
                    "request_id": "2" * 32,
                    "changes": [
                        {
                            "operation": "edit",
                            "path": "existing.txt",
                            "content": "after\n",
                            "expected_revision": hashlib.sha256(b"before\n").hexdigest(),
                            "line_ending": "lf",
                        },
                        {
                            "operation": "create",
                            "path": "created.md",
                            "content": "# Reviewed output\n",
                            "line_ending": "lf",
                        },
                    ],
                },
            },
        }
        pending = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(3, "agent_propose_transaction", proposal_arguments),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert pending["state"] == "pending_native_review"
        assert pending["file_count"] == 2
        assert existing.read_bytes() == b"before\n"
        assert not (workspace / "created.md").exists()

        approval_path = (
            f"/v1/agent/sessions/{session_id}/approvals/{pending['approval_id']}"
        )
        approval_body = b'{"approved":true}'
        native_capability = owned.user_presence.issue(
            method="POST",
            path=approval_path,
            body_sha256=hashlib.sha256(approval_body).hexdigest(),
        )
        approval_request = Request(
            origin + approval_path,
            data=approval_body,
            headers={
                "Content-Type": "application/json",
                "Origin": origin,
                CSRF_HEADER: csrf_token,
                USER_PRESENCE_HEADER: native_capability,
            },
            method="POST",
        )
        with opener.open(approval_request, timeout=30) as approved:
            assert approved.status == 200
            approved.read()

        settled = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                4,
                "agent_wait",
                {
                    "egress": egress,
                    "request": {
                        "session_id": session_id,
                        "after": pending["cursor"],
                    },
                    "deadline_seconds": 3,
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert settled["outcome"] == "settled"
        assert settled["pending_approval_id"] is None

        replayed = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(5, "agent_propose_transaction", proposal_arguments),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert replayed["state"] == "applied"
        assert replayed["transaction_result"]["state"] == "committed"
        assert [item["state"] for item in replayed["transaction_result"]["files"]] == [
            "committed",
            "committed",
        ]

        for identifier, path, content in (
            (6, "existing.txt", "after\n"),
            (7, "created.md", "# Reviewed output\n"),
        ):
            read_back = _http_mcp(
                private.endpoint_url,
                private.bearer_token,
                _tool_call(
                    identifier,
                    "agent_workspace",
                    {
                        "egress": egress,
                        "session_id": session_id,
                        "action": "read",
                        "path": path,
                    },
                ),
                opener=opener,
            )["result"]["structuredContent"]["result"]["response"]
            assert read_back["path"] == path
            assert read_back["content"] == content
            assert read_back["revision"] == hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()

        assert existing.read_bytes() == b"after\n"
        assert (workspace / "created.md").read_bytes() == b"# Reviewed output\n"

        reviewed_artifacts = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                71,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "list",
                        "project_id": opened["project"]["project_id"],
                        "session_id": session_id,
                    },
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]["response"]
        by_path = {
            item["path"]: item for item in reviewed_artifacts["artifacts"]
        }
        assert set(by_path) == {"created.md", "existing.txt"}
        assert all(
            item["latest_version"]["provenance"] == "reviewed_write"
            and item["version_count"] == 1
            for item in by_path.values()
        )
        artifact_detail = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                72,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "get",
                        "project_id": opened["project"]["project_id"],
                        "session_id": session_id,
                        "artifact_id": by_path["created.md"]["artifact_id"],
                    },
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]["response"]
        assert artifact_detail["path"] == "created.md"
        assert artifact_detail["availability"] == "available"
        assert artifact_detail["latest_version"]["sha256"] == hashlib.sha256(
            b"# Reviewed output\n"
        ).hexdigest()
        assert "Reviewed output" not in json.dumps(artifact_detail)

        lifecycle_arguments = {
            "egress": egress,
            "mutation_authorized": True,
            "request": {
                "session_id": session_id,
                "proposal": {
                    "request_id": "3" * 32,
                    "operation": "move_file",
                    "source_path": "created.md",
                    "target_path": "archive/created.md",
                    "expected_revision": hashlib.sha256(
                        b"# Reviewed output\n"
                    ).hexdigest(),
                },
            },
        }
        pending_lifecycle = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(8, "agent_propose_lifecycle", lifecycle_arguments),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert pending_lifecycle["state"] == "pending_native_review"
        assert (workspace / "created.md").exists()
        assert not (workspace / "archive" / "created.md").exists()

        lifecycle_approval_path = (
            f"/v1/agent/sessions/{session_id}/approvals/"
            f"{pending_lifecycle['approval_id']}"
        )
        lifecycle_capability = owned.user_presence.issue(
            method="POST",
            path=lifecycle_approval_path,
            body_sha256=hashlib.sha256(approval_body).hexdigest(),
        )
        lifecycle_approval_request = Request(
            origin + lifecycle_approval_path,
            data=approval_body,
            headers={
                "Content-Type": "application/json",
                "Origin": origin,
                CSRF_HEADER: csrf_token,
                USER_PRESENCE_HEADER: lifecycle_capability,
            },
            method="POST",
        )
        with opener.open(lifecycle_approval_request, timeout=30) as approved:
            assert approved.status == 200
            approved.read()

        lifecycle_wait = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                9,
                "agent_wait",
                {
                    "egress": egress,
                    "request": {
                        "session_id": session_id,
                        "after": pending_lifecycle["cursor"],
                    },
                    "deadline_seconds": 3,
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert lifecycle_wait["outcome"] == "settled"

        lifecycle_replay = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(10, "agent_propose_lifecycle", lifecycle_arguments),
            opener=opener,
        )["result"]["structuredContent"]["result"]
        assert lifecycle_replay["state"] == "applied"
        assert lifecycle_replay["verified"] is True
        assert not (workspace / "created.md").exists()
        assert (workspace / "archive" / "created.md").read_bytes() == (
            b"# Reviewed output\n"
        )

        lifecycle_read_back = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                11,
                "agent_workspace",
                {
                    "egress": egress,
                    "session_id": session_id,
                    "action": "read",
                    "path": "archive/created.md",
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]["response"]
        assert lifecycle_read_back["content"] == "# Reviewed output\n"

        moved_artifacts = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                73,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "list",
                        "project_id": opened["project"]["project_id"],
                        "session_id": session_id,
                    },
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]["response"]
        moved_by_path = {
            item["path"]: item for item in moved_artifacts["artifacts"]
        }
        assert set(moved_by_path) == {"archive/created.md", "existing.txt"}
        moved_card = moved_by_path["archive/created.md"]
        assert moved_card["artifact_id"] == artifact_detail["artifact_id"]
        assert moved_card["version_count"] == 2
        assert moved_card["latest_version"]["provenance"] == "reviewed_move"
        assert moved_card["latest_version"]["sha256"] == hashlib.sha256(
            b"# Reviewed output\n"
        ).hexdigest()

        moved_detail = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                74,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "get",
                        "project_id": opened["project"]["project_id"],
                        "session_id": session_id,
                        "artifact_id": moved_card["artifact_id"],
                    },
                },
            ),
            opener=opener,
        )["result"]["structuredContent"]["result"]["response"]
        assert moved_detail["availability"] == "available"
        assert [version["path"] for version in moved_detail["versions"]] == [
            "created.md",
            "archive/created.md",
        ]
        assert "Reviewed output" not in json.dumps(moved_detail)
    finally:
        owned.stop()

    assert owned.lifecycle.cleanup_finished is True
    assert owned.thread.is_alive() is False
    if origin:
        port = int(origin.rsplit(":", 1)[1])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_installed_shape_stdio_bridge_reaches_real_loopback_and_persists_catalog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "agent-mcp-composition"
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    (root / "empty-provider").mkdir()
    settings = AppSettings(
        home=root / "application",
        host="127.0.0.1",
        port=8766,
        session_reader_enabled=False,
    )
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        str(root / "empty-provider"),
    )
    owned = desktop_overlay._start_owned_server(
        settings,
        allow_ephemeral=True,
    )
    origin = ""
    try:
        token = settings.api_token_path.read_text(encoding="utf-8").strip()
        origin = desktop_overlay._wait_for_owned_service(
            owned.endpoints,
            token,
            owned,
        )
        egress = {
            "task_authorized": True,
            "redaction_previewed": True,
            "destination": "local_controller",
        }
        replies = _run_mcp(
            origin=origin,
            environment=_child_environment(root),
            requests=[
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "synthetic-mcp-client",
                            "version": "1",
                        },
                    },
                },
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                _tool_call(3, "agent_discover", {}),
                _tool_call(
                    4,
                    "agent_catalog",
                    {
                        "egress": egress,
                        "request": {"action": "list_projects"},
                    },
                ),
                _tool_call(
                    5,
                    "agent_invoke",
                    {
                        "egress": egress,
                        "request": {"operation": "get_local_runtime"},
                    },
                ),
                _tool_call(
                    6,
                    "agent_open",
                    {
                        "egress": egress,
                        "request": {
                            "project_name": "Synthetic MCP integration project",
                            "settings": {
                                "workspace": str(workspace),
                                "title": "Synthetic MCP integration chat",
                                "retention_policy": "local_history",
                                "allow_writes": False,
                                "allow_commands": False,
                                "allow_web": False,
                            },
                        },
                    },
                ),
                _tool_call(
                    7,
                    "agent_catalog",
                    {
                        "egress": egress,
                        "request": {"action": "list_projects"},
                    },
                ),
            ],
        )

        assert [reply["id"] for reply in replies] == [1, 2, 3, 4, 5, 6, 7]
        assert replies[0]["result"]["serverInfo"]["name"] == (
            "prompt-enhancer-agent"
        )
        assert [tool["name"] for tool in replies[1]["result"]["tools"]] == [
            "agent_discover",
            "agent_invoke",
            "agent_open",
            "agent_resume",
            "agent_fork",
            "agent_export",
            "agent_close",
            "agent_catalog",
            "agent_history",
            "agent_artifacts",
            "agent_stage_attachment",
            "agent_context",
            "agent_workspace",
            "agent_propose",
            "agent_propose_transaction",
            "agent_propose_lifecycle",
            "agent_turn",
            "agent_stop",
            "agent_wait",
        ]
        assert replies[2]["result"]["structuredContent"]["result"][
            "contract_version"
        ] == "local-agent-orchestration.v22"
        assert replies[3]["result"]["structuredContent"]["result"][
            "response"
        ]["projects"] == []
        runtime = replies[4]["result"]["structuredContent"]["result"][
            "response"
        ]
        assert runtime["state"] == "idle"
        assert runtime["served"] is None
        opened = replies[5]["result"]["structuredContent"]["result"]
        assert opened["outcome"] == "ready"
        assert opened["project_created"] is True
        assert opened["session"] is not None
        session_id = opened["session"]["session_id"]
        projects = replies[6]["result"]["structuredContent"]["result"][
            "response"
        ]["projects"]
        assert len(projects) == 1
        project_id = projects[0]["project_id"]
        project_revision = projects[0]["revision"]

        persisted = _run_mcp(
            origin=origin,
            environment=_child_environment(root),
            requests=[
                _tool_call(
                    8,
                    "agent_catalog",
                    {
                        "egress": egress,
                        "request": {
                            "action": "get_project",
                            "project_id": project_id,
                        },
                    },
                ),
                _tool_call(
                    9,
                    "agent_catalog",
                    {
                        "egress": egress,
                        "request": {
                            "action": "list_chats",
                            "project_id": project_id,
                        },
                    },
                ),
                _tool_call(
                    10,
                    "agent_catalog",
                    {
                        "egress": egress,
                        "request": {
                            "action": "update_project",
                            "mutation_authorized": True,
                            "project_id": project_id,
                            "expected_revision": project_revision,
                            "pinned": True,
                        },
                    },
                ),
                _tool_call(
                    11,
                    "agent_history",
                    {
                        "egress": egress,
                        "project_id": project_id,
                        "session_id": session_id,
                        "after": 0,
                        "limit": 50,
                    },
                ),
                _tool_call(
                    12,
                    "agent_artifacts",
                    {
                        "egress": egress,
                        "request": {
                            "action": "list",
                            "project_id": project_id,
                            "session_id": session_id,
                        },
                    },
                ),
                _tool_call(
                    13,
                    "agent_context",
                    {
                        "egress": egress,
                        "request": {
                            "action": "chat",
                            "project_id": project_id,
                            "session_id": session_id,
                        },
                    },
                ),
                _tool_call(
                    14,
                    "agent_workspace",
                    {
                        "egress": egress,
                        "session_id": session_id,
                        "action": "inspect",
                    },
                ),
            ],
        )
        persisted_project = persisted[0]["result"]["structuredContent"]["result"][
            "response"
        ]
        assert persisted_project["project_id"] == project_id
        persisted_chats = persisted[1]["result"]["structuredContent"]["result"][
            "response"
        ]["sessions"]
        assert [chat["session_id"] for chat in persisted_chats] == [session_id]
        updated_project = persisted[2]["result"]["structuredContent"]["result"][
            "response"
        ]
        assert updated_project["pinned"] is True
        assert updated_project["revision"] == project_revision + 1
        retained = persisted[3]["result"]["structuredContent"]["result"][
            "response"
        ]
        assert retained["session_id"] == session_id
        assert retained["running"] is False
        assert all(event.get("arguments") is None for event in retained["events"])
        assert all(event.get("approval_id") is None for event in retained["events"])
        assert all(event.get("preview") is None for event in retained["events"])
        artifact_list = persisted[4]["result"]["structuredContent"]["result"][
            "response"
        ]
        assert artifact_list["project_id"] == project_id
        assert artifact_list["session_id"] == session_id
        assert artifact_list["artifacts"] == []
        context_result = persisted[5]["result"]["structuredContent"]["result"]
        assert context_result["action"] == "chat"
        assert context_result["view"]["runtime"]["state"] == "idle"
        assert context_result["view"]["runtime"]["served"] is None
        assert context_result["view"]["runtime"]["context"]["state"] == "unknown"
        assert context_result["view"]["runtime"]["context_binding"] == (
            "runtime_global_last_request"
        )
        assert "selected_chat_context_proven" not in context_result["view"]["runtime"]
        assert context_result["view"]["models"]["installed_count"] == 0
        assert context_result["view"]["attachments"]["image_input"] is False
        assert context_result["view"]["attachments"]["audio_input"] is False
        assert context_result["view"]["attachments"]["document_input"] is False
        assert context_result["view"]["chat"]["project_id"] == project_id
        assert context_result["view"]["chat"]["session_id"] == session_id
        assert context_result["view"]["chat"]["selected_model_ready"] is False
        assert context_result["view"]["chat"]["selected_chat_context_proven"] is False
        assert context_result["view"]["chat"]["context"]["binding_state"] == "unmeasured"
        assert context_result["view"]["chat"]["context"]["unknown_reason"] == "no_request_measured"
        assert context_result["view"]["chat"]["staged_attachments"] == []
        serialized_context = json.dumps(context_result)
        assert str(workspace) not in serialized_context
        assert '"pid"' not in serialized_context
        assert '"instructions"' not in serialized_context
        assert '"sha256"' not in serialized_context
        workspace_result = persisted[6]["result"]["structuredContent"]["result"]
        assert workspace_result["action"] == "inspect"
        assert workspace_result["operation"] == "inspect_workspace"
        assert workspace_result["response"]["session_id"] == session_id
        assert workspace_result["response"]["inventory_coverage"] == "complete"
    finally:
        owned.stop()

    assert owned.lifecycle.cleanup_finished is True
    assert owned.thread.is_alive() is False
    if origin:
        port = int(origin.rsplit(":", 1)[1])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_direct_http_mcp_reenters_the_same_real_listener_without_a_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "agent-http-mcp-composition"
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    (root / "empty-provider").mkdir()
    settings = AppSettings(
        home=root / "application",
        host="127.0.0.1",
        port=8766,
        session_reader_enabled=False,
    )
    monkeypatch.setenv(
        "PROMPT_ENHANCER_CLAUDE_HOME",
        str(root / "empty-provider"),
    )
    owned = desktop_overlay._start_owned_server(
        settings,
        allow_ephemeral=True,
    )
    origin = ""
    try:
        app_token = settings.api_token_path.read_text(encoding="utf-8").strip()
        origin = desktop_overlay._wait_for_owned_service(
            owned.endpoints,
            app_token,
            owned,
        )
        database = AgentCatalogSqliteDatabase(settings.agent_catalog_path)
        scope_project = AgentCatalogService(
            SqliteAgentCatalogRepository(database),
            id_factory=lambda: "b" * 32,
        ).create_project(CreateAgentProject(name="Synthetic direct HTTP project"))
        connection_service = AgentMcpConnectionService(
            SqliteAgentMcpConnectionRepository(database),
            token_pepper=app_token,
            id_factory=lambda: "c" * 32,
        )
        private = connection_service.create(
            CreateAgentMcpConnection(
                request_id="d" * 32,
                label="Synthetic direct HTTP client",
                client_kind="other",
                project_id=scope_project.project_id,
            ),
            endpoint_url=origin + "/mcp/agent",
        )

        def fail_spawn(*_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("direct HTTP MCP must not spawn a subprocess")

        monkeypatch.setattr(subprocess, "Popen", fail_spawn)
        first_client = build_opener(ProxyHandler({}))
        second_client = build_opener(ProxyHandler({}))
        initialized = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "synthetic-direct-http-client",
                        "version": "1",
                    },
                },
            },
            opener=first_client,
        )
        assert initialized["result"]["serverInfo"]["name"] == (
            "prompt-enhancer-agent"
        )
        second_initialized = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "synthetic-direct-http-client-two",
                        "version": "1",
                    },
                },
            },
            opener=second_client,
        )
        assert second_initialized["result"]["serverInfo"]["name"] == (
            "prompt-enhancer-agent"
        )
        first_tools = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            {"jsonrpc": "2.0", "id": 102, "method": "tools/list"},
            opener=first_client,
        )["result"]["tools"]
        second_tools = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            {"jsonrpc": "2.0", "id": 103, "method": "tools/list"},
            opener=second_client,
        )["result"]["tools"]
        assert frozenset(tool["name"] for tool in first_tools) == (
            DEFAULT_AGENT_MCP_TOOLS
        )
        assert frozenset(tool["name"] for tool in second_tools) == (
            DEFAULT_AGENT_MCP_TOOLS
        )
        assert "agent_runtime" not in DEFAULT_AGENT_MCP_TOOLS

        egress = {
            "task_authorized": True,
            "redaction_previewed": True,
            "destination": "local_controller",
        }
        discovered = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(2, "agent_discover", {}),
        )
        assert discovered["result"]["structuredContent"]["result"][
            "contract_version"
        ] == "local-agent-orchestration.v22"

        opened = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                3,
                "agent_open",
                {
                    "egress": egress,
                    "request": {
                        "project_id": scope_project.project_id,
                        "settings": {
                            "workspace": str(workspace),
                            "title": "Synthetic direct HTTP chat",
                            "retention_policy": "local_history",
                            "allow_writes": True,
                            "allow_commands": False,
                            "allow_web": False,
                        },
                    },
                },
            ),
            opener=first_client,
        )
        opened_result = opened["result"]["structuredContent"]["result"]
        assert opened_result["outcome"] == "ready"
        assert opened_result["project_created"] is False
        session_id = opened_result["session"]["session_id"]

        workspace_view = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                4,
                "agent_workspace",
                {
                    "egress": egress,
                    "session_id": session_id,
                    "action": "list",
                },
            ),
        )["result"]["structuredContent"]["result"]
        assert workspace_view["action"] == "list"
        assert workspace_view["response"]["session_id"] == session_id
        assert workspace_view["response"]["path"] == "."
        assert workspace_view["response"]["entries"] == []

        workspace_search = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                104,
                "agent_workspace",
                {
                    "egress": egress,
                    "session_id": session_id,
                    "action": "search",
                    "query": "synthetic",
                    "glob": "**/*.txt",
                    "regex": False,
                },
            ),
            opener=first_client,
        )["result"]["structuredContent"]["result"]
        assert workspace_search["action"] == "search"
        assert workspace_search["operation"] == "search_workspace_text"
        assert workspace_search["response"] == {
            "contract_version": "local-agent-workspace-search.v1",
            "session_id": session_id,
            "scope": "application_readable_utf8_text",
            "coverage": "complete",
            "reasons": [],
            "reason_code": None,
            "scanned_entry_count": 0,
            "inspected_byte_count": 0,
            "skipped_entry_count": 0,
            "match_count": 0,
            "matches": [],
        }

        projects = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                5,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {"action": "list_projects"},
                },
            ),
        )["result"]["structuredContent"]["result"]["response"]["projects"]
        assert len(projects) == 1

        chat = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                6,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "get_chat",
                        "session_id": session_id,
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]["response"]
        assert chat["session_id"] == session_id

        updated_chat = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                7,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "update_chat",
                        "mutation_authorized": True,
                        "session_id": session_id,
                        "expected_revision": chat["revision"],
                        "title": "Synthetic renamed HTTP chat",
                        "pinned": True,
                    },
                },
            ),
        )["result"]["structuredContent"]["result"]["response"]
        assert updated_chat["title"] == "Synthetic renamed HTTP chat"
        assert updated_chat["pinned"] is True
        assert updated_chat["revision"] == chat["revision"] + 1

        reread_chat = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                8,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "get_chat",
                        "session_id": session_id,
                    },
                },
            ),
        )["result"]["structuredContent"]["result"]["response"]
        assert reread_chat["title"] == "Synthetic renamed HTTP chat"
        assert reread_chat["pinned"] is True

        retained = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                9,
                "agent_history",
                {
                    "egress": egress,
                    "project_id": projects[0]["project_id"],
                    "session_id": session_id,
                    "after": 0,
                    "limit": 50,
                },
            ),
        )["result"]["structuredContent"]["result"]["response"]
        assert retained["session_id"] == session_id
        assert retained["running"] is False
        assert retained["pending_approval_id"] is None

        artifacts = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                10,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "list",
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                    },
                },
            ),
        )["result"]["structuredContent"]["result"]["response"]
        assert artifacts["project_id"] == projects[0]["project_id"]
        assert artifacts["session_id"] == session_id
        assert artifacts["artifacts"] == []

        synthetic_output = workspace / "reports" / "synthetic-output.md"
        synthetic_output.parent.mkdir()
        synthetic_payload = (
            b"# Synthetic output\n\nReserved example content only.\n"
        )
        synthetic_output.write_bytes(synthetic_payload)
        capture_preview = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                110,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "preview_capture",
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                        "path": "reports/synthetic-output.md",
                        "title": "Synthetic generated output",
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert capture_preview["action"] == "preview_capture"
        assert capture_preview["operation"] == "preview_artifact_capture"
        assert capture_preview["status_code"] == 200
        assert capture_preview["response"] == {
            "contract_version": "agent-artifact-capture-preview.v1",
            "project_id": projects[0]["project_id"],
            "session_id": session_id,
            "path": "reports/synthetic-output.md",
            "title": "Synthetic generated output",
            "kind": "markdown",
            "media_type": "text/markdown; charset=utf-8",
            "preview_kind": "text",
            "sha256": hashlib.sha256(synthetic_payload).hexdigest(),
            "byte_size": len(synthetic_payload),
            "requires_native_confirmation": True,
            "file_content_included": False,
        }
        serialized_preview = json.dumps(capture_preview, sort_keys=True)
        assert "Reserved example content only" not in serialized_preview
        assert "data_base64" not in serialized_preview
        assert "payload" not in serialized_preview
        assert synthetic_output.read_bytes() == synthetic_payload

        artifacts_after_preview = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                109,
                "agent_artifacts",
                {
                    "egress": egress,
                    "request": {
                        "action": "list",
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                    },
                },
            ),
            opener=first_client,
        )["result"]["structuredContent"]["result"]["response"]
        assert artifacts_after_preview["artifacts"] == []

        context = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                11,
                "agent_context",
                {
                    "egress": egress,
                    "request": {
                        "action": "chat",
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                    },
                },
            ),
        )["result"]["structuredContent"]["result"]
        assert context["view"]["chat"]["session_id"] == session_id
        assert context["view"]["chat"]["selected_model_ready"] is False
        assert context["view"]["runtime"]["state"] == "idle"
        assert "selected_chat_context_proven" not in context["view"]["runtime"]
        assert context["view"]["chat"]["selected_chat_context_proven"] is False
        assert context["view"]["chat"]["context"]["unknown_reason"] == "no_request_measured"
        assert context["view"]["models"]["installed_count"] == 0
        assert context["view"]["attachments"]["microphone_recording"] is False
        assert context["view"]["attachments"]["document_input"] is False
        assert str(workspace) not in json.dumps(context)

        proposal_arguments = {
            "egress": egress,
            "mutation_authorized": True,
            "request": {
                "session_id": session_id,
                "proposal": {
                    "request_id": "6" * 32,
                    "operation": "create",
                    "path": "native-review-only.txt",
                    "content": "SYNTHETIC_DIRECT_MCP_PROPOSAL\n",
                },
            },
        }
        proposed = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(111, "agent_propose", proposal_arguments),
            opener=first_client,
        )["result"]["structuredContent"]["result"]
        assert proposed["state"] == "pending_native_review"
        assert proposed["approval_id"] is not None
        assert not (workspace / "native-review-only.txt").exists()

        waiting = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                112,
                "agent_wait",
                {
                    "egress": egress,
                    "request": {
                        "session_id": session_id,
                        "after": proposed["cursor"],
                    },
                    "deadline_seconds": 1,
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert waiting["outcome"] == "needs_native_approval"
        assert waiting["pending_approval_id"] == proposed["approval_id"]

        cancelled = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                113,
                "agent_stop",
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {
                        "session_id": session_id,
                        "after": waiting["cursor"],
                    },
                    "drain_timeout_seconds": 2,
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert cancelled["outcome"] == "stopped"
        assert cancelled["pending_approval_id"] is None
        assert cancelled["cursor"] == cancelled["last_seq"]
        assert not (workspace / "native-review-only.txt").exists()

        replayed_proposal = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(114, "agent_propose", proposal_arguments),
            opener=first_client,
        )["result"]["structuredContent"]["result"]
        assert replayed_proposal["state"] == "cancelled"
        assert replayed_proposal["approval_id"] is None
        assert not (workspace / "native-review-only.txt").exists()

        reread_chat = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                115,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "get_chat",
                        "session_id": session_id,
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]["response"]

        resumed_live = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                12,
                "agent_resume",
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                        "expected_catalog_revision": reread_chat["revision"],
                        "expected_history_revision": reread_chat["history_revision"],
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert resumed_live["outcome"] == "already_live"
        assert resumed_live["mutation_state"] == "not_attempted"
        assert resumed_live["session"]["session_id"] == session_id

        closed_live = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                13,
                "agent_close",
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                        "expected_catalog_revision": reread_chat["revision"],
                        "expected_history_revision": reread_chat["history_revision"],
                    },
                },
            ),
            opener=first_client,
        )["result"]["structuredContent"]["result"]
        assert closed_live["outcome"] == "closed"
        assert closed_live["mutation_state"] == "accepted"
        assert closed_live["live_session_present"] is False
        assert closed_live["catalog_session_retained"] is True
        assert closed_live["permanent_delete_requested"] is False
        assert closed_live["retained_history_delete_requested"] is False
        assert str(workspace) not in json.dumps(closed_live)

        closed_chat = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                14,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "get_chat",
                        "session_id": session_id,
                    },
                },
            ),
            opener=first_client,
        )["result"]["structuredContent"]["result"]["response"]

        resumed_retained = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                15,
                "agent_resume",
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                        "expected_catalog_revision": closed_chat["revision"],
                        "expected_history_revision": closed_chat["history_revision"],
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert resumed_retained["outcome"] == "resumed"
        assert resumed_retained["mutation_state"] == "accepted"
        assert resumed_retained["session"]["recovered"] is True
        assert resumed_retained["session"]["authority_revalidated"] is False
        assert resumed_retained["session"]["settings"]["allow_writes"] is False
        assert resumed_retained["session"]["settings"]["allow_commands"] is False
        assert resumed_retained["session"]["settings"]["allow_web"] is False

        fork_source = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                16,
                "agent_catalog",
                {
                    "egress": egress,
                    "request": {
                        "action": "get_chat",
                        "session_id": session_id,
                    },
                },
            ),
            opener=first_client,
        )["result"]["structuredContent"]["result"]["response"]
        fork_arguments = {
            "egress": egress,
            "mutation_authorized": True,
            "request": {
                "project_id": projects[0]["project_id"],
                "session_id": session_id,
                "request_id": "8" * 32,
                "expected_catalog_revision": fork_source["revision"],
                "expected_history_revision": fork_source["history_revision"],
                "title": "Synthetic direct HTTP branch",
            },
        }
        exported_history = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                17,
                "agent_export",
                {
                    "egress": egress,
                    "request": {
                        "project_id": projects[0]["project_id"],
                        "session_id": session_id,
                        "expected_catalog_revision": fork_source["revision"],
                        "expected_history_revision": fork_source["history_revision"],
                        "max_events": 100,
                    },
                },
            ),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert exported_history["complete"] is True
        assert exported_history["event_count"] == fork_source["history_revision"]
        assert exported_history["workspace_path_included"] is False
        assert exported_history["attachment_bytes_included"] is False
        assert exported_history["live_approval_state_included"] is False
        assert exported_history["raw_tool_payloads_included"] is False
        assert exported_history["mutation_authority_included"] is False
        assert str(workspace) not in json.dumps(exported_history)

        forked = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(18, "agent_fork", fork_arguments),
            opener=first_client,
        )["result"]["structuredContent"]["result"]
        assert forked["outcome"] == "forked"
        assert forked["attempts"] == 1
        assert forked["receipt"]["approvals_copied"] is False
        assert forked["receipt"]["mutation_authority_copied"] is False
        assert forked["receipt"]["pending_tool_state_copied"] is False
        assert forked["receipt"]["staged_attachments_copied"] is False
        assert forked["receipt"]["artifacts_copied"] is False
        branch_session_id = forked["receipt"]["session"]["session_id"]
        assert branch_session_id != session_id

        replayed_fork = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(19, "agent_fork", fork_arguments),
            opener=second_client,
        )["result"]["structuredContent"]["result"]
        assert replayed_fork["outcome"] == "idempotent_replay"
        assert replayed_fork["receipt"]["session"]["session_id"] == branch_session_id

        stopped_without_owner = _http_mcp(
            private.endpoint_url,
            private.bearer_token,
            _tool_call(
                20,
                "agent_stop",
                {
                    "egress": egress,
                    "mutation_authorized": True,
                    "request": {"session_id": session_id, "after": 0},
                    "drain_timeout_seconds": 1,
                },
            ),
            opener=second_client,
        )["result"]
        assert stopped_without_owner["isError"] is True
        assert stopped_without_owner["structuredContent"] == {
            "error": "agent_controller_ownership_required"
        }

        revoked = connection_service.revoke(
            private.connection.connection_id,
            RevokeAgentMcpConnection(
                expected_revision=private.connection.revision,
            ),
        )
        assert revoked.state == "revoked"
        with pytest.raises(HTTPError) as rejected:
            _http_mcp(
                private.endpoint_url,
                private.bearer_token,
                {"jsonrpc": "2.0", "id": 104, "method": "ping"},
                opener=second_client,
            )
        assert rejected.value.code == 401
    finally:
        owned.stop()

    assert owned.lifecycle.cleanup_finished is True
    assert owned.thread.is_alive() is False
    if origin:
        port = int(origin.rsplit(":", 1)[1])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
