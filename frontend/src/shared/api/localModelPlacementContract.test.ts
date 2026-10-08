import { describe, expect, it } from "vitest";

import {
  LocalModelPlacementPayloadError,
  parseLocalModelPlacement,
} from "./localModelPlacementContract";

function admission() {
  return {
    contract_version: "local-model-placement.v1",
    alias: "example-model",
    context_size: 8192,
    gpu_memory_free_mb: 12000,
    actual_offload_verified: false,
    options: [
      { device: "gpu", state: "available", reason_code: "gpu_estimate_fits", recommended_gpu_layers: 8, estimated_vram_required_mb: 6000 },
      { device: "split", state: "available", reason_code: "split_estimate_available", recommended_gpu_layers: 6, estimated_vram_required_mb: 5000 },
      { device: "cpu", state: "available", reason_code: "cpu_available", recommended_gpu_layers: 0, estimated_vram_required_mb: 0 },
    ],
  };
}

describe("parseLocalModelPlacement", () => {
  it("accepts the exact, explicitly unverified placement contract", () => {
    expect(parseLocalModelPlacement(admission())).toMatchObject({
      alias: "example-model",
      actual_offload_verified: false,
    });
  });

  it.each([
    { ...admission(), actual_offload_verified: true },
    { ...admission(), private_path: "D:/private/model.gguf" },
    { ...admission(), options: admission().options.slice().reverse() },
    { ...admission(), options: admission().options.map((item, index) => index === 1 ? { ...item, recommended_gpu_layers: 0 } : item) },
    { ...admission(), options: admission().options.map((item, index) => index === 2 ? { ...item, recommended_gpu_layers: 1 } : item) },
  ])("rejects malformed or truth-inflating payloads", (value) => {
    expect(() => parseLocalModelPlacement(value)).toThrow(LocalModelPlacementPayloadError);
  });
});
