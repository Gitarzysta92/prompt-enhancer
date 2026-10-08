import { describe, expect, it } from "vitest";
import type { AgentEvent } from "../../shared/api/contracts";
import {
  findLoadedConversationMessageCandidates,
  findLoadedConversationMessages,
} from "./agentConversationNavigation";

function event(seq: number, kind: AgentEvent["kind"], extra: Partial<AgentEvent> = {}): AgentEvent {
  return { at: "2040-01-01T00:00:00Z", attachments: [], kind, seq, text: null, ...extra };
}

describe("findLoadedConversationMessages", () => {
  it("returns one literal match per loaded user or terminal assistant message", () => {
    const events = [
      event(1, "user", { text: "İx [a-z]+ twice [a-z]+" }),
      event(2, "assistant", { stream_status: "stopped", text: "Stopped [a-z]+ reply" }),
      event(3, "assistant", { stream_status: "failed", text: "Failed [a-z]+ reply" }),
      event(4, "tool_result", { text: "[a-z]+ tool output", tool: "read_file" }),
      event(5, "status", { text: "[a-z]+ status" }),
      event(6, "assistant_delta", { text: "[a-z]+ delta", stream_id: "d".repeat(32) }),
      event(7, "assistant", { text: "No matching text", reasoning: "[a-z]+ reasoning" }),
    ];

    expect(findLoadedConversationMessages(events, "[a-z]+", true)).toEqual([
      { eventIndex: 0, eventSeq: 1, role: "user" },
      { eventIndex: 1, eventSeq: 2, role: "assistant" },
      { eventIndex: 2, eventSeq: 3, role: "assistant" },
    ]);
    expect(findLoadedConversationMessages(events, "İx", true)).toEqual([
      { eventIndex: 0, eventSeq: 1, role: "user" },
    ]);
  });

  it("keeps case matching local and returns no candidates for an empty or absent literal", () => {
    const events = [event(1, "user", { text: "Synthetic Message" })];

    expect(findLoadedConversationMessages(events, "message", true)).toEqual([]);
    expect(findLoadedConversationMessages(events, "message", false)).toEqual([
      { eventIndex: 0, eventSeq: 1, role: "user" },
    ]);
    expect(findLoadedConversationMessages(events, "", false)).toEqual([]);
    expect(findLoadedConversationMessages(events, "[missing]", false)).toEqual([]);
  });

  it("preserves sparse loaded indices used by the paged timeline", () => {
    const candidates = [
      { event: event(2, "user", { text: "Synthetic match" }), eventIndex: 1 },
      { event: event(401, "assistant", { text: "Another synthetic match" }), eventIndex: 400 },
    ];

    expect(findLoadedConversationMessageCandidates(candidates, "match", false)).toEqual([
      { eventIndex: 1, eventSeq: 2, role: "user" },
      { eventIndex: 400, eventSeq: 401, role: "assistant" },
    ]);
  });
});
