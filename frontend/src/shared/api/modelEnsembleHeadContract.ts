import type {
  ModelEnsembleAttempt,
  ModelEnsembleAttemptSnapshot,
  ModelEnsembleAttemptStage,
  ModelEnsembleCanonicalHead,
} from "./contracts";
import { parseModelEnsembleWatch } from "./modelEnsembleWatchContract";

export class ModelEnsembleHeadPayloadError extends Error {
  constructor() {
    super("Canonical model ensemble head was invalid");
    this.name = "ModelEnsembleHeadPayloadError";
  }
}

type Row = Record<string, unknown>;
const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_CODE = /^[a-z0-9][a-z0-9._+:/-]{0,127}$/i;

function row(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new ModelEnsembleHeadPayloadError();
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ModelEnsembleHeadPayloadError();
  }
}

function safeId(value: unknown, nullable = false): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || !HEX_64.test(value)) throw new ModelEnsembleHeadPayloadError();
  return value;
}

function safeToken(value: unknown, nullable = false): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || !SAFE_CODE.test(value)) throw new ModelEnsembleHeadPayloadError();
  return value;
}

function repositoryId(value: unknown, nullable = false): string | null {
  if (nullable && value === null) return null;
  if (
    typeof value !== "string"
    || value.length < 3
    || value.length > 192
    || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(value)
    || value.includes("..")
  ) throw new ModelEnsembleHeadPayloadError();
  return value;
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new ModelEnsembleHeadPayloadError();
  }
  return value as number;
}

function finite(value: unknown, nullable = false): number | null {
  if (nullable && value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) throw new ModelEnsembleHeadPayloadError();
  return value;
}

function timestamp(value: unknown, nullable = false): string | null {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) {
    throw new ModelEnsembleHeadPayloadError();
  }
  const parsed = new Date(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  if (
    match === null || Number.isNaN(parsed.getTime())
    || parsed.getUTCFullYear() !== Number(match[1])
    || parsed.getUTCMonth() + 1 !== Number(match[2])
    || parsed.getUTCDate() !== Number(match[3])
    || parsed.getUTCHours() !== Number(match[4])
    || parsed.getUTCMinutes() !== Number(match[5])
    || parsed.getUTCSeconds() !== Number(match[6])
  ) throw new ModelEnsembleHeadPayloadError();
  return value;
}

function parseAttempt(value: unknown): ModelEnsembleAttempt {
  const attempt = row(value);
  exact(attempt, [
    "attempt_id", "watch_id", "generation", "state", "prior_head_run_id", "published_run_id",
    "progress_completed", "progress_total", "stage_count", "warning_count", "error_code",
    "requested_at", "started_at", "completed_at", "content_persisted",
  ]);
  safeId(attempt.attempt_id);
  safeId(attempt.watch_id);
  integer(attempt.generation, 1, 1_000_000_000);
  const state = String(attempt.state);
  if (!["running", "completed", "partial", "failed", "cancelled"].includes(state)) throw new ModelEnsembleHeadPayloadError();
  safeId(attempt.prior_head_run_id, true);
  safeId(attempt.published_run_id, true);
  const completed = integer(attempt.progress_completed, 0, 32);
  const total = integer(attempt.progress_total, 1, 32);
  if (completed > total) throw new ModelEnsembleHeadPayloadError();
  integer(attempt.stage_count, 0, 32);
  integer(attempt.warning_count, 0, 32);
  safeToken(attempt.error_code, true);
  timestamp(attempt.requested_at);
  timestamp(attempt.started_at);
  const completedAt = timestamp(attempt.completed_at, true);
  if ((state === "running") !== (completedAt === null)) throw new ModelEnsembleHeadPayloadError();
  if ((state === "completed" || state === "partial") && attempt.published_run_id === null) throw new ModelEnsembleHeadPayloadError();
  if (state === "completed" && (attempt.warning_count !== 0 || attempt.error_code !== null)) throw new ModelEnsembleHeadPayloadError();
  if (state === "partial" && (attempt.warning_count as number) < 1) throw new ModelEnsembleHeadPayloadError();
  if ((state === "failed" || state === "cancelled") && attempt.error_code === null) throw new ModelEnsembleHeadPayloadError();
  if (state === "running" && (attempt.published_run_id !== null || attempt.warning_count !== 0 || attempt.error_code !== null)) {
    throw new ModelEnsembleHeadPayloadError();
  }
  if (attempt.content_persisted !== false) throw new ModelEnsembleHeadPayloadError();
  return value as ModelEnsembleAttempt;
}

function parseStage(value: unknown): ModelEnsembleAttemptStage {
  const stage = row(value);
  exact(stage, [
    "stage_ordinal", "stage_key", "state", "model_key", "repository_id", "revision", "error_code",
    "device", "quantization", "inference_latency_ms", "peak_accelerator_memory_mb", "process_rss_mb",
    "evaluated_case_count", "contributed_case_count", "unloaded_after_stage", "completed_at",
  ]);
  integer(stage.stage_ordinal, 0, 31);
  safeToken(stage.stage_key);
  if (!["completed", "unavailable", "resource_exhausted", "failed", "cancelled"].includes(String(stage.state))) throw new ModelEnsembleHeadPayloadError();
  safeToken(stage.model_key, true);
  repositoryId(stage.repository_id, true);
  safeToken(stage.revision, true);
  safeToken(stage.error_code, true);
  if (stage.device !== null && !["cpu", "cuda", "mps"].includes(String(stage.device))) throw new ModelEnsembleHeadPayloadError();
  if (!["none", "bitsandbytes_nf4"].includes(String(stage.quantization))) throw new ModelEnsembleHeadPayloadError();
  finite(stage.inference_latency_ms, true);
  const peakMemory = finite(stage.peak_accelerator_memory_mb, true);
  const processRss = finite(stage.process_rss_mb, true);
  if ((peakMemory ?? 0) > 16_384 || (processRss ?? 0) > 32_768) throw new ModelEnsembleHeadPayloadError();
  const evaluated = stage.evaluated_case_count === null ? null : integer(stage.evaluated_case_count, 0, 100_000);
  const contributed = stage.contributed_case_count === null ? null : integer(stage.contributed_case_count, 0, 100_000);
  if (evaluated !== null && contributed !== null && contributed > evaluated) throw new ModelEnsembleHeadPayloadError();
  if (stage.unloaded_after_stage !== null && typeof stage.unloaded_after_stage !== "boolean") throw new ModelEnsembleHeadPayloadError();
  timestamp(stage.completed_at);
  if (stage.state === "completed" ? stage.error_code !== null : stage.error_code === null) {
    throw new ModelEnsembleHeadPayloadError();
  }
  return value as ModelEnsembleAttemptStage;
}

function parseStages(value: unknown): ModelEnsembleAttemptStage[] {
  if (!Array.isArray(value) || value.length > 32) throw new ModelEnsembleHeadPayloadError();
  const stages = value.map(parseStage);
  if (stages.some((stage, index) => stage.stage_ordinal !== index)) throw new ModelEnsembleHeadPayloadError();
  return stages;
}

export function parseModelEnsembleCanonicalHead(value: unknown): ModelEnsembleCanonicalHead {
  const head = row(value);
  exact(head, ["schema_version", "watch", "head_run_id", "head_generation", "latest_attempt", "stages", "content_persisted"]);
  if (head.schema_version !== "analysis-snapshot-v2" || head.content_persisted !== false) throw new ModelEnsembleHeadPayloadError();
  const watch = parseModelEnsembleWatch(head.watch);
  const runId = safeId(head.head_run_id, true);
  const generation = head.head_generation === null ? null : integer(head.head_generation, 1, 1_000_000_000);
  if ((runId === null) !== (generation === null) || (runId === null) !== !watch.has_result) throw new ModelEnsembleHeadPayloadError();
  const attempt = head.latest_attempt === null ? null : parseAttempt(head.latest_attempt);
  const stages = parseStages(head.stages);
  if (attempt === null) {
    if (stages.length !== 0) throw new ModelEnsembleHeadPayloadError();
  } else {
    if (attempt.watch_id !== watch.watch_id || attempt.generation !== watch.generation) throw new ModelEnsembleHeadPayloadError();
    if ((attempt.state === "completed" || attempt.state === "partial") && attempt.published_run_id !== runId) {
      throw new ModelEnsembleHeadPayloadError();
    }
    if (attempt.state === "running") {
      if (stages.length !== 0 || attempt.stage_count !== 0) throw new ModelEnsembleHeadPayloadError();
    } else if (attempt.stage_count !== stages.length) {
      throw new ModelEnsembleHeadPayloadError();
    }
    if (attempt.warning_count !== stages.filter((stage) => stage.state !== "completed").length) {
      throw new ModelEnsembleHeadPayloadError();
    }
  }
  return { ...head, watch, head_run_id: runId, head_generation: generation, latest_attempt: attempt, stages } as ModelEnsembleCanonicalHead;
}

export function parseModelEnsembleAttemptSnapshot(value: unknown): ModelEnsembleAttemptSnapshot {
  const snapshot = row(value);
  exact(snapshot, ["attempt", "stages"]);
  const attempt = parseAttempt(snapshot.attempt);
  const stages = parseStages(snapshot.stages);
  if (attempt.state === "running") {
    if (stages.length !== 0 || attempt.stage_count !== 0) throw new ModelEnsembleHeadPayloadError();
  } else if (attempt.stage_count !== stages.length) throw new ModelEnsembleHeadPayloadError();
  if (attempt.state !== "running" && attempt.warning_count !== stages.filter((stage) => stage.state !== "completed").length) {
    throw new ModelEnsembleHeadPayloadError();
  }
  return { attempt, stages };
}
