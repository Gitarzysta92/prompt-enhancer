import { describe, expect, it, vi } from "vitest";
import { SYNTHETIC_CANDIDATES, SYNTHETIC_TASK_DECISIONS } from "./syntheticFixtures";
import { createHttpTransport } from "./httpTransport";
import {
  parseCandidateDecisionsResponse,
  TaskDecisionPayloadError,
} from "./taskDecisionContract";

const candidateId = SYNTHETIC_CANDIDATES[2].candidate.candidate_id;
const valid = () => ({
  candidate_id: candidateId,
  decisions: structuredClone(SYNTHETIC_TASK_DECISIONS[candidateId]),
});

describe("decision audit payload boundary", () => {
  it("accepts the exact content-free immutable receipt", () => {
    expect(parseCandidateDecisionsResponse(valid(), candidateId)).toEqual(valid());
  });

  it("rejects identity, ordering, private-extra, chronology, and lineage mutations", () => {
    const malformed: unknown[] = [
      { ...valid(), raw_source_text: "PRIVATE-AUDIT-CANARY" },
      { ...valid(), candidate_id: "f".repeat(64) },
      { ...valid(), decisions: [...valid().decisions, ...valid().decisions] },
      (() => {
        const value = valid();
        value.decisions[0].decided_at = "2040-01-01T15:05:00+01:00";
        return value;
      })(),
      (() => {
        const value = valid();
        value.decisions[0].decision_schema_version = "private schema text";
        return value;
      })(),
      (() => {
        const value = valid();
        value.decisions[0].candidate_ids = ["f".repeat(64)];
        return value;
      })(),
      (() => {
        const value = valid();
        value.decisions[0].revision_links.push({ ...value.decisions[0].revision_links[0] });
        return value;
      })(),
      (() => {
        const value = valid();
        value.decisions[0].action = "reject";
        return value;
      })(),
    ];
    for (const value of malformed) {
      let failure: unknown;
      try {
        parseCandidateDecisionsResponse(value, candidateId);
      } catch (error) {
        failure = error;
      }
      expect(failure).toBeInstanceOf(TaskDecisionPayloadError);
      expect(String(failure)).not.toContain("PRIVATE-AUDIT-CANARY");
    }
  });

  it("uses only the encoded same-origin local route", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        csrf_token: "synthetic-csrf-token",
        expires_in_seconds: 300,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(valid()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    const signal = new AbortController().signal;

    await expect(transport.getCandidateDecisions(candidateId, signal)).resolves.toEqual(valid());
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/v1/discovery/candidates/${candidateId}/decisions`,
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: "GET",
      credentials: "include",
      referrerPolicy: "no-referrer",
      signal,
    }));
  });
});
