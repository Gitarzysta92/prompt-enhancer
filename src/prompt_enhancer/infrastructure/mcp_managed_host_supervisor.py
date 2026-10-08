"""Memory-only supervisor for owner-started project-scoped MCP hosts.

One daemon event-loop thread owns every official-SDK client for its complete
lifetime.  The synchronous Agent/API facade never receives an SDK object,
process handle, endpoint, credential, command or path.  No host starts during
construction or application boot, and failures never reconnect automatically.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    TimeoutError as FutureTimeoutError,
)
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import threading
import time
from collections.abc import Sequence
from typing import Any, Literal, Mapping, NoReturn

from mcp.types import Implementation

from ..application.mcp_guarded_host import (
    McpGuardedHostError,
    McpRemoteConnectionSpec,
    McpStdioConnectionSpec,
    review_mcp_tool_contracts,
)
from ..application.mcp_managed_host import (
    MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS,
    MAX_MCP_MANAGED_ACTIVE_HOSTS,
    MAX_MCP_MANAGED_HOST_HEALTH_SECONDS,
    McpManagedHostBinding,
    McpManagedHostStatus,
    StopMcpManagedHost,
)
from ..application.mcp_managed_runtime import (
    MAX_MCP_MANAGED_RESULT_BYTES,
    MAX_MCP_MANAGED_RESULT_CHARS,
    MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS,
    McpManagedCallProjection,
    McpManagedRuntimeError,
    validate_mcp_tool_result,
)
from ..application.mcp_server_management import (
    McpManagedReviewedTool,
    McpManagedToolSnapshot,
)
from .mcp_guarded_host import (
    MCP_READ_TIMEOUT_SECONDS,
    McpSdkClientLease,
    OfficialSdkMcpConnectionFactory,
    enumerate_mcp_tool_contracts,
)


MAX_MCP_MANAGED_CLEANUP_SECONDS = 4.0


@dataclass(slots=True, repr=False)
class _HostActor:
    binding: McpManagedHostBinding
    connection: McpRemoteConnectionSpec | McpStdioConnectionSpec | None
    snapshot: McpManagedToolSnapshot
    instance_id: str
    status: McpManagedHostStatus
    context: Any | None = None
    lease: McpSdkClientLease | None = None
    health_task: asyncio.Task[None] | None = None
    start_task: asyncio.Task[Any] | None = None
    active_call: asyncio.Task[Any] | None = None
    call_reserved: bool = False
    closing: bool = False
    closed: threading.Event = field(default_factory=threading.Event)
    context_enter_started: bool = False
    call_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _now() -> datetime:
    return datetime.now(UTC)


def _error_code(error: BaseException, fallback: str) -> str:
    # SDK/server exceptions may carry attacker-controlled diagnostic or code
    # attributes.  Only our two closed internal taxonomies may cross the
    # content-free runtime boundary; every other exception uses a fixed code.
    code = (
        error.code
        if isinstance(error, (McpGuardedHostError, McpManagedRuntimeError))
        else None
    )
    if isinstance(code, str) and code and len(code) <= 96 and all(
        character.islower() or character.isdigit() or character == "_"
        for character in code
    ):
        return code
    return fallback


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    with suppress(BaseException):
        task.result()


def _snapshot_matches(
    binding: McpManagedHostBinding,
    snapshot: McpManagedToolSnapshot,
    *,
    protocol_version: str,
    observed: tuple[Any, ...],
    schema_digest: str,
) -> bool:
    if (
        snapshot.management_id != binding.management_id
        or snapshot.snapshot_id != binding.tool_snapshot_id
        or snapshot.schema_digest != binding.tool_schema_digest
        or snapshot.tool_count != binding.reviewed_tool_count
        or snapshot.protocol_version != protocol_version
        or schema_digest != snapshot.schema_digest
        or len(observed) != snapshot.tool_count
    ):
        return False
    try:
        normalized = tuple(McpManagedReviewedTool.from_guarded(item) for item in observed)
    except Exception:
        return False
    return normalized == snapshot.tools


def _project_result(
    *,
    call_id: str,
    result: Any,
    output_schema: Mapping[str, Any] | None,
) -> McpManagedCallProjection:
    if getattr(result, "result_type", "complete") != "complete":
        raise McpManagedRuntimeError("mcp_tool_result_incomplete")

    content = getattr(result, "content", ())
    if not isinstance(content, Sequence) or isinstance(
        content, (str, bytes, bytearray)
    ):
        raise McpManagedRuntimeError("mcp_tool_result_malformed")
    if len(content) > MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS:
        raise McpManagedRuntimeError("mcp_tool_result_too_complex")
    text_parts: list[str] = []
    text_characters = 0
    text_bytes = 0
    for item in content:
        if getattr(item, "type", None) != "text" or not isinstance(
            getattr(item, "text", None), str
        ):
            raise McpManagedRuntimeError("mcp_tool_result_content_unsupported")
        text = item.text
        if "\x00" in text:
            raise McpManagedRuntimeError("mcp_tool_result_malformed")
        text_characters += len(text)
        text_bytes += len(text.encode("utf-8"))
        if (
            text_characters + max(0, len(text_parts)) > MAX_MCP_MANAGED_RESULT_CHARS
            or text_bytes + max(0, len(text_parts)) > MAX_MCP_MANAGED_RESULT_BYTES
        ):
            raise McpManagedRuntimeError("mcp_tool_result_too_large")
        text_parts.append(text)

    structured = getattr(result, "structured_content", None)
    if structured is not None:
        structured, _encoded_structured = validate_mcp_tool_result(
            structured,
            output_schema,
        )
    elif output_schema is not None:
        raise McpManagedRuntimeError("mcp_tool_result_schema_mismatch")

    error_state = getattr(result, "is_error", False)
    if not isinstance(error_state, bool):
        raise McpManagedRuntimeError("mcp_tool_result_malformed")

    text_value = "\n".join(text_parts)
    structured_value = (
        ""
        if structured is None
        else json.dumps(
            structured,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )
    if text_value and structured_value:
        rendered = text_value + "\n\nStructured result:\n" + structured_value
        mode: Literal["text", "structured_json", "text_and_structured_json", "none"] = (
            "text_and_structured_json"
        )
    elif structured_value:
        rendered = structured_value
        mode = "structured_json"
    elif text_value:
        rendered = text_value
        mode = "text"
    else:
        rendered = "The MCP tool returned no supported content."
        mode = "none"
    encoded = rendered.encode("utf-8")
    if len(rendered) > MAX_MCP_MANAGED_RESULT_CHARS or len(encoded) > MAX_MCP_MANAGED_RESULT_BYTES:
        raise McpManagedRuntimeError("mcp_tool_result_too_large")
    return McpManagedCallProjection(
        call_id=call_id,
        outcome="tool_error" if error_state else "succeeded",
        text=rendered,
        result_bytes=len(encoded),
        result_digest=hashlib.sha256(encoded).hexdigest(),
        content_mode=mode,
        cleanup_verified=True,
    )


class McpManagedHostSupervisor:
    """Own guarded persistent MCP clients without durable run authority."""

    def __init__(
        self,
        connection_factory: OfficialSdkMcpConnectionFactory | None = None,
        *,
        clock: Any | None = None,
        health_interval_seconds: float = MCP_MANAGED_HOST_HEALTH_INTERVAL_SECONDS,
    ) -> None:
        self._connections = connection_factory or OfficialSdkMcpConnectionFactory()
        self._clock = clock or _now
        self._health_interval = max(0.05, float(health_interval_seconds))
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._actors: dict[tuple[str, str], _HostActor] = {}
        self._last: dict[tuple[str, str], McpManagedHostStatus] = {}
        self._shutdown = False

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._shutdown:
                raise McpManagedRuntimeError("mcp_managed_runtime_shutdown")
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            self._loop = loop

            def run() -> None:
                asyncio.set_event_loop(loop)
                self._loop_ready.set()
                loop.run_forever()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()

            thread = threading.Thread(
                target=run,
                name="prompt-enhancer-mcp-hosts",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        if not self._loop_ready.wait(2.0):
            raise McpManagedRuntimeError("mcp_managed_runtime_unavailable")
        return loop

    def _stopped(
        self,
        management_id: str,
        project_id: str,
        *,
        reason: Literal["never_started", "stopped_by_owner", "stopped_after_restart", "start_cancelled", "app_shutdown"] = "never_started",
    ) -> McpManagedHostStatus:
        now = self._clock()
        return McpManagedHostStatus(
            management_id=management_id,
            project_id=project_id,
            state="not_started",
            reason=reason,
            last_transition_at=now,
            stopped_at=now if reason != "never_started" else None,
            process_started=False,
            cleanup_state=("verified" if reason != "never_started" else "not_applicable"),
            host_lease_active=False,
        )

    def status(self, management_id: str, project_id: str) -> McpManagedHostStatus:
        key = (management_id, project_id)
        with self._lock:
            actor = self._actors.get(key)
            if actor is not None:
                return actor.status
            return self._last.get(key) or self._stopped(*key)

    def statuses(self) -> tuple[McpManagedHostStatus, ...]:
        with self._lock:
            combined = dict(self._last)
            combined.update({key: actor.status for key, actor in self._actors.items()})
            return tuple(combined[key] for key in sorted(combined))

    def start(
        self,
        binding: McpManagedHostBinding,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        snapshot: McpManagedToolSnapshot,
        *,
        deadline_seconds: float,
    ) -> McpManagedHostStatus:
        if (
            snapshot.management_id != binding.management_id
            or snapshot.snapshot_id != binding.tool_snapshot_id
            or snapshot.schema_digest != binding.tool_schema_digest
            or snapshot.tool_count != binding.reviewed_tool_count
        ):
            raise McpManagedRuntimeError("mcp_managed_host_tool_snapshot_conflict")
        key = (binding.management_id, binding.project_id)
        now = self._clock()
        instance_id = hashlib.sha256(
            f"{key}:{time.monotonic_ns()}".encode("ascii")
        ).hexdigest()[:32]
        with self._lock:
            if self._shutdown:
                raise McpManagedRuntimeError("mcp_managed_runtime_shutdown")
            existing = self._actors.get(key)
            if existing is not None:
                if existing.binding == binding and existing.status.state in {"starting", "ready"}:
                    return existing.status
                raise McpManagedRuntimeError("mcp_managed_host_already_active")
            if len(self._actors) >= MAX_MCP_MANAGED_ACTIVE_HOSTS:
                raise McpManagedRuntimeError("mcp_managed_host_limit_reached")
            local = binding.transport == "stdio"
            actor = _HostActor(
                binding=binding,
                connection=connection,
                snapshot=snapshot,
                instance_id=instance_id,
                status=McpManagedHostStatus(
                    management_id=binding.management_id,
                    project_id=binding.project_id,
                    state="starting",
                    reason="start_requested",
                    binding=binding,
                    instance_id=instance_id,
                    started_at=now,
                    last_transition_at=now,
                    process_started=False,
                    cleanup_state="not_applicable",
                    host_lease_active=False,
                ),
            )
            self._actors[key] = actor
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._start_actor(actor, deadline_seconds),
            loop,
        )
        try:
            return future.result(timeout=deadline_seconds + 2.0)
        except FutureTimeoutError:
            future.cancel()
            with suppress(Exception):
                self.stop(
                    binding.management_id,
                    binding.project_id,
                    StopMcpManagedHost(
                        request_id=hashlib.sha256(
                            f"start-timeout:{instance_id}".encode("ascii")
                        ).hexdigest()[:32],
                        expected_instance_id=instance_id,
                    ),
                )
            raise McpManagedRuntimeError("mcp_managed_host_start_timeout") from None
        except FutureCancelledError:
            raise McpManagedRuntimeError("mcp_managed_host_start_cancelled") from None
        except McpManagedRuntimeError:
            raise
        except Exception as error:
            raise McpManagedRuntimeError(
                _error_code(error, "mcp_managed_host_start_failed")
            ) from None

    async def _start_actor(
        self,
        actor: _HostActor,
        deadline_seconds: float,
    ) -> McpManagedHostStatus:
        key = (actor.binding.management_id, actor.binding.project_id)
        loop = asyncio.get_running_loop()
        operation_deadline = loop.time() + deadline_seconds
        actor.start_task = asyncio.current_task()

        def remaining() -> float:
            return max(0.0, operation_deadline - loop.time())

        try:
            if actor.connection is None:
                raise McpManagedRuntimeError("mcp_managed_host_connection_unavailable")
            context = self._connections.connect(
                actor.connection,
                read_timeout_seconds=min(MCP_READ_TIMEOUT_SECONDS, deadline_seconds),
                client_info=Implementation(
                    name="prompt-enhancer-managed-host",
                    version="1",
                ),
            )
            actor.context = context
            actor.context_enter_started = True
            actor.lease = await asyncio.wait_for(
                context.__aenter__(),
                timeout=remaining(),
            )
            if actor.closing:
                raise asyncio.CancelledError
            local = actor.binding.transport == "stdio"
            cleanup = actor.lease.process_cleanup
            process_started = local and bool(cleanup and cleanup.process_started)
            if local and not process_started:
                raise McpManagedRuntimeError(
                    "mcp_managed_host_process_evidence_missing"
                )
            actor.status = actor.status.model_copy(
                update={
                    "process_started": process_started,
                    "cleanup_state": "pending" if process_started else "not_applicable",
                }
            )
            with self._lock:
                self._last[key] = actor.status
            protocol, discovered = await asyncio.wait_for(
                enumerate_mcp_tool_contracts(actor.lease.client),
                timeout=remaining(),
            )
            if actor.closing:
                raise asyncio.CancelledError
            observed, digest = review_mcp_tool_contracts(
                actor.binding.management_id,
                discovered,
            )
            if not _snapshot_matches(
                actor.binding,
                actor.snapshot,
                protocol_version=protocol,
                observed=observed,
                schema_digest=digest,
            ):
                raise McpManagedRuntimeError("mcp_managed_host_contract_drift")
            now = self._clock()
            actor.status = McpManagedHostStatus(
                management_id=actor.binding.management_id,
                project_id=actor.binding.project_id,
                state="ready",
                reason="healthy",
                binding=actor.binding,
                instance_id=actor.instance_id,
                observed_tool_count=len(observed),
                observed_schema_digest=digest,
                started_at=actor.status.started_at,
                last_checked_at=now,
                last_transition_at=now,
                process_started=process_started,
                cleanup_state="pending" if local else "not_applicable",
                host_lease_active=True,
                tool_calls_available=True,
                tool_routing_state="project_scoped_fresh_approval",
            )
            with self._lock:
                self._last[key] = actor.status
            actor.health_task = asyncio.create_task(self._health_loop(actor))
            return actor.status
        except asyncio.TimeoutError:
            code = "mcp_managed_host_start_timeout"
            if actor.lease is None:
                actor.context = None
            await self._close_actor(
                actor,
                final="failed",
                error_code=code,
                cleanup_timeout_seconds=min(2.0, deadline_seconds),
            )
            raise McpManagedRuntimeError(code) from None
        except BaseException as error:
            if isinstance(error, asyncio.CancelledError):
                if actor.lease is None:
                    actor.context = None
                raise
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            code = _error_code(error, "mcp_managed_host_start_failed")
            if actor.lease is None:
                actor.context = None
            await self._close_actor(
                actor,
                final="failed",
                error_code=code,
                cleanup_timeout_seconds=min(2.0, deadline_seconds),
            )
            raise McpManagedRuntimeError(code) from None

    async def _health_loop(self, actor: _HostActor) -> None:
        try:
            while True:
                await asyncio.sleep(self._health_interval)
                if (
                    actor.status.state != "ready"
                    or actor.lease is None
                    or actor.closing
                ):
                    return
                async with actor.call_lock:
                    protocol, discovered = await asyncio.wait_for(
                        enumerate_mcp_tool_contracts(actor.lease.client),
                        timeout=MAX_MCP_MANAGED_HOST_HEALTH_SECONDS,
                    )
                    observed, digest = review_mcp_tool_contracts(
                        actor.binding.management_id,
                        discovered,
                    )
                    if not _snapshot_matches(
                        actor.binding,
                        actor.snapshot,
                        protocol_version=protocol,
                        observed=observed,
                        schema_digest=digest,
                    ):
                        raise McpManagedRuntimeError("mcp_managed_host_contract_drift")
                    now = self._clock()
                    actor.status = actor.status.model_copy(
                        update={"last_checked_at": now, "last_transition_at": now}
                    )
                    with self._lock:
                        self._last[(actor.binding.management_id, actor.binding.project_id)] = actor.status
        except asyncio.CancelledError:
            return
        except BaseException as error:
            code = _error_code(error, "mcp_managed_host_health_failed")
            await self._close_actor(actor, final="unhealthy", error_code=code)

    def stop(
        self,
        management_id: str,
        project_id: str,
        command: StopMcpManagedHost,
    ) -> McpManagedHostStatus:
        key = (management_id, project_id)
        wait_for_existing_close = False
        with self._lock:
            actor = self._actors.get(key)
            if actor is None:
                stopped = self._stopped(
                    management_id,
                    project_id,
                    reason="stopped_by_owner",
                )
                self._last[key] = stopped
                return stopped
            if (
                command.expected_instance_id is not None
                and command.expected_instance_id != actor.instance_id
            ):
                raise McpManagedRuntimeError("mcp_managed_host_instance_conflict")
            if actor.status.state == "cleanup_required":
                return actor.status
            if actor.closing:
                wait_for_existing_close = True
            else:
                now = self._clock()
                actor.closing = True
                actor.status = actor.status.model_copy(
                    update={
                        "state": "stopping",
                        "reason": "owner_stop",
                        "host_lease_active": False,
                        "tool_calls_available": False,
                        "tool_routing_state": "inactive",
                        "last_transition_at": now,
                        "error_code": None,
                    }
                )
                self._last[key] = actor.status
        if wait_for_existing_close:
            if not actor.closed.wait(
                timeout=min(
                    command.deadline_seconds,
                    MAX_MCP_MANAGED_CLEANUP_SECONDS,
                )
                + 2.0
            ):
                raise McpManagedRuntimeError(
                    "mcp_host_cleanup_unconfirmed"
                ) from None
            with self._lock:
                return self._last.get(key, actor.status)
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._close_actor(
                actor,
                final="stopped",
                error_code=None,
                cleanup_timeout_seconds=command.deadline_seconds,
            ),
            loop,
        )
        try:
            return future.result(
                timeout=min(
                    command.deadline_seconds,
                    MAX_MCP_MANAGED_CLEANUP_SECONDS,
                ) + 2.0
            )
        except FutureTimeoutError:
            future.cancel()
            raise McpManagedRuntimeError("mcp_managed_host_stop_timeout") from None
        except McpManagedRuntimeError:
            raise
        except Exception as error:
            raise McpManagedRuntimeError(
                _error_code(error, "mcp_managed_host_stop_failed")
            ) from None

    async def _close_actor(
        self,
        actor: _HostActor,
        *,
        final: Literal["stopped", "failed", "unhealthy", "shutdown"],
        error_code: str | None,
        cleanup_timeout_seconds: float = MAX_MCP_MANAGED_CLEANUP_SECONDS,
    ) -> McpManagedHostStatus:
        key = (actor.binding.management_id, actor.binding.project_id)
        actor.closing = True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(
            0.1,
            min(MAX_MCP_MANAGED_CLEANUP_SECONDS, float(cleanup_timeout_seconds)),
        )

        async def cancel_bounded(task: asyncio.Task[Any]) -> bool:
            task.cancel()
            remaining = max(0.0, deadline - loop.time())
            done, _pending = await asyncio.wait(
                {task},
                timeout=min(0.05, remaining * 0.1),
            )
            if task in done:
                with suppress(BaseException):
                    task.result()
                return True
            task.add_done_callback(_consume_task_result)
            return False

        current = asyncio.current_task()
        cleanup_error: BaseException | None = None
        if actor.start_task is not None and actor.start_task is not current:
            if not await cancel_bounded(actor.start_task):
                cleanup_error = McpManagedRuntimeError(
                    "mcp_host_cleanup_unconfirmed"
                )
        if actor.health_task is not None and actor.health_task is not current:
            if not await cancel_bounded(actor.health_task):
                cleanup_error = McpManagedRuntimeError(
                    "mcp_host_cleanup_unconfirmed"
                )
        if actor.active_call is not None and actor.active_call is not current:
            if not await cancel_bounded(actor.active_call):
                cleanup_error = McpManagedRuntimeError(
                    "mcp_host_cleanup_unconfirmed"
                )
        if actor.context is not None:
            close_task = asyncio.create_task(
                actor.context.__aexit__(None, None, None)
            )
            try:
                done, _pending = await asyncio.wait(
                    {close_task},
                    timeout=max(0.0, deadline - loop.time()),
                )
                if close_task not in done:
                    close_task.cancel()
                    close_task.add_done_callback(_consume_task_result)
                    raise McpManagedRuntimeError(
                        "mcp_host_cleanup_unconfirmed"
                    )
                close_task.result()
            except BaseException as error:
                cleanup_error = error
        if actor.active_call is not None and actor.active_call is not current:
            if not actor.active_call.done():
                actor.active_call.cancel()
                done, _pending = await asyncio.wait(
                    {actor.active_call},
                    timeout=max(0.0, deadline - loop.time()),
                )
                if actor.active_call not in done:
                    cleanup_error = McpManagedRuntimeError(
                        "mcp_host_cleanup_unconfirmed"
                    )
            if actor.active_call.done():
                with suppress(BaseException):
                    actor.active_call.result()
        cleanup = actor.lease.process_cleanup if actor.lease is not None else None
        local = actor.binding.transport == "stdio"
        process_started = local and bool(cleanup and cleanup.process_started)
        unverified_local_start = (
            local and actor.context_enter_started and cleanup is None
        )
        cleanup_verified = (
            (
                not unverified_local_start
                and (not process_started or bool(cleanup and cleanup.cleanup_verified))
            )
            if local
            else cleanup_error is None
        )
        now = self._clock()
        if not cleanup_verified:
            status = McpManagedHostStatus(
                management_id=actor.binding.management_id,
                project_id=actor.binding.project_id,
                state="cleanup_required",
                reason="cleanup_unconfirmed",
                binding=actor.binding,
                instance_id=actor.instance_id,
                observed_tool_count=actor.status.observed_tool_count,
                observed_schema_digest=actor.status.observed_schema_digest,
                started_at=actor.status.started_at,
                last_checked_at=actor.status.last_checked_at,
                stopped_at=now,
                last_transition_at=now,
                process_started=process_started,
                cleanup_state="unconfirmed",
                host_lease_active=False,
                error_code="mcp_host_cleanup_unconfirmed",
            )
        elif final in {"failed", "unhealthy"}:
            status = McpManagedHostStatus(
                management_id=actor.binding.management_id,
                project_id=actor.binding.project_id,
                state="unhealthy",
                reason=("contract_drift" if error_code == "mcp_managed_host_contract_drift" else "transport_failed"),
                binding=actor.binding,
                instance_id=actor.instance_id,
                observed_tool_count=actor.status.observed_tool_count,
                observed_schema_digest=actor.status.observed_schema_digest,
                started_at=actor.status.started_at,
                last_checked_at=actor.status.last_checked_at,
                last_transition_at=now,
                process_started=process_started,
                cleanup_state=(
                    "verified" if process_started else "not_applicable"
                ),
                host_lease_active=False,
                error_code=error_code or "mcp_managed_host_failed",
            )
        else:
            status = self._stopped(
                actor.binding.management_id,
                actor.binding.project_id,
                reason="app_shutdown" if final == "shutdown" else "stopped_by_owner",
            )
        actor.status = status
        actor.connection = None
        actor.context = None
        actor.lease = None
        with self._lock:
            self._actors.pop(key, None)
            self._last[key] = status
        actor.closed.set()
        return status

    def _settle_call_failure(
        self,
        actor: _HostActor,
        code: str,
    ) -> NoReturn:
        """Let exactly one closer settle a failed or interrupted call."""

        with self._lock:
            owns_cleanup = not actor.closing
            if owns_cleanup:
                actor.closing = True
        if not owns_cleanup:
            raise McpManagedRuntimeError(
                "mcp_tool_call_interrupted"
            ) from None
        self._stop_after_call(actor)
        raise McpManagedRuntimeError(code) from None

    def call_tool(
        self,
        *,
        management_id: str,
        project_id: str,
        instance_id: str,
        call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        output_schema: Mapping[str, Any] | None,
        deadline_seconds: float,
        cancelled: threading.Event,
    ) -> McpManagedCallProjection:
        key = (management_id, project_id)
        with self._lock:
            actor = self._actors.get(key)
            if (
                actor is None
                or actor.status.state != "ready"
                or actor.instance_id != instance_id
                or actor.lease is None
                or actor.closing
            ):
                raise McpManagedRuntimeError("mcp_tool_host_not_ready")
            if actor.active_call is not None or actor.call_reserved:
                raise McpManagedRuntimeError("mcp_tool_call_in_progress")
            actor.call_reserved = True
        if cancelled.is_set():
            with self._lock:
                actor.call_reserved = False
            raise McpManagedRuntimeError("mcp_tool_cancelled")
        loop = self._ensure_loop()
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._call_actor(
                    actor,
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    output_schema=output_schema,
                    deadline_seconds=deadline_seconds,
                ),
                loop,
            )
        except Exception:
            with self._lock:
                actor.call_reserved = False
            raise
        deadline = time.monotonic() + deadline_seconds
        while True:
            if cancelled.is_set():
                future.cancel()
                self._settle_call_failure(actor, "mcp_tool_cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                self._settle_call_failure(actor, "mcp_tool_deadline_exceeded")
            try:
                projection = future.result(timeout=min(0.05, remaining))
            except FutureTimeoutError:
                continue
            except McpManagedRuntimeError as error:
                self._settle_call_failure(actor, error.code)
            except Exception as error:
                self._settle_call_failure(
                    actor,
                    _error_code(error, "mcp_tool_call_failed"),
                )
            if cancelled.is_set():
                self._settle_call_failure(actor, "mcp_tool_cancelled")
            if actor.closing:
                raise McpManagedRuntimeError(
                    "mcp_tool_call_interrupted"
                ) from None
            return projection

    async def _call_actor(
        self,
        actor: _HostActor,
        *,
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        output_schema: Mapping[str, Any] | None,
        deadline_seconds: float,
    ) -> McpManagedCallProjection:
        current = asyncio.current_task()
        actor.active_call = current
        actor.call_reserved = False
        try:
            async with actor.call_lock:
                if (
                    actor.status.state != "ready"
                    or actor.lease is None
                    or actor.closing
                ):
                    raise McpManagedRuntimeError("mcp_tool_host_not_ready")
                result = await asyncio.wait_for(
                    actor.lease.client.call_tool(
                        tool_name,
                        arguments,
                        read_timeout_seconds=deadline_seconds,
                    ),
                    timeout=deadline_seconds,
                )
                if actor.closing:
                    raise McpManagedRuntimeError("mcp_tool_call_interrupted")
                return _project_result(
                    call_id=call_id,
                    result=result,
                    output_schema=output_schema,
                )
        except asyncio.TimeoutError:
            raise McpManagedRuntimeError("mcp_tool_deadline_exceeded") from None
        except McpManagedRuntimeError:
            raise
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            raise McpManagedRuntimeError(
                _error_code(error, "mcp_tool_call_failed")
            ) from None
        finally:
            actor.active_call = None
            actor.call_reserved = False

    def _stop_after_call(self, actor: _HostActor) -> McpManagedHostStatus:
        loop = self._loop
        if loop is None or loop.is_closed():
            raise McpManagedRuntimeError("mcp_host_cleanup_unconfirmed")
        future = asyncio.run_coroutine_threadsafe(
            self._close_actor(
                actor,
                final="unhealthy",
                error_code="mcp_tool_call_interrupted",
            ),
            loop,
        )
        try:
            status = future.result(timeout=MAX_MCP_MANAGED_CLEANUP_SECONDS + 2.0)
        except Exception:
            future.cancel()
            raise McpManagedRuntimeError("mcp_host_cleanup_unconfirmed") from None
        if status.state == "cleanup_required":
            raise McpManagedRuntimeError("mcp_host_cleanup_unconfirmed")
        return status

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            actors = tuple(self._actors.values())
            loop = self._loop
            thread = self._thread
        if loop is not None and not loop.is_closed():
            futures = [
                asyncio.run_coroutine_threadsafe(
                    self._close_actor(actor, final="shutdown", error_code=None),
                    loop,
                )
                for actor in actors
            ]
            failures = False
            deadline = time.monotonic() + MAX_MCP_MANAGED_CLEANUP_SECONDS + 2.0
            for future in futures:
                try:
                    status = future.result(
                        timeout=max(0.0, deadline - time.monotonic())
                    )
                    failures = failures or status.state == "cleanup_required"
                except Exception:
                    future.cancel()
                    failures = True
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(timeout=3.0)
            if failures:
                raise McpManagedRuntimeError("mcp_host_cleanup_unconfirmed")


__all__ = (
    "MAX_MCP_MANAGED_CLEANUP_SECONDS",
    "McpManagedHostSupervisor",
)
