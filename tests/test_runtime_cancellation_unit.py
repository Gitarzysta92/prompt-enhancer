"""Content-free ownership and controlled connect/upload cancellation failures."""

from contextlib import contextmanager
import errno
import socket
import threading

import pytest

from prompt_enhancer.application import local_models
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCooperativeStop,
    current_runtime_cancellation,
    raise_if_runtime_cancelled,
    runtime_critical_cleanup_scope,
    runtime_request_scope,
)


def test_request_scope_restores_nested_context_and_does_not_leak_to_another_thread():
    outer, inner = threading.Event(), threading.Event()
    observed = []
    assert current_runtime_cancellation() is None
    with runtime_request_scope(outer):
        with pytest.raises(RuntimeError, match="example"):
            with runtime_request_scope(inner):
                assert current_runtime_cancellation() is inner
                raise RuntimeError("example")
        assert current_runtime_cancellation() is outer
        worker = threading.Thread(target=lambda: observed.append(current_runtime_cancellation()))
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive() and observed == [None]
    assert current_runtime_cancellation() is None


def test_critical_cleanup_temporarily_suppresses_then_restores_a_cancelled_request():
    cancelled = threading.Event()
    cancelled.set()
    with runtime_request_scope(cancelled):
        assert current_runtime_cancellation() is cancelled
        with runtime_critical_cleanup_scope():
            assert current_runtime_cancellation() is None
        assert current_runtime_cancellation() is cancelled
    assert current_runtime_cancellation() is None


def test_shared_cooperative_boundary_stops_only_the_cancelled_scope():
    raise_if_runtime_cancelled()
    cancelled = threading.Event()
    cancelled.set()

    with runtime_request_scope(cancelled), pytest.raises(
        RuntimeCooperativeStop, match="^synthetic_worker_shutdown$"
    ):
        raise_if_runtime_cancelled("synthetic_worker_shutdown")

    # Cleanup scopes deliberately finish their bounded restoration work.
    with runtime_request_scope(cancelled), runtime_critical_cleanup_scope():
        raise_if_runtime_cancelled()


@pytest.mark.parametrize("host", ["example.invalid", "192.0.2.1"])
def test_cancellable_connection_rejects_dns_and_nonloopback_before_network_io(monkeypatch, host):
    monkeypatch.setattr(local_models.socket, "socket", lambda *_: pytest.fail("No socket should be opened"))
    with runtime_request_scope(threading.Event()):
        connection = local_models._RuntimeHTTPConnection(host, timeout=1)
    with pytest.raises(OSError, match="numeric loopback"):
        connection.connect()


def test_already_cancelled_request_never_opens_a_socket(monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    monkeypatch.setattr(local_models.socket, "socket", lambda *_: pytest.fail("Cancelled request opened a socket"))
    with runtime_request_scope(cancelled):
        connection = local_models._RuntimeHTTPConnection("127.0.0.1", timeout=1)
    with pytest.raises(OSError, match="cancelled"):
        connection.connect()


class _Socket:
    def __init__(self):
        self.closed = False
        self.timeout = 1
        self.sent = bytearray()
        self.block_upload = True

    def setblocking(self, _value):
        pass

    def settimeout(self, timeout):
        self.timeout = timeout

    def gettimeout(self):
        return self.timeout

    def connect_ex(self, _destination):
        return errno.EWOULDBLOCK

    def send(self, data):
        if self.block_upload:
            raise BlockingIOError()
        chunk = data[:2]
        self.sent.extend(chunk)
        return len(chunk)

    def close(self):
        self.closed = True


def test_cancel_during_connect_closes_the_owned_attempt(monkeypatch):
    cancelled, owned = threading.Event(), _Socket()
    monkeypatch.setattr(local_models.socket, "socket", lambda *_: owned)

    def cancel_poll(*_args):
        cancelled.set()
        return [], [], []

    monkeypatch.setattr(local_models.select, "select", cancel_poll)
    with runtime_request_scope(cancelled):
        connection = local_models._RuntimeHTTPConnection("127.0.0.1", timeout=1)
    with pytest.raises(OSError, match="cancelled"):
        connection.connect()
    assert owned.closed and connection.sock is None


def test_cancel_during_blocked_upload_returns_control_to_the_connection_owner(monkeypatch):
    cancelled, owned = threading.Event(), _Socket()

    def cancel_poll(*_args):
        cancelled.set()
        return [], [], []

    monkeypatch.setattr(local_models.select, "select", cancel_poll)
    with runtime_request_scope(cancelled):
        connection = local_models._RuntimeHTTPConnection("127.0.0.1", timeout=1)
    connection.sock = owned
    try:
        with pytest.raises(OSError, match="cancelled"):
            connection.send(b"Example request body")
        assert owned.timeout == 1 and not owned.sent
    finally:
        connection.close()  # urllib's do_open owns this same error cleanup.
    assert owned.closed


def test_partial_upload_writes_every_byte_once_and_restores_timeout():
    cancelled, owned = threading.Event(), _Socket()
    owned.block_upload = False
    with runtime_request_scope(cancelled):
        connection = local_models._RuntimeHTTPConnection("127.0.0.1", timeout=1)
    connection.sock = owned
    try:
        connection.send(b"Example request body")
        assert owned.sent == b"Example request body" and owned.timeout == 1
    finally:
        connection.close()
    assert not cancelled.is_set()


def test_closing_a_response_reader_does_not_cancel_the_next_tool_step():
    cancelled = threading.Event()
    with _socket_pair() as (left, right):
        reader = local_models._RuntimeSocketReader(left, cancelled)
        right.sendall(b"example")
        buffer = bytearray(7)
        assert reader.readinto(buffer) == 7 and buffer == b"example"
        reader.close()
    assert not cancelled.is_set()


@contextmanager
def _socket_pair():
    left, right = socket.socketpair()
    try:
        yield left, right
    finally:
        left.close()
        right.close()
