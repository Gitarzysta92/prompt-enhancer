from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.workspace_folder_picker import (
    LocalWorkspaceFolderPicker,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER


def test_picker_reports_capability_and_returns_only_valid_absolute_selection() -> None:
    selections = iter(
        [
            r"D:\example\workspace",
            None,
            "relative-folder",
        ]
    )
    picker = LocalWorkspaceFolderPicker(lambda: next(selections))

    assert picker.capability().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "available": True,
        "mode": "server_native_dialog",
    }
    assert picker.choose().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "status": "selected",
        "path": r"D:\example\workspace",
    }
    assert picker.choose().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "status": "cancelled",
        "path": None,
    }
    assert picker.choose().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "status": "unavailable",
        "path": None,
    }


def test_picker_fails_closed_without_leaking_dialog_errors() -> None:
    def fail() -> str | None:
        raise RuntimeError("EXAMPLE_PRIVATE_DIALOG_CANARY")

    result = LocalWorkspaceFolderPicker(fail).choose()

    assert result.status == "unavailable"
    assert result.path is None
    assert "CANARY" not in result.model_dump_json()
    assert LocalWorkspaceFolderPicker(None).capability().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "available": False,
        "mode": "unavailable",
    }


def test_picker_allows_only_one_native_dialog_at_a_time() -> None:
    entered = Event()
    release = Event()
    first_result: list[str] = []

    def wait_for_user() -> str | None:
        entered.set()
        assert release.wait(timeout=2)
        return r"D:\example\workspace"

    picker = LocalWorkspaceFolderPicker(wait_for_user)

    def choose_first() -> None:
        first_result.append(picker.choose().status)

    worker = Thread(target=choose_first)
    worker.start()
    assert entered.wait(timeout=2)
    assert picker.choose().model_dump() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "status": "busy",
        "path": None,
    }
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert first_result == ["selected"]


def test_http_picker_requires_same_origin_browser_gesture(tmp_path: Path) -> None:
    calls: list[None] = []

    def choose() -> str | None:
        calls.append(None)
        return r"D:\example\chosen-workspace"

    settings = AppSettings(home=tmp_path / "example-state")
    application = bootstrap_local_application(settings)
    picker = LocalWorkspaceFolderPicker(choose)
    http_app = application.create_http_app(workspace_folder_picker=picker)
    client = TestClient(
        http_app,
        base_url="http://127.0.0.1",
    )
    token = settings.api_token_path.read_text(encoding="utf-8").strip()
    post_parameters = {
        item["name"]
        for item in http_app.openapi()["paths"][
            "/v1/local-ui/workspace-folder-picker"
        ]["post"]["parameters"]
    }
    assert post_parameters == {CSRF_HEADER}
    assert API_TOKEN_HEADER not in post_parameters

    assert client.get("/v1/local-ui/workspace-folder-picker").status_code == 401
    browser = client.get("/auth/session")
    csrf = browser.json()["csrf_token"]
    capability = client.get("/v1/local-ui/workspace-folder-picker")
    assert capability.status_code == 200
    assert capability.headers["cache-control"] == "no-store, private"
    assert capability.headers["pragma"] == "no-cache"
    assert capability.json() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "available": True,
        "mode": "server_native_dialog",
    }

    assert client.post("/v1/local-ui/workspace-folder-picker").status_code == 403
    assert client.post(
        "/v1/local-ui/workspace-folder-picker",
        headers={CSRF_HEADER: csrf, "Origin": "http://example.invalid"},
    ).status_code == 403
    token_response = client.post(
        "/v1/local-ui/workspace-folder-picker",
        headers={
            API_TOKEN_HEADER: token,
            CSRF_HEADER: csrf,
            "Origin": "http://127.0.0.1",
        },
    )
    assert token_response.status_code == 403
    assert token_response.json() == {"detail": "browser interaction required"}
    assert calls == []

    selected = client.post(
        "/v1/local-ui/workspace-folder-picker",
        headers={CSRF_HEADER: csrf, "Origin": "http://127.0.0.1"},
    )
    assert selected.status_code == 200
    assert selected.headers["cache-control"] == "no-store, private"
    assert selected.headers["pragma"] == "no-cache"
    assert selected.json() == {
        "contract_version": "local-workspace-folder-picker.v1",
        "status": "selected",
        "path": r"D:\example\chosen-workspace",
    }
    assert calls == [None]
