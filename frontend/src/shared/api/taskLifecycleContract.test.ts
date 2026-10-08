import { describe, expect, it, vi } from "vitest";
import { SYNTHETIC_TASK_LIFECYCLES } from "./syntheticFixtures";
import { createHttpTransport, TransportError } from "./httpTransport";
import {
  parseTaskLifecycleListResponse,
  parseTaskLifecycleMutationResponse,
  parseTaskLifecycleSnapshot,
  TaskLifecyclePayloadError,
} from "./taskLifecycleContract";

const snapshot = () => structuredClone(SYNTHETIC_TASK_LIFECYCLES[0]);
const taskId = SYNTHETIC_TASK_LIFECYCLES[0].task_id;

describe("task lifecycle payload boundary", () => {
  it("accepts the exact content-free linear snapshot and list page", () => {
    const value = snapshot();
    expect(parseTaskLifecycleSnapshot(value, { taskId, revision: 1 })).toEqual(value);
    expect(parseTaskLifecycleListResponse(
      { lifecycles: [value], limit: 100, offset: 0 },
      { limit: 100, offset: 0 },
    ).lifecycles).toEqual([value]);
  });

  it("rejects extras, illegal chronology, foreign identity, and false completeness", () => {
    const malformed: unknown[] = [
      { ...snapshot(), transcript: "PRIVATE-LIFECYCLE-CANARY" },
      { ...snapshot(), task_id: "f".repeat(64) },
      { ...snapshot(), current_state: "done" },
      { ...snapshot(), events_complete: false },
      (() => {
        const value = snapshot();
        value.events[1].sequence = 4;
        return value;
      })(),
      (() => {
        const value = snapshot();
        value.events[1].previous_event_id = "f".repeat(64);
        return value;
      })(),
      (() => {
        const value = snapshot();
        value.events[1].prior_state = null;
        return value;
      })(),
      (() => {
        const value = snapshot();
        value.events[1].prior_state = "in_progress";
        return value;
      })(),
      (() => {
        const value = snapshot();
        const predecessor = value.events[0];
        value.events[1] = {
          ...value.events[1],
          event_kind: "correction",
          supersedes_event_id: predecessor.event_id,
          prior_state: predecessor.resulting_state,
          resulting_state: "done",
        };
        value.current_state = "done";
        return value;
      })(),
      (() => {
        const value = snapshot();
        value.events[1].task_input_fingerprint = "f".repeat(64);
        return value;
      })(),
      (() => {
        const value = snapshot();
        value.events[0].created_at = "2040-01-01T15:05:10+01:00";
        return value;
      })(),
    ];
    for (const value of malformed) {
      let failure: unknown;
      try {
        parseTaskLifecycleSnapshot(value, { taskId, revision: 1 });
      } catch (error) {
        failure = error;
      }
      expect(failure).toBeInstanceOf(TaskLifecyclePayloadError);
      expect(String(failure)).not.toContain("PRIVATE-LIFECYCLE-CANARY");
    }
  });

  it("validates mutation identity, kind, state, and receipt head", () => {
    const event = snapshot().events[1];
    const valid = { event, head_event_id: event.event_id, state: "in_progress" as const };
    expect(parseTaskLifecycleMutationResponse(valid, {
      taskId,
      revision: 1,
      eventKind: "transition",
      expectedHeadEventId: event.previous_event_id,
      requestedState: "in_progress",
    })).toEqual(valid);
    expect(() => parseTaskLifecycleMutationResponse(
      { ...valid, head_event_id: "f".repeat(64) },
      {
        taskId,
        revision: 1,
        eventKind: "transition",
        expectedHeadEventId: event.previous_event_id,
        requestedState: "in_progress",
      },
    )).toThrow(TaskLifecyclePayloadError);

    expect(() => parseTaskLifecycleMutationResponse(valid, {
      taskId,
      revision: 1,
      eventKind: "transition",
      expectedHeadEventId: "f".repeat(64),
      requestedState: "in_progress",
    })).toThrow(TaskLifecyclePayloadError);

    const correction = {
      ...event,
      event_id: "e".repeat(64),
      sequence: 3,
      event_kind: "correction" as const,
      prior_state: "in_progress" as const,
      resulting_state: "backlog" as const,
      previous_event_id: event.event_id,
      supersedes_event_id: event.event_id,
    };
    const correctionResponse = {
      event: correction,
      head_event_id: correction.event_id,
      state: "backlog" as const,
    };
    expect(parseTaskLifecycleMutationResponse(correctionResponse, {
      taskId,
      revision: 1,
      eventKind: "correction",
      expectedHeadEventId: event.event_id,
      correctionPriorState: "in_progress",
      correctionResultingState: "backlog",
    })).toEqual(correctionResponse);
    expect(() => parseTaskLifecycleMutationResponse(correctionResponse, {
      taskId,
      revision: 1,
      eventKind: "correction",
      expectedHeadEventId: event.event_id,
      correctionPriorState: "in_progress",
      correctionResultingState: null,
    })).toThrow(TaskLifecyclePayloadError);
  });

  it("uses only private same-origin GET and CSRF-bound idempotent POST routes", async () => {
    const lifecycle = snapshot();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        csrf_token: "synthetic-csrf-token",
        expires_in_seconds: 300,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        lifecycles: [lifecycle], limit: 100, offset: 0,
      }), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store, private",
          Pragma: "no-cache",
        },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        event: lifecycle.events[1],
        state: "in_progress",
        head_event_id: lifecycle.events[1].event_id,
      }), {
        status: 201,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store, private",
          Pragma: "no-cache",
        },
      }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.listTaskLifecycles()).resolves.toMatchObject({
      lifecycles: [{ current_state: "in_progress" }],
    });
    await expect(transport.transitionTaskLifecycle(
      taskId,
      1,
      lifecycle.events[0].event_id,
      "in_progress",
      "dashboard-task-lifecycle-example",
    )).resolves.toMatchObject({ state: "in_progress" });

    expect(fetchMock.mock.calls[1][0]).toBe(
      "/v1/task-lifecycles?limit=100&offset=0&event_limit=100",
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      `/v1/tasks/${taskId}/revisions/1/lifecycle/transitions`,
    );
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: "POST",
      cache: "no-store",
      credentials: "include",
      referrerPolicy: "no-referrer",
      headers: expect.objectContaining({
        "Idempotency-Key": "dashboard-task-lifecycle-example",
        "X-Prompt-Enhancer-CSRF": "synthetic-csrf-token",
      }),
    }));
    expect(JSON.parse(String(fetchMock.mock.calls[2][1].body))).toEqual({
      expected_head_event_id: lifecycle.events[0].event_id,
      state: "in_progress",
    });
  });

  it("fails closed when a lifecycle response is cacheable", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        csrf_token: "synthetic-csrf-token",
        expires_in_seconds: 300,
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        lifecycles: [], limit: 100, offset: 0,
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const transport = createHttpTransport({
      fetch: fetchMock as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(transport.listTaskLifecycles()).rejects.toBeInstanceOf(TransportError);
  });
});
