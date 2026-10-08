"""Real application HTTP serialization; synthetic service, workspace and token."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService
from prompt_enhancer.application.local_agent_limits import LocalAgentError
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.local_agent_routes import _failure


@pytest.mark.parametrize(
    "code,status",
    [
        ("workspace_write_failed", 503),
        ("workspace_cleanup_failed", 503),
        ("workspace_verification_failed", 409),
    ],
)
def test_workspace_publication_failures_have_fixed_recovery_status(code, status):
    failure = _failure(LocalAgentError(code))
    assert failure.status_code == status
    assert failure.detail == {"code": code}


def test_http_cleanup_state_and_fixed_refusals_survive_idle_worker(tmp_path, monkeypatch):
    workspace = tmp_path / "example-project"
    workspace.mkdir()
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
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    root = f"/v1/agent/sessions/{view.session_id}"
    try:
        # This test injects the service outcome, not permission to execute any action.
        service._quarantine_commands()
        for endpoint in (root, root + "/events"):
            response = client.get(endpoint, headers=headers)
            assert response.status_code == 200
            assert response.json()["contract_version"] == "local-agent.v9"
            assert response.json()["cleanup_unconfirmed"] is True
            assert response.json()["closing"] is True
            assert response.json()["running"] is False
        assert client.get("/v1/agent/sessions", headers=headers).json()[0]["cleanup_unconfirmed"] is True
        changes = client.get(root + "/changes", headers=headers)
        assert changes.status_code == 200
        assert changes.json()["settled"] is False
        assert changes.json()["coverage"] == "partial"
        streamed = client.get(root + "/events/stream", headers=headers)
        assert streamed.status_code == 200 and '"cleanup_unconfirmed":true' in streamed.text
        for method, endpoint, body in (
            ("POST", "/v1/agent/sessions", {"workspace": str(workspace)}),
            ("POST", root + "/messages", {"text": "Another fictional request."}),
            ("DELETE", root, None),
            ("POST", root + "/workspace/previews", {"path": "example.txt", "content": "example", "expected_revision": "a" * 64, "line_ending": "lf"}),
        ):
            response = client.request(method, endpoint, json=body, headers=headers)
            assert response.status_code == 409
            assert response.json() == {"detail": {"code": "command_cleanup_unconfirmed"}}
        stopped = client.post(root + "/stop", headers=headers)
        assert stopped.status_code == 200 and stopped.json()["cleanup_unconfirmed"] is True
        # An API token still cannot approve a protected command, including when paused.
        denied = client.post(root + "/approvals/" + "b" * 32, json={"approved": True}, headers=headers)
        assert denied.status_code == 403
        assert denied.json() == {"detail": "owned native confirmation required"}
    finally:
        client.close()
        with pytest.raises(RuntimeError, match="^agent_shutdown_incomplete$"):
            service.shutdown(timeout=1)
