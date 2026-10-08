import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type {
  AgentEvent,
  AgentMcpToolDescriptor,
  AgentMcpToolResultReceipt,
} from "../../shared/api/contracts";
import {
  AgentMcpToolActivity,
  collectAgentMcpCalls,
} from "./AgentMcpToolActivity";

const ALIAS = "mcp_99999999_synthetic_read";
const CALL = "synthetic-model-call";

const descriptor: AgentMcpToolDescriptor = {
  contract_version: "agent-mcp-tool.v1",
  source: "managed_mcp",
  server_title: "Synthetic Files",
  tool_name: "read_example",
  tool_title: "Read example",
  model_alias: ALIAS,
  every_call_requires_native_approval: true,
};

function event(
  seq: number,
  kind: AgentEvent["kind"],
  extra: Partial<AgentEvent> = {},
): AgentEvent {
  return {
    seq,
    at: "2040-01-01T10:00:00Z",
    kind,
    attachments: [],
    ...extra,
  };
}

function resultReceipt(
  extra: Partial<AgentMcpToolResultReceipt> = {},
): AgentMcpToolResultReceipt {
  return {
    contract_version: "agent-mcp-tool-result.v1",
    managed_call_id: "a".repeat(32),
    outcome: "succeeded",
    content_mode: "text",
    result_bytes: 24,
    result_digest: "b".repeat(64),
    error_code: null,
    cleanup_verified: true,
    arguments_persisted: false,
    result_text_persisted: false,
    reusable_approval_persisted: false,
    ...extra,
  };
}

function activity(events: AgentEvent[]) {
  const call = collectAgentMcpCalls(events).get(CALL);
  if (!call) throw new Error("synthetic MCP call was not collected");
  return call;
}

describe("AgentMcpToolActivity", () => {
  it("coalesces one exact request, approval, resolution and result without merging adjacent calls", () => {
    const secondCall = "second-synthetic-model-call";
    const calls = collectAgentMcpCalls([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "approval_required", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), arguments: {}, mcp_tool: descriptor }),
      event(3, "approval_resolved", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), ok: true, mcp_tool: descriptor }),
      event(4, "tool_result", { call_id: CALL, tool: ALIAS, ok: true, tool_state: "succeeded", mcp_tool: descriptor, mcp_result: resultReceipt() }),
      event(5, "tool_call", { call_id: secondCall, tool: ALIAS, arguments: {} }),
    ]);

    expect(calls).toHaveLength(2);
    expect(calls.get(CALL)?.request?.seq).toBe(1);
    expect(calls.get(CALL)?.approval?.seq).toBe(2);
    expect(calls.get(CALL)?.resolution?.seq).toBe(3);
    expect(calls.get(CALL)?.result?.seq).toBe(4);
    expect(calls.get(secondCall)?.result).toBeNull();
  });

  it("keeps an early managed-runtime refusal terminal even when no descriptor was prepared", () => {
    const call = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "tool_result", {
        call_id: CALL,
        tool: ALIAS,
        ok: false,
        tool_state: "failed",
        text: "managed MCP runtime unavailable",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 2,
          timing_source: "server_monotonic.v1",
          approval_state: "not_requested",
          evidence_state: "no_effect",
        },
      }),
    ]);

    render(<AgentMcpToolActivity call={call} />);

    expect(screen.getByRole("article", { name: "MCP tool call: Managed MCP tool from Managed MCP server. Failed" })).toBeVisible();
    expect(screen.getByText("Approval not requested")).toBeVisible();
    expect(screen.getByText("No invocation effect")).toBeVisible();
  });

  it("shows a friendly pending identity and one-call approval policy without the model alias", () => {
    const call = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "approval_required", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), arguments: {}, mcp_tool: descriptor }),
    ]);

    render(<AgentMcpToolActivity call={call} />);

    const card = screen.getByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Waiting for approval" });
    expect(card).toBeVisible();
    expect(screen.getByText("Read example")).toBeVisible();
    expect(within(card).getAllByText("Synthetic Files")[0]).toBeVisible();
    expect(screen.getByText(/fresh native approval for this call only/i)).toBeVisible();
    expect(screen.queryByText(ALIAS)).not.toBeInTheDocument();
  });

  it("replaces a pending approval state with cancelling as soon as Stop is acknowledged", () => {
    const call = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "approval_required", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), arguments: {}, mcp_tool: descriptor }),
    ]);

    render(<AgentMcpToolActivity call={call} stopping />);

    expect(screen.getByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Cancelling" })).toBeVisible();
    expect(screen.queryByText("Waiting for approval")).not.toBeInTheDocument();
  });

  it("shows approved result evidence and keeps bounded output behind details", () => {
    const call = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "approval_required", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), arguments: {}, mcp_tool: descriptor }),
      event(3, "approval_resolved", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), ok: true, mcp_tool: descriptor }),
      event(4, "tool_result", {
        call_id: CALL,
        tool: ALIAS,
        ok: true,
        tool_state: "succeeded",
        text: "Synthetic bounded result",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 1250,
          timing_source: "server_monotonic.v1",
          approval_state: "approved",
          evidence_state: "untracked_external_effect",
        },
        mcp_tool: descriptor,
        mcp_result: resultReceipt(),
      }),
    ]);

    render(<AgentMcpToolActivity call={call} />);

    const card = screen.getByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Completed" });
    expect(within(card).getAllByText("Completed")[0]).toBeVisible();
    expect(screen.getByText("1.25 s")).toBeVisible();
    expect(screen.getByText("Approved once")).toBeVisible();
    expect(screen.getByText("External effect not verified")).toBeVisible();
    expect(screen.getByText("Text result")).toBeVisible();
    expect(screen.getByText("24 B")).toBeVisible();
    expect(screen.getByText("Cleanup verified")).toBeVisible();
    expect(screen.queryByText("Synthetic bounded result")).not.toBeVisible();
    fireEvent.click(screen.getByText("Call details"));
    expect(screen.getByText("Synthetic bounded result")).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy Read example result" })).toBeVisible();
  });

  it("distinguishes a denied uninvoked call from a failed invocation", () => {
    const call = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "approval_resolved", { call_id: CALL, tool: ALIAS, approval_id: "c".repeat(32), ok: false, mcp_tool: descriptor }),
      event(3, "tool_result", {
        call_id: CALL,
        tool: ALIAS,
        ok: false,
        tool_state: "not_approved",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 12,
          timing_source: "server_monotonic.v1",
          approval_state: "denied",
          evidence_state: "no_effect",
        },
        mcp_tool: descriptor,
        mcp_result: resultReceipt({
          outcome: "not_invoked",
          content_mode: "none",
          result_bytes: 0,
          result_digest: null,
        }),
      }),
    ]);

    render(<AgentMcpToolActivity call={call} />);

    const card = screen.getByRole("article", { name: "MCP tool call: Read example from Synthetic Files. Not approved" });
    expect(within(card).getAllByText("Not approved")[0]).toBeVisible();
    expect(screen.getByText("Denied")).toBeVisible();
    expect(screen.getByText("No invocation effect")).toBeVisible();
    expect(screen.getByText("Not invoked")).toBeVisible();
  });

  it("surfaces cleanup uncertainty and interrupted retained calls truthfully", () => {
    const uncertain = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "tool_result", {
        call_id: CALL,
        tool: ALIAS,
        ok: false,
        tool_state: "unverified",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: null,
          timing_source: "server_monotonic.v1",
          approval_state: "approved",
          evidence_state: "untracked_external_effect",
        },
        mcp_tool: descriptor,
        mcp_result: resultReceipt({
          outcome: "failed",
          content_mode: "none",
          result_bytes: 28,
          result_digest: null,
          error_code: "mcp_host_cleanup_unconfirmed",
          cleanup_verified: false,
        }),
      }),
    ]);
    const interrupted = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
    ]);

    const { rerender } = render(<AgentMcpToolActivity call={uncertain} />);
    expect(screen.getAllByText("Cleanup uncertain").length).toBeGreaterThan(0);
    expect(screen.getByText("External effect not verified")).toBeVisible();
    expect(screen.getByText(/Recover or stop this MCP host/)).toBeVisible();

    rerender(<AgentMcpToolActivity call={interrupted} interrupted />);
    expect(screen.getByText("Interrupted")).toBeVisible();
  });

  it("provides fixed recovery guidance for a bounded result refusal", () => {
    const refused = activity([
      event(1, "tool_call", { call_id: CALL, tool: ALIAS, arguments: {} }),
      event(2, "tool_result", {
        call_id: CALL,
        tool: ALIAS,
        ok: false,
        tool_state: "failed",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 8,
          timing_source: "server_monotonic.v1",
          approval_state: "approved",
          evidence_state: "untracked_external_effect",
        },
        mcp_tool: descriptor,
        mcp_result: resultReceipt({
          outcome: "failed",
          content_mode: "none",
          result_bytes: 0,
          result_digest: null,
          error_code: "mcp_tool_result_too_complex",
        }),
      }),
    ]);

    render(<AgentMcpToolActivity call={refused} />);
    expect(screen.getByText(/result failed a bounded safety check/)).toBeVisible();
    expect(screen.getByText(/host was stopped/)).toBeVisible();
  });
});
