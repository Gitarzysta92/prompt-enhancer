"""Per-invocation control signals and fail-closed model process ownership."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from threading import Event

from ...application.runtime_cancellation import (
    RuntimeCleanupUnconfirmed,
    RuntimeCooperativeStop,
)


MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE = (
    "model_ensemble_subprocess_cleanup_unconfirmed"
)


class ModelEnsembleError(RuntimeError):
    """Fixed local failure; never includes model output or private input."""


class ModelEnsembleCleanupUnconfirmedError(ModelEnsembleError, RuntimeCleanupUnconfirmed):
    def __init__(self) -> None:
        super().__init__(MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE)


@dataclass
class _RunState:
    heartbeat: Callable[[], None] | None = None
    interrupted: BaseException | None = None


class ModelRunControl:
    """Keep control callbacks local to a run and cleanup quarantine permanent.

    A heartbeat exception is sticky even if a stage adapter catches it. There
    is deliberately no reset for uncertain cleanup in this runner instance.
    The application service serializes admission to its shared model lane.
    """

    def __init__(self) -> None:
        self._current: ContextVar[_RunState | None] = ContextVar("model_run_control", default=None)
        self._cleanup_failed = Event()

    @property
    def heartbeat(self) -> Callable[[], None] | None:
        state = self._current.get()
        return None if state is None else state.heartbeat

    @heartbeat.setter
    def heartbeat(self, callback: Callable[[], None] | None) -> None:
        state = self._current.get()
        if state is None:
            raise RuntimeError("model control callback requires an active run")
        state.heartbeat = callback

    def check(self, error: BaseException | None = None) -> None:
        if isinstance(error, RuntimeCleanupUnconfirmed) or (
            isinstance(error, ModelEnsembleError)
            and error.args == (MODEL_ENSEMBLE_SUBPROCESS_CLEANUP_UNCONFIRMED_ERROR_CODE,)
        ):
            self._cleanup_failed.set()
        # Cleanup uncertainty outranks cancellation: no subsequent stage may
        # use a model while an old owned process might still be alive.
        if self._cleanup_failed.is_set():
            raise ModelEnsembleCleanupUnconfirmedError() from None
        state = self._current.get()
        if state is not None and state.interrupted is not None:
            raise state.interrupted
        if isinstance(error, RuntimeCooperativeStop):
            raise error

    def guard_progress(self, callback: Callable[[int, int], None]) -> Callable[[int, int], None]:
        state = self._current.get()
        if state is None:
            raise RuntimeError("model progress requires an active run")

        def guarded(completed: int, total: int) -> None:
            self.check()
            try:
                callback(completed, total)
            except BaseException as error:
                state.interrupted = error
                raise

        return guarded

    @contextmanager
    def scope(self) -> Iterator[None]:
        self.check()
        state = _RunState()
        token = self._current.set(state)
        try:
            yield
            self.check()
        except BaseException as error:
            self.check(error)
            raise
        finally:
            # Do not retain progress closures, result payloads or exceptions
            # through the long-lived runner after any exit path.
            state.heartbeat = None
            state.interrupted = None
            self._current.reset(token)


def controlled_model_run(method):
    """Preserve the runner signature while fencing every return/error path."""

    @wraps(method)
    def run(self, *args, progress_callback=None, **kwargs):
        with self._run_control.scope():
            progress = (
                None if progress_callback is None
                else self._run_control.guard_progress(progress_callback)
            )
            return method(self, *args, progress_callback=progress, **kwargs)

    return run
