from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from prompt_enhancer import cli
from prompt_enhancer.config import AppSettings
from prompt_enhancer import desktop_overlay
from prompt_enhancer.interfaces.http.desktop_identity import (
    DESKTOP_OWNED_INSTANCE_PATH_PREFIX,
)


TOKEN = "example_desktop_overlay_token_123456789"


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self) -> None:
        for handler in tuple(self.handlers):
            handler()


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.current_url = "about:blank"
        self.folder_dialog_calls: list[tuple[object, bool]] = []
        self.folder_dialog_result: object = None
        self.events = SimpleNamespace(closed=FakeEvent())

    def get_current_url(self) -> str:
        return self.current_url

    def minimize(self) -> None:
        self.calls.append("minimize")

    def maximize(self) -> None:
        self.calls.append("maximize")

    def restore(self) -> None:
        self.calls.append("restore")

    def destroy(self) -> None:
        self.calls.append("destroy")

    def create_file_dialog(
        self,
        dialog_type: object,
        *,
        allow_multiple: bool,
    ) -> object:
        self.folder_dialog_calls.append((dialog_type, allow_multiple))
        return self.folder_dialog_result


class FakeWebview:
    FileDialog = SimpleNamespace(FOLDER="synthetic-folder-dialog")
    FOLDER_DIALOG = "legacy-synthetic-folder-dialog"

    def __init__(
        self,
        *,
        fail_start: bool = False,
        confirm_close_event: bool = True,
    ) -> None:
        self.created: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.started: list[dict[str, object]] = []
        self.window = FakeWindow()
        self.fail_start = fail_start
        self.confirm_close_event = confirm_close_event

    def create_window(self, *args: object, **kwargs: object) -> object:
        self.created.append((args, kwargs))
        self.window.current_url = str(kwargs["url"])
        return self.window

    def start(self, **kwargs: object) -> None:
        self.started.append(kwargs)
        if self.fail_start:
            raise RuntimeError("synthetic GUI failure")
        if self.confirm_close_event:
            self.window.events.closed.emit()


class FakeOwnedServer:
    def __init__(self) -> None:
        self.stops = 0
        self.thread = SimpleNamespace(is_alive=lambda: True)
        self.user_presence = desktop_overlay.UserPresenceApprovalManager()
        self.endpoints = (("127.0.0.1", "http://127.0.0.1:18765"),)
        self.readiness_path = (
            f"{DESKTOP_OWNED_INSTANCE_PATH_PREFIX}{'s' * 43}"
        )

    def stop(self) -> None:
        self.stops += 1


def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(home=tmp_path, host="127.0.0.1", port=18765)


def prepare_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    service_open: bool,
    trusted: bool,
) -> None:
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay,
        "load_or_create_api_token",
        lambda _path: TOKEN,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_port_is_open",
        lambda _host, _port: service_open,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_verify_service_identity",
        lambda _origin, supplied: supplied == TOKEN and trusted,
    )


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "http://127.0.0.1:8765"),
        ("localhost", "http://localhost:8765"),
        ("::1", "http://[::1]:8765"),
    ],
)
def test_loopback_origin_is_canonical(host: str, expected: str) -> None:
    assert desktop_overlay._loopback_origin(host, 8765) == expected


def test_loopback_origin_rejects_remote_hosts_and_unsafe_ports() -> None:
    with pytest.raises(desktop_overlay.DesktopOverlayServiceError):
        desktop_overlay._loopback_origin("192.0.2.10", 8765)
    with pytest.raises(desktop_overlay.DesktopOverlayServiceError):
        desktop_overlay._loopback_origin("127.0.0.1", 80)


def test_attaches_to_authenticated_service_without_owning_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=True, trusted=True)
    webview = FakeWebview()
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)
    monkeypatch.setattr(
        desktop_overlay,
        "_start_owned_server",
        lambda _settings: pytest.fail("trusted listeners must be reused"),
    )

    desktop_overlay.run_desktop_overlay(settings(tmp_path))

    assert len(webview.created) == 1
    args, options = webview.created[0]
    assert args == ("Prompt Enhancer - Live metrics",)
    assert options["url"] == "http://127.0.0.1:18765/overlay/model-ensemble"
    assert TOKEN not in str(args)
    assert TOKEN not in str(options)
    assert options["on_top"] is True
    assert options["resizable"] is True
    assert options["frameless"] is True
    assert options["easy_drag"] is False
    assert options["shadow"] is True
    assert options["min_size"] == (340, 420)
    window_api = options["js_api"]
    assert window_api._user_presence is None
    window_api.minimize_window()
    assert window_api.toggle_maximize_window() is True
    assert window_api.toggle_maximize_window() is False
    window_api.close_window()
    assert webview.window.calls == ["minimize", "maximize", "restore", "destroy"]
    assert webview.started == [{"gui": "edgechromium", "debug": False}]


def test_localhost_attachment_probes_and_renders_only_an_exact_numeric_origin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = AppSettings(home=tmp_path, host="localhost", port=18765)
    webview = FakeWebview()
    probed: list[str] = []
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay,
        "load_or_create_api_token",
        lambda _path: TOKEN,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_exact_loopback_endpoints",
        lambda _host, _port: (
            ("::1", "http://[::1]:18765"),
            ("127.0.0.1", "http://127.0.0.1:18765"),
        ),
    )
    monkeypatch.setattr(desktop_overlay, "_port_is_open", lambda *_args: True)

    def verify(origin: str, supplied: str) -> bool:
        probed.append(origin)
        return supplied == TOKEN and origin == "http://127.0.0.1:18765"

    monkeypatch.setattr(desktop_overlay, "_verify_service_identity", verify)
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)
    monkeypatch.setattr(
        desktop_overlay,
        "_start_owned_server",
        lambda _settings: pytest.fail("the trusted IPv4 listener must be reused"),
    )

    desktop_overlay.run_desktop_overlay(selected)

    assert probed == ["http://[::1]:18765", "http://127.0.0.1:18765"]
    assert len(webview.created) == 1
    assert webview.created[0][1]["url"] == (
        "http://127.0.0.1:18765/overlay/model-ensemble"
    )


def test_refuses_an_occupied_port_that_fails_authentication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=True, trusted=False)
    monkeypatch.setattr(
        desktop_overlay,
        "_load_webview",
        lambda: pytest.fail("an untrusted listener must never be rendered"),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        desktop_overlay.run_desktop_overlay(settings(tmp_path))
    assert caught.value.reason_code == "service_untrusted"
    assert str(caught.value) == desktop_overlay._FAILURE_MESSAGES["service_untrusted"]


def test_starts_and_stops_only_an_owned_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    webview = FakeWebview()
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, supplied, candidate: (
            endpoints[0][1]
            if supplied == TOKEN and candidate is owned
            else pytest.fail("owned service readiness binding changed")
        ),
    )
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)

    desktop_overlay.run_desktop_overlay(settings(tmp_path))

    assert owned.stops == 1
    assert len(webview.created) == 1
    assert webview.created[0][1]["js_api"]._user_presence is owned.user_presence


def test_protected_agent_owns_a_fallback_listener_instead_of_attaching_to_an_existing_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=True, trusted=True)
    monkeypatch.setattr(
        desktop_overlay,
        "_verify_service_identity",
        lambda *_args: pytest.fail("protected Agent must never probe an attached identity"),
    )
    owned = FakeOwnedServer()
    owned.endpoints = (("127.0.0.1", "http://127.0.0.1:19876"),)
    webview = FakeWebview()
    starts: list[dict[str, object]] = []

    def start(_settings, **options):
        starts.append(options)
        return owned

    monkeypatch.setattr(desktop_overlay, "_start_owned_server", start)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, supplied, candidate: (
            endpoints[0][1]
            if supplied == TOKEN and candidate is owned
            else pytest.fail("fallback ownership binding changed")
        ),
    )
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)

    desktop_overlay.run_desktop_agent(settings(tmp_path))

    assert starts == [{"allow_ephemeral": True}]
    assert owned.stops == 1
    assert webview.created[0][1]["url"] == "http://127.0.0.1:19876/agent"
    assert webview.created[0][1]["js_api"]._user_presence is owned.user_presence


def test_protected_agent_refuses_trusted_listener_that_wins_startup_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=True)
    owned = FakeOwnedServer()
    owned.thread = SimpleNamespace(is_alive=lambda: False)
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings, **_options: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_verify_owned_service_instance",
        lambda _origin, _readiness_path: False,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_load_webview",
        lambda: pytest.fail("a racing listener must never get the native bridge"),
    )

    with pytest.raises(
        desktop_overlay.DesktopOverlayServiceError,
    ) as caught:
        desktop_overlay.run_desktop_agent(settings(tmp_path))

    assert caught.value.reason_code == "service_exited"
    assert owned.stops == 1


def test_protected_agent_owns_server_manager_and_opens_full_agent_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    webview = FakeWebview()
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings, **_options: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, supplied, candidate: (
            endpoints[0][1]
            if supplied == TOKEN and candidate is owned
            else pytest.fail("owned Agent readiness binding changed")
        ),
    )
    monkeypatch.setattr(desktop_overlay, "_load_webview", lambda: webview)

    desktop_overlay.run_desktop_agent(settings(tmp_path))

    assert owned.stops == 1
    assert len(webview.created) == 1
    args, options = webview.created[0]
    assert args == ("Prompt Enhancer - Agent workspace",)
    assert options["url"] == "http://127.0.0.1:18765/agent"
    assert options["frameless"] is False
    assert options["on_top"] is False
    assert options["min_size"] == (840, 640)
    assert TOKEN not in str(args)
    assert TOKEN not in str(options)
    window_api = options["js_api"]
    assert isinstance(window_api, desktop_overlay._DesktopAgentWindowApi)
    assert window_api._user_presence is owned.user_presence
    assert window_api._folder_dialog_type == FakeWebview.FileDialog.FOLDER
    assert webview.started == [{"gui": "edgechromium", "debug": False}]
    lifecycle = json.loads(
        (tmp_path / "diagnostics" / "native-agent-lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["contract"] == "native-lifecycle.v1"
    assert lifecycle["window"] == "agent"
    assert lifecycle["phase"] == "stopped"
    assert lifecycle["terminal"] is True


def test_protected_agent_stops_owned_server_when_native_loop_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings, **_options: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, *_args: endpoints[0][1],
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_load_webview",
        lambda: FakeWebview(fail_start=True),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.run_desktop_agent(settings(tmp_path))
    assert caught.value.reason_code == "window_start_failed"
    assert "synthetic GUI failure" not in str(caught.value)
    assert caught.value.__context__ is None
    assert owned.stops == 1
    lifecycle = json.loads(
        (tmp_path / "diagnostics" / "native-agent-lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["phase"] == "failed"
    assert lifecycle["reason_code"] == "window_start_failed"
    assert lifecycle["cleanup_reason_code"] is None


def test_returned_native_loop_requires_a_confirmed_close_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    monkeypatch.setattr(
        desktop_overlay,
        "_start_owned_server",
        lambda _settings, **_options: owned,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, *_args: endpoints[0][1],
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_load_webview",
        lambda: FakeWebview(confirm_close_event=False),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.run_desktop_agent(settings(tmp_path))

    assert caught.value.reason_code == "window_close_unconfirmed"
    assert owned.stops == 1
    lifecycle = json.loads(
        (tmp_path / "diagnostics" / "native-agent-lifecycle.json").read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["phase"] == "failed"
    assert lifecycle["reason_code"] == "window_close_unconfirmed"


def test_owned_server_stops_when_native_loop_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda endpoints, *_args: endpoints[0][1],
    )
    monkeypatch.setattr(
        desktop_overlay,
        "_load_webview",
        lambda: FakeWebview(fail_start=True),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.run_desktop_overlay(settings(tmp_path))
    assert caught.value.reason_code == "window_start_failed"
    assert "synthetic GUI failure" not in str(caught.value)
    assert caught.value.__context__ is None
    assert owned.stops == 1


def test_native_confirmation_issues_one_content_free_bound_capability() -> None:
    manager = desktop_overlay.UserPresenceApprovalManager()
    expected_origin = "http://127.0.0.1:18765"
    window_api = desktop_overlay._DesktopWindowApi(manager, expected_origin)
    calls: list[tuple[str, str]] = []
    window = SimpleNamespace(
        get_current_url=lambda: f"{expected_origin}/overlay/model-ensemble",
        create_confirmation_dialog=lambda title, message: (
            calls.append((title, message)) or True
        )
    )
    window_api._bind(window)
    path = f"/v1/sessions/{'a' * 64}/declared-task-profile"
    body = b'{"confirmation":"save_reviewed_declared_task_profile"}'
    import hashlib

    response = window_api.confirm_user_presence(
        {
            "method": "POST",
            "path": path,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }
    )

    assert response["approved"] is True
    assert response["version"] == "native-user-presence-v1"
    token = response["approval_token"]
    assert manager.consume(token=token, method="POST", path=path, body=body) is True
    assert manager.consume(token=token, method="POST", path=path, body=body) is False
    assert calls == [
        (
            "Confirm local action",
            "Save declared metric denominators for future analysis.\n\n"
            "Approve only if you initiated and reviewed this action.",
        )
    ]
    assert path not in str(calls)
    assert "declared-task-profile" not in str(calls)


def test_native_confirmation_decline_and_unregistered_action_fail_closed() -> None:
    manager = desktop_overlay.UserPresenceApprovalManager()
    expected_origin = "http://127.0.0.1:18765"
    window_api = desktop_overlay._DesktopWindowApi(manager, expected_origin)
    window_api._bind(
        SimpleNamespace(
            get_current_url=lambda: f"{expected_origin}/overlay/model-ensemble",
            create_confirmation_dialog=lambda _title, _message: False,
        )
    )
    allowed_path = f"/v1/agent/sessions/{'a' * 32}/approvals/{'b' * 32}"

    declined = window_api.confirm_user_presence(
        {"method": "POST", "path": allowed_path, "body_sha256": "c" * 64}
    )
    rejected = window_api.confirm_user_presence(
        {"method": "POST", "path": "/v1/unreviewed", "body_sha256": "c" * 64}
    )

    assert declined == {
        "approved": False,
        "reason": "user_declined",
        "version": "native-user-presence-v1",
    }
    assert rejected == {
        "approved": False,
        "reason": "action_not_allowed",
        "version": "native-user-presence-v1",
    }


@pytest.mark.parametrize(
    "current_url",
    [
        "https://example.invalid/overlay/model-ensemble",
        "http://127.0.0.1:18765@example.invalid/overlay/model-ensemble",
        "not a URL",
        "http://127.0.0.1:18766/overlay/model-ensemble",
    ],
)
def test_native_confirmation_rejects_window_origin_drift(current_url: str) -> None:
    manager = desktop_overlay.UserPresenceApprovalManager()
    dialogs: list[bool] = []
    window_api = desktop_overlay._DesktopWindowApi(
        manager,
        "http://127.0.0.1:18765",
    )
    window_api._bind(
        SimpleNamespace(
            get_current_url=lambda: current_url,
            create_confirmation_dialog=lambda *_args: dialogs.append(True) or True,
        )
    )

    response = window_api.confirm_user_presence(
        {
            "method": "POST",
            "path": f"/v1/sessions/{'a' * 64}/declared-task-profile",
            "body_sha256": "b" * 64,
        }
    )

    assert response == {
        "approved": False,
        "reason": "native_confirmation_unavailable",
        "version": "native-user-presence-v1",
    }
    assert dialogs == []


def test_native_confirmation_rechecks_origin_after_the_modal() -> None:
    manager = desktop_overlay.UserPresenceApprovalManager()
    current = ["http://127.0.0.1:18765/overlay/model-ensemble"]
    window_api = desktop_overlay._DesktopWindowApi(
        manager,
        "http://127.0.0.1:18765",
    )

    def approve_then_navigate(_title: str, _message: str) -> bool:
        current[0] = "https://example.invalid/after-dialog"
        return True

    window_api._bind(
        SimpleNamespace(
            get_current_url=lambda: current[0],
            create_confirmation_dialog=approve_then_navigate,
        )
    )
    response = window_api.confirm_user_presence(
        {
            "method": "POST",
            "path": f"/v1/sessions/{'a' * 64}/declared-task-profile",
            "body_sha256": "b" * 64,
        }
    )

    assert response == {
        "approved": False,
        "reason": "native_confirmation_unavailable",
        "version": "native-user-presence-v1",
    }


def test_native_folder_picker_returns_only_the_exact_selected_contract() -> None:
    expected_origin = "http://127.0.0.1:18765"
    window = FakeWindow()
    window.current_url = f"{expected_origin}/agent"
    window.folder_dialog_result = (r"D:\example\project",)
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    response = window_api.choose_workspace_folder()

    assert response == {
        "version": "native-folder-picker-v1",
        "status": "selected",
        "path": r"D:\example\project",
    }
    assert set(response) == {"version", "status", "path"}
    assert window.folder_dialog_calls == [(FakeWebview.FileDialog.FOLDER, False)]


def test_native_folder_picker_cancel_is_exact_and_content_free() -> None:
    expected_origin = "http://127.0.0.1:18765"
    window = FakeWindow()
    window.current_url = f"{expected_origin}/agent"
    window.folder_dialog_result = None
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    response = window_api.choose_workspace_folder()

    assert response == {
        "version": "native-folder-picker-v1",
        "status": "cancelled",
    }
    assert set(response) == {"version", "status"}


def test_native_folder_picker_dialog_failure_is_content_free_unavailable() -> None:
    expected_origin = "http://127.0.0.1:18765"

    def fail_dialog(_dialog_type: object, *, allow_multiple: bool) -> object:
        assert allow_multiple is False
        raise RuntimeError("synthetic native detail")

    window = SimpleNamespace(
        get_current_url=lambda: f"{expected_origin}/agent",
        create_file_dialog=fail_dialog,
    )
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    response = window_api.choose_workspace_folder()

    assert response == {
        "version": "native-folder-picker-v1",
        "status": "unavailable",
    }
    assert "synthetic native detail" not in str(response)


@pytest.mark.parametrize(
    "selection",
    [
        "D:\\example\\project",
        ("relative\\project",),
        ("D:\\one", "D:\\two"),
        (123,),
    ],
)
def test_native_folder_picker_malformed_results_fail_closed(selection: object) -> None:
    expected_origin = "http://127.0.0.1:18765"
    window = FakeWindow()
    window.current_url = f"{expected_origin}/agent"
    window.folder_dialog_result = selection
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    assert window_api.choose_workspace_folder() == {
        "version": "native-folder-picker-v1",
        "status": "unavailable",
    }


def test_native_folder_picker_rechecks_agent_route_after_selection() -> None:
    expected_origin = "http://127.0.0.1:18765"
    current = [f"{expected_origin}/agent"]

    def select_then_navigate(_dialog_type: object, *, allow_multiple: bool) -> object:
        assert allow_multiple is False
        current[0] = f"{expected_origin}/overview"
        return (r"D:\example\private-project",)

    window = SimpleNamespace(
        get_current_url=lambda: current[0],
        create_file_dialog=select_then_navigate,
    )
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    assert window_api.choose_workspace_folder() == {
        "version": "native-folder-picker-v1",
        "status": "unavailable",
    }


def test_native_folder_picker_rejects_another_same_origin_route() -> None:
    expected_origin = "http://127.0.0.1:18765"
    window = FakeWindow()
    window.current_url = f"{expected_origin}/overview"
    window.folder_dialog_result = (r"D:\example\project",)
    window_api = desktop_overlay._DesktopAgentWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        expected_origin,
        FakeWebview.FileDialog.FOLDER,
    )
    window_api._bind(window)

    assert window_api.choose_workspace_folder() == {
        "version": "native-folder-picker-v1",
        "status": "unavailable",
    }
    assert window.folder_dialog_calls == []


def test_metrics_overlay_does_not_expose_workspace_folder_picker() -> None:
    api = desktop_overlay._DesktopWindowApi(
        desktop_overlay.UserPresenceApprovalManager(),
        "http://127.0.0.1:18765",
    )
    assert not hasattr(api, "choose_workspace_folder")


def test_failed_owned_startup_is_stopped_before_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepare_common(monkeypatch, service_open=False, trusted=False)
    owned = FakeOwnedServer()
    monkeypatch.setattr(desktop_overlay, "_start_owned_server", lambda _settings: owned)
    monkeypatch.setattr(
        desktop_overlay,
        "_wait_for_owned_service",
        lambda *_args: (_ for _ in ()).throw(
            desktop_overlay.DesktopOverlayServiceError(
                "not ready", reason_code="service_not_ready"
            )
        ),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        desktop_overlay.run_desktop_overlay(settings(tmp_path))
    assert caught.value.reason_code == "service_not_ready"
    assert owned.stops == 1


def test_missing_optional_webview_is_a_safe_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(_name: str) -> object:
        raise ImportError("synthetic missing package")

    monkeypatch.setattr(desktop_overlay.importlib, "import_module", missing)
    with pytest.raises(
        desktop_overlay.DesktopOverlayDependencyError,
        match="desktop extra",
    ):
        desktop_overlay._load_webview()


def test_folder_dialog_type_prefers_pywebview_v6_and_has_legacy_fallback() -> None:
    current = SimpleNamespace(
        FileDialog=SimpleNamespace(FOLDER="current-folder"),
        FOLDER_DIALOG="legacy-folder",
    )
    legacy = SimpleNamespace(FOLDER_DIALOG="legacy-folder")

    assert desktop_overlay._native_folder_dialog_type(current) == "current-folder"
    assert desktop_overlay._native_folder_dialog_type(legacy) == "legacy-folder"
    assert desktop_overlay._native_folder_dialog_type(SimpleNamespace()) is None


def test_cli_desktop_has_no_identifier_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[AppSettings] = []
    monkeypatch.setattr(
        desktop_overlay,
        "run_desktop_overlay",
        lambda value: seen.append(value),
    )

    assert cli.main(["desktop"]) == 0
    assert len(seen) == 1
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["desktop", "--session-id", "0" * 64])


def test_cli_agent_desktop_has_no_path_or_identifier_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[AppSettings] = []
    monkeypatch.setattr(
        desktop_overlay,
        "launch_desktop_agent",
        lambda value: seen.append(value),
    )

    assert cli.main(["agent-desktop"]) == 0
    assert len(seen) == 1
    with pytest.raises(SystemExit):
        cli._parser().parse_args(["agent-desktop", "--workspace", "D:\\example"])


def test_run_desktop_delegates_without_rendering_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = settings(tmp_path)
    calls: list[AppSettings] = []
    monkeypatch.setattr(
        desktop_overlay,
        "run_desktop_overlay",
        lambda value: calls.append(value),
    )

    assert cli._run_desktop(selected) == 0
    assert calls == [selected]


def test_run_agent_desktop_delegates_without_rendering_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = settings(tmp_path)
    calls: list[AppSettings] = []
    monkeypatch.setattr(
        desktop_overlay,
        "launch_desktop_agent",
        lambda value: calls.append(value),
    )

    assert cli._run_agent_desktop(selected) == 0
    assert calls == [selected]


def test_parser_exposes_plain_desktop_commands_without_extra_authority() -> None:
    parsed = cli._parser().parse_args(["desktop"])
    assert isinstance(parsed, argparse.Namespace)
    assert vars(parsed) == {"command": "desktop"}
    agent = cli._parser().parse_args(["agent-desktop"])
    assert isinstance(agent, argparse.Namespace)
    assert vars(agent) == {"command": "agent-desktop"}


def test_console_free_entry_loads_settings_and_opens_overlay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = settings(tmp_path)
    calls: list[AppSettings] = []
    monkeypatch.setattr(AppSettings, "from_env", lambda: selected)
    monkeypatch.setattr(desktop_overlay, "run_desktop_overlay", calls.append)

    assert desktop_overlay.desktop_main() == 0
    assert calls == [selected]


def test_console_free_entry_reports_only_a_safe_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notices: list[bool] = []
    monkeypatch.setattr(
        desktop_overlay,
        "run_desktop_overlay",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("example private detail")),
    )
    monkeypatch.setattr(AppSettings, "from_env", lambda: object())
    monkeypatch.setattr(desktop_overlay, "_show_safe_desktop_error", lambda *_args: notices.append(True))

    assert desktop_overlay.desktop_main() == 1
    assert notices == [True]


def test_console_free_agent_entry_loads_settings_and_opens_owned_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = settings(tmp_path)
    calls: list[AppSettings] = []
    monkeypatch.setattr(AppSettings, "from_env", lambda: selected)
    monkeypatch.setattr(desktop_overlay, "launch_desktop_agent", calls.append)

    assert desktop_overlay.agent_desktop_main() == 0
    assert calls == [selected]


def test_console_free_agent_entry_reports_only_a_safe_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notices: list[bool] = []
    monkeypatch.setattr(
        desktop_overlay,
        "launch_desktop_agent",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("example private detail")),
    )
    monkeypatch.setattr(AppSettings, "from_env", lambda: object())
    monkeypatch.setattr(desktop_overlay, "_show_safe_agent_error", lambda *_args: notices.append(True))

    assert desktop_overlay.agent_desktop_main() == 1
    assert notices == [True]


class _InstanceLease:
    def __init__(self, *, close_fails: bool = False) -> None:
        self.close_fails = close_fails
        self.closes = 0

    def close(self) -> None:
        self.closes += 1
        if self.close_fails:
            raise desktop_overlay.WindowsSingleInstanceError(
                "single_instance_release_failed"
            )


def test_agent_launch_primary_owns_exactly_one_runtime_and_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = settings(tmp_path)
    lease = _InstanceLease()
    calls: list[AppSettings] = []
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay, "acquire_windows_instance", lambda _name: lease
    )
    monkeypatch.setattr(desktop_overlay, "run_desktop_agent", calls.append)
    monkeypatch.setattr(
        desktop_overlay,
        "focus_existing_window",
        lambda _title: pytest.fail("a primary launch must not focus another window"),
    )

    desktop_overlay.launch_desktop_agent(selected)

    assert calls == [selected]
    assert lease.closes == 1


@pytest.mark.parametrize("focused", [True, False])
def test_agent_duplicate_focuses_best_effort_without_starting_any_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    focused: bool,
) -> None:
    focus_calls: list[str] = []
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay, "acquire_windows_instance", lambda _name: None
    )
    monkeypatch.setattr(
        desktop_overlay,
        "focus_existing_window",
        lambda title: focus_calls.append(title) or focused,
    )
    monkeypatch.setattr(
        desktop_overlay,
        "run_desktop_agent",
        lambda _settings: pytest.fail("a duplicate must not start a runtime"),
    )

    desktop_overlay.launch_desktop_agent(settings(tmp_path))

    assert focus_calls == [desktop_overlay._AGENT_WINDOW_TITLE]


def test_agent_instance_acquire_failure_is_content_free(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay,
        "acquire_windows_instance",
        lambda _name: (_ for _ in ()).throw(
            desktop_overlay.WindowsSingleInstanceError("SYNTHETIC_PRIVATE_CANARY")
        ),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.launch_desktop_agent(settings(tmp_path))

    assert caught.value.reason_code == "local_state_unavailable"
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_agent_primary_failure_still_releases_lease_and_preserves_safe_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lease = _InstanceLease()
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay, "acquire_windows_instance", lambda _name: lease
    )
    monkeypatch.setattr(
        desktop_overlay,
        "run_desktop_agent",
        lambda _settings: (_ for _ in ()).throw(
            desktop_overlay.DesktopOverlayServiceError(
                "SYNTHETIC_PRIVATE_CANARY", reason_code="service_stop_timeout"
            )
        ),
    )

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.launch_desktop_agent(settings(tmp_path))

    assert lease.closes == 1
    assert caught.value.reason_code == "service_stop_timeout"
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(caught.value)


def test_agent_lease_release_failure_is_not_reported_as_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lease = _InstanceLease(close_fails=True)
    monkeypatch.setattr(desktop_overlay, "sys_platform_is_windows", lambda: True)
    monkeypatch.setattr(
        desktop_overlay, "acquire_windows_instance", lambda _name: lease
    )
    monkeypatch.setattr(desktop_overlay, "run_desktop_agent", lambda _settings: None)

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay.launch_desktop_agent(settings(tmp_path))

    assert lease.closes == 1
    assert caught.value.reason_code == "local_state_unavailable"
