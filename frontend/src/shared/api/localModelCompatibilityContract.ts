import type { LocalModelCompatibilityCatalog } from "./contracts";

const ALIAS = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const SHA256 = /^[a-f0-9]{64}$/u;
const REVISION = /^[a-f0-9]{40}$/u;
const CATALOG_KEYS = new Set(["contract_version", "adapter", "models"]);
const ADAPTER_KEYS = new Set([
  "adapter_id", "adapter_version", "runtime_version", "runtime_identity_state",
  "runtime_binary_sha256", "capability_probe_version",
]);
const MODEL_KEYS = new Set([
  "alias", "state", "reason_code", "format", "architecture", "tokenizer_model",
  "training_context_size", "metadata_reader_version", "artifact_identity_state",
  "artifact_sha256", "source_revision", "source_license", "source_license_policy",
  "execution_state", "context_counter_state",
]);
const REASONS = new Set([
  "live_text_probe_verified", "model_not_executed", "live_text_probe_failed",
  "runtime_execution_failed", "runtime_unavailable", "artifact_missing",
]);

export class LocalModelCompatibilityPayloadError extends Error {
  constructor() {
    super("Local model compatibility payload was invalid");
    this.name = "LocalModelCompatibilityPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function nullableText(value: unknown, maximum: number): boolean {
  return value === null || typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function adapter(value: unknown): boolean {
  if (!(record(value)
    && exact(value, ADAPTER_KEYS)
    && value.adapter_id === "llama.cpp-openai-gguf"
    && value.adapter_version === "llama.cpp-openai-gguf.v1"
    && nullableText(value.runtime_version, 120)
    && ["verified", "unknown"].includes(String(value.runtime_identity_state))
    && value.capability_probe_version === "local-runtime-multimodal-probe.v2")) return false;
  return value.runtime_identity_state === "verified"
    ? typeof value.runtime_binary_sha256 === "string" && SHA256.test(value.runtime_binary_sha256)
    : value.runtime_binary_sha256 === null;
}

function model(value: unknown): boolean {
  if (
    !record(value)
    || !exact(value, MODEL_KEYS)
    || typeof value.alias !== "string" || !ALIAS.test(value.alias)
    || !["supported", "unsupported", "unknown"].includes(String(value.state))
    || typeof value.reason_code !== "string" || !REASONS.has(value.reason_code)
    || value.format !== "gguf"
    || !nullableText(value.architecture, 120)
    || !nullableText(value.tokenizer_model, 120)
    || !(value.training_context_size === null
      || typeof value.training_context_size === "number"
      && Number.isSafeInteger(value.training_context_size)
      && value.training_context_size >= 1
      && value.training_context_size <= 16_777_216)
    || !(value.metadata_reader_version === null || value.metadata_reader_version === "gguf-metadata.v1")
    || !["verified_at_admission", "unverified"].includes(String(value.artifact_identity_state))
    || !["verified", "failed", "not_run"].includes(String(value.execution_state))
    || !["verified", "unsupported", "failed", "not_run"].includes(String(value.context_counter_state))
  ) return false;
  const supported = value.state === "supported";
  if (supported !== (
    value.reason_code === "live_text_probe_verified" && value.execution_state === "verified"
  )) return false;
  if (value.artifact_identity_state === "verified_at_admission") {
    return typeof value.artifact_sha256 === "string" && SHA256.test(value.artifact_sha256)
      && typeof value.source_revision === "string" && REVISION.test(value.source_revision)
      && nullableText(value.source_license, 40) && value.source_license !== null
      && nullableText(value.source_license_policy, 64) && value.source_license_policy !== null;
  }
  return value.artifact_sha256 === null
    && value.source_revision === null
    && value.source_license === null
    && value.source_license_policy === null;
}

export function parseLocalModelCompatibility(value: unknown): LocalModelCompatibilityCatalog {
  if (
    !record(value)
    || !exact(value, CATALOG_KEYS)
    || value.contract_version !== "local-model-compatibility.v1"
    || !adapter(value.adapter)
    || !Array.isArray(value.models)
    || !value.models.every(model)
  ) throw new LocalModelCompatibilityPayloadError();
  const aliases = value.models.map((item) => (item as Record<string, unknown>).alias);
  if (new Set(aliases).size !== aliases.length) throw new LocalModelCompatibilityPayloadError();
  return value as unknown as LocalModelCompatibilityCatalog;
}
