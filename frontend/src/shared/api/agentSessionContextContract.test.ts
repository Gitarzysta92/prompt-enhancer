import { describe, expect, it } from "vitest";

import {
  AgentSessionContextPayloadError,
  parseAgentSessionContext,
} from "./agentSessionContextContract";

const SESSION_ID = "a".repeat(32);

function unmeasured() {
  return {
    contract_version: "agent-session-context.v1",
    session_id: SESSION_ID,
    revision: 0,
    binding_state: "unmeasured",
    source: "runtime_chat_template_preflight",
    unknown_reason: "no_request_measured",
    turn_id: null,
    turn_number: null,
    model_alias: null,
    observed_at: null,
    context: null,
  };
}

function bound() {
  return {
    ...unmeasured(),
    revision: 2,
    binding_state: "bound",
    unknown_reason: null,
    turn_id: "b".repeat(32),
    turn_number: 1,
    model_alias: "example-model",
    observed_at: "2026-08-28T12:00:00Z",
    context: {
      state: "known",
      used_tokens: 640,
      limit_tokens: 8192,
      requested_output_tokens: 1400,
      available_output_tokens: 7552,
      source: "runtime_chat_input_tokens",
      scope: "last_request",
      policy: "exact_admitted",
      compacted_messages: 0,
      reason_code: null,
    },
  };
}

describe("Agent session context contract", () => {
  it("accepts explicit unknown and exact turn-bound evidence", () => {
    expect(parseAgentSessionContext(unmeasured(), SESSION_ID).binding_state)
      .toBe("unmeasured");
    const parsed = parseAgentSessionContext(bound(), SESSION_ID);
    expect(parsed.binding_state).toBe("bound");
    expect(parsed.turn_number).toBe(1);
    expect(parsed.context?.used_tokens).toBe(640);
  });

  it("keeps bound unknown, exact compacted, and exact refused evidence distinct", () => {
    const boundUnknown = bound();
    Object.assign(boundUnknown.context, {
      state: "unknown",
      used_tokens: null,
      requested_output_tokens: null,
      available_output_tokens: null,
      source: "runtime_limit_only",
      scope: "runtime_limit",
      policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: "input_counter_unavailable",
    });
    expect(parseAgentSessionContext(boundUnknown, SESSION_ID).context?.state).toBe("unknown");

    const compacted = bound();
    Object.assign(compacted.context, {
      used_tokens: 7000,
      requested_output_tokens: 1000,
      available_output_tokens: 1192,
      policy: "exact_compacted",
      compacted_messages: 4,
    });
    expect(parseAgentSessionContext(compacted, SESSION_ID).context?.policy).toBe("exact_compacted");

    const refused = bound();
    Object.assign(refused.context, {
      used_tokens: 8500,
      available_output_tokens: -308,
      policy: "exact_refused",
      reason_code: "context_window_exceeded",
    });
    expect(parseAgentSessionContext(refused, SESSION_ID).context?.policy).toBe("exact_refused");

    const inventedEstimate = bound();
    Object.assign(inventedEstimate.context, { state: "estimated" });
    expect(() => parseAgentSessionContext(inventedEstimate, SESSION_ID))
      .toThrow(AgentSessionContextPayloadError);
  });

  it("rejects cross-chat, private extension, and partial bindings", () => {
    expect(() => parseAgentSessionContext(bound(), "c".repeat(32)))
      .toThrow(AgentSessionContextPayloadError);

    const extended = { ...bound(), private_path: "C:/synthetic/private" };
    expect(() => parseAgentSessionContext(extended, SESSION_ID))
      .toThrow(AgentSessionContextPayloadError);

    const partial = { ...unmeasured(), turn_id: "b".repeat(32) };
    expect(() => parseAgentSessionContext(partial, SESSION_ID))
      .toThrow(AgentSessionContextPayloadError);
  });

  it("rejects forged or internally inconsistent token evidence", () => {
    const forged = bound();
    forged.context.available_output_tokens = 1;
    expect(() => parseAgentSessionContext(forged, SESSION_ID))
      .toThrow(AgentSessionContextPayloadError);
  });
});
