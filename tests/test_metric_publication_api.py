"""Authenticated read-only API tests for the V2 metric publication seam."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_RUBRIC_VERSION,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.metric_guidance import (
    GuidanceStateClass,
    metric_guidance_catalog,
)
from prompt_enhancer.application.analysis.session_metric_publication_service import (
    SESSION_METRIC_PUBLICATION_KEY,
    SessionMetricPublicationError,
    SessionMetricPublicationService,
)
from prompt_enhancer.application.persistence import (
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    TEXT_METRIC_SCHEMA_VERSION,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import SCHEMA_VERSION, Database
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2040, 5, 6, 8, 0, tzinfo=UTC)
EXAMPLE_TOKEN = "example_metric_publication_token_123456"
RUN_ID = "a" * 64
CATALOG_PATH = "/v1/metric-contracts/v2/guidance-catalog"
OPERABILITY_CATALOG_PATH = "/v1/metric-contracts/v2/operability-catalog"


def _database_and_session(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    return database, database.list_sessions(limit=1)[0]["session_id"]


def _draft(session_id: str) -> SessionAnalysisRunDraft:
    return SessionAnalysisRunDraft(
        run_id=RUN_ID,
        session_id=session_id,
        request_fingerprint="f" * 64,
        input_fingerprint="b" * 64,
        analysis_profile_key="coaching_profile",
        analysis_profile_version=1,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
        selected_metric_keys=("prompt.task_definition_coverage",),
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version="explicit-session-text-analysis-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-schema-v1",
        content_schema_version="redacted-message-v1",
        metric_engine_version=COACHING_METRIC_ENGINE_VERSION,
        redactor_version="deterministic-redactor-v1",
        model_plan_fingerprint="c" * 64,
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        started_at=NOW,
    )


def _rubric_result() -> SessionAnalysisResultRecord:
    return SessionAnalysisResultRecord(
        observation=MetricObservation(
            key="prompt.task_definition_coverage",
            version=2,
            numeric_value=2 / 3,
            unit="ratio",
            source=MetricSource.DETERMINISTIC,
            observed_count=3,
            eligible_count=3,
            coverage=1.0,
        ),
        value_state=MetricValueState.KNOWN,
        direction=SessionMetricDirection.HIGHER_IS_BETTER,
        applicability=SessionMetricApplicability.APPLICABLE,
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        fraction_numerator=2,
        fraction_denominator=3,
        explanation_code="rubric_factors",
        algorithm_id=COACHING_METRIC_ALGORITHM_ID,
        algorithm_version=COACHING_METRIC_ALGORITHM_VERSION,
        rubric_version=COACHING_METRIC_RUBRIC_VERSION,
        computed_at=NOW,
    )


def _completed_run(tmp_path) -> tuple[Database, str]:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(session_id)
    repository.begin(draft)
    repository.complete(
        draft.run_id,
        (_rubric_result(),),
        finished_at=NOW + timedelta(minutes=1),
    )
    return database, session_id


def _app(tmp_path, database: Database):
    return create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )


def test_guidance_catalog_route_requires_a_token_and_carries_no_session_data(
    tmp_path,
) -> None:
    database, _ = _database_and_session(tmp_path)

    with TestClient(_app(tmp_path, database), base_url="http://127.0.0.1") as client:
        unauthorized = client.get(CATALOG_PATH)
        response = client.get(CATALOG_PATH, headers={API_TOKEN_HEADER: EXAMPLE_TOKEN})

    assert unauthorized.status_code == 401
    assert response.status_code == 200, response.text
    body = response.json()
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert body["contract_set_fingerprint"] == metric_contract_v2_set_fingerprint()
    assert body["registry_version"] == "all-20-factor-contracts-v2"
    assert body["catalog_version"] == "metric-guidance-templates-v1"
    assert body["contract_version"] == "metric-guidance-contract-v1"
    assert len(body["entries"]) == 20
    assert [entry["metric_key"] for entry in body["entries"]] == [
        contract.metric_key for contract in METRIC_CONTRACTS_V2
    ]
    assert len(body["entries"][0]["templates"]) == len(GuidanceStateClass)
    lowered = response.text.casefold()
    for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
        assert prohibited not in lowered


def test_operability_catalog_is_authenticated_private_and_content_free(
    tmp_path,
) -> None:
    database, _ = _database_and_session(tmp_path)

    with TestClient(_app(tmp_path, database), base_url="http://127.0.0.1") as client:
        unauthorized = client.get(OPERABILITY_CATALOG_PATH)
        response = client.get(
            OPERABILITY_CATALOG_PATH,
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["Pragma"] == "no-cache"
    body = response.json()
    assert body["total_metric_count"] == 20
    assert body["shipped_path_count"] == 16
    assert body["task_profile_configuration_gap_count"] == 0
    assert body["provider_adapter_gap_count"] == 4
    assert body["experimental_model_path_count"] == 8
    assert body["model_authoritative_metric_count"] == 0
    assert [entry["metric_key"] for entry in body["entries"]] == [
        contract.metric_key for contract in METRIC_CONTRACTS_V2
    ]
    assert all(
        entry["measured_value_may_use_model_output"] is False
        for entry in body["entries"]
    )
    lowered = response.text.casefold()
    for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
        assert prohibited not in lowered


def test_authenticated_metric_publication_publishes_all_twenty_states(
    tmp_path,
) -> None:
    database, session_id = _completed_run(tmp_path)
    path = f"/v1/quality-analysis/runs/{RUN_ID}/metric-v2-compatibility-preview"

    with TestClient(_app(tmp_path, database), base_url="http://127.0.0.1") as client:
        unauthorized = client.get(path)
        response = client.get(path, headers={API_TOKEN_HEADER: EXAMPLE_TOKEN})
        missing = client.get(
            f"/v1/quality-analysis/runs/{'9' * 64}/metric-v2-compatibility-preview",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["projection_key"] == SESSION_METRIC_PUBLICATION_KEY
    assert body["run_id"] == RUN_ID
    assert body["source_result_count"] == 1
    assert "not_canonical_live_snapshot" in body["preview_limits"]
    assert "no_model_stage_output_consumed" in body["preview_limits"]
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["Pragma"] == "no-cache"
    publication = body["publication"]
    assert publication["source"] == "v1_compatibility_preview"
    assert publication["registry_version"] == "all-20-factor-contracts-v2"
    assert publication["contract_set_fingerprint"] == (
        metric_contract_v2_set_fingerprint()
    )
    assert len(publication["metrics"]) == 20
    assert publication["known_count"] == 1
    assert publication["objective_measured_count"] == 0
    assert publication["product_metric_eligible"] is False
    assert publication["canonical_live_snapshot"] is False
    assert publication["model_stage_consumed"] is False
    assert publication["compatibility_preview"] is True
    assert sorted(
        {item["implementation_state"] for item in publication["metrics"]}
    ) == ["compatibility_projected", "method_only_withheld", "objective_capability_missing"]

    by_key = {item["state"]["metric_key"]: item for item in publication["metrics"]}
    known = by_key["prompt.task_definition_coverage"]
    assert known["state"]["value_state"] == "known"
    assert known["guidance"]["basis"] == "method-only"
    assert known["guidance"]["action_template_id"] == (
        "action.improve.prompt.task_definition_coverage.v1"
    )
    # Every evidence-lane metric stays fail-closed for a V1 receipt.
    for metric_key in (
        "logic.hypothesis_test_linkage",
        "logic.requirement_action_traceability",
        "outcome.agent_claim_grounding",
        "outcome.first_pass_verification",
        "outcome.verified_requirement_coverage",
    ):
        entry = by_key[metric_key]
        assert entry["state"]["value_state"] == "unknown"
        assert entry["state"]["numeric_value"] is None
        assert entry["guidance"]["audience"] == "tooling"
        assert entry["guidance"]["state_class"] == "objective_evidence_missing"

    lowered = response.text.casefold()
    assert session_id not in lowered
    for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
        assert prohibited not in lowered


def test_publication_rejects_a_running_or_incompatible_run(tmp_path) -> None:
    database, session_id = _database_and_session(tmp_path)
    repository = database.session_analysis_run_repository()
    draft = _draft(session_id)
    repository.begin(draft)
    service = SessionMetricPublicationService(repository)

    with pytest.raises(SessionMetricPublicationError) as running:
        service.get(draft.run_id)
    assert running.value.code == "publication_run_not_completed"

    path = f"/v1/quality-analysis/runs/{RUN_ID}/metric-v2-compatibility-preview"
    with TestClient(_app(tmp_path, database), base_url="http://127.0.0.1") as client:
        conflict = client.get(path, headers={API_TOKEN_HEADER: EXAMPLE_TOKEN})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "completed quality analysis required"


def test_publication_is_read_only_and_leaves_stored_receipts_untouched(
    tmp_path,
) -> None:
    database, _ = _completed_run(tmp_path)
    repository = database.session_analysis_run_repository()

    def _snapshot() -> tuple[object, ...]:
        with sqlite3.connect(tmp_path / "metrics.sqlite3") as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT key, version, value_state, fraction_numerator,
                       fraction_denominator, explanation_code
                FROM session_analysis_results
                WHERE run_id = ?
                ORDER BY key, version
                """,
                (RUN_ID,),
            ).fetchall()
            runs = connection.execute(
                "SELECT status, finished_at FROM session_analysis_runs WHERE run_id = ?",
                (RUN_ID,),
            ).fetchall()
        return tuple(tuple(row) for row in rows) + tuple(tuple(row) for row in runs)

    before = _snapshot()
    first = SessionMetricPublicationService(repository).get(RUN_ID)
    second = SessionMetricPublicationService(repository).get(RUN_ID)
    after = _snapshot()

    assert before == after
    # A derived projection must be reproducible rather than a second record.
    assert first == second
    assert SCHEMA_VERSION == 61


def test_publication_adds_no_table_and_cannot_outlive_its_parent_run(
    tmp_path,
) -> None:
    """The projection is derived, so a privacy deletion needs no new cascade.

    Adding a persisted publication table would create a second lifetime that a
    privacy deletion has to reach.  Recomputing instead means the run's existing
    ``ON DELETE CASCADE`` is still the only path that has to be correct.
    """

    database, _ = _completed_run(tmp_path)
    repository = database.session_analysis_run_repository()
    assert SessionMetricPublicationService(repository).get(RUN_ID) is not None

    with sqlite3.connect(tmp_path / "metrics.sqlite3") as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        results_ddl = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'session_analysis_results'
            """
        ).fetchone()[0]
        cascade = connection.execute(
            "PRAGMA foreign_key_list(session_analysis_results)"
        ).fetchall()

    # The quality-analysis V1 compatibility preview remains derived.  A
    # separate canonical model-ensemble V2 sidecar has its own parent lifetime
    # and must not be mistaken for persistence of this preview.
    assert not any(
        name.startswith("session_analysis_")
        and ("metric_publication" in name or "metric_guidance" in name)
        for name in tables
    )
    assert "session_analysis_runs(run_id) ON DELETE CASCADE" in results_ddl
    assert any(
        row[2] == "session_analysis_runs" and row[6] == "CASCADE" for row in cascade
    )
    # An absent run yields no projection at all rather than an empty publication.
    assert SessionMetricPublicationService(repository).get("9" * 64) is None


def test_guidance_catalog_matches_the_openapi_documented_response(tmp_path) -> None:
    database, _ = _database_and_session(tmp_path)
    app = _app(tmp_path, database)
    schema = app.openapi()

    assert CATALOG_PATH in schema["paths"]
    assert OPERABILITY_CATALOG_PATH in schema["paths"]
    publication_path = (
        "/v1/quality-analysis/runs/{run_id}/metric-v2-compatibility-preview"
    )
    assert publication_path in schema["paths"]
    # The catalog is the client's single source for renderable identities.
    assert len(metric_guidance_catalog()) == 20


def test_malformed_and_tampered_publication_requests_are_rejected(tmp_path) -> None:
    database, _ = _completed_run(tmp_path)
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}

    with TestClient(_app(tmp_path, database), base_url="http://127.0.0.1") as client:
        short_id = client.get(
            "/v1/quality-analysis/runs/abc/metric-v2-compatibility-preview",
            headers=headers,
        )
        non_hex = client.get(
            f"/v1/quality-analysis/runs/{'z' * 64}/metric-v2-compatibility-preview",
            headers=headers,
        )
        traversal = client.get(
            "/v1/quality-analysis/runs/../../etc/passwd"
            "/metric-v2-compatibility-preview",
            headers=headers,
        )
        bad_token = client.get(
            f"/v1/quality-analysis/runs/{RUN_ID}/metric-v2-compatibility-preview",
            headers={API_TOKEN_HEADER: "example_wrong_token_000000000000000000"},
        )

    assert short_id.status_code == 422
    assert non_hex.status_code == 422
    assert traversal.status_code in {307, 404}
    assert bad_token.status_code == 401
    for response in (short_id, non_hex, bad_token):
        lowered = response.text.casefold()
        for prohibited in ("prompt_text", "excerpt", "filesystem_path", "raw_content"):
            assert prohibited not in lowered
