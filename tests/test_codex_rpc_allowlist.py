from __future__ import annotations

import io
import json
import pytest

from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    RPC_METHOD_ALLOWLIST,
    CodexAppServerClient,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexProtocolViolation,
    CodexRequestRejected,
    CodexScopeError,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.limits import CodexReadLimits
from prompt_enhancer.infrastructure.providers.codex_app_server.transports import stdio_jsonl
from prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl import (
    StdioJsonRpcTransport,
    codex_app_server_argv,
    codex_app_server_creation_flags,
)


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def _start(self) -> None:
        raise AssertionError("synthetic transport must not launch")

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.requests.append((method, params or {}))

    def close(self) -> None:
        return None


class FakeProcess:
    def __init__(self, stdout_payload: bytes = b"") -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout_payload)
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_rpc_surface_is_an_exact_static_read_only_allowlist() -> None:
    assert RPC_METHOD_ALLOWLIST == {
        "initialize",
        "initialized",
        "thread/list",
        "thread/read",
    }
    public_names = {
        name for name in dir(CodexAppServerClient) if not name.startswith("_")
    }
    assert not {
        "request",
        "notify",
        "delete_thread",
        "archive_thread",
        "resume_thread",
        "send_prompt",
        "run_sql",
    }.intersection(public_names)


def test_every_list_request_forces_state_database_only() -> None:
    transport = RecordingTransport(
        [
            {"version": "example-1"},
            {
                "data": [
                    {
                        "id": "example-session-1",
                        "cwd": "/example/project",
                        "createdAt": 1_768_473_600,
                    }
                ],
                "nextCursor": "example-raw-cursor",
            },
            {"data": [], "nextCursor": None},
        ]
    )
    client = CodexAppServerClient(transport)
    client.initialize()
    client.list_threads(cursor=None, limit=10, new_snapshot=True)
    client.list_threads(
        cursor="example-raw-cursor", limit=10, new_snapshot=False
    )

    list_calls = [entry for entry in transport.requests if entry[0] == "thread/list"]
    assert len(list_calls) == 2
    assert all(call[1]["useStateDbOnly"] is True for call in list_calls)


def test_read_rejects_an_id_that_was_not_listed_without_an_rpc() -> None:
    transport = RecordingTransport([{"version": "example-1"}])
    client = CodexAppServerClient(transport)
    client.initialize()

    with pytest.raises(CodexScopeError) as error:
        client.read_thread("example-unlisted-session")

    assert "example-unlisted-session" not in str(error.value)
    assert [method for method, _params in transport.requests] == [
        "initialize",
        "initialized",
    ]


def test_stdio_transport_uses_fixed_argv_shell_false_and_discards_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []
    synthetic_argv = (
        "cmd.exe",
        "/d",
        "/s",
        "/c",
        r"C:\Synthetic Tools\codex.cmd",
        "app-server",
        "--listen",
        "stdio://",
    )
    process = FakeProcess()

    def fake_start(argv: object, **kwargs: object) -> FakeProcess:
        calls.append((argv, kwargs))
        return process

    monkeypatch.setattr(stdio_jsonl, "start_owned_process", fake_start)
    monkeypatch.setattr(stdio_jsonl, "CODEX_APP_SERVER_ARGV", synthetic_argv)
    transport = StdioJsonRpcTransport()
    assert calls == []
    transport._start()
    transport.close()

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == synthetic_argv
    assert kwargs["cwd"] is None
    assert isinstance(kwargs["env"], dict)
    assert kwargs["pipe_stdin"] is True
    assert kwargs["capture_stdout"] is True
    assert kwargs["capture_stderr"] is False
    assert kwargs["maximum_active_processes"] == 16


def test_stdio_transport_resolves_fixed_platform_commands() -> None:
    synthetic_cmd = r"C:\Synthetic Tools\codex.cmd"
    synthetic_exe = r"C:\Synthetic Tools\codex.exe"
    assert codex_app_server_argv(platform="posix", which=lambda _name: None) == (
        "codex",
        "app-server",
        "--listen",
        "stdio://",
    )
    assert codex_app_server_argv(platform="nt", which=lambda _name: None) == (
        "codex.exe",
        "app-server",
        "--listen",
        "stdio://",
    )
    assert codex_app_server_argv(
        platform="nt",
        which=lambda name: synthetic_cmd if name == "codex.cmd" else None,
    ) == (
        "cmd.exe",
        "/d",
        "/s",
        "/c",
        synthetic_cmd,
        "app-server",
        "--listen",
        "stdio://",
    )
    assert codex_app_server_argv(
        platform="nt",
        which=lambda name: synthetic_exe if name == "codex.exe" else None,
    ) == (
        synthetic_exe,
        "app-server",
        "--listen",
        "stdio://",
    )


def test_stdio_transport_prefers_native_windows_executable_over_cmd_shim() -> None:
    synthetic_cmd = r"C:\Synthetic Tools\codex.cmd"
    synthetic_exe = r"C:\Synthetic Tools\codex.exe"
    observed: list[str] = []

    def resolve(name: str) -> str | None:
        observed.append(name)
        return synthetic_exe if name == "codex.exe" else synthetic_cmd

    assert codex_app_server_argv(platform="nt", which=resolve) == (
        synthetic_exe,
        "app-server",
        "--listen",
        "stdio://",
    )
    assert observed == ["codex.exe"]


def test_stdio_transport_uses_nonzero_no_window_flag_on_windows() -> None:
    assert codex_app_server_creation_flags(platform="nt") == 0x08000000
    assert codex_app_server_creation_flags(platform="posix") == 0


def test_stdio_transport_writes_current_headerless_protocol_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = b'{"id":1,"result":{"version":"example-1"}}\n'
    process = FakeProcess(response)
    monkeypatch.setattr(
        stdio_jsonl, "start_codex_app_server_process", lambda: process
    )
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(request_timeout_seconds=0.5)
    )

    assert transport._request("initialize", {"clientInfo": {}}) == {
        "version": "example-1"
    }
    transport._notify("initialized", {})
    outbound = [
        json.loads(line) for line in process.stdin.getvalue().splitlines()
    ]

    assert outbound == [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {}}},
        {"method": "initialized", "params": {}},
    ]
    assert all("jsonrpc" not in frame for frame in outbound)

    transport.close()


def test_stdio_transport_fails_closed_on_server_request_without_leaking_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_method_canary = "private.provider.method.example"
    line = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": private_method_canary,
                "params": {"content": "private synthetic payload"},
            }
        ).encode("utf-8")
        + b"\n"
    )
    process = FakeProcess(line)
    monkeypatch.setattr(
        stdio_jsonl, "start_codex_app_server_process", lambda: process
    )
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(request_timeout_seconds=0.5)
    )

    with pytest.raises(CodexProtocolViolation) as error:
        transport._request("initialize", {})

    rendered = str(error.value)
    assert private_method_canary not in rendered
    assert "private synthetic payload" not in rendered


def test_stdio_transport_sanitizes_provider_request_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_canary = "PRIVATE-PROVIDER-ERROR-CANARY"
    line = json.dumps(
        {
            "id": 1,
            "error": {
                "code": -32602,
                "message": private_canary,
                "data": {"path": private_canary},
            },
        }
    ).encode("utf-8") + b"\n"
    process = FakeProcess(line)
    monkeypatch.setattr(
        stdio_jsonl, "start_codex_app_server_process", lambda: process
    )
    transport = StdioJsonRpcTransport(
        limits=CodexReadLimits(request_timeout_seconds=0.5)
    )

    with pytest.raises(CodexRequestRejected) as raised:
        transport._request("initialize", {})

    assert str(raised.value) == "provider rejected a read-only request"
    assert private_canary not in repr(raised.value)
