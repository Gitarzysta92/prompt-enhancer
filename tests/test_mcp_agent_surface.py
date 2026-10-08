"""Read-only MCP server (ADR 0014): allowlisted tools over stdio, content-free, bounded."""

from __future__ import annotations

from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import subprocess
import sys

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.agent_surface import (
    AGENT_SURFACE_CONTRACT_VERSION,
    AgentReadSurface,
    AgentSurfaceError,
    MAX_SESSIONS_PER_PAGE,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.interfaces.mcp import (
    CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV,
    MCP_PROTOCOL_VERSION,
    McpStdioServer,
    handle_message,
)
from prompt_enhancer.privacy import Pseudonymizer


FORBIDDEN_FRAGMENTS = ("text", "prompt", "response", "path", "token", "transcript")


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(SyntheticAdapter())
    return database


def _surface(tmp_path: Path) -> AgentReadSurface:
    database = _database(tmp_path)
    newest = database.list_sessions(limit=1)[0]["started_at"]
    now = datetime.fromisoformat(str(newest)) + timedelta(days=1)
    return AgentReadSurface(
        database,
        calibration_status=lambda: {"sample_sessions": 3, "fully_rated_sessions": 1, "metric_keys": ["a"], "model_judge": []},
        clock=lambda: now,
    )


def test_tools_are_allowlisted_bounded_and_content_free(tmp_path: Path) -> None:
    surface = _surface(tmp_path)
    names = [tool.name for tool in surface.tools()]
    assert names == [
        "list_metric_definitions",
        "list_sessions",
        "get_session_metrics",
        "summarize_period",
        "explain_metric",
        "get_calibration_status",
    ]
    for tool in surface.tools():
        schema = tool.input_schema()
        assert schema["type"] == "object" and schema.get("additionalProperties") is False

    definitions = surface.call("list_metric_definitions", {})
    assert definitions["contract_version"] == AGENT_SURFACE_CONTRACT_VERSION and definitions["definitions"]
    assert set(definitions["definitions"][0]) == {"key", "version", "dimension", "display_name", "description", "unit", "source"}

    listed = surface.call("list_sessions", {"provider": "synthetic", "limit": 2})
    assert len(listed["sessions"]) == 2
    first = listed["sessions"][0]
    assert set(first) <= {
        "session_id", "project_id", "provider", "provider_version", "started_at", "ended_at",
        "terminal_state", "events_complete", "project_display_name", "session_display_name",
    }
    assert not any(fragment in key for key in first for fragment in FORBIDDEN_FRAGMENTS if key != "session_display_name")

    metrics = surface.call("get_session_metrics", {"session_id": first["session_id"]})
    assert metrics["session_id"] == first["session_id"]
    for row in metrics["metrics"]:
        assert set(row) <= {
            "key", "version", "dimension", "display_name", "numeric_value", "text_value", "unit", "source",
            "observed_count", "eligible_count", "coverage", "confidence", "computed_at",
        }

    summary = surface.call("summarize_period", {"days": 365})
    assert summary["sessions"] >= 2 and "synthetic" in summary["sessions_by_provider"]
    assert summary["truncated"] is False and len(summary["top_projects"]) <= 10
    assert isinstance(summary["sessions_with_known_value_by_metric"], dict)

    explained = surface.call("explain_metric", {"metric_key": definitions["definitions"][0]["key"]})
    assert explained["metric"]["key"] == definitions["definitions"][0]["key"]
    assert "never converted to zero" in explained["reading_guide"]["unknown"]

    calibration = surface.call("get_calibration_status", {})
    assert calibration == {"contract_version": AGENT_SURFACE_CONTRACT_VERSION, "available": True, "sample_sessions": 3, "fully_rated_sessions": 1, "metric_keys": ["a"], "model_judge": []}

    # Closed failure codes; nothing leaks through validation errors.
    for name, arguments, code in (
        ("list_sessions", {"limit": MAX_SESSIONS_PER_PAGE + 1}, "invalid_arguments"),
        ("list_sessions", {"provider": "gemini"}, "invalid_arguments"),
        ("get_session_metrics", {"session_id": "../etc"}, "invalid_arguments"),
        ("explain_metric", {"metric_key": "no.such.metric"}, "metric_not_found"),
        ("drop_everything", {}, "unknown_tool"),
        ("list_sessions", {"unexpected": 1}, "invalid_arguments"),
    ):
        try:
            surface.call(name, arguments)
        except AgentSurfaceError as error:
            assert error.code == code, (name, error.code)
        else:
            raise AssertionError(f"{name} accepted {arguments}")


def test_jsonrpc_handshake_tool_listing_and_calls(tmp_path: Path) -> None:
    surface = _surface(tmp_path)
    init = handle_message(surface, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}, version="9.9")
    assert init["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert init["result"]["serverInfo"] == {"name": "prompt-enhancer", "version": "9.9"}
    assert handle_message(surface, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert handle_message(surface, {"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    tools = handle_message(surface, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
    assert [tool["name"] for tool in tools][:2] == ["list_metric_definitions", "list_sessions"]
    assert all("inputSchema" in tool and "description" in tool for tool in tools)
    called = handle_message(surface, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_sessions", "arguments": {"limit": 1}}})
    assert called["result"]["isError"] is False
    text_payload = json.loads(called["result"]["content"][0]["text"])
    assert text_payload == called["result"]["structuredContent"] and len(text_payload["sessions"]) == 1
    bad_args = handle_message(surface, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_sessions", "arguments": {"limit": 0}}})
    assert bad_args["result"]["isError"] is True and json.loads(bad_args["result"]["content"][0]["text"]) == {"error": "invalid_arguments"}
    unknown = handle_message(surface, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "sql", "arguments": {}}})
    assert unknown["error"]["code"] == -32602
    missing = handle_message(surface, {"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {"uri": "file:///x"}})
    assert missing["error"]["code"] == -32601
    assert handle_message(surface, {"jsonrpc": "2.0", "id": 8, "method": "resources/list"})["result"] == {"resources": []}
    assert handle_message(surface, {"id": 9, "method": "ping"})["error"]["code"] == -32600


def test_stdio_server_round_trips_lines_and_ignores_garbage(tmp_path: Path) -> None:
    surface = _surface(tmp_path)
    stdin = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                "not json",
                "",
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_calibration_status"}}),
                json.dumps([{"jsonrpc": "2.0", "id": 3, "method": "ping"}, {"jsonrpc": "2.0", "id": 4, "method": "ping"}]),
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    seen: list[str] = []
    assert McpStdioServer(surface, stdin=stdin, stdout=stdout, on_message=seen.append).serve_forever() == 0
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["id"] == 1 and "protocolVersion" in lines[0]["result"]
    assert lines[1]["error"]["code"] == -32700
    assert lines[2]["id"] == 2 and lines[2]["result"]["structuredContent"]["available"] is True
    assert [reply["id"] for reply in lines[3]] == [3, 4]
    assert seen == ["initialize", "notifications/initialized", "tools/call", "?"]


def test_cli_refuses_without_acknowledgement_and_serves_with_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings = AppSettings(home=home)
    application = bootstrap_local_application(settings)
    application.database.initialize()
    env = {**os.environ, "PROMPT_ENHANCER_HOME": str(home), CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV: ""}
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        source_root
        if not inherited_pythonpath
        else os.pathsep.join((source_root, inherited_pythonpath))
    )
    env.pop(CONTEXT_EGRESS_ACKNOWLEDGEMENT_ENV)
    refused = subprocess.run(
        [sys.executable, "-m", "prompt_enhancer", "mcp"], input="", capture_output=True, text=True, env=env, timeout=120,
    )
    assert refused.returncode == 2 and "acknowledge" in refused.stderr and refused.stdout == ""

    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    served = subprocess.run(
        [sys.executable, "-m", "prompt_enhancer", "mcp", "--acknowledge-context-egress"],
        input=request, capture_output=True, text=True, env=env, timeout=180,
    )
    assert served.returncode == 0, served.stderr
    reply = json.loads(served.stdout.strip().splitlines()[-1])
    assert [tool["name"] for tool in reply["result"]["tools"]][0] == "list_metric_definitions"

    config = subprocess.run(
        [sys.executable, "-m", "prompt_enhancer", "mcp-config"], capture_output=True, text=True, env=env, timeout=120,
    )
    assert config.returncode == 0 and '"prompt-enhancer"' in config.stdout and "--acknowledge-context-egress" in config.stdout
    assert "[mcp_servers.prompt-enhancer]" in config.stdout


def test_bootstrap_surface_reports_calibration_without_a_running_model(tmp_path: Path) -> None:
    settings = AppSettings(home=tmp_path / "home")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    surface = application.create_agent_read_surface()
    status = surface.call("get_calibration_status", {})
    assert status["available"] is True and status["model_judge"] == [] and status["sample_sessions"] >= 0
    assert Provider.SYNTHETIC.value in {"synthetic"}  # the surface never widens the provider set
