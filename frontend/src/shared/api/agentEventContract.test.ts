import { describe, expect, it } from "vitest";
import { AgentEventPayloadError, parseAgentEvents } from "./agentEventContract";

const SESSION = "a".repeat(32);
const STREAM = "b".repeat(32);
const ATTACHMENT = {
  contract_version: "agent-attachment.v2",
  attachment_id: "c".repeat(32),
  display_name: "example.png",
  kind: "image",
  media_type: "image/png",
  byte_size: 68,
  sha256: "d".repeat(64),
  width: 1,
  height: 1,
  duration_ms: null,
  sample_rate_hz: null,
  channels: null,
  routing: "native_multimodal",
  document_format: null,
  projected_characters: null,
  projection_truncated: null,
  omitted_features: [],
  context_tokens: null,
  context_cost_source: "runtime_unreported",
} as const;
const EXECUTION_RECEIPT = {
  contract_version: "agent-tool-execution.v1",
  elapsed_ms: 125,
  timing_source: "server_monotonic.v1",
  approval_state: "approved",
  evidence_state: "verified_workspace_effect",
} as const;
const MCP_TOOL = {
  contract_version: "agent-mcp-tool.v1",
  source: "managed_mcp",
  server_title: "Synthetic Files",
  tool_name: "read_example",
  tool_title: "Read example",
  model_alias: "mcp_99999999_synthetic_read",
  every_call_requires_native_approval: true,
} as const;
const MCP_RESULT = {
  contract_version: "agent-mcp-tool-result.v1",
  managed_call_id: "e".repeat(32),
  outcome: "succeeded",
  content_mode: "text",
  result_bytes: 24,
  result_digest: "f".repeat(64),
  error_code: null,
  cleanup_verified: true,
  arguments_persisted: false,
  result_text_persisted: false,
  reusable_approval_persisted: false,
} as const;

function page() {
  return {
    contract_version: "local-agent.v9", cleanup_unconfirmed: false, closing: false, stopping: false,
    session_id: SESSION,
    events: [
      {
        seq: 1,
        at: "2026-08-20T01:00:00Z",
        kind: "assistant_delta",
        text: "Hello",
        reasoning: null,
        stream_id: STREAM,
        stream_phase: "content",
        stream_status: null,
        tool: null,
        arguments: null,
        call_id: null,
        approval_id: null,
        ok: null,
        preview: null,
      },
      {
        seq: 2,
        at: "2026-08-20T01:00:01Z",
        kind: "assistant",
        text: "Hello",
        reasoning: null,
        stream_id: STREAM,
        stream_phase: null,
        stream_status: "complete",
        tool: null,
        arguments: null,
        call_id: null,
        approval_id: null,
        ok: null,
        preview: null,
      },
    ],
    running: false,
    pending_approval_id: null,
    last_seq: 2,
    first_seq: 1,
  };
}

describe("agent event contract", () => {
  it("accepts one exact v6 stream page with explicit cleanup, closing and stopping states", () => {
    const parsed = parseAgentEvents(page(), SESSION, 0);
    expect(parsed.events.map((event) => event.kind)).toEqual(["assistant_delta", "assistant"]);
    expect(parsed.closing).toBe(false);
    expect(parseAgentEvents({ ...page(), cleanup_unconfirmed: true, closing: true }, SESSION).cleanup_unconfirmed).toBe(true);
    expect(parseAgentEvents({ ...page(), closing: true }, SESSION, 0).closing).toBe(true);
    expect(parseAgentEvents({ ...page(), running: true, stopping: true }, SESSION, 0).stopping).toBe(true);
    const emojiDense = page();
    emojiDense.events[0].text = "😀".repeat(192);
    expect(parseAgentEvents(emojiDense, SESSION, 0).events[0].text).toHaveLength(384);
  });

  it("rejects stale versions, foreign sessions, cursor replays, and forged stream states", () => {
    const attacks = [
      { ...page(), contract_version: "local-agent.v1" },
      { ...page(), contract_version: "local-agent.v2" },
      { ...page(), contract_version: "local-agent.v3" },
      { ...page(), contract_version: "local-agent.v4" },
      { ...page(), contract_version: "local-agent.v5" },
      { ...page(), contract_version: "local-agent.v6" },
      { ...page(), contract_version: "local-agent.v7" },
      { ...page(), contract_version: "local-agent.v8" },
      { ...page(), cleanup_unconfirmed: undefined },
      { ...page(), cleanup_unconfirmed: "false" },
      { ...page(), cleanup_unconfirmed: true, closing: false },
      { ...page(), cleanup_unconfirmed: true, closing: true, pending_approval_id: "b".repeat(32) },
      { ...page(), stopping: undefined },
      { ...page(), stopping: "false" },
      { ...page(), stopping: true, running: false },
      { ...page(), closing: undefined },
      { ...page(), closing: "false" },
      { ...page(), session_id: "c".repeat(32) },
      { ...page(), events: [{ ...page().events[0], seq: 0 }] },
      { ...page(), events: [{ ...page().events[0], stream_status: "complete" }] },
      { ...page(), events: [{ ...page().events[1], stream_status: null }] },
      { ...page(), events: [{ ...page().events[1], extra: "content" }] },
    ];
    for (const attack of attacks) {
      expect(() => parseAgentEvents(attack, SESSION, 0)).toThrow(AgentEventPayloadError);
    }
    expect(() => parseAgentEvents(page(), SESSION, 1)).toThrow(AgentEventPayloadError);
  });

  it("admits attachment-only user events while rejecting media on every other event kind", () => {
    const userEvent = {
      ...page().events[0],
      kind: "user",
      text: "",
      reasoning: null,
      stream_id: null,
      stream_phase: null,
      attachments: [ATTACHMENT],
    };
    const attachmentOnly = { ...page(), events: [userEvent], first_seq: 1, last_seq: 1 };
    expect(parseAgentEvents(attachmentOnly, SESSION).events[0].attachments).toEqual([ATTACHMENT]);

    const forgedAssistant = {
      ...page(),
      events: [page().events[0], { ...page().events[1], attachments: [ATTACHMENT] }],
    };
    expect(() => parseAgentEvents(forgedAssistant, SESSION)).toThrow(AgentEventPayloadError);

    const emptyUser = { ...attachmentOnly, events: [{ ...userEvent, attachments: [] }] };
    expect(() => parseAgentEvents(emptyUser, SESSION)).toThrow(AgentEventPayloadError);
  });

  it("rejects fields borrowed from another event kind and incomplete activity receipts", () => {
    const assistantWithToolAuthority = {
      ...page(),
      events: [{ ...page().events[1], tool: "run_command", call_id: "synthetic-call" }],
      first_seq: 2,
      last_seq: 2,
    };
    const statusWithApprovalIdentity = {
      ...page(),
      events: [{ ...page().events[0], kind: "status", stream_id: null, stream_phase: null, text: "Ready", approval_id: "d".repeat(32) }],
      first_seq: 1,
      last_seq: 1,
    };
    const resultWithoutOutcome = {
      ...page(),
      events: [{ ...page().events[0], kind: "tool_result", stream_id: null, stream_phase: null, text: null, tool: "read_file", call_id: "synthetic-call" }],
      first_seq: 1,
      last_seq: 1,
    };
    for (const attack of [assistantWithToolAuthority, statusWithApprovalIdentity, resultWithoutOutcome]) {
      expect(() => parseAgentEvents(attack, SESSION)).toThrow(AgentEventPayloadError);
    }
  });

  it("accepts truthful tool execution receipts and rejects contradictory or foreign receipts", () => {
    const result = {
      ...page().events[0],
      kind: "tool_result",
      stream_id: null,
      stream_phase: null,
      text: null,
      tool: "write_file",
      call_id: "synthetic-call",
      ok: true,
      tool_state: "succeeded",
      execution_receipt: EXECUTION_RECEIPT,
    };
    const valid = { ...page(), events: [result], first_seq: 1, last_seq: 1 };
    expect(parseAgentEvents(valid, SESSION).events[0].execution_receipt).toEqual(EXECUTION_RECEIPT);

    const attacks = [
      { ...EXECUTION_RECEIPT, elapsed_ms: -1 },
      { ...EXECUTION_RECEIPT, elapsed_ms: Number.NaN },
      { ...EXECUTION_RECEIPT, contract_version: "agent-tool-execution.v0" },
      { ...EXECUTION_RECEIPT, approval_state: "denied" },
      { ...EXECUTION_RECEIPT, evidence_state: "invented_evidence" },
      { ...EXECUTION_RECEIPT, private_output: "must not be admitted" },
    ];
    for (const execution_receipt of attacks) {
      expect(() => parseAgentEvents(
        { ...valid, events: [{ ...result, execution_receipt }] },
        SESSION,
      )).toThrow(AgentEventPayloadError);
    }
  });

  it("admits exact content-free managed MCP activity and rejects forged or contradictory projections", () => {
    const approval = {
      ...page().events[0],
      kind: "approval_required",
      stream_id: null,
      stream_phase: null,
      text: null,
      tool: MCP_TOOL.model_alias,
      call_id: "synthetic-model-call",
      approval_id: "d".repeat(32),
      arguments: {},
      preview: "Synthetic redacted review",
      mcp_tool: MCP_TOOL,
    };
    const result = {
      ...page().events[0],
      kind: "tool_result",
      stream_id: null,
      stream_phase: null,
      text: "Synthetic bounded live result",
      tool: MCP_TOOL.model_alias,
      call_id: "synthetic-model-call",
      ok: true,
      tool_state: "succeeded",
      execution_receipt: {
        ...EXECUTION_RECEIPT,
        evidence_state: "untracked_external_effect",
      },
      mcp_tool: MCP_TOOL,
      mcp_result: MCP_RESULT,
    };
    const valid = {
      ...page(),
      events: [approval, result],
      first_seq: 1,
      last_seq: 2,
    };
    valid.events[1].seq = 2;
    const parsed = parseAgentEvents(valid, SESSION);
    expect(parsed.events[0].mcp_tool).toEqual(MCP_TOOL);
    expect(parsed.events[1].mcp_result).toEqual(MCP_RESULT);

    const attacks = [
      { ...result, mcp_tool: { ...MCP_TOOL, model_alias: "mcp_99999999_foreign" } },
      { ...result, mcp_tool: { ...MCP_TOOL, server_title: "" } },
      { ...result, mcp_tool: { ...MCP_TOOL, server_title: " Synthetic Files" } },
      { ...result, mcp_tool: { ...MCP_TOOL, tool_name: "read\nexample" } },
      { ...result, mcp_tool: { ...MCP_TOOL, every_call_requires_native_approval: false } },
      { ...result, mcp_tool: { ...MCP_TOOL, private_endpoint: "https://example.invalid" } },
      { ...result, mcp_result: { ...MCP_RESULT, result_bytes: 128 * 1024 + 1 } },
      { ...result, mcp_result: { ...MCP_RESULT, result_digest: "short" } },
      { ...result, mcp_result: { ...MCP_RESULT, outcome: "failed", result_digest: null, error_code: null } },
      { ...result, mcp_result: { ...MCP_RESULT, outcome: "not_invoked", content_mode: "none", result_bytes: 1, result_digest: null } },
      { ...result, mcp_tool: null },
    ];
    for (const attack of attacks) {
      expect(() => parseAgentEvents(
        { ...page(), events: [{ ...attack, seq: 1 }], first_seq: 1, last_seq: 1 },
        SESSION,
      )).toThrow(AgentEventPayloadError);
    }
  });
});
