from __future__ import annotations

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database, DatabaseInvariantError

from test_estimator_contracts import synthetic_plan


TOKEN = "example_model_lab_token_do_not_use_123456789"

ROOT_KEYS = {
    "contract_version",
    "scope",
    "session_data_read",
    "private_evidence_returned",
    "registered_plan_count",
    "synthetic_execution_count",
    "model_run_count",
    "model_vote_count",
    "metric_estimate_count",
    "activation_outcome",
    "activation_allowed",
    "plans",
}
PLAN_KEYS = {
    "plan_fingerprint",
    "plan_key",
    "plan_version",
    "route",
    "metric_question_count",
    "synthetic_execution_count",
    "model_run_count",
    "model_vote_count",
    "metric_estimate_count",
    "activation_outcome",
    "activation_allowed",
}


def test_model_lab_inventory_is_authenticated_get_only_and_private_no_store(
    tmp_path,
) -> None:
    database = Database(tmp_path / "model-lab.sqlite3")
    repository = database.estimator_repository()
    repository.register_plan(synthetic_plan())
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=database,
        api_token=TOKEN,
        estimator_repository=repository,
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    with client:
        unauthorized = client.get("/v1/estimators/plans")
        response = client.get(
            "/v1/estimators/plans",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        mutation = client.post(
            "/v1/estimators/plans",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert mutation.status_code == 405
    body = response.json()
    assert set(body) == ROOT_KEYS
    assert len(body["plans"]) == 1
    assert set(body["plans"][0]) == PLAN_KEYS
    assert body["scope"] == "synthetic_only"
    assert body["session_data_read"] is False
    assert body["private_evidence_returned"] is False
    assert body["activation_allowed"] is False
    serialized = response.text.casefold()
    for forbidden in (
        "session_id",
        "project_id",
        "case_id",
        "execution_id",
        "evidence_ref",
        "provider",
        "model_id",
        "commentary",
    ):
        assert forbidden not in serialized


def test_model_lab_openapi_is_closed_and_has_no_activation_mutation(tmp_path) -> None:
    database = Database(tmp_path / "schema.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "schema-home"),
        database=database,
        api_token=TOKEN,
        estimator_repository=database.estimator_repository(),
    )
    schema = app.openapi()

    operations = schema["paths"]["/v1/estimators/plans"]
    assert set(operations) == {"get"}
    schemas = schema["components"]["schemas"]
    inventory = schemas["ModelLabInventoryDto"]
    plan = schemas["ModelLabPlanSummaryDto"]
    assert inventory["additionalProperties"] is False
    assert plan["additionalProperties"] is False
    assert set(inventory["properties"]) == ROOT_KEYS
    assert set(plan["properties"]) == PLAN_KEYS
    assert inventory["properties"]["activation_allowed"]["const"] is False
    assert inventory["properties"]["session_data_read"]["const"] is False
    assert inventory["properties"]["private_evidence_returned"]["const"] is False


def test_empty_http_inventory_returns_verified_zeros_not_unknown(tmp_path) -> None:
    database = Database(tmp_path / "empty-http.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "empty-http-home"),
        database=database,
        api_token=TOKEN,
        estimator_repository=database.estimator_repository(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/estimators/plans", headers={API_TOKEN_HEADER: TOKEN}
        )

    assert response.status_code == 200
    assert response.json() == {
        "contract_version": "model-lab-inventory-v1",
        "scope": "synthetic_only",
        "session_data_read": False,
        "private_evidence_returned": False,
        "registered_plan_count": 0,
        "synthetic_execution_count": 0,
        "model_run_count": 0,
        "model_vote_count": 0,
        "metric_estimate_count": 0,
        "activation_outcome": "synthetic_or_insufficient",
        "activation_allowed": False,
        "plans": [],
    }


def test_repository_failure_is_sanitized_private_unknown_not_zero(tmp_path) -> None:
    class FailingRepository:
        def model_lab_inventory(self):
            raise RuntimeError("synthetic-private-canary")

    database = Database(tmp_path / "failure.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "failure-home"),
        database=database,
        api_token=TOKEN,
        estimator_repository=FailingRepository(),  # type: ignore[arg-type]
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    with client:
        response = client.get(
            "/v1/estimators/plans",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "detail": {"code": "model_lab_inventory_unavailable"}
    }
    assert "synthetic-private-canary" not in response.text
    assert "registered_plan_count" not in response.text


def test_plan_overflow_maps_to_unavailable_never_an_empty_inventory(tmp_path) -> None:
    class OverflowRepository:
        def model_lab_inventory(self):
            raise DatabaseInvariantError(
                "model lab plan inventory exceeds its safe bound"
            )

    database = Database(tmp_path / "overflow.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path / "overflow-home"),
        database=database,
        api_token=TOKEN,
        estimator_repository=OverflowRepository(),  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/estimators/plans", headers={API_TOKEN_HEADER: TOKEN}
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "model_lab_inventory_unavailable"}
    }
    assert "registered_plan_count" not in response.text
