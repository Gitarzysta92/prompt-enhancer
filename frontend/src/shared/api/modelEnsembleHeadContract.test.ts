import { describe, expect, it } from "vitest";
import type { ModelEnsembleAttemptSnapshot, ModelEnsembleCanonicalHead } from "./contracts";
import {
  ModelEnsembleHeadPayloadError,
  parseModelEnsembleAttemptSnapshot,
  parseModelEnsembleCanonicalHead,
} from "./modelEnsembleHeadContract";

function headFixture(): { head: ModelEnsembleCanonicalHead; attempt: ModelEnsembleAttemptSnapshot } {
  const watchId = "a".repeat(64);
  const runId = "b".repeat(64);
  const attemptId = "c".repeat(64);
  const watch = {
    watch_id: watchId,
    provider: "codex" as const,
    project_id: "d".repeat(64),
    session_id: "e".repeat(64),
    max_messages: 100,
    state: "idle" as const,
    generation: 3,
    progress_completed: 1,
    progress_total: 10 as const,
    has_result: true,
    last_error_code: null,
    next_check_at: "2040-01-01T00:01:00Z",
    updated_at: "2040-01-01T00:00:01Z",
    serial_model_execution: true as const,
    process_isolated_model_release: true as const,
    cuda_resource_retry_on_cpu: true as const,
    content_persisted: false as const,
    calibrated_as_truth: false as const,
  };
  const attempt = {
    attempt_id: attemptId,
    watch_id: watchId,
    generation: 3,
    state: "completed" as const,
    prior_head_run_id: runId,
    published_run_id: runId,
    progress_completed: 6,
    progress_total: 6,
    stage_count: 1,
    warning_count: 0,
    error_code: null,
    requested_at: "2040-01-01T00:00:00Z",
    started_at: "2040-01-01T00:00:00Z",
    completed_at: "2040-01-01T00:00:01Z",
    content_persisted: false as const,
  };
  const stages = [{
    stage_ordinal: 0,
    stage_key: "mdeberta_xnli",
    state: "completed" as const,
    model_key: "mdeberta_xnli",
    repository_id: "example-org/example-model",
    revision: "1".repeat(40),
    error_code: null,
    device: "cuda" as const,
    quantization: "none" as const,
    inference_latency_ms: 125,
    peak_accelerator_memory_mb: 1024,
    process_rss_mb: 1536,
    evaluated_case_count: 20,
    contributed_case_count: 14,
    unloaded_after_stage: true,
    completed_at: "2040-01-01T00:00:01Z",
  }];
  return {
    head: {
      schema_version: "analysis-snapshot-v2" as const,
      watch,
      head_run_id: runId,
      head_generation: 2,
      latest_attempt: attempt,
      stages,
      content_persisted: false as const,
    },
    attempt: { attempt, stages },
  };
}

describe("canonical model ensemble head contract", () => {
  it("accepts dynamic progress and content-free terminal stage telemetry", () => {
    const fixture = headFixture();
    expect(parseModelEnsembleCanonicalHead(structuredClone(fixture.head))).toEqual(fixture.head);
    expect(parseModelEnsembleAttemptSnapshot(structuredClone(fixture.attempt))).toEqual(fixture.attempt);
  });

  it("accepts a running attempt only before terminal stage receipts exist", () => {
    const running = structuredClone(headFixture().head);
    running.watch.state = "running";
    running.latest_attempt!.state = "running";
    running.latest_attempt!.published_run_id = null;
    running.latest_attempt!.progress_completed = 1;
    running.latest_attempt!.stage_count = 0;
    running.latest_attempt!.completed_at = null;
    running.stages = [];

    expect(parseModelEnsembleCanonicalHead(running)).toEqual(running);
  });

  it("rejects additive content, mismatched stage counts, and impossible timestamps", () => {
    const extra = structuredClone(headFixture().head) as unknown as Record<string, unknown>;
    extra.private_text = "SYNTHETIC_PRIVATE_CANARY";
    expect(() => parseModelEnsembleCanonicalHead(extra)).toThrow(ModelEnsembleHeadPayloadError);

    const count = structuredClone(headFixture().head);
    count.latest_attempt!.stage_count = 2;
    expect(() => parseModelEnsembleCanonicalHead(count)).toThrow(ModelEnsembleHeadPayloadError);

    const date = structuredClone(headFixture().head);
    date.stages[0].completed_at = "2040-02-31T00:00:01Z";
    expect(() => parseModelEnsembleCanonicalHead(date)).toThrow(ModelEnsembleHeadPayloadError);
  });

  it("requires head identity and watch result state to agree", () => {
    const head: unknown = {
      ...structuredClone(headFixture().head),
      head_run_id: null,
      head_generation: null,
    };
    expect(() => parseModelEnsembleCanonicalHead(head)).toThrow(ModelEnsembleHeadPayloadError);
  });

  it("rejects tampered generations, repositories, ordinals, counts, and telemetry", () => {
    const zeroGeneration = structuredClone(headFixture().head);
    zeroGeneration.latest_attempt!.generation = 0;
    expect(() => parseModelEnsembleCanonicalHead(zeroGeneration)).toThrow(ModelEnsembleHeadPayloadError);

    const wrongWatchGeneration = structuredClone(headFixture().head);
    wrongWatchGeneration.latest_attempt!.generation = 2;
    expect(() => parseModelEnsembleCanonicalHead(wrongWatchGeneration)).toThrow(ModelEnsembleHeadPayloadError);

    const repository = structuredClone(headFixture().head);
    repository.stages[0].repository_id = "example-org/../private-model";
    expect(() => parseModelEnsembleCanonicalHead(repository)).toThrow(ModelEnsembleHeadPayloadError);

    const missingOwner = structuredClone(headFixture().head);
    missingOwner.stages[0].repository_id = "example-model";
    expect(() => parseModelEnsembleCanonicalHead(missingOwner)).toThrow(ModelEnsembleHeadPayloadError);

    const ordinal = structuredClone(headFixture().head);
    ordinal.stages[0].stage_ordinal = 1;
    expect(() => parseModelEnsembleCanonicalHead(ordinal)).toThrow(ModelEnsembleHeadPayloadError);

    const contributions = structuredClone(headFixture().head);
    contributions.stages[0].contributed_case_count = 21;
    expect(() => parseModelEnsembleCanonicalHead(contributions)).toThrow(ModelEnsembleHeadPayloadError);

    const memory = structuredClone(headFixture().head);
    memory.stages[0].peak_accelerator_memory_mb = 16_385;
    expect(() => parseModelEnsembleCanonicalHead(memory)).toThrow(ModelEnsembleHeadPayloadError);
  });

  it("rejects attempt/head publication and terminal-stage semantic mismatches", () => {
    const publication = structuredClone(headFixture().head);
    publication.latest_attempt!.published_run_id = "f".repeat(64);
    expect(() => parseModelEnsembleCanonicalHead(publication)).toThrow(ModelEnsembleHeadPayloadError);

    const warning = structuredClone(headFixture().head);
    warning.latest_attempt!.state = "partial";
    warning.latest_attempt!.warning_count = 1;
    expect(() => parseModelEnsembleCanonicalHead(warning)).toThrow(ModelEnsembleHeadPayloadError);

    const failedStage = structuredClone(headFixture().head);
    failedStage.latest_attempt!.state = "partial";
    failedStage.latest_attempt!.warning_count = 1;
    failedStage.stages[0].state = "failed";
    failedStage.stages[0].error_code = null;
    expect(() => parseModelEnsembleCanonicalHead(failedStage)).toThrow(ModelEnsembleHeadPayloadError);

    const runningWithStages = structuredClone(headFixture().head);
    runningWithStages.latest_attempt!.state = "running";
    runningWithStages.latest_attempt!.published_run_id = null;
    runningWithStages.latest_attempt!.completed_at = null;
    expect(() => parseModelEnsembleCanonicalHead(runningWithStages)).toThrow(ModelEnsembleHeadPayloadError);
  });
});
