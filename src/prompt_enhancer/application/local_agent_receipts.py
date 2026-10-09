"""Source-labelled receipts for Agent turns and reviewed writes.

Runtime counts are reported observations, not token estimates or task grades.
Missing counters stay unknown, including when only some requests report usage.
Chats using explicit local-history retention may persist these bounded receipts.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal
import unicodedata

from pydantic import Field, field_validator, model_validator

from ..domain import StrictModel
from .local_agent_limits import MAX_FILE_WRITE_BYTES, MAX_STEPS_PER_TURN, MAX_TOOL_CALLS_PER_REPLY


MAX_COUNTER = 9_007_199_254_740_991
MAX_TURN_TOOLS = MAX_STEPS_PER_TURN * MAX_TOOL_CALLS_PER_REPLY
MAX_AGENT_MCP_RESULT_BYTES = 128 * 1024
AgentToolState = Literal["succeeded", "failed", "not_approved", "cancelled", "unverified"]
AgentToolApprovalState = Literal[
    "not_required",
    "not_requested",
    "approved",
    "denied",
    "timed_out",
    "cancelled_before_decision",
]
AgentToolEvidenceState = Literal[
    "read_only_observation",
    "verified_workspace_effect",
    "unverified_workspace_effect",
    "untracked_external_effect",
    "no_effect",
    "unknown",
]
TurnReason = Literal[
    "answer_complete", "stop_requested", "step_limit", "model_response_limit",
    "model_response_filtered", "model_completion_unrecognized", "model_stream_incomplete",
    "model_stream_failed", "model_reply_unusable", "model_reply_too_large",
    "model_answer_missing", "runtime_unreachable", "runtime_http_error", "turn_failed",
    "command_cleanup_unconfirmed", "context_window_exceeded", "inference_not_authorized",
]


class AgentToolExecutionReceipt(StrictModel):
    """Content-free terminal facts for one action request.

    Elapsed time spans the tool call event through its terminal result and may
    therefore include time spent waiting for native approval. It is never
    inferred from wall-clock event timestamps.
    """

    contract_version: Literal["agent-tool-execution.v1"] = (
        "agent-tool-execution.v1"
    )
    elapsed_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timing_source: Literal["server_monotonic.v1"] = "server_monotonic.v1"
    approval_state: AgentToolApprovalState
    evidence_state: AgentToolEvidenceState

    @model_validator(mode="after")
    def coherent_authority_and_evidence(self) -> "AgentToolExecutionReceipt":
        no_execution = {
            "not_requested",
            "denied",
            "timed_out",
            "cancelled_before_decision",
        }
        protected_effects = {
            "verified_workspace_effect",
            "unverified_workspace_effect",
            "untracked_external_effect",
        }
        if self.approval_state in no_execution and self.evidence_state != "no_effect":
            raise ValueError("an unexecuted action cannot claim an effect")
        if (
            self.evidence_state in protected_effects
            and self.approval_state != "approved"
        ):
            raise ValueError("protected effects require recorded approval")
        if (
            self.evidence_state == "read_only_observation"
            and self.approval_state != "not_required"
        ):
            raise ValueError("read-only evidence cannot claim protected authority")
        if self.approval_state == "not_required" and self.evidence_state not in {
            "read_only_observation",
            "no_effect",
        }:
            raise ValueError("unprotected tools cannot claim protected effects")
        return self


class AgentMcpToolDescriptor(StrictModel):
    """Safe display identity for one exact managed MCP tool.

    Project, host, endpoint, argument and credential material is deliberately
    absent so this descriptor may be retained with local Agent history.
    """

    contract_version: Literal["agent-mcp-tool.v1"] = "agent-mcp-tool.v1"
    source: Literal["managed_mcp"] = "managed_mcp"
    server_title: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=128)
    tool_title: str | None = Field(default=None, min_length=1, max_length=256)
    model_alias: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    every_call_requires_native_approval: Literal[True] = True

    @field_validator("server_title", "tool_name", "tool_title")
    @classmethod
    def safe_display_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip() != value or any(
            unicodedata.category(character) in {"Cc", "Cf"}
            for character in value
        ):
            raise ValueError("managed MCP display identity is unsafe")
        return value


class AgentMcpToolResultReceipt(StrictModel):
    """Content-free terminal evidence projected into the Agent timeline."""

    contract_version: Literal["agent-mcp-tool-result.v1"] = (
        "agent-mcp-tool-result.v1"
    )
    managed_call_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    outcome: Literal[
        "not_invoked",
        "succeeded",
        "tool_error",
        "failed",
        "cancelled",
        "timed_out",
    ]
    content_mode: Literal[
        "text",
        "structured_json",
        "text_and_structured_json",
        "none",
    ]
    result_bytes: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_MCP_RESULT_BYTES,
    )
    result_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{2,95}$",
    )
    cleanup_verified: bool = Field(strict=True)
    arguments_persisted: Literal[False] = False
    result_text_persisted: Literal[False] = False
    reusable_approval_persisted: Literal[False] = False

    @model_validator(mode="after")
    def coherent_result(self) -> "AgentMcpToolResultReceipt":
        completed = self.outcome in {"succeeded", "tool_error"}
        failed = self.outcome in {"failed", "cancelled", "timed_out"}
        if completed != (self.result_digest is not None):
            raise ValueError("managed MCP result digest is incoherent")
        if failed != (self.error_code is not None):
            raise ValueError("managed MCP result error evidence is incoherent")
        if self.outcome == "not_invoked" and (
            self.content_mode != "none"
            or self.result_bytes != 0
            or self.result_digest is not None
            or self.error_code is not None
            or not self.cleanup_verified
        ):
            raise ValueError("an uninvoked managed MCP tool cannot claim a result")
        return self


class AgentWriteReceipt(StrictModel):
    contract_version: Literal["agent-write.v1"] = "agent-write.v1"
    source: Literal["reviewed_write_file"] = "reviewed_write_file"
    path: str = Field(min_length=1, max_length=1024)
    state: Literal["verified", "unverified"]
    operation: Literal["created", "modified", "unchanged"] | None = None
    before_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    added_lines: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    removed_lines: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES + 1)
    byte_size: int | None = Field(default=None, strict=True, ge=0, le=MAX_FILE_WRITE_BYTES)
    line_count_version: Literal["line-sequence-diff.v1"] = "line-sequence-diff.v1"

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        windows, posix = PureWindowsPath(value), PurePosixPath(value)
        if (value in {".", ".."} or windows.drive or windows.root or posix.is_absolute()
                or any(part in {"", ".", ".."} for part in value.split("/")) or "\\" in value
                or ":" in value or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError("invalid workspace receipt path")
        return value

    @model_validator(mode="after")
    def coherent_effect(self) -> "AgentWriteReceipt":
        facts = (self.operation, self.after_sha256, self.added_lines, self.removed_lines, self.byte_size)
        if self.state == "unverified":
            if any(value is not None for value in facts):
                raise ValueError("unverified write cannot claim a verified effect")
        elif any(value is None for value in facts):
            raise ValueError("verified write requires complete effect metadata")
        elif ((self.operation == "created") != (self.before_sha256 is None)
              or (self.operation == "unchanged") != (self.before_sha256 == self.after_sha256)
              or (self.operation == "unchanged" and (self.added_lines != 0 or self.removed_lines != 0))):
            raise ValueError("write operation does not match its revisions")
        return self


class AgentTokenUsage(StrictModel):
    contract_version: Literal["agent-token-usage.v1"] = "agent-token-usage.v1"
    source: Literal["runtime_reported"] = "runtime_reported"
    state: Literal["reported", "partial", "unavailable", "invalid"]
    model_requests: int = Field(strict=True, ge=0, le=MAX_STEPS_PER_TURN)
    reported_requests: int = Field(strict=True, ge=0, le=MAX_STEPS_PER_TURN)
    prompt_tokens: int | None = Field(default=None, strict=True, ge=0, le=MAX_COUNTER)
    completion_tokens: int | None = Field(default=None, strict=True, ge=0, le=MAX_COUNTER)
    total_tokens: int | None = Field(default=None, strict=True, ge=0, le=MAX_COUNTER)
    cached_prompt_tokens: int | None = Field(default=None, strict=True, ge=0, le=MAX_COUNTER)
    reasoning_tokens: int | None = Field(default=None, strict=True, ge=0, le=MAX_COUNTER)

    @model_validator(mode="after")
    def coherent_usage(self) -> "AgentTokenUsage":
        values = (self.prompt_tokens, self.completion_tokens, self.total_tokens,
                  self.cached_prompt_tokens, self.reasoning_tokens)
        if self.reported_requests > self.model_requests:
            raise ValueError("usage coverage exceeds issued requests")
        if self.state == "reported" and (self.model_requests == 0 or self.reported_requests != self.model_requests or any(value is None for value in values[:3])):
            raise ValueError("reported usage requires every request")
        if self.state in {"unavailable", "invalid"} and any(value is not None for value in values):
            raise ValueError("unavailable usage cannot carry counts")
        if self.state == "unavailable" and self.reported_requests != 0:
            raise ValueError("unavailable usage cannot claim complete requests")
        if self.state == "partial" and (self.model_requests == 0 or self.reported_requests == self.model_requests or all(value is not None for value in values[:3])):
            raise ValueError("partial usage must leave request coverage incomplete")
        if self.total_tokens is not None and any(value is not None and value > self.total_tokens for value in values[:2]):
            raise ValueError("usage part exceeds total")
        if self.prompt_tokens is not None and self.completion_tokens is not None and self.total_tokens is not None:
            if self.prompt_tokens + self.completion_tokens != self.total_tokens:
                raise ValueError("usage totals do not agree")
        for part, whole in ((self.cached_prompt_tokens, self.prompt_tokens), (self.reasoning_tokens, self.completion_tokens)):
            if part is not None and whole is not None and part > whole:
                raise ValueError("usage detail exceeds its parent")
        return self


class AgentTurnSummary(StrictModel):
    contract_version: Literal["agent-turn.v1"] = "agent-turn.v1"
    turn_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    turn_number: int = Field(strict=True, ge=1)
    model_alias: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "stopped", "failed", "step_limit"]
    reason: TurnReason
    started_at: datetime
    finished_at: datetime
    duration_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_wait_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    time_to_first_text_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timing_source: Literal["server_monotonic.v1"] = "server_monotonic.v1"
    usage: AgentTokenUsage
    tools_requested: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    tools_succeeded: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    tools_failed: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    tools_not_approved: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    tools_cancelled: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    tools_unverified: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    untracked_command_calls: int = Field(strict=True, ge=0, le=MAX_TURN_TOOLS)
    writes: tuple[AgentWriteReceipt, ...] = Field(max_length=MAX_TURN_TOOLS)

    @model_validator(mode="after")
    def coherent_turn(self) -> "AgentTurnSummary":
        if self.tools_requested != sum((self.tools_succeeded, self.tools_failed, self.tools_not_approved, self.tools_cancelled, self.tools_unverified)):
            raise ValueError("tool receipt counts do not agree")
        if self.untracked_command_calls + len(self.writes) > self.tools_requested:
            raise ValueError("tool effects exceed requests")
        if (sum(write.state == "verified" for write in self.writes) > self.tools_succeeded
                or sum(write.state == "unverified" for write in self.writes) > self.tools_unverified):
            raise ValueError("write receipts exceed matching tool outcomes")
        statuses = {"answer_complete": "completed", "stop_requested": "stopped", "step_limit": "step_limit"}
        if self.status != statuses.get(self.reason, "failed"):
            raise ValueError("turn termination reason does not match status")
        if self.duration_ms is not None and any(value is not None and value > self.duration_ms + 0.001 for value in (self.model_wait_ms, self.time_to_first_text_ms)):
            raise ValueError("timing component exceeds turn duration")
        return self


@dataclass(frozen=True)
class RuntimeUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    reasoning_tokens: int | None = None
    invalid: bool = False

    @property
    def complete(self) -> bool:
        return not self.invalid and all(value is not None for value in (self.prompt_tokens, self.completion_tokens, self.total_tokens))


def runtime_usage(value: object) -> RuntimeUsage:
    """Accept only coherent reported integers; never estimate missing counters."""
    if value is None:
        return RuntimeUsage()
    if not isinstance(value, dict):
        return RuntimeUsage(invalid=True)
    try:
        def counter(data: dict, name: str) -> int | None:
            number = data.get(name)
            if number is not None and (type(number) is not int or not 0 <= number <= MAX_COUNTER):
                raise ValueError("invalid usage count")
            return number

        prompt, completion, total = (counter(value, name) for name in ("prompt_tokens", "completion_tokens", "total_tokens"))
        details = []
        for key, field in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
            nested = value.get(key)
            if nested is not None and not isinstance(nested, dict):
                raise ValueError("invalid usage details")
            details.append(counter(nested or {}, field))
        cached, reasoning = details
        if (total is not None and ((prompt is not None and total < prompt) or (completion is not None and total < completion)
                                  or (prompt is not None and completion is not None and total != prompt + completion))
                or cached is not None and prompt is not None and cached > prompt
                or reasoning is not None and completion is not None and reasoning > completion):
            raise ValueError("incoherent usage")
        return RuntimeUsage(prompt, completion, total, cached, reasoning)
    except (ValueError, TypeError):
        return RuntimeUsage(invalid=True)


def _elapsed(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    value = (end - start) * 1000
    return value if math.isfinite(value) else None


class ToolExecutionReceiptBuilder:
    """Measure one action without retaining arguments, output, or authority."""

    def __init__(self, *, monotonic: Callable[[], float]):
        self._monotonic = monotonic
        self._start = self._now()

    def _now(self) -> float | None:
        try:
            value = self._monotonic()
            return (
                float(value)
                if type(value) in (int, float) and math.isfinite(value)
                else None
            )
        except Exception:
            return None

    def finish(
        self,
        *,
        approval_state: AgentToolApprovalState,
        evidence_state: AgentToolEvidenceState,
    ) -> AgentToolExecutionReceipt:
        return AgentToolExecutionReceipt(
            elapsed_ms=_elapsed(self._start, self._now()),
            approval_state=approval_state,
            evidence_state=evidence_state,
        )


class TurnReceiptBuilder:
    """One worker owns these bounded metadata; no evidence text is retained."""
    def __init__(self, *, turn_id: str, turn_number: int, model_alias: str, started_at: datetime, monotonic: Callable[[], float]):
        self.turn_id, self.turn_number, self.model_alias = turn_id, turn_number, model_alias
        self.started_at, self._monotonic = started_at, monotonic
        self._start = self._now()
        self._request_start: float | None = None
        self._first_text: float | None = None
        self._saw_text = False
        self._usage: list[RuntimeUsage] = []
        self._waits: list[float | None] = []
        self._tools: dict[AgentToolState, int] = {key: 0 for key in ("succeeded", "failed", "not_approved", "cancelled", "unverified")}
        self._writes: list[AgentWriteReceipt] = []
        self._commands = 0

    def _now(self) -> float | None:
        try:
            value = self._monotonic()
            return float(value) if type(value) in (int, float) and math.isfinite(value) else None
        except Exception:
            return None

    def begin_request(self) -> None:
        self._request_start = self._now()

    def end_request(self, usage: RuntimeUsage | None) -> None:
        self._waits.append(_elapsed(self._request_start, self._now()))
        self._usage.append(usage or RuntimeUsage())

    def observe_text(self) -> None:
        if not self._saw_text:
            self._saw_text = True
            self._first_text = _elapsed(self._start, self._now())

    def tool(self, state: AgentToolState, write: AgentWriteReceipt | None, untracked_command: bool) -> None:
        self._tools[state] += 1
        self._commands += int(untracked_command)
        if write is not None:
            self._writes.append(write)

    def finish(self, *, status: str, reason: str, finished_at: datetime) -> AgentTurnSummary:
        counts = {}
        for field in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_prompt_tokens", "reasoning_tokens"):
            values = [getattr(item, field) for item in self._usage]
            counts[field] = sum(values) if values and all(value is not None for value in values) else None
        invalid = any(item.invalid for item in self._usage) or any(value is not None and value > MAX_COUNTER for value in counts.values())
        reported = sum(item.complete for item in self._usage)
        state = "invalid" if invalid else "reported" if self._usage and reported == len(self._usage) else "partial" if any(any(getattr(item, field) is not None for field in counts) for item in self._usage) else "unavailable"
        if invalid:
            counts = {field: None for field in counts}
        duration = _elapsed(self._start, self._now())
        wait = sum(self._waits) if self._waits and all(value is not None for value in self._waits) else None
        if wait is not None and not math.isfinite(wait):
            wait = None
        if duration is not None and wait is not None and wait > duration:
            wait = None
        first_text = self._first_text if duration is None or self._first_text is None or self._first_text <= duration else None
        return AgentTurnSummary(
            turn_id=self.turn_id, turn_number=self.turn_number, model_alias=self.model_alias,
            status=status, reason=reason, started_at=self.started_at, finished_at=finished_at,
            duration_ms=duration, model_wait_ms=wait, time_to_first_text_ms=first_text,
            usage=AgentTokenUsage(state=state, model_requests=len(self._usage), reported_requests=reported, **counts),
            tools_requested=sum(self._tools.values()), tools_succeeded=self._tools["succeeded"],
            tools_failed=self._tools["failed"], tools_not_approved=self._tools["not_approved"],
            tools_cancelled=self._tools["cancelled"], tools_unverified=self._tools["unverified"],
            untracked_command_calls=self._commands, writes=tuple(self._writes),
        )
