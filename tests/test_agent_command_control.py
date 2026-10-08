"""Synthetic command ownership: Stop, bounded output, and sealed cleanup truth."""

from __future__ import annotations

import json
import subprocess
import sys
from threading import Event, Thread
import time

import pytest

from prompt_enhancer.application.local_agent import (
    AgentSettings, ApprovalDecision, LocalAgentService, SendMessage,
)
from prompt_enhancer.application.local_agent_workspace import (
    WorkspaceTools, minimal_environment, run_with_tree_kill,
)
from prompt_enhancer.application.local_agent_editor import (
    WORKSPACE_APPLY_CONFIRMATION, WorkspaceApplyCommand, WorkspacePreviewCommand,
)
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCleanupUnconfirmed, RuntimeCooperativeStop,
    current_runtime_cancellation, runtime_request_scope,
)
from tests.test_local_agent import _stub_model, _wait


def _run_example(tmp_path, program, *, timeout=5):
    return run_with_tree_kill(
        [sys.executable, "-I", "-c", program], cwd=str(tmp_path),
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        errors="replace", encoding="utf-8", env=minimal_environment(), timeout=timeout,
    )


def test_cancelled_command_is_rejected_before_the_runner_is_called(tmp_path):
    calls = []

    def runner(argv, **_kwargs):
        calls.append(True)
        return subprocess.CompletedProcess(argv, 0, "example", "")

    stopped = Event()
    stopped.set()
    with runtime_request_scope(stopped):
        outcome = WorkspaceTools(tmp_path, runner=runner).run_command("example-command")
    assert not outcome.ok and outcome.code == "tool_cancelled"
    assert not calls
    assert not outcome.untracked_command


def test_real_command_observes_its_cancellation_while_silent(tmp_path):
    stopped = Event()
    ready = tmp_path / "example-command.ready"
    failures = []

    def cancel():
        if _wait(ready.exists, timeout=3):
            stopped.set()
        else:
            failures.append("example_child_not_ready")

    caller = Thread(target=cancel, daemon=True)
    caller.start()
    started = time.monotonic()
    try:
        with runtime_request_scope(stopped), pytest.raises(RuntimeCooperativeStop):
            _run_example(tmp_path, "from pathlib import Path; import time; Path('example-command.ready').touch(); time.sleep(2)")
        assert time.monotonic() - started < 1.8
        assert not failures
    finally:
        caller.join(timeout=4)
        assert not caller.is_alive()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_command_retains_only_a_bounded_output_tail(tmp_path, stream):
    result = _run_example(tmp_path, f"import sys; sys.{stream}.write('x' * 200000 + 'EXAMPLE_TAIL')")
    output = getattr(result, stream)
    assert result.returncode == 0
    assert len(output) <= 24000
    assert output.endswith("EXAMPLE_TAIL")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows owned-job acceptance")
def test_shell_exit_does_not_mean_its_detached_stdio_child_has_finished(tmp_path):
    import ctypes
    from ctypes import wintypes

    result = _run_example(tmp_path, (
        "import subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(1)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "print(child.pid, flush=True)"
    ))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, int(result.stdout.strip()))
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.WaitForSingleObject(handle, 3000)
            kernel.CloseHandle(handle)


def test_approved_command_inherits_turn_cancellation_without_another_model_step(tmp_path):
    entered, release = Event(), Event()
    observed = []

    def runner(argv, **_kwargs):
        cancellation = current_runtime_cancellation()
        observed.append(cancellation)
        entered.set()
        release.wait(2)
        return subprocess.CompletedProcess(argv, 0, "example late output", "")

    chat, calls = _stub_model([{"tool_calls": [{"id": "example-call", "type": "function", "function": {
        "name": "run_command", "arguments": json.dumps({"command": "example-command"}),
    }}]}])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", runner=runner)
    view = service.create(AgentSettings(workspace=str(tmp_path), allow_commands=True))
    try:
        service.send(view.session_id, SendMessage(text="Run the example check."))
        assert _wait(lambda: service.get(view.session_id).pending_approval_id is not None)
        assert not entered.is_set()
        service.approve(view.session_id, service.get(view.session_id).pending_approval_id, ApprovalDecision(approved=True))
        assert entered.wait(2)
        service.stop(view.session_id)
        release.set()
        assert _wait(lambda: not service.get(view.session_id).running)
        assert observed[0] is not None and observed[0].is_set()
        events = service.events(view.session_id).events
        result = next(item for item in events if item.kind == "tool_result")
        assert result.tool_state == "cancelled" and result.ok is False
        assert result.execution_receipt is not None
        assert result.execution_receipt.approval_state == "approved"
        assert result.execution_receipt.evidence_state == "untracked_external_effect"
        summary = events[-1].turn_summary
        assert summary.status == "stopped"
        assert summary.tools_cancelled == 1 and summary.tools_succeeded == 0
        assert summary.untracked_command_calls == 1
        assert len(calls) == 1
    finally:
        release.set()
        service.shutdown(timeout=3)


def test_unconfirmed_command_cleanup_cannot_become_successful_followup_chat(tmp_path):
    def runner(*_args, **_kwargs):
        raise RuntimeCleanupUnconfirmed("EXAMPLE_PRIVATE_CLEANUP_CANARY")

    chat, calls = _stub_model([{"tool_calls": [{"id": "example-call", "type": "function", "function": {
        "name": "run_command", "arguments": json.dumps({"command": "example-command"}),
    }}]}])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", runner=runner)
    view = service.create(AgentSettings(workspace=str(tmp_path), allow_commands=True))
    service.send(view.session_id, SendMessage(text="Run the example check."))
    assert _wait(lambda: service.get(view.session_id).pending_approval_id is not None)
    service.approve(view.session_id, service.get(view.session_id).pending_approval_id, ApprovalDecision(approved=True))
    assert _wait(lambda: not service.get(view.session_id).running)
    events = service.events(view.session_id).events
    assert len(calls) == 1
    assert events[-1].turn_summary.status == "failed"
    assert events[-1].turn_summary.reason == "command_cleanup_unconfirmed"
    assert "EXAMPLE_PRIVATE_CLEANUP_CANARY" not in str(events)
    assert getattr(service.get(view.session_id), "cleanup_unconfirmed", False) is True
    assert service.get(view.session_id).closing
    assert service.events(view.session_id).cleanup_unconfirmed
    result = next(item for item in events if item.kind == "tool_result")
    assert result.tool_state == "unverified"
    assert result.execution_receipt is not None
    assert result.execution_receipt.approval_state == "approved"
    assert result.execution_receipt.evidence_state == "untracked_external_effect"
    for action in (
        lambda: service.send(view.session_id, SendMessage(text="Another example request.")),
        lambda: service.create(AgentSettings(workspace=str(tmp_path))),
        lambda: service.delete(view.session_id),
    ):
        with pytest.raises(ValueError, match="^command_cleanup_unconfirmed$"):
            action()
    with pytest.raises(RuntimeError, match="^agent_shutdown_incomplete$"):
        service.shutdown(timeout=1)
    assert len(calls) == 1


def test_cleanup_quarantine_denies_other_pending_actions_and_manual_apply(tmp_path):
    def runner(*_args, **_kwargs):
        raise RuntimeCleanupUnconfirmed("EXAMPLE_PRIVATE_CLEANUP_CANARY")

    chat, calls = _stub_model([
        {"tool_calls": [{"id": "example-command", "type": "function", "function": {
            "name": "run_command", "arguments": json.dumps({"command": "example-check"}),
        }}]},
        {"tool_calls": [{"id": "example-write", "type": "function", "function": {
            "name": "write_file", "arguments": json.dumps({"path": "example-new.txt", "content": "example"}),
        }}]},
    ])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", runner=runner)
    first, second = [service.create(AgentSettings(workspace=str(tmp_path))) for _ in range(2)]
    existing = tmp_path / "example-existing.txt"
    existing.write_text("before\n", encoding="utf-8")
    file = service.workspace_file(second.session_id, existing.name)
    edit = WorkspacePreviewCommand(path=existing.name, content="after\n", expected_revision=file.revision, line_ending=file.line_ending)
    preview = service.preview_workspace_edit(second.session_id, edit)
    apply = WorkspaceApplyCommand(**edit.model_dump(), proposed_revision=preview.proposed_revision, confirmation=WORKSPACE_APPLY_CONFIRMATION)
    try:
        service.send(first.session_id, SendMessage(text="Run the fictional check."))
        assert _wait(lambda: service.get(first.session_id).pending_approval_id is not None)
        service.send(second.session_id, SendMessage(text="Propose a fictional write."))
        assert _wait(lambda: service.get(second.session_id).pending_approval_id is not None)
        other_pending = service._session(second.session_id).pending
        service.approve(first.session_id, service.get(first.session_id).pending_approval_id, ApprovalDecision(approved=True))
        assert _wait(lambda: all(not view.running for view in service.list()))
        assert other_pending.decided.is_set() and other_pending.approved is False
        assert all(view.cleanup_unconfirmed and view.closing and view.pending_approval_id is None for view in service.list())
        assert all(service.events(view.session_id).events[-1].turn_summary.reason == "command_cleanup_unconfirmed" for view in service.list())
        assert not (tmp_path / "example-new.txt").exists()
        assert existing.read_text(encoding="utf-8") == "before\n"
        for operation in (
            lambda: service.approve(second.session_id, other_pending.approval_id, ApprovalDecision(approved=True)),
            lambda: service.preview_workspace_edit(second.session_id, edit),
            lambda: service.apply_workspace_edit(second.session_id, preview.preview_id, apply),
        ):
            with pytest.raises(ValueError, match="^command_cleanup_unconfirmed$"):
                operation()
        assert len(calls) == 2
    finally:
        with pytest.raises(RuntimeError, match="^agent_shutdown_incomplete$"):
            service.shutdown(timeout=2)


@pytest.mark.parametrize("boundary", ["stop", "delete", "shutdown"])
def test_real_approved_command_is_reaped_before_turn_or_session_finishes(tmp_path, boundary):
    ready = tmp_path / "example-approved.ready"
    command = f'''"{sys.executable}" -I -c "from pathlib import Path; import time; Path('example-approved.ready').touch(); time.sleep(10)"'''
    chat, calls = _stub_model([{"tool_calls": [{"id": "example-call", "type": "function", "function": {
        "name": "run_command", "arguments": json.dumps({"command": command}),
    }}]}])
    service = LocalAgentService(chat=chat, active_model=lambda: "example-model")
    view = service.create(AgentSettings(workspace=str(tmp_path), command_timeout_seconds=5))
    internal = service._session(view.session_id)
    try:
        service.send(view.session_id, SendMessage(text="Run the disposable example command."))
        assert _wait(lambda: service.get(view.session_id).pending_approval_id is not None)
        assert not ready.exists()
        service.approve(view.session_id, service.get(view.session_id).pending_approval_id, ApprovalDecision(approved=True))
        assert _wait(ready.exists, timeout=3)
        started = time.monotonic()
        if boundary == "shutdown":
            service.shutdown(timeout=2)
        else:
            getattr(service, boundary)(view.session_id)
        assert _wait(lambda: not internal.running, timeout=2)
        internal.thread.join(timeout=2)
        assert not internal.thread.is_alive()
        assert time.monotonic() - started < 3
        summary = internal.events[-1].turn_summary
        assert summary.status == "stopped" and summary.tools_cancelled == 1
        assert summary.tools_succeeded == 0 and summary.untracked_command_calls == 1
        assert not internal.cleanup_unconfirmed
        assert len(calls) == 1
    finally:
        internal.request_cancelled.set()
        internal.stop_requested = True
        if internal.thread is not None:
            internal.thread.join(timeout=7)
            assert not internal.thread.is_alive()
        service.shutdown(timeout=2)


def test_command_cleanup_uncertainty_wins_over_a_simultaneous_stop(tmp_path):
    chat, calls = _stub_model([{"tool_calls": [
        {"id": "example-first", "type": "function", "function": {"name": "run_command", "arguments": '{"command":"example-command"}'}},
        {"id": "example-later", "type": "function", "function": {"name": "write_file", "arguments": '{"path":"example-not-written.txt","content":"example"}'}},
    ]}])

    def runner(*_args, **_kwargs):
        service.stop(view.session_id)
        raise RuntimeCleanupUnconfirmed("EXAMPLE_PRIVATE_CLEANUP_CANARY")

    service = LocalAgentService(chat=chat, active_model=lambda: "example-model", runner=runner)
    view = service.create(AgentSettings(workspace=str(tmp_path)))
    service.send(view.session_id, SendMessage(text="Run the disposable example sequence."))
    assert _wait(lambda: service.get(view.session_id).pending_approval_id is not None)
    service.approve(view.session_id, service.get(view.session_id).pending_approval_id, ApprovalDecision(approved=True))
    assert _wait(lambda: not service.get(view.session_id).running)
    summary = service.events(view.session_id).events[-1].turn_summary
    assert summary.status == "failed" and summary.reason == "command_cleanup_unconfirmed"
    assert summary.tools_unverified == 1 and summary.tools_cancelled == 1
    assert not (tmp_path / "example-not-written.txt").exists()
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="^agent_shutdown_incomplete$"):
        service.shutdown(timeout=1)
