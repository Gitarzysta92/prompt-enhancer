import type {
  ModelEnsembleAttemptStage,
  ModelEnsembleRun,
} from "../../shared/api/contracts";

/**
 * Presentation model for the model stages behind one sealed snapshot or the
 * latest durable attempt. Pure data: no React and no transport.
 *
 * The grouping and role heuristics live here exactly once so the radar's
 * "at least two small experts" gate and the Models drawer can never disagree
 * about which stage is the selective deep judge. Everything stays a receipt
 * fact: missing counts remain `null`, never zero.
 */
export const MODEL_ENSEMBLE_STAGE_GROUPS = [
  "Factor models",
  "Challengers",
  "Deep judge",
  "Legacy stages",
] as const;

export type ModelEnsembleStageGroup = (typeof MODEL_ENSEMBLE_STAGE_GROUPS)[number];

export interface ModelEnsembleStage {
  modelKey: string;
  repositoryId: string;
  revision: string;
  status: "completed" | "unavailable" | "resource_exhausted" | "failed" | "cancelled";
  errorCode: string | null;
  device: "cpu" | "cuda" | "mps" | null;
  quantization: string;
  latency: number | null;
  acceleratorMemory: number | null;
  rss: number | null;
  /** Whether the receipt explicitly records unloading after the stage. */
  unloaded: boolean | null;
  evaluatedCases: number | null;
  contributedCases: number | null;
  group: ModelEnsembleStageGroup;
  role: string;
}

/** Where the displayed stage receipts come from. */
export type ModelEnsembleStageSource = "attempt" | "sealed";

export interface ModelEnsembleStageSet {
  stages: ModelEnsembleStage[];
  source: ModelEnsembleStageSource;
}

/**
 * The selective deep adjudicator (rubric judge) is never a small expert. This
 * single predicate feeds both the stage grouping below and the predictive
 * "small experts proven" gate in the axis model.
 */
export function isDeepModelStage(modelKey: string, repositoryId: string): boolean {
  return /qwen|rubric|deep/i.test(`${modelKey} ${repositoryId}`);
}

export function modelEnsembleStageGroup(modelKey: string, repositoryId: string): ModelEnsembleStageGroup {
  const identity = `${modelKey} ${repositoryId}`;
  if (isDeepModelStage(modelKey, repositoryId)) return "Deep judge";
  if (/modernbert|deberta.*small.*long|challenger/i.test(identity)) return "Challengers";
  return "Factor models";
}

export function modelEnsembleStageRole(modelKey: string, repositoryId: string): string {
  const identity = `${modelKey} ${repositoryId}`;
  if (isDeepModelStage(modelKey, repositoryId)) return "Selective disagreement adjudicator";
  if (/modernbert|deberta.*small.*long/i.test(identity)) return "English / long-context challenger";
  if (/minilm/i.test(identity)) return "Cheap multilingual factor challenger";
  if (/mdeberta|xnli/i.test(identity)) return "Primary multilingual factor model";
  return "Local factor model";
}

/** Stages of a sealed run: live predictive stages first, legacy expert slots otherwise. */
export function modelEnsembleRunStages(run: ModelEnsembleRun | null): ModelEnsembleStage[] {
  if (run === null) return [];
  const predictiveStages = run.predictive_model_stages ?? [];
  if (predictiveStages.length > 0) {
    return predictiveStages.map((stage) => ({
      modelKey: stage.model_key,
      repositoryId: stage.repository_id,
      revision: stage.revision,
      status: stage.status,
      errorCode: stage.error_code,
      device: stage.device,
      quantization: stage.quantization,
      latency: stage.inference_latency_ms ?? null,
      acceleratorMemory: stage.peak_accelerator_memory_mb ?? null,
      rss: stage.process_rss_mb ?? null,
      unloaded: stage.unloaded_after_stage,
      evaluatedCases: null,
      contributedCases: null,
      group: modelEnsembleStageGroup(stage.model_key, stage.repository_id),
      role: modelEnsembleStageRole(stage.model_key, stage.repository_id),
    }));
  }
  return (run.experts ?? []).map((stage) => ({
    modelKey: stage.model_key,
    repositoryId: stage.repository_id,
    revision: stage.revision,
    status: stage.status,
    errorCode: stage.error_code,
    device: stage.device,
    quantization: "legacy receipt",
    latency: stage.inference_latency_ms ?? null,
    acceleratorMemory: stage.peak_accelerator_memory_mb ?? null,
    rss: stage.process_rss_mb ?? null,
    unloaded: stage.unloaded_after_stage,
    evaluatedCases: null,
    contributedCases: null,
    group: "Legacy stages",
    role: stage.role.replaceAll("_", " "),
  }));
}

/** Stages of the latest durable attempt; unknown identity fields fall back to the stage key. */
export function modelEnsembleAttemptStages(stages: readonly ModelEnsembleAttemptStage[]): ModelEnsembleStage[] {
  return stages.map((stage) => ({
    modelKey: stage.model_key ?? stage.stage_key,
    repositoryId: stage.repository_id ?? stage.stage_key.replaceAll("_", " "),
    revision: stage.revision ?? "not-recorded",
    status: stage.state,
    errorCode: stage.error_code,
    device: stage.device,
    quantization: stage.quantization,
    latency: stage.inference_latency_ms,
    acceleratorMemory: stage.peak_accelerator_memory_mb,
    rss: stage.process_rss_mb,
    unloaded: stage.unloaded_after_stage,
    evaluatedCases: stage.evaluated_case_count,
    contributedCases: stage.contributed_case_count,
    group: modelEnsembleStageGroup(stage.model_key ?? stage.stage_key, stage.repository_id ?? ""),
    role: modelEnsembleStageRole(stage.model_key ?? stage.stage_key, stage.repository_id ?? ""),
  }));
}

/**
 * The latest attempt's stage rows take precedence over the sealed snapshot's
 * stage receipts; an attempt without stage rows falls back to the snapshot.
 */
export function modelEnsembleStagesFor(
  run: ModelEnsembleRun | null,
  attemptStages: readonly ModelEnsembleAttemptStage[],
): ModelEnsembleStageSet {
  return attemptStages.length > 0
    ? { stages: modelEnsembleAttemptStages(attemptStages), source: "attempt" }
    : { stages: modelEnsembleRunStages(run), source: "sealed" };
}

/** Drawer summary: provenance of the rows plus completed/total, or an explicit "not exposed". */
export function modelEnsembleStageSummaryLabel({ stages, source }: ModelEnsembleStageSet): string {
  if (stages.length === 0) return "Stage receipts not exposed";
  const completed = stages.filter((stage) => stage.status === "completed").length;
  return `${source === "attempt" ? "Latest attempt" : "Sealed snapshot"} · ${completed}/${stages.length} stages completed`;
}

/** Memory receipts are shown only when recorded; absence is stated, never rendered as 0 MiB. */
export function formatStageResource(value: number | null): string {
  return value === null ? "not recorded" : `${Math.round(value)} MiB`;
}

/** Preserve the unload receipt's true / false / unknown distinction. */
export function formatStageUnloadReceipt(value: boolean | null): string {
  if (value === true) return "yes · unloaded after stage";
  if (value === false) return "no · not unloaded after stage";
  return "not recorded · unload receipt missing";
}

/** Compact identity for run ids and revisions; short values are shown whole. */
export function shortIdentity(value: string): string {
  return value.length <= 12 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}
