"""Activated only by the disposable packaged-native probe environment.

Python imports ``sitecustomize`` before a generated GUI entry point. This hook
keeps the real packaged WebView hidden, binds it to disposable state, closes it
after the document-loaded event and emits only a fixed synthetic receipt file.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
import threading


if os.environ.get("PROMPT_ENHANCER_PACKAGED_PROBE") == "enabled":
    result_path = Path(os.environ["PROMPT_ENHANCER_PACKAGED_PROBE_RESULT"])
    profile_path = os.environ["PROMPT_ENHANCER_PACKAGED_PROBE_PROFILE"]
    provider_path = Path(os.environ["PROMPT_ENHANCER_PACKAGED_PROBE_PROVIDER"])
    report: dict[str, object] = {
        "contract": "packaged-native-hook.v1",
        "window_created": False,
        "document_loaded": False,
        "window_closed": False,
        "timed_out": False,
        "error_code": None,
    }
    report_lock = threading.Lock()
    timers: list[threading.Timer] = []

    def write_report() -> None:
        with report_lock:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(report, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )

    try:
        logging.disable(logging.CRITICAL)
        import webview

        from prompt_enhancer.bootstrap import LocalApplication

        LocalApplication.claude_home = lambda _self: provider_path

        def forbid_provider_adapter(*_args, **_kwargs):
            raise RuntimeError("synthetic_packaged_probe_provider_access_forbidden")

        LocalApplication.create_codex_adapter = forbid_provider_adapter
        create_window = webview.create_window
        start_webview = webview.start

        def create_probe_window(*args, **kwargs):
            kwargs.update(hidden=True, confirm_close=False)
            window = create_window(*args, **kwargs)
            if window is None:
                report["error_code"] = "window_not_created"
                write_report()
                return None
            report["window_created"] = True
            write_report()

            def loaded() -> None:
                report["document_loaded"] = True
                write_report()
                window.destroy()

            def closed() -> None:
                report["window_closed"] = True
                write_report()

            def expire() -> None:
                if not report["window_closed"]:
                    report["timed_out"] = True
                    write_report()
                    window.destroy()

            window.events.loaded += loaded
            window.events.closed += closed
            timer = threading.Timer(25, expire)
            timer.daemon = True
            timers.append(timer)
            timer.start()
            return window

        def start_probe_webview(*args, **kwargs):
            kwargs.update(private_mode=True, storage_path=profile_path)
            return start_webview(*args, **kwargs)

        webview.create_window = create_probe_window
        webview.start = start_probe_webview

        def finish_probe() -> None:
            for timer in timers:
                timer.cancel()
            write_report()

        atexit.register(finish_probe)
        write_report()
    except Exception:
        report["error_code"] = "probe_setup_failed"
        write_report()
        os._exit(91)
