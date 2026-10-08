"""Failure-atomic lifecycle tests for the three durable worker primitives.

Every dependency and failure is synthetic.  The assertions intentionally use
only content-free liveness booleans and fixed lifecycle error codes.
"""

from __future__ import annotations

from collections.abc import Callable
import threading
import time
from types import ModuleType
from typing import Any

import pytest

import prompt_enhancer.application.analysis.model_ensemble_watch as watch_module
import prompt_enhancer.application.automation.service as automation_module
import prompt_enhancer.application.jobs.service as jobs_module
from prompt_enhancer.application.analysis.model_ensemble_watch import (
    ModelEnsembleWatchWorker,
)
from prompt_enhancer.application.automation.service import AutomationGrantWorker
from prompt_enhancer.application.jobs.service import AnalysisJobWorker
from prompt_enhancer.application.runtime_cancellation import (
    current_runtime_cancellation,
    raise_if_runtime_cancelled,
)


_PRIVATE_START_CANARY = "SYNTHETIC-PRIVATE-WORKER-START-CANARY"
_PRIVATE_JOIN_CANARY = "SYNTHETIC-PRIVATE-WORKER-JOIN-CANARY"
_PRIVATE_RECOVERY_CANARY = "SYNTHETIC-PRIVATE-WORKER-RECOVERY-CANARY"
_PRIVATE_CLAIM_CANARY = "SYNTHETIC-PRIVATE-WORKER-CLAIM-CANARY"


class _IdleAnalysisRepository:
    def recover_expired(self, *, now: object) -> int:
        del now
        return 0

    def claim_next(self, **_kwargs: object) -> None:
        return None


class _IdleAutomationService:
    def poll_due(self) -> object:
        return object()


class _IdleWatchService:
    cleanup_unconfirmed = False

    def recover_orphaned_leases(self) -> int:
        return 0

    def run_once(self, **_kwargs: object) -> None:
        return None


def _analysis_worker() -> AnalysisJobWorker:
    return AnalysisJobWorker(
        _IdleAnalysisRepository(),  # type: ignore[arg-type]
        {},
        poll_seconds=0.05,
        worker_id="1" * 64,
    )


def _automation_worker() -> AutomationGrantWorker:
    return AutomationGrantWorker(
        _IdleAutomationService(),  # type: ignore[arg-type]
        poll_seconds=1,
    )


def _watch_worker() -> ModelEnsembleWatchWorker:
    return ModelEnsembleWatchWorker(
        _IdleWatchService(),  # type: ignore[arg-type]
        wake_seconds=1,
    )


_WORKERS: tuple[
    tuple[str, ModuleType, Callable[[], Any]],
    ...,
] = (
    ("analysis", jobs_module, _analysis_worker),
    ("automation", automation_module, _automation_worker),
    ("watch", watch_module, _watch_worker),
)


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        threading.Event().wait(0.005)
    assert predicate()


def test_automation_worker_propagates_shutdown_to_blocked_poll_work() -> None:
    entered = threading.Event()
    observed: list[threading.Event | None] = []

    class CooperativePoll:
        def poll_due(self) -> object:
            observed.append(current_runtime_cancellation())
            entered.set()
            while True:
                raise_if_runtime_cancelled("synthetic_automation_shutdown")
                threading.Event().wait(0.005)

    worker = AutomationGrantWorker(
        CooperativePoll(),  # type: ignore[arg-type]
        poll_seconds=1,
    )
    worker.start()
    assert entered.wait(1.5)

    started = time.monotonic()
    worker.stop(timeout=0.5)

    assert time.monotonic() - started < 0.5
    assert len(observed) == 1 and observed[0] is not None
    assert worker.is_alive() is False


def test_automation_worker_keeps_startup_quiet_until_first_interval() -> None:
    polled = threading.Event()

    class ObservedPoll:
        def poll_due(self) -> object:
            polled.set()
            return object()

    worker = AutomationGrantWorker(
        ObservedPoll(),  # type: ignore[arg-type]
        poll_seconds=1,
    )
    worker.start()
    assert polled.wait(0.05) is False

    worker.stop(timeout=0.5)

    assert polled.is_set() is False
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_start_is_atomic_after_thread_creation_failure_and_can_retry(
    _name: str,
    worker_module: ModuleType,
    worker_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_thread = worker_module.Thread
    fail_next = True

    class _StartFailure:
        def start(self) -> None:
            raise RuntimeError(_PRIVATE_START_CANARY)

    def thread_factory(*args: object, **kwargs: object) -> object:
        nonlocal fail_next
        if fail_next:
            fail_next = False
            return _StartFailure()
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(worker_module, "Thread", thread_factory)
    worker = worker_factory()

    with pytest.raises(RuntimeError, match="^worker_start_failed$") as raised:
        worker.start()

    assert _PRIVATE_START_CANARY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert worker.is_alive() is False
    worker.start()
    _wait_until(worker.is_alive)
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_concurrent_start_publishes_exactly_one_live_thread(
    _name: str,
    worker_module: ModuleType,
    worker_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_thread = worker_module.Thread
    created = 0
    created_lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def thread_factory(*args: object, **kwargs: object) -> threading.Thread:
        nonlocal created
        with created_lock:
            created += 1
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(worker_module, "Thread", thread_factory)
    worker = worker_factory()

    def controlled_run() -> None:
        entered.set()
        release.wait(2)

    worker._run = controlled_run  # type: ignore[method-assign]
    barrier = threading.Barrier(9)
    failures: list[str] = []

    def start_together() -> None:
        barrier.wait()
        try:
            worker.start()
        except Exception as error:  # pragma: no cover - asserted below
            failures.append(type(error).__name__)

    callers = [threading.Thread(target=start_together) for _ in range(8)]
    for caller in callers:
        caller.start()
    barrier.wait()
    for caller in callers:
        caller.join(timeout=2)

    assert failures == []
    assert entered.wait(1)
    assert created == 1
    assert worker.is_alive() is True
    release.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "_worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_start_racing_with_stop_creates_a_live_next_generation(
    _name: str,
    _worker_module: ModuleType,
    worker_factory: Callable[[], Any],
) -> None:
    worker = worker_factory()
    first_entered = threading.Event()
    first_stop_seen = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    release_second = threading.Event()
    start_returned = threading.Event()
    failures: list[str] = []
    generations = 0
    stop_signal = getattr(worker, "_stop_event", None) or getattr(worker, "_stop")

    def controlled_run() -> None:
        nonlocal generations
        generations += 1
        if generations == 1:
            first_entered.set()
            assert stop_signal.wait(1)
            first_stop_seen.set()
            release_first.wait(2)
            return
        second_entered.set()
        release_second.wait(2)

    worker._run = controlled_run  # type: ignore[method-assign]
    worker.start()
    assert first_entered.wait(1)

    def stop_first() -> None:
        try:
            worker.stop(timeout=1)
        except Exception as error:  # pragma: no cover - asserted below
            failures.append(type(error).__name__)

    def start_second() -> None:
        try:
            worker.start()
        except Exception as error:  # pragma: no cover - asserted below
            failures.append(type(error).__name__)
        finally:
            start_returned.set()

    stopper = threading.Thread(target=stop_first)
    stopper.start()
    assert first_stop_seen.wait(1)
    starter = threading.Thread(target=start_second)
    starter.start()
    assert start_returned.wait(0.05) is False

    release_first.set()
    stopper.join(timeout=2)
    starter.join(timeout=2)
    assert not stopper.is_alive()
    assert not starter.is_alive()
    assert failures == []
    assert second_entered.wait(1)
    assert worker.is_alive() is True
    assert generations == 2

    release_second.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "_worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_dead_worker_generation_can_be_restarted(
    _name: str,
    _worker_module: ModuleType,
    worker_factory: Callable[[], Any],
) -> None:
    worker = worker_factory()
    first_finished = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    generations = 0

    def controlled_run() -> None:
        nonlocal generations
        generations += 1
        if generations == 1:
            first_finished.set()
            return
        second_entered.set()
        release.wait(2)

    worker._run = controlled_run  # type: ignore[method-assign]
    worker.start()
    assert first_finished.wait(1)
    _wait_until(lambda: not worker.is_alive())

    worker.start()
    assert second_entered.wait(1)
    assert worker.is_alive() is True
    assert generations == 2
    release.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "_worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_cleanly_stopped_worker_can_be_restarted(
    _name: str,
    _worker_module: ModuleType,
    worker_factory: Callable[[], Any],
) -> None:
    worker = worker_factory()

    worker.start()
    _wait_until(worker.is_alive)
    worker.stop(timeout=1)
    assert worker.is_alive() is False

    worker.start()
    _wait_until(worker.is_alive)
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "_worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_stop_timeout_is_fixed_and_liveness_remains_truthful(
    _name: str,
    _worker_module: ModuleType,
    worker_factory: Callable[[], Any],
) -> None:
    worker = worker_factory()
    entered = threading.Event()
    release = threading.Event()

    def blocked_run() -> None:
        entered.set()
        release.wait(2)

    worker._run = blocked_run  # type: ignore[method-assign]
    worker.start()
    assert entered.wait(1)

    with pytest.raises(RuntimeError, match="^worker_stop_timeout$"):
        worker.stop(timeout=0.01)

    assert worker.is_alive() is True
    release.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "_worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_start_rejects_an_alive_stopping_generation_then_restarts_after_exit(
    _name: str,
    _worker_module: ModuleType,
    worker_factory: Callable[[], Any],
) -> None:
    worker = worker_factory()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    release_second = threading.Event()
    generations = 0

    def controlled_run() -> None:
        nonlocal generations
        generations += 1
        if generations == 1:
            first_entered.set()
            release_first.wait(2)
            return
        second_entered.set()
        release_second.wait(2)

    worker._run = controlled_run  # type: ignore[method-assign]
    worker.start()
    assert first_entered.wait(1)

    with pytest.raises(RuntimeError, match="^worker_stop_timeout$"):
        worker.stop(timeout=0.01)
    with pytest.raises(RuntimeError, match="^worker_stop_in_progress$") as raised:
        worker.start()

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert worker.is_alive() is True

    release_first.set()
    _wait_until(lambda: not worker.is_alive())
    worker.start()
    assert second_entered.wait(1)
    assert worker.is_alive() is True
    assert generations == 2

    release_second.set()
    worker.stop(timeout=1)
    assert worker.is_alive() is False


@pytest.mark.parametrize(
    ("_name", "worker_module", "worker_factory"),
    _WORKERS,
    ids=[item[0] for item in _WORKERS],
)
def test_stop_never_exposes_join_exception_text(
    _name: str,
    worker_module: ModuleType,
    worker_factory: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _JoinFailure:
        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

        def join(self, *, timeout: float) -> None:
            del timeout
            raise RuntimeError(_PRIVATE_JOIN_CANARY)

    monkeypatch.setattr(worker_module, "Thread", lambda **_kwargs: _JoinFailure())
    worker = worker_factory()
    worker.start()

    with pytest.raises(RuntimeError, match="^worker_stop_failed$") as raised:
        worker.stop(timeout=0.01)

    assert _PRIVATE_JOIN_CANARY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert worker.is_alive() is True


def test_analysis_worker_retries_top_level_failures_without_thread_leakage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    completed = threading.Event()
    lock = threading.Lock()
    recovery_calls = 0
    claim_calls = 0
    started_at = time.monotonic()
    uncaught: list[str] = []

    class _FlakyRepository:
        def recover_expired(self, *, now: object) -> int:
            del now
            return 0

        def claim_next(self, **_kwargs: object) -> None:
            nonlocal claim_calls
            with lock:
                claim_calls += 1
                current = claim_calls
            if current == 1:
                raise RuntimeError(_PRIVATE_CLAIM_CANARY)
            completed.set()
            return None

    def recover_execution(_now: object) -> None:
        nonlocal recovery_calls
        with lock:
            recovery_calls += 1
            current = recovery_calls
        # Call one happens synchronously during start.  Exercise the supervised
        # worker loop on call two, then allow its next retry to reach claim.
        if current == 2:
            raise RuntimeError(_PRIVATE_RECOVERY_CANARY)

    monkeypatch.setattr(
        threading,
        "excepthook",
        lambda args: uncaught.append(type(args.exc_value).__name__),
    )
    worker = AnalysisJobWorker(
        _FlakyRepository(),  # type: ignore[arg-type]
        {},
        execution_recovery_callback=recover_execution,
        poll_seconds=0.05,
        worker_id="2" * 64,
    )

    worker.start()
    assert completed.wait(2)
    elapsed = time.monotonic() - started_at
    assert elapsed >= 0.08
    assert recovery_calls >= 4
    assert claim_calls >= 2
    assert worker.is_alive() is True
    worker.stop(timeout=1)
    assert worker.is_alive() is False
    assert uncaught == []
    captured = capsys.readouterr()
    assert _PRIVATE_RECOVERY_CANARY not in captured.err
    assert _PRIVATE_CLAIM_CANARY not in captured.err
