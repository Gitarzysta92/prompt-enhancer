import { describe, expect, it } from "vitest";
import type { ModelEnsembleTrajectoryPoint } from "../../shared/api/contracts";
import {
  modelEnsembleHistoryRadarValue,
  modelEnsembleTrajectoryRadarData,
} from "./MetricWorkspace";
import { modelEnsembleRadarAxes } from "./ModelEnsembleRadar";

describe("modelEnsembleHistoryRadarValue", () => {
  it("keeps lower-is-better rework history aligned with radar quality", () => {
    const point = {
      typed_metrics: [{
        metric_key: "collaboration.rework_candidate_rate",
        value_state: "known",
        numeric_value: 0.02,
      }],
      metrics: [],
    } as unknown as ModelEnsembleTrajectoryPoint;

    expect(modelEnsembleHistoryRadarValue(
      point,
      "collaboration.rework_candidate_rate",
      "lower_is_better",
    )).toBeCloseTo(0.98);
    expect(modelEnsembleHistoryRadarValue(
      point,
      "collaboration.rework_candidate_rate",
      "higher_is_better",
    )).toBeCloseTo(0.02);
  });

  it("withholds trajectory-only experimental summaries without contributor proof", () => {
    const point = {
      typed_metrics: [],
      metrics: [],
      predictive_metrics: [{
        metric_key: "prompt.task_definition_coverage",
        target: "metric_value",
        state: "experimental",
        mean: 0.6,
        median: 0.6,
        q05: 0.4,
        q25: 0.5,
        q75: 0.7,
        q95: 0.8,
        applicability_probability: 0.9,
        pending_probability: 0,
        model_disagreement: 0.1,
        effective_observation_count: 2,
        model_set_version: "example-model-set-v1",
        calibration_version: "not-calibrated-v1",
        contract_version: "example-contract-v1",
        contract_fingerprint: "a".repeat(64),
        product_metric_eligible: false,
      }],
    } as unknown as ModelEnsembleTrajectoryPoint;

    const axis = modelEnsembleRadarAxes(
      modelEnsembleTrajectoryRadarData(point),
      "task-framing",
    )[0];
    expect(axis.predictiveMedian).toBeNull();
    expect(axis.predictiveWithheldReason).toMatch(/does not expose contributor proof/i);
    expect(axis.predictiveWithheldReason).not.toMatch(/fewer than two/i);
  });

  it("distinguishes a sealed receipt proving fewer than two small experts from missing proof", () => {
    const point = {
      typed_metrics: [],
      metrics: [],
      predictive_metrics: [{
        metric_key: "prompt.task_definition_coverage",
        target: "metric_value",
        state: "experimental",
        mean: 0.6,
        median: 0.6,
        q05: 0.4,
        q25: 0.5,
        q75: 0.7,
        q95: 0.8,
        applicability_probability: 0.9,
        pending_probability: 0,
        model_disagreement: 0.1,
        effective_observation_count: 2,
        model_set_version: "example-model-set-v1",
        calibration_version: "not-calibrated-v1",
        contract_version: "example-contract-v1",
        contract_fingerprint: "a".repeat(64),
        product_metric_eligible: false,
      }],
    } as unknown as ModelEnsembleTrajectoryPoint;
    const stage = (modelKey: string, status: "completed" | "failed") => ({
      model_key: modelKey,
      repository_id: `example-org/${modelKey}`,
      revision: "f".repeat(40),
      status,
      error_code: status === "completed" ? null : "example_failure",
      device: status === "completed" ? "cpu" : null,
      quantization: "none",
      inference_latency_ms: 10,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 128,
      unloaded_after_stage: true,
    });

    const sealedOneExpert = {
      ...modelEnsembleTrajectoryRadarData(point),
      predictive_model_stages: [stage("mdeberta_xnli", "completed"), stage("minilm_challenger", "failed")],
    } as unknown as Parameters<typeof modelEnsembleRadarAxes>[0];
    const sealedTwoExperts = {
      ...modelEnsembleTrajectoryRadarData(point),
      predictive_model_stages: [stage("mdeberta_xnli", "completed"), stage("minilm_challenger", "completed")],
    } as unknown as Parameters<typeof modelEnsembleRadarAxes>[0];
    const sealedNoStages = {
      ...modelEnsembleTrajectoryRadarData(point),
      predictive_model_stages: [],
    } as unknown as Parameters<typeof modelEnsembleRadarAxes>[0];

    expect(modelEnsembleRadarAxes(sealedOneExpert, "task-framing")[0].predictiveWithheldReason)
      .toMatch(/fewer than two small experts/i);
    expect(modelEnsembleRadarAxes(sealedNoStages, "task-framing")[0].predictiveWithheldReason)
      .toMatch(/fewer than two small experts/i);
    const proven = modelEnsembleRadarAxes(sealedTwoExperts, "task-framing")[0];
    expect(proven.predictiveWithheldReason).toBeNull();
    expect(proven.predictiveMedian).toBeCloseTo(0.6);
  });
});
