from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.metric_coverage import (
    MetricCoverageService,
)
from prompt_enhancer.application.analysis.metric_readiness import (
    MetricReadinessService,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider, SafeSession, SessionState


NOW = datetime(2049, 1, 2, 3, 4, tzinfo=UTC)
TOKEN = "example_metric_coverage_token_123456"
PROJECT_ID = "2" * 64


class _MissingCatalog:
    def descriptor(self, provider, surface):
        del provider, surface
        raise LookupError("reserved synthetic missing adapter")

    def get_cached(self, provider, surface):
        del provider, surface
        return None


def _service(database: Database) -> MetricCoverageService:
    readiness = MetricReadinessService(
        database,
        database.session_analysis_run_repository(),
        _MissingCatalog(),
    )
    return MetricCoverageService(
        database.metric_coverage_repository(),
        readiness,
        clock=lambda: NOW,
    )


def _client(tmp_path) -> tuple[TestClient, Database]:
    database = Database(tmp_path / "coverage.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        metric_coverage_service=_service(database),
    )
    return TestClient(app, base_url="http://127.0.0.1"), database


def test_metric_coverage_routes_are_authenticated_private_and_identifier_free(
    tmp_path,
) -> None:
    client, database = _client(tmp_path)
    database.persist_session(
        SafeSession(
            provider=Provider.CODEX,
            installation_id="1" * 64,
            project_id=PROJECT_ID,
            session_id="3" * 64,
            provider_version="0.144.5",
            adapter_version="codex-app-server-v1",
            source_schema_version="codex-consumed-schema-v1",
            started_at=NOW - timedelta(minutes=2),
            ended_at=NOW - timedelta(minutes=1),
            terminal_state=SessionState.COMPLETED,
            events_complete=True,
        ),
        (),
    )
    headers = {API_TOKEN_HEADER: TOKEN}

    with client:
        unauthorized = client.get("/v1/metric-coverage")
        catalog = client.get("/v1/metric-coverage", headers=headers)
        project = client.get(
            f"/v1/projects/{PROJECT_ID}/metric-coverage",
            headers=headers,
        )

    assert unauthorized.status_code == 401
    assert catalog.status_code == 200
    assert project.status_code == 200
    assert catalog.headers["cache-control"] == "no-store, private"
    assert catalog.headers["pragma"] == "no-cache"
    assert catalog.json()["scope"] == "provider_catalog"
    assert project.json()["scope"] == "one_project"
    assert catalog.json()["indexed_session_count"] == 1
    assert project.json()["indexed_session_count"] == 1
    assert len(catalog.json()["metrics"]) == 20
    assert catalog.json()["provider_history_completeness"] == "unknown"
    assert (
        catalog.json()["capability_report"][
            "structurally_unknown_metric_count"
        ]
        == 20
    )
    payload = json.dumps(project.json(), sort_keys=True)
    assert PROJECT_ID not in payload
    assert "session_id" not in payload
    assert "run_id" not in payload
    assert "grant_id" not in payload


def test_missing_project_and_invalid_provider_errors_are_sanitized(tmp_path) -> None:
    client, _database = _client(tmp_path)
    headers = {API_TOKEN_HEADER: TOKEN}

    with client:
        missing = client.get(
            f"/v1/projects/{'f' * 64}/metric-coverage",
            headers=headers,
        )
        invalid = client.get(
            "/v1/metric-coverage",
            params={"provider": "private-provider-value"},
            headers=headers,
        )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "indexed project not found"}
    assert "f" * 64 not in missing.text
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "request validation failed"}
    assert "private-provider-value" not in invalid.text
