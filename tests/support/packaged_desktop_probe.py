"""Exercise the installed Windows GUI launcher with disposable local state.

Only the ``PACKAGED_DESKTOP_PROBE`` JSON line is supported output. The child
window is hidden and auto-closes; no provider data, model, folder picker or
native approval is used.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


def _entry_target(kind: str) -> tuple[str, str]:
    name = "prompt-enhancer-agent" if kind == "agent" else "prompt-enhancer-desktop"
    expected = (
        "prompt_enhancer.desktop_overlay:agent_desktop_main"
        if kind == "agent"
        else "prompt_enhancer.desktop_overlay:desktop_main"
    )
    distribution = importlib.metadata.distribution("prompt-enhancer")
    matches = [
        entry
        for entry in distribution.entry_points
        if entry.group == "gui_scripts" and entry.name == name
    ]
    if len(matches) != 1 or matches[0].value != expected:
        raise RuntimeError("packaged_entry_mismatch")
    executable = Path(sys.executable).with_name(name + ".exe")
    if not executable.is_file():
        raise RuntimeError("packaged_entry_missing")
    return os.fspath(executable), expected


def _base_environment(root: Path, port: int) -> dict[str, str]:
    keep = {
        "APPDATA",
        "COMSPEC",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in keep}
    provider = root / "empty-provider"
    provider.mkdir()
    application = root / "application"
    models = root / "local-models"
    profile = root / "webview-profile"
    hook = Path(__file__).resolve().parent / "packaged_probe"
    environment.update(
        {
            "HOME": os.fspath(root),
            "USERPROFILE": os.fspath(root),
            "PYTHONPATH": os.fspath(hook),
            "PROMPT_ENHANCER_HOME": os.fspath(application),
            "PROMPT_ENHANCER_HOST": "127.0.0.1",
            "PROMPT_ENHANCER_PORT": str(port),
            "PROMPT_ENHANCER_SESSION_READER": "disabled",
            "PROMPT_ENHANCER_LOCAL_MODELS_DIR": os.fspath(models),
            "PROMPT_ENHANCER_PACKAGED_PROBE": "enabled",
            "PROMPT_ENHANCER_PACKAGED_PROBE_RESULT": os.fspath(root / "probe.json"),
            "PROMPT_ENHANCER_PACKAGED_PROBE_PROFILE": os.fspath(profile),
            "PROMPT_ENHANCER_PACKAGED_PROBE_PROVIDER": os.fspath(provider),
        }
    )
    return environment


def probe(kind: str, *, occupy_configured_port: bool) -> dict[str, object]:
    report: dict[str, object] = {
        "contract": "packaged-desktop-probe.v1",
        "window": kind,
        "entry_target_verified": False,
        "configured_port_occupied": occupy_configured_port,
        "launcher_exit_code": None,
        "window_created": False,
        "document_loaded": False,
        "window_closed": False,
        "timed_out": False,
        "lifecycle_terminal": False,
        "temporary_state_removed": False,
        "error_code": None,
    }
    if sys.platform != "win32":
        report["error_code"] = "unsupported_platform"
        return report
    occupied: socket.socket | None = None
    try:
        executable, _target = _entry_target(kind)
        report["entry_target_verified"] = True
        with tempfile.TemporaryDirectory(prefix="prompt-enhancer-packaged-probe-") as temporary:
            root = Path(temporary)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            if occupy_configured_port:
                occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                occupied.bind(("127.0.0.1", port))
                occupied.listen()
            environment = _base_environment(root, port)
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            child = subprocess.Popen(
                [executable],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            try:
                report["launcher_exit_code"] = child.wait(timeout=40)
            except subprocess.TimeoutExpired:
                report["timed_out"] = True
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            hook_path = root / "probe.json"
            if hook_path.is_file():
                hook = json.loads(hook_path.read_text(encoding="utf-8"))
                if hook.get("contract") == "packaged-native-hook.v1":
                    for key in ("window_created", "document_loaded", "window_closed"):
                        report[key] = hook.get(key) is True
                    report["timed_out"] = report["timed_out"] or hook.get("timed_out") is True
                    if hook.get("error_code") is not None:
                        report["error_code"] = "native_hook_failed"
            marker_name = (
                "native-agent-lifecycle.json"
                if kind == "agent"
                else "native-overlay-lifecycle.json"
            )
            marker_path = root / "application" / "diagnostics" / marker_name
            if marker_path.is_file():
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                report["lifecycle_terminal"] = (
                    marker.get("contract") == "native-lifecycle.v1"
                    and marker.get("window") == kind
                    and marker.get("phase") == "stopped"
                    and marker.get("terminal") is True
                )
        report["temporary_state_removed"] = True
    except Exception:
        report["error_code"] = report["error_code"] or "probe_failed"
    finally:
        if occupied is not None:
            occupied.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=("agent", "overlay"), default="agent")
    parser.add_argument("--occupy-configured-port", action="store_true")
    arguments = parser.parse_args()
    report = probe(
        arguments.window,
        occupy_configured_port=arguments.occupy_configured_port,
    )
    print("PACKAGED_DESKTOP_PROBE=" + json.dumps(report, sort_keys=True), flush=True)
    passed = (
        report.get("entry_target_verified") is True
        and report.get("launcher_exit_code") == 0
        and report.get("window_created") is True
        and report.get("document_loaded") is True
        and report.get("window_closed") is True
        and report.get("timed_out") is False
        and report.get("lifecycle_terminal") is True
        and report.get("temporary_state_removed") is True
        and report.get("error_code") is None
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
