import { describe, expect, it } from "vitest";
import type { ModelEnsembleAttemptStage, ModelEnsembleRun } from "../../shared/api/contracts";
import {
  MODEL_ENSEMBLE_STAGE_GROUPS,
  formatStageResource,
  formatStageUnloadReceipt,
  isDeepModelStage,
  modelEnsembleAttemptStages,
  modelEnsembleRunStages,
  modelEnsembleStageGroup,
  modelEnsembleStageRole,
  modelEnsembleStageSummaryLabel,
  modelEnsembleStagesFor,
  shortIdentity,
} from "./modelStages";

function predictiveStage(modelKey: string, repositoryId: string, status: "completed" | "failed" = "completed") {
  return {
    model_key: modelKey,
    repository_id: repositoryId,
    revision: "a".repeat(40),
    status,
    error_code: status === "completed" ? null : "example_stage_failure",
    device: status === "completed" ? "cpu" as const : null,
    quantization: "none" as const,
    inference_latency_ms: 12,
    peak_accelerator_memory_mb: 0,
    process_rss_mb: 256,
    unloaded_after_stage: true as const,
  };
}

function attemptStage(overrides: Partial<ModelEnsembleAttemptStage> = {}): ModelEnsembleAttemptStage {
  return {
    stage_ordinal: 0,
    stage_key: "mdeberta_xnli",
    state: "completed",
    model_key: "mdeberta_xnli",
    repository_id: "example-org/mdeberta-xnli",
    revision: "b".repeat(40),
    error_code: null,
    device: "cuda",
    quantization: "none",
    inference_latency_ms: 40,
    peak_accelerator_memory_mb: 1024,
    process_rss_mb: 1536,
    evaluated_case_count: 20,
    contributed_case_count: 14,
    unloaded_after_stage: true,
    completed_at: "2040-01-02T10:00:01Z",
    ...overrides,
  };
}

describe("modelStages grouping and roles", () => {
  it("routes the deep rubric judge, challengers, and factor models to fixed groups", () => {
    expect(MODEL_ENSEMBLE_STAGE_GROUPS).toEqual(["Factor models", "Challengers", "Deep judge", "Legacy stages"]);
    expect(modelEnsembleStageGroup("qwen3_4b_rubric", "example-org/qwen3-4b-rubric")).toBe("Deep judge");
    expect(modelEnsembleStageGroup("example_stage", "example-org/deep-adjudicator")).toBe("Deep judge");
    expect(modelEnsembleStageGroup("modernbert_nli", "example-org/modernbert")).toBe("Challengers");
    expect(modelEnsembleStageGroup("deberta_small_long", "example-org/deberta-v3-small-long-context")).toBe("Challengers");
    expect(modelEnsembleStageGroup("example_challenger", "example-org/example")).toBe("Challengers");
    expect(modelEnsembleStageGroup("mdeberta_xnli", "example-org/mdeberta-xnli")).toBe("Factor models");
    expect(modelEnsembleStageGroup("multilingual_minilmv2_l6_nli", "example-org/minilm")).toBe("Factor models");
  });

  it("keeps the deep-model predicate and the Deep judge group in lockstep", () => {
    const identities: Array<[string, string]> = [
      ["qwen3_4b_rubric", "example-org/qwen3-4b-rubric"],
      ["example_rubric_judge", "example-org/example"],
      ["mdeberta_xnli", "example-org/mdeberta-xnli"],
      ["multilingual_minilmv2_l12_nli", "example-org/minilm"],
      ["modernbert_nli", "example-org/modernbert"],
      ["example_stage", "example-org/deep-adjudicator"],
    ];
    for (const [modelKey, repositoryId] of identities) {
      expect(modelEnsembleStageGroup(modelKey, repositoryId) === "Deep judge").toBe(isDeepModelStage(modelKey, repositoryId));
      expect(modelEnsembleStageRole(modelKey, repositoryId) === "Selective disagreement adjudicator").toBe(isDeepModelStage(modelKey, repositoryId));
    }
  });

  it("names roles from the model identity without inventing capabilities", () => {
    expect(modelEnsembleStageRole("qwen3_4b_rubric", "example-org/qwen3-4b-rubric")).toBe("Selective disagreement adjudicator");
    expect(modelEnsembleStageRole("modernbert_nli", "example-org/modernbert")).toBe("English / long-context challenger");
    expect(modelEnsembleStageRole("multilingual_minilmv2_l6_nli", "example-org/minilm")).toBe("Cheap multilingual factor challenger");
    expect(modelEnsembleStageRole("mdeberta_xnli", "example-org/mdeberta-xnli")).toBe("Primary multilingual factor model");
    expect(modelEnsembleStageRole("example_model", "example-org/example-model")).toBe("Local factor model");
    // A "challenger" token groups a stage but is not enough to claim the long-context role.
    expect(modelEnsembleStageRole("example_challenger", "example-org/example")).toBe("Local factor model");
  });
});

describe("modelStages receipt adapters", () => {
  it("prefers live predictive stages, then legacy expert slots, and never invents case counts", () => {
    const run = {
      predictive_model_stages: [
        predictiveStage("mdeberta_xnli", "example-org/mdeberta-xnli"),
        predictiveStage("qwen3_4b_rubric", "example-org/qwen3-4b-rubric", "failed"),
      ],
      experts: [{
        ordinal: 0,
        model_key: "legacy_model",
        role: "scope_nli",
        repository_id: "example-org/legacy-model",
        revision: "c".repeat(40),
        license_spdx: "MIT",
        contributes_to_decision: true,
        status: "completed",
        error_code: null,
        device: "cpu",
        inference_latency_ms: 10,
        peak_accelerator_memory_mb: 0,
        process_rss_mb: 256,
        unloaded_after_stage: true,
      }],
    } as unknown as ModelEnsembleRun;

    const live = modelEnsembleRunStages(run);
    expect(live.map((stage) => [stage.modelKey, stage.group, stage.status, stage.errorCode])).toEqual([
      ["mdeberta_xnli", "Factor models", "completed", null],
      ["qwen3_4b_rubric", "Deep judge", "failed", "example_stage_failure"],
    ]);
    expect(live.every((stage) => stage.evaluatedCases === null && stage.contributedCases === null)).toBe(true);
    expect(live[1].device).toBeNull();

    const legacy = modelEnsembleRunStages({ ...run, predictive_model_stages: [] });
    expect(legacy).toHaveLength(1);
    expect(legacy[0]).toMatchObject({
      modelKey: "legacy_model",
      group: "Legacy stages",
      role: "scope nli",
      quantization: "legacy receipt",
      evaluatedCases: null,
      contributedCases: null,
    });
    expect(modelEnsembleRunStages(null)).toEqual([]);
  });

  it("adapts attempt stages without collapsing an unknown unload receipt into false", () => {
    const [known, explicitNegative, anonymous] = modelEnsembleAttemptStages([
      attemptStage(),
      attemptStage({
        stage_ordinal: 1,
        stage_key: "explicit_no_unload_stage",
        unloaded_after_stage: false,
      }),
      attemptStage({
        stage_ordinal: 2,
        stage_key: "typed_projection_stage",
        model_key: null,
        repository_id: null,
        revision: null,
        state: "unavailable",
        device: null,
        inference_latency_ms: null,
        peak_accelerator_memory_mb: null,
        process_rss_mb: null,
        evaluated_case_count: null,
        contributed_case_count: null,
        unloaded_after_stage: null,
      }),
    ]);
    expect(known).toMatchObject({
      modelKey: "mdeberta_xnli",
      repositoryId: "example-org/mdeberta-xnli",
      status: "completed",
      evaluatedCases: 20,
      contributedCases: 14,
      unloaded: true,
      group: "Factor models",
      role: "Primary multilingual factor model",
    });
    expect(explicitNegative.unloaded).toBe(false);
    expect(anonymous).toMatchObject({
      modelKey: "typed_projection_stage",
      repositoryId: "typed projection stage",
      revision: "not-recorded",
      status: "unavailable",
      latency: null,
      acceleratorMemory: null,
      rss: null,
      unloaded: null,
      evaluatedCases: null,
      contributedCases: null,
      group: "Factor models",
      role: "Local factor model",
    });
  });

  it("lets attempt rows outrank sealed stages and words the drawer summary from that source", () => {
    const run = {
      predictive_model_stages: [
        predictiveStage("mdeberta_xnli", "example-org/mdeberta-xnli"),
        predictiveStage("multilingual_minilmv2_l6_nli", "example-org/minilm"),
        predictiveStage("qwen3_4b_rubric", "example-org/qwen3-4b-rubric", "failed"),
      ],
      experts: [],
    } as unknown as ModelEnsembleRun;
    const attempt = [attemptStage(), attemptStage({ stage_ordinal: 1, stage_key: "qwen3_4b_rubric", model_key: "qwen3_4b_rubric", repository_id: "example-org/qwen3-4b-rubric", state: "cancelled", error_code: "analysis_cancelled" })];

    const fromAttempt = modelEnsembleStagesFor(run, attempt);
    expect(fromAttempt.source).toBe("attempt");
    expect(fromAttempt.stages.map((stage) => stage.status)).toEqual(["completed", "cancelled"]);
    expect(modelEnsembleStageSummaryLabel(fromAttempt)).toBe("Latest attempt · 1/2 stages completed");

    const fromSealed = modelEnsembleStagesFor(run, []);
    expect(fromSealed.source).toBe("sealed");
    expect(modelEnsembleStageSummaryLabel(fromSealed)).toBe("Sealed snapshot · 2/3 stages completed");

    expect(modelEnsembleStageSummaryLabel(modelEnsembleStagesFor(null, []))).toBe("Stage receipts not exposed");
  });

  it("formats resources and identities without converting absence into zero", () => {
    expect(formatStageResource(null)).toBe("not recorded");
    expect(formatStageResource(1023.6)).toBe("1024 MiB");
    expect(shortIdentity("short-id")).toBe("short-id");
    expect(shortIdentity("d".repeat(64))).toBe(`${"d".repeat(8)}…${"d".repeat(4)}`);
  });

  it("formats true, false, and unknown unload receipts as distinct facts", () => {
    expect(formatStageUnloadReceipt(true)).toBe("yes · unloaded after stage");
    expect(formatStageUnloadReceipt(false)).toBe("no · not unloaded after stage");
    expect(formatStageUnloadReceipt(null)).toBe("not recorded · unload receipt missing");
  });
});
