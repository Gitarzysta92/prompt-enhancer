from __future__ import annotations

import socket
import subprocess

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.cli import main
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TOKEN = "example_local_api_token_do_not_use_123456789"


class MemoryReadStore:
    def __init__(self) -> None:
        self.initialize_calls = 0

    def initialize(self) -> None:
        self.initialize_calls += 1

    def list_metric_definitions(self) -> list[dict[str, object]]:
        return [{"key": "workflow.event_count", "version": 1, "unit": "count"}]

    def list_sessions(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        return []

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        return []


def _client(tmp_path) -> TestClient:
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=MemoryReadStore(),
        api_token=EXAMPLE_TOKEN,
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_health_is_minimal_and_only_v1_routes_require_authentication(tmp_path) -> None:
    with _client(tmp_path) as client:
        health = client.get("/health")
        unauthorized = client.get("/v1/capabilities")
        wrong = client.get(
            "/v1/capabilities",
            headers={API_TOKEN_HEADER: "example_wrong_token_do_not_use_123456"},
        )
        authorized = client.get(
            "/v1/capabilities",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "cost_mode": "offline_only",
        "data_tier": "metadata",
    }
    assert unauthorized.status_code == 401
    assert wrong.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {
        "cost_mode": "offline_only",
        "data_tier": "metadata",
        "network_inference": False,
        "raw_transcripts": False,
        "arbitrary_sql": False,
        "write_api": False,
        "task_review": False,
        "task_lifecycle": False,
        "task_analysis": False,
        "session_text_analysis": False,
        "session_model_link_experiment": False,
        "session_text_analysis_data_tier": None,
        "session_text_content_persistence": False,
        "codex_local_source": False,
        "claude_code_local_source": False,
        "local_models": False,
        "prompt_check": False,
        "local_agent": False,
        "annotation": False,
        "shared_folders": False,
        "manual_display_labels": False,
        "browser_session": True,
        "demo_provider": "synthetic",
    }
    assert EXAMPLE_TOKEN not in "".join(
        response.text for response in (health, unauthorized, wrong, authorized)
    )


def test_host_and_origin_checks_reject_non_local_requests(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with _client(tmp_path) as client:
        hostile_host = client.get(
            "/v1/capabilities",
            headers={**headers, "Host": "attacker.invalid"},
        )
        hostile_origin = client.get(
            "/v1/capabilities",
            headers={**headers, "Origin": "https://attacker.invalid"},
        )
        same_origin = client.get(
            "/v1/capabilities",
            headers={**headers, "Origin": "http://127.0.0.1"},
        )

    assert hostile_host.status_code == 400
    assert hostile_origin.status_code == 403
    assert same_origin.status_code == 200


def test_api_has_no_docs_sql_or_write_surface(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with _client(tmp_path) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.post("/v1/sql", headers=headers, json={"sql": "SELECT 1"}).status_code == 404
        assert client.post("/v1/sessions", headers=headers, json={}).status_code == 405


def test_session_metric_identifier_is_a_pseudonym(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with _client(tmp_path) as client:
        valid = client.get(f"/v1/sessions/{'a' * 64}/metrics", headers=headers)
        raw_identifier = client.get(
            "/v1/sessions/example-session-completed/metrics",
            headers=headers,
        )

    assert valid.status_code == 200
    assert raw_identifier.status_code == 422


def test_project_session_catalog_is_scoped_counted_and_bounded(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    project_id = str(database.list_sessions(limit=1)[0]["project_id"])
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}

    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.get(
            f"/v1/projects/{project_id}/sessions?provider=synthetic&limit=1",
            headers=headers,
        )
        second = client.get(
            f"/v1/projects/{project_id}/sessions?provider=synthetic&limit=1&offset=1",
            headers=headers,
        )
        missing = client.get(
            f"/v1/projects/{'f' * 64}/sessions?provider=synthetic",
            headers=headers,
        )
        invalid = client.get(
            "/v1/projects/example-project/sessions",
            headers=headers,
        )

    assert first.status_code == 200
    assert first.json()["total"] == 2
    assert first.json()["has_more"] is True
    assert len(first.json()["sessions"]) == 1
    assert all(item["project_id"] == project_id for item in first.json()["sessions"])
    assert second.status_code == 200
    assert second.json()["total"] == 2
    assert second.json()["has_more"] is False
    assert len(second.json()["sessions"]) == 1
    assert missing.status_code == 200
    assert missing.json()["sessions"] == []
    assert missing.json()["total"] == 0
    assert missing.json()["has_more"] is False
    assert invalid.status_code == 422


def test_synthetic_demo_does_not_open_network_connections(
    tmp_path, monkeypatch, capsys
) -> None:
    def deny_network(*args, **kwargs):
        raise AssertionError("synthetic demo attempted a network operation")

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setenv("PROMPT_ENHANCER_HOST", "127.0.0.1")
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)

    result = main(["demo"])
    output = capsys.readouterr()

    assert result == 0
    assert "Synthetic demo loaded" in output.out
    assert output.err == ""
    assert str(tmp_path) not in output.out
    assert EXAMPLE_TOKEN not in output.out
    assert "example-session" not in output.out


def test_codex_consent_commands_do_not_access_provider_state(
    tmp_path, monkeypatch, capsys
) -> None:
    def deny_process(*args, **kwargs):
        raise AssertionError("consent command attempted to launch a process")

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", deny_process)

    assert main(["codex-consent-grant", "local-history"]) == 0
    database = Database(tmp_path / "metrics.sqlite3")
    assert database.has_active_consent(
        Provider.CODEX, DataTier.REDACTED_CONTENT
    )
    assert main(["codex-consent-revoke", "local-history"]) == 0
    assert not database.has_active_consent(
        Provider.CODEX, DataTier.REDACTED_CONTENT
    )

    output = capsys.readouterr()
    assert str(tmp_path) not in output.out


def test_codex_index_without_consent_never_launches_app_server(
    tmp_path, monkeypatch, capsys
) -> None:
    def deny_process(*args, **kwargs):
        raise AssertionError("consent gate was bypassed")

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", deny_process)

    assert main(["codex-index"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "failed safely" in output.err


def test_codex_analysis_requires_an_explicit_safe_selection(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))

    assert main(["codex-analyze"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "failed safely" in output.err


def test_codex_analysis_rejects_unindexed_selection_without_provider_access(
    tmp_path, monkeypatch, capsys
) -> None:
    def deny_process(*args, **kwargs):
        raise AssertionError("unindexed selection attempted to launch a process")

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    assert main(["codex-consent-grant", "local-history"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(subprocess, "Popen", deny_process)

    result = main(
        [
            "codex-analyze",
            "--project-id",
            "a" * 64,
            "--max-sessions",
            "10",
        ]
    )
    output = capsys.readouterr()

    assert result == 1
    assert output.out == ""
    assert "failed safely" in output.err
    assert str(tmp_path) not in output.err
