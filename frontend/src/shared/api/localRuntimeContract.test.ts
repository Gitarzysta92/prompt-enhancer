import { describe, expect, it } from "vitest";

import {
  LocalRuntimePayloadError,
  parseLocalRuntimeCoordinator,
} from "./localRuntimeContract";

function readyRuntime() {
  return {
    contract_version: "local-runtime-coordinator.v2",
    revision: 4,
    state: "ready",
    requested: {
      alias: "example-model",
      device: "split",
      gpu_layers: 21,
      context_size: 8192,
    },
    served: {
      alias: "example-model",
      device: "split",
      gpu_layers: 21,
      context_size: 8192,
      started_at: "2026-08-27T09:00:00+00:00",
      pid: 1234,
    },
    cleanup: {
      state: "measured",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: 2048,
      gpu_memory_free_after_mb: 4096,
      gpu_memory_released_mb: 2048,
    },
    capabilities: {
      state: "verified",
      probe_version: "local-runtime-multimodal-probe.v2",
      text: true,
      tools: true,
      vision: false,
      audio: false,
      recording: false,
      structured_output: false,
      error_code: null as string | null,
    },
    context: {
      state: "unknown",
      used_tokens: null,
      limit_tokens: 8192,
      requested_output_tokens: null,
      available_output_tokens: null,
      source: "runtime_limit_only",
      scope: "runtime_limit",
      policy: "runtime_enforced",
      compacted_messages: 0,
      reason_code: "no_request_measured",
    },
    active_requests: 0,
    last_error_code: null,
  };
}

describe("parseLocalRuntimeCoordinator", () => {
  it("accepts coherent requested-versus-served runtime truth", () => {
    expect(parseLocalRuntimeCoordinator(readyRuntime())).toMatchObject({
      state: "ready",
      served: { alias: "example-model" },
      context: { used_tokens: null, limit_tokens: 8192 },
    });
  });

  it.each([
    ["extra field", (value: ReturnType<typeof readyRuntime>) => Object.assign(value, { transcript: "no" })],
    ["wrong served context", (value: ReturnType<typeof readyRuntime>) => { value.context.limit_tokens = 4096; }],
    ["unverified ready", (value: ReturnType<typeof readyRuntime>) => { value.capabilities.state = "not_probed"; value.capabilities.text = false; value.capabilities.tools = false; }],
    ["incoherent GPU receipt", (value: ReturnType<typeof readyRuntime>) => { value.cleanup.gpu_memory_released_mb = 1; }],
    ["advertised failed capability", (value: ReturnType<typeof readyRuntime>) => { value.capabilities.state = "failed"; value.capabilities.error_code = "runtime_capability_probe_failed"; }],
    ["recording without audio input", (value: ReturnType<typeof readyRuntime>) => { value.capabilities.recording = true; }],
    ["invalid alias", (value: ReturnType<typeof readyRuntime>) => { value.served.alias = "Bad Alias"; }],
  ])("rejects %s", (_label, mutate) => {
    const value = readyRuntime();
    mutate(value);
    expect(() => parseLocalRuntimeCoordinator(value)).toThrow(LocalRuntimePayloadError);
  });

  it("accepts idle truth without inventing context usage", () => {
    const value = readyRuntime();
    value.state = "idle";
    value.requested = null as unknown as typeof value.requested;
    value.served = null as unknown as typeof value.served;
    value.cleanup = {
      state: "not_required",
      process_exit_confirmed: true,
      gpu_memory_free_before_mb: null as unknown as number,
      gpu_memory_free_after_mb: null as unknown as number,
      gpu_memory_released_mb: null as unknown as number,
    };
    value.capabilities = {
      ...value.capabilities,
      state: "not_probed",
      text: false,
      tools: false,
      error_code: null,
    };
    value.context.limit_tokens = null as unknown as number;
    value.context.reason_code = "runtime_not_served";
    expect(parseLocalRuntimeCoordinator(value).state).toBe("idle");
  });

  it("accepts exact last-request token evidence and rejects arithmetic drift", () => {
    const value = readyRuntime();
    Object.assign(value.context, {
      state: "known",
      used_tokens: 2048,
      requested_output_tokens: 1024,
      available_output_tokens: 6144,
      source: "runtime_chat_input_tokens",
      scope: "last_request",
      policy: "exact_admitted",
      compacted_messages: 0,
      reason_code: null,
    });
    expect(parseLocalRuntimeCoordinator(value).context.used_tokens).toBe(2048);
    Object.assign(value.context, { available_output_tokens: 6000 });
    expect(() => parseLocalRuntimeCoordinator(value)).toThrow(LocalRuntimePayloadError);
  });
});
