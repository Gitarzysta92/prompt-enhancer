"""Failure-atomic application workers and content-free runtime liveness."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.config import AppSettings


TOKEN = "example_runtime_liveness_token_123456789"


class _Store:
    def initialize(self) -> None:
        return None


class _Worker:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:
        self.name = name
        self.events = events
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.alive = False
        self.liveness_error = False

    def start(self) -> None:
        self.events.append(f"start:{self.name}")
        self.alive = True
        if self.fail_start:
            raise RuntimeError("SYNTHETIC_PRIVATE_START_CANARY")

    def stop(self) -> None:
        self.events.append(f"stop:{self.name}")
        self.alive = False
        if self.fail_stop:
            raise RuntimeError("SYNTHETIC_PRIVATE_STOP_CANARY")

    def is_alive(self) -> bool:
        if self.liveness_error:
            raise RuntimeError("SYNTHETIC_PRIVATE_LIVENESS_CANARY")
        return self.alive


class _Models:
    def __init__(self, events: list[str], *, fail_shutdown: bool = False) -> None:
        self.events = events
        self.fail_shutdown = fail_shutdown

    def shutdown(self) -> None:
        self.events.append("shutdown:models")
        if self.fail_shutdown:
            raise RuntimeError("SYNTHETIC_PRIVATE_MODEL_SHUTDOWN_CANARY")


def _app(tmp_path, workers: list[_Worker], models: _Models, updater=None):
    return create_app(
        settings=AppSettings(home=tmp_path),
        database=_Store(),
        api_token=TOKEN,
        analysis_job_worker=workers[0],  # type: ignore[arg-type]
        automation_grant_worker=workers[1],  # type: ignore[arg-type]
        model_ensemble_watch_worker=workers[2],  # type: ignore[arg-type]
        local_source_refresh_worker=workers[3],
        local_model_service=models,
        application_update_service=updater,
    )


def test_start_failure_rolls_back_current_and_prior_workers_then_models(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events, fail_stop=True),
        _Worker("automation", events, fail_start=True, fail_stop=True),
        _Worker("watch", events),
        _Worker("refresh", events),
    ]

    with pytest.raises(
        RuntimeError, match="^runtime_component_start_failed$"
    ) as caught:
        with TestClient(
            _app(tmp_path, workers, _Models(events, fail_shutdown=True)),
            base_url="http://127.0.0.1",
        ):
            raise AssertionError("startup unexpectedly succeeded")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert events == [
        "start:analysis",
        "start:automation",
        "stop:automation",
        "stop:analysis",
        "shutdown:models",
    ]
    assert "SYNTHETIC_PRIVATE" not in " ".join(events)


def test_shutdown_attempts_every_cleanup_in_reverse_order(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events, fail_stop=True),
        _Worker("automation", events),
        _Worker("watch", events, fail_stop=True),
        _Worker("refresh", events),
    ]

    with pytest.raises(
        RuntimeError, match="^runtime_component_shutdown_failed$"
    ) as caught:
        with TestClient(
            _app(tmp_path, workers, _Models(events, fail_shutdown=True)),
            base_url="http://127.0.0.1",
        ) as client:
            assert client.get("/health").status_code == 200

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None

    assert events == [
        "start:analysis",
        "start:automation",
        "start:watch",
        "start:refresh",
        "stop:refresh",
        "stop:watch",
        "stop:automation",
        "stop:analysis",
        "shutdown:models",
    ]


def test_authenticated_liveness_distinguishes_running_and_degraded(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events),
        _Worker("automation", events),
        _Worker("watch", events),
        _Worker("refresh", events),
    ]
    headers = {API_TOKEN_HEADER: TOKEN}

    with TestClient(
        _app(tmp_path, workers, _Models(events)),
        base_url="http://127.0.0.1",
    ) as client:
        assert client.get("/v1/runtime-liveness").status_code == 401
        healthy = client.get("/v1/runtime-liveness", headers=headers)
        workers[1].alive = False
        workers[2].liveness_error = True
        degraded = client.get("/v1/runtime-liveness", headers=headers)

    assert healthy.status_code == 200
    assert healthy.json() == {
        "contract_version": "runtime-liveness.v1",
        "status": "ok",
        "components": [
            {"component": "analysis_job_worker", "configured": True, "alive": True},
            {"component": "automation_grant_worker", "configured": True, "alive": True},
            {"component": "model_ensemble_watch_worker", "configured": True, "alive": True},
            {"component": "local_source_refresh_worker", "configured": True, "alive": True},
        ],
    }
    assert degraded.status_code == 503
    assert degraded.json()["status"] == "degraded"
    assert [row["alive"] for row in degraded.json()["components"]] == [
        True,
        False,
        False,
        True,
    ]
    assert "SYNTHETIC_PRIVATE_LIVENESS_CANARY" not in degraded.text


def test_degraded_liveness_response_is_documented(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events),
        _Worker("automation", events),
        _Worker("watch", events),
        _Worker("refresh", events),
    ]
    schema = _app(tmp_path, workers, _Models(events)).openapi()

    response_schema = schema["paths"]["/v1/runtime-liveness"]["get"]["responses"]
    assert response_schema["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RuntimeLivenessDto"
    }


def test_unconfigured_components_remain_distinct_from_stopped(tmp_path) -> None:
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=_Store(),
        api_token=TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/runtime-liveness",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert all(
        row == {"component": row["component"], "configured": False, "alive": None}
        for row in response.json()["components"]
    )


def test_shutdown_records_only_the_closed_component_names(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events, fail_stop=True),
        _Worker("automation", events),
        _Worker("watch", events, fail_stop=True),
        _Worker("refresh", events),
    ]
    app = _app(tmp_path, workers, _Models(events, fail_shutdown=True))

    with pytest.raises(RuntimeError, match="^runtime_component_shutdown_failed$"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pass

    report = app.state.runtime_lifecycle
    assert report.shutdown_failures == (
        "model_ensemble_watch_worker",
        "analysis_job_worker",
        "local_model_service",
    )
    assert report.startup_failure is None
    assert "SYNTHETIC_PRIVATE" not in repr(report)


def test_startup_report_keeps_start_and_cleanup_failures_separate(tmp_path) -> None:
    events: list[str] = []
    workers = [
        _Worker("analysis", events),
        _Worker("automation", events, fail_start=True, fail_stop=True),
        _Worker("watch", events),
        _Worker("refresh", events),
    ]
    app = _app(tmp_path, workers, _Models(events))

    with pytest.raises(RuntimeError, match="^runtime_component_start_failed$"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pass

    report = app.state.runtime_lifecycle
    assert report.startup_failure == "automation_grant_worker"
    assert report.shutdown_failures == ("automation_grant_worker",)
    assert "SYNTHETIC_PRIVATE" not in repr(report)


def test_native_fallback_and_lifespan_share_one_exhaustive_cleanup(tmp_path) -> None:
    events: list[str] = []
    workers = [_Worker(name, events) for name in ("analysis", "automation", "watch", "refresh")]
    app = _app(tmp_path, workers, _Models(events))

    with TestClient(app, base_url="http://127.0.0.1"):
        app.state.stop_runtime_components()
        app.state.stop_runtime_components()

    assert events.count("shutdown:models") == 1
    for name in ("analysis", "automation", "watch", "refresh"):
        assert events.count(f"stop:{name}") == 1
    assert app.state.runtime_lifecycle.cleanup_finished is True
    assert app.state.runtime_lifecycle.shutdown_failures == ()


def test_update_shutdown_failure_is_reported_without_private_exception_text(tmp_path) -> None:
    class _FailingUpdater:
        def status(self):
            raise AssertionError("status should not be called")

        def shutdown(self) -> None:
            raise RuntimeError("SYNTHETIC_PRIVATE_UPDATE_SHUTDOWN_CANARY")

    events: list[str] = []
    workers = [
        _Worker(name, events)
        for name in ("analysis", "automation", "watch", "refresh")
    ]
    app = _app(tmp_path, workers, _Models(events), updater=_FailingUpdater())

    with pytest.raises(RuntimeError, match="^runtime_component_shutdown_failed$"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pass

    report = app.state.runtime_lifecycle
    assert report.shutdown_failures == ("application_update_service",)
    assert report.cleanup_finished is True
    assert "SYNTHETIC_PRIVATE" not in repr(report)


def test_agent_and_evaluation_shutdown_are_exhaustive_and_content_free(tmp_path) -> None:
    from prompt_enhancer.application.local_agent import LocalAgentService
    from prompt_enhancer.infrastructure.text_models.jobs import LocalTextModelEvaluationService

    events: list[str] = []

    class FailingAgent(LocalAgentService):
        def shutdown(self):
            events.append("shutdown:agent")
            raise RuntimeError("EXAMPLE_PRIVATE_AGENT_SHUTDOWN_CANARY")

    class FailingEvaluation(LocalTextModelEvaluationService):
        def shutdown(self):
            events.append("shutdown:evaluation")
            raise RuntimeError("EXAMPLE_PRIVATE_EVALUATION_SHUTDOWN_CANARY")

    app = create_app(
        settings=AppSettings(home=tmp_path), database=_Store(), api_token=TOKEN,
        local_model_service=_Models(events),
        local_agent_service=FailingAgent(chat=lambda *_: (200, b"{}", "application/json"), active_model=lambda: None),
        model_evaluation_service=FailingEvaluation(),
    )
    with pytest.raises(RuntimeError, match="^runtime_component_shutdown_failed$"):
        with TestClient(app, base_url="http://127.0.0.1"):
            pass
    app.state.stop_runtime_components()
    assert events == ["shutdown:models", "shutdown:agent", "shutdown:evaluation"]
    assert app.state.runtime_lifecycle.shutdown_failures == ("local_agent_service", "model_evaluation_service")
    assert "EXAMPLE_PRIVATE" not in repr(app.state.runtime_lifecycle)
