"""Synthetic-only tests for project-scoped managed MCP execution."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import sqlite3
from types import SimpleNamespace
import threading
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent
from pydantic import SecretStr
import pytest

from prompt_enhancer.application.mcp_guarded_host import (
    McpDiscoveredTool,
    McpRemoteConnectionSpec,
    McpStdioConnectionSpec,
    review_mcp_tool_contracts,
)
from prompt_enhancer.application.mcp_managed_host import (
    McpManagedHostActionReceipt,
    McpManagedHostBinding,
    McpManagedHostCleanupBlock,
    McpManagedHostStatus,
    StartMcpManagedHost,
    StopMcpManagedHost,
    build_mcp_managed_host_start_preview,
    mcp_managed_host_binding_digest,
)
from prompt_enhancer.application.mcp_managed_runtime import (
    MAX_MCP_MANAGED_APPROVAL_SECONDS,
    MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS,
    McpManagedCallProjection,
    McpManagedHostCleanupEvidence,
    McpManagedProjectRuntime,
    McpManagedRuntimeError,
    McpManagedRuntimeService,
    McpManagedToolCallClaim,
    McpManagedToolCallReceipt,
    validate_mcp_tool_arguments,
    validate_mcp_tool_result,
)
from prompt_enhancer.application.mcp_server_management import (
    MCP_MANAGED_SERVER_PATH,
    McpManagedReviewedTool,
    McpManagedToolSnapshot,
)
from prompt_enhancer.infrastructure.mcp_guarded_host import McpSdkClientLease
from prompt_enhancer.infrastructure.mcp_stdio_transport import McpStdioCleanupEvidence
from prompt_enhancer.infrastructure.mcp_managed_host_supervisor import (
    MAX_MCP_MANAGED_CLEANUP_SECONDS,
    McpManagedHostSupervisor,
    _project_result,
)
from prompt_enhancer.infrastructure.sqlite.agent_catalog import (
    AGENT_CATALOG_DATABASE_FILENAME,
    AGENT_CATALOG_SCHEMA_VERSION,
    AgentCatalogSqliteDatabase,
)
from prompt_enhancer.infrastructure.sqlite.mcp_managed_runtime import (
    SqliteMcpManagedRuntimeReceiptRepository,
)
from prompt_enhancer.interfaces.http.mcp_server_management_routes import (
    _runtime_error,
    create_mcp_server_management_router,
)


MANAGEMENT_ID = "a" * 32
PROJECT_ID = "b" * 32
SNAPSHOT_ID = "c" * 32
SESSION_ID = "d" * 32
TURN_ID = "e" * 32
PROTOCOL = "2025-11-25"
NOW = datetime(2026, 8, 30, tzinfo=UTC)


def _discovered() -> tuple[McpDiscoveredTool, ...]:
    return (
        McpDiscoveredTool(
            name="synthetic_echo",
            title="Synthetic echo",
            description="Returns one synthetic value.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string", "maxLength": 32}},
                "required": ["value"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"echoed": {"type": "string"}},
                "required": ["echoed"],
                "additionalProperties": False,
            },
        ),
    )


def _snapshot() -> McpManagedToolSnapshot:
    reviewed, digest = review_mcp_tool_contracts(MANAGEMENT_ID, _discovered())
    return McpManagedToolSnapshot(
        snapshot_id=SNAPSHOT_ID,
        management_id=MANAGEMENT_ID,
        plan_revision="f" * 64,
        source="remote_probe",
        protocol_version=PROTOCOL,
        tool_count=len(reviewed),
        schema_digest=digest,
        reviewed_at=NOW,
        tools=tuple(McpManagedReviewedTool.from_guarded(item) for item in reviewed),
    )


def _binding(snapshot: McpManagedToolSnapshot) -> McpManagedHostBinding:
    return McpManagedHostBinding(
        management_id=MANAGEMENT_ID,
        project_id=PROJECT_ID,
        server_revision=7,
        project_binding_revision=3,
        plan_revision=snapshot.plan_revision,
        option_kind="remote_server",
        transport="streamable-http",
        tool_snapshot_id=snapshot.snapshot_id,
        tool_schema_digest=snapshot.schema_digest,
        reviewed_tool_count=snapshot.tool_count,
        admitted_tool_ids=tuple(item.tool_id for item in snapshot.tools),
        granted_permissions=("network_egress",),
    )


def _connection() -> McpRemoteConnectionSpec:
    return McpRemoteConnectionSpec(
        management_id=MANAGEMENT_ID,
        catalog_id="1" * 32,
        option_id="2" * 32,
        plan_revision="f" * 64,
        transport="streamable-http",
        endpoint_host="synthetic.example",
        endpoint=SecretStr("https://synthetic.example/mcp"),
        headers=(),
    )


def _local_binding(snapshot: McpManagedToolSnapshot) -> McpManagedHostBinding:
    return _binding(snapshot).model_copy(
        update={
            "option_kind": "local_package",
            "transport": "stdio",
            "granted_permissions": ("process_spawn",),
        }
    )


def _local_connection() -> McpStdioConnectionSpec:
    return McpStdioConnectionSpec(
        management_id=MANAGEMENT_ID,
        executable="synthetic-mcp-server",
        arguments=("--synthetic",),
        environment={},
    )


class _Client:
    protocol_version = PROTOCOL
    server_capabilities = SimpleNamespace(tools=object())

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self, *, cursor=None, cache_mode="use"):
        assert cursor is None
        assert cache_mode == "bypass"
        tools = tuple(
            SimpleNamespace(
                name=item.name,
                title=item.title,
                description=item.description,
                input_schema=item.input_schema,
                output_schema=item.output_schema,
            )
            for item in _discovered()
        )
        return SimpleNamespace(result_type="complete", tools=tools, next_cursor=None)

    async def call_tool(
        self,
        name,
        arguments,
        read_timeout_seconds=None,
    ):
        assert read_timeout_seconds == 2.0
        self.calls.append((name, arguments))
        return CallToolResult(
            content=[TextContent(text="synthetic result")],
            structuredContent={"echoed": arguments["value"]},
        )


class _Factory:
    def __init__(self, client: _Client) -> None:
        self.client = client
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def connect(self, connection, *, read_timeout_seconds, client_info):
        del connection, read_timeout_seconds, client_info
        self.opened += 1
        try:
            yield McpSdkClientLease(
                client=self.client,
                transport="streamable-http",
                process_cleanup=None,
            )
        finally:
            self.closed += 1


class _SlowCloseFactory:
    def __init__(self) -> None:
        self.client = _Client()
        self.close_started = threading.Event()
        self.close_cancelled = threading.Event()

    @asynccontextmanager
    async def connect(self, connection, *, read_timeout_seconds, client_info):
        del connection, read_timeout_seconds, client_info
        try:
            yield McpSdkClientLease(
                client=self.client,
                transport="streamable-http",
                process_cleanup=None,
            )
        finally:
            self.close_started.set()
            try:
                await asyncio.sleep(60.0)
            except asyncio.CancelledError:
                self.close_cancelled.set()
                raise


class _SlowEnterFactory:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.cancelled = threading.Event()

    @asynccontextmanager
    async def connect(self, connection, *, read_timeout_seconds, client_info):
        del connection, read_timeout_seconds, client_info
        self.entered.set()
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield  # pragma: no cover


class _BlockingClient(_Client):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        del name, arguments, read_timeout_seconds
        self.entered.set()
        await asyncio.sleep(60.0)


class _LateCancellationClient(_Client):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.cancel_seen = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        del name, arguments, read_timeout_seconds
        self.entered.set()
        while not self.release.is_set():
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                self.cancel_seen.set()
        self.returned.set()
        return CallToolResult(
            content=[TextContent(text="synthetic late result")],
            structuredContent={"echoed": "synthetic late result"},
        )


class _UnsupportedResultClient(_Client):
    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        del name, arguments, read_timeout_seconds
        return SimpleNamespace(
            result_type="complete",
            content=(SimpleNamespace(type="image"),),
            structured_content=None,
            is_error=False,
        )


class _UntrustedCodedError(RuntimeError):
    code = "example_private_failure_canary"


class _UntrustedCodedClient(_Client):
    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        del name, arguments, read_timeout_seconds
        raise _UntrustedCodedError("example-private-diagnostic-canary")


class _LocalFactory:
    def __init__(self, *, process_started: bool, client: _Client | None = None) -> None:
        self.client = client or _Client()
        self.cleanup = McpStdioCleanupEvidence(process_started=process_started)
        self.closed = 0

    @asynccontextmanager
    async def connect(self, connection, *, read_timeout_seconds, client_info):
        del connection, read_timeout_seconds, client_info
        try:
            yield McpSdkClientLease(
                client=self.client,
                transport="stdio",
                process_cleanup=self.cleanup,
            )
        finally:
            self.closed += 1
            if self.cleanup.process_started:
                self.cleanup.root_exited = True
                self.cleanup.tree_exited = True
                self.cleanup.streams_closed = True
                self.cleanup.cleanup_verified = True


class _BlockingListClient(_Client):
    def __init__(self) -> None:
        super().__init__()
        self.list_entered = threading.Event()
        self.list_cancelled = threading.Event()

    async def list_tools(self, *, cursor=None, cache_mode="use"):
        del cursor, cache_mode
        self.list_entered.set()
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            self.list_cancelled.set()
            raise


class _RuntimeRouteStub:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self._status = McpManagedHostStatus(
            management_id=MANAGEMENT_ID,
            project_id=PROJECT_ID,
            state="not_started",
            reason="never_started",
            last_transition_at=NOW,
            process_started=False,
            cleanup_state="not_applicable",
            host_lease_active=False,
        )

    def status(self, management_id, project_id):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        return self._status

    def start(self, management_id, project_id, payload):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        del payload
        self.starts += 1
        snapshot = _snapshot()
        self._status = McpManagedHostStatus(
            management_id=MANAGEMENT_ID,
            project_id=PROJECT_ID,
            state="ready",
            reason="healthy",
            binding=_binding(snapshot),
            instance_id="6" * 32,
            observed_tool_count=snapshot.tool_count,
            observed_schema_digest=snapshot.schema_digest,
            started_at=NOW,
            last_checked_at=NOW,
            last_transition_at=NOW,
            process_started=False,
            cleanup_state="not_applicable",
            host_lease_active=True,
            tool_calls_available=True,
            tool_routing_state="project_scoped_fresh_approval",
        )
        return self._status

    def stop(self, management_id, project_id, payload):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        del payload
        self.stops += 1
        self._status = self._status.model_copy(
            update={
                "state": "not_started",
                "reason": "stopped_by_owner",
                "binding": None,
                "instance_id": None,
                "observed_tool_count": None,
                "observed_schema_digest": None,
                "started_at": None,
                "last_checked_at": None,
                "stopped_at": NOW,
                "process_started": False,
                "cleanup_state": "verified",
                "host_lease_active": False,
                "tool_calls_available": False,
                "tool_routing_state": "inactive",
            }
        )
        return self._status

    def project_tools(self, project_id):
        assert project_id == PROJECT_ID
        return McpManagedProjectRuntime(project_id=PROJECT_ID)


class _RuntimeManagementStub:
    def __init__(self) -> None:
        self.snapshot = _snapshot()
        self.binding = _binding(self.snapshot)

    def get(self, management_id):
        assert management_id == MANAGEMENT_ID
        return SimpleNamespace(server_title="Synthetic MCP")

    def get_tool_snapshot(self, management_id):
        assert management_id == MANAGEMENT_ID
        return self.snapshot

    def resolve_host_start_preview(
        self,
        management_id,
        project_id,
        *,
        expected_server_revision,
        expected_project_binding_revision,
        expected_tool_snapshot_id,
    ):
        binding = self.resolve_host_binding(
            management_id,
            project_id,
            expected_server_revision=expected_server_revision,
            expected_project_binding_revision=expected_project_binding_revision,
            expected_tool_snapshot_id=expected_tool_snapshot_id,
        )
        return build_mcp_managed_host_start_preview(binding)

    def resolve_transient_host_connection(self, management_id, *, expected_revision):
        assert management_id == MANAGEMENT_ID
        assert expected_revision == self.binding.server_revision
        return _connection()

    def resolve_host_binding(
        self,
        management_id,
        project_id,
        *,
        expected_server_revision,
        expected_project_binding_revision,
        expected_tool_snapshot_id,
    ):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        if (
            self.binding.server_revision != expected_server_revision
            or self.binding.project_binding_revision
            != expected_project_binding_revision
            or self.binding.tool_snapshot_id != expected_tool_snapshot_id
        ):
            raise McpManagedRuntimeError("mcp_managed_revision_conflict")
        return self.binding


class _RuntimeSupervisorStub:
    def __init__(self, management: _RuntimeManagementStub) -> None:
        snapshot = management.snapshot
        self.ready = McpManagedHostStatus(
            management_id=MANAGEMENT_ID,
            project_id=PROJECT_ID,
            state="ready",
            reason="healthy",
            binding=management.binding,
            instance_id="6" * 32,
            observed_tool_count=snapshot.tool_count,
            observed_schema_digest=snapshot.schema_digest,
            started_at=NOW,
            last_checked_at=NOW,
            last_transition_at=NOW,
            process_started=False,
            cleanup_state="not_applicable",
            host_lease_active=True,
            tool_calls_available=True,
            tool_routing_state="project_scoped_fresh_approval",
        )
        self.calls: list[dict[str, object]] = []

    def statuses(self):
        return (self.ready,)

    def status(self, management_id, project_id):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        return self.ready

    def call_tool(self, **values):
        self.calls.append(values)
        text = "synthetic managed result"
        return McpManagedCallProjection(
            call_id=str(values["call_id"]),
            outcome="succeeded",
            text=text,
            result_bytes=len(text.encode("utf-8")),
            result_digest="7" * 64,
            content_mode="text",
            cleanup_verified=True,
        )

    def shutdown(self):
        return None


class _CleanupFailingSupervisor(_RuntimeSupervisorStub):
    def stop(self, management_id, project_id, command):
        assert (management_id, project_id) == (MANAGEMENT_ID, PROJECT_ID)
        assert command.expected_instance_id == self.ready.instance_id
        self.ready = self.ready.model_copy(
            update={
                "state": "cleanup_required",
                "reason": "cleanup_unconfirmed",
                "stopped_at": NOW,
                "last_transition_at": NOW,
                "cleanup_state": "unconfirmed",
                "host_lease_active": False,
                "error_code": "mcp_host_cleanup_unconfirmed",
                "tool_calls_available": False,
                "tool_routing_state": "inactive",
            }
        )
        return self.ready


class _ReceiptStub:
    def __init__(self) -> None:
        self.claims: list[McpManagedToolCallClaim] = []
        self.receipts: list[McpManagedToolCallReceipt] = []
        self.host_actions: list[McpManagedHostActionReceipt] = []
        self.cleanup_evidence: list[McpManagedHostCleanupEvidence] = []
        self.restart_reconciliations: list[tuple[str, datetime]] = []

    def get_tool_call_claim(self, call_id):
        return next(
            (claim for claim in self.claims if claim.call_id == call_id),
            None,
        )

    def claim_tool_call(self, claim):
        if self.get_tool_call_receipt(claim.call_id) is not None:
            return False
        existing = self.get_tool_call_claim(claim.call_id)
        if existing is not None and existing != claim:
            raise McpManagedRuntimeError("mcp_tool_claim_conflict")
        if existing is not None:
            return False
        self.claims.append(claim)
        return True

    def get_tool_call_receipt(self, call_id):
        return next(
            (receipt for receipt in self.receipts if receipt.call_id == call_id),
            None,
        )

    def record_tool_call_receipt(self, receipt):
        claim = self.get_tool_call_claim(receipt.call_id)
        if claim is None:
            raise McpManagedRuntimeError("mcp_tool_claim_missing")
        existing = self.get_tool_call_receipt(receipt.call_id)
        if existing is not None and existing != receipt:
            raise McpManagedRuntimeError("mcp_tool_receipt_conflict")
        if existing is None:
            self.receipts.append(receipt)

    def reconcile_interrupted_tool_calls(
        self,
        *,
        current_app_run_digest,
        interrupted_at,
    ):
        self.restart_reconciliations.append(
            (current_app_run_digest, interrupted_at)
        )
        return ()

    def get_host_action_receipt(self, request_id):
        return next(
            (receipt for receipt in self.host_actions if receipt.request_id == request_id),
            None,
        )

    def record_host_action_receipt(self, receipt):
        existing = self.get_host_action_receipt(receipt.request_id)
        if existing is not None and existing != receipt:
            raise McpManagedRuntimeError("mcp_host_action_receipt_conflict")
        if existing is None:
            self.host_actions.append(receipt)

    def get_active_cleanup_evidence(self, management_id, project_id):
        return next(
            (
                evidence
                for evidence in self.cleanup_evidence
                if evidence.block.management_id == management_id
                and evidence.block.project_id == project_id
                and evidence.block.state == "active"
            ),
            None,
        )

    def record_cleanup_evidence(self, evidence):
        existing = next(
            (
                item
                for item in self.cleanup_evidence
                if item.block.block_id == evidence.block.block_id
            ),
            None,
        )
        if existing is not None and existing != evidence:
            raise McpManagedRuntimeError("mcp_host_cleanup_evidence_conflict")
        if existing is None:
            self.cleanup_evidence.append(evidence)


def test_supervisor_starts_exact_host_calls_once_and_stops_cleanly() -> None:
    snapshot = _snapshot()
    client = _Client()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        assert ready.state == "ready"
        assert ready.host_lease_active is True
        assert ready.process_started is False
        assert factory.opened == 1

        result = supervisor.call_tool(
            management_id=MANAGEMENT_ID,
            project_id=PROJECT_ID,
            instance_id=ready.instance_id or "",
            call_id="3" * 32,
            tool_name="synthetic_echo",
            arguments={"value": "hello"},
            output_schema=snapshot.tools[0].output_schema,
            deadline_seconds=2.0,
            cancelled=threading.Event(),
        )
        assert result.outcome == "succeeded"
        assert result.content_mode == "text_and_structured_json"
        assert "synthetic result" in result.text
        assert client.calls == [("synthetic_echo", {"value": "hello"})]

        stopped = supervisor.stop(
            MANAGEMENT_ID,
            PROJECT_ID,
            StopMcpManagedHost(
                request_id="4" * 32,
                expected_instance_id=ready.instance_id,
                deadline_seconds=2.0,
            ),
        )
        assert stopped.state == "not_started"
        assert stopped.host_lease_active is False
        assert factory.closed == 1
    finally:
        supervisor.shutdown()


def test_cross_project_instance_substitution_cannot_stop_or_call_another_host() -> None:
    snapshot = _snapshot()
    other_project_id = "0" * 32
    client = _Client()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        first = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        second = supervisor.start(
            _binding(snapshot).model_copy(
                update={"project_id": other_project_id}
            ),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )

        with pytest.raises(McpManagedRuntimeError) as crossed_stop:
            supervisor.stop(
                MANAGEMENT_ID,
                other_project_id,
                StopMcpManagedHost(
                    request_id="0" * 32,
                    expected_instance_id=first.instance_id,
                    deadline_seconds=2.0,
                ),
            )
        assert crossed_stop.value.code == "mcp_managed_host_instance_conflict"

        with pytest.raises(McpManagedRuntimeError) as crossed_call:
            supervisor.call_tool(
                management_id=MANAGEMENT_ID,
                project_id=other_project_id,
                instance_id=first.instance_id or "",
                call_id="1" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "synthetic"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=2.0,
                cancelled=threading.Event(),
            )
        assert crossed_call.value.code == "mcp_tool_host_not_ready"
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).instance_id == first.instance_id
        assert supervisor.status(MANAGEMENT_ID, other_project_id).instance_id == second.instance_id

        result = supervisor.call_tool(
            management_id=MANAGEMENT_ID,
            project_id=other_project_id,
            instance_id=second.instance_id or "",
            call_id="2" * 32,
            tool_name="synthetic_echo",
            arguments={"value": "other"},
            output_schema=snapshot.tools[0].output_schema,
            deadline_seconds=2.0,
            cancelled=threading.Event(),
        )
        assert result.outcome == "succeeded"
        assert len(supervisor.statuses()) == 2
    finally:
        supervisor.shutdown()


def test_owner_stop_during_active_call_wins_once_without_late_revival() -> None:
    snapshot = _snapshot()
    client = _BlockingClient()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                supervisor.call_tool,
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="5" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "stop wins"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=5.0,
                cancelled=threading.Event(),
            )
            assert client.entered.wait(1.0)
            stopped = supervisor.stop(
                MANAGEMENT_ID,
                PROJECT_ID,
                StopMcpManagedHost(
                    request_id="6" * 32,
                    expected_instance_id=ready.instance_id,
                    deadline_seconds=2.0,
                ),
            )
            with pytest.raises(McpManagedRuntimeError) as interrupted:
                pending.result(timeout=3.0)
        assert interrupted.value.code == "mcp_tool_call_interrupted"
        assert stopped.state == "not_started"
        assert factory.closed == 1
        time.sleep(0.05)
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "not_started"
    finally:
        supervisor.shutdown()


def test_untrusted_exception_code_and_diagnostic_are_never_projected_or_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    snapshot = _snapshot()
    factory = _Factory(_UntrustedCodedClient())
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with pytest.raises(McpManagedRuntimeError) as failed:
            supervisor.call_tool(
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="7" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "synthetic"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=2.0,
                cancelled=threading.Event(),
            )
        assert failed.value.code == "mcp_tool_call_failed"
        rendered = failed.value.code + supervisor.status(
            MANAGEMENT_ID,
            PROJECT_ID,
        ).model_dump_json()
        assert "example_private_failure_canary" not in rendered
        assert "example-private-diagnostic-canary" not in rendered
        assert "example_private_failure_canary" not in caplog.text
        assert "example-private-diagnostic-canary" not in caplog.text
    finally:
        supervisor.shutdown()


def test_remote_stop_deadline_settles_cleanup_unconfirmed_without_hanging() -> None:
    snapshot = _snapshot()
    factory = _SlowCloseFactory()
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        started = time.monotonic()
        status = supervisor.stop(
            MANAGEMENT_ID,
            PROJECT_ID,
            StopMcpManagedHost(
                request_id="d" * 32,
                expected_instance_id=ready.instance_id,
                deadline_seconds=0.1,
            ),
        )
        elapsed = time.monotonic() - started

        assert elapsed < 1.0
        assert status.state == "cleanup_required"
        assert status.host_lease_active is False
        assert status.error_code == "mcp_host_cleanup_unconfirmed"
        assert factory.close_started.wait(1.0)
        assert factory.close_cancelled.wait(1.0)
    finally:
        supervisor.shutdown()


def test_managed_host_cleanup_budget_is_finite_for_stop_call_and_shutdown() -> None:
    assert 0.5 <= MAX_MCP_MANAGED_CLEANUP_SECONDS <= 5.0


def test_remote_start_uses_one_total_deadline_and_cannot_become_ready_late() -> None:
    snapshot = _snapshot()
    factory = _SlowEnterFactory()
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        started = time.monotonic()
        with pytest.raises(McpManagedRuntimeError) as caught:
            supervisor.start(
                _binding(snapshot),
                _connection(),
                snapshot,
                deadline_seconds=0.1,
            )
        elapsed = time.monotonic() - started

        assert caught.value.code == "mcp_managed_host_start_timeout"
        assert elapsed < 1.0
        assert factory.entered.wait(1.0)
        assert factory.cancelled.wait(1.0)
        status = supervisor.status(MANAGEMENT_ID, PROJECT_ID)
        assert status.state in {"unhealthy", "cleanup_required"}
        assert status.host_lease_active is False
        time.sleep(0.05)
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state != "ready"
    finally:
        supervisor.shutdown()


def test_supervisor_rejects_contract_drift_and_closes_connection() -> None:
    snapshot = _snapshot().model_copy(update={"schema_digest": "0" * 64})
    binding = _binding(snapshot)
    factory = _Factory(_Client())
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        with pytest.raises(McpManagedRuntimeError) as caught:
            supervisor.start(
                binding,
                _connection(),
                snapshot,
                deadline_seconds=2.0,
            )
        assert caught.value.code == "mcp_managed_host_contract_drift"
        assert factory.opened == factory.closed == 1
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "unhealthy"
    finally:
        supervisor.shutdown()


def test_supervisor_is_inert_until_an_explicit_start() -> None:
    before = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name == "prompt-enhancer-mcp-hosts"
    }
    supervisor = McpManagedHostSupervisor(_Factory(_Client()))  # type: ignore[arg-type]
    try:
        assert supervisor.statuses() == ()
        after = {
            thread.ident
            for thread in threading.enumerate()
            if thread.name == "prompt-enhancer-mcp-hosts"
        }
        assert after == before
    finally:
        supervisor.shutdown()


def test_cancelled_call_closes_host_before_returning() -> None:
    snapshot = _snapshot()
    client = _BlockingClient()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    cancelled = threading.Event()
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                supervisor.call_tool,
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="7" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "cancel me"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=5.0,
                cancelled=cancelled,
            )
            assert client.entered.wait(1.0)
            with pytest.raises(McpManagedRuntimeError) as concurrent:
                supervisor.call_tool(
                    management_id=MANAGEMENT_ID,
                    project_id=PROJECT_ID,
                    instance_id=ready.instance_id or "",
                    call_id="8" * 32,
                    tool_name="synthetic_echo",
                    arguments={"value": "second"},
                    output_schema=snapshot.tools[0].output_schema,
                    deadline_seconds=2.0,
                    cancelled=threading.Event(),
                )
            assert concurrent.value.code == "mcp_tool_call_in_progress"
            cancelled.set()
            with pytest.raises(McpManagedRuntimeError) as caught:
                pending.result(timeout=3.0)
        assert caught.value.code == "mcp_tool_cancelled"
        assert factory.closed == 1
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "unhealthy"
    finally:
        supervisor.shutdown()


def test_late_result_after_cancel_cannot_revive_or_complete_the_call() -> None:
    snapshot = _snapshot()
    client = _LateCancellationClient()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    cancelled = threading.Event()
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                supervisor.call_tool,
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="a" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "synthetic"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=5.0,
                cancelled=cancelled,
            )
            assert client.entered.wait(1.0)
            cancelled.set()
            assert client.cancel_seen.wait(1.0)
            client.release.set()
            with pytest.raises(McpManagedRuntimeError) as caught:
                pending.result(timeout=3.0)
        assert caught.value.code == "mcp_tool_cancelled"
        assert client.returned.wait(1.0)
        assert factory.closed == 1
        status = supervisor.status(MANAGEMENT_ID, PROJECT_ID)
        assert status.state == "unhealthy"
        assert status.host_lease_active is False
        with pytest.raises(McpManagedRuntimeError) as refused:
            supervisor.call_tool(
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="b" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "second"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=1.0,
                cancelled=threading.Event(),
            )
        assert refused.value.code == "mcp_tool_host_not_ready"
    finally:
        client.release.set()
        supervisor.shutdown()


def test_timed_out_call_closes_host_before_returning() -> None:
    snapshot = _snapshot()
    client = _BlockingClient()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with pytest.raises(McpManagedRuntimeError) as caught:
            supervisor.call_tool(
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="c" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "timeout"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=0.1,
                cancelled=threading.Event(),
            )
        assert caught.value.code == "mcp_tool_deadline_exceeded"
        assert factory.closed == 1
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "unhealthy"
    finally:
        supervisor.shutdown()


def test_contract_violating_result_revokes_and_closes_host() -> None:
    snapshot = _snapshot()
    factory = _Factory(_UnsupportedResultClient())
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _binding(snapshot),
            _connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        with pytest.raises(McpManagedRuntimeError) as caught:
            supervisor.call_tool(
                management_id=MANAGEMENT_ID,
                project_id=PROJECT_ID,
                instance_id=ready.instance_id or "",
                call_id="9" * 32,
                tool_name="synthetic_echo",
                arguments={"value": "synthetic"},
                output_schema=snapshot.tools[0].output_schema,
                deadline_seconds=2.0,
                cancelled=threading.Event(),
            )
        assert caught.value.code == "mcp_tool_result_content_unsupported"
        assert factory.closed == 1
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "unhealthy"
    finally:
        supervisor.shutdown()


def test_local_start_without_process_evidence_does_not_invent_cleanup_work() -> None:
    snapshot = _snapshot()
    factory = _LocalFactory(process_started=False)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        with pytest.raises(McpManagedRuntimeError) as caught:
            supervisor.start(
                _local_binding(snapshot),
                _local_connection(),
                snapshot,
                deadline_seconds=2.0,
            )
        assert caught.value.code == "mcp_managed_host_process_evidence_missing"
        status = supervisor.status(MANAGEMENT_ID, PROJECT_ID)
        assert status.state == "unhealthy"
        assert status.process_started is False
        assert status.cleanup_state == "not_applicable"
        assert factory.closed == 1
    finally:
        supervisor.shutdown()


def test_local_ready_stop_requires_verified_owned_tree_cleanup() -> None:
    snapshot = _snapshot()
    factory = _LocalFactory(process_started=True)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    try:
        ready = supervisor.start(
            _local_binding(snapshot),
            _local_connection(),
            snapshot,
            deadline_seconds=2.0,
        )
        assert ready.state == "ready"
        assert ready.process_started is True
        assert ready.cleanup_state == "pending"

        stopped = supervisor.stop(
            MANAGEMENT_ID,
            PROJECT_ID,
            StopMcpManagedHost(
                request_id="a" * 32,
                expected_instance_id=ready.instance_id,
                deadline_seconds=2.0,
            ),
        )
        assert stopped.state == "not_started"
        assert factory.closed == 1
        assert factory.cleanup.root_exited is True
        assert factory.cleanup.tree_exited is True
        assert factory.cleanup.streams_closed is True
        assert factory.cleanup.cleanup_verified is True
    finally:
        supervisor.shutdown()


def test_stop_during_local_tool_enumeration_cancels_start_and_cannot_revive() -> None:
    snapshot = _snapshot()
    client = _BlockingListClient()
    factory = _LocalFactory(process_started=True, client=client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    start_outcome: list[str] = []

    def start() -> None:
        try:
            supervisor.start(
                _local_binding(snapshot),
                _local_connection(),
                snapshot,
                deadline_seconds=5.0,
            )
            start_outcome.append("ready")
        except McpManagedRuntimeError as error:
            start_outcome.append(error.code)

    thread = threading.Thread(target=start, daemon=True)
    try:
        thread.start()
        assert client.list_entered.wait(2.0)
        starting = supervisor.status(MANAGEMENT_ID, PROJECT_ID)
        assert starting.state == "starting"
        assert starting.process_started is True

        stopped = supervisor.stop(
            MANAGEMENT_ID,
            PROJECT_ID,
            StopMcpManagedHost(
                request_id="b" * 32,
                expected_instance_id=starting.instance_id,
                deadline_seconds=2.0,
            ),
        )
        thread.join(timeout=2.0)

        assert not thread.is_alive()
        assert start_outcome == ["mcp_managed_host_start_cancelled"]
        assert client.list_cancelled.is_set()
        assert stopped.state == "not_started"
        assert factory.closed == 1
        assert factory.cleanup.cleanup_verified is True
        time.sleep(0.05)
        assert supervisor.status(MANAGEMENT_ID, PROJECT_ID).state == "not_started"
    finally:
        supervisor.shutdown()


def test_arguments_are_bounded_detached_and_exact_schema_validated() -> None:
    source = {"value": "synthetic"}
    detached, digest, byte_count = validate_mcp_tool_arguments(
        source,
        _discovered()[0].input_schema,
    )
    source["value"] = "changed"
    assert detached == {"value": "synthetic"}
    assert len(digest) == 64
    assert byte_count > 2

    with pytest.raises(McpManagedRuntimeError) as caught:
        validate_mcp_tool_arguments(
            {"value": 9},
            _discovered()[0].input_schema,
        )
    assert caught.value.code == "mcp_tool_arguments_schema_mismatch"


def test_structured_results_are_detached_and_fail_closed_on_depth_size_and_schema() -> None:
    source = {"echoed": "synthetic"}
    detached, encoded = validate_mcp_tool_result(
        source,
        _discovered()[0].output_schema,
    )
    source["echoed"] = "changed"
    assert detached == {"echoed": "synthetic"}
    assert encoded == b'{"echoed":"synthetic"}'

    deep: dict[str, object] = {}
    cursor = deep
    for _ in range(40):
        child: dict[str, object] = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(McpManagedRuntimeError) as captured:
        validate_mcp_tool_result(deep, None)
    assert captured.value.code == "mcp_tool_result_too_complex"

    with pytest.raises(McpManagedRuntimeError) as captured:
        validate_mcp_tool_result({"echoed": "x" * 50_000}, None)
    assert captured.value.code == "mcp_tool_result_too_large"

    with pytest.raises(McpManagedRuntimeError) as captured:
        validate_mcp_tool_result({"echoed": 7}, _discovered()[0].output_schema)
    assert captured.value.code == "mcp_tool_result_schema_mismatch"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            SimpleNamespace(
                result_type="complete",
                content=tuple(
                    SimpleNamespace(type="text", text="")
                    for _ in range(MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS + 1)
                ),
                structured_content=None,
                is_error=False,
            ),
            "mcp_tool_result_too_complex",
        ),
        (
            SimpleNamespace(
                result_type="complete",
                content=(SimpleNamespace(type="text", text="x" * 50_000),),
                structured_content=None,
                is_error=False,
            ),
            "mcp_tool_result_too_large",
        ),
        (
            SimpleNamespace(
                result_type="complete",
                content=(),
                structured_content=None,
                is_error="false",
            ),
            "mcp_tool_result_malformed",
        ),
    ],
)
def test_result_projection_rejects_content_floods_and_ambiguous_error_truth(
    result: object,
    expected: str,
) -> None:
    with pytest.raises(McpManagedRuntimeError) as captured:
        _project_result(call_id="1" * 32, result=result, output_schema=None)
    assert captured.value.code == expected


def test_runtime_restart_reconciliation_is_explicit_and_run_scoped() -> None:
    management = _RuntimeManagementStub()
    receipts = _ReceiptStub()
    run_digest = "7" * 64
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        _RuntimeSupervisorStub(management),  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
        app_run_digest=run_digest,
    )

    assert runtime.reconcile_after_restart() == ()
    assert receipts.restart_reconciliations == [(run_digest, NOW)]


def test_runtime_revalidates_approval_boundary_and_records_content_free_receipt() -> None:
    management = _RuntimeManagementStub()
    supervisor = _RuntimeSupervisorStub(management)
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
    )
    tool = management.snapshot.tools[0]
    schemas = runtime.model_tool_schemas(PROJECT_ID)
    assert [item["function"]["name"] for item in schemas] == [tool.model_alias]
    prepared = runtime.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=tool.model_alias,
        arguments={"value": "hello"},
        deadline_seconds=2.0,
    )
    assert "Approval: one call only; never remembered" in prepared.preview
    projection = runtime.settle_tool_call(
        prepared,
        approval_state="approved",
        cancelled=threading.Event(),
    )
    assert projection.outcome == "succeeded"
    assert len(supervisor.calls) == 1
    receipt = receipts.receipts[0]
    assert receipt.outcome == "succeeded"
    assert receipt.argument_digest == prepared.argument_digest
    assert receipt.result_digest == projection.result_digest
    assert receipt.arguments_persisted is False
    assert receipt.result_persisted is False
    assert receipt.reusable_approval_persisted is False
    assert len(receipts.claims) == 1
    assert receipts.claims[0].approval_digest != prepared.approval_id
    assert prepared.approval_id not in receipts.claims[0].model_dump_json()


def test_one_prepared_approval_can_dispatch_only_once_even_concurrently() -> None:
    management = _RuntimeManagementStub()

    class BlockingSupervisor(_RuntimeSupervisorStub):
        def __init__(self, managed):
            super().__init__(managed)
            self.entered = threading.Event()
            self.release = threading.Event()

        def call_tool(self, **values):
            self.calls.append(values)
            self.entered.set()
            assert self.release.wait(2.0)
            text = "synthetic managed result"
            return McpManagedCallProjection(
                call_id=values["call_id"],
                outcome="succeeded",
                text=text,
                result_bytes=len(text.encode("utf-8")),
                result_digest="7" * 64,
                content_mode="text",
                cleanup_verified=True,
            )

    supervisor = BlockingSupervisor(management)
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
    )
    prepared = runtime.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=management.snapshot.tools[0].model_alias,
        arguments={"value": "synthetic"},
        deadline_seconds=2.0,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(
            runtime.settle_tool_call,
            prepared,
            approval_state="approved",
            cancelled=threading.Event(),
        )
        assert supervisor.entered.wait(1.0)
        with pytest.raises(McpManagedRuntimeError) as replayed:
            runtime.settle_tool_call(
                prepared,
                approval_state="approved",
                cancelled=threading.Event(),
            )
        assert replayed.value.code == "mcp_tool_approval_replayed"
        supervisor.release.set()
        assert first.result(timeout=2.0).outcome == "succeeded"
    assert len(supervisor.calls) == 1
    assert len(receipts.claims) == 1
    assert len(receipts.receipts) == 1


def test_prepared_call_is_bound_to_its_originating_runtime_and_exact_scope() -> None:
    management = _RuntimeManagementStub()
    originating_supervisor = _RuntimeSupervisorStub(management)
    foreign_supervisor = _RuntimeSupervisorStub(management)
    receipts = _ReceiptStub()
    originating = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        originating_supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
        app_run_digest="8" * 64,
    )
    foreign = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        foreign_supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
        app_run_digest="9" * 64,
    )
    prepared = originating.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=management.snapshot.tools[0].model_alias,
        arguments={"value": "synthetic"},
        deadline_seconds=2.0,
    )

    with pytest.raises(McpManagedRuntimeError) as crossed_runtime:
        foreign.settle_tool_call(
            prepared,
            approval_state="approved",
            cancelled=threading.Event(),
        )
    assert crossed_runtime.value.code == "mcp_tool_call_scope_conflict"
    assert foreign_supervisor.calls == []
    assert receipts.claims == []

    tampered = replace(prepared, session_id="0" * 32)
    with pytest.raises(McpManagedRuntimeError) as crossed_chat:
        originating.settle_tool_call(
            tampered,
            approval_state="approved",
            cancelled=threading.Event(),
        )
    assert crossed_chat.value.code == "mcp_tool_call_scope_conflict"
    assert originating_supervisor.calls == []
    assert receipts.claims == []

    projection = originating.settle_tool_call(
        prepared,
        approval_state="approved",
        cancelled=threading.Event(),
    )
    assert projection.outcome == "succeeded"
    assert len(originating_supervisor.calls) == 1
    assert len(receipts.claims) == 1


def test_prepared_argument_mutation_cannot_spend_approval_or_reach_host() -> None:
    management = _RuntimeManagementStub()
    supervisor = _RuntimeSupervisorStub(management)
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
    )
    prepared = runtime.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=management.snapshot.tools[0].model_alias,
        arguments={"value": "before"},
        deadline_seconds=2.0,
    )
    prepared.arguments["value"] = "after"

    with pytest.raises(McpManagedRuntimeError) as changed:
        runtime.settle_tool_call(
            prepared,
            approval_state="approved",
            cancelled=threading.Event(),
        )
    assert changed.value.code == "mcp_tool_call_scope_conflict"
    assert supervisor.calls == []
    assert receipts.claims == []


def test_expired_prepared_approval_is_claimed_once_but_never_dispatched() -> None:
    management = _RuntimeManagementStub()
    supervisor = _RuntimeSupervisorStub(management)
    receipts = _ReceiptStub()
    moments = iter(
        (
            NOW,
            NOW + timedelta(seconds=MAX_MCP_MANAGED_APPROVAL_SECONDS + 1),
        )
    )
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: next(moments),
    )
    prepared = runtime.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=management.snapshot.tools[0].model_alias,
        arguments={"value": "synthetic"},
        deadline_seconds=2.0,
    )
    projection = runtime.settle_tool_call(
        prepared,
        approval_state="approved",
        cancelled=threading.Event(),
    )
    assert projection.outcome == "timed_out"
    assert projection.error_code == "mcp_tool_approval_timed_out"
    assert supervisor.calls == []
    assert receipts.claims[0].approval_state == "timed_out"
    assert receipts.receipts[0].outcome == "timed_out"


def test_runtime_refuses_stale_post_approval_binding_without_invoking_tool() -> None:
    management = _RuntimeManagementStub()
    supervisor = _RuntimeSupervisorStub(management)
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
    )
    prepared = runtime.prepare_tool_call(
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        model_alias=management.snapshot.tools[0].model_alias,
        arguments={"value": "hello"},
        deadline_seconds=2.0,
    )
    management.binding = management.binding.model_copy(
        update={"server_revision": management.binding.server_revision + 1}
    )
    projection = runtime.settle_tool_call(
        prepared,
        approval_state="approved",
        cancelled=threading.Event(),
    )
    assert projection.outcome == "failed"
    assert projection.error_code == "mcp_managed_revision_conflict"
    assert supervisor.calls == []
    assert receipts.receipts[0].outcome == "failed"


def test_runtime_does_not_advertise_tools_from_a_stale_ready_host() -> None:
    management = _RuntimeManagementStub()
    supervisor = _RuntimeSupervisorStub(management)
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,  # type: ignore[arg-type]
        _ReceiptStub(),
        clock=lambda: NOW,
    )
    management.binding = management.binding.model_copy(
        update={"server_revision": management.binding.server_revision + 1}
    )

    projection = runtime.project_tools(PROJECT_ID)

    assert projection.ready_host_count == 0
    assert projection.ready_tool_count == 0
    assert projection.tools == ()
    assert runtime.model_tool_schemas(PROJECT_ID) == ()


def test_owner_start_and_stop_write_content_free_non_replaying_action_receipts() -> None:
    management = _RuntimeManagementStub()
    client = _Client()
    factory = _Factory(client)
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,
        receipts,
        clock=lambda: NOW,
        app_run_digest="8" * 64,
    )
    preview = build_mcp_managed_host_start_preview(management.binding)
    start = StartMcpManagedHost(
        request_id="1" * 32,
        expected_server_revision=management.binding.server_revision,
        expected_project_binding_revision=management.binding.project_binding_revision,
        expected_tool_snapshot_id=management.binding.tool_snapshot_id,
        preview_digest=preview.preview_digest,
        deadline_seconds=2.0,
    )
    try:
        ready = runtime.start(MANAGEMENT_ID, PROJECT_ID, start)
        assert ready.state == "ready"
        assert factory.opened == 1
        assert runtime.start(MANAGEMENT_ID, PROJECT_ID, start) == ready
        assert factory.opened == 1

        stopped = runtime.stop(
            MANAGEMENT_ID,
            PROJECT_ID,
            StopMcpManagedHost(
                request_id="2" * 32,
                expected_instance_id=ready.instance_id,
                deadline_seconds=2.0,
            ),
        )
        assert stopped.state == "not_started"
        assert factory.closed == 1
        assert [(item.action, item.outcome) for item in receipts.host_actions] == [
            ("start", "ready"),
            ("stop", "stopped"),
        ]
        rendered = "".join(item.model_dump_json() for item in receipts.host_actions)
        for forbidden in (
            "https://",
            "synthetic.example",
            "synthetic_echo",
            "synthetic result",
            "credential_persisted\":true",
            "command_or_path\":true",
        ):
            assert forbidden not in rendered

        with pytest.raises(McpManagedRuntimeError) as replayed:
            runtime.start(MANAGEMENT_ID, PROJECT_ID, start)
        assert replayed.value.code == "mcp_host_action_request_already_settled"
        assert factory.opened == 1
    finally:
        runtime.shutdown()


def test_cleanup_uncertainty_survives_runtime_recreation_and_blocks_restart() -> None:
    management = _RuntimeManagementStub()
    receipts = _ReceiptStub()
    failing = _CleanupFailingSupervisor(management)
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        failing,  # type: ignore[arg-type]
        receipts,
        clock=lambda: NOW,
        app_run_digest="8" * 64,
    )
    blocked = runtime.stop(
        MANAGEMENT_ID,
        PROJECT_ID,
        StopMcpManagedHost(
            request_id="3" * 32,
            expected_instance_id=failing.ready.instance_id,
            deadline_seconds=2.0,
        ),
    )
    assert blocked.state == "cleanup_required"
    assert receipts.host_actions[0].outcome == "cleanup_required"
    assert receipts.cleanup_evidence[0].block.lifecycle_actions_blocked is True

    fresh_factory = _Factory(_Client())
    fresh_supervisor = McpManagedHostSupervisor(
        fresh_factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    restarted = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        fresh_supervisor,
        receipts,
        clock=lambda: NOW,
        app_run_digest="9" * 64,
    )
    try:
        restored = restarted.status(MANAGEMENT_ID, PROJECT_ID)
        assert restored.state == "cleanup_required"
        assert restored.instance_id == failing.ready.instance_id
        preview = build_mcp_managed_host_start_preview(management.binding)
        with pytest.raises(McpManagedRuntimeError) as refused:
            restarted.start(
                MANAGEMENT_ID,
                PROJECT_ID,
                StartMcpManagedHost(
                    request_id="4" * 32,
                    expected_server_revision=management.binding.server_revision,
                    expected_project_binding_revision=(
                        management.binding.project_binding_revision
                    ),
                    expected_tool_snapshot_id=management.binding.tool_snapshot_id,
                    preview_digest=preview.preview_digest,
                    deadline_seconds=2.0,
                ),
            )
        assert refused.value.code == "mcp_host_cleanup_unconfirmed"
        assert fresh_factory.opened == 0
        assert restarted.model_tool_schemas(PROJECT_ID) == ()
    finally:
        restarted.shutdown()


def test_project_authority_change_revokes_host_before_mutation_can_continue() -> None:
    management = _RuntimeManagementStub()
    factory = _Factory(_Client())
    supervisor = McpManagedHostSupervisor(
        factory,  # type: ignore[arg-type]
        health_interval_seconds=60.0,
    )
    receipts = _ReceiptStub()
    runtime = McpManagedRuntimeService(
        management,  # type: ignore[arg-type]
        supervisor,
        receipts,
        clock=lambda: NOW,
        app_run_digest="8" * 64,
    )
    preview = build_mcp_managed_host_start_preview(management.binding)
    try:
        ready = runtime.start(
            MANAGEMENT_ID,
            PROJECT_ID,
            StartMcpManagedHost(
                request_id="a" * 32,
                expected_server_revision=management.binding.server_revision,
                expected_project_binding_revision=(
                    management.binding.project_binding_revision
                ),
                expected_tool_snapshot_id=management.binding.tool_snapshot_id,
                preview_digest=preview.preview_digest,
                deadline_seconds=2.0,
            ),
        )
        revoked = runtime.revoke_project_host(
            MANAGEMENT_ID,
            PROJECT_ID,
            request_id="b" * 32,
            deadline_seconds=2.0,
        )
        assert ready.state == "ready"
        assert revoked.state == "not_started"
        assert factory.closed == 1
        assert receipts.host_actions[-1].action == "revoke_project"
        assert receipts.host_actions[-1].reason == "project_revoked"
        assert receipts.host_actions[-1].outcome == "stopped"
        assert runtime.model_tool_schemas(PROJECT_ID) == ()
    finally:
        runtime.shutdown()


def test_durable_call_receipt_cannot_hold_arguments_results_or_authority() -> None:
    receipt = McpManagedToolCallReceipt(
        call_id="3" * 32,
        management_id=MANAGEMENT_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        host_instance_id="4" * 32,
        tool_snapshot_id=SNAPSHOT_ID,
        tool_id=_snapshot().tools[0].tool_id,
        server_revision=7,
        project_binding_revision=3,
        argument_digest="5" * 64,
        argument_bytes=21,
        approval_state="approved",
        outcome="succeeded",
        requested_at=NOW,
        completed_at=NOW,
        result_bytes=16,
        result_digest="6" * 64,
        cleanup_verified=True,
    )
    payload = receipt.model_dump(mode="json")
    assert payload["arguments_persisted"] is False
    assert payload["result_persisted"] is False
    assert payload["reusable_approval_persisted"] is False
    with pytest.raises(Exception):
        McpManagedToolCallReceipt.model_validate({**payload, "arguments": {"secret": "forbidden"}})


def test_schema_29_keeps_call_claim_host_and_package_evidence_content_free(tmp_path) -> None:
    database = AgentCatalogSqliteDatabase(
        tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    )
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION == 30
    with database.connect() as connection:
        claim_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_tool_call_claims)"
            ).fetchall()
        }
        call_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_tool_call_receipts)"
            ).fetchall()
        }
        action_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_host_action_receipts)"
            ).fetchall()
        }
        cleanup_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_host_cleanup_blocks)"
            ).fetchall()
        }
        inspection_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_local_configuration_inspections)"
            ).fetchall()
        }
        migrations = {
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM agent_catalog_schema_migrations"
            ).fetchall()
        }
        scope_triggers = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'mcp_managed_tool_call_%'"
            ).fetchall()
        }
    assert migrations == set(range(1, 31))
    assert scope_triggers == {
        "mcp_managed_tool_call_claims_scope_insert",
        "mcp_managed_tool_call_claims_immutable",
        "mcp_managed_tool_call_receipts_claim_insert",
        "mcp_managed_tool_call_receipts_immutable",
    }
    assert {
        "app_run_digest",
        "argument_digest",
        "argument_bytes",
        "approval_digest",
        "approval_state",
        "approval_expires_at",
        "claimed_at",
        "replay_grants_authority",
    } <= claim_columns
    assert {
        "argument_digest",
        "argument_bytes",
        "result_digest",
        "result_bytes",
        "cleanup_verified",
    } <= call_columns
    assert {
        "request_id",
        "app_run_digest",
        "binding_digest",
        "outcome",
        "cleanup_state",
    } <= action_columns
    assert {
        "app_run_digest",
        "binding_digest",
        "binding_json",
        "lifecycle_actions_blocked",
        "cleanup_verified",
    } <= cleanup_columns
    assert {
        "artifact_sha256",
        "manifest_digest",
        "configuration_schema_digest",
        "requirement_ids_json",
        "archive_retained",
        "process_started",
        "configuration_values_persisted",
        "manifest_content_persisted",
    } <= inspection_columns
    forbidden = {
        "arguments",
        "result",
        "endpoint",
        "credential",
        "command",
        "path",
        "prompt",
        "transcript",
        "approval_token",
        "pid",
        "process_id",
    }
    assert not call_columns.intersection(forbidden)
    assert not claim_columns.intersection(forbidden)
    assert not action_columns.intersection(forbidden)
    assert not cleanup_columns.intersection(forbidden)
    assert not inspection_columns.intersection(forbidden)


def test_schema_27_migrates_once_to_immutable_one_use_call_claims(tmp_path) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    current = AgentCatalogSqliteDatabase(path)
    assert current.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE mcp_managed_tool_call_claims")
        connection.execute("DROP TABLE agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=28"
        )
        connection.execute("PRAGMA user_version=27")

    migrated = AgentCatalogSqliteDatabase(path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_catalog_schema_migrations WHERE version=28"
            ).fetchone()[0]
        )
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_tool_call_claims)"
            ).fetchall()
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='mcp_managed_tool_call_claims'"
            ).fetchone()[0]
        )
    assert migration_count == 1
    assert {
        "approval_digest",
        "approval_state",
        "approval_expires_at",
        "approval_identifier_persisted",
        "replay_grants_authority",
    } <= columns
    assert not columns.intersection(
        {"approval_id", "arguments", "result", "endpoint", "credential"}
    )
    assert "approval_identifier_persisted=0" in table_sql
    assert "replay_grants_authority=0" in table_sql


def test_schema_26_migrates_once_through_package_inspection_and_call_claims(
    tmp_path,
) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    current = AgentCatalogSqliteDatabase(path)
    assert current.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE mcp_managed_tool_call_claims")
        connection.execute(
            "DROP TABLE mcp_managed_local_configuration_inspections"
        )
        connection.execute("DROP TABLE agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=27"
        )
        connection.execute("PRAGMA user_version=26")

    migrated = AgentCatalogSqliteDatabase(path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        migrations = {
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM agent_catalog_schema_migrations WHERE version>=27"
            ).fetchall()
        }
        inspection_migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_catalog_schema_migrations WHERE version=27"
            ).fetchone()[0]
        )
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(mcp_managed_local_configuration_inspections)"
            ).fetchall()
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='mcp_managed_local_configuration_inspections'"
            ).fetchone()[0]
        )
        current_index_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
                "AND name='mcp_managed_local_configuration_inspections_current_idx'"
            ).fetchone()[0]
        )
        claim_table_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='mcp_managed_tool_call_claims'"
            ).fetchone()[0]
        )
    assert migrations == {27, 28, 29, 30}
    assert inspection_migration_count == 1
    assert current_index_count == 1
    assert claim_table_count == 1
    assert {
        "plan_revision",
        "artifact_sha256",
        "manifest_digest",
        "configuration_schema_digest",
        "requirement_ids_json",
        "current_state",
    } <= columns
    assert not columns.intersection(
        {"value", "default", "manifest", "archive", "command", "environment"}
    )
    assert "archive_retained=0" in table_sql
    assert "process_started=0" in table_sql
    assert "configuration_values_persisted=0" in table_sql
    assert "manifest_content_persisted=0" in table_sql


def test_schema_24_migrates_once_through_call_and_host_lifecycle_receipts(tmp_path) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    current = AgentCatalogSqliteDatabase(path)
    assert current.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE mcp_managed_tool_call_claims")
        connection.execute("DROP TABLE mcp_managed_local_configuration_inspections")
        connection.execute("DROP TABLE mcp_managed_host_cleanup_blocks")
        connection.execute("DROP TABLE mcp_managed_host_action_receipts")
        connection.execute("DROP TABLE mcp_managed_tool_call_receipts")
        connection.execute("DROP TABLE agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=25"
        )
        connection.execute("PRAGMA user_version=24")

    migrated = AgentCatalogSqliteDatabase(path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        migrations = {
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM agent_catalog_schema_migrations WHERE version>=25"
            ).fetchall()
        }
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mcp_managed_%receipts'"
            ).fetchall()
        }
    assert migrations == {25, 26, 27, 28, 29, 30}
    assert {
        "mcp_managed_tool_call_receipts",
        "mcp_managed_host_action_receipts",
    } <= tables


def test_schema_25_migrates_once_to_host_lifecycle_evidence(tmp_path) -> None:
    path = tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    current = AgentCatalogSqliteDatabase(path)
    assert current.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE mcp_managed_tool_call_claims")
        connection.execute("DROP TABLE mcp_managed_local_configuration_inspections")
        connection.execute("DROP TABLE mcp_managed_host_cleanup_blocks")
        connection.execute("DROP TABLE mcp_managed_host_action_receipts")
        connection.execute("DROP TABLE agent_catalog_migration_checksums")
        connection.execute(
            "DELETE FROM agent_catalog_schema_migrations WHERE version>=26"
        )
        connection.execute("PRAGMA user_version=25")

    migrated = AgentCatalogSqliteDatabase(path)
    assert migrated.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    with migrated.connect() as connection:
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_catalog_schema_migrations WHERE version=26"
            ).fetchone()[0]
        )
        table_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                "('mcp_managed_host_action_receipts','mcp_managed_host_cleanup_blocks')"
            ).fetchone()[0]
        )
    assert migration_count == 1
    assert table_count == 2


def test_sqlite_restart_terminalizes_prior_run_claims_without_replay_authority(
    tmp_path,
) -> None:
    database = AgentCatalogSqliteDatabase(
        tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    )
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    timestamp = NOW.isoformat(timespec="microseconds")
    snapshot = _snapshot()
    tool = snapshot.tools[0]
    encode = lambda value: json.dumps(  # noqa: E731 - compact fixture encoder
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO agent_projects(
                project_id,name,created_at,updated_at,revision,pinned,archived_at,
                is_default
            ) VALUES (?,?,?,?,1,0,NULL,0)
            """,
            (PROJECT_ID, "Synthetic project", timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO agent_catalog_sessions(
                session_id,project_id,title,workspace,model_alias,created_at,
                updated_at,last_opened_at,revision,pinned,archived_at,history_state
            ) VALUES (?,?,?,?,NULL,?,?,?,1,0,NULL,'memory_only')
            """,
            (
                SESSION_ID,
                PROJECT_ID,
                "Synthetic chat",
                "X:/synthetic-workspace",
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO mcp_managed_servers(
                management_id,request_id,request_fingerprint,catalog_id,
                server_name,server_title,server_version,server_status_at_review,
                option_id,plan_revision,option_kind,option_label,registry_type,
                package_identifier,package_version,runtime_hint,transport,
                endpoint_host,endpoint_state,secure_transport,
                required_permissions_json,risks_json,created_at,updated_at,
                revision,lifecycle_state,installation_state,host_state,
                health_state,last_health_checked_at,update_state,
                latest_available_version,tool_routing_state
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?,?,?,?,?,?, ?,1,
                'planned','not_installed','not_started','not_checked',NULL,
                'not_checked',NULL,'inactive'
            )
            """,
            (
                MANAGEMENT_ID,
                "5" * 32,
                "6" * 64,
                "7" * 32,
                "example.synthetic/server",
                "Synthetic MCP",
                "1.0.0",
                "active",
                "8" * 32,
                snapshot.plan_revision,
                "remote_server",
                "Synthetic remote",
                "streamable-http",
                "synthetic.example",
                "fixed_host",
                1,
                '["network_egress"]',
                "[]",
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO mcp_managed_tool_snapshots(
                snapshot_id,management_id,observation_id,plan_revision,source,
                source_tree_digest,protocol_version,tool_count,schema_digest,
                reviewed_at,created_at
            ) VALUES (?,?,?,?, 'remote_probe',NULL,?,?,?,?,?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.management_id,
                "9" * 32,
                snapshot.plan_revision,
                snapshot.protocol_version,
                snapshot.tool_count,
                snapshot.schema_digest,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            """
            INSERT INTO mcp_managed_tools(
                snapshot_id,tool_id,tool_order,name,title,description,model_alias,
                input_schema_json,input_schema_digest,model_input_schema_json,
                output_schema_json,output_schema_digest,contract_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                snapshot.snapshot_id,
                tool.tool_id,
                0,
                tool.name,
                tool.title,
                tool.description,
                tool.model_alias,
                encode(tool.input_schema),
                tool.input_schema_digest,
                encode(tool.model_input_schema),
                encode(tool.output_schema),
                tool.output_schema_digest,
                tool.contract_digest,
            ),
        )

    approval_id = "1" * 32
    claim = McpManagedToolCallClaim(
        call_id="2" * 32,
        app_run_digest="3" * 64,
        management_id=MANAGEMENT_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        host_instance_id="4" * 32,
        tool_snapshot_id=snapshot.snapshot_id,
        tool_id=tool.tool_id,
        server_revision=7,
        project_binding_revision=3,
        argument_digest="5" * 64,
        argument_bytes=21,
        approval_digest=hashlib.sha256(approval_id.encode("ascii")).hexdigest(),
        approval_state="approved",
        requested_at=NOW,
        approval_expires_at=NOW + timedelta(minutes=30),
        claimed_at=NOW,
    )
    old_claims = (
        claim,
        claim.model_copy(update={"call_id": "6" * 32, "approval_state": "denied"}),
        claim.model_copy(update={"call_id": "7" * 32, "approval_state": "timed_out"}),
        claim.model_copy(
            update={
                "call_id": "8" * 32,
                "approval_state": "cancelled_before_decision",
            }
        ),
    )
    current_run_digest = "9" * 64
    current_claim = claim.model_copy(
        update={
            "call_id": "b" * 32,
            "app_run_digest": current_run_digest,
            "approval_state": "denied",
        }
    )
    first = SqliteMcpManagedRuntimeReceiptRepository(database)
    for item in (*old_claims, current_claim):
        assert first.claim_tool_call(item) is True

    restarted = SqliteMcpManagedRuntimeReceiptRepository(database)
    for item in old_claims:
        assert restarted.get_tool_call_claim(item.call_id) == item
    assert restarted.claim_tool_call(claim) is False
    assert approval_id not in claim.model_dump_json()

    receipts = restarted.reconcile_interrupted_tool_calls(
        current_app_run_digest=current_run_digest,
        interrupted_at=NOW + timedelta(seconds=1),
    )
    assert {item.call_id: item.outcome for item in receipts} == {
        claim.call_id: "failed",
        "6" * 32: "denied",
        "7" * 32: "timed_out",
        "8" * 32: "cancelled",
    }
    approved_receipt = restarted.get_tool_call_receipt(claim.call_id)
    assert approved_receipt is not None
    assert approved_receipt.error_code == "mcp_tool_call_interrupted"
    assert approved_receipt.cleanup_verified is False
    assert approved_receipt.result_bytes == 0
    assert approved_receipt.result_digest is None
    assert all(
        item.cleanup_verified is True and item.error_code is None
        for item in receipts
        if item.approval_state != "approved"
    )
    assert restarted.get_tool_call_receipt(current_claim.call_id) is None
    assert restarted.reconcile_interrupted_tool_calls(
        current_app_run_digest=current_run_digest,
        interrupted_at=NOW + timedelta(seconds=2),
    ) == ()
    assert restarted.claim_tool_call(claim) is False

    other_project_id = "0" * 32
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO agent_projects(
                project_id,name,created_at,updated_at,revision,pinned,archived_at,
                is_default
            ) VALUES (?,?,?,?,1,0,NULL,0)
            """,
            (other_project_id, "Other synthetic project", timestamp, timestamp),
        )
    wrong_scope = claim.model_copy(
        update={
            "call_id": "a" * 32,
            "project_id": other_project_id,
        }
    )
    with pytest.raises(McpManagedRuntimeError) as crossed_project:
        restarted.claim_tool_call(wrong_scope)
    assert crossed_project.value.code == "mcp_tool_claim_binding_invalid"
    assert restarted.get_tool_call_claim(wrong_scope.call_id) is None

    with database.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE mcp_managed_tool_call_claims SET project_id=? WHERE call_id=?",
                (other_project_id, claim.call_id),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE mcp_managed_tool_call_receipts SET project_id=? WHERE call_id=?",
                (other_project_id, claim.call_id),
            )


def test_sqlite_host_receipts_and_cleanup_blocks_survive_repository_recreation(
    tmp_path,
) -> None:
    database = AgentCatalogSqliteDatabase(
        tmp_path / AGENT_CATALOG_DATABASE_FILENAME
    )
    assert database.initialize() == AGENT_CATALOG_SCHEMA_VERSION
    timestamp = NOW.isoformat(timespec="microseconds")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO agent_projects(
                project_id,name,created_at,updated_at,revision,pinned,archived_at,
                is_default
            ) VALUES (?,?,?,?,1,0,NULL,0)
            """,
            (PROJECT_ID, "Synthetic project", timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO mcp_managed_servers(
                management_id,request_id,request_fingerprint,catalog_id,
                server_name,server_title,server_version,server_status_at_review,
                option_id,plan_revision,option_kind,option_label,registry_type,
                package_identifier,package_version,runtime_hint,transport,
                endpoint_host,endpoint_state,secure_transport,
                required_permissions_json,risks_json,created_at,updated_at,
                revision,lifecycle_state,installation_state,host_state,
                health_state,last_health_checked_at,update_state,
                latest_available_version,tool_routing_state
            ) VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?,?,?,?,?,?, ?,1,
                'planned','not_installed','not_started','not_checked',NULL,
                'not_checked',NULL,'inactive'
            )
            """,
            (
                MANAGEMENT_ID,
                "5" * 32,
                "6" * 64,
                "7" * 32,
                "example.synthetic/server",
                "Synthetic MCP",
                "1.0.0",
                "active",
                "8" * 32,
                "f" * 64,
                "remote_server",
                "Synthetic remote",
                "streamable-http",
                "synthetic.example",
                "fixed_host",
                1,
                '["network_egress"]',
                "[]",
                timestamp,
                timestamp,
            ),
        )

    binding = _binding(_snapshot())
    action = McpManagedHostActionReceipt(
        receipt_id="9" * 32,
        request_id="1" * 32,
        management_id=MANAGEMENT_ID,
        project_id=PROJECT_ID,
        instance_id="2" * 32,
        app_run_digest="3" * 64,
        binding_digest=mcp_managed_host_binding_digest(binding),
        execution_kind="reviewed_remote_connection",
        action="start",
        outcome="ready",
        reason="owner_start",
        requested_at=NOW,
        completed_at=NOW,
        process_started=False,
        cleanup_state="not_applicable",
        host_ready=True,
    )
    evidence = McpManagedHostCleanupEvidence(
        block=McpManagedHostCleanupBlock(
            block_id="4" * 32,
            management_id=MANAGEMENT_ID,
            project_id=PROJECT_ID,
            instance_id="2" * 32,
            app_run_digest="3" * 64,
            binding_digest=mcp_managed_host_binding_digest(binding),
            reason="remote_connection_cleanup_unconfirmed",
            state="active",
            process_started=False,
            cleanup_verified=False,
            lifecycle_actions_blocked=True,
            recovery_attempts=0,
            created_at=NOW,
            updated_at=NOW,
        ),
        binding=binding,
    )
    first = SqliteMcpManagedRuntimeReceiptRepository(database)
    first.record_host_action_receipt(action)
    first.record_cleanup_evidence(evidence)

    restarted = SqliteMcpManagedRuntimeReceiptRepository(database)
    assert restarted.get_host_action_receipt(action.request_id) == action
    assert (
        restarted.get_active_cleanup_evidence(MANAGEMENT_ID, PROJECT_ID)
        == evidence
    )
    restarted.record_host_action_receipt(action)
    restarted.record_cleanup_evidence(evidence)
    with database.connect() as connection:
        action_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM mcp_managed_host_action_receipts"
            ).fetchone()[0]
        )
        block_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM mcp_managed_host_cleanup_blocks"
            ).fetchone()[0]
        )
    assert action_count == block_count == 1


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("mcp_tool_approval_replayed", 409),
        ("mcp_tool_alias_collision", 409),
        ("mcp_tool_call_scope_conflict", 409),
        ("mcp_tool_claim_unavailable", 503),
        ("mcp_tool_claim_storage_unavailable", 503),
        ("mcp_tool_claim_storage_corrupt", 503),
        ("mcp_tool_claim_binding_invalid", 503),
    ],
)
def test_runtime_http_error_taxonomy_is_content_free(code: str, status: int) -> None:
    failure = _runtime_error(McpManagedRuntimeError(code))
    assert failure.status_code == status
    assert failure.detail == code


def test_runtime_http_boundary_is_private_confirmed_and_inert_on_reads() -> None:
    runtime = _RuntimeRouteStub()

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer synthetic-local-token":
            raise HTTPException(status_code=401, detail="local authentication required")

    def require_confirmation(
        x_synthetic_confirmation: str | None = Header(default=None),
    ) -> None:
        if x_synthetic_confirmation != "confirmed":
            raise HTTPException(status_code=403, detail="native confirmation required")

    app = FastAPI()
    app.include_router(
        create_mcp_server_management_router(
            require_auth,
            require_confirmation,
            SimpleNamespace(),  # Runtime-only routes do not touch plan methods.
            runtime,  # type: ignore[arg-type]
        )
    )
    client = TestClient(app)
    base = (
        f"{MCP_MANAGED_SERVER_PATH}/{MANAGEMENT_ID}/projects/{PROJECT_ID}/host"
    )
    auth = {"Authorization": "Bearer synthetic-local-token"}

    assert client.get(base).status_code == 401
    status = client.get(base, headers=auth)
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store, private"
    assert status.json()["state"] == "not_started"
    assert runtime.starts == 0

    body = {
        "request_id": "7" * 32,
        "expected_server_revision": 7,
        "expected_project_binding_revision": 3,
        "expected_tool_snapshot_id": SNAPSHOT_ID,
        "preview_digest": "8" * 64,
        "deadline_seconds": 2.0,
    }
    assert client.post(base + "/start", headers=auth, json=body).status_code == 403
    started = client.post(
        base + "/start",
        headers={**auth, "X-Synthetic-Confirmation": "confirmed"},
        json=body,
    )
    assert started.status_code == 200
    assert started.json()["tool_calls_available"] is True
    assert runtime.starts == 1

    stopped = client.post(
        base + "/stop",
        headers=auth,
        json={
            "request_id": "9" * 32,
            "expected_instance_id": "6" * 32,
            "deadline_seconds": 2.0,
        },
    )
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "not_started"
    assert runtime.stops == 1
