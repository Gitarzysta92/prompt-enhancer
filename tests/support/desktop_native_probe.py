"""Opt-in Windows native-engine probe using disposable application state.

Run in a subprocess; only the DESKTOP_PROBE JSON line is a supported result.
The native window is hidden and auto-closes after its document-loaded event.
No native approval, folder picking, model inference or owner data is exercised.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
import threading


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def probe(kind: str) -> dict[str, object]:
    report: dict[str, object] = {
        "contract": "desktop-native-probe.v1",
        "window": kind,
        "entry_status": None,
        "window_created": False,
        "document_loaded": False,
        "window_closed": False,
        "listener_released": False,
        "temporary_state_removed": False,
        "timed_out": False,
        "error_code": None,
    }
    if sys.platform != "win32":
        report["error_code"] = "unsupported_platform"
        return report

    # Dependency/native logs may contain local paths. The parent captures and
    # discards all output except the closed, content-free result below.
    logging.disable(logging.CRITICAL)
    from prompt_enhancer import desktop_overlay
    from prompt_enhancer.bootstrap import LocalApplication
    from prompt_enhancer.config import AppSettings

    try:
        import webview
    except Exception:
        report["error_code"] = "dependency_unavailable"
        return report

    class IsolatedSettings(AppSettings):
        @property
        def local_models_dir(self):
            return self.home / "local-models"

    with tempfile.TemporaryDirectory(prefix="prompt-enhancer-native-probe-") as temporary:
        root = Path(temporary)
        provider = root / "empty-provider"
        provider.mkdir()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        selected = IsolatedSettings(
            home=root / "application",
            host="127.0.0.1",
            port=port,
            session_reader_enabled=False,
        )
        AppSettings.from_env = classmethod(lambda _cls, *_args, **_kwargs: selected)
        LocalApplication.claude_home = lambda _self: provider

        def forbid_provider_adapter(*_args, **_kwargs):
            raise RuntimeError("synthetic_probe_provider_access_forbidden")

        LocalApplication.create_codex_adapter = forbid_provider_adapter

        def collect_error(code="desktop_failed", *_args):
            report["error_code"] = (
                code if code in desktop_overlay._FAILURE_MESSAGES else "desktop_failed"
            )

        desktop_overlay._show_safe_agent_error = collect_error
        desktop_overlay._show_safe_desktop_error = collect_error
        create_window = webview.create_window
        start_webview = webview.start
        timers: list[threading.Timer] = []

        def create_probe_window(*args, **kwargs):
            # This is disposable test state, not the owner's desktop window.
            kwargs.update(hidden=True, confirm_close=False)
            window = create_window(*args, **kwargs)
            if window is None:
                return None
            report["window_created"] = True

            def loaded():
                report["document_loaded"] = True
                window.destroy()

            def closed():
                report["window_closed"] = True

            def expire():
                if not report["window_closed"]:
                    report["timed_out"] = True
                    window.destroy()

            window.events.loaded += loaded
            window.events.closed += closed
            timer = threading.Timer(25, expire)
            timer.daemon = True
            timers.append(timer)
            timer.start()
            return window

        def start_probe_webview(*args, **kwargs):
            kwargs.update(private_mode=True, storage_path=str(root / "webview-profile"))
            return start_webview(*args, **kwargs)

        webview.create_window = create_probe_window
        webview.start = start_probe_webview
        try:
            entry = (
                desktop_overlay.agent_desktop_main
                if kind == "agent"
                else desktop_overlay.desktop_main
            )
            report["entry_status"] = entry()
        finally:
            for timer in timers:
                timer.cancel()
        report["listener_released"] = not desktop_overlay._port_is_open("127.0.0.1", port)
    report["temporary_state_removed"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=("agent", "overlay"), default="agent")
    arguments = parser.parse_args()
    try:
        report = probe(arguments.window)
    except Exception:
        report = {"contract": "desktop-native-probe.v1", "error_code": "probe_failed"}
    print("DESKTOP_PROBE=" + json.dumps(report, sort_keys=True), flush=True)
    passed = (
        report.get("entry_status") == 0
        and report.get("document_loaded") is True
        and report.get("window_closed") is True
        and report.get("listener_released") is True
        and report.get("temporary_state_removed") is True
        and report.get("timed_out") is False
        and report.get("error_code") is None
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
