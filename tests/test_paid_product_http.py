"""HTTP boundary tests for the default-off paid-product readiness surface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.paid_product.contracts import (
    DEVELOPMENT_PRODUCT_READINESS,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.interfaces.http.paid_product_routes import (
    create_paid_product_readiness_router,
)


TOKEN = "fictional-local-test-token"


def app() -> FastAPI:
    application = FastAPI()

    def require_token(x_api_token: str | None = Header(default=None)) -> None:
        if x_api_token != TOKEN:
            raise HTTPException(status_code=401, detail="authentication required")

    application.include_router(
        create_paid_product_readiness_router(
            require_token, DEVELOPMENT_PRODUCT_READINESS
        )
    )
    return application


def test_readiness_requires_local_auth_and_is_private() -> None:
    client = TestClient(app())
    denied = client.get("/v1/paid-product/readiness")
    assert denied.status_code == 401
    response = client.get(
        "/v1/paid-product/readiness", headers={"X-Api-Token": TOKEN}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == DEVELOPMENT_PRODUCT_READINESS.model_dump(mode="json")
    assert response.json()["production_ready"] is False
    assert response.json()["remote_transport_enabled"] is False


def test_readiness_schema_has_no_identity_billing_or_job_mutations() -> None:
    schema = app().openapi()
    assert set(schema["paths"]) == {"/v1/paid-product/readiness"}
    assert set(schema["paths"]["/v1/paid-product/readiness"]) == {"get"}
    serialized = str(schema)
    assert "approved_payload" not in serialized
    assert "SignedBillingWebhook" not in serialized
    assert "DeepAnalysisRequest" not in serialized


def test_main_api_requires_both_exact_opt_in_and_composed_readiness(
    tmp_path: Path,
) -> None:
    token = "t" * 32

    def client(*, enabled: bool, composed: bool) -> TestClient:
        settings = AppSettings(
            home=tmp_path,
            paid_product_development_api=enabled,
        )
        return TestClient(
            create_app(
                settings=settings,
                database=Database(tmp_path / f"metrics-{enabled}-{composed}.sqlite3"),
                api_token=token,
                paid_product_readiness=(
                    DEVELOPMENT_PRODUCT_READINESS if composed else None
                ),
            ),
            base_url="http://127.0.0.1:8765",
        )

    headers = {API_TOKEN_HEADER: token}
    assert client(enabled=False, composed=True).get(
        "/v1/paid-product/readiness", headers=headers
    ).status_code == 404
    assert client(enabled=True, composed=False).get(
        "/v1/paid-product/readiness", headers=headers
    ).status_code == 404
    response = client(enabled=True, composed=True).get(
        "/v1/paid-product/readiness", headers=headers
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"


def test_paid_product_environment_opt_in_is_exact(tmp_path: Path) -> None:
    common = {
        "PROMPT_ENHANCER_HOME": str(tmp_path),
        "PROMPT_ENHANCER_PAID_PRODUCT_DEV_API": "true",
    }
    assert AppSettings.from_env(common).paid_product_development_api is False
    assert (
        AppSettings.from_env(
            {**common, "PROMPT_ENHANCER_PAID_PRODUCT_DEV_API": "enabled"}
        ).paid_product_development_api
        is True
    )
