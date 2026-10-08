import { describe, expect, it } from "vitest";

import {
  LocalModelCompatibilityPayloadError,
  parseLocalModelCompatibility,
} from "./localModelCompatibilityContract";

function catalog() {
  return {
    contract_version: "local-model-compatibility.v1",
    adapter: {
      adapter_id: "llama.cpp-openai-gguf",
      adapter_version: "llama.cpp-openai-gguf.v1",
      runtime_version: "synthetic-b9000",
      runtime_identity_state: "verified",
      runtime_binary_sha256: "c".repeat(64),
      capability_probe_version: "local-runtime-multimodal-probe.v2",
    },
    models: [{
      alias: "example-model",
      state: "supported",
      reason_code: "live_text_probe_verified",
      format: "gguf",
      architecture: "example-arch",
      tokenizer_model: "example-tokenizer",
      training_context_size: 32768,
      metadata_reader_version: "gguf-metadata.v1",
      artifact_identity_state: "verified_at_admission",
      artifact_sha256: "a".repeat(64),
      source_revision: "b".repeat(40),
      source_license: "apache-2.0",
      source_license_policy: "local-model-license-policy.v1",
      execution_state: "verified",
      context_counter_state: "verified",
    }],
  };
}

describe("parseLocalModelCompatibility", () => {
  it("accepts a live exact-artifact compatibility receipt", () => {
    expect(parseLocalModelCompatibility(catalog())).toMatchObject({
      models: [{ alias: "example-model", state: "supported" }],
    });
  });

  it.each([
    ["extra field", (value: ReturnType<typeof catalog>) => Object.assign(value.models[0], { path: "forbidden" })],
    ["unsupported verified execution", (value: ReturnType<typeof catalog>) => { value.models[0].state = "unknown"; }],
    ["unverified pinned digest", (value: ReturnType<typeof catalog>) => { value.models[0].artifact_identity_state = "unverified"; }],
    ["duplicate alias", (value: ReturnType<typeof catalog>) => { value.models.push({ ...value.models[0] }); }],
  ])("rejects %s", (_label, mutate) => {
    const value = catalog();
    mutate(value);
    expect(() => parseLocalModelCompatibility(value)).toThrow(LocalModelCompatibilityPayloadError);
  });
});
