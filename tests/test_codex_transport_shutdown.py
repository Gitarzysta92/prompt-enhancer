from __future__ import annotations

import subprocess
from threading import Event

import pytest

from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCooperativeStop,
    runtime_request_scope,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexTransportError,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.limits import CodexReadLimits
from prompt_enhancer.infrastructure.providers.codex_app_server.transports import stdio_jsonl
from prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl import (
    CODEX_APP_SERVER_ARGV,
    StdioJsonRpcTransport,
)


class RecordingInput:
    def __init__(self, order: list[str]) -> None:
        self._order = order

    def close(self) -> None:
        self._order.append("stdin.close")


class StalledOutput:
    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.started = Event()
        self.released = Event()

    def readline(self, _limit: int) -> bytes:
        self.started.set()
        self.released.wait(timeout=2)
        return b""

    def close(self) -> None:
        self._order.append("stdout.close")
        self.released.set()


class StalledProcess:
    def __init__(self, order: list[str]) -> None:
        self.stdin = RecordingInput(order)
        self.stdout = StalledOutput(order)
        self._order = order
        self._killed = False
        self._terminated = False

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self._order.append("terminate")
        self._terminated = True

    def kill(self) -> None:
        self._order.append("kill")
        self._killed = True

    def wait(self, timeout: float | None = None) -> int:
        if self._killed:
            self._order.append("wait.after_kill")
            return 0
        if self._terminated:
            self._order.append("wait.after_terminate")
        else:
            self._order.append("wait.after_stdin")
        raise subprocess.TimeoutExpired(CODEX_APP_SERVER_ARGV, timeout)


class GracefulProcess(StalledProcess):
    def wait(self, timeout: float | None = None) -> int:
        self._order.append("wait.after_stdin")
        return 0


def test_close_allows_graceful_eof_shutdown_before_terminating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    process = GracefulProcess(order)
    monkeypatch.setattr(
        stdio_jsonl, "start_codex_app_server_process", lambda: process
    )
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(shutdown_timeout_seconds=0.1)
    )
    transport._start()
    assert process.stdout.started.wait(timeout=1)

    transport.close()

    assert order == [
        "stdin.close",
        "wait.after_stdin",
        "stdout.close",
    ]
def test_close_stops_child_before_closing_stdout_and_joins_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    process = StalledProcess(order)
    process_attempts = 0

    def fake_start() -> StalledProcess:
        nonlocal process_attempts
        process_attempts += 1
        return process

    monkeypatch.setattr(stdio_jsonl, "start_codex_app_server_process", fake_start)
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(shutdown_timeout_seconds=0.1)
    )
    transport._start()
    assert process.stdout.started.wait(timeout=1)
    reader = transport._reader
    assert reader is not None

    transport.close()

    assert order == [
        "stdin.close",
        "wait.after_stdin",
        "terminate",
        "wait.after_terminate",
        "kill",
        "wait.after_kill",
        "stdout.close",
    ]
    assert reader.is_alive() is False
    assert process_attempts == 1

    transport.close()
    with pytest.raises(CodexTransportError):
        transport._request("initialize", {})
    assert process_attempts == 1


def test_runtime_shutdown_kills_waiting_helper_before_normal_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    process = StalledProcess(order)
    monkeypatch.setattr(
        stdio_jsonl, "start_codex_app_server_process", lambda: process
    )
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(shutdown_timeout_seconds=0.1)
    )
    transport._start()
    assert process.stdout.started.wait(timeout=1)
    cancelled = Event()
    cancelled.set()

    with runtime_request_scope(cancelled), pytest.raises(
        RuntimeCooperativeStop, match="^codex_provider_request_cancelled$"
    ):
        transport._next_message(deadline=10**9)

    assert order == ["kill"]
    transport.close()
    assert order == [
        "kill",
        "stdin.close",
        "wait.after_kill",
        "stdout.close",
    ]
