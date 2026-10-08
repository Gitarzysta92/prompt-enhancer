"""Synthetic child processes cover job I/O before model code is involved."""

from dataclasses import replace
import sys
from threading import Event, Thread
import time

import pytest

from prompt_enhancer.infrastructure.text_models import model_ensemble


def _example_child(tmp_path, monkeypatch, source):
    script = tmp_path / "scripts" / "run_local_model_ensemble_expert.py"
    script.parent.mkdir()
    script.write_text(source, encoding="utf-8")
    monkeypatch.setattr(model_ensemble, "repository_root", lambda: tmp_path)
    owned = []
    launched = Event()
    start_owned = model_ensemble._start_ensemble_process

    def capture(command, *, root, environment):
        process = start_owned(command, root=root, environment=environment)
        if len(command) > 1 and command[1] == str(script):
            owned.append(process)
            launched.set()
        return process

    monkeypatch.setattr(model_ensemble, "_start_ensemble_process", capture)
    spec = replace(model_ensemble.ensemble_expert_specs()[6], cache_root=tmp_path / "example-cache")
    return spec, owned, launched


def _finish_owned(owned, caller=None):
    exited = []
    for process in owned:
        try:
            running = process.poll() is None
        except OSError:
            running = False
        if running:
            assert model_ensemble._terminate_ensemble_process_tree(process, environment=model_ensemble._process_control_environment())
    if caller is not None:
        caller.join(timeout=2)
        assert not caller.is_alive()
    for process in owned:
        try:
            exited.append(process.poll() is not None)
        except OSError:
            # Production ownership closes the native process and Job handles
            # only after positive tree-exit evidence has been collected.
            exited.append(True)
    assert all(exited)


@pytest.mark.parametrize("exit_code", [1, 2])
def test_failed_child_exit_cannot_supply_a_completed_model_result(tmp_path, monkeypatch, exit_code):
    spec, owned, _ = _example_child(tmp_path, monkeypatch, f"import sys\nsys.stdin.buffer.read()\nprint('{{\"status\":\"completed\"}}', flush=True)\nsys.exit({exit_code})\n")
    try:
        with pytest.raises(model_ensemble.ModelEnsembleError, match="^model_ensemble_subprocess_failed$"):
            model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu", python_executable=sys.executable)
    finally:
        _finish_owned(owned)


def test_oversized_live_output_is_stopped_before_the_overall_timeout(tmp_path, monkeypatch):
    spec, owned, launched = _example_child(tmp_path, monkeypatch,
        "import sys,time\nsys.stdin.buffer.read()\nsys.stdout.buffer.write(b'x' * (4 * 1024 * 1024 + 1))\nsys.stdout.buffer.flush()\ntime.sleep(10)\n")
    result = []

    def run():
        try:
            model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu", timeout_seconds=5)
        except Exception as error:
            result.append(error)

    caller = Thread(target=run, name="example-output-bound")
    caller.start()
    try:
        assert launched.wait(2)
        caller.join(timeout=1.5)
        assert not caller.is_alive(), "The output limit did not stop a still-running child"
        assert len(result) == 1 and result[0].args == ("model_ensemble_output_invalid",)
    finally:
        _finish_owned(owned, caller)


@pytest.mark.parametrize("boundary", ["timeout", "cancellation"])
def test_unread_child_stdin_cannot_hide_deadlines_or_cancellation(tmp_path, monkeypatch, boundary):
    spec, owned, launched = _example_child(tmp_path, monkeypatch, "import time\ntime.sleep(10)\n")
    result = []
    requested = Event()

    class ExampleCancelled(RuntimeError):
        pass

    def heartbeat():
        if requested.is_set():
            raise ExampleCancelled("example_cancelled")

    def run():
        try:
            model_ensemble.run_ensemble_expert_subprocess(
                spec, "scope_nli", {"example": "x" * 131_072}, "cpu",
                heartbeat=heartbeat, timeout_seconds=0.2 if boundary == "timeout" else 5,
            )
        except Exception as error:
            result.append(error)

    caller = Thread(target=run, name="example-blocked-model-input")
    caller.start()
    try:
        assert launched.wait(2)
        if boundary == "cancellation":
            requested.set()
        started = time.monotonic()
        caller.join(timeout=1.5)
        assert not caller.is_alive(), "Input upload hid the cancellation/deadline check"
        assert time.monotonic() - started < 1.5
        assert len(result) == 1
        expected = "model_ensemble_subprocess_timeout" if boundary == "timeout" else "example_cancelled"
        assert result[0].args == (expected,)
    finally:
        _finish_owned(owned, caller)


def test_ordinary_completed_child_remains_usable(tmp_path, monkeypatch):
    spec, owned, _ = _example_child(tmp_path, monkeypatch,
        "import json,sys\npayload=json.load(sys.stdin)\nprint(json.dumps({'status':'completed','example_count':len(payload['example'])}),flush=True)\n")
    try:
        result = model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"example": "x" * 131_072}, "cpu", timeout_seconds=2)
        assert result == {"status": "completed", "example_count": 131_072}
    finally:
        _finish_owned(owned)


def test_documented_failed_exit_retains_its_resource_failure_receipt(tmp_path, monkeypatch):
    spec, owned, _ = _example_child(tmp_path, monkeypatch,
        "import sys\nsys.stdin.buffer.read()\nprint('{\"status\":\"failed\",\"error_code\":\"resource_exhausted\"}',flush=True)\nsys.exit(2)\n")
    try:
        result = model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu")
        assert result == {"status": "failed", "error_code": "resource_exhausted"}
    finally:
        _finish_owned(owned)


def test_cancellation_with_final_bytes_is_not_misclassified_as_cleanup_failure(tmp_path, monkeypatch):
    spec, owned, _ = _example_child(tmp_path, monkeypatch,
        "import sys\nsys.stdin.buffer.read()\nprint('{\"status\":\"completed\"}',flush=True)\n")

    class ExampleCancelled(RuntimeError):
        pass

    def heartbeat():
        if owned and owned[0].poll() is not None:
            raise ExampleCancelled("example_late_cancellation")

    try:
        with pytest.raises(ExampleCancelled, match="^example_late_cancellation$"):
            model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu", heartbeat=heartbeat)
    finally:
        _finish_owned(owned)


@pytest.mark.parametrize("reply", [
    '{"status":"failed","status":"completed"}',
    '{"status":"completed","value":NaN}',
    '{"status":"completed","value":Infinity}',
    '{"status":"completed","value":"\\ud800"}',
    '{"status":"completed","value":' + '[' * 80 + '0' + ']' * 80 + '}',
], ids=["duplicate", "nan", "infinity", "unicode", "depth"])
def test_ambiguous_or_invalid_json_is_not_usable_model_output(tmp_path, monkeypatch, reply):
    spec, owned, _ = _example_child(tmp_path, monkeypatch, "import sys\nsys.stdin.buffer.read()\nprint(" + repr(reply) + ",flush=True)\n")
    try:
        with pytest.raises(model_ensemble.ModelEnsembleError, match="^model_ensemble_output_invalid$"):
            model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu")
    finally:
        _finish_owned(owned)


@pytest.mark.parametrize("failed_name", ["model-stage-output", "model-stage-input"], ids=["first-worker", "second-worker"])
def test_io_worker_start_failure_reaps_the_child_and_every_started_worker(tmp_path, monkeypatch, failed_name):
    spec, owned, _ = _example_child(tmp_path, monkeypatch, "import time\ntime.sleep(10)\n")
    original_start = Thread.start
    workers = []

    def start(thread):
        if thread.name in {"model-stage-output", "model-stage-input"}:
            workers.append(thread)
            if thread.name == failed_name:
                raise RuntimeError("example worker start failure")
        return original_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    try:
        with pytest.raises(model_ensemble.ModelEnsembleError, match="^model_ensemble_subprocess_failed$"):
            model_ensemble.run_ensemble_expert_subprocess(spec, "scope_nli", {"schema_version": 3}, "cpu", timeout_seconds=3)
        assert all(not thread.is_alive() for thread in workers)
    finally:
        _finish_owned(owned)
