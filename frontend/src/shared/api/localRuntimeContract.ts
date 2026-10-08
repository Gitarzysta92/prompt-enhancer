import type { LocalRuntimeCoordinatorStatus, RuntimeContextStatus } from "./contracts";

const ALIAS = /^[a-z0-9][a-z0-9._-]{0,63}$/u;
const ERROR_CODE = /^[a-z0-9_]{1,64}$/u;
const STATUS_KEYS = new Set([
  "contract_version", "revision", "state", "requested", "served", "cleanup",
  "capabilities", "context", "active_requests", "last_error_code",
]);
const SELECTION_KEYS = new Set(["alias", "device", "gpu_layers", "context_size"]);
const SERVED_KEYS = new Set([...SELECTION_KEYS, "started_at", "pid"]);
const CLEANUP_KEYS = new Set([
  "state", "process_exit_confirmed", "gpu_memory_free_before_mb",
  "gpu_memory_free_after_mb", "gpu_memory_released_mb",
]);
const CAPABILITY_KEYS = new Set([
  "state", "probe_version", "text", "tools", "vision", "audio", "recording",
  "structured_output", "error_code",
]);
const CONTEXT_KEYS = new Set([
  "state", "used_tokens", "limit_tokens", "requested_output_tokens",
  "available_output_tokens", "source", "scope", "policy",
  "compacted_messages", "reason_code",
]);
const UNKNOWN_CONTEXT_REASONS = new Set([
  "runtime_not_served", "no_request_measured", "input_counter_unavailable",
  "input_counter_invalid", "input_counter_failed",
]);

export class LocalRuntimePayloadError extends Error {
  constructor() {
    super("Local runtime payload was invalid");
    this.name = "LocalRuntimePayloadError";
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

function nullableInteger(value: unknown): value is number | null {
  return value === null || integer(value, 0);
}

function signedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number"
    && Number.isSafeInteger(value)
    && value >= minimum
    && value <= maximum;
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function selection(value: unknown, served: boolean): value is Record<string, unknown> {
  if (
    !record(value) || !exact(value, served ? SERVED_KEYS : SELECTION_KEYS)
    || typeof value.alias !== "string" || !ALIAS.test(value.alias)
    || !["cpu", "gpu", "split"].includes(String(value.device))
    || !integer(value.gpu_layers, 0, 4096)
    || !integer(value.context_size, 512, 131072)
  ) return false;
  return !served || (timestamp(value.started_at) && integer(value.pid, 1));
}

function cleanup(value: unknown): value is Record<string, unknown> {
  if (
    !record(value) || !exact(value, CLEANUP_KEYS)
    || !["not_required", "measured", "unknown", "failed"].includes(String(value.state))
    || typeof value.process_exit_confirmed !== "boolean"
    || !nullableInteger(value.gpu_memory_free_before_mb)
    || !nullableInteger(value.gpu_memory_free_after_mb)
    || !nullableInteger(value.gpu_memory_released_mb)
  ) return false;
  const measurements = [
    value.gpu_memory_free_before_mb,
    value.gpu_memory_free_after_mb,
    value.gpu_memory_released_mb,
  ];
  if (value.state === "measured") {
    return value.process_exit_confirmed
      && measurements.every((item) => typeof item === "number")
      && Number(value.gpu_memory_free_after_mb) - Number(value.gpu_memory_free_before_mb)
        === value.gpu_memory_released_mb;
  }
  if (measurements.some((item) => item !== null)) return false;
  return value.state !== "failed" || value.process_exit_confirmed === false;
}

function capabilities(value: unknown): value is Record<string, unknown> {
  if (
    !record(value) || !exact(value, CAPABILITY_KEYS)
    || !["not_probed", "verified", "failed"].includes(String(value.state))
    || value.probe_version !== "local-runtime-multimodal-probe.v2"
    || !["text", "tools", "vision", "audio", "recording", "structured_output"]
      .every((key) => typeof value[key] === "boolean")
    || !(value.error_code === null
      || typeof value.error_code === "string" && ERROR_CODE.test(value.error_code))
  ) return false;
  const advertised = ["text", "tools", "vision", "audio", "recording", "structured_output"]
    .some((key) => value[key] === true);
  if (value.recording === true && value.audio !== true) return false;
  if (value.state === "verified") return value.text === true && value.error_code === null;
  if (advertised) return false;
  return value.state === "failed" ? value.error_code !== null : value.error_code === null;
}

function context(value: unknown): value is Record<string, unknown> {
  if (
    !record(value)
    || !exact(value, CONTEXT_KEYS)
    || !["unknown", "known"].includes(String(value.state))
    || !(value.limit_tokens === null || integer(value.limit_tokens, 512, 131072))
    || !integer(value.compacted_messages, 0, 10_000)
  ) return false;
  if (value.state === "unknown") {
    return value.used_tokens === null
      && value.requested_output_tokens === null
      && value.available_output_tokens === null
      && value.source === "runtime_limit_only"
      && value.scope === "runtime_limit"
      && value.policy === "runtime_enforced"
      && value.compacted_messages === 0
      && typeof value.reason_code === "string"
      && UNKNOWN_CONTEXT_REASONS.has(value.reason_code);
  }
  if (
    !integer(value.used_tokens, 0, 24 * 1024 * 1024)
    || !integer(value.limit_tokens, 512, 131072)
    || !(value.requested_output_tokens === null || integer(value.requested_output_tokens, 0))
    || !signedInteger(value.available_output_tokens, -(24 * 1024 * 1024), 131072)
    || value.available_output_tokens !== value.limit_tokens - value.used_tokens
    || value.source !== "runtime_chat_input_tokens"
    || value.scope !== "last_request"
    || !["exact_admitted", "exact_compacted", "exact_refused"].includes(String(value.policy))
  ) return false;
  const overflow = value.available_output_tokens < 0
    || (typeof value.requested_output_tokens === "number"
      && value.requested_output_tokens > value.available_output_tokens);
  if (value.policy === "exact_refused") {
    return overflow && value.reason_code === "context_window_exceeded";
  }
  return !overflow
    && value.reason_code === null
    && (value.policy === "exact_compacted"
      ? value.compacted_messages > 0
      : value.compacted_messages === 0);
}

export function parseRuntimeContextStatus(value: unknown): RuntimeContextStatus {
  if (!context(value)) throw new LocalRuntimePayloadError();
  return value as unknown as RuntimeContextStatus;
}

export function parseLocalRuntimeCoordinator(value: unknown): LocalRuntimeCoordinatorStatus {
  if (
    !record(value) || !exact(value, STATUS_KEYS)
    || value.contract_version !== "local-runtime-coordinator.v2"
    || !integer(value.revision, 0)
    || ![
      "idle", "draining", "unloading", "loading", "ready", "failed",
      "cleanup_unknown", "quarantined",
    ].includes(String(value.state))
    || !(value.requested === null || selection(value.requested, false))
    || !(value.served === null || selection(value.served, true))
    || !cleanup(value.cleanup)
    || !capabilities(value.capabilities)
    || !context(value.context)
    || !integer(value.active_requests, 0)
    || !(value.last_error_code === null
      || typeof value.last_error_code === "string" && ERROR_CODE.test(value.last_error_code))
  ) throw new LocalRuntimePayloadError();

  const served = value.served as Record<string, unknown> | null;
  const runtimeContext = value.context as Record<string, unknown>;
  const runtimeCapabilities = value.capabilities as Record<string, unknown>;
  const runtimeCleanup = value.cleanup as Record<string, unknown>;
  if (
    (value.state === "ready" && (served === null || runtimeCapabilities.state !== "verified"))
    || (value.state === "idle" && served !== null)
    || (served !== null && runtimeContext.limit_tokens !== served.context_size)
    || (served === null && runtimeContext.limit_tokens !== null)
    || (served === null && runtimeContext.reason_code !== "runtime_not_served")
    || (served !== null && runtimeContext.reason_code === "runtime_not_served")
    || (value.state === "cleanup_unknown" && runtimeCleanup.state !== "unknown")
    || (value.state === "quarantined" && runtimeCleanup.state !== "failed")
  ) throw new LocalRuntimePayloadError();
  return value as unknown as LocalRuntimeCoordinatorStatus;
}
