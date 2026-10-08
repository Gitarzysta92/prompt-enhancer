"""Owned desktop lifecycle regressions; all state and failures are fictional."""

from __future__ import annotations

import json
import socket
from types import SimpleNamespace
import urllib.request

import pytest

from prompt_enhancer import desktop_overlay
from prompt_enhancer.config import AppSettings
from prompt_enhancer.privacy import load_or_create_api_token


class _Thread:
    def __init__(self, *, survives: bool, join_fails: bool = False) -> None:
        self.survives = survives
        self.join_fails = join_fails
        self.joins: list[float] = []

    def join(self, *, timeout: float) -> None:
        self.joins.append(timeout)
        if self.join_fails:
            raise OSError("SYNTHETIC_PRIVATE_JOIN_CANARY")

    def is_alive(self) -> bool:
        return self.survives


def _owned(thread: _Thread):
    from prompt_enhancer.application.runtime_lifecycle import RuntimeLifecycleReport

    return desktop_overlay._OwnedServer(
        server=SimpleNamespace(should_exit=False, force_exit=False),
        thread=thread,
        user_presence=desktop_overlay.UserPresenceApprovalManager(),
        readiness_path="/example-readiness",
        lifecycle=RuntimeLifecycleReport(cleanup_finished=True),
    )


def test_owned_stop_rejects_a_thread_that_survives_both_waits() -> None:
    thread = _Thread(survives=True)
    owned = _owned(thread)

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        owned.stop()

    assert caught.value.reason_code == "service_stop_timeout"
    assert thread.joins == [
        desktop_overlay._SERVICE_STOP_TIMEOUT_SECONDS,
        desktop_overlay._SERVICE_FORCE_STOP_TIMEOUT_SECONDS,
    ]
    assert owned.server.should_exit is True
    assert owned.server.force_exit is True


def test_owned_stop_sanitizes_join_failure_and_attempts_forced_cleanup() -> None:
    thread = _Thread(survives=True, join_fails=True)
    owned = _owned(thread)

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        owned.stop()

    assert caught.value.reason_code == "service_stop_failed"
    assert thread.joins == [
        desktop_overlay._SERVICE_STOP_TIMEOUT_SECONDS,
        desktop_overlay._SERVICE_FORCE_STOP_TIMEOUT_SECONDS,
    ]
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)


def test_owned_stop_is_idempotent_after_confirmed_exit() -> None:
    thread = _Thread(survives=False)
    owned = _owned(thread)

    owned.stop()
    owned.stop()

    assert owned.server.should_exit is True
    assert owned.server.force_exit is False


def test_dead_owned_thread_cannot_be_accepted_as_ready(monkeypatch) -> None:
    owned = _owned(_Thread(survives=False))
    monkeypatch.setattr(desktop_overlay, "_verify_service_identity", lambda *_: True)
    monkeypatch.setattr(desktop_overlay, "_verify_owned_service_instance", lambda *_: True)

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        desktop_overlay._wait_for_owned_service(
            (("127.0.0.1", "http://127.0.0.1:18765"),),
            "example_desktop_lifecycle_token_123456789",
            owned,
        )

    assert caught.value.reason_code == "service_exited"


def test_owned_stop_does_not_confuse_listener_exit_with_component_cleanup() -> None:
    from prompt_enhancer.application.runtime_lifecycle import RuntimeComponent

    owned = _owned(_Thread(survives=False))
    owned.lifecycle.shutdown_failures = (RuntimeComponent.LOCAL_MODEL_SERVICE,)

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        owned.stop()

    assert caught.value.reason_code == "runtime_stop_failed"
    assert caught.value.components == ("local_model_service",)


def test_composed_owned_service_can_start_stop_and_restart_without_provider_data(tmp_path) -> None:
    class IsolatedSettings(AppSettings):
        @property
        def local_models_dir(self):
            # Do not use any owner override or model registry in this check.
            return self.home / "local-models"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    settings = IsolatedSettings(
        home=tmp_path / "example-application",
        host="127.0.0.1",
        port=port,
        session_reader_enabled=False,
    )
    endpoints = desktop_overlay._exact_loopback_endpoints(settings.host, port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    for force_exit in (False, True, False):
        owned = desktop_overlay._start_owned_server(settings)
        try:
            token = load_or_create_api_token(settings.api_token_path)
            origin = desktop_overlay._wait_for_owned_service(endpoints, token, owned)
            with opener.open(f"{origin}/health", timeout=3) as response:
                assert response.status == 200
                assert json.load(response) == {
                    "status": "ok",
                    "cost_mode": "offline_only",
                    "data_tier": "metadata",
                }
            assert owned.lifecycle.startup_failure is None
        finally:
            if force_exit:
                owned.server.force_exit = True
            owned.stop()
        assert not owned.thread.is_alive()
        assert not desktop_overlay._port_is_open("127.0.0.1", port)
        assert owned.lifecycle.shutdown_failures == ()
        assert owned.lifecycle.cleanup_finished is True
        assert all(
            worker is None or not worker.is_alive()
            for _name, worker in owned.server.config.app.state.runtime_workers
        )


def test_reserved_listener_closes_the_check_then_bind_race(tmp_path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    settings = AppSettings(home=tmp_path, host="127.0.0.1", port=port)

    listener, selected, endpoints = desktop_overlay._reserve_owned_listener(
        settings,
        allow_ephemeral=False,
    )
    try:
        assert selected.port == port
        assert endpoints == (("127.0.0.1", f"http://127.0.0.1:{port}"),)
        competitor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError):
                competitor.bind(("127.0.0.1", port))
        finally:
            competitor.close()
    finally:
        listener.close()


def test_agent_reservation_uses_ephemeral_loopback_when_configured_port_is_owned(
    tmp_path,
) -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    configured_port = occupied.getsockname()[1]
    settings = AppSettings(
        home=tmp_path,
        host="127.0.0.1",
        port=configured_port,
    )
    try:
        with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
            desktop_overlay._reserve_owned_listener(settings, allow_ephemeral=False)
        assert caught.value.reason_code == "port_in_use"

        listener, selected, endpoints = desktop_overlay._reserve_owned_listener(
            settings,
            allow_ephemeral=True,
        )
        try:
            assert selected.port != configured_port
            assert selected.host == "127.0.0.1"
            assert endpoints == (
                ("127.0.0.1", f"http://127.0.0.1:{selected.port}"),
            )
        finally:
            listener.close()
    finally:
        occupied.close()


def test_composed_agent_fallback_does_not_attach_to_the_occupied_listener(tmp_path) -> None:
    class IsolatedSettings(AppSettings):
        @property
        def local_models_dir(self):
            return self.home / "local-models"

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    configured_port = occupied.getsockname()[1]
    settings = IsolatedSettings(
        home=tmp_path / "example-application",
        host="127.0.0.1",
        port=configured_port,
        session_reader_enabled=False,
    )
    owned = desktop_overlay._start_owned_server(settings, allow_ephemeral=True)
    try:
        token = load_or_create_api_token(settings.api_token_path)
        origin = desktop_overlay._wait_for_owned_service(owned.endpoints, token, owned)
        assert origin != f"http://127.0.0.1:{configured_port}"
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"{origin}/health",
            timeout=3,
        ) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "ok"
        assert occupied.fileno() >= 0
    finally:
        owned.stop()
        occupied.close()
    assert not desktop_overlay._port_is_open(
        owned.endpoints[0][0],
        int(owned.endpoints[0][1].rsplit(":", 1)[1]),
    )


def test_primary_window_failure_is_not_replaced_by_cleanup_failure() -> None:
    owned = _owned(_Thread(survives=True))

    def fail_window() -> None:
        raise RuntimeError("SYNTHETIC_PRIVATE_NATIVE_CANARY")

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay._run_with_owned_cleanup(owned, fail_window)

    assert caught.value.reason_code == "window_start_failed"
    assert caught.value.cleanup_reason_code == "service_stop_timeout"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


def test_native_notice_rejects_arbitrary_codes_and_component_text() -> None:
    notice = desktop_overlay._failure_notice(
        "SYNTHETIC_PRIVATE_CODE_CANARY",
        ("SYNTHETIC_PRIVATE_COMPONENT_CANARY",),
        "SYNTHETIC_PRIVATE_CLEANUP_CANARY",
    )
    assert "desktop_failed" in notice
    assert "SYNTHETIC_PRIVATE" not in notice


def test_native_notice_can_distinguish_component_cleanup_failure() -> None:
    from prompt_enhancer.application.runtime_lifecycle import RuntimeComponent

    notice = desktop_overlay._failure_notice(
        "window_start_failed",
        (RuntimeComponent.LOCAL_MODEL_SERVICE,),
        "runtime_stop_failed",
    )
    assert "window_start_failed" in notice
    assert "local_model_service" in notice
    assert "runtime_stop_failed" in notice


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError("SYNTHETIC_PRIVATE_CANARY"), "desktop_failed"),
        (ImportError("SYNTHETIC_PRIVATE_CANARY"), "dependency_unavailable"),
        (PermissionError("SYNTHETIC_PRIVATE_CANARY"), "local_state_unavailable"),
    ],
)
def test_native_diagnostic_classification_does_not_render_exception_text(error, code) -> None:
    safe = desktop_overlay._safe_desktop_failure(error)
    assert safe.reason_code == code
    assert "SYNTHETIC_PRIVATE" not in str(safe)
    assert safe.__context__ is None


def test_console_free_agent_error_contains_a_safe_specific_reason(monkeypatch) -> None:
    captured: list[tuple[object, ...]] = []

    def occupied(_settings) -> None:
        raise desktop_overlay.DesktopOverlayServiceError(
            "SYNTHETIC_PRIVATE_BIND_CANARY", reason_code="port_in_use"
        )

    monkeypatch.setattr(AppSettings, "from_env", lambda: object())
    monkeypatch.setattr(desktop_overlay, "launch_desktop_agent", occupied)
    monkeypatch.setattr(
        desktop_overlay, "_show_safe_agent_error", lambda *args: captured.append(args)
    )

    assert desktop_overlay.agent_desktop_main() == 1
    assert captured == [("port_in_use", (), None)]


def test_owned_stop_runs_fallback_when_server_skips_lifespan_cleanup() -> None:
    owned = _owned(_Thread(survives=False))
    owned.lifecycle.cleanup_finished = False
    calls: list[str] = []

    def cleanup() -> None:
        calls.append("cleanup")
        owned.lifecycle.cleanup_finished = True

    owned.cleanup_runtime = cleanup
    owned.stop()

    assert calls == ["cleanup"]
    assert owned.lifecycle.cleanup_finished is True


def test_listener_exit_without_cleanup_evidence_is_not_success() -> None:
    owned = _owned(_Thread(survives=False))
    owned.lifecycle.cleanup_finished = False

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        owned.stop()

    assert caught.value.reason_code == "runtime_stop_unconfirmed"


def test_failed_fallback_cleanup_does_not_expose_the_adapter_exception() -> None:
    owned = _owned(_Thread(survives=False))
    owned.lifecycle.cleanup_finished = False

    def fail_cleanup() -> None:
        raise OSError("SYNTHETIC_PRIVATE_CLEANUP_CANARY")

    owned.cleanup_runtime = fail_cleanup
    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        owned.stop()

    assert caught.value.reason_code == "runtime_stop_failed"
    assert caught.value.__context__ is None
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)


def test_marker_publication_failure_does_not_replace_the_primary_native_failure() -> None:
    class Marker:
        def start(self) -> None:
            return None

        def failed(self, *_args, **_kwargs) -> None:
            raise OSError("SYNTHETIC_PRIVATE_MARKER_CANARY")

        def stopped(self) -> None:
            pytest.fail("failed operations cannot publish stopped")

    def fail_operation() -> None:
        raise desktop_overlay.DesktopOverlayServiceError(
            "SYNTHETIC_PRIVATE_PRIMARY_CANARY",
            reason_code="service_not_ready",
        )

    with pytest.raises(desktop_overlay.DesktopOverlayServiceError) as caught:
        desktop_overlay._run_with_lifecycle_marker(Marker(), fail_operation)

    assert caught.value.reason_code == "service_not_ready"
    assert str(caught.value) == desktop_overlay._FAILURE_MESSAGES["service_not_ready"]
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


def test_missing_terminal_marker_is_a_safe_failed_launcher_outcome() -> None:
    class Marker:
        def start(self) -> None:
            return None

        def stopped(self) -> None:
            raise OSError("SYNTHETIC_PRIVATE_MARKER_CANARY")

    with pytest.raises(desktop_overlay.DesktopOverlayError) as caught:
        desktop_overlay._run_with_lifecycle_marker(Marker(), lambda: None)

    assert caught.value.reason_code == "lifecycle_marker_unavailable"
    assert str(caught.value) == desktop_overlay._FAILURE_MESSAGES[
        "lifecycle_marker_unavailable"
    ]
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)
