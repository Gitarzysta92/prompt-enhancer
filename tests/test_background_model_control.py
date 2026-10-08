"""Fictional model stages must not swallow job control or outlive ownership."""

from threading import Event, Thread
from datetime import timedelta

import pytest

from prompt_enhancer.application.analysis.model_ensemble import build_ensemble_chunks, coaching_ensemble_metric_specs
from prompt_enhancer.application.analysis.model_ensemble_watch import (
    MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    ModelEnsembleWatchService,
    ModelEnsembleWatchStopped,
    ModelEnsembleWatchWorker,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    MODEL_ENSEMBLE_CONFIRMATION,
    ModelEnsembleRuntimeCleanupError,
)
from prompt_enhancer.infrastructure.text_models.model_ensemble import ModelEnsembleError, SerialModelEnsembleRunner
from prompt_enhancer.infrastructure.text_models.probabilistic_metrics import LocalProbabilisticMetricRunner
from prompt_enhancer.interfaces.http.model_ensemble_watch_routes import ModelEnsembleWatchDto
from tests.test_chunked_model_ensemble import _context
from tests.test_session_model_ensemble import SESSION_ID, _execute, _service
from tests.test_model_ensemble_persistence import NOW, _database_and_session
from prompt_enhancer.domain import Provider


@pytest.mark.parametrize("runner_type,heartbeat_name", [
    (SerialModelEnsembleRunner, "_heartbeat_callback"),
    (LocalProbabilisticMetricRunner, "_heartbeat"),
], ids=["serial", "probabilistic"])
def test_one_shot_heartbeat_failure_cannot_become_a_partial_model_receipt(runner_type, heartbeat_name):
    in_stage = False
    interrupted = False
    calls = []

    def progress(_completed, _total):
        nonlocal interrupted
        if in_stage and not interrupted:
            interrupted = True
            raise ModelEnsembleWatchStopped()

    def execute(spec, stage, payload, device):
        nonlocal in_stage
        calls.append(stage)
        in_stage = True
        try:
            getattr(runner, heartbeat_name)()
        finally:
            in_stage = False
        return _execute(spec, stage, payload, device)

    runner = runner_type(executor=execute, device="cpu")
    with pytest.raises(ModelEnsembleWatchStopped):
        runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs(), progress_callback=progress)
    assert len(calls) == 1
    assert getattr(runner, heartbeat_name) is None


@pytest.mark.parametrize("runner_type,heartbeat_name", [
    (SerialModelEnsembleRunner, "_heartbeat_callback"),
    (LocalProbabilisticMetricRunner, "_heartbeat"),
], ids=["serial", "probabilistic"])
def test_control_callback_is_released_even_when_admission_raises(runner_type, heartbeat_name):
    runner = runner_type(executor=_execute, device="cpu")

    def stopped(*_args):
        raise ModelEnsembleWatchStopped()

    with pytest.raises(ModelEnsembleWatchStopped):
        runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs(), progress_callback=stopped)
    assert getattr(runner, heartbeat_name) is None


def test_session_service_preserves_cooperative_stop_without_publishing():
    service, _source, repository = _service()

    def stopped(*_args):
        raise ModelEnsembleWatchStopped()

    with pytest.raises(ModelEnsembleWatchStopped):
        service.run(provider=Provider.CODEX, session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION, idempotency_key="example-cancel-before-stage", progress_callback=stopped)
    assert not repository.items


def test_waiting_for_the_shared_model_lane_can_be_cancelled_without_reading_content():
    service, source, _repository = _service()
    requested, started = Event(), Event()
    results = []

    def progress(*_args):
        if requested.is_set():
            raise ModelEnsembleWatchStopped()

    def run():
        started.set()
        try:
            service.run(provider=Provider.CODEX, session_id=SESSION_ID,
                confirmation=MODEL_ENSEMBLE_CONFIRMATION, idempotency_key="example-cancel-waiting-lane", progress_callback=progress)
        except Exception as error:
            results.append(error)

    service._lock.acquire()
    caller = Thread(target=run, name="example-waiting-model-job")
    caller.start()
    try:
        assert started.wait(1)
        requested.set()
        caller.join(timeout=0.5)
        assert not caller.is_alive(), "A job waiting for the model lane ignored cancellation"
        assert len(results) == 1 and isinstance(results[0], ModelEnsembleWatchStopped)
        assert source.read_count == 0
    finally:
        service._lock.release()
        caller.join(timeout=2)
        assert not caller.is_alive()


@pytest.mark.parametrize("runner_type", [SerialModelEnsembleRunner, LocalProbabilisticMetricRunner], ids=["serial", "probabilistic"])
def test_uncertain_process_cleanup_blocks_another_run_in_the_same_instance(runner_type):
    calls = []

    def execute(*args):
        calls.append(args[1])
        raise ModelEnsembleError("model_ensemble_subprocess_cleanup_unconfirmed")

    runner = runner_type(executor=execute, device="cpu")
    for _ in range(2):
        with pytest.raises(ModelEnsembleError, match="^model_ensemble_subprocess_cleanup_unconfirmed$"):
            runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs())
    assert len(calls) == 1, "An uncertain old process must not admit another model"


@pytest.mark.parametrize("runner_type,heartbeat_name", [
    (SerialModelEnsembleRunner, "_heartbeat_callback"),
    (LocalProbabilisticMetricRunner, "_heartbeat"),
], ids=["serial", "probabilistic"])
@pytest.mark.parametrize("boundary", ["swallowed", "cpu-fallback", "cleanup"])
def test_control_survives_adapter_and_fallback_boundaries(runner_type, heartbeat_name, boundary):
    in_stage = False
    calls = []

    def progress(*_args):
        if in_stage:
            raise ModelEnsembleWatchStopped()

    def execute(spec, stage, payload, device):
        nonlocal in_stage
        calls.append(device)
        if boundary == "cpu-fallback" and device != "cpu":
            return {"status": "failed", "error_code": "resource_exhausted"}
        in_stage = True
        try:
            try:
                getattr(runner, heartbeat_name)()
            except ModelEnsembleWatchStopped:
                if boundary == "cleanup":
                    raise ModelEnsembleError("model_ensemble_subprocess_cleanup_unconfirmed")
                # An adapter swallowing the callback may not resume the run.
            return {"status": "failed", "error_code": "resource_exhausted"}
        finally:
            in_stage = False

    runner = runner_type(executor=execute, device="cuda")
    expected = ModelEnsembleError if boundary == "cleanup" else ModelEnsembleWatchStopped
    with pytest.raises(expected):
        runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs(), progress_callback=progress)
    assert calls == (["cuda", "cpu"] if boundary == "cpu-fallback" else ["cuda"])
    assert getattr(runner, heartbeat_name) is None
    if boundary == "cleanup":
        with pytest.raises(ModelEnsembleError, match="^model_ensemble_subprocess_cleanup_unconfirmed$"):
            runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs())
        assert calls == ["cuda"]
    else:
        # Ordinary cancellation does not permanently quarantine a healthy lane.
        runner._executor = _execute
        runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs())


@pytest.mark.parametrize("boundary", ["pipeline", "publication"])
def test_session_control_is_not_reclassified_at_late_boundaries(boundary, monkeypatch):
    service, source, repository = _service()

    def stopped(*_args, **_kwargs):
        raise ModelEnsembleWatchStopped()

    arguments = {}
    if boundary == "pipeline":
        monkeypatch.setattr(service._runner, "run", stopped)
    else:
        arguments["persistence_authority"] = stopped
    with pytest.raises(ModelEnsembleWatchStopped):
        service.run(provider=Provider.CODEX, session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION, idempotency_key="example-late-cancellation", **arguments)
    assert source.read_count == 1
    assert not repository.items


def test_service_quarantine_rejects_retries_before_any_further_source_read():
    service, source, repository = _service()
    calls = []

    def uncertain(*_args):
        calls.append(True)
        raise ModelEnsembleError("model_ensemble_subprocess_cleanup_unconfirmed")

    service._runner._executor = uncertain
    for index in range(2):
        with pytest.raises(ModelEnsembleRuntimeCleanupError) as failed:
            service.run(provider=Provider.CODEX, session_id=SESSION_ID,
                confirmation=MODEL_ENSEMBLE_CONFIRMATION, idempotency_key=f"example-cleanup-retry-{index}")
        assert failed.value.code == "model_ensemble_cleanup_unconfirmed"
    assert source.read_count == 1
    assert len(calls) == 1
    assert not repository.items


def test_watch_cleanup_failure_is_durably_quarantined_without_automatic_retry(tmp_path):
    database, session_id = _database_and_session(tmp_path)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    repository = database.model_ensemble_watch_repository()
    clock = [NOW]
    calls = []

    class ExampleEnsemble:
        def require_watchable(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            calls.append(True)
            raise ModelEnsembleRuntimeCleanupError("example cleanup failure")

    watch = ModelEnsembleWatchService(repository, ExampleEnsemble(), clock=lambda: clock[0])
    enabled = watch.enable(provider=Provider.CODEX, project_id=project_id, session_id=session_id,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION)
    failed = watch.run_once()
    assert failed is not None and failed.quarantined
    assert failed.quarantine_reason_code == "model_ensemble_cleanup_unconfirmed"
    assert failed.failure_streak == 1
    assert failed.last_error_code == failed.quarantine_reason_code
    payload = ModelEnsembleWatchDto.from_record(failed).model_dump(mode="json")
    assert payload["quarantined"] is True
    assert payload["quarantine_reason_code"] == failed.quarantine_reason_code
    head = repository.canonical_head(enabled.watch_id)
    assert head.head_run_id is None
    assert head.latest_attempt.state.value == "failed"
    assert head.latest_attempt.error_code == "model_ensemble_cleanup_unconfirmed"
    clock[0] += timedelta(days=1)
    assert watch.run_once() is None
    assert len(calls) == 1


@pytest.mark.parametrize("boundary", ["queued-lane", "during-stage", "publication"])
def test_real_watch_controller_keeps_shutdown_cancelled_without_failure_streak(tmp_path, monkeypatch, boundary):
    from prompt_enhancer.database import Database
    from tests.test_session_model_ensemble import _persist_api_session

    database = Database(tmp_path / "example-control.sqlite3")
    database.initialize()
    _persist_api_session(database)
    service, source, receipts = _service()
    repository = database.model_ensemble_watch_repository()
    stopped = Event()
    entered = Event()
    results = []
    if boundary == "queued-lane":
        service._lock.acquire()
        original_lane = service._execution_lane

        def waiting(progress):
            entered.set()
            return original_lane(progress)

        monkeypatch.setattr(service, "_execution_lane", waiting)
    elif boundary == "during-stage":
        def execute(*_args):
            stopped.set()
            service._runner._heartbeat_callback()
            pytest.fail("A cancelled stage resumed")

        service._runner._executor = execute
    else:
        original_run = service._runner.run

        def finish_then_cancel(*args, **kwargs):
            receipt = original_run(*args, **kwargs)
            stopped.set()
            return receipt

        monkeypatch.setattr(service._runner, "run", finish_then_cancel)

    watch = ModelEnsembleWatchService(repository, service, clock=lambda: NOW)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    enabled = watch.enable(provider=Provider.CODEX, project_id=project_id, session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION)
    caller = Thread(target=lambda: results.append(watch.run_once(stop_requested=stopped.is_set)), name="example-watch-stop")
    caller.start()
    try:
        if boundary == "queued-lane":
            assert entered.wait(1)
            stopped.set()
        caller.join(timeout=2)
        assert not caller.is_alive()
        assert len(results) == 1
        assert results[0].failure_streak == 0
        assert not results[0].quarantined
        head = repository.canonical_head(enabled.watch_id)
        assert head.head_run_id is None
        assert head.latest_attempt.state.value == "cancelled"
        assert head.latest_attempt.error_code == "application_shutdown"
        assert source.read_count == (0 if boundary == "queued-lane" else 1)
        assert not receipts.items
    finally:
        stopped.set()
        if boundary == "queued-lane":
            service._lock.release()
        caller.join(timeout=2)
        assert not caller.is_alive()


@pytest.mark.parametrize("boundary", ["cancellation", "guard-failure", "cleanup"])
def test_optional_deep_lane_must_not_publish_after_control_failure(boundary):
    in_deep = False
    calls = []

    class ExampleGuardFailure(RuntimeError):
        pass

    def progress(*_args):
        if in_deep:
            if boundary == "guard-failure":
                raise ExampleGuardFailure("example_guard_failed")
            raise ModelEnsembleWatchStopped()

    def execute(spec, stage, payload, device):
        calls.append(stage)
        return {"status": "completed", "device": "cuda",
            "rows": [{"case_id": case["case_id"], "entailment": 0.35, "neutral": 0.5, "contradiction": 0.15} for case in payload["cases"]],
            "runtime": {"inference_latency_ms": 100.0, "peak_cuda_allocated_mb": 900.0, "process_rss_after_load_and_inference_mb": 1500.0}}

    def deep(*_args):
        nonlocal in_deep
        calls.append("example_deep")
        in_deep = True
        try:
            runner._heartbeat()
        except ModelEnsembleWatchStopped:
            if boundary == "cleanup":
                raise ModelEnsembleError("model_ensemble_subprocess_cleanup_unconfirmed")
            raise
        finally:
            in_deep = False

    runner = LocalProbabilisticMetricRunner(executor=execute, deep_executor=deep, device="cuda")
    expected = ModelEnsembleError if boundary == "cleanup" else ExampleGuardFailure if boundary == "guard-failure" else ModelEnsembleWatchStopped
    with pytest.raises(expected):
        runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs(), progress_callback=progress)
    assert calls == ["scope_nli", "scope_nli", "scope_nli", "example_deep"]
    assert runner._heartbeat is None
    if boundary == "cleanup":
        with pytest.raises(ModelEnsembleError):
            runner.run(build_ensemble_chunks(_context()), coaching_ensemble_metric_specs())
        assert len(calls) == 4


@pytest.mark.parametrize("boundary", ["shutdown", "cancel", "disable"])
def test_cleanup_failure_after_cancel_is_not_lost_with_the_old_lease(tmp_path, boundary):
    from prompt_enhancer.database import Database
    from tests.test_session_model_ensemble import _persist_api_session

    database = Database(tmp_path / "example-cancel-cleanup.sqlite3")
    database.initialize()
    _persist_api_session(database)
    service, source, receipts = _service()
    repository = database.model_ensemble_watch_repository()
    stopped = Event()

    def execute(*_args):
        if boundary == "shutdown":
            stopped.set()
        elif boundary == "cancel":
            repository.cancel_attempt(enabled.watch_id, now=NOW, next_check_at=NOW + timedelta(minutes=1))
        else:
            repository.disable(enabled.watch_id, now=NOW)
        try:
            service._runner._heartbeat_callback()
        except (ModelEnsembleWatchStopped, ValueError):
            raise ModelEnsembleError("model_ensemble_subprocess_cleanup_unconfirmed")
        pytest.fail("An interrupted stage resumed")

    service._runner._executor = execute
    watch = ModelEnsembleWatchService(repository, service, clock=lambda: NOW)
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    enabled = watch.enable(provider=Provider.CODEX, project_id=project_id, session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION)
    failed = watch.run_once(stop_requested=stopped.is_set)
    assert failed.quarantined, "Losing the cancelled lease hid uncertain process cleanup"
    assert failed.quarantine_reason_code == "model_ensemble_cleanup_unconfirmed"
    assert failed.state.value == ("disabled" if boundary == "disable" else "failed")
    assert failed.failure_streak == 0
    assert watch.cleanup_unconfirmed
    assert ModelEnsembleWatchDto.from_record(failed).quarantined is True
    head = repository.canonical_head(enabled.watch_id)
    assert head.latest_attempt.state.value == "cancelled"
    assert head.latest_attempt.error_code == {
        "shutdown": "application_shutdown", "cancel": "analysis_cancelled", "disable": "watch_disabled",
    }[boundary]
    assert head.head_run_id is None
    assert source.read_count == 1
    assert not receipts.items
    if boundary == "disable":
        watch.enable(provider=Provider.CODEX, project_id=project_id, session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION)
    else:
        repository.request_refresh(enabled.watch_id, now=NOW)
    assert watch.run_once().quarantined
    assert source.read_count == 1
    assert not receipts.items


def test_worker_exit_does_not_claim_cleanup_succeeded_after_cancel(tmp_path):
    database, session_id = _database_and_session(tmp_path)
    repository = database.model_ensemble_watch_repository()
    project_id = database.list_sessions(provider=Provider.CODEX, limit=1)[0]["project_id"]
    watch_id = "5" * 64
    repository.enable(watch_id=watch_id, provider=Provider.CODEX, project_id=project_id,
        session_id=session_id, now=NOW)
    entered, release = Event(), Event()

    class ExampleEnsemble:
        def run(self, *, progress_callback, **_kwargs):
            entered.set()
            try:
                while not release.wait(0.01):
                    progress_callback(0, 10)
            except ModelEnsembleWatchStopped:
                raise ModelEnsembleRuntimeCleanupError()
            raise RuntimeError("example_test_teardown")

    service = ModelEnsembleWatchService(repository, ExampleEnsemble(), clock=lambda: NOW)
    worker = ModelEnsembleWatchWorker(service, wake_seconds=1)
    try:
        worker.start()
        assert entered.wait(2)
        for _ in range(2):
            with pytest.raises(RuntimeError, match="^worker_stop_failed$") as failed:
                worker.stop(timeout=2)
            assert failed.value.__context__ is None
            assert failed.value.__cause__ is None
            assert not worker.is_alive()
        with pytest.raises(RuntimeError, match="^worker_start_failed$"):
            worker.start()
        head = repository.canonical_head(watch_id)
        assert head.watch.quarantined
        assert head.latest_attempt.state.value == "cancelled"
        assert head.latest_attempt.error_code == "application_shutdown"
        assert head.head_run_id is None
    finally:
        release.set()
        try:
            worker.stop(timeout=2)
        except RuntimeError as error:
            assert str(error) == "worker_stop_failed"
        assert not worker.is_alive()
