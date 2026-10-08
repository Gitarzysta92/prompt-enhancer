"""Synthetic Agent turns and real application HTTP for bounded inspection."""

from __future__ import annotations

import json
from threading import Event

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService, SendMessage
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools
from prompt_enhancer.application.runtime_cancellation import current_runtime_cancellation
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from tests.test_local_agent import _stub_model, _wait


@pytest.mark.parametrize("name, arguments", [
    ("read_file", {"path": "example.txt"}), ("list_dir", {}), ("search_text", {"query": "example"}),
])
def test_turn_stop_reaches_read_only_tools_and_is_not_a_failed_model_turn(tmp_path, monkeypatch, name, arguments):
    (tmp_path / "example.txt").write_text("example", encoding="utf-8")
    entered, release = Event(), Event()
    observed = []
    original = getattr(WorkspaceTools, name)

    def inspection(self, *args, **kwargs):
        observed.append(current_runtime_cancellation())
        entered.set()
        assert release.wait(2)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(WorkspaceTools, name, inspection)
    chat, calls = _stub_model([{"tool_calls": [{"id": "example-read", "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments),
    }}]}])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model")
    view = service.create(AgentSettings(workspace=str(tmp_path)))
    try:
        service.send(view.session_id, SendMessage(text="Inspect the fictional workspace."))
        assert entered.wait(2)
        service.stop(view.session_id)
        release.set()
        assert _wait(lambda: not service.get(view.session_id).running)
        assert observed[0] is not None and observed[0].is_set()
        events = service.events(view.session_id).events
        result = next(event for event in events if event.kind == "tool_result")
        assert result.ok is False and result.tool_state == "cancelled"
        done = next(event for event in events if event.kind == "done")
        assert done.turn_summary is not None and done.turn_summary.status == "stopped"
        assert done.turn_summary.reason == "stop_requested"
        assert done.turn_summary.tools_cancelled == 1 and done.turn_summary.tools_failed == 0
        assert len(calls) == 1
    finally:
        release.set()
        service.shutdown(timeout=2)


@pytest.fixture
def example_workspace_http(tmp_path, monkeypatch):
    workspace = tmp_path / "example-project"
    workspace.mkdir()
    (workspace / "example.txt").write_text("example\n", encoding="utf-8")
    settings = AppSettings(home=tmp_path / "example-app")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    service = LocalAgentService(chat=lambda *_: (200, b"{}", "application/json"), active_model=lambda: "example-model")
    view = service.create(AgentSettings(workspace=str(workspace)))
    monkeypatch.setattr(
        type(application),
        "create_local_agent_service",
        lambda self, local_model_service=None, *, mcp_managed_runtime_service=None: service,
    )
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    # This is a newly generated token in disposable fixture state, not a user credential.
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    try:
        yield client, headers, f"/v1/agent/sessions/{view.session_id}/workspace", workspace, service
    finally:
        client.close()
        service.shutdown(timeout=2)


def test_http_replaced_root_returns_only_a_fixed_error_and_private_headers(example_workspace_http):
    client, headers, url, workspace, _ = example_workspace_http
    old_file = client.get(url + "/file?path=example.txt", headers=headers).json()
    workspace.rename(workspace.parent / "example-original")
    workspace.mkdir()
    (workspace / "example.txt").write_text("EXAMPLE_REPLACEMENT_CANARY", encoding="utf-8")
    for path in ("/tree?path=.", "/file?path=example.txt"):
        response = client.get(url + path, headers=headers)
        assert response.status_code == 409
        assert response.json() == {"detail": {"code": "workspace_root_changed"}}
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["pragma"] == "no-cache"
        assert "EXAMPLE_REPLACEMENT_CANARY" not in response.text
    preview = client.post(url + "/previews", headers=headers, json={
        "path": "example.txt", "content": "example revised\n", "expected_revision": old_file["revision"], "line_ending": "lf",
    })
    assert preview.status_code == 409
    assert preview.json() == {"detail": {"code": "workspace_root_changed"}}
    assert (workspace / "example.txt").read_text(encoding="utf-8") == "EXAMPLE_REPLACEMENT_CANARY"


def test_http_zero_visible_entries_with_scan_limit_is_not_a_complete_tree(example_workspace_http, monkeypatch):
    from prompt_enhancer.application import local_agent_workspace as workspace_module

    client, headers, url, _, _ = example_workspace_http
    monkeypatch.setattr(workspace_module, "MAX_TREE_SCAN_ENTRIES", 0)
    response = client.get(url + "/tree?path=.", headers=headers)
    assert response.status_code == 200
    assert response.json()["entries"] == []
    assert response.json()["complete"] is False
    assert response.headers["cache-control"] == "no-store, private"


def test_http_inspection_timeout_is_a_retryable_fixed_error(example_workspace_http, monkeypatch):
    from prompt_enhancer.application import local_agent_workspace as workspace_module

    client, headers, url, _, _ = example_workspace_http
    monkeypatch.setattr(workspace_module, "MAX_WORKSPACE_SCAN_SECONDS", 0)
    response = client.get(url + "/tree?path=.", headers=headers)
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "workspace_inspection_timeout"}}
    assert response.headers["cache-control"] == "no-store, private"


def test_http_filesystem_exception_cannot_become_an_empty_tree_or_expose_detail(example_workspace_http, monkeypatch):
    from prompt_enhancer.application.local_workspace_io import WorkspaceIO

    client, headers, url, _, _ = example_workspace_http

    def denied(*_args, **_kwargs):
        raise PermissionError("EXAMPLE_PRIVATE_DIRECTORY_CANARY")

    monkeypatch.setattr(WorkspaceIO, "entries", denied)
    response = client.get(url + "/tree?path=.", headers=headers)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "workspace_directory_unavailable"}}
    assert "EXAMPLE_PRIVATE_DIRECTORY_CANARY" not in response.text
