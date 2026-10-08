import { describe, expect, it } from "vitest";
import { AgentEventPayloadError, parseAgentSession } from "./agentEventContract";
import { exampleAgentSession } from "./agentSession.test-support";

describe("Agent session cleanup authority", () => {
  it("accepts explicit ready, stopping, and cleanup-paused sessions", () => {
    const ready = exampleAgentSession();
    expect(parseAgentSession(ready, ready.session_id)).toEqual(ready);
    expect(parseAgentSession({ ...ready, running: true, stopping: true }).stopping).toBe(true);
    const paused = { ...ready, cleanup_unconfirmed: true, closing: true };
    expect(parseAgentSession(paused).cleanup_unconfirmed).toBe(true);
  });

  const cases: [string, object][] = [
    ["legacy", { contract_version: "local-agent.v5" }],
    ["missing-cleanup", { cleanup_unconfirmed: undefined }],
    ["string-cleanup", { cleanup_unconfirmed: "false" }],
    ["cleanup-still-open", { cleanup_unconfirmed: true, closing: false }],
    ["cleanup-approval", { cleanup_unconfirmed: true, closing: true, pending_approval_id: "b".repeat(32) }],
    ["foreign", { session_id: "b".repeat(32) }],
    ["stopped-running", { stopping: true, running: false }],
    ["string-running", { running: "false" }],
    ["bad-created", { created_at: "not-a-date" }],
    ["negative-cursor", { last_seq: -1 }],
    ["fractional-turn", { turns: 0.5 }],
    ["extra-field", { extra: "EXAMPLE_PRIVATE_CANARY" }],
    ["empty-settings", { settings: {} }],
    ["bad-permission", { settings: { ...exampleAgentSession().settings, allow_commands: "false" } }],
    ["timeout-ceiling", { settings: { ...exampleAgentSession().settings, command_timeout_seconds: 601 } }],
    ["invalid-sampling", { settings: { ...exampleAgentSession().settings, parameters: { ...exampleAgentSession().settings.parameters, top_p: 0 } } }],
  ];
  it.each(cases)("rejects %s without accepting an actionable session", (_label, changes) => {
    expect(() => parseAgentSession({ ...exampleAgentSession(), ...changes }, "a".repeat(32))).toThrow(AgentEventPayloadError);
  });
});
