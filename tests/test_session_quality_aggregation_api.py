from __future__ import annotations

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)


EXAMPLE_TOKEN = "example_quality_aggregate_token_123456789"


def _client_and_sessions(tmp_path):
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_ids = tuple(
        str(item["session_id"]) for item in database.list_sessions(limit=100)
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )
    return TestClient(app, base_url="http://127.0.0.1"), session_ids


def test_selected_session_quality_aggregate_is_content_free_and_missing_aware(
    tmp_path,
) -> None:
    client, session_ids = _client_and_sessions(tmp_path)
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}

    with client:
        response = client.post(
            "/v1/quality-analysis/aggregate",
            headers=headers,
            json={"session_ids": list(session_ids)},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_profile_key"] == "coaching_profile"
    assert body["analysis_profile_version"] == 1
    assert body["metric_pack_key"] == COACHING_METRIC_PACK_KEY
    assert body["metric_pack_version"] == COACHING_METRIC_PACK_VERSION
    assert body["metric_schema_version"] == 2
    assert body["selected_session_count"] == 2
    assert body["completed_run_count"] == 0
    assert body["missing_run_count"] == 2
    assert body["integrity_state"] == "valid"
    assert len(body["metrics"]) == 20
    assert tuple(
        (item["metric_key"], item["metric_version"])
        for item in body["metrics"]
    ) == tuple(
        (definition.key, definition.version)
        for definition in COACHING_METRIC_DEFINITIONS
    )
    assert all(item["aggregate_state"] == "unknown" for item in body["metrics"])
    assert all(item["numeric_value"] is None for item in body["metrics"])
    serialized = response.text
    assert all(session_id not in serialized for session_id in session_ids)
    assert "evidence_event_ids" not in serialized
    assert "message_refs" not in serialized


def test_quality_aggregate_rejects_bad_scope_without_repository_details(tmp_path) -> None:
    client, session_ids = _client_and_sessions(tmp_path)
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}

    with client:
        unauthorized = client.post(
            "/v1/quality-analysis/aggregate",
            json={"session_ids": [session_ids[0]]},
        )
        duplicate = client.post(
            "/v1/quality-analysis/aggregate",
            headers=headers,
            json={"session_ids": [session_ids[0], session_ids[0]]},
        )
        raw = client.post(
            "/v1/quality-analysis/aggregate",
            headers=headers,
            json={"session_ids": ["example-session"]},
        )
        extra = client.post(
            "/v1/quality-analysis/aggregate",
            headers=headers,
            json={
                "session_ids": [session_ids[0]],
                "transcript": "synthetic-canary-must-not-be-accepted",
            },
        )

    assert unauthorized.status_code == 401
    assert duplicate.status_code == 422
    assert raw.status_code == 422
    assert extra.status_code == 422
    combined = duplicate.text + raw.text + extra.text
    assert "synthetic-canary-must-not-be-accepted" not in combined
    assert all(session_id not in combined for session_id in session_ids)
