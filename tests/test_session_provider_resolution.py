"""Exact session-provider routing: no missing or unavailable Codex fallback."""

from __future__ import annotations

from inspect import Parameter, signature
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from prompt_enhancer.api import (
    API_TOKEN_HEADER,
    _resolve_session_provider,
    create_app,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    MODEL_ENSEMBLE_CONFIRMATION,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import Provider
from prompt_enhancer.interfaces.http.declared_task_profile_routes import (
    create_declared_task_profile_router,
)
from prompt_enhancer.interfaces.http.model_ensemble_routes import (
    create_model_ensemble_router,
)
from prompt_enhancer.interfaces.http.model_ensemble_watch_routes import (
    create_model_ensemble_watch_router,
)
from prompt_enhancer.interfaces.http.model_link_experiment_routes import (
    create_model_link_experiment_router,
)
from prompt_enhancer.interfaces.http.session_analysis_command_routes import (
    create_session_analysis_command_router,
)
from prompt_enhancer.interfaces.http.session_provider_contracts import (
    SessionProviderFailureResponse,
)


TOKEN = "example_provider_resolution_token_123456789"
SESSION_ID = "a" * 64


class _Catalog:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def initialize(self) -> None:
        return None

    def get_session(self, _session_id: str):
        if self.error is not None:
            raise self.error
        return self.result


class _NeverCalledEnsemble:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, **_kwargs):
        self.calls += 1
        raise AssertionError("service must not run without an exact catalog row")

    def latest(self, _session_id: str):
        return None


class _ExplodingProviderAttribute:
    @property
    def provider(self) -> str:
        raise RuntimeError("SYNTHETIC_PRIVATE_ATTRIBUTE_CANARY")


class _ExplodingProviderMapping(dict[str, object]):
    def get(self, key, default=None):
        raise RuntimeError("SYNTHETIC_PRIVATE_MAPPING_CANARY")


def _schema_references(value) -> set[str]:
    if isinstance(value, dict):
        references = {
            item for key, item in value.items() if key == "$ref" and isinstance(item, str)
        }
        for item in value.values():
            references.update(_schema_references(item))
        return references
    if isinstance(value, list):
        references: set[str] = set()
        for item in value:
            references.update(_schema_references(item))
        return references
    return set()


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (SimpleNamespace(provider=Provider.CODEX), Provider.CODEX),
        ({"provider": "claude_code"}, Provider.CLAUDE_CODE),
        ({"provider": "synthetic"}, Provider.SYNTHETIC),
    ],
)
def test_exact_catalog_provider_is_preserved(record, expected: Provider) -> None:
    assert _resolve_session_provider(_Catalog(record), SESSION_ID) is expected


@pytest.mark.parametrize(
    ("catalog", "status", "code"),
    [
        (_Catalog(None), 404, "session_not_found"),
        (
            _Catalog(error=RuntimeError("SYNTHETIC_PRIVATE_CANARY")),
            503,
            "session_catalog_unavailable",
        ),
        (
            _Catalog(_ExplodingProviderAttribute()),
            503,
            "session_catalog_unavailable",
        ),
        (
            _Catalog(_ExplodingProviderMapping()),
            503,
            "session_catalog_unavailable",
        ),
        (_Catalog({"provider": "invalid"}), 503, "session_catalog_unavailable"),
    ],
)
def test_missing_unavailable_and_malformed_catalogs_fail_closed(
    catalog: _Catalog,
    status: int,
    code: str,
) -> None:
    with pytest.raises(HTTPException) as caught:
        _resolve_session_provider(catalog, SESSION_ID)
    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(caught.value.detail)


@pytest.mark.parametrize(
    "record",
    [_ExplodingProviderAttribute(), _ExplodingProviderMapping()],
    ids=["attribute", "mapping"],
)
def test_broken_provider_accessors_are_sanitized_without_exception_context(
    record,
) -> None:
    with pytest.raises(HTTPException) as caught:
        _resolve_session_provider(_Catalog(record), SESSION_ID)

    assert caught.value.status_code == 503
    assert caught.value.detail == {
        "code": "session_catalog_unavailable",
        "message": "session catalog is unavailable",
    }
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE" not in str(caught.value.detail)


@pytest.mark.parametrize(
    "factory",
    [
        create_session_analysis_command_router,
        create_model_link_experiment_router,
        create_model_ensemble_router,
        create_model_ensemble_watch_router,
        create_declared_task_profile_router,
    ],
)
def test_every_session_command_router_requires_a_provider_resolver(factory) -> None:
    parameter = signature(factory).parameters["provider_resolver"]
    assert parameter.default is Parameter.empty


@pytest.mark.parametrize(
    "body",
    [
        {
            "detail": {
                "code": "session_not_found",
                "message": "session catalog is unavailable",
            }
        },
        {
            "detail": {
                "code": "example_unknown_failure",
                "message": "session catalog is unavailable",
            }
        },
        {
            "detail": {
                "code": "session_catalog_unavailable",
                "message": "session catalog is unavailable",
                "private_context": "example forbidden field",
            }
        },
    ],
)
def test_shared_provider_failure_contract_is_closed(body) -> None:
    with pytest.raises(ValidationError):
        SessionProviderFailureResponse.model_validate(body)


def test_every_provider_resolved_operation_documents_the_shared_failure_contract(
    tmp_path,
) -> None:
    service = object()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=_Catalog(None),
        api_token=TOKEN,
        declared_task_profile_service=service,  # type: ignore[arg-type]
        session_text_analysis_service=service,  # type: ignore[arg-type]
        session_model_link_experiment_service=service,  # type: ignore[arg-type]
        session_model_ensemble_service=service,  # type: ignore[arg-type]
        model_ensemble_watch_service=service,  # type: ignore[arg-type]
    )
    schema = app.openapi()
    operations = (
        ("/v1/sessions/{session_id}/quality-analysis-previews", "post"),
        ("/v1/sessions/{session_id}/quality-analysis-runs", "post"),
        ("/v1/sessions/{session_id}/model-link-experiments", "post"),
        ("/v1/sessions/{session_id}/model-ensemble-runs", "post"),
        ("/v1/sessions/{session_id}/model-ensemble-watch", "put"),
        ("/v1/sessions/{session_id}/declared-task-profile", "get"),
        ("/v1/sessions/{session_id}/declared-task-profile", "post"),
    )
    expected_ref = "#/components/schemas/SessionProviderFailureResponse"

    for path, method in operations:
        responses = schema["paths"][path][method]["responses"]
        for status in ("404", "503"):
            response_schema = responses[status]["content"]["application/json"][
                "schema"
            ]
            assert expected_ref in _schema_references(response_schema), (
                path,
                method,
                status,
            )


@pytest.mark.parametrize(
    ("catalog", "expected_status", "expected_code"),
    [
        (_Catalog(None), 404, "session_not_found"),
        (
            _Catalog(error=RuntimeError("SYNTHETIC_PRIVATE_CANARY")),
            503,
            "session_catalog_unavailable",
        ),
        (
            _Catalog(_ExplodingProviderAttribute()),
            503,
            "session_catalog_unavailable",
        ),
        (
            _Catalog(_ExplodingProviderMapping()),
            503,
            "session_catalog_unavailable",
        ),
    ],
)
def test_http_boundary_never_calls_service_without_exact_provider(
    tmp_path,
    catalog: _Catalog,
    expected_status: int,
    expected_code: str,
) -> None:
    service = _NeverCalledEnsemble()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=catalog,
        api_token=TOKEN,
        session_model_ensemble_service=service,  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            f"/v1/sessions/{SESSION_ID}/model-ensemble-runs",
            json={"confirmation": MODEL_ENSEMBLE_CONFIRMATION},
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "example-provider-resolution-1",
            },
        )

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    SessionProviderFailureResponse.model_validate(response.json())
    assert response.headers["cache-control"] == "no-store, private"
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert service.calls == 0
