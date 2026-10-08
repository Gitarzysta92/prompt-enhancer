"""Project-scoped app-run MCP hosting and one-shot tool-call contracts.

The durable Store decides which exact reviewed tools a project may use.  This
module adds no remembered execution authority: a host must be owner-started for
the current app run and every call is prepared, natively approved once, then
revision-checked again before invocation.  Arguments/results exist only in the
live call path; durable receipts are content-free evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
from typing import Any, Literal, Protocol

from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_receipts import AgentToolApprovalState
from .mcp_guarded_host import (
    McpGuardedHostError,
    McpRemoteConnectionSpec,
    McpStdioConnectionSpec,
    mcp_json_schema_validator,
)
from .mcp_managed_host import (
    McpManagedHostActionReceipt,
    McpManagedHostBinding,
    McpManagedHostCleanupBlock,
    McpManagedHostStatus,
    StartMcpManagedHost,
    StopMcpManagedHost,
    mcp_managed_host_binding_digest,
)
from .mcp_server_management import (
    McpManagedReviewedTool,
    McpManagedServerError,
    McpManagedServerService,
    McpManagedToolSnapshot,
)


MCP_MANAGED_RUNTIME_CONTRACT_VERSION = "mcp-managed-runtime.v1"
MAX_MCP_MANAGED_ARGUMENT_BYTES = 64 * 1024
MAX_MCP_MANAGED_RESULT_BYTES = 128 * 1024
MAX_MCP_MANAGED_RESULT_CHARS = 48_000
MAX_MCP_MANAGED_CALL_SECONDS = 60.0
MAX_MCP_MANAGED_ARGUMENT_NODES = 4_096
MAX_MCP_MANAGED_ARGUMENT_DEPTH = 32
MAX_MCP_MANAGED_PREVIEW_CHARS = 4_000
MAX_MCP_MANAGED_APPROVAL_SECONDS = 1_800.0
MAX_MCP_MANAGED_RESULT_NODES = 8_192
MAX_MCP_MANAGED_RESULT_DEPTH = 32
MAX_MCP_MANAGED_RESULT_COLLECTION_ITEMS = 1_024
MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS = 256
MAX_MCP_MANAGED_JSON_INTEGER_BITS = 16_384

_ID_PATTERN = r"^[0-9a-f]{32}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_ERROR_PATTERN = r"^[a-z0-9_]{1,96}$"
_SECRET_KEY = re.compile(
    r"(?:authorization|credential|password|passwd|secret|token|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)


class McpManagedRuntimeError(RuntimeError):
    """Stable content-free failure at the managed runtime boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("managed MCP runtime timestamps require a timezone")
    return value.astimezone(UTC)


def _canonical_json(
    value: Any,
    *,
    maximum: int,
    invalid_code: str,
    maximum_nodes: int = MAX_MCP_MANAGED_ARGUMENT_NODES,
    maximum_depth: int = MAX_MCP_MANAGED_ARGUMENT_DEPTH,
    maximum_collection_items: int = 1_024,
    maximum_string_chars: int = MAX_MCP_MANAGED_ARGUMENT_BYTES,
    too_large_code: str | None = None,
    too_complex_code: str | None = None,
) -> bytes:
    """Bound arbitrary JSON without recursive Python traversal."""

    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > maximum_nodes or depth > maximum_depth:
            raise McpManagedRuntimeError(too_complex_code or invalid_code)
        if isinstance(current, Mapping):
            if len(current) > maximum_collection_items:
                raise McpManagedRuntimeError(too_complex_code or invalid_code)
            for key, child in current.items():
                if not isinstance(key, str) or not key or len(key) > 256 or "\x00" in key:
                    raise McpManagedRuntimeError(invalid_code)
                stack.append((child, depth + 1))
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            if len(current) > maximum_collection_items:
                raise McpManagedRuntimeError(too_complex_code or invalid_code)
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            if len(current) > maximum_string_chars:
                raise McpManagedRuntimeError(too_large_code or invalid_code)
            if "\x00" in current:
                raise McpManagedRuntimeError(invalid_code)
        elif isinstance(current, float):
            if not math.isfinite(current):
                raise McpManagedRuntimeError(invalid_code)
        elif isinstance(current, int) and not isinstance(current, bool):
            if current.bit_length() > MAX_MCP_MANAGED_JSON_INTEGER_BITS:
                raise McpManagedRuntimeError(invalid_code)
        elif current is not None and not isinstance(current, bool):
            raise McpManagedRuntimeError(invalid_code)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise McpManagedRuntimeError(invalid_code) from None
    if len(encoded) > maximum:
        raise McpManagedRuntimeError(too_large_code or invalid_code)
    return encoded


def validate_mcp_tool_arguments(
    arguments: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> tuple[dict[str, Any], str, int]:
    """Return one canonical detached argument object after exact validation."""

    encoded = _canonical_json(
        arguments,
        maximum=MAX_MCP_MANAGED_ARGUMENT_BYTES,
        invalid_code="mcp_tool_arguments_invalid",
    )
    try:
        detached = json.loads(encoded)
        mcp_json_schema_validator(schema).validate(detached)
    except (
        JsonSchemaValidationError,
        McpGuardedHostError,
        ValueError,
        TypeError,
        RecursionError,
    ):
        raise McpManagedRuntimeError("mcp_tool_arguments_schema_mismatch") from None
    if not isinstance(detached, dict):
        raise McpManagedRuntimeError("mcp_tool_arguments_invalid")
    return detached, hashlib.sha256(encoded).hexdigest(), len(encoded)


def validate_mcp_tool_result(
    result: Any,
    schema: Mapping[str, Any] | None,
) -> tuple[Any, bytes]:
    """Detach and validate one structured result under result-specific budgets."""

    encoded = _canonical_json(
        result,
        maximum=MAX_MCP_MANAGED_RESULT_BYTES,
        invalid_code="mcp_tool_result_malformed",
        maximum_nodes=MAX_MCP_MANAGED_RESULT_NODES,
        maximum_depth=MAX_MCP_MANAGED_RESULT_DEPTH,
        maximum_collection_items=MAX_MCP_MANAGED_RESULT_COLLECTION_ITEMS,
        maximum_string_chars=MAX_MCP_MANAGED_RESULT_CHARS,
        too_large_code="mcp_tool_result_too_large",
        too_complex_code="mcp_tool_result_too_complex",
    )
    try:
        detached = json.loads(encoded)
        if schema is not None:
            mcp_json_schema_validator(schema).validate(detached)
    except (
        JsonSchemaValidationError,
        McpGuardedHostError,
        ValueError,
        TypeError,
        RecursionError,
    ):
        raise McpManagedRuntimeError("mcp_tool_result_schema_mismatch") from None
    return detached, encoded


def _redacted_preview(value: Any) -> str:
    """Build a bounded live-only review preview without exposing secret fields."""

    def redact(current: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "<depth omitted>"
        if isinstance(current, Mapping):
            result: dict[str, Any] = {}
            for index, (key, child) in enumerate(current.items()):
                if index >= 64:
                    result["…"] = "<additional fields omitted>"
                    break
                name = str(key)
                result[name] = "<redacted>" if _SECRET_KEY.search(name) else redact(child, depth + 1)
            return result
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            values = [redact(child, depth + 1) for child in current[:64]]
            if len(current) > 64:
                values.append("<additional items omitted>")
            return values
        if isinstance(current, str) and len(current) > 512:
            return current[:512] + f"… ({len(current)} chars)"
        return current

    text = json.dumps(redact(value), ensure_ascii=False, indent=2, allow_nan=False)
    if len(text) > MAX_MCP_MANAGED_PREVIEW_CHARS:
        return text[:MAX_MCP_MANAGED_PREVIEW_CHARS] + "\n… preview truncated"
    return text


class McpManagedReadyTool(StrictModel):
    """One currently routed project tool suitable for a local model schema."""

    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    host_instance_id: str = Field(pattern=_ID_PATTERN)
    server_title: str = Field(min_length=1, max_length=100)
    tool_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    model_alias: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1, max_length=4_096)
    model_input_schema: dict[str, Any]


class McpManagedProjectRuntime(StrictModel):
    contract_version: Literal["mcp-managed-runtime.v1"] = MCP_MANAGED_RUNTIME_CONTRACT_VERSION
    project_id: str = Field(pattern=_ID_PATTERN)
    ready_host_count: int = Field(strict=True, ge=0, le=4)
    ready_tool_count: int = Field(strict=True, ge=0, le=256)
    tools: tuple[McpManagedReadyTool, ...] = Field(max_length=256)
    automatic_start: Literal[False] = False
    remembered_call_approval: Literal[False] = False
    every_call_requires_native_approval: Literal[True] = True

    @model_validator(mode="after")
    def coherent_counts(self) -> "McpManagedProjectRuntime":
        if self.ready_tool_count != len(self.tools):
            raise ValueError("managed MCP ready tool count is incoherent")
        if len({item.model_alias for item in self.tools}) != len(self.tools):
            raise ValueError("managed MCP ready aliases are not unique")
        if any(item.project_id != self.project_id for item in self.tools):
            raise ValueError("managed MCP ready tool crossed project scope")
        return self


class McpManagedCallProjection(StrictModel):
    """Ephemeral bounded result returned to the current local Agent turn."""

    contract_version: Literal["mcp-managed-call-projection.v1"] = (
        "mcp-managed-call-projection.v1"
    )
    call_id: str = Field(pattern=_ID_PATTERN)
    outcome: Literal["succeeded", "tool_error", "failed", "cancelled", "timed_out"]
    text: str = Field(max_length=MAX_MCP_MANAGED_RESULT_CHARS)
    result_bytes: int = Field(strict=True, ge=0, le=MAX_MCP_MANAGED_RESULT_BYTES)
    result_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    error_code: str | None = Field(default=None, pattern=_ERROR_PATTERN)
    content_mode: Literal["text", "structured_json", "text_and_structured_json", "none"]
    cleanup_verified: bool = Field(strict=True)

    @model_validator(mode="after")
    def coherent_projection(self) -> "McpManagedCallProjection":
        terminal_error = self.outcome in {"failed", "cancelled", "timed_out"}
        if terminal_error != (self.error_code is not None):
            raise ValueError("managed MCP call error evidence is incoherent")
        if self.outcome in {"succeeded", "tool_error"} and self.result_digest is None:
            raise ValueError("managed MCP call result evidence is incomplete")
        if self.result_bytes != len(self.text.encode("utf-8")):
            raise ValueError("managed MCP call result byte count is incoherent")
        return self


class McpManagedToolCallReceipt(StrictModel):
    """Durable content-free evidence for one approval-bound call attempt."""

    contract_version: Literal["mcp-managed-tool-call-receipt.v1"] = (
        "mcp-managed-tool-call-receipt.v1"
    )
    call_id: str = Field(pattern=_ID_PATTERN)
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    turn_id: str = Field(pattern=_ID_PATTERN)
    host_instance_id: str = Field(pattern=_ID_PATTERN)
    tool_snapshot_id: str = Field(pattern=_ID_PATTERN)
    tool_id: str = Field(pattern=_ID_PATTERN)
    server_revision: int = Field(strict=True, ge=1)
    project_binding_revision: int = Field(strict=True, ge=1)
    argument_digest: str = Field(pattern=_DIGEST_PATTERN)
    argument_bytes: int = Field(strict=True, ge=2, le=MAX_MCP_MANAGED_ARGUMENT_BYTES)
    approval_state: AgentToolApprovalState
    outcome: Literal["denied", "timed_out", "cancelled", "succeeded", "tool_error", "failed"]
    error_code: str | None = Field(default=None, pattern=_ERROR_PATTERN)
    requested_at: datetime
    completed_at: datetime
    result_bytes: int = Field(strict=True, ge=0, le=MAX_MCP_MANAGED_RESULT_BYTES)
    result_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    cleanup_verified: bool = Field(strict=True)
    arguments_persisted: Literal[False] = False
    result_persisted: Literal[False] = False
    credentials_persisted: Literal[False] = False
    reusable_approval_persisted: Literal[False] = False

    @field_validator("requested_at", "completed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_receipt(self) -> "McpManagedToolCallReceipt":
        if self.completed_at < self.requested_at:
            raise ValueError("managed MCP call timestamps are incoherent")
        expected_by_approval = {
            "denied": "denied",
            "timed_out": "timed_out",
            "cancelled_before_decision": "cancelled",
        }
        expected = expected_by_approval.get(self.approval_state)
        if expected is not None and self.outcome != expected:
            raise ValueError("managed MCP call approval outcome is incoherent")
        if self.approval_state != "approved" and (
            self.result_bytes != 0 or self.result_digest is not None
        ):
            raise ValueError("unapproved managed MCP call retains result evidence")
        if self.outcome in {"succeeded", "tool_error"}:
            if self.approval_state != "approved" or self.result_digest is None or self.error_code is not None:
                raise ValueError("completed managed MCP call evidence is incoherent")
        elif self.outcome == "failed":
            if self.approval_state != "approved" or self.error_code is None:
                raise ValueError("failed managed MCP call evidence is incoherent")
        elif self.error_code is not None:
            raise ValueError("settled approval outcome cannot retain an error code")
        return self


class McpManagedToolCallClaim(StrictModel):
    """Immutable content-free one-use claim written before tool dispatch."""

    contract_version: Literal["mcp-managed-tool-call-claim.v1"] = (
        "mcp-managed-tool-call-claim.v1"
    )
    call_id: str = Field(pattern=_ID_PATTERN)
    app_run_digest: str = Field(pattern=_DIGEST_PATTERN)
    management_id: str = Field(pattern=_ID_PATTERN)
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    turn_id: str = Field(pattern=_ID_PATTERN)
    host_instance_id: str = Field(pattern=_ID_PATTERN)
    tool_snapshot_id: str = Field(pattern=_ID_PATTERN)
    tool_id: str = Field(pattern=_ID_PATTERN)
    server_revision: int = Field(strict=True, ge=1)
    project_binding_revision: int = Field(strict=True, ge=1)
    argument_digest: str = Field(pattern=_DIGEST_PATTERN)
    argument_bytes: int = Field(strict=True, ge=2, le=MAX_MCP_MANAGED_ARGUMENT_BYTES)
    approval_digest: str = Field(pattern=_DIGEST_PATTERN)
    approval_state: AgentToolApprovalState
    requested_at: datetime
    approval_expires_at: datetime
    claimed_at: datetime
    arguments_persisted: Literal[False] = False
    result_persisted: Literal[False] = False
    approval_identifier_persisted: Literal[False] = False
    replay_grants_authority: Literal[False] = False

    @field_validator("requested_at", "approval_expires_at", "claimed_at")
    @classmethod
    def normalize_claim_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent_claim(self) -> "McpManagedToolCallClaim":
        if self.approval_state not in {
            "approved",
            "denied",
            "timed_out",
            "cancelled_before_decision",
        }:
            raise ValueError("managed MCP call claim lacks a native decision")
        if (
            self.approval_expires_at <= self.requested_at
            or self.claimed_at < self.requested_at
        ):
            raise ValueError("managed MCP call claim timestamps are incoherent")
        return self


class McpManagedHostCleanupEvidence(StrictModel):
    """Internal durable block plus its exact content-free reviewed binding."""

    contract_version: Literal["mcp-managed-host-cleanup-evidence.v1"] = (
        "mcp-managed-host-cleanup-evidence.v1"
    )
    block: McpManagedHostCleanupBlock
    binding: McpManagedHostBinding

    @model_validator(mode="after")
    def coherent_evidence(self) -> "McpManagedHostCleanupEvidence":
        if (
            self.binding.management_id != self.block.management_id
            or self.binding.project_id != self.block.project_id
            or mcp_managed_host_binding_digest(self.binding)
            != self.block.binding_digest
        ):
            raise ValueError("managed MCP cleanup evidence binding is incoherent")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class PreparedMcpManagedToolCall:
    app_run_digest: str
    preparation_digest: str
    call_id: str
    management_id: str
    project_id: str
    session_id: str
    turn_id: str
    host_instance_id: str
    server_title: str
    server_revision: int
    project_binding_revision: int
    tool_snapshot_id: str
    tool: McpManagedReviewedTool
    arguments: dict[str, Any]
    argument_digest: str
    argument_bytes: int
    requested_at: datetime
    approval_id: str
    approval_expires_at: datetime
    deadline_seconds: float
    preview: str


class McpManagedRuntimeReceiptRepository(Protocol):
    def get_tool_call_claim(self, call_id: str) -> McpManagedToolCallClaim | None: ...

    def claim_tool_call(self, claim: McpManagedToolCallClaim) -> bool: ...

    def get_tool_call_receipt(self, call_id: str) -> McpManagedToolCallReceipt | None: ...

    def record_tool_call_receipt(self, receipt: McpManagedToolCallReceipt) -> None: ...

    def reconcile_interrupted_tool_calls(
        self,
        *,
        current_app_run_digest: str,
        interrupted_at: datetime,
    ) -> Sequence[McpManagedToolCallReceipt]: ...

    def get_host_action_receipt(
        self,
        request_id: str,
    ) -> McpManagedHostActionReceipt | None: ...

    def record_host_action_receipt(
        self,
        receipt: McpManagedHostActionReceipt,
    ) -> None: ...

    def get_active_cleanup_evidence(
        self,
        management_id: str,
        project_id: str,
    ) -> McpManagedHostCleanupEvidence | None: ...

    def record_cleanup_evidence(
        self,
        evidence: McpManagedHostCleanupEvidence,
    ) -> None: ...


class McpManagedHostSupervisorPort(Protocol):
    def start(
        self,
        binding: McpManagedHostBinding,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        snapshot: McpManagedToolSnapshot,
        *,
        deadline_seconds: float,
    ) -> McpManagedHostStatus: ...

    def stop(
        self,
        management_id: str,
        project_id: str,
        command: StopMcpManagedHost,
    ) -> McpManagedHostStatus: ...

    def status(self, management_id: str, project_id: str) -> McpManagedHostStatus: ...

    def statuses(self) -> tuple[McpManagedHostStatus, ...]: ...

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
    ) -> McpManagedCallProjection: ...

    def shutdown(self) -> None: ...


class McpManagedRuntimeService:
    """Join durable review/admission to memory-only hosts and one-shot calls."""

    def __init__(
        self,
        management: McpManagedServerService,
        supervisor: McpManagedHostSupervisorPort,
        receipts: McpManagedRuntimeReceiptRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        app_run_digest: str | None = None,
    ) -> None:
        self._management = management
        self._supervisor = supervisor
        self._receipts = receipts
        self._clock = clock or (lambda: datetime.now(UTC))
        run_digest = app_run_digest or hashlib.sha256(
            secrets.token_bytes(32)
        ).hexdigest()
        if re.fullmatch(_DIGEST_PATTERN, run_digest) is None:
            raise ValueError("managed MCP app-run digest is invalid")
        self._app_run_digest = run_digest
        # Prepared calls never survive an application run.  A separate
        # memory-only key prevents another runtime/client instance from
        # settling or modifying a prepared call even if it can observe the
        # otherwise content-free app-run digest.
        self._preparation_key = secrets.token_bytes(32)

    def reconcile_after_restart(self) -> tuple[McpManagedToolCallReceipt, ...]:
        """Terminalize prior-run one-use claims without replaying any authority."""

        try:
            return tuple(
                self._receipts.reconcile_interrupted_tool_calls(
                    current_app_run_digest=self._app_run_digest,
                    interrupted_at=_utc(self._clock()),
                )
            )
        except McpManagedRuntimeError:
            raise
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_tool_restart_reconciliation_unavailable"
            ) from None

    def _preparation_digest(
        self,
        prepared: PreparedMcpManagedToolCall,
    ) -> str:
        material = {
            "contract": "mcp-managed-prepared-call-scope.v1",
            "app_run_digest": prepared.app_run_digest,
            "call_id": prepared.call_id,
            "management_id": prepared.management_id,
            "project_id": prepared.project_id,
            "session_id": prepared.session_id,
            "turn_id": prepared.turn_id,
            "host_instance_id": prepared.host_instance_id,
            "server_title_digest": hashlib.sha256(
                prepared.server_title.encode("utf-8")
            ).hexdigest(),
            "server_revision": prepared.server_revision,
            "project_binding_revision": prepared.project_binding_revision,
            "tool_snapshot_id": prepared.tool_snapshot_id,
            "tool_id": prepared.tool.tool_id,
            "tool_contract_digest": prepared.tool.contract_digest,
            "argument_digest": prepared.argument_digest,
            "argument_bytes": prepared.argument_bytes,
            "requested_at": prepared.requested_at.isoformat(timespec="microseconds"),
            "approval_digest": hashlib.sha256(
                prepared.approval_id.encode("ascii")
            ).hexdigest(),
            "approval_expires_at": prepared.approval_expires_at.isoformat(
                timespec="microseconds"
            ),
            "deadline_seconds": prepared.deadline_seconds,
            "preview_digest": hashlib.sha256(
                prepared.preview.encode("utf-8")
            ).hexdigest(),
        }
        encoded = json.dumps(
            material,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        return hmac.new(self._preparation_key, encoded, hashlib.sha256).hexdigest()

    def _validate_preparation_scope(
        self,
        prepared: PreparedMcpManagedToolCall,
    ) -> None:
        if (
            prepared.app_run_digest != self._app_run_digest
            or not hmac.compare_digest(
                prepared.preparation_digest,
                self._preparation_digest(prepared),
            )
        ):
            raise McpManagedRuntimeError("mcp_tool_call_scope_conflict")
        try:
            reviewed_tool = McpManagedReviewedTool.model_validate(
                prepared.tool.model_dump(mode="python")
            )
            _, argument_digest, argument_bytes = validate_mcp_tool_arguments(
                prepared.arguments,
                reviewed_tool.input_schema,
            )
        except Exception:
            raise McpManagedRuntimeError("mcp_tool_call_scope_conflict") from None
        if (
            reviewed_tool != prepared.tool
            or argument_digest != prepared.argument_digest
            or argument_bytes != prepared.argument_bytes
        ):
            raise McpManagedRuntimeError("mcp_tool_call_scope_conflict")

    @staticmethod
    def _translate(error: Exception) -> McpManagedRuntimeError:
        if isinstance(error, McpManagedRuntimeError):
            return error
        if isinstance(error, McpManagedServerError):
            return McpManagedRuntimeError(error.code)
        return McpManagedRuntimeError("mcp_managed_runtime_unavailable")

    @staticmethod
    def _action_receipt_id(request_id: str) -> str:
        return hashlib.sha256(
            f"mcp-managed-host-action:{request_id}".encode("ascii")
        ).hexdigest()[:32]

    def _claim_tool_call(
        self,
        prepared: PreparedMcpManagedToolCall,
        *,
        approval_state: AgentToolApprovalState,
        claimed_at: datetime,
    ) -> None:
        claim = McpManagedToolCallClaim(
            call_id=prepared.call_id,
            app_run_digest=self._app_run_digest,
            management_id=prepared.management_id,
            project_id=prepared.project_id,
            session_id=prepared.session_id,
            turn_id=prepared.turn_id,
            host_instance_id=prepared.host_instance_id,
            tool_snapshot_id=prepared.tool_snapshot_id,
            tool_id=prepared.tool.tool_id,
            server_revision=prepared.server_revision,
            project_binding_revision=prepared.project_binding_revision,
            argument_digest=prepared.argument_digest,
            argument_bytes=prepared.argument_bytes,
            approval_digest=hashlib.sha256(
                prepared.approval_id.encode("ascii")
            ).hexdigest(),
            approval_state=approval_state,
            requested_at=prepared.requested_at,
            approval_expires_at=prepared.approval_expires_at,
            claimed_at=claimed_at,
        )
        try:
            claimed = self._receipts.claim_tool_call(claim)
        except McpManagedRuntimeError:
            raise
        except Exception:
            raise McpManagedRuntimeError("mcp_tool_claim_unavailable") from None
        if not claimed:
            raise McpManagedRuntimeError("mcp_tool_approval_replayed")

    def _active_cleanup(
        self,
        management_id: str,
        project_id: str,
    ) -> McpManagedHostCleanupEvidence | None:
        try:
            return self._receipts.get_active_cleanup_evidence(
                management_id,
                project_id,
            )
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_unavailable"
            ) from None

    @staticmethod
    def _cleanup_status(
        evidence: McpManagedHostCleanupEvidence,
    ) -> McpManagedHostStatus:
        block = evidence.block
        return McpManagedHostStatus(
            management_id=block.management_id,
            project_id=block.project_id,
            state="cleanup_required",
            reason="cleanup_unconfirmed",
            binding=evidence.binding,
            instance_id=block.instance_id,
            started_at=block.created_at,
            stopped_at=block.updated_at,
            last_transition_at=block.updated_at,
            process_started=block.process_started,
            cleanup_state="unconfirmed",
            host_lease_active=False,
            error_code="mcp_host_cleanup_unconfirmed",
        )

    def _record_cleanup(
        self,
        *,
        binding: McpManagedHostBinding,
        instance_id: str,
        process_started: bool,
        at: datetime,
    ) -> McpManagedHostCleanupEvidence:
        existing = self._active_cleanup(binding.management_id, binding.project_id)
        if existing is not None:
            if (
                existing.block.instance_id != instance_id
                or existing.binding != binding
            ):
                raise McpManagedRuntimeError("mcp_host_cleanup_block_conflict")
            return existing
        local = binding.transport == "stdio"
        if local and not process_started:
            raise McpManagedRuntimeError("mcp_host_cleanup_evidence_incomplete")
        evidence = McpManagedHostCleanupEvidence(
            block=McpManagedHostCleanupBlock(
                block_id=hashlib.sha256(
                    (
                        "mcp-managed-host-cleanup:"
                        f"{self._app_run_digest}:{instance_id}"
                    ).encode("ascii")
                ).hexdigest()[:32],
                management_id=binding.management_id,
                project_id=binding.project_id,
                instance_id=instance_id,
                app_run_digest=self._app_run_digest,
                binding_digest=mcp_managed_host_binding_digest(binding),
                reason=(
                    "local_process_cleanup_unconfirmed"
                    if local
                    else "remote_connection_cleanup_unconfirmed"
                ),
                state="active",
                process_started=process_started,
                cleanup_verified=False,
                lifecycle_actions_blocked=True,
                recovery_attempts=0,
                created_at=at,
                updated_at=at,
            ),
            binding=binding,
        )
        try:
            self._receipts.record_cleanup_evidence(evidence)
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_cleanup_evidence_unavailable"
            ) from None
        return evidence

    def _record_host_action(
        self,
        *,
        request_id: str,
        binding: McpManagedHostBinding,
        instance_id: str | None,
        action: Literal[
            "start",
            "stop",
            "revoke_project",
            "revoke_server",
            "health_revoke",
            "shutdown",
        ],
        outcome: Literal[
            "ready",
            "stopped",
            "refused",
            "failed",
            "cleanup_required",
        ],
        reason: Literal[
            "owner_start",
            "owner_stop",
            "project_revoked",
            "server_revoked",
            "health_failed",
            "app_shutdown",
            "start_refused",
            "start_failed",
            "cleanup_unconfirmed",
        ],
        requested_at: datetime,
        process_started: bool,
        cleanup_state: Literal[
            "not_applicable",
            "pending",
            "verified",
            "unconfirmed",
        ],
        error_code: str | None = None,
    ) -> McpManagedHostActionReceipt:
        receipt = McpManagedHostActionReceipt(
            receipt_id=self._action_receipt_id(request_id),
            request_id=request_id,
            management_id=binding.management_id,
            project_id=binding.project_id,
            instance_id=instance_id,
            app_run_digest=self._app_run_digest,
            binding_digest=mcp_managed_host_binding_digest(binding),
            execution_kind=(
                "local_native_process"
                if binding.transport == "stdio"
                else "reviewed_remote_connection"
            ),
            action=action,
            outcome=outcome,
            reason=reason,
            requested_at=requested_at,
            completed_at=self._clock(),
            process_started=process_started,
            cleanup_state=cleanup_state,
            host_ready=outcome == "ready",
            error_code=error_code,
        )
        try:
            self._receipts.record_host_action_receipt(receipt)
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_unavailable"
            ) from None
        return receipt

    def start(
        self,
        management_id: str,
        project_id: str,
        command: StartMcpManagedHost,
    ) -> McpManagedHostStatus:
        try:
            settled = self._receipts.get_host_action_receipt(command.request_id)
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_unavailable"
            ) from None
        if settled is not None:
            if (
                settled.action != "start"
                or settled.management_id != management_id
                or settled.project_id != project_id
            ):
                raise McpManagedRuntimeError("mcp_host_action_request_conflict")
            current = self.status(management_id, project_id)
            if (
                settled.outcome == "ready"
                and current.state == "ready"
                and current.instance_id == settled.instance_id
            ):
                return current
            raise McpManagedRuntimeError("mcp_host_action_request_already_settled")
        blocking = self._active_cleanup(management_id, project_id)
        if blocking is not None:
            raise McpManagedRuntimeError("mcp_host_cleanup_unconfirmed")

        requested_at = _utc(self._clock())
        binding: McpManagedHostBinding | None = None
        attempted = False
        try:
            preview = self._management.resolve_host_start_preview(
                management_id,
                project_id,
                expected_server_revision=command.expected_server_revision,
                expected_project_binding_revision=(
                    command.expected_project_binding_revision
                ),
                expected_tool_snapshot_id=command.expected_tool_snapshot_id,
            )
            if preview.preview_digest != command.preview_digest:
                raise McpManagedRuntimeError("mcp_managed_host_preview_conflict")
            binding = preview.binding
            connection = self._management.resolve_transient_host_connection(
                management_id,
                expected_revision=command.expected_server_revision,
            )
            snapshot = self._management.get_tool_snapshot(management_id)
            if snapshot.snapshot_id != command.expected_tool_snapshot_id:
                raise McpManagedRuntimeError("mcp_managed_host_tool_snapshot_conflict")
            # Close the resolver/start race before third-party code is entered.
            rebound = self._management.resolve_host_binding(
                management_id,
                project_id,
                expected_server_revision=command.expected_server_revision,
                expected_project_binding_revision=(
                    command.expected_project_binding_revision
                ),
                expected_tool_snapshot_id=command.expected_tool_snapshot_id,
            )
            if rebound != preview.binding:
                raise McpManagedRuntimeError("mcp_managed_host_binding_changed")
            binding = rebound
            attempted = True
            status = self._supervisor.start(
                rebound,
                connection,
                snapshot,
                deadline_seconds=command.deadline_seconds,
            )
            try:
                self._record_host_action(
                    request_id=command.request_id,
                    binding=rebound,
                    instance_id=status.instance_id,
                    action="start",
                    outcome="ready",
                    reason="owner_start",
                    requested_at=requested_at,
                    process_started=status.process_started,
                    cleanup_state=status.cleanup_state,
                )
            except McpManagedRuntimeError as receipt_error:
                if status.instance_id is not None:
                    try:
                        stopped = self._supervisor.stop(
                            management_id,
                            project_id,
                            StopMcpManagedHost(
                                request_id=hashlib.sha256(
                                    (
                                        "unreceipted-start-stop:"
                                        f"{command.request_id}"
                                    ).encode("ascii")
                                ).hexdigest()[:32],
                                expected_instance_id=status.instance_id,
                                deadline_seconds=command.deadline_seconds,
                            ),
                        )
                        if stopped.state == "cleanup_required":
                            self._record_cleanup(
                                binding=rebound,
                                instance_id=status.instance_id,
                                process_started=stopped.process_started,
                                at=_utc(self._clock()),
                            )
                    except Exception:
                        raise McpManagedRuntimeError(
                            "mcp_host_cleanup_unconfirmed"
                        ) from None
                raise receipt_error
            return status
        except Exception as error:
            normalized = self._translate(error)
            if normalized.code == "mcp_host_action_receipt_unavailable":
                raise normalized from None
            if binding is None:
                raise normalized from None
            try:
                current = self._supervisor.status(management_id, project_id)
            except Exception:
                current = None
            bound_status = (
                current
                if current is not None and current.binding == binding
                else None
            )
            instance_id = None if bound_status is None else bound_status.instance_id
            process_started = bool(
                bound_status is not None and bound_status.process_started
            )
            if (
                bound_status is not None
                and bound_status.state == "cleanup_required"
                and instance_id is not None
            ):
                self._record_cleanup(
                    binding=binding,
                    instance_id=instance_id,
                    process_started=process_started,
                    at=_utc(self._clock()),
                )
                outcome = "cleanup_required"
                reason = "cleanup_unconfirmed"
                cleanup_state = "unconfirmed"
            elif attempted:
                outcome = "failed"
                reason = "start_failed"
                cleanup_state = "verified" if process_started else "not_applicable"
            else:
                outcome = "refused"
                reason = "start_refused"
                instance_id = None
                process_started = False
                cleanup_state = "not_applicable"
            self._record_host_action(
                request_id=command.request_id,
                binding=binding,
                instance_id=instance_id,
                action="start",
                outcome=outcome,
                reason=reason,
                requested_at=requested_at,
                process_started=process_started,
                cleanup_state=cleanup_state,
                error_code=normalized.code,
            )
            raise normalized from None

    def _settle_host_stop(
        self,
        management_id: str,
        project_id: str,
        command: StopMcpManagedHost,
        *,
        action: Literal[
            "stop",
            "revoke_project",
            "revoke_server",
            "health_revoke",
            "shutdown",
        ],
        reason: Literal[
            "owner_stop",
            "project_revoked",
            "server_revoked",
            "health_failed",
            "app_shutdown",
        ],
    ) -> McpManagedHostStatus:
        try:
            settled = self._receipts.get_host_action_receipt(command.request_id)
        except Exception:
            raise McpManagedRuntimeError(
                "mcp_host_action_receipt_unavailable"
            ) from None
        if settled is not None:
            if (
                settled.action != action
                or settled.management_id != management_id
                or settled.project_id != project_id
            ):
                raise McpManagedRuntimeError("mcp_host_action_request_conflict")
            return self.status(management_id, project_id)
        blocking = self._active_cleanup(management_id, project_id)
        if blocking is not None:
            return self._cleanup_status(blocking)
        requested_at = _utc(self._clock())
        try:
            before = self._supervisor.status(management_id, project_id)
            status = self._supervisor.stop(management_id, project_id, command)
            if before.binding is None or before.instance_id is None:
                return status
            if status.state == "cleanup_required":
                self._record_cleanup(
                    binding=before.binding,
                    instance_id=before.instance_id,
                    process_started=status.process_started,
                    at=_utc(self._clock()),
                )
                self._record_host_action(
                    request_id=command.request_id,
                    binding=before.binding,
                    instance_id=before.instance_id,
                    action=action,
                    outcome="cleanup_required",
                    reason="cleanup_unconfirmed",
                    requested_at=requested_at,
                    process_started=status.process_started,
                    cleanup_state="unconfirmed",
                    error_code=status.error_code,
                )
            else:
                self._record_host_action(
                    request_id=command.request_id,
                    binding=before.binding,
                    instance_id=before.instance_id,
                    action=action,
                    outcome="stopped",
                    reason=reason,
                    requested_at=requested_at,
                    process_started=before.process_started,
                    cleanup_state=(
                        "verified" if before.process_started else "not_applicable"
                    ),
                )
            return status
        except Exception as error:
            normalized = self._translate(error)
            before_value = locals().get("before")
            if (
                isinstance(before_value, McpManagedHostStatus)
                and before_value.binding is not None
                and before_value.instance_id is not None
                and (
                    before_value.binding.transport != "stdio"
                    or before_value.process_started
                )
            ):
                self._record_cleanup(
                    binding=before_value.binding,
                    instance_id=before_value.instance_id,
                    process_started=before_value.process_started,
                    at=_utc(self._clock()),
                )
                self._record_host_action(
                    request_id=command.request_id,
                    binding=before_value.binding,
                    instance_id=before_value.instance_id,
                    action=action,
                    outcome="cleanup_required",
                    reason="cleanup_unconfirmed",
                    requested_at=requested_at,
                    process_started=before_value.process_started,
                    cleanup_state="unconfirmed",
                    error_code="mcp_host_cleanup_unconfirmed",
                )
                raise McpManagedRuntimeError(
                    "mcp_host_cleanup_unconfirmed"
                ) from None
            raise normalized from None

    def stop(
        self,
        management_id: str,
        project_id: str,
        command: StopMcpManagedHost,
    ) -> McpManagedHostStatus:
        return self._settle_host_stop(
            management_id,
            project_id,
            command,
            action="stop",
            reason="owner_stop",
        )

    def revoke_project_host(
        self,
        management_id: str,
        project_id: str,
        *,
        request_id: str,
        deadline_seconds: float = 20.0,
    ) -> McpManagedHostStatus:
        current = self.status(management_id, project_id)
        if current.state in {"not_started", "cleanup_required"}:
            return current
        return self._settle_host_stop(
            management_id,
            project_id,
            StopMcpManagedHost(
                request_id=request_id,
                expected_instance_id=current.instance_id,
                deadline_seconds=deadline_seconds,
            ),
            action="revoke_project",
            reason="project_revoked",
        )

    def revoke_server_hosts(
        self,
        management_id: str,
        *,
        request_id: str,
        deadline_seconds: float = 20.0,
    ) -> tuple[McpManagedHostStatus, ...]:
        try:
            active = tuple(
                status
                for status in self._supervisor.statuses()
                if status.management_id == management_id
                and status.state not in {"not_started", "cleanup_required"}
            )
        except Exception as error:
            raise self._translate(error) from None
        settled: list[McpManagedHostStatus] = []
        for status in sorted(active, key=lambda item: item.project_id):
            derived_request_id = hashlib.sha256(
                (
                    "mcp-managed-host-server-revoke:"
                    f"{request_id}:{status.project_id}"
                ).encode("ascii")
            ).hexdigest()[:32]
            settled.append(
                self._settle_host_stop(
                    management_id,
                    status.project_id,
                    StopMcpManagedHost(
                        request_id=derived_request_id,
                        expected_instance_id=status.instance_id,
                        deadline_seconds=deadline_seconds,
                    ),
                    action="revoke_server",
                    reason="server_revoked",
                )
            )
        return tuple(settled)

    def status(self, management_id: str, project_id: str) -> McpManagedHostStatus:
        try:
            blocking = self._active_cleanup(management_id, project_id)
            if blocking is not None:
                return self._cleanup_status(blocking)
            return self._supervisor.status(management_id, project_id)
        except Exception as error:
            raise self._translate(error) from None

    def project_tools(self, project_id: str) -> McpManagedProjectRuntime:
        try:
            ready = tuple(
                status
                for status in self._supervisor.statuses()
                if status.project_id == project_id and status.state == "ready"
            )
            current_ready: list[McpManagedHostStatus] = []
            tools: list[McpManagedReadyTool] = []
            for status in ready:
                binding = status.binding
                instance_id = status.instance_id
                if binding is None or instance_id is None:
                    raise McpManagedRuntimeError("mcp_managed_host_status_invalid")
                if self._active_cleanup(binding.management_id, project_id) is not None:
                    continue
                try:
                    current_binding = self._management.resolve_host_binding(
                        binding.management_id,
                        project_id,
                        expected_server_revision=binding.server_revision,
                        expected_project_binding_revision=(
                            binding.project_binding_revision
                        ),
                        expected_tool_snapshot_id=binding.tool_snapshot_id,
                    )
                except Exception:
                    # A read never starts or stops a host. It does, however, fail
                    # closed immediately when durable authority has changed.
                    continue
                if current_binding != binding:
                    continue
                server = self._management.get(binding.management_id)
                snapshot = self._management.get_tool_snapshot(binding.management_id)
                if snapshot.snapshot_id != binding.tool_snapshot_id:
                    continue
                current_ready.append(status)
                admitted = set(binding.admitted_tool_ids)
                tools.extend(
                    McpManagedReadyTool(
                        management_id=binding.management_id,
                        project_id=project_id,
                        host_instance_id=instance_id,
                        server_title=server.server_title,
                        tool_id=tool.tool_id,
                        name=tool.name,
                        model_alias=tool.model_alias,
                        title=tool.title,
                        description=tool.description,
                        model_input_schema=tool.model_input_schema,
                    )
                    for tool in snapshot.tools
                    if tool.tool_id in admitted
                )
            tools.sort(key=lambda item: (item.server_title.casefold(), item.model_alias))
            aliases = [item.model_alias.casefold() for item in tools]
            if len(aliases) != len(set(aliases)):
                raise McpManagedRuntimeError("mcp_tool_alias_collision")
            return McpManagedProjectRuntime(
                project_id=project_id,
                ready_host_count=len(current_ready),
                ready_tool_count=len(tools),
                tools=tuple(tools),
            )
        except Exception as error:
            raise self._translate(error) from None

    def model_tool_schemas(self, project_id: str) -> tuple[dict[str, Any], ...]:
        runtime = self.project_tools(project_id)
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": tool.model_alias,
                    "description": (
                        f"MCP server {tool.server_title}: "
                        + (tool.description or tool.title or "Owner-admitted external tool.")
                        + " Every call requires a fresh native approval."
                    )[:4_096],
                    "parameters": tool.model_input_schema,
                },
            }
            for tool in runtime.tools
        )

    def prepare_tool_call(
        self,
        *,
        project_id: str,
        session_id: str,
        turn_id: str,
        model_alias: str,
        arguments: Mapping[str, Any],
        deadline_seconds: float = MAX_MCP_MANAGED_CALL_SECONDS,
    ) -> PreparedMcpManagedToolCall:
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or not 0.1 <= float(deadline_seconds) <= MAX_MCP_MANAGED_CALL_SECONDS
        ):
            raise McpManagedRuntimeError("mcp_tool_deadline_invalid")
        runtime = self.project_tools(project_id)
        candidates = [tool for tool in runtime.tools if tool.model_alias == model_alias]
        if len(candidates) != 1:
            raise McpManagedRuntimeError("mcp_tool_not_admitted")
        ready_tool = candidates[0]
        status = self._supervisor.status(ready_tool.management_id, project_id)
        binding = status.binding
        if (
            status.state != "ready"
            or status.instance_id != ready_tool.host_instance_id
            or binding is None
        ):
            raise McpManagedRuntimeError("mcp_tool_host_not_ready")
        snapshot = self._management.get_tool_snapshot(ready_tool.management_id)
        tool = next(
            (item for item in snapshot.tools if item.tool_id == ready_tool.tool_id),
            None,
        )
        if (
            tool is None
            or snapshot.snapshot_id != binding.tool_snapshot_id
            or tool.tool_id not in binding.admitted_tool_ids
        ):
            raise McpManagedRuntimeError("mcp_tool_admission_stale")
        detached, argument_digest, argument_bytes = validate_mcp_tool_arguments(
            arguments,
            tool.input_schema,
        )
        requested_at = _utc(self._clock())
        call_id = secrets.token_hex(16)
        approval_id = secrets.token_hex(16)
        approval_expires_at = requested_at + timedelta(
            seconds=MAX_MCP_MANAGED_APPROVAL_SECONDS
        )
        preview = (
            f"Allow one MCP tool call\nServer: {ready_tool.server_title}\n"
            f"Tool: {tool.title or tool.name}\nAlias: {tool.model_alias}\n"
            f"Project scope: this Agent project only\n"
            f"Permissions: {', '.join(binding.granted_permissions) or 'none declared'}\n"
            "Approval: one call only; never remembered; expires in 30 minutes\n"
            "Arguments (secret-like fields redacted):\n"
            + _redacted_preview(detached)
        )
        prepared = PreparedMcpManagedToolCall(
            app_run_digest=self._app_run_digest,
            preparation_digest="0" * 64,
            call_id=call_id,
            management_id=ready_tool.management_id,
            project_id=project_id,
            session_id=session_id,
            turn_id=turn_id,
            host_instance_id=ready_tool.host_instance_id,
            server_title=ready_tool.server_title,
            server_revision=binding.server_revision,
            project_binding_revision=binding.project_binding_revision,
            tool_snapshot_id=binding.tool_snapshot_id,
            tool=tool,
            arguments=detached,
            argument_digest=argument_digest,
            argument_bytes=argument_bytes,
            requested_at=requested_at,
            approval_id=approval_id,
            approval_expires_at=approval_expires_at,
            deadline_seconds=float(deadline_seconds),
            preview=preview,
        )
        return replace(
            prepared,
            preparation_digest=self._preparation_digest(prepared),
        )

    def settle_tool_call(
        self,
        prepared: PreparedMcpManagedToolCall,
        *,
        approval_state: AgentToolApprovalState,
        cancelled: threading.Event,
    ) -> McpManagedCallProjection:
        # Validate the memory-only runtime/client binding before a durable
        # one-use claim is written.  A foreign or modified prepared object may
        # neither consume this run's approval nor reach a host.
        self._validate_preparation_scope(prepared)
        completed_at = _utc(self._clock())
        if approval_state not in {
            "approved",
            "denied",
            "timed_out",
            "cancelled_before_decision",
        }:
            approval_state = "denied"
        if (
            approval_state == "approved"
            and completed_at > prepared.approval_expires_at
        ):
            approval_state = "timed_out"
        self._claim_tool_call(
            prepared,
            approval_state=approval_state,
            claimed_at=completed_at,
        )
        if approval_state != "approved":
            outcome = {
                "timed_out": "timed_out",
                "cancelled_before_decision": "cancelled",
            }.get(approval_state, "denied")
            projection = McpManagedCallProjection(
                call_id=prepared.call_id,
                outcome=("cancelled" if outcome == "cancelled" else "timed_out" if outcome == "timed_out" else "failed"),
                text=(
                    "MCP call cancelled before execution."
                    if outcome == "cancelled"
                    else "MCP call approval timed out; nothing was invoked."
                    if outcome == "timed_out"
                    else "MCP call was not approved; nothing was invoked."
                ),
                result_bytes=len(
                    (
                        "MCP call cancelled before execution."
                        if outcome == "cancelled"
                        else "MCP call approval timed out; nothing was invoked."
                        if outcome == "timed_out"
                        else "MCP call was not approved; nothing was invoked."
                    ).encode("utf-8")
                ),
                error_code=(
                    "mcp_tool_cancelled"
                    if outcome == "cancelled"
                    else "mcp_tool_approval_timed_out"
                    if outcome == "timed_out"
                    else "mcp_tool_not_approved"
                ),
                content_mode="none",
                cleanup_verified=True,
            )
            self._record_receipt(
                prepared,
                approval_state=approval_state,
                outcome=outcome,
                projection=projection,
                completed_at=completed_at,
            )
            return projection

        try:
            binding = self._management.resolve_host_binding(
                prepared.management_id,
                prepared.project_id,
                expected_server_revision=prepared.server_revision,
                expected_project_binding_revision=prepared.project_binding_revision,
                expected_tool_snapshot_id=prepared.tool_snapshot_id,
            )
            status = self._supervisor.status(
                prepared.management_id,
                prepared.project_id,
            )
            if (
                status.state != "ready"
                or status.instance_id != prepared.host_instance_id
                or status.binding != binding
            ):
                raise McpManagedRuntimeError("mcp_tool_host_not_ready")
            snapshot = self._management.get_tool_snapshot(prepared.management_id)
            current_tool = next(
                (item for item in snapshot.tools if item.tool_id == prepared.tool.tool_id),
                None,
            )
            if (
                current_tool != prepared.tool
                or snapshot.snapshot_id != prepared.tool_snapshot_id
                or current_tool.tool_id not in binding.admitted_tool_ids
            ):
                raise McpManagedRuntimeError("mcp_tool_admission_stale")
            detached, digest, byte_count = validate_mcp_tool_arguments(
                prepared.arguments,
                current_tool.input_schema,
            )
            if digest != prepared.argument_digest or byte_count != prepared.argument_bytes:
                raise McpManagedRuntimeError("mcp_tool_arguments_changed")
            projection = self._supervisor.call_tool(
                management_id=prepared.management_id,
                project_id=prepared.project_id,
                instance_id=prepared.host_instance_id,
                call_id=prepared.call_id,
                tool_name=current_tool.name,
                arguments=detached,
                output_schema=current_tool.output_schema,
                deadline_seconds=prepared.deadline_seconds,
                cancelled=cancelled,
            )
        except Exception as error:
            normalized = self._translate(error)
            projection = McpManagedCallProjection(
                call_id=prepared.call_id,
                outcome=("cancelled" if normalized.code == "mcp_tool_cancelled" else "timed_out" if normalized.code == "mcp_tool_deadline_exceeded" else "failed"),
                text=normalized.code.replace("_", " "),
                result_bytes=len(normalized.code.replace("_", " ").encode("utf-8")),
                error_code=normalized.code,
                content_mode="none",
                cleanup_verified=normalized.code != "mcp_host_cleanup_unconfirmed",
            )
        self._record_receipt(
            prepared,
            approval_state=approval_state,
            outcome=(
                "succeeded"
                if projection.outcome == "succeeded"
                else "tool_error"
                if projection.outcome == "tool_error"
                else "cancelled"
                if projection.outcome == "cancelled"
                else "timed_out"
                if projection.outcome == "timed_out"
                else "failed"
            ),
            projection=projection,
            completed_at=self._clock(),
        )
        return projection

    def _record_receipt(
        self,
        prepared: PreparedMcpManagedToolCall,
        *,
        approval_state: AgentToolApprovalState,
        outcome: Literal["denied", "timed_out", "cancelled", "succeeded", "tool_error", "failed"],
        projection: McpManagedCallProjection,
        completed_at: datetime,
    ) -> None:
        receipt = McpManagedToolCallReceipt(
            call_id=prepared.call_id,
            management_id=prepared.management_id,
            project_id=prepared.project_id,
            session_id=prepared.session_id,
            turn_id=prepared.turn_id,
            host_instance_id=prepared.host_instance_id,
            tool_snapshot_id=prepared.tool_snapshot_id,
            tool_id=prepared.tool.tool_id,
            server_revision=prepared.server_revision,
            project_binding_revision=prepared.project_binding_revision,
            argument_digest=prepared.argument_digest,
            argument_bytes=prepared.argument_bytes,
            approval_state=approval_state,
            outcome=outcome,
            error_code=projection.error_code if outcome == "failed" else None,
            requested_at=prepared.requested_at,
            completed_at=completed_at,
            result_bytes=(projection.result_bytes if outcome in {"succeeded", "tool_error"} else 0),
            result_digest=(projection.result_digest if outcome in {"succeeded", "tool_error"} else None),
            cleanup_verified=projection.cleanup_verified,
        )
        try:
            self._receipts.record_tool_call_receipt(receipt)
        except Exception:
            raise McpManagedRuntimeError("mcp_tool_receipt_unavailable") from None

    def shutdown(self) -> None:
        self._supervisor.shutdown()


__all__ = (
    "MCP_MANAGED_RUNTIME_CONTRACT_VERSION",
    "MAX_MCP_MANAGED_APPROVAL_SECONDS",
    "MAX_MCP_MANAGED_ARGUMENT_BYTES",
    "MAX_MCP_MANAGED_CALL_SECONDS",
    "MAX_MCP_MANAGED_RESULT_BYTES",
    "MAX_MCP_MANAGED_RESULT_COLLECTION_ITEMS",
    "MAX_MCP_MANAGED_RESULT_CONTENT_ITEMS",
    "MAX_MCP_MANAGED_RESULT_DEPTH",
    "MAX_MCP_MANAGED_RESULT_NODES",
    "McpManagedCallProjection",
    "McpManagedHostCleanupEvidence",
    "McpManagedHostSupervisorPort",
    "McpManagedProjectRuntime",
    "McpManagedReadyTool",
    "McpManagedRuntimeError",
    "McpManagedRuntimeReceiptRepository",
    "McpManagedRuntimeService",
    "McpManagedToolCallClaim",
    "McpManagedToolCallReceipt",
    "PreparedMcpManagedToolCall",
    "validate_mcp_tool_arguments",
    "validate_mcp_tool_result",
)
