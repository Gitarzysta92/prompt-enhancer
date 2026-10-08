"""Fail-closed availability boundaries for the local model-judge lane."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
import threading

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.calibration_ratings import (
    CALIBRATION_METRIC_KEYS,
    CalibrationSampleEmptyError,
    RatingLabel,
)
from prompt_enhancer.application.analysis.model_judge import (
    JUDGE_PROMPT_VERSION,
    JUDGE_RETRY_PROMPT_VERSION,
    JudgeSweepStatus,
    MODEL_JUDGE_CATALOG_UNAVAILABLE,
    ModelJudgeError,
    ModelJudgeService,
    ModelJudgeSweepFailureCode,
    ModelJudgment,
    render_window,
)
from prompt_enhancer.application.analysis.calibration_cases import prepare_calibration_case
from prompt_enhancer.domain import Provider
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.model_judge_routes import (
    ModelJudgeFailureResponse,
    create_model_judge_router,
)


SESSION_ID = "a" * 64
WINDOW_FINGERPRINT = "b" * 64
TOKEN = "example_model_judge_availability_token_123456789"


def _synthetic_window(
    fingerprint: str = WINDOW_FINGERPRINT,
) -> SimpleNamespace:
    return SimpleNamespace(
        analysis_window_fingerprint=fingerprint,
        messages=(
            EphemeralRedactedMessage(
                message_id="c" * 64,
                sequence=0,
                role=TextRole.USER,
                kind=TextMessageKind.REQUEST,
                language=TextLanguage.ENGLISH,
                text=SecretStr("Review the synthetic fixture."),
            ),
        ),
    )


class _Repository:
    def __init__(self, rows: tuple[ModelJudgment, ...] = ()) -> None:
        self.rows = rows

    def upsert(self, judgment: ModelJudgment) -> None:
        self.rows = (*self.rows, judgment)

    def list(
        self, *, session_id: str | None = None, model_alias: str | None = None
    ) -> tuple[ModelJudgment, ...]:
        return tuple(
            row
            for row in self.rows
            if (session_id is None or row.session_id == session_id)
            and (model_alias is None or row.model_alias == model_alias)
        )


class _Ratings:
    def list_ratings(
        self, *, rater_id: str | None = None, session_id: str | None = None
    ) -> tuple[object, ...]:
        del rater_id, session_id
        return ()


class _SweepService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def start_sweep(self, session_ids: tuple[str, ...]) -> JudgeSweepStatus:
        self.calls.append(session_ids)
        return JudgeSweepStatus(
            running=False,
            total=len(session_ids),
            done=0,
            failed=0,
        )

    def sweep_status(self) -> JudgeSweepStatus:
        return JudgeSweepStatus(running=False, total=0, done=0, failed=0)


class _JudgeFailureService:
    def __init__(self, code: str) -> None:
        self.code = code

    def judge(self, _session_id: str):
        raise ModelJudgeError(self.code)


class _ContextualFailureService:
    @staticmethod
    def _raise(code: str):
        try:
            raise RuntimeError("SYNTHETIC_PRIVATE_CONTEXT_CANARY")
        except RuntimeError:
            raise ModelJudgeError(code)

    def judgments_for(self, _session_id: str):
        self._raise(MODEL_JUDGE_CATALOG_UNAVAILABLE)

    def interpret(self, _session_id: str):
        self._raise("model_error")

    def judge(self, _session_id: str):
        self._raise("model_error")

    def start_sweep(self, _session_ids: tuple[str, ...]):
        self._raise(MODEL_JUDGE_CATALOG_UNAVAILABLE)

    def agreement(self):
        self._raise(MODEL_JUDGE_CATALOG_UNAVAILABLE)


class _Store:
    def initialize(self) -> None:
        return None


def _app(
    service: object,
    *,
    sample_session_ids=lambda: (),
    all_session_ids=None,
) -> FastAPI:
    app = FastAPI()

    def allow_local_request() -> None:
        return None

    app.include_router(
        create_model_judge_router(
            allow_local_request,
            cast(ModelJudgeService, service),
            sample_session_ids,
            all_session_ids,
        )
    )
    return app


def _client(
    service: object,
    *,
    sample_session_ids=lambda: (),
    all_session_ids=None,
) -> TestClient:
    return TestClient(
        _app(
            service,
            sample_session_ids=sample_session_ids,
            all_session_ids=all_session_ids,
        ),
        base_url="http://127.0.0.1",
    )


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


def _judge_service(active_model, rows: tuple[ModelJudgment, ...] = ()) -> ModelJudgeService:
    return ModelJudgeService(
        repository=_Repository(rows),
        ratings=_Ratings(),
        access=object(),
        source_factory=lambda _provider: object(),
        chat=lambda _alias, _body: (500, b"{}", "application/json"),
        active_model=active_model,
        session_lookup=lambda _session_id: None,
    )


def _stored_judgments(
    *,
    keys: tuple[str, ...] = CALIBRATION_METRIC_KEYS,
    model_identity: str = "synthetic-model.gguf",
    prompt_version: str = JUDGE_PROMPT_VERSION,
    window_fingerprint: str = WINDOW_FINGERPRINT,
) -> tuple[ModelJudgment, ...]:
    return tuple(
        ModelJudgment(
            session_id=SESSION_ID,
            metric_key=key,
            label=RatingLabel.HIGH,
            model_alias="synthetic-model",
            model_identity=model_identity,
            prompt_version=prompt_version,
            window_fingerprint=window_fingerprint,
            judged_at=datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
            case_version="calibration-case.v1",
            case_fingerprint=prepare_calibration_case(
                session_id=SESSION_ID, provider=Provider.CODEX, window_fingerprint=window_fingerprint,
                rendered_window=render_window(_synthetic_window(window_fingerprint)),
            ).case_fingerprint,
        )
        for key in keys
    )


def _freshness_service(
    rows: tuple[ModelJudgment, ...],
    *,
    active_identity: str = "synthetic-model.gguf",
    current_fingerprint: str = WINDOW_FINGERPRINT,
) -> tuple[ModelJudgeService, list[str]]:
    service = ModelJudgeService(
        repository=_Repository(rows),
        ratings=_Ratings(),
        access=object(),
        source_factory=lambda _provider: object(),
        chat=lambda _alias, _body: (500, b"{}", "application/json"),
        active_model=lambda: ("synthetic-model", active_identity),
        session_lookup=lambda _session_id: SimpleNamespace(provider="codex"),
    )
    window_calls: list[str] = []

    def current_window(_provider, session_id):  # type: ignore[no-untyped-def]
        window_calls.append(session_id)
        return _synthetic_window(current_fingerprint)

    service._window = current_window  # type: ignore[method-assign]  # noqa: SLF001
    service.judge = (  # type: ignore[method-assign]
        lambda _session_id: SimpleNamespace(raw_valid=True)
    )
    return service, window_calls


def _wait_for_finished_sweep(service: ModelJudgeService) -> JudgeSweepStatus:
    for _ in range(100):
        status = service.sweep_status()
        if not status.running:
            return status
        threading.Event().wait(0.01)
    raise AssertionError("synthetic model-judge sweep did not finish")


@pytest.mark.parametrize(
    "prompt_version", (JUDGE_PROMPT_VERSION, JUDGE_RETRY_PROMPT_VERSION)
)
def test_sweep_accepts_only_complete_matching_current_judgment_sets(
    prompt_version: str,
) -> None:
    service, window_calls = _freshness_service(
        _stored_judgments(prompt_version=prompt_version)
    )

    status = service.start_sweep((SESSION_ID,))

    assert status.total == 0
    assert status.running is False
    assert window_calls == [SESSION_ID]


@pytest.mark.parametrize(
    ("rows", "current_fingerprint"),
    [
        (_stored_judgments(keys=CALIBRATION_METRIC_KEYS[:-1]), WINDOW_FINGERPRINT),
        (
            _stored_judgments(model_identity="superseded-model.gguf"),
            WINDOW_FINGERPRINT,
        ),
        (_stored_judgments(window_fingerprint="d" * 64), WINDOW_FINGERPRINT),
        (_stored_judgments(prompt_version="judge-v3-untrusted-json-anchor-15k"), WINDOW_FINGERPRINT),
        (_stored_judgments(prompt_version="judge-v3-untrusted-json-anchor-6k"), WINDOW_FINGERPRINT),
    ],
    ids=("partial-keys", "changed-identity", "changed-window", "unchecked-main-protocol", "unchecked-retry-protocol"),
)
def test_sweep_rejudges_partial_identity_or_window_mismatches(
    rows: tuple[ModelJudgment, ...], current_fingerprint: str
) -> None:
    service, _window_calls = _freshness_service(
        rows, current_fingerprint=current_fingerprint
    )

    launched = service.start_sweep((SESSION_ID,))
    finished = _wait_for_finished_sweep(service)

    assert launched.total == 1
    assert finished.done == 1
    assert finished.failed == 0


def test_sweep_window_freshness_failure_uses_closed_worker_accounting() -> None:
    service = ModelJudgeService(
        repository=_Repository(_stored_judgments()),
        ratings=_Ratings(),
        access=object(),
        source_factory=lambda _provider: object(),
        chat=lambda _alias, _body: (_ for _ in ()).throw(
            AssertionError("chat must not run without a window")
        ),
        active_model=lambda: ("synthetic-model", "synthetic-model.gguf"),
        session_lookup=lambda _session_id: SimpleNamespace(provider="codex"),
    )
    service._window = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda _provider, _session_id: (_ for _ in ()).throw(
            ModelJudgeError("window_unavailable")
        )
    )

    launched = service.start_sweep((SESSION_ID,))
    finished = _wait_for_finished_sweep(service)

    assert launched.total == 1
    assert finished.done == 1
    assert finished.failed == 1
    assert finished.last_error_code is ModelJudgeSweepFailureCode.WINDOW_UNAVAILABLE


def test_sample_catalog_failure_is_typed_and_never_starts_a_sweep() -> None:
    service = _SweepService()

    def unavailable_sample() -> tuple[str, ...]:
        raise RuntimeError("synthetic private failure detail")

    response = _client(service, sample_session_ids=unavailable_sample).post(
        "/v1/model-judge/sweep"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": MODEL_JUDGE_CATALOG_UNAVAILABLE}
    }
    ModelJudgeFailureResponse.model_validate(response.json())
    assert "private failure detail" not in response.text
    assert service.calls == []


@pytest.mark.parametrize("scope", ["sample", "all"])
def test_composed_app_does_not_convert_supplier_failure_to_empty(
    tmp_path: Path,
    scope: str,
) -> None:
    service = _SweepService()

    def unavailable() -> tuple[str, ...]:
        raise RuntimeError("synthetic private composed catalog detail")

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=_Store(),
        api_token=TOKEN,
        model_judge_service=cast(ModelJudgeService, service),
        calibration_sample_session_ids=unavailable,
        all_session_ids=unavailable,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            f"/v1/model-judge/sweep?scope={scope}",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": MODEL_JUDGE_CATALOG_UNAVAILABLE}
    }
    ModelJudgeFailureResponse.model_validate(response.json())
    assert "private composed catalog detail" not in response.text
    assert service.calls == []


def test_missing_all_catalog_never_falls_back_to_the_sample() -> None:
    service = _SweepService()
    sample_calls = 0

    def sample() -> tuple[str, ...]:
        nonlocal sample_calls
        sample_calls += 1
        return (SESSION_ID,)

    response = _client(service, sample_session_ids=sample).post(
        "/v1/model-judge/sweep?scope=all"
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": MODEL_JUDGE_CATALOG_UNAVAILABLE}
    }
    ModelJudgeFailureResponse.model_validate(response.json())
    assert sample_calls == 0
    assert service.calls == []


@pytest.mark.parametrize(
    "sample_session_ids",
    [
        lambda: (),
        lambda: (_ for _ in ()).throw(
            CalibrationSampleEmptyError("no indexed session to sample")
        ),
    ],
)
def test_a_known_empty_sample_remains_a_valid_zero_scope(
    sample_session_ids,
) -> None:
    service = _SweepService()

    response = _client(service, sample_session_ids=sample_session_ids).post(
        "/v1/model-judge/sweep"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert service.calls == [()]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"/v1/model-judge/sessions/{SESSION_ID}"),
        ("POST", f"/v1/model-judge/sessions/{SESSION_ID}/interpret"),
        ("POST", "/v1/model-judge/sweep"),
        ("GET", f"/v1/model-judge/sessions/{SESSION_ID}"),
        ("GET", "/v1/model-judge/agreement"),
    ],
)
def test_active_model_catalog_failure_is_a_content_free_503(
    method: str, path: str
) -> None:
    def unavailable_active_model() -> tuple[str, str] | None:
        raise RuntimeError("synthetic private model catalog detail")

    response = _client(
        _judge_service(unavailable_active_model),
        sample_session_ids=lambda: (SESSION_ID,),
    ).request(method, path)

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": MODEL_JUDGE_CATALOG_UNAVAILABLE}
    }
    ModelJudgeFailureResponse.model_validate(response.json())
    assert "private model catalog detail" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/model-judge/sessions/{SESSION_ID}",
        f"/v1/model-judge/sessions/{SESSION_ID}/interpret",
        "/v1/model-judge/sweep",
    ],
)
def test_a_readable_catalog_with_no_running_model_remains_a_409(path: str) -> None:
    response = _client(
        _judge_service(lambda: None), sample_session_ids=lambda: (SESSION_ID,)
    ).post(path)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "no_active_model"}}
    ModelJudgeFailureResponse.model_validate(response.json())


@pytest.mark.parametrize(
    ("source_code", "expected_status", "expected_code"),
    [
        ("no_active_model", 409, "no_active_model"),
        ("session_not_found", 404, "session_not_found"),
        ("consent_required", 403, "consent_required"),
        ("window_unavailable", 409, "window_unavailable"),
        ("model_unreachable", 502, "model_unreachable"),
        ("model_not_active", 409, "model_not_active"),
        ("model_error", 502, "model_error"),
        ("model_reply_invalid", 502, "model_reply_invalid"),
        (
            MODEL_JUDGE_CATALOG_UNAVAILABLE,
            503,
            MODEL_JUDGE_CATALOG_UNAVAILABLE,
        ),
        ("runtime_unreachable", 502, "model_unreachable"),
        ("SYNTHETIC_PRIVATE_ERROR_CODE", 502, "model_error"),
    ],
)
def test_judge_failure_bodies_are_closed_and_content_free(
    source_code: str,
    expected_status: int,
    expected_code: str,
) -> None:
    response = _client(_JudgeFailureService(source_code)).post(
        f"/v1/model-judge/sessions/{SESSION_ID}"
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": {"code": expected_code}}
    ModelJudgeFailureResponse.model_validate(response.json())
    assert "SYNTHETIC_PRIVATE" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"detail": {"code": "example_unknown_failure"}},
        {
            "detail": {
                "code": "model_error",
                "private_context": "example forbidden field",
            }
        },
        {
            "detail": {"code": "model_error"},
            "private_context": "example forbidden field",
        },
    ],
)
def test_model_judge_failure_contract_rejects_unknown_and_extra_fields(body) -> None:
    with pytest.raises(ValidationError):
        ModelJudgeFailureResponse.model_validate(body)


def test_openapi_documents_only_reachable_model_judge_failures() -> None:
    schema = _app(_SweepService()).openapi()
    expected = {
        ("/v1/model-judge/sessions/{session_id}", "get"): {503},
        ("/v1/model-judge/sessions/{session_id}", "post"): {
            403,
            404,
            409,
            502,
            503,
        },
        ("/v1/model-judge/sessions/{session_id}/interpret", "post"): {
            403,
            404,
            409,
            502,
            503,
        },
        ("/v1/model-judge/sweep", "post"): {409, 503},
        ("/v1/model-judge/sweep", "get"): set(),
        ("/v1/model-judge/agreement", "get"): {503},
    }
    failure_ref = "#/components/schemas/ModelJudgeFailureResponse"

    for (path, method), expected_statuses in expected.items():
        documented_statuses: set[int] = set()
        for status, response in schema["paths"][path][method]["responses"].items():
            response_schema = (
                response.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if failure_ref in _schema_references(response_schema):
                documented_statuses.add(int(status))
        assert documented_statuses == expected_statuses, (path, method)


@pytest.mark.parametrize(
    ("path", "method", "kwargs", "expected_status", "expected_code"),
    [
        (
            "/v1/model-judge/sessions/{session_id}",
            "GET",
            {"session_id": SESSION_ID},
            503,
            MODEL_JUDGE_CATALOG_UNAVAILABLE,
        ),
        (
            "/v1/model-judge/sessions/{session_id}/interpret",
            "POST",
            {"session_id": SESSION_ID},
            502,
            "model_error",
        ),
        (
            "/v1/model-judge/sessions/{session_id}",
            "POST",
            {"session_id": SESSION_ID},
            502,
            "model_error",
        ),
        (
            "/v1/model-judge/sweep",
            "POST",
            {"scope": "sample"},
            503,
            MODEL_JUDGE_CATALOG_UNAVAILABLE,
        ),
        (
            "/v1/model-judge/agreement",
            "GET",
            {},
            503,
            MODEL_JUDGE_CATALOG_UNAVAILABLE,
        ),
    ],
)
def test_route_failure_has_no_private_exception_context(
    path: str,
    method: str,
    kwargs: dict[str, object],
    expected_status: int,
    expected_code: str,
) -> None:
    router = create_model_judge_router(
        lambda: None,
        cast(ModelJudgeService, _ContextualFailureService()),
        lambda: (SESSION_ID,),
    )
    route = next(
        candidate
        for candidate in router.routes
        if isinstance(candidate, APIRoute)
        and candidate.path == path
        and method in candidate.methods
    )

    with pytest.raises(HTTPException) as caught:
        route.endpoint(**kwargs)

    assert caught.value.status_code == expected_status
    assert caught.value.detail == {"code": expected_code}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE_CONTEXT_CANARY" not in str(caught.value.detail)


def test_explicit_alias_reads_do_not_require_the_active_model_catalog() -> None:
    active_calls = 0

    def unavailable_active_model() -> tuple[str, str] | None:
        nonlocal active_calls
        active_calls += 1
        raise RuntimeError("synthetic unavailable")

    stored = ModelJudgment(
        session_id=SESSION_ID,
        metric_key="prompt.task_definition_coverage",
        label=RatingLabel.HIGH,
        model_alias="stored-model",
        model_identity="synthetic.gguf",
        prompt_version="judge-v1",
        window_fingerprint=WINDOW_FINGERPRINT,
        judged_at=datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
    )
    service = _judge_service(unavailable_active_model, (stored,))

    assert service.judged_model_aliases() == ("stored-model",)
    report = service.agreement("stored-model")

    assert report.model_alias == "stored-model"
    assert report.judged_sessions == 0
    assert report.excluded_judgments == 1
    assert active_calls == 0


def test_bootstrap_does_not_turn_an_overview_failure_into_no_active_model(
    tmp_path: Path,
) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))

    class UnavailableModels:
        def overview(self):
            raise RuntimeError("synthetic private overview failure")

        def chat(self, _alias: str, _body: bytes):
            raise AssertionError("chat must not run")

    service, _ = application.create_model_judge_service(UnavailableModels())

    with pytest.raises(ModelJudgeError) as caught:
        service.agreement()

    assert caught.value.code == MODEL_JUDGE_CATALOG_UNAVAILABLE
    assert str(caught.value) == MODEL_JUDGE_CATALOG_UNAVAILABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    ("adapter_code", "expected_code"),
    [
        (
            "runtime_unreachable",
            ModelJudgeSweepFailureCode.MODEL_UNREACHABLE,
        ),
        (
            "SYNTHETIC_PRIVATE_ASYNC_ADAPTER_CANARY",
            ModelJudgeSweepFailureCode.MODEL_ERROR,
        ),
    ],
)
def test_async_adapter_error_codes_are_closed_before_public_sweep_status(
    adapter_code: str,
    expected_code: ModelJudgeSweepFailureCode,
) -> None:
    adapter_called = threading.Event()

    class AdapterFailure(RuntimeError):
        def __init__(self) -> None:
            super().__init__("SYNTHETIC_PRIVATE_ASYNC_ADAPTER_DETAIL")
            self.code = adapter_code

    def failing_chat(_alias: str, _body: bytes):
        adapter_called.set()
        raise AdapterFailure

    service = ModelJudgeService(
        repository=_Repository(),
        ratings=_Ratings(),
        access=object(),
        source_factory=lambda _provider: object(),
        chat=failing_chat,
        active_model=lambda: ("synthetic-model", "synthetic-model.gguf"),
        session_lookup=lambda _session_id: SimpleNamespace(provider="codex"),
    )
    service._window = (  # type: ignore[method-assign]  # noqa: SLF001
        lambda _provider, _session_id: _synthetic_window()
    )

    service.start_sweep((SESSION_ID,))
    assert adapter_called.wait(timeout=1)
    status = _wait_for_finished_sweep(service)

    assert status.last_error_code is expected_code
    assert "SYNTHETIC_PRIVATE" not in str(status.model_dump(mode="json"))


def test_sweep_status_rejects_non_public_error_codes() -> None:
    with pytest.raises(ValidationError):
        JudgeSweepStatus(
            running=False,
            total=1,
            done=1,
            failed=1,
            last_error_code="SYNTHETIC_PRIVATE_ASYNC_ADAPTER_CANARY",
        )


def test_sweep_thread_start_failure_is_atomic_content_free_and_restartable(
    monkeypatch,
) -> None:
    service = _judge_service(
        lambda: ("synthetic-model", "synthetic-model.gguf")
    )
    original_start = threading.Thread.start

    def failing_start(_thread: threading.Thread) -> None:
        raise RuntimeError("SYNTHETIC_PRIVATE_THREAD_START_CANARY")

    monkeypatch.setattr(threading.Thread, "start", failing_start)
    with pytest.raises(ModelJudgeError) as caught:
        service.start_sweep((SESSION_ID,))

    failed = service.sweep_status()
    assert caught.value.code == "model_error"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert failed.running is False
    assert failed.last_error_code is ModelJudgeSweepFailureCode.JUDGE_FAILED
    assert "SYNTHETIC_PRIVATE" not in str(failed.model_dump(mode="json"))

    monkeypatch.setattr(threading.Thread, "start", original_start)
    service.judge = (  # type: ignore[method-assign]
        lambda _session_id: SimpleNamespace(raw_valid=True)
    )
    service.start_sweep((SESSION_ID,))
    restarted = _wait_for_finished_sweep(service)
    assert restarted.done == 1
    assert restarted.failed == 0
    assert restarted.last_error_code is None
