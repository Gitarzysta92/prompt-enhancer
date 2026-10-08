import { describe, expect, it, vi } from "vitest";
import { SYNTHETIC_MODEL_LAB_INVENTORY } from "./syntheticModelLabFixture";
import { createSyntheticTransport } from "./syntheticTransport";
import {
  createHttpTransport,
  parseModelLabInventory,
} from "./httpTransport";

const AUTH_RESPONSE = {
  csrf_token: "synthetic-csrf-token",
  expires_in_seconds: 300,
};

function jsonResponse(body: unknown, privateNoStore = false): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      ...(privateNoStore
        ? { "Cache-Control": "no-store, private", Pragma: "no-cache" }
        : {}),
    },
  });
}

function changed(path: string, value: unknown): unknown {
  const copy = structuredClone(SYNTHETIC_MODEL_LAB_INVENTORY) as Record<string, unknown>;
  if (path.startsWith("plans.0.")) {
    const key = path.slice("plans.0.".length);
    (copy.plans as Array<Record<string, unknown>>)[0][key] = value;
  } else {
    copy[path] = value;
  }
  return copy;
}

describe("Model Lab inventory contract", () => {
  it("returns an isolated synthetic fixture", async () => {
    const first = await createSyntheticTransport().getModelLabInventory?.();
    expect(first).toEqual(SYNTHETIC_MODEL_LAB_INVENTORY);
    if (first) first.plans[0].plan_key = "changed-in-test";
    await expect(createSyntheticTransport().getModelLabInventory?.()).resolves.toEqual(
      SYNTHETIC_MODEL_LAB_INVENTORY,
    );
  });

  it("accepts only canonical content-free synthetic totals", () => {
    expect(parseModelLabInventory(SYNTHETIC_MODEL_LAB_INVENTORY)).toEqual(
      SYNTHETIC_MODEL_LAB_INVENTORY,
    );
  });

  it.each([
    ["unexpected root field", { ...SYNTHETIC_MODEL_LAB_INVENTORY, session_id: "5".repeat(64) }],
    ["activation claim", changed("activation_allowed", true)],
    ["private scope", changed("session_data_read", true)],
    ["fabricated total", changed("model_run_count", 9)],
    ["unsafe plan version", changed("plans.0.plan_version", "https://invalid.example")],
    ["unsafe count", changed("plans.0.model_run_count", Number.MAX_SAFE_INTEGER + 1)],
    ["duplicate plan", {
      ...SYNTHETIC_MODEL_LAB_INVENTORY,
      registered_plan_count: 2,
      synthetic_execution_count: 4,
      model_run_count: 16,
      model_vote_count: 8,
      metric_estimate_count: 4,
      plans: [
        SYNTHETIC_MODEL_LAB_INVENTORY.plans[0],
        SYNTHETIC_MODEL_LAB_INVENTORY.plans[0],
      ],
    }],
  ])("rejects %s instead of displaying a zero", (_label, payload) => {
    expect(() => parseModelLabInventory(payload)).toThrow(
      /Model Lab inventory response was invalid/,
    );
  });

  it("requires private no-store response headers and uses GET only", async () => {
    const successFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_MODEL_LAB_INVENTORY, true));
    const transport = createHttpTransport({
      fetch: successFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });

    await expect(transport.getModelLabInventory?.()).resolves.toEqual(
      SYNTHETIC_MODEL_LAB_INVENTORY,
    );
    expect(successFetch.mock.calls[1][0]).toBe("/v1/estimators/plans");
    expect(successFetch.mock.calls[1][1]).toEqual(
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );

    const unsafeFetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse(AUTH_RESPONSE))
      .mockResolvedValueOnce(jsonResponse(SYNTHETIC_MODEL_LAB_INVENTORY));
    const unsafeTransport = createHttpTransport({
      fetch: unsafeFetch as unknown as typeof fetch,
      origin: "http://127.0.0.1:4173",
    });
    await expect(unsafeTransport.getModelLabInventory?.()).rejects.toThrow(
      /not cache-safe/,
    );
  });
});
