"""Owned command process controls; only disposable fictional workloads."""

from __future__ import annotations

import io
import subprocess
import sys
from threading import Event, Thread

import pytest

from prompt_enhancer.application import local_command_process as commands
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCleanupUnconfirmed, RuntimeCooperativeStop, runtime_request_scope,
)
from tests.test_agent_command_control import _run_example
from tests.test_local_agent import _wait


def test_output_tail_stays_bounded_before_the_child_finishes():
    reads = 0
    maximum = 0

    class ExamplePipe:
        def read(self, size):
            nonlocal reads, maximum
            maximum = max(maximum, len(tail.data))
            assert size <= 16 * 1024
            reads += 1
            return b"x" * size if reads < 500 else b"EXAMPLE_END" if reads == 500 else b""

        def close(self):
            pass

    tail = commands._OutputTail(ExamplePipe(), "utf-8", "replace")
    tail.drain()
    assert maximum <= 96000
    assert len(tail.text()) <= 24000
    assert tail.text().endswith("EXAMPLE_END")
    assert tail.truncated and not tail.failed


def test_timeout_returns_only_bounded_partial_output_after_verified_cleanup(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired) as failed:
        _run_example(tmp_path, "import sys, time; print('EXAMPLE_PARTIAL', flush=True); time.sleep(5)", timeout=0.5)
    assert "EXAMPLE_PARTIAL" in failed.value.stdout
    assert not any(thread.name.startswith("agent-command-pipe-") for thread in __import__("threading").enumerate())


def test_command_output_truncation_is_visible_and_preserves_the_exit_status(tmp_path):
    command = f'''"{sys.executable}" -I -c "print('x' * 200000 + 'EXAMPLE_TAIL')"'''
    result = WorkspaceTools(tmp_path).run_command(command)
    assert result.ok and result.text.startswith("exit 0")
    assert "[Earlier command output truncated]" in result.text
    assert result.text.endswith("EXAMPLE_TAIL")
    assert len(result.text) <= 24000


def test_native_command_preserves_unicode_output(tmp_path):
    command = f'''"{sys.executable}" -I -X utf8 -c "print(chr(0x17c) + chr(0xf3) + chr(0x142) + chr(0x107) + chr(0x1f33f))"'''
    result = WorkspaceTools(tmp_path).run_command(command)
    assert result.ok
    assert "żółć🌿" in result.text


def test_waiting_command_can_cancel_without_entering_an_owned_lane(tmp_path):
    calls = []
    stopped = Event()
    tools = WorkspaceTools(tmp_path, runner=lambda *_args, **_kwargs: calls.append(True))
    results = []

    def run():
        with runtime_request_scope(stopped):
            results.append(tools.run_command("example-command"))

    tools._command_lock.acquire()
    worker = Thread(target=run, daemon=True)
    try:
        worker.start()
        stopped.set()
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert results[0].code == "tool_cancelled"
        assert not results[0].untracked_command and not calls
    finally:
        tools._command_lock.release()
        worker.join(timeout=1)


def test_workspace_quarantine_cannot_be_reset_by_a_new_command(tmp_path):
    calls = []

    def runner(*_args, **_kwargs):
        calls.append(True)
        raise RuntimeCleanupUnconfirmed("EXAMPLE_PRIVATE_CLEANUP_CANARY")

    tools = WorkspaceTools(tmp_path, runner=runner)
    first = tools.run_command("example-command")
    second = tools.run_command("another-example-command")
    assert first.code == second.code == "command_cleanup_unconfirmed"
    assert first.untracked_command and not second.untracked_command
    assert len(calls) == 1
    assert "EXAMPLE_PRIVATE_CLEANUP_CANARY" not in first.text + second.text


@pytest.mark.parametrize("fault", ["tree-survives", "query-failed", "close-failed", "join-failed"])
def test_uncertain_cleanup_supersedes_cancel_and_still_attempts_every_release(monkeypatch, fault):
    stopped = Event()

    class ExampleProcess:
        stdout, stderr = io.BytesIO(b"example"), io.BytesIO(b"")
        terminated = False
        closed = False

        def poll(self):
            return 0 if self.terminated else None

        def tree_exited(self):
            if fault == "query-failed":
                raise OSError("EXAMPLE_PRIVATE_QUERY_CANARY")
            return fault != "tree-survives"

        def terminate(self):
            self.terminated = True

        def close(self, **_kwargs):
            self.closed = True
            self.stdout.close()
            self.stderr.close()
            return fault != "close-failed"

    process = ExampleProcess()

    def start(*_args, **_kwargs):
        stopped.set()
        return process

    monkeypatch.setattr(commands, "_start_process", start)
    monkeypatch.setattr(commands, "COMMAND_CLEANUP_SECONDS", 0.05)
    if fault == "join-failed":
        class ExampleThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

            def join(self, **_kwargs):
                raise RuntimeError("EXAMPLE_PRIVATE_JOIN_CANARY")

            def is_alive(self):
                return False

        monkeypatch.setattr(commands.threading, "Thread", ExampleThread)
    with runtime_request_scope(stopped), pytest.raises(RuntimeCleanupUnconfirmed) as failed:
        commands.run_with_tree_kill(["example-command"], timeout=1)
    assert str(failed.value) == "command_cleanup_unconfirmed"
    assert failed.value.__context__ is None
    assert process.terminated and process.closed


@pytest.mark.parametrize("failed_worker", [1, 2])
def test_pipe_thread_start_failure_still_reaps_the_real_owned_job(tmp_path, monkeypatch, failed_worker):
    actual_thread = commands.threading.Thread
    actual_start = commands._start_process
    starts = 0
    cleanup = []

    def process_factory(*args, **kwargs):
        process = actual_start(*args, **kwargs)
        close = process.close

        def record_close(**options):
            cleanup.append(process.poll() is not None and process.tree_exited())
            return close(**options)

        process.close = record_close
        return process

    class UnavailableThread:
        def start(self):
            raise RuntimeError("example_pipe_start_failed")

    def thread_factory(*args, **kwargs):
        nonlocal starts
        starts += 1
        return UnavailableThread() if starts == failed_worker else actual_thread(*args, **kwargs)

    monkeypatch.setattr(commands, "_start_process", process_factory)
    monkeypatch.setattr(commands.threading, "Thread", thread_factory)
    with pytest.raises(RuntimeError, match="^example_pipe_start_failed$"):
        _run_example(tmp_path, "import time; time.sleep(5)")
    assert cleanup == [True]


def test_cancelling_one_real_command_does_not_stop_another(tmp_path):
    stops = [Event(), Event()]
    outcomes = []

    def run(index):
        try:
            with runtime_request_scope(stops[index]):
                _run_example(tmp_path, f"from pathlib import Path; import time; Path('example-{index}.ready').touch(); time.sleep(5)")
        except RuntimeCooperativeStop:
            outcomes.append(index)

    workers = [Thread(target=run, args=(index,), daemon=True) for index in range(2)]
    try:
        for worker in workers:
            worker.start()
        assert _wait(lambda: all((tmp_path / f"example-{index}.ready").exists() for index in range(2)), timeout=2)
        stops[0].set()
        workers[0].join(timeout=2)
        assert not workers[0].is_alive()
        assert workers[1].is_alive()
        assert outcomes == [0]
    finally:
        for stop in stops:
            stop.set()
        for worker in workers:
            worker.join(timeout=3)
            assert not worker.is_alive()
    assert sorted(outcomes) == [0, 1]
