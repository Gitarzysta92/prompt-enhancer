import { describe, expect, it } from "vitest";
import { exampleAgentTurn, exampleTokenUsage, exampleWriteReceipt } from "../../features/agent/agentTurnFixtures.test-support";
import { AgentEventPayloadError, parseAgentEvents } from "./agentEventContract";
import { isAgentToolExecutionReceipt, isAgentTurnSummary, isAgentWriteReceipt } from "./agentTurnContract";

const SESSION = "a".repeat(32);
function page(extra: Record<string, unknown> = {}) {
  const receipt = exampleAgentTurn();
  return { contract_version: "local-agent.v9", cleanup_unconfirmed: false, session_id: SESSION, closing: false, stopping: false, running: false, pending_approval_id: null, last_seq: 1, first_seq: 1,
    events: [{ seq: 1, at: receipt.finished_at, kind: "done", turn_id: receipt.turn_id, turn_summary: receipt, ...extra }] };
}

describe("Agent turn receipt contract", () => {
  it("accepts content-free action facts and rejects impossible authority/evidence pairs", () => {
    const receipt = {
      contract_version: "agent-tool-execution.v1",
      elapsed_ms: null,
      timing_source: "server_monotonic.v1",
      approval_state: "not_required",
      evidence_state: "read_only_observation",
    };
    expect(isAgentToolExecutionReceipt(receipt)).toBe(true);
    expect(isAgentToolExecutionReceipt({ ...receipt, approval_state: "denied" })).toBe(false);
    expect(isAgentToolExecutionReceipt({ ...receipt, elapsed_ms: Infinity })).toBe(false);
    expect(isAgentToolExecutionReceipt({ ...receipt, output: "synthetic private output" })).toBe(false);
  });
  it("accepts exact reported receipts through the public event parser", () => {
    const receipt = exampleAgentTurn();
    expect(isAgentTurnSummary(receipt, receipt.turn_id)).toBe(true);
    expect(parseAgentEvents(page(), SESSION, 0).events[0].turn_summary).toEqual(receipt);
  });

  it("preserves reported zero and unknown timings without estimation", () => {
    expect(isAgentTurnSummary(exampleAgentTurn({ duration_ms: null, model_wait_ms: null, time_to_first_text_ms: null,
      usage: exampleTokenUsage({ prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 }) }))).toBe(true);
    expect(isAgentTurnSummary(exampleAgentTurn({ usage: exampleTokenUsage({ state: "partial", model_requests: 2, reported_requests: 1, prompt_tokens: null, completion_tokens: null, total_tokens: null }) }))).toBe(true);
  });

  it.each([
    { contract_version: "agent-turn.v0" }, { source: "example-inferred" }, { turn_number: 0 }, { turn_number: true },
    { status: "completed", reason: "stop_requested" }, { model_alias: "" }, { started_at: "invalid" },
    { duration_ms: -1 }, { duration_ms: Infinity }, { duration_ms: 1 }, { timing_source: "estimated" },
    { tools_requested: 0 }, { untracked_command_calls: 1 }, { tools_succeeded: 0, tools_failed: 1 },
    { writes: [exampleWriteReceipt({ state: "unverified", operation: null, after_sha256: null, added_lines: null, removed_lines: null, byte_size: null })] },
  ])("rejects incompatible or contradictory turn metadata: %j", (changes) => {
    expect(isAgentTurnSummary({ ...exampleAgentTurn(), ...changes })).toBe(false);
  });

  it.each([
    { prompt_tokens: true }, { prompt_tokens: "11" }, { prompt_tokens: -1 }, { total_tokens: Number.MAX_SAFE_INTEGER + 1 },
    { total_tokens: 500 }, { cached_prompt_tokens: 12 }, { reasoning_tokens: 8 },
    { state: "unavailable" }, { state: "invalid" }, { state: "partial" }, { model_requests: 0 },
    { reported_requests: 2 }, { model_requests: 17 }, { source: "estimated" }, { extra: "example" },
    { state: "partial", reported_requests: 0, prompt_tokens: 11, completion_tokens: null, total_tokens: 10 },
  ])("rejects invented coverage or counters: %j", (changes) => {
    expect(isAgentTurnSummary({ ...exampleAgentTurn(), usage: { ...exampleTokenUsage(), ...changes } })).toBe(false);
  });

  it.each(["../example.txt", "/example.txt", "C:/example.txt", "example\\file.txt", "example//file.txt", "./example.txt", "example/./file.txt", "example/", "example\u0000.txt"])("rejects noncanonical receipt paths: %s", (path) => {
    expect(isAgentWriteReceipt(exampleWriteReceipt({ path }))).toBe(false);
  });

  it("rejects fabricated verified effects and permits honest unverified attempts", () => {
    expect(isAgentWriteReceipt(exampleWriteReceipt({ state: "unverified" }))).toBe(false);
    expect(isAgentWriteReceipt(exampleWriteReceipt({ operation: "created" }))).toBe(false);
    expect(isAgentWriteReceipt(exampleWriteReceipt({ operation: "unchanged" }))).toBe(false);
    expect(isAgentWriteReceipt(exampleWriteReceipt({ state: "unverified", operation: null, after_sha256: null, added_lines: null, removed_lines: null, byte_size: null }))).toBe(true);
  });

  it.each([
    { turn_id: null }, { turn_id: undefined }, { turn_id: "f".repeat(32) }, { kind: "status" },
    { tool_state: "succeeded", ok: true }, { write_receipt: exampleWriteReceipt() },
  ])("rejects a receipt attached to a foreign or unbound event: %j", (changes) => {
    expect(() => parseAgentEvents(page(changes), SESSION, 0)).toThrow(AgentEventPayloadError);
  });

  it("binds write receipts to matching tool outcomes", () => {
    const result = { kind: "tool_result", turn_summary: null, tool: "write_file", call_id: "synthetic-write-call", tool_state: "succeeded", ok: true, write_receipt: exampleWriteReceipt() };
    expect(parseAgentEvents(page(result), SESSION, 0).events[0].write_receipt).toEqual(exampleWriteReceipt());
    for (const changes of [{ tool: "run_command" }, { ok: false }, { tool_state: "unverified" }, { kind: "assistant" }]) {
      expect(() => parseAgentEvents(page({ ...result, ...changes }), SESSION, 0)).toThrow(AgentEventPayloadError);
    }
  });
});
