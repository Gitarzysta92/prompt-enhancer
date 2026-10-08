import { describe, expect, it } from "vitest";

import { exampleAgentTurn } from "../../features/agent/agentTurnFixtures.test-support";
import { AgentHistoryPayloadError, parseAgentHistoryExport } from "./agentHistoryContract";

const PROJECT_ID = "1".repeat(32);
const SESSION_ID = "2".repeat(32);
const STREAM_ID = "3".repeat(32);
const TURN_ID = "e".repeat(32);

function validExport() {
  return {
    contract_version: "agent-history.v1",
    exported_at: "2040-01-01T10:05:00Z",
    project_id: PROJECT_ID,
    session_id: SESSION_ID,
    title: "Saved synthetic chat",
    workspace: "D:\\example\\workspace",
    model_alias: "example-model",
    history_revision: 3,
    turn_count: 1,
    interrupted: false,
    events: [
      {
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "user",
        text: "Synthetic retained request.",
        turn_id: TURN_ID,
      },
      {
        seq: 2,
        at: "2040-01-01T10:00:01Z",
        kind: "assistant",
        text: "Synthetic retained answer.",
        reasoning: "Synthetic model-provided rationale.",
        stream_id: STREAM_ID,
        stream_status: "complete",
        turn_id: TURN_ID,
      },
      {
        seq: 3,
        at: "2040-01-01T10:00:02Z",
        kind: "done",
        turn_id: TURN_ID,
        turn_summary: exampleAgentTurn({
          turn_id: TURN_ID,
          tools_requested: 0,
          tools_succeeded: 0,
          writes: [],
        }),
      },
    ],
  };
}

describe("Agent retained-history contract", () => {
  it("accepts an exact, settled, identity-bound local export", () => {
    const parsed = parseAgentHistoryExport(validExport(), PROJECT_ID, SESSION_ID);
    expect(parsed.events.map((event) => event.kind)).toEqual(["user", "assistant", "done"]);
    expect(parsed.turn_count).toBe(1);
    expect(parsed.interrupted).toBe(false);
  });

  it("accepts an interrupted user turn only when the export says it is interrupted", () => {
    const value = {
      ...validExport(),
      history_revision: 1,
      turn_count: 0,
      interrupted: true,
      events: [validExport().events[0]],
    };
    expect(parseAgentHistoryExport(value, PROJECT_ID, SESSION_ID).interrupted).toBe(true);
    expect(() => parseAgentHistoryExport({ ...value, interrupted: false }, PROJECT_ID, SESSION_ID))
      .toThrow(AgentHistoryPayloadError);
  });

  it("retains content-free action execution facts without admitting raw output", () => {
    const value = {
      ...validExport(),
      history_revision: 1,
      turn_count: 0,
      events: [{
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "tool_result",
        tool: "run_command",
        call_id: "synthetic-call",
        ok: true,
        tool_state: "succeeded",
        execution_receipt: {
          contract_version: "agent-tool-execution.v1",
          elapsed_ms: 25,
          timing_source: "server_monotonic.v1",
          approval_state: "approved",
          evidence_state: "untracked_external_effect",
        },
      }],
    };
    const parsed = parseAgentHistoryExport(value, PROJECT_ID, SESSION_ID);
    expect(parsed.events[0].execution_receipt?.evidence_state).toBe("untracked_external_effect");
    expect(parsed.events[0].text).toBeUndefined();
  });

  it("rejects identities, revisions, turn counts, order, and extra export fields", () => {
    const valid = validExport();
    const attacks = [
      { ...valid, contract_version: "agent-history.v0" },
      { ...valid, project_id: "4".repeat(32) },
      { ...valid, session_id: "5".repeat(32) },
      { ...valid, history_revision: 4 },
      { ...valid, turn_count: 0 },
      { ...valid, events: [valid.events[1], valid.events[0], valid.events[2]] },
      { ...valid, transcript: "SYNTHETIC-PRIVATE-CANARY" },
    ];
    for (const attack of attacks) {
      expect(() => parseAgentHistoryExport(attack, PROJECT_ID, SESSION_ID))
        .toThrow(AgentHistoryPayloadError);
    }
  });

  it("rejects approval material, stream deltas, and raw tool output even when otherwise parseable", () => {
    const base = {
      ...validExport(),
      history_revision: 1,
      turn_count: 0,
      interrupted: false,
    };
    const attacks = [
      [{ seq: 1, at: "2040-01-01T10:00:00Z", kind: "status", text: "Ready.", approval_id: null }],
      [{
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "assistant_delta",
        text: "partial",
        stream_id: STREAM_ID,
        stream_phase: "content",
      }],
      [{
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "approval_required",
        tool: "run_command",
        approval_id: "6".repeat(32),
      }],
      [{
        seq: 1,
        at: "2040-01-01T10:00:00Z",
        kind: "tool_result",
        tool: "run_command",
        call_id: "synthetic-call",
        ok: true,
        tool_state: "succeeded",
        text: "SYNTHETIC-PRIVATE-OUTPUT-CANARY",
      }],
    ];
    for (const events of attacks) {
      expect(() => parseAgentHistoryExport({ ...base, events }, PROJECT_ID, SESSION_ID))
        .toThrow(AgentHistoryPayloadError);
    }
  });
});
