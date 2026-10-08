"""Synthetic metadata invariants: unknown values, bounded counts and write proof."""
from datetime import UTC, datetime
import os
import subprocess

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.local_agent_receipts import (
    AgentMcpToolDescriptor,
    AgentMcpToolResultReceipt,
    AgentTokenUsage,
    AgentToolExecutionReceipt,
    AgentTurnSummary,
    AgentWriteReceipt,
    MAX_AGENT_MCP_RESULT_BYTES,
    MAX_COUNTER,
    ToolExecutionReceiptBuilder,
    TurnReceiptBuilder,
    runtime_usage,
)
from prompt_enhancer.application.local_agent_workspace import WorkspaceTools


NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _builder(monotonic=lambda: 10.0):
    return TurnReceiptBuilder(turn_id="a" * 32, turn_number=1, model_alias="example-model", started_at=NOW, monotonic=monotonic)


def _finish(builder):
    return builder.finish(status="completed", reason="answer_complete", finished_at=NOW)


def test_aggregate_counts_require_all_requests_and_never_infer_missing_total():
    builder = _builder()
    for payload in ({"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}, {"completion_tokens": 7}):
        builder.begin_request()
        builder.end_request(runtime_usage(payload))
    usage = _finish(builder).usage
    assert usage.state == "partial" and usage.reported_requests == 1 and usage.model_requests == 2
    assert usage.completion_tokens == 10
    assert usage.prompt_tokens is usage.total_tokens is None
    assert runtime_usage({"prompt_tokens": 2, "completion_tokens": 3}).total_tokens is None


def test_reported_zero_and_optional_detail_counts_remain_observations():
    builder = _builder()
    builder.begin_request()
    builder.end_request(runtime_usage({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                                      "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}}))
    receipt = _finish(builder)
    assert receipt.usage.state == "reported"
    assert receipt.usage.prompt_tokens == receipt.usage.completion_tokens == receipt.usage.total_tokens == 0
    assert receipt.usage.cached_prompt_tokens == receipt.usage.reasoning_tokens == 0
    assert receipt.duration_ms == receipt.model_wait_ms == 0
    assert receipt.time_to_first_text_ms is None


def test_overflow_invalidates_turn_usage_instead_of_truncating_it():
    builder = _builder()
    for _ in range(2):
        builder.begin_request()
        builder.end_request(runtime_usage({"prompt_tokens": MAX_COUNTER, "completion_tokens": 0, "total_tokens": MAX_COUNTER}))
    receipt = _finish(builder)
    assert receipt.usage.state == "invalid" and receipt.usage.reported_requests == 2
    assert receipt.usage.prompt_tokens is receipt.usage.completion_tokens is receipt.usage.total_tokens is None


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "example-clock"])
def test_unusable_clock_keeps_timings_unknown_and_still_finishes(value):
    builder = _builder(lambda: value)
    builder.begin_request()
    builder.observe_text()
    builder.end_request(None)
    receipt = _finish(builder)
    assert receipt.duration_ms is receipt.model_wait_ms is receipt.time_to_first_text_ms is None


def test_backwards_clock_does_not_create_negative_or_fabricated_timing():
    ticks = iter([10, 10, 9, 8, 7])
    builder = _builder(lambda: next(ticks))
    builder.begin_request()
    builder.observe_text()
    builder.end_request(None)
    receipt = _finish(builder)
    assert receipt.duration_ms is receipt.model_wait_ms is receipt.time_to_first_text_ms is None


def test_tool_execution_receipt_uses_monotonic_elapsed_time_without_content():
    ticks = iter([10.0, 10.125])
    builder = ToolExecutionReceiptBuilder(monotonic=lambda: next(ticks))
    receipt = builder.finish(
        approval_state="approved",
        evidence_state="verified_workspace_effect",
    )

    assert receipt == AgentToolExecutionReceipt(
        elapsed_ms=125.0,
        approval_state="approved",
        evidence_state="verified_workspace_effect",
    )
    assert set(receipt.model_dump()) == {
        "contract_version",
        "elapsed_ms",
        "timing_source",
        "approval_state",
        "evidence_state",
    }


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "example-clock"])
def test_tool_execution_receipt_keeps_unusable_timing_unknown(value):
    receipt = ToolExecutionReceiptBuilder(monotonic=lambda: value).finish(
        approval_state="not_required",
        evidence_state="read_only_observation",
    )
    assert receipt.elapsed_ms is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("server_title", " Synthetic Files"),
        ("server_title", "Synthetic\nFiles"),
        ("tool_name", "read\u200bexample"),
        ("tool_title", "Read example "),
        ("model_alias", "mcp/foreign"),
        ("every_call_requires_native_approval", False),
    ],
)
def test_managed_mcp_descriptor_rejects_unsafe_or_reusable_identity(field, value):
    payload = {
        "server_title": "Synthetic Files",
        "tool_name": "read_example",
        "tool_title": "Read example",
        "model_alias": "mcp_99999999_synthetic_read",
        "every_call_requires_native_approval": True,
    }
    with pytest.raises(ValidationError):
        AgentMcpToolDescriptor.model_validate({**payload, field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "not_invoked", "content_mode": "text"},
        {"outcome": "not_invoked", "result_bytes": 1},
        {"outcome": "not_invoked", "cleanup_verified": False},
        {"outcome": "succeeded", "result_digest": None},
        {"outcome": "failed", "result_digest": None, "error_code": None},
        {"result_bytes": MAX_AGENT_MCP_RESULT_BYTES + 1},
        {"arguments_persisted": True},
        {"result_text_persisted": True},
        {"reusable_approval_persisted": True},
    ],
)
def test_managed_mcp_result_receipt_rejects_false_or_retained_evidence(changes):
    payload = {
        "managed_call_id": "a" * 32,
        "outcome": "not_invoked",
        "content_mode": "none",
        "result_bytes": 0,
        "result_digest": None,
        "error_code": None,
        "cleanup_verified": True,
    }
    with pytest.raises(ValidationError):
        AgentMcpToolResultReceipt.model_validate({**payload, **changes})


@pytest.mark.parametrize(
    "approval_state,evidence_state",
    [
        ("denied", "verified_workspace_effect"),
        ("timed_out", "unknown"),
        ("cancelled_before_decision", "untracked_external_effect"),
        ("not_requested", "read_only_observation"),
        ("not_required", "verified_workspace_effect"),
    ],
)
def test_tool_execution_receipt_rejects_contradictory_effect_claims(
    approval_state,
    evidence_state,
):
    with pytest.raises(ValidationError):
        AgentToolExecutionReceipt(
            approval_state=approval_state,
            evidence_state=evidence_state,
        )


@pytest.mark.parametrize("changes", [
    {"state": "partial", "model_requests": 0}, {"reported_requests": 1},
    {"prompt_tokens": 0}, {"model_requests": True}, {"model_requests": "1"},
    {"state": "reported"}, {"state": "partial", "model_requests": 1, "prompt_tokens": 10, "total_tokens": 2},
])
def test_public_usage_rejects_contradictions_and_coercions(changes):
    with pytest.raises(ValidationError):
        AgentTokenUsage.model_validate({"state": "unavailable", "model_requests": 0, "reported_requests": 0, **changes})


@pytest.mark.parametrize("path", ["../example.txt", "/example.txt", "C:/example.txt", "example\\file.txt", "example//file.txt", "./example.txt", "example/./file.txt", "example/", "example\x00.txt"])
def test_receipts_require_relative_canonical_paths(path):
    with pytest.raises(ValidationError):
        AgentWriteReceipt(path=path, state="unverified")


@pytest.mark.parametrize("changes", [{"tools_requested": True}, {"tools_requested": 1}, {"untracked_command_calls": 1}, {"status": "stopped"}])
def test_turn_summary_rejects_unaccounted_effects_or_wrong_termination(changes):
    original = _finish(_builder()).model_dump()
    with pytest.raises(ValidationError):
        AgentTurnSummary.model_validate({**original, **changes})


@pytest.mark.parametrize("before,after,operation,counts", [
    (None, "", "created", (0, 0)),
    ("example\n", "example\n", "unchanged", (0, 0)),
    ("example\r\n", "example\n", "modified", (1, 1)),
    ("one\ntwo\n", "one\nthree\nfour\n", "modified", (2, 1)),
])
def test_file_effect_metadata_comes_from_verified_bytes(tmp_path, before, after, operation, counts):
    path = tmp_path / "example.txt"
    if before is not None:
        path.write_bytes(before.encode())
    tools = WorkspaceTools(tmp_path)
    outcome = tools.write_file("example.txt", after)
    assert outcome.ok and outcome.write_receipt is not None
    receipt = outcome.write_receipt
    assert receipt.state == "verified" and receipt.operation == operation
    assert (receipt.added_lines, receipt.removed_lines) == counts
    assert receipt.byte_size == len(after.encode())
    assert path.read_bytes() == after.encode()


@pytest.mark.skipif(os.name != "nt", reason="Windows rollback fault seam")
def test_failed_postwrite_verification_restores_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_text("old example\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "new example\n")
    original = tools._read_open_descriptor
    calls = 0

    def read(descriptor, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("synthetic readback failure")
        return original(descriptor, **kwargs)

    monkeypatch.setattr(tools, "_read_open_descriptor", read)
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.write_receipt is None
    assert path.read_text() == "old example\n"
    assert not list(tmp_path.glob(".prompt-enhancer-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows rollback fault seam")
def test_failed_rollback_retains_an_unverified_attempt(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_text("old example\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "new example\n")
    original_read = tools._read_open_descriptor
    original_replace = tools._replace_windows_file
    reads = replacements = 0

    def read(descriptor, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 5:
            raise OSError("synthetic readback failure")
        return original_read(descriptor, **kwargs)

    def replace(target, replacement, backup):
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("synthetic rollback failure")
        return original_replace(target, replacement, backup)

    monkeypatch.setattr(tools, "_read_open_descriptor", read)
    monkeypatch.setattr(tools, "_replace_windows_file", replace)
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.write_receipt.state == "unverified"
    assert outcome.write_receipt.after_sha256 is outcome.write_receipt.operation is outcome.write_receipt.byte_size is None
    assert path.read_text() == "new example\n"
    assert len(list(tmp_path.glob(".prompt-enhancer-backup-*.tmp"))) == 1


def test_rejected_stale_revision_does_not_claim_any_write(tmp_path):
    path = tmp_path / "example.txt"
    path.write_text("old example\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path)
    prepared = tools.prepare_write("example.txt", "proposed example\n")
    path.write_text("external fictional change\n", encoding="utf-8")
    outcome = tools.apply_prepared_write(prepared)
    assert not outcome.ok and outcome.write_receipt is None
    assert path.read_text() == "external fictional change\n"


@pytest.mark.parametrize("mode", ["success", "nonzero", "timeout", "not_started"])
def test_command_attempts_never_invent_a_file_inventory(tmp_path, mode):
    def runner(*_args, **_kwargs):
        if mode == "timeout":
            raise subprocess.TimeoutExpired(["example-command"], 5)
        if mode == "not_started":
            raise OSError("synthetic launch failure")
        return subprocess.CompletedProcess(["example-command"], 0 if mode == "success" else 1, "example output", "")

    outcome = WorkspaceTools(tmp_path, runner=runner).run_command("example-command")
    assert outcome.ok == (mode == "success")
    assert outcome.untracked_command and outcome.write_receipt is None
