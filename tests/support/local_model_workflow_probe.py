"""Opt-in real GGUF integration with a disposable registry and fictional files.

The supplied model/runtime are read-only inputs, never copied or downloaded.
No provider sessions, owner registry/configuration, credentials or network
fetches are used. Only content-free results are printed; cleanup is mandatory.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time


REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))


def phase(name: str) -> None:
    print("MODEL_PROBE_PHASE=" + json.dumps({"phase": name}), flush=True)


def probe(model_root: Path, filename: str) -> dict[str, object]:
    from prompt_enhancer.application.local_agent import (
        AgentModelParameters, AgentSettings, LocalAgentService, SendMessage,
    )
    import prompt_enhancer.application.local_models as model_module
    from prompt_enhancer.application.local_models import (
        ActivateLocalModel, AddLocalModel, DeviceMode, LocalModelError,
        LocalModelService, RuntimeState,
    )

    report: dict[str, object] = {
        "contract": "local-model-workflow-probe.v2",
        "model_identity": "existing-local-file-not-product-certified",
        "activated": False,
        "direct_reply_verified": False,
        "agent_session_created": False,
        "agent_read_tool_verified": False,
        "agent_reply_verified": False,
        "stream_observed_before_stop": False,
        "stop_completed_promptly": False,
        "runtime_window_hidden": False,
        "coordinator_idle_after_unload": False,
        "process_exit_confirmed": False,
        "gpu_cleanup_state": "unknown",
        "gpu_cleanup_verified": False,
        "conversation_retained_after_unload": False,
        "send_rejected_after_unload": False,
        "owned_runtime_exited": False,
        "temporary_state_removed": False,
        "timed_out": False,
        "error_code": None,
    }
    weights = [path for path in model_root.rglob("*.gguf") if path.name == filename]
    binaries = list(model_root.rglob("llama-server.exe"))
    if len(weights) != 1 or len(binaries) != 1:
        report["error_code"] = "model_or_runtime_selection_ambiguous"
        return report
    logging.disable(logging.CRITICAL)
    model_module.CHAT_TIMEOUT_SECONDS = 75
    scratch = REPOSITORY / "test-results"
    scratch.mkdir(exist_ok=True)
    alias = "example-installed-model"

    with tempfile.TemporaryDirectory(prefix="local-model-probe-", dir=scratch) as temporary:
        root = Path(temporary)
        workspace = root / "example-workspace"
        workspace.mkdir()
        (workspace / "example.txt").write_text("EXAMPLE_WORKSPACE_OK\n", encoding="utf-8")
        models = LocalModelService(
            root / "isolated-model-registry",
            llama_server=lambda: binaries[0],
            health_timeout_seconds=90,
        )
        agent = LocalAgentService(
            chat=models.chat,
            open_chat=models.open_chat,
            active_model=lambda: alias if alias in models.running_aliases() else None,
            model_ready=lambda selected: models.status(selected).runtime.state is RuntimeState.RUNNING,
            allowed_roots=(workspace,),
        )
        handles = ()
        sessions: list[str] = []

        def watchdog() -> None:
            report["timed_out"] = True
            try:
                models.shutdown()
            except Exception:
                pass

        timer = threading.Timer(300, watchdog)
        timer.daemon = True
        timer.start()
        try:
            models.add(AddLocalModel(alias=alias, path=str(weights[0]), context_size=4096))
            phase("activate")
            activated = models.activate(alias, ActivateLocalModel(
                device=DeviceMode.GPU, gpu_layers=999, context_size=4096, remember=False,
            ))
            report["activated"] = activated.runtime.state is RuntimeState.RUNNING
            handles = tuple(models._processes.values())
            report["runtime_window_hidden"] = bool(handles) and all(
                not handle.process.visible_window_detected() for handle in handles
            )
            phase("direct_reply")
            status, payload, _ = models.chat(alias, json.dumps({
                "messages": [{"role": "user", "content": "Reply with exactly LOCAL_READY and no other text."}],
                "max_tokens": 64,
                "temperature": 0,
                "chat_template_kwargs": {"enable_thinking": False},
            }).encode())
            if status == 200:
                message = json.loads(payload)["choices"][0]["message"].get("content")
                report["direct_reply_verified"] = isinstance(message, str) and message.strip() == "LOCAL_READY"

            phase("agent_file_read")
            session = agent.create(AgentSettings(
                workspace=str(workspace), model_alias=alias,
                allow_writes=False, allow_commands=False, allow_web=False, max_steps=3,
                parameters=AgentModelParameters(max_tokens=256, temperature=0, enable_thinking=False),
            ))
            sessions.append(session.session_id)
            report["agent_session_created"] = any(item.session_id == session.session_id for item in agent.list())
            agent.send(session.session_id, SendMessage(
                text="Use read_file to read example.txt in this workspace, then reply with only the marker it contains. Do not write files, run commands or fetch URLs."
            ))
            deadline = time.monotonic() + 110
            cursor = 0
            while agent.get(session.session_id).running and time.monotonic() < deadline:
                events = agent.wait_events(session.session_id, after=cursor, timeout=0.5)
                cursor = events.last_seq
            events = agent.events(session.session_id, limit=500).events
            report["agent_read_tool_verified"] = any(
                item.kind == "tool_result" and item.tool == "read_file" and item.ok is True
                for item in events
            )
            report["agent_reply_verified"] = any(
                item.kind == "assistant" and (item.text or "").strip() == "EXAMPLE_WORKSPACE_OK"
                for item in events
            )

            phase("stream_stop")
            if not agent.get(session.session_id).running:
                cursor = agent.get(session.session_id).last_seq
                agent.send(session.session_id, SendMessage(
                    text="Count upward from 1 to 10000, writing one number per line. Do not use tools."
                ))
                deadline = time.monotonic() + 75
                while agent.get(session.session_id).running and time.monotonic() < deadline:
                    page = agent.wait_events(session.session_id, after=cursor, timeout=0.5)
                    cursor = page.last_seq
                    if any(item.kind == "assistant_delta" for item in page.events):
                        report["stream_observed_before_stop"] = True
                        break
                stop_started = time.monotonic()
                stopper = threading.Thread(target=agent.stop, args=(session.session_id,), daemon=True)
                stopper.start()
                stopper.join(timeout=5)
                deadline = stop_started + 5
                while agent.get(session.session_id).running and time.monotonic() < deadline:
                    threading.Event().wait(0.05)
                report["stop_completed_promptly"] = not stopper.is_alive() and not agent.get(session.session_id).running

            phase("unload")
            models.deactivate(alias)
            coordinator = models.coordinator_status()
            report["coordinator_idle_after_unload"] = (
                coordinator.state.value == "idle"
                and coordinator.served is None
                and coordinator.active_requests == 0
            )
            report["process_exit_confirmed"] = coordinator.cleanup.process_exit_confirmed
            report["gpu_cleanup_state"] = coordinator.cleanup.state.value
            used_gpu = (activated.runtime.gpu_layers or 0) > 0
            report["gpu_cleanup_verified"] = (
                coordinator.cleanup.state.value == "measured"
                if used_gpu
                else coordinator.cleanup.state.value == "not_required"
            )
            report["conversation_retained_after_unload"] = agent.get(session.session_id).turns >= 1
            try:
                agent.send(session.session_id, SendMessage(text="Example blocked message after unload."))
            except Exception as error:
                report["send_rejected_after_unload"] = getattr(error, "code", None) == "model_not_ready"
        except LocalModelError as error:
            report["error_code"] = error.code if error.code in {
                "runtime_not_healthy", "runtime_unavailable", "runtime_unreachable", "runtime_spawn_failed",
                "runtime_shutdown_in_progress", "runtime_stop_failed", "runtime_shutdown_failed",
                "runtime_cleanup_unconfirmed", "runtime_quarantined",
            } else "model_probe_failed"
        except Exception:
            report["error_code"] = "workflow_probe_failed"
        finally:
            phase("cleanup")
            timer.cancel()
            try:
                models.shutdown()
            finally:
                for session_id in sessions:
                    agent.delete(session_id)
                report["owned_runtime_exited"] = bool(handles) and all(
                    handle.process.poll() is not None for handle in handles
                )
    report["temporary_state_removed"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--model-file", required=True)
    arguments = parser.parse_args()
    try:
        report = probe(arguments.model_root, arguments.model_file)
    except Exception:
        report = {"contract": "local-model-workflow-probe.v2", "error_code": "probe_cleanup_failed"}
    print("MODEL_PROBE=" + json.dumps(report, sort_keys=True), flush=True)
    required = (
        "activated", "direct_reply_verified", "agent_session_created", "agent_read_tool_verified",
        "agent_reply_verified", "stream_observed_before_stop", "stop_completed_promptly",
        "runtime_window_hidden", "coordinator_idle_after_unload", "process_exit_confirmed",
        "gpu_cleanup_verified",
        "conversation_retained_after_unload", "send_rejected_after_unload", "owned_runtime_exited",
        "temporary_state_removed",
    )
    return 0 if all(report.get(key) is True for key in required) and report.get("timed_out") is False and report.get("error_code") is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
