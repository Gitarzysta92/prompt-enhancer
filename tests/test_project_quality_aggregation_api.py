from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.project_quality_aggregation import (
    FingerprintedSessionQualityAggregator,
    ProjectQualityAggregationService,
    ProjectQualitySelectionLimitError,
)
from prompt_enhancer.application.analysis.session_quality_aggregation import (
    SessionQualityAggregationService,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


EXAMPLE_TOKEN = "example_project_aggregate_token_123456789"


def _service(database: Database) -> ProjectQualityAggregationService:
    def session_quality_factory(repository):
        return FingerprintedSessionQualityAggregator(
            SessionQualityAggregationService(
                repository,
                definitions=COACHING_METRIC_DEFINITIONS,
                analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
                analysis_profile_version=(
                    COACHING_PROFILE_V1.analysis_profile_version
                ),
                metric_pack_key=COACHING_METRIC_PACK_KEY,
                metric_pack_version=COACHING_METRIC_PACK_VERSION,
            )
        )

    return ProjectQualityAggregationService(database, session_quality_factory)


def _client_and_scope(tmp_path):
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    sessions = database.list_sessions(limit=100)
    project_id = str(sessions[0]["project_id"])
    session_ids = tuple(str(item["session_id"]) for item in sessions)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
        project_quality_aggregation_service=_service(database),
    )
    return (
        TestClient(app, base_url="http://127.0.0.1"),
        project_id,
        session_ids,
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


def test_multi_project_endpoint_is_explicit_complete_and_identifier_free(
    tmp_path,
) -> None:
    client, project_id, session_ids = _client_and_scope(tmp_path)

    with client:
        response = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
            json={
                "project_ids": [project_id],
                "selection_mode": "all_analyzed_work",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selection_mode"] == "all_analyzed_work"
    assert body["estimand"] == "per_eligible_opportunity"
    assert body["aggregation_method"] == "ratio_of_sums"
    assert body["selected_project_count"] == 1
    aggregate = body["session_quality"]
    assert aggregate["selected_session_count"] == len(session_ids)
    assert aggregate["completed_run_count"] == 0
    assert aggregate["missing_run_count"] == len(session_ids)
    assert len(aggregate["metrics"]) == len(COACHING_METRIC_DEFINITIONS)

    serialized = response.text
    assert project_id not in serialized
    assert all(session_id not in serialized for session_id in session_ids)
    forbidden_keys = {
        "project_id",
        "project_ids",
        "session_id",
        "session_ids",
        "display_name",
        "label",
        "evidence",
        "evidence_id",
        "path",
        "excerpt",
        "prompt",
        "response",
        "tool_output",
    }
    assert _all_keys(body).isdisjoint(forbidden_keys)


def test_invalid_modes_selectors_and_canaries_are_sanitized(tmp_path) -> None:
    client, project_id, _session_ids = _client_and_scope(tmp_path)
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    canary = "synthetic-private-transcript-canary"

    with client:
        unauthorized = client.post(
            "/v1/quality-analysis/aggregate-projects",
            json={"project_ids": [project_id]},
        )
        duplicate = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers=headers,
            json={"project_ids": [project_id, project_id]},
        )
        unsupported = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers=headers,
            json={
                "project_ids": [project_id],
                "selection_mode": "typical_project",
            },
        )
        extra = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers=headers,
            json={"project_ids": [project_id], "transcript": canary},
        )

    assert unauthorized.status_code == 401
    assert duplicate.status_code == 422
    assert unsupported.status_code == 422
    assert extra.status_code == 422
    combined = duplicate.text + unsupported.text + extra.text
    assert canary not in combined
    assert project_id not in combined
    assert all(
        response.json() == {"detail": "request validation failed"}
        for response in (duplicate, unsupported, extra)
    )


def test_missing_project_returns_one_fixed_content_free_failure(tmp_path) -> None:
    client, project_id, _session_ids = _client_and_scope(tmp_path)
    missing_project = "9" * 64

    with client:
        response = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
            json={"project_ids": [project_id, missing_project]},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "project quality selection is incomplete"}
    assert project_id not in response.text
    assert missing_project not in response.text


class _LimitService:
    def aggregate(self, _selection):
        raise ProjectQualitySelectionLimitError(
            ProjectQualitySelectionLimitError.code
        )


def test_over_limit_response_is_fixed_and_contains_no_selection(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
        project_quality_aggregation_service=_LimitService(),  # type: ignore[arg-type]
    )
    project_id = "7" * 64

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/v1/quality-analysis/aggregate-projects",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
            json={"project_ids": [project_id]},
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "project quality selection exceeds the local session limit"
    }
    assert project_id not in response.text


class _NavigationGuardService:
    def __init__(self) -> None:
        self.calls = 0

    def aggregate(self, _selection):
        self.calls += 1
        raise AssertionError("navigation must not start project aggregation")


def test_project_navigation_does_not_trigger_aggregation_or_provider_access(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    project_id = str(database.list_sessions(limit=1)[0]["project_id"])
    service = _NavigationGuardService()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
        project_quality_aggregation_service=service,  # type: ignore[arg-type]
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            f"/v1/projects/{project_id}/sessions",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert response.status_code == 200
    assert service.calls == 0
