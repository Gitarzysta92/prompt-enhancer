"""Bounded MCP stdio transport with owned process-tree cleanup.

The upstream MCP transport hides console windows but assigns its Windows Job
Object after process creation.  A hostile server can spawn a descendant in
that gap.  This adapter admits the root to an owned job atomically on Windows
and starts a new process group on POSIX.  Shutdown is not considered complete
until the root and its ordinary descendants are gone and every pipe is closed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import os
import signal
import subprocess
import sys
from typing import Any, BinaryIO, Protocol

import anyio
from anyio.streams.file import FileReadStream, FileWriteStream
import mcp_types as types

from mcp.shared.message import SessionMessage

from ..application.mcp_guarded_host import McpGuardedHostError


_READ_BYTES = 64 * 1024
_WRITER_FLUSH_SECONDS = 0.5
_GRACEFUL_EXIT_SECONDS = 0.5
_FORCED_EXIT_SECONDS = 2.0
_POLL_SECONDS = 0.01
MAX_MCP_STDIO_PROCESSES = 16
MAX_MCP_STDERR_BYTES = 2 * 1024 * 1024


class _OwnedProcess(Protocol):
    pid: int
    stdin: BinaryIO | None
    stdout: BinaryIO | None
    stderr: BinaryIO | None

    def poll(self) -> int | None: ...

    def tree_exited(self) -> bool: ...

    def terminate(self) -> None: ...

    def close(self, *, close_streams: bool = True) -> bool: ...

    def visible_window_detected(self) -> bool: ...


class _PosixMcpProcessGroup:
    def __init__(self, argv: list[str], *, cwd: str | None, env: dict[str, str]) -> None:
        self._process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
            close_fds=True,
        )
        self.pid = self._process.pid
        self.stdin = self._process.stdin
        self.stdout = self._process.stdout
        self.stderr = self._process.stderr

    def poll(self) -> int | None:
        return self._process.poll()

    def tree_exited(self) -> bool:
        try:
            os.killpg(self.pid, 0)
        except ProcessLookupError:
            return True
        return False

    def terminate(self) -> None:
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    @staticmethod
    def visible_window_detected() -> bool:
        return False

    def close(self, *, close_streams: bool = True) -> bool:
        closed = True
        if close_streams:
            for stream in (self.stdin, self.stdout, self.stderr):
                if stream is None:
                    continue
                try:
                    stream.close()
                except OSError:
                    closed = False
        return closed


def start_owned_stdio_process(
    argv: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
) -> _OwnedProcess:
    """Start one stdio server with atomic descendant ownership."""

    if sys.platform == "win32":
        from ..application.local_command_windows import WindowsCommandJob

        return WindowsCommandJob(
            argv,
            cwd=cwd,
            env=env,
            pipe_stdin=True,
            maximum_active_processes=MAX_MCP_STDIO_PROCESSES,
        )
    return _PosixMcpProcessGroup(argv, cwd=cwd, env=env)


@dataclass(slots=True)
class McpStdioCleanupEvidence:
    process_started: bool = False
    root_pid: int | None = None
    root_exited: bool = False
    tree_exited: bool = False
    streams_closed: bool = False
    cleanup_verified: bool = False
    descendant_limit_applied: bool = False
    visible_window_detected: bool = False
    output_limit_exceeded: bool = False


async def _wait_for_tree(process: _OwnedProcess, timeout: float) -> bool:
    deadline = anyio.current_time() + timeout
    while True:
        try:
            root_exited = process.poll() is not None
            tree_exited = process.tree_exited()
        except Exception:
            return False
        if root_exited and tree_exited:
            return True
        if anyio.current_time() >= deadline:
            return False
        await anyio.sleep(_POLL_SECONDS)


async def _close_stream(stream: Any) -> bool:
    if stream is None:
        return True
    try:
        await stream.aclose()
    except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
        return False
    return True


async def _stop_owned_process(
    process: _OwnedProcess,
    streams: tuple[Any, ...],
    evidence: McpStdioCleanupEvidence,
) -> None:
    confirmed = await _wait_for_tree(process, _GRACEFUL_EXIT_SECONDS)
    if not confirmed:
        with suppress(Exception):
            process.terminate()
        confirmed = await _wait_for_tree(process, _FORCED_EXIT_SECONDS)
    try:
        evidence.root_exited = process.poll() is not None
        evidence.tree_exited = process.tree_exited()
    except Exception:
        evidence.root_exited = False
        evidence.tree_exited = False
    try:
        handles_closed = process.close(close_streams=False)
    except Exception:
        handles_closed = False
    stream_results = [await _close_stream(stream) for stream in streams]
    evidence.streams_closed = handles_closed and all(stream_results)
    evidence.cleanup_verified = (
        confirmed
        and evidence.root_exited
        and evidence.tree_exited
        and evidence.streams_closed
    )


def _safe_message(line: bytes) -> SessionMessage | McpGuardedHostError:
    if line.endswith(b"\r"):
        line = line[:-1]
    try:
        text = line.decode("utf-8", errors="strict")
        message = types.jsonrpc_message_adapter.validate_json(text, by_name=False)
    except (UnicodeError, ValueError):
        return McpGuardedHostError("mcp_host_jsonrpc_invalid")
    return SessionMessage(message)


class _ErrorRaisingReceiveStream:
    """Turn our content-free terminal policy codes into transport failures.

    The SDK treats yielded ``Exception`` values as notifications and may leave
    an in-flight request waiting for EOF.  Raising here settles the dispatcher
    immediately while retaining only the stable local reason code.
    """

    def __init__(self, source: Any) -> None:
        self._source = source

    async def receive(self) -> SessionMessage:
        item = await self._source.receive()
        if isinstance(item, McpGuardedHostError):
            raise item
        if isinstance(item, Exception):
            raise McpGuardedHostError("mcp_host_stdio_transport_failed") from None
        return item

    def __aiter__(self) -> "_ErrorRaisingReceiveStream":
        return self

    async def __anext__(self) -> SessionMessage:
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    async def __aenter__(self) -> "_ErrorRaisingReceiveStream":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    def close(self) -> None:
        self._source.close()

    async def aclose(self) -> None:
        await self._source.aclose()


@asynccontextmanager
async def owned_stdio_client(
    *,
    executable: str,
    arguments: tuple[str, ...],
    environment: dict[str, str],
    working_directory: str | None,
    maximum_response_bytes: int,
    evidence: McpStdioCleanupEvidence,
) -> AsyncIterator[tuple[Any, Any]]:
    """Yield MCP streams and verify bounded, tree-wide cleanup on every exit."""

    try:
        process = start_owned_stdio_process(
            [executable, *arguments],
            cwd=working_directory,
            env=environment,
        )
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        raise McpGuardedHostError("mcp_host_stdio_start_failed") from None
    evidence.process_started = True
    evidence.root_pid = process.pid
    evidence.descendant_limit_applied = sys.platform == "win32"
    if process.stdin is None or process.stdout is None or process.stderr is None:
        with suppress(Exception):
            process.terminate()
        await _stop_owned_process(process, (), evidence)
        raise McpGuardedHostError("mcp_host_stdio_pipes_unavailable")

    stdin = FileWriteStream(process.stdin)
    stdout = FileReadStream(process.stdout)
    stderr = FileReadStream(process.stderr)
    read_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](4)
    guarded_read_stream = _ErrorRaisingReceiveStream(read_stream)
    write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](0)
    writer_done = anyio.Event()
    terminal_error_sent = False
    stdout_messages = read_writer.clone()
    stderr_messages = read_writer.clone()
    policy_messages = read_writer.clone() if sys.platform == "win32" else None

    async def fail_transport(code: str, writer: Any) -> None:
        nonlocal terminal_error_sent
        if terminal_error_sent:
            return
        terminal_error_sent = True
        with suppress(Exception):
            process.terminate()
        await writer.send(McpGuardedHostError(code))

    async def stdout_reader() -> None:
        buffer = bytearray()
        received = 0
        async with stdout_messages:
            while True:
                try:
                    chunk = await stdout.receive(_READ_BYTES)
                except anyio.EndOfStream:
                    break
                except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
                    return
                received += len(chunk)
                if received > maximum_response_bytes:
                    evidence.output_limit_exceeded = True
                    await fail_transport("mcp_host_response_too_large", stdout_messages)
                    return
                buffer.extend(chunk)
                while True:
                    marker = buffer.find(b"\n")
                    if marker < 0:
                        if len(buffer) > maximum_response_bytes:
                            evidence.output_limit_exceeded = True
                            await fail_transport("mcp_host_response_too_large", stdout_messages)
                            return
                        break
                    line = bytes(buffer[:marker])
                    del buffer[: marker + 1]
                    if not line:
                        continue
                    message = _safe_message(line)
                    if isinstance(message, McpGuardedHostError):
                        await fail_transport(message.code, stdout_messages)
                        return
                    await stdout_messages.send(message)
            if buffer:
                await fail_transport("mcp_host_jsonrpc_invalid", stdout_messages)

    async def stdin_writer() -> None:
        try:
            async with write_reader:
                async for session_message in write_reader:
                    payload = (
                        session_message.message.model_dump_json(
                            by_alias=True,
                            exclude_unset=True,
                        )
                        + "\n"
                    ).encode("utf-8")
                    if len(payload) > maximum_response_bytes:
                        raise McpGuardedHostError("mcp_host_request_too_large")
                    await stdin.send(payload)
        except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass
        finally:
            await _close_stream(stdin)
            writer_done.set()

    async def stderr_reader() -> None:
        received = 0
        async with stderr_messages:
            while True:
                try:
                    chunk = await stderr.receive(_READ_BYTES)
                except (
                    anyio.EndOfStream,
                    OSError,
                    anyio.BrokenResourceError,
                    anyio.ClosedResourceError,
                ):
                    return
                received += len(chunk)
                if received > MAX_MCP_STDERR_BYTES:
                    evidence.output_limit_exceeded = True
                    await fail_transport(
                        "mcp_host_process_output_limit",
                        stderr_messages,
                    )
                    return

    async def process_policy_monitor() -> None:
        if policy_messages is None:
            return
        async with policy_messages:
            while True:
                try:
                    if process.poll() is not None:
                        return
                    if process.visible_window_detected():
                        evidence.visible_window_detected = True
                        await fail_transport(
                            "mcp_host_visible_window_detected",
                            policy_messages,
                        )
                        return
                except Exception:
                    await fail_transport(
                        "mcp_host_process_visibility_unconfirmed",
                        policy_messages,
                    )
                    return
                await anyio.sleep(_POLL_SECONDS)

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(stdout_reader)
        task_group.start_soon(stdin_writer)
        task_group.start_soon(stderr_reader)
        task_group.start_soon(process_policy_monitor)
        read_writer.close()
        try:
            yield guarded_read_stream, write_stream
        finally:
            with anyio.CancelScope(shield=True):
                guarded_read_stream.close()
                write_stream.close()
                with anyio.move_on_after(_WRITER_FLUSH_SECONDS):
                    await writer_done.wait()
                await _stop_owned_process(
                    process,
                    (
                        stdin,
                        stdout,
                        stderr,
                        read_writer,
                        guarded_read_stream,
                        write_stream,
                        write_reader,
                    ),
                    evidence,
                )
            task_group.cancel_scope.cancel()
    await anyio.lowlevel.cancel_shielded_checkpoint()
    if not evidence.cleanup_verified:
        raise McpGuardedHostError("mcp_host_cleanup_unconfirmed")


__all__ = (
    "MAX_MCP_STDERR_BYTES",
    "MAX_MCP_STDIO_PROCESSES",
    "McpStdioCleanupEvidence",
    "owned_stdio_client",
    "start_owned_stdio_process",
)
