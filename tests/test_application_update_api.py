from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.updates import (
    ApplicationUpdateReason,
    ApplicationUpdateState,
    ApplicationUpdateStatus,
    UpdateChannel,
    UnconfiguredApplicationUpdateSurface,
)
from prompt_enhancer.application.updates.status import UpdateActionConflict
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER

TOKEN = "synthetic-update-token-000000000000000000000000"


class _EmptyStore:

    def initialize(self) -> None:
        return None

    def task_repository(self):
        from prompt_enhancer.application.tasks import MemoryTaskRepository

        return MemoryTaskRepository()

    def analysis_run_repository(self):
        from prompt_enhancer.application.analysis import MemoryAnalysisRunRepository

        return MemoryAnalysisRunRepository()

    def list_metric_definitions(self):
        return []

    def list_sessions(self, *, limit: int = 100, offset: int = 0):
        return []

    def get_session_metrics(self, session_id: str):
        return []


class _RecordingSurface:

    def __init__(self) -> None:
        self.checks = 0
        self.calls: list[tuple[str, int, str]] = []
        self.shutdown_calls = 0
        self.snapshot = ApplicationUpdateStatus(
            installed_version="1.2.3",
            channel=UpdateChannel.STABLE,
            state=ApplicationUpdateState.READY_TO_CHECK,
            instance_id="0" * 32,
            revision=0,
            can_check=True,
            can_stage=False,
            can_cancel=False,
            can_retry=False,
            can_apply=False,
        )

    def status(self) -> ApplicationUpdateStatus:
        return self.snapshot

    def _record(self, name: str, *, expected_revision: int,
                expected_instance_id: str) -> ApplicationUpdateStatus:
        self.calls.append((name, expected_revision, expected_instance_id))
        return self.snapshot

    def check(self, **kwargs: object) -> ApplicationUpdateStatus:
        self.checks += 1
        return self._record("check", **kwargs)  # type: ignore[arg-type]

    def stage(self, **kwargs: object) -> ApplicationUpdateStatus:
        return self._record("stage", **kwargs)  # type: ignore[arg-type]

    def cancel(self, **kwargs: object) -> ApplicationUpdateStatus:
        return self._record("cancel", **kwargs)  # type: ignore[arg-type]

    def retry(self, **kwargs: object) -> ApplicationUpdateStatus:
        return self._record("retry", **kwargs)  # type: ignore[arg-type]

    def verify(self, **kwargs: object) -> ApplicationUpdateStatus:
        return self._record("verify", **kwargs)  # type: ignore[arg-type]

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _app(tmp_path: Path, service=None):
    return create_app(
        settings=AppSettings(home=tmp_path / "synthetic-state"),
        database=_EmptyStore(),
        api_token=TOKEN,
        application_update_service=service,
    )


def test_unconfigured_surface_is_content_free_and_network_silent() -> None:
    surface = UnconfiguredApplicationUpdateSurface(installed_version="1.2.3")

    assert surface.status() == surface.check()
    assert surface.status().model_dump(mode="json") == {
            "contract_version": "application-update-status.v3",
        "contains_private_data": False,
        "installed_version": "1.2.3",
        "channel": "stable",
        "state": "unconfigured",
        "instance_id": surface.status().instance_id,
        "revision": 0,
        "available_version": None,
        "artifact_size_bytes": None,
        "downloaded_bytes": None,
        "last_checked_at": None,
        "reason_code": "release_feed_unconfigured",
        "verification_code": None,
        "can_check": False,
        "can_stage": False,
        "can_cancel": False,
        "can_retry": False,
            "can_apply": False,
            "can_verify": False,
            "package_review": {
                "state": "not_configured",
                "reason_code": None,
                "checked_at": None,
            },
    }


@pytest.mark.parametrize(
    "changes",
    [
        {
            "reason_code": None
        },
        {
            "can_check": True
        },
        {
            "available_version": "2.0.0"
        },
        {
            "downloaded_bytes": 0
        },
    ],
)
def test_unconfigured_contract_rejects_invented_capabilities(
        changes: dict) -> None:
    values = {
        "installed_version": "1.2.3",
        "channel": UpdateChannel.STABLE,
        "state": ApplicationUpdateState.UNCONFIGURED,
        "instance_id": "0" * 32,
        "revision": 0,
        "reason_code": ApplicationUpdateReason.RELEASE_FEED_UNCONFIGURED,
        "can_check": False,
        "can_stage": False,
        "can_cancel": False,
        "can_retry": False,
        "can_apply": False,
        **changes,
    }

    with pytest.raises(ValueError):
        ApplicationUpdateStatus(**values)


def test_update_status_is_authenticated_and_does_not_trigger_a_check(
    tmp_path: Path, ) -> None:
    service = _RecordingSurface()
    app = _app(tmp_path, service)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/v1/application-updates/status").status_code == 401
        response = client.get(
            "/v1/application-updates/status",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["state"] == "ready_to_check"
    assert response.json()["contains_private_data"] is False
    assert service.checks == 0


def test_update_check_requires_an_explicit_same_origin_browser_gesture(
    tmp_path: Path, ) -> None:
    service = _RecordingSurface()
    app = _app(tmp_path, service)
    client = TestClient(app, base_url="http://127.0.0.1")

    assert client.post("/v1/application-updates/check").status_code == 401
    bootstrap = client.get("/auth/session")
    csrf = bootstrap.json()["csrf_token"]
    assert client.post(
        "/v1/application-updates/check",
        json={
            "expected_revision": 0,
            "expected_instance_id": "0" * 32
        },
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://example.invalid"
        },
    ).status_code == 403
    assert client.post(
        "/v1/application-updates/check",
        json={
            "expected_revision": 0,
            "expected_instance_id": "0" * 32
        },
        headers={
            API_TOKEN_HEADER: TOKEN,
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1",
        },
    ).status_code == 403
    assert service.checks == 0

    checked = client.post(
        "/v1/application-updates/check",
        json={
            "expected_revision": 0,
            "expected_instance_id": "0" * 32
        },
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1"
        },
    )

    assert checked.status_code == 200
    assert checked.headers["cache-control"] == "no-store, private"
    assert checked.json()["state"] == "ready_to_check"
    assert service.checks == 1


def test_default_app_exposes_only_an_unconfigured_update_surface(
        tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/application-updates/status",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["state"] == "unconfigured"
    assert response.json()["reason_code"] == "release_feed_unconfigured"
    assert response.json()["can_check"] is False


@pytest.mark.parametrize("action", ["stage", "cancel", "retry", "verify"])
def test_update_mutations_require_browser_gesture_and_forward_exact_fence(
    tmp_path: Path,
    action: str,
) -> None:
    service = _RecordingSurface()
    client = TestClient(_app(tmp_path, service), base_url="http://127.0.0.1")
    payload = {"expected_revision": 0, "expected_instance_id": "0" * 32}

    assert client.post(f"/v1/application-updates/{action}",
                       json=payload).status_code == 401
    csrf = client.get("/auth/session").json()["csrf_token"]
    assert client.post(
        f"/v1/application-updates/{action}",
        json=payload,
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://example.invalid"
        },
    ).status_code == 403
    response = client.post(
        f"/v1/application-updates/{action}",
        json=payload,
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1"
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert service.calls == [(action, 0, "0" * 32)]


@pytest.mark.parametrize("action", ["check", "stage", "cancel", "retry", "verify"])
@pytest.mark.parametrize(
    "payload",
    [
        {
            "expected_revision": True,
            "expected_instance_id": "0" * 32
        },
        {
            "expected_revision": 0,
            "expected_instance_id": "bad"
        },
    ],
)
def test_update_mutations_reject_malformed_fences_without_dispatch(
    tmp_path: Path,
    action: str,
    payload: dict[str, object],
) -> None:
    service = _RecordingSurface()
    client = TestClient(_app(tmp_path, service), base_url="http://127.0.0.1")
    csrf = client.get("/auth/session").json()["csrf_token"]
    response = client.post(
        f"/v1/application-updates/{action}",
        json=payload,
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1"
        },
    )
    assert response.status_code == 422
    assert service.calls == []


def test_stale_fence_conflict_is_private_and_query_cannot_dispatch_shutdown(
    tmp_path: Path, ) -> None:

    class _ConflictingSurface(_RecordingSurface):

        def stage(self, **kwargs: object) -> ApplicationUpdateStatus:
            raise UpdateActionConflict("synthetic_stale_fence")

    service = _ConflictingSurface()
    client = TestClient(_app(tmp_path, service), base_url="http://127.0.0.1")
    csrf = client.get("/auth/session").json()["csrf_token"]
    payload = {"expected_revision": 0, "expected_instance_id": "0" * 32}
    conflict = client.post(
        "/v1/application-updates/stage",
        json=payload,
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1"
        },
    )
    checked = client.post(
        "/v1/application-updates/check?action=shutdown",
        json=payload,
        headers={
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1"
        },
    )

    assert conflict.status_code == 409
    assert conflict.headers["cache-control"] == "no-store, private"
    assert checked.status_code == 200
    assert service.shutdown_calls == 0
    assert service.calls == [("check", 0, "0" * 32)]
