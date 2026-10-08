import { describe, expect, it } from "vitest";

import {
  McpManagedRuntimePayloadError,
  parseMcpManagedHostStartPreview,
  parseMcpManagedHostStatus,
  parseMcpManagedProjectRuntime,
} from "./mcpManagedRuntimeContract";
import {
  syntheticMcpManagedHostStartPreview,
  syntheticMcpManagedHostStatus,
  syntheticMcpManagedProjectRuntime,
  syntheticReadyMcpManagedHostStatus,
} from "./mcpManagedRuntime.test-support";

describe("managed MCP runtime contract", () => {
  it("accepts exact stopped, preview, ready, and routed-tool projections", () => {
    expect(parseMcpManagedHostStatus(syntheticMcpManagedHostStatus()).state).toBe("not_started");
    expect(parseMcpManagedHostStartPreview(syntheticMcpManagedHostStartPreview()).preview_starts_host).toBe(false);
    expect(parseMcpManagedHostStatus(syntheticReadyMcpManagedHostStatus()).tool_calls_available).toBe(true);
    expect(parseMcpManagedProjectRuntime(syntheticMcpManagedProjectRuntime()).ready_tool_count).toBe(1);
  });

  it("rejects extra connection material and false routing claims", () => {
    expect(() => parseMcpManagedHostStatus({
      ...syntheticMcpManagedHostStatus(),
      endpoint: "https://mcp.example.invalid/private",
    })).toThrow(McpManagedRuntimePayloadError);
    expect(() => parseMcpManagedHostStatus({
      ...syntheticReadyMcpManagedHostStatus(),
      tool_calls_available: false,
      tool_routing_state: "inactive",
    })).toThrow(McpManagedRuntimePayloadError);
  });

  it("rejects reordered effects, cross-project tools, and remembered approvals", () => {
    const preview = syntheticMcpManagedHostStartPreview();
    expect(() => parseMcpManagedHostStartPreview({
      ...preview,
      effects: [...preview.effects].reverse(),
    })).toThrow(McpManagedRuntimePayloadError);
    const runtime = syntheticMcpManagedProjectRuntime();
    expect(() => parseMcpManagedProjectRuntime({
      ...runtime,
      tools: runtime.tools.map((tool) => ({ ...tool, project_id: "e".repeat(32) })),
    })).toThrow(McpManagedRuntimePayloadError);
    expect(() => parseMcpManagedProjectRuntime({
      ...runtime,
      remembered_call_approval: true,
    })).toThrow(McpManagedRuntimePayloadError);
  });

  it("rejects a valid-shaped but unallowlisted host failure code", () => {
    expect(() => parseMcpManagedHostStatus({
      ...syntheticReadyMcpManagedHostStatus(),
      state: "unhealthy",
      reason: "transport_failed",
      host_lease_active: false,
      error_code: "example_private_failure_canary",
      tool_calls_available: false,
      tool_routing_state: "inactive",
    })).toThrow(McpManagedRuntimePayloadError);
  });
});
