import type { ModelEnsembleWatch, ModelEnsembleWatchSnapshot } from "./contracts";
import { parseModelEnsembleRun } from "./modelEnsembleContract";

export class ModelEnsembleWatchPayloadError extends Error {
  constructor() {
    super("Continuous model ensemble response was invalid");
    this.name = "ModelEnsembleWatchPayloadError";
  }
}

type Row = Record<string, unknown>;
const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_REASON = /^[a-z0-9][a-z0-9._-]{0,63}$/;

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ModelEnsembleWatchPayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ModelEnsembleWatchPayloadError();
  }
}

function timestamp(value: unknown): void {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) {
    throw new ModelEnsembleWatchPayloadError();
  }
  const parsed = new Date(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  if (
    match === null || Number.isNaN(parsed.getTime()) ||
    parsed.getUTCFullYear() !== Number(match[1]) ||
    parsed.getUTCMonth() + 1 !== Number(match[2]) ||
    parsed.getUTCDate() !== Number(match[3]) ||
    parsed.getUTCHours() !== Number(match[4]) ||
    parsed.getUTCMinutes() !== Number(match[5]) ||
    parsed.getUTCSeconds() !== Number(match[6])
  ) throw new ModelEnsembleWatchPayloadError();
}

export function parseModelEnsembleWatch(value: unknown): ModelEnsembleWatch {
  const watch = row(value);
  exact(watch, [
    "watch_id", "provider", "project_id", "session_id", "max_messages", "state", "generation",
    "progress_completed", "progress_total", "has_result", "last_error_code",
    "next_check_at", "updated_at", "serial_model_execution",
    "process_isolated_model_release", "cuda_resource_retry_on_cpu",
    "content_persisted", "calibrated_as_truth",
    ...("quarantined" in watch || "quarantine_reason_code" in watch
      ? ["quarantined", "quarantine_reason_code"] : []),
  ]);
  for (const key of ["watch_id", "project_id", "session_id"] as const) {
    if (typeof watch[key] !== "string" || !HEX_64.test(watch[key])) {
      throw new ModelEnsembleWatchPayloadError();
    }
  }
  if (
    !["codex", "claude_code"].includes(String(watch.provider)) ||
    !Number.isInteger(watch.max_messages) ||
    (watch.max_messages as number) < 1 || (watch.max_messages as number) > 100 ||
    !["queued", "running", "idle", "failed", "disabled"].includes(String(watch.state)) ||
    !Number.isInteger(watch.generation) || (watch.generation as number) < 0 ||
    !Number.isInteger(watch.progress_completed) || (watch.progress_completed as number) < 0 ||
    (watch.progress_completed as number) > 10 || watch.progress_total !== 10 ||
    typeof watch.has_result !== "boolean" ||
    (watch.last_error_code !== null &&
      (typeof watch.last_error_code !== "string" || !SAFE_REASON.test(watch.last_error_code))) ||
    watch.serial_model_execution !== true ||
    watch.process_isolated_model_release !== true ||
    watch.cuda_resource_retry_on_cpu !== true ||
    watch.content_persisted !== false || watch.calibrated_as_truth !== false
  ) throw new ModelEnsembleWatchPayloadError();
  if ("quarantined" in watch) {
    if (
      (watch.quarantined !== null && typeof watch.quarantined !== "boolean") ||
      (watch.quarantine_reason_code !== null &&
        (typeof watch.quarantine_reason_code !== "string" || !SAFE_REASON.test(watch.quarantine_reason_code))) ||
      (watch.quarantined === true) !== (watch.quarantine_reason_code !== null) ||
      (watch.quarantined === true && !["failed", "disabled"].includes(String(watch.state)))
    ) throw new ModelEnsembleWatchPayloadError();
  }
  timestamp(watch.next_check_at);
  timestamp(watch.updated_at);
  return value as ModelEnsembleWatch;
}

export function parseModelEnsembleWatchSnapshot(value: unknown): ModelEnsembleWatchSnapshot {
  const snapshot = row(value);
  exact(snapshot, ["watch", "latest_run"]);
  const watch = parseModelEnsembleWatch(snapshot.watch);
  if (snapshot.latest_run === null) {
    if (watch.has_result !== false) throw new ModelEnsembleWatchPayloadError();
  } else {
    parseModelEnsembleRun(snapshot.latest_run);
    if (watch.has_result !== true) throw new ModelEnsembleWatchPayloadError();
  }
  return value as ModelEnsembleWatchSnapshot;
}
