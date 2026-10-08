import type { DeviceMode, LocalModelPlacementAdmission } from "./contracts";

const ALIAS = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const TOP_LEVEL_KEYS = new Set([
  "contract_version", "alias", "context_size", "gpu_memory_free_mb",
  "actual_offload_verified", "options",
]);
const OPTION_KEYS = new Set([
  "device", "state", "reason_code", "recommended_gpu_layers",
  "estimated_vram_required_mb",
]);
const DEVICES: readonly DeviceMode[] = ["gpu", "split", "cpu"];
const REASONS = new Set([
  "cpu_available",
  "accelerator_evidence_unavailable",
  "model_size_unavailable",
  "layer_count_unavailable",
  "context_exceeds_model_metadata",
  "gpu_estimate_fits",
  "gpu_estimate_exceeds_free_memory",
  "split_estimate_available",
  "split_estimate_exceeds_free_memory",
  "owned_runtime_requires_cleanup_recheck",
]);

export class LocalModelPlacementPayloadError extends Error {
  constructor() {
    super("Local model placement payload was invalid");
    this.name = "LocalModelPlacementPayloadError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: Set<string>): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.size && actual.every((key) => keys.has(key));
}

function integer(value: unknown, minimum: number, maximum?: number): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && (maximum === undefined || value <= maximum);
}

function nullableInteger(value: unknown, maximum?: number): value is number | null {
  return value === null || integer(value, 0, maximum);
}

function option(value: unknown, expectedDevice: DeviceMode): boolean {
  if (
    !record(value)
    || !exact(value, OPTION_KEYS)
    || value.device !== expectedDevice
    || !["available", "blocked", "recheck_required"].includes(String(value.state))
    || !REASONS.has(String(value.reason_code))
    || !nullableInteger(value.recommended_gpu_layers, 4096)
    || !nullableInteger(value.estimated_vram_required_mb)
  ) return false;
  if (expectedDevice === "cpu") {
    if (value.state === "available") {
      return value.reason_code === "cpu_available"
        && value.recommended_gpu_layers === 0
        && value.estimated_vram_required_mb === 0;
    }
    return value.state === "blocked"
      && value.reason_code === "context_exceeds_model_metadata"
      && value.recommended_gpu_layers === null
      && value.estimated_vram_required_mb === null;
  }
  if (value.state === "recheck_required") {
    return value.reason_code === "owned_runtime_requires_cleanup_recheck"
      && value.recommended_gpu_layers === null
      && value.estimated_vram_required_mb === null;
  }
  if (value.state === "blocked") return value.recommended_gpu_layers === null;
  if (expectedDevice === "split") {
    return value.reason_code === "split_estimate_available"
      && integer(value.recommended_gpu_layers, 1, 4096)
      && integer(value.estimated_vram_required_mb, 0);
  }
  return value.reason_code === "gpu_estimate_fits"
    && integer(value.estimated_vram_required_mb, 0);
}

export function parseLocalModelPlacement(value: unknown): LocalModelPlacementAdmission {
  if (
    !record(value)
    || !exact(value, TOP_LEVEL_KEYS)
    || value.contract_version !== "local-model-placement.v1"
    || typeof value.alias !== "string"
    || !ALIAS.test(value.alias)
    || !integer(value.context_size, 512, 131072)
    || !nullableInteger(value.gpu_memory_free_mb)
    || value.actual_offload_verified !== false
    || !Array.isArray(value.options)
    || value.options.length !== DEVICES.length
    || !value.options.every((candidate, index) => option(candidate, DEVICES[index]))
  ) throw new LocalModelPlacementPayloadError();
  return value as LocalModelPlacementAdmission;
}
