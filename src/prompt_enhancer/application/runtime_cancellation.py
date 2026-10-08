"""Content-free cancellation ownership for one local runtime request/turn.

The event is scoped to its caller, not its model. Context propagation through
the ASGI thread pool keeps the existing two-argument model adapter interface.
Socket readers retain the event after response headers have been returned.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event


class RuntimeCooperativeStop(RuntimeError):
    """A caller stopped work; this is not a failed model observation."""


class RuntimeCleanupUnconfirmed(RuntimeError):
    """Model resource ownership is uncertain; admitting more work is unsafe."""


_request_cancellation: ContextVar[Event | None] = ContextVar("local_runtime_cancellation", default=None)


def current_runtime_cancellation() -> Event | None:
    return _request_cancellation.get()


def raise_if_runtime_cancelled(reason: str = "runtime_operation_cancelled") -> None:
    """Stop at a cooperative boundary without exposing operation content.

    Background workers and request-owned adapters share this one content-free
    check.  Code that is not running inside ``runtime_request_scope`` remains
    unaffected, while a scoped shutdown can interrupt bounded provider reads
    before the desktop's cleanup deadline expires.
    """

    cancelled = current_runtime_cancellation()
    if cancelled is not None and cancelled.is_set():
        raise RuntimeCooperativeStop(reason)


@contextmanager
def runtime_request_scope(cancelled: Event) -> Iterator[None]:
    token = _request_cancellation.set(cancelled)
    try:
        yield
    finally:
        _request_cancellation.reset(token)


@contextmanager
def runtime_critical_cleanup_scope() -> Iterator[None]:
    """Finish a bounded safety cleanup after cooperative cancellation.

    A stop may interrupt new work, but it must not interrupt restoration that
    became necessary after a reviewed mutation was already published.
    """

    token = _request_cancellation.set(None)
    try:
        yield
    finally:
        _request_cancellation.reset(token)
