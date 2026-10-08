import { describe, expect, it, vi } from "vitest";
import { createHttpTransport } from "./httpTransport";
import type { AgentMessageSearchResult } from "./agentMessageSearchContract";

const csrf = { csrf_token: "synthetic-csrf-token", expires_in_seconds: 300, user_presence_confirmation_available: false, user_presence_confirmation_mode: "unavailable" };
const request = { query: "  retained\trequest ", projectId: "b".repeat(32), includeArchived: false, limit: 20, offset: 0 };
const response: AgentMessageSearchResult = { contract_version: "agent-message-search.v1", snapshot: "a".repeat(64), limit: 20, offset: 0, total: 0, next_offset: null, complete: true, matches: [] };
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store, private", "Pragma": "no-cache" } }); }
function transport(fetchMock: ReturnType<typeof vi.fn>) { return createHttpTransport({ fetch: fetchMock as unknown as typeof fetch, origin: "http://127.0.0.1:4173" }); }

describe("searchAgentSavedMessages HTTP transport", () => {
  it("POSTs the normalized query in the body, never the URL, and forwards signal", async () => {
    const signal = new AbortController().signal;
    const fetchMock = vi.fn().mockResolvedValueOnce(json(csrf)).mockResolvedValueOnce(json(response));
    await transport(fetchMock).searchAgentSavedMessages(request, signal);
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/agent/catalog/sessions/message-search");
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({ method: "POST", signal, body: JSON.stringify({ query: "retained request", project_id: request.projectId, include_archived: false, limit: 20, offset: 0 }) }));
  });

  it.each([
    [{ query: "" }], [{ query: "x", limit: 51 }], [{ query: "x", offset: 1 }],
  ])("rejects invalid request before network: %o", async (override) => {
    const fetchMock = vi.fn();
    await expect(transport(fetchMock).searchAgentSavedMessages({ ...request, ...override })).rejects.toMatchObject({ status: 422 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects malformed response and preserves structured HTTP errors", async () => {
    const malformed = vi.fn().mockResolvedValueOnce(json(csrf)).mockResolvedValueOnce(json({ ...response, extra: true }));
    await expect(transport(malformed).searchAgentSavedMessages({ query: "x" })).rejects.toMatchObject({ status: 200 });
    const conflict = vi.fn().mockResolvedValueOnce(json(csrf)).mockResolvedValueOnce(json({ detail: { code: "agent_catalog_revision_conflict" } }, 409));
    await expect(transport(conflict).searchAgentSavedMessages({ query: "x" })).rejects.toMatchObject({ status: 409 });
    const unavailable = vi.fn().mockResolvedValueOnce(json(csrf)).mockResolvedValueOnce(json({ detail: "synthetic unavailable" }, 503));
    await expect(transport(unavailable).searchAgentSavedMessages({ query: "x" })).rejects.toMatchObject({ status: 503 });
  });
});
