import { describe, expect, it } from "vitest";
import { AgentMessageSearchPayloadError, parseAgentMessageSearchResult } from "./agentMessageSearchContract";

const request = { query: "synthetic", limit: 20, offset: 0 };
const match = { session_id: "1".repeat(32), project_id: "2".repeat(32), project_name: "Synthetic project", title: "Synthetic chat", match_event_seq: 9, history_revision: 2, role: "user", excerpt: "Synthetic bounded excerpt." };
const result = { contract_version: "agent-message-search.v1", snapshot: "a".repeat(64), limit: 20, offset: 0, total: 1, next_offset: null, complete: true, matches: [match] };

describe("agent message search contract", () => {
  it("accepts sparse event sequence and history revision values", () => {
    expect(parseAgentMessageSearchResult(result, request).matches[0].match_event_seq).toBe(9);
  });

  it("rejects unknown fields, duplicate sessions, and invalid pagination", () => {
    expect(() => parseAgentMessageSearchResult({ ...result, extra: true }, request)).toThrow(AgentMessageSearchPayloadError);
    expect(() => parseAgentMessageSearchResult({ ...result, matches: [match, { ...match, project_id: "3".repeat(32) }] }, request)).toThrow(AgentMessageSearchPayloadError);
    expect(() => parseAgentMessageSearchResult({ ...result, total: 2, complete: false, next_offset: null }, request)).toThrow(AgentMessageSearchPayloadError);
  });
});
