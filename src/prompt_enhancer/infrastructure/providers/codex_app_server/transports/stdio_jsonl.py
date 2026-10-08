"""Bounded, local-only JSONL transport for ``codex app-server``."""

from __future__ import annotations

import json
import ntpath
import os
from enum import StrEnum
from queue import Empty, Full, Queue
import shutil
import subprocess
from threading import Event, Lock, Thread
import time
from typing import BinaryIO, Callable

from .....application.owned_process import (
    OwnedProcess,
    start_owned_process,
)
from .....application.runtime_cancellation import (
    RuntimeCooperativeStop,
    raise_if_runtime_cancelled,
)
from ..errors import (
    CodexProtocolViolation,
    CodexResponseLimitError,
    CodexRequestRejected,
    CodexTransportError,
    CodexTransportTimeout,
)
from ..limits import CodexReadLimits
from .protocol import JsonObject


ExecutableResolver = Callable[[str], str | None]

# Keep the literal fallback because this module is also imported by tests and
# packaging probes on non-Windows hosts. A Windows desktop launch must never
# depend on a console window being available.
_WINDOWS_CREATE_NO_WINDOW = 0x08000000


def codex_app_server_creation_flags(*, platform: str | None = None) -> int:
    current_platform = os.name if platform is None else platform
    if current_platform != "nt":
        return 0
    return int(
        getattr(subprocess, "CREATE_NO_WINDOW", _WINDOWS_CREATE_NO_WINDOW)
        or _WINDOWS_CREATE_NO_WINDOW
    )


def codex_app_server_argv(
    *, platform: str | None = None, which: ExecutableResolver = shutil.which
) -> tuple[str, ...]:
    """Build a fixed, non-user-controlled command for the local Codex CLI."""

    current_platform = os.name if platform is None else platform
    command: tuple[str, ...]
    if current_platform == "nt":
        # Prefer the native executable. npm's ``codex.cmd`` necessarily adds
        # cmd.exe (and commonly conhost.exe) to the process tree, which can
        # flash or retain terminal windows in a GUI application even when the
        # parent requested CREATE_NO_WINDOW.
        resolved_exe = which("codex.exe")
        if resolved_exe is not None:
            command = (ntpath.abspath(resolved_exe),)
        else:
            resolved_cmd = which("codex.cmd")
            command = (
                (
                    "cmd.exe",
                    "/d",
                    "/s",
                    "/c",
                    ntpath.abspath(resolved_cmd),
                )
                if resolved_cmd is not None
                else ("codex.exe",)
            )
    else:
        command = ("codex",)
    return (*command, "app-server", "--listen", "stdio://")


CODEX_APP_SERVER_ARGV = codex_app_server_argv()
MAX_CODEX_APP_SERVER_PROCESSES = 16
REQUEST_METHOD_ALLOWLIST = frozenset({"initialize", "thread/list", "thread/read"})
NOTIFICATION_METHOD_ALLOWLIST = frozenset({"initialized"})


class ThreadReadPolicy(StrEnum):
    NONE = "none"
    SUMMARY_ONLY = "summary_only"
    OPERATIONAL = "operational"
    TEXT_ANALYSIS = "text_analysis"


def start_codex_app_server_process() -> OwnedProcess:
    """Start the documented provider helper under exact tree ownership."""

    return start_owned_process(
        CODEX_APP_SERVER_ARGV,
        cwd=None,
        env=dict(os.environ),
        pipe_stdin=True,
        capture_stdout=True,
        capture_stderr=False,
        maximum_active_processes=MAX_CODEX_APP_SERVER_PROCESSES,
    )


class StdioJsonRpcTransport:
    """One-process, sequential JSON-RPC transport with no stderr capture."""

    def __init__(
        self,
        *,
        limits: CodexReadLimits | None = None,
        thread_read_policy: ThreadReadPolicy = ThreadReadPolicy.NONE,
    ) -> None:
        self._limits = limits or CodexReadLimits()
        self._thread_read_policy = thread_read_policy
        self._response_json_line_bytes = (
            self._limits.max_text_analysis_json_line_bytes
            if thread_read_policy is ThreadReadPolicy.TEXT_ANALYSIS
            else self._limits.max_json_line_bytes
        )
        self._process: OwnedProcess | None = None
        # A text response can be materially larger than metadata.  One queued
        # frame is sufficient for this sequential transport and prevents four
        # maximum-sized provider frames from accumulating in memory.
        queue_capacity = (
            1 if thread_read_policy is ThreadReadPolicy.TEXT_ANALYSIS else 4
        )
        self._lines: Queue[bytes | None] = Queue(maxsize=queue_capacity)
        self._reader: Thread | None = None
        self._reader_stop = Event()
        self._request_id = 0
        self._lock = Lock()

    def _start(self) -> None:
        if self._reader_stop.is_set():
            raise CodexTransportError("Codex App Server transport is closed")
        if self._process is not None:
            return
        try:
            process = start_codex_app_server_process()
        except (OSError, ValueError) as _error:
            raise CodexTransportError("Codex App Server is unavailable") from None
        if process.stdin is None or process.stdout is None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
            raise CodexTransportError("Codex App Server stdio is unavailable")
        self._process = process
        self._reader = Thread(
            target=self._read_lines,
            args=(process.stdout,),
            name="prompt-enhancer-codex-jsonl",
            daemon=True,
        )
        self._reader.start()

    def _queue_line(self, line: bytes | None) -> bool:
        while not self._reader_stop.is_set():
            try:
                self._lines.put(line, timeout=0.05)
                return True
            except Full:
                continue
        return False

    def _read_lines(self, stdout: BinaryIO) -> None:
        try:
            while True:
                line = stdout.readline(self._response_json_line_bytes + 1)
                if not line:
                    self._queue_line(None)
                    return
                if not self._queue_line(line):
                    return
                if len(line) > self._response_json_line_bytes or not line.endswith(b"\n"):
                    return
        except (OSError, ValueError):
            self._queue_line(None)

    def _write_message(self, payload: JsonObject) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise CodexTransportError("Codex App Server transport is not started")
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8") + b"\n"
        except (TypeError, ValueError):
            raise CodexProtocolViolation("outbound JSON-RPC message is invalid") from None
        if len(encoded) > self._limits.max_json_line_bytes:
            raise CodexProtocolViolation("outbound JSON-RPC message exceeded the line bound")
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise CodexTransportError("Codex App Server transport closed unexpectedly") from None

    def _next_message(self, *, deadline: float) -> JsonObject:
        while True:
            # Poll the request-owned cancellation signal more frequently than
            # the provider timeout.  Automation shutdown otherwise waits up to
            # ten seconds here while its worker owns only a five-second join.
            try:
                raise_if_runtime_cancelled("codex_provider_request_cancelled")
            except RuntimeCooperativeStop:
                # Kill only the transport-owned helper.  ``IngestionService``
                # still reaches its normal ``adapter.close`` finally block,
                # which reaps the process and joins the reader deterministically.
                self._abort_for_runtime_stop()
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexTransportTimeout("Codex App Server request timed out")
            try:
                line = self._lines.get(timeout=min(remaining, 0.05))
                break
            except Empty:
                continue
        if line is None:
            raise CodexTransportError("Codex App Server transport closed unexpectedly")
        if len(line) > self._response_json_line_bytes:
            raise CodexResponseLimitError(
                "provider JSON-RPC line exceeded the configured bound"
            )
        if not line.endswith(b"\n"):
            raise CodexProtocolViolation("provider returned an unterminated JSON-RPC line")
        try:
            payload = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CodexProtocolViolation("provider returned invalid JSON-RPC") from None
        if not isinstance(payload, dict):
            raise CodexProtocolViolation("provider returned an invalid JSON-RPC envelope")
        if "jsonrpc" in payload and payload["jsonrpc"] != "2.0":
            raise CodexProtocolViolation("provider returned an invalid JSON-RPC version")
        return payload

    def _abort_for_runtime_stop(self) -> None:
        """Unblock one cancelled provider wait without spawning cleanup work."""

        self._reader_stop.set()
        process = self._process
        if process is None:
            return
        try:
            process.kill()
        except (OSError, ValueError):
            pass

    @staticmethod
    def _is_server_request(payload: JsonObject) -> bool:
        return "method" in payload and "id" in payload

    def _validate_request(self, method: str, params: JsonObject) -> None:
        if method not in REQUEST_METHOD_ALLOWLIST:
            raise CodexProtocolViolation("outbound JSON-RPC method is not allowed")
        if method == "thread/list" and params.get("useStateDbOnly") is not True:
            raise CodexProtocolViolation(
                "thread listing must use the read-only state database"
            )
        if method != "thread/read":
            return
        if self._thread_read_policy is ThreadReadPolicy.NONE:
            raise CodexProtocolViolation("thread reads are disabled for this transport")
        if set(params) != {"threadId", "includeTurns"}:
            raise CodexProtocolViolation("thread read parameters are not allowed")
        thread_id = params.get("threadId")
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or len(thread_id) > 4_096
        ):
            raise CodexProtocolViolation("thread read identifier is invalid")
        include_turns = params.get("includeTurns")
        if (
            self._thread_read_policy is ThreadReadPolicy.SUMMARY_ONLY
            and include_turns is not False
        ):
            raise CodexProtocolViolation("summary transport requires a no-turn read")
        if self._thread_read_policy in {
            ThreadReadPolicy.OPERATIONAL,
            ThreadReadPolicy.TEXT_ANALYSIS,
        } and include_turns is not True:
            purpose = self._thread_read_policy.value.replace("_", " ")
            raise CodexProtocolViolation(f"{purpose} transport requires a turn read")

    def _request(self, method: str, params: JsonObject) -> object:
        self._validate_request(method, params)
        self._start()
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            self._write_message(
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            timeout = (
                self._limits.text_analysis_request_timeout_seconds
                if method == "thread/read"
                and self._thread_read_policy is ThreadReadPolicy.TEXT_ANALYSIS
                else self._limits.request_timeout_seconds
            )
            deadline = time.monotonic() + timeout
            while True:
                payload = self._next_message(deadline=deadline)
                if self._is_server_request(payload):
                    self.close()
                    raise CodexProtocolViolation(
                        "provider-initiated requests are not supported"
                    )
                if "method" in payload:
                    # Notifications are deliberately ignored and cannot trigger work.
                    continue
                if payload.get("id") != request_id:
                    self.close()
                    raise CodexProtocolViolation("provider returned an unexpected response id")
                if "error" in payload:
                    # Provider error messages and data may contain identifiers,
                    # paths, or content. Deliberately discard the entire payload
                    # and expose only this closed, content-free category.
                    raise CodexRequestRejected("provider rejected a read-only request")
                if "result" not in payload:
                    raise CodexProtocolViolation("provider returned an incomplete response")
                return payload["result"]

    def _notify(self, method: str, params: JsonObject | None = None) -> None:
        if method not in NOTIFICATION_METHOD_ALLOWLIST or params != {}:
            raise CodexProtocolViolation(
                "outbound JSON-RPC notification is not allowed"
            )
        self._start()
        with self._lock:
            self._write_message({"method": method, "params": params})

    def close(self) -> None:
        process = self._process
        self._process = None
        cleanup_confirmed = True
        if process is not None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            root_exit_observed = False
            try:
                process.wait(timeout=self._limits.shutdown_timeout_seconds)
                root_exit_observed = True
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.terminate()
                    process.wait(timeout=self._limits.shutdown_timeout_seconds)
                    root_exit_observed = True
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=self._limits.shutdown_timeout_seconds)
                        root_exit_observed = True
                    except (OSError, subprocess.TimeoutExpired):
                        cleanup_confirmed = False
            tree_exited = getattr(process, "tree_exited", None)
            if callable(tree_exited):
                try:
                    cleanup_confirmed = bool(tree_exited()) and cleanup_confirmed
                except Exception:
                    cleanup_confirmed = False
            else:
                cleanup_confirmed = root_exit_observed and cleanup_confirmed
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except (OSError, ValueError):
                    cleanup_confirmed = False
            close = getattr(process, "close", None)
            if callable(close):
                try:
                    cleanup_confirmed = bool(close(close_streams=False)) and cleanup_confirmed
                except Exception:
                    cleanup_confirmed = False

        self._reader_stop.set()
        while True:
            try:
                self._lines.get_nowait()
            except Empty:
                break
        try:
            self._lines.put_nowait(None)
        except Full:
            pass

        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.join(timeout=self._limits.shutdown_timeout_seconds)
            cleanup_confirmed = not reader.is_alive() and cleanup_confirmed
        if not cleanup_confirmed:
            raise CodexTransportError(
                "Codex App Server cleanup could not be confirmed"
            ) from None

    def __enter__(self) -> StdioJsonRpcTransport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
