"""Disposable real-HTTP dashboard host for opt-in local browser acceptance.

No provider history or owner registry is used. The optional existing GGUF and
runtime are read-only inputs. Stop by creating the reported stop-request file;
a ten-minute deadline also shuts down all owned resources. Never use this as a
normal application launcher or a replacement for native approval testing.
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
import time


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))


def run(model_root: Path, filename: str, lifetime_seconds: int = 600) -> int:
    from prompt_enhancer import desktop_overlay
    from prompt_enhancer.application.local_models import AddLocalModel, DeviceMode, LocalModelService
    from prompt_enhancer.bootstrap import LocalApplication
    from prompt_enhancer.config import AppSettings
    from prompt_enhancer.privacy import load_or_create_api_token

    logging.disable(logging.CRITICAL)
    weights = [path for path in model_root.rglob("*.gguf") if path.name == filename]
    binaries = list(model_root.rglob("llama-server.exe"))
    if len(weights) != 1 or len(binaries) != 1:
        print('WORKFLOW_HOST_ERROR={"code":"model_or_runtime_selection_ambiguous"}', flush=True)
        return 1

    class IsolatedSettings(AppSettings):
        @property
        def local_models_dir(self):
            return self.home / "local-models"

    scratch = REPOSITORY / "test-results"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="browser-workflow-", dir=scratch) as temporary:
        root = Path(temporary)
        workspace = root / "example-workspace"
        workspace.mkdir()
        (workspace / "example.txt").write_text("EXAMPLE_WORKSPACE_OK\n", encoding="utf-8")
        provider = root / "empty-provider"
        provider.mkdir()
        stop_request = root / "stop.request"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        selected = IsolatedSettings(home=root / "application", port=port, session_reader_enabled=False)
        models = LocalModelService(selected.local_models_dir, llama_server=lambda: binaries[0])
        models.add(AddLocalModel(
            alias="example-installed-model", display_name="Example installed local model",
            path=str(weights[0]), default_device=DeviceMode.GPU, context_size=4096,
        ))
        LocalApplication.create_local_model_service = lambda _self: models
        LocalApplication.claude_home = lambda _self: provider

        def forbid_provider_adapter(*_args, **_kwargs):
            raise RuntimeError("synthetic_workflow_provider_access_forbidden")

        LocalApplication.create_codex_adapter = forbid_provider_adapter
        owned = desktop_overlay._start_owned_server(selected)
        try:
            token = load_or_create_api_token(selected.api_token_path)
            endpoints = desktop_overlay._exact_loopback_endpoints(selected.host, port)
            origin = desktop_overlay._wait_for_owned_service(endpoints, token, owned)
            print("WORKFLOW_HOST_READY=" + json.dumps({
                "origin": origin,
                "workspace": str(workspace),
                "model_alias": "example-installed-model",
                "stop_request_path": str(stop_request),
                "expires_after_seconds": lifetime_seconds,
            }), flush=True)
            deadline = time.monotonic() + lifetime_seconds
            while not stop_request.exists() and owned.thread.is_alive() and time.monotonic() < deadline:
                threading.Event().wait(0.25)
        finally:
            try:
                owned.stop()
            finally:
                models.shutdown()
        stopped = {
            "listener_released": not desktop_overlay._port_is_open("127.0.0.1", port),
            "model_runtimes_remaining": len(models.running_aliases()),
            "cleanup_confirmed": owned.lifecycle.cleanup_finished and not owned.lifecycle.shutdown_failures,
        }
    stopped["temporary_state_removed"] = not root.exists()
    print("WORKFLOW_HOST_STOPPED=" + json.dumps(stopped), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--lifetime-seconds", type=int, default=600, choices=range(1, 601), metavar="1..600")
    arguments = parser.parse_args()
    try:
        return run(arguments.model_root, arguments.model_file, arguments.lifetime_seconds)
    except Exception:
        print('WORKFLOW_HOST_ERROR={"code":"isolated_workflow_host_failed"}', flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
