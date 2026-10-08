import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type {
  DeclaredTaskProfile,
  ModelEnsembleCanonicalHead,
  ModelEnsembleRun,
  ModelPredictiveMetricDetail,
  ModelEnsembleTrajectoryPage,
  ModelEnsembleWatchSnapshot,
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
} from "../../shared/api/contracts";
import {
  ModelEnsemblePayloadError,
  parseModelMetricProfileBinding,
  parseModelRequirementActionEvidenceBinding,
  parseModelRequirementPlanEvidenceBinding,
  parseModelRequirementVerificationEvidenceBinding,
  parseModelEnsembleOutcome,
  parseModelEnsembleRun,
} from "../../shared/api/modelEnsembleContract";
import {
  MetricDefinitionsOutOfDateError,
  parseMetricV2State,
} from "../../shared/api/metricPublicationV2Contract";
import {
  ModelEnsembleWatchPayloadError,
  parseModelEnsembleWatchSnapshot,
} from "../../shared/api/modelEnsembleWatchContract";
import {
  ModelEnsembleTrajectoryPayloadError,
  parseModelEnsembleTrajectoryPage,
} from "../../shared/api/modelEnsembleTrajectoryContract";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { parseModelPredictiveMetricDetail } from "../../shared/api/modelPredictiveMetricDetailContract";
import {
  syntheticMetricPublicationV2,
  syntheticPublishedMetricV2,
} from "../../test/metricPublicationV2Fixture";
import { createHttpTransport, TransportError } from "../../shared/api/httpTransport";
import { MetricWorkspace } from "./MetricWorkspace";
import { ModelEnsemblePanel } from "./ModelEnsemblePanel";
import {
  TRAJECTORY_RETRY_LIMIT,
  TRAJECTORY_RETRY_MS,
} from "./canonicalPolling";
import {
  modelEnsembleCompletedSmallExperts,
  modelEnsembleRadarAxes,
} from "./ModelEnsembleRadar";

const SESSION_ID = "a".repeat(64);
const PROJECT_ID = "b".repeat(64);
const EXACT: ProviderCompatibilityStatus = {
  provider: "codex",
  capability: "session_text_analysis",
  state: "exact",
  capability_state: "supported",
  provider_family: "codex_app_server",
  provider_version: "1.2.3",
  adapter_family: "codex_app_server",
  adapter_version: "2.0.0",
  source_schema_family: "codex_thread",
  source_schema_version: "1",
  content_schema_family: "codex_thread_items",
  content_schema_version: "1",
  reason_code: "exact_match",
  checked_at: "2040-01-01T10:00:00Z",
  update_support: "unsupported",
  update_target: null,
};
const CAPABILITY = {
  available: true,
  reason_code: "available",
  data_tier: "redacted_content",
  content_persistence: false,
  network_inference: false,
  raw_transcripts: false,
} as const;

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function runFixture(): ModelEnsembleRun {
  const roles = [
    "retrieval", "retrieval", "retrieval", "retrieval",
    "reranking", "reranking",
    "scope_nli", "scope_nli", "scope_nli",
    "structured_rubric",
  ] as const;
  const keys = roles.map((_, index) => `example_model_${index}`);
  const metricKeys = [
    "prompt.task_definition_coverage",
    "prompt.context_sufficiency",
    "prompt.acceptance_testability",
  ];
  return {
    run_id: "b".repeat(64),
    plan_version: "local-shadow-ensemble-v1",
    plan_fingerprint: "c".repeat(64),
    source_coverage_state: "complete_window",
    chunk_count: 1,
    model_count: 10,
    chunks: [{ ordinal: 0, source_message_count: 4, fragment_count: 8, character_count: 4000 }],
    experts: roles.map((role, ordinal) => ({
      ordinal,
      model_key: keys[ordinal],
      role,
      repository_id: `example-org/model-${ordinal}`,
      revision: ordinal.toString(16).repeat(40),
      license_spdx: ordinal % 2 === 0 ? "MIT" as const : "Apache-2.0" as const,
      contributes_to_decision: ordinal >= 7,
      status: "completed" as const,
      error_code: null,
      device: "cpu" as const,
      inference_latency_ms: 10,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 256,
      unloaded_after_stage: true as const,
    })),
    votes: metricKeys.flatMap((metric_key) => [6, 7, 8, 9].map((ordinal) => ({
      chunk_ordinal: 0,
      metric_key,
      model_key: keys[ordinal],
      role: ordinal === 9 ? "structured_rubric" as const : "scope_nli" as const,
      state: "present" as const,
      raw_score: 0.9,
      evidence_fragment_count: 2,
      reason_code: "example_present",
    }))),
    chunk_metrics: metricKeys.map((metric_key) => ({
      chunk_ordinal: 0,
      metric_key,
      value_state: "known" as const,
      numerator: 1,
      denominator: 1,
      rubric_vote: "present" as const,
      contributing_nli_votes: 2,
      diagnostic_nli_votes: 1,
      reason_code: "example_committee_present",
    })),
    metrics: metricKeys.map((metric_key) => ({
      metric_key,
      value_state: "known" as const,
      numerator: 1,
      denominator: 1,
      numeric_value: 1,
      known_chunk_count: 1,
      abstained_chunk_count: 0,
      unsupported_chunk_count: 0,
      failed_chunk_count: 0,
      total_chunk_count: 1,
      explanation_code: "example_ratio_of_chunks",
      calibration_state: "not_assessed" as const,
      product_metric_eligible: false as const,
    })),
    metric_projection_version: "coaching-typed-projection-v1",
    metric_projection_completed_at: "2040-01-02T10:00:01Z",
    metric_publication_v2: null,
    metric_profile_binding: null,
    requirement_plan_evidence_binding: null,
    requirement_action_evidence_binding: null,
    requirement_verification_evidence_binding: null,
    metric_evidence_readiness_v2: null,
    typed_metrics: metricKeys.map((metric_key, index) => ({
      metric_key,
      metric_version: 3,
      value_state: "known" as const,
      numerator: [3, 1, 4][index],
      denominator: 4,
      numeric_value: [0.75, 0.25, 1][index],
      observed_message_count: 4,
      eligible_message_count: 4,
      coverage: 1,
      explanation_code: "typed_requirement_ratio",
      error_code: null,
      projection_source: "deterministic_typed_contract" as const,
      metric_schema_version: 2,
      engine_version: "coaching-rules-en-pl-2",
      algorithm_id: "coaching-text-features",
      algorithm_version: "coaching-features-en-pl-2",
      rubric_version: "coaching-rubric-v3",
      calibration_state: "not_assessed" as const,
      product_metric_eligible: false as const,
    })),
    predictive_projection_version: "local-probabilistic-radar-v1",
    predictive_projected_at: "2040-01-02T10:00:02Z",
    predictive_metrics: metricKeys.map((metric_key, index) => ({
      metric_key,
      target: "metric_value" as const,
      state: "experimental" as const,
      mean: [0.7, 0.4, 0.8][index],
      median: [0.7, 0.4, 0.8][index],
      q05: [0.45, 0.15, 0.55][index],
      q25: [0.6, 0.3, 0.7][index],
      q75: [0.8, 0.5, 0.9][index],
      q95: [0.95, 0.75, 0.98][index],
      applicability_probability: 0.9,
      pending_probability: 0.05,
      model_disagreement: 0.12,
      effective_observation_count: 1,
      model_set_version: "local-factor-router-v2",
      calibration_version: "not-calibrated-v1",
      contract_version: "example-contract-v1",
      contract_fingerprint: (index + 4).toString(16).repeat(64),
      product_metric_eligible: false as const,
    })),
    predictive_model_stages: [0, 1, 2].map((ordinal) => ({
      model_key: `example_predictive_model_${ordinal}`,
      repository_id: `example-org/predictive-model-${ordinal}`,
      revision: (ordinal + 4).toString(16).repeat(40),
      status: "completed" as const,
      error_code: null,
      device: "cpu" as const,
      quantization: "none" as const,
      inference_latency_ms: 12,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 256,
      unloaded_after_stage: true as const,
    })),
    completed_at: "2040-01-02T10:00:00Z",
    local_only: true,
    content_persisted: false,
    calibration_state: "not_assessed",
    product_metric_eligible: false,
  };
}

function r5RunFixture(
  binding: NonNullable<ModelEnsembleRun["metric_profile_binding"]>,
): ModelEnsembleRun {
  const run = structuredClone(runFixture());
  const publication = structuredClone(syntheticMetricPublicationV2());
  publication.projection_version = "metric-contract-v2-projection-5";
  for (const item of publication.metrics) {
    item.state.projection_version = "metric-contract-v2-projection-5";
  }
  const metricKeys = publication.metrics.map((item) => item.state.metric_key);
  const aggregate = run.metrics[0];
  const chunkMetric = run.chunk_metrics[0];
  const typed = run.typed_metrics[0];
  const predictive = run.predictive_metrics[0];
  const votes = run.votes.slice(0, 4);
  run.metrics = metricKeys.map((metric_key) => ({ ...aggregate, metric_key }));
  run.chunk_metrics = metricKeys.map((metric_key) => ({ ...chunkMetric, metric_key }));
  run.typed_metrics = metricKeys.map((metric_key) => ({ ...typed, metric_key }));
  run.predictive_metrics = metricKeys.map((metric_key) => ({ ...predictive, metric_key }));
  run.votes = metricKeys.flatMap((metric_key) => votes.map((vote) => ({ ...vote, metric_key })));
  run.metric_publication_v2 = publication;
  run.metric_profile_binding = binding;
  return run;
}

function r6RunFixture(
  requirementPlanBinding: NonNullable<ModelEnsembleRun["requirement_plan_evidence_binding"]>,
): ModelEnsembleRun {
  const profile = parseModelMetricProfileBinding({
    profile_source: "coaching_profile_v1_unconfigured",
    profile_id: null,
    profile_revision: null,
    profile_fingerprint: "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71",
    profile_schema_version: "coaching-profile-v1-unconfigured",
    profile_policy_version: "server-preset-v1",
    local_only: true,
    content_persisted: false,
  });
  const run = r5RunFixture(profile);
  const publication = run.metric_publication_v2!;
  publication.projection_version = "metric-contract-v2-projection-6";
  for (const item of publication.metrics) {
    item.state.projection_version = "metric-contract-v2-projection-6";
  }
  const index = publication.metrics.findIndex(
    (item) => item.state.metric_key === "logic.decomposition_coverage",
  );
  const unavailable = syntheticPublishedMetricV2("logic.decomposition_coverage", {
    value_state: "unknown",
    capability_available: false,
    source_complete: true,
    explanation_code: "requirement_plan_evidence_unavailable",
  });
  unavailable.state.projection_version = "metric-contract-v2-projection-6";
  publication.metrics[index] = unavailable as typeof publication.metrics[number];
  run.requirement_plan_evidence_binding = requirementPlanBinding;
  return run;
}

function r7RunFixture(
  actionBinding: NonNullable<ModelEnsembleRun["requirement_action_evidence_binding"]>,
): ModelEnsembleRun {
  const planBinding = parseModelRequirementPlanEvidenceBinding({
    evidence_source: "reviewed_requirement_plan",
    confirmation_id: "8".repeat(64),
    proposal_id: "9".repeat(64),
    evidence_fingerprint: "7".repeat(64),
    evidence_schema_version: "requirement-plan-evidence-v1",
    evidence_policy_version: "reviewed-requirement-plan-v1",
    local_only: true,
    content_persisted: false,
  });
  const run = r6RunFixture(planBinding);
  const publication = run.metric_publication_v2!;
  publication.projection_version = "metric-contract-v2-projection-7";
  for (const item of publication.metrics) {
    item.state.projection_version = "metric-contract-v2-projection-7";
  }
  const decompositionIndex = publication.metrics.findIndex(
    (item) => item.state.metric_key === "logic.decomposition_coverage",
  );
  const decomposition = syntheticPublishedMetricV2("logic.decomposition_coverage", {
    value_state: "known", numerator: 1, denominator: 2,
    explanation_code: "reviewed_requirement_plan_links",
  });
  decomposition.state.projection_version = "metric-contract-v2-projection-7";
  publication.metrics[decompositionIndex] = decomposition as typeof publication.metrics[number];
  publication.unknown_count -= 1;
  publication.known_count += 1;

  const actionIndex = publication.metrics.findIndex(
    (item) => item.state.metric_key === "logic.requirement_action_traceability",
  );
  const scenario = actionBinding.evidence_source === "unavailable"
    ? { value_state: "unknown" as const, capability_available: false, source_complete: true,
      eligible: 2, unknown: 2, explanation_code: "requirement_action_evidence_unavailable" }
    : actionBinding.evidence_source === "awaiting_review"
      ? { value_state: "unknown" as const, capability_available: true, source_complete: true,
        eligible: 2, unknown: 2, explanation_code: "requirement_action_evidence_confirmation_required" }
      : actionBinding.evidence_source === "candidate_manifest_overflow"
        ? { value_state: "unknown" as const, capability_available: true, source_complete: true,
          eligible: 2, unknown: 2, explanation_code: "requirement_action_evidence_overflow" }
        : actionBinding.evidence_source === "candidate_source_incomplete"
          ? { value_state: "unknown" as const, capability_available: true, source_complete: false,
            eligible: 2, unknown: 2, explanation_code: "requirement_action_candidate_source_incomplete" }
          : actionBinding.evidence_source === "binding_invalid"
            ? { value_state: "unknown" as const, capability_available: true, source_complete: false,
              eligible: 2, unknown: 2, explanation_code: "requirement_action_evidence_invalid" }
          : { value_state: "known" as const, numerator: 1, denominator: 2,
            explanation_code: "reviewed_requirement_action_links" };
  const action = syntheticPublishedMetricV2("logic.requirement_action_traceability", scenario);
  action.state.projection_version = "metric-contract-v2-projection-7";
  publication.metrics[actionIndex] = action as typeof publication.metrics[number];
  if (actionBinding.evidence_source === "reviewed_requirement_action") {
    publication.unknown_count -= 1;
    publication.known_count += 1;
    publication.objective_measured_count += 1;
  }
  run.requirement_action_evidence_binding = actionBinding;
  return run;
}

const R8_VERIFICATION_IDENTITY = {
  opportunity_issuer_version: "reviewed-r6-requirement-opportunity-issuer-v1",
  result_issuer_version: "local-objective-verification-result-issuer-v1",
  acceptance_issuer_version: "native-explicit-requirement-acceptance-issuer-v1",
  evidence_schema_version: "requirement-verification-evidence-v1",
  evidence_policy_version: "app-issued-reviewed-requirement-verification-v1",
  persistence_schema_version: "requirement-verification-persistence-v1",
  evidence_projection_version: "reviewed-requirement-verification-objective-projection-v1",
  objective_projection_version: "reviewed-requirement-verification-objective-projection-v1",
  binding_schema_version: "session-requirement-verification-evidence-binding-v1",
  binding_fingerprint: "e".repeat(64),
  local_only: true,
  content_persisted: false,
} as const;

function r8UnavailableVerificationBinding() {
  return parseModelRequirementVerificationEvidenceBinding({
    evidence_source: "unavailable",
    requirement_plan_confirmation_id: null,
    requirement_plan_proposal_id: null,
    requirement_plan_evidence_fingerprint: null,
    requirement_plan_schema_version: null,
    requirement_plan_policy_version: null,
    requirement_plan_review_rubric_version: null,
    opportunity_count: null,
    opportunity_set_fingerprint: null,
    evidence_set_fingerprint: null,
    through_revision: null,
    authority_head_count: null,
    objective_result_count: null,
    native_acceptance_count: null,
    resolved_opportunity_count: null,
    met_requirement_count: null,
    ...R8_VERIFICATION_IDENTITY,
  });
}

function r8OverflowVerificationBinding() {
  return parseModelRequirementVerificationEvidenceBinding({
    evidence_source: "opportunity_bound_exceeded",
    requirement_plan_confirmation_id: "8".repeat(64),
    requirement_plan_proposal_id: "9".repeat(64),
    requirement_plan_evidence_fingerprint: "7".repeat(64),
    requirement_plan_schema_version: "requirement-plan-evidence-v1",
    requirement_plan_policy_version: "reviewed-requirement-plan-v1",
    requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1",
    opportunity_count: 101,
    opportunity_set_fingerprint: "4".repeat(64),
    evidence_set_fingerprint: null,
    through_revision: null,
    authority_head_count: null,
    objective_result_count: null,
    native_acceptance_count: null,
    resolved_opportunity_count: null,
    met_requirement_count: null,
    ...R8_VERIFICATION_IDENTITY,
  });
}

function r8AwaitingVerificationBinding() {
  return parseModelRequirementVerificationEvidenceBinding({
    evidence_source: "awaiting_evidence",
    requirement_plan_confirmation_id: "8".repeat(64),
    requirement_plan_proposal_id: "9".repeat(64),
    requirement_plan_evidence_fingerprint: "7".repeat(64),
    requirement_plan_schema_version: "requirement-plan-evidence-v1",
    requirement_plan_policy_version: "reviewed-requirement-plan-v1",
    requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1",
    opportunity_count: 2,
    opportunity_set_fingerprint: "4".repeat(64),
    evidence_set_fingerprint: null,
    through_revision: null,
    authority_head_count: 0,
    objective_result_count: 0,
    native_acceptance_count: 0,
    resolved_opportunity_count: 0,
    met_requirement_count: 0,
    ...R8_VERIFICATION_IDENTITY,
    binding_fingerprint: "f".repeat(64),
  });
}

function r8PersistedVerificationBinding() {
  return parseModelRequirementVerificationEvidenceBinding({
    evidence_source: "persisted_evidence",
    requirement_plan_confirmation_id: "8".repeat(64),
    requirement_plan_proposal_id: "9".repeat(64),
    requirement_plan_evidence_fingerprint: "7".repeat(64),
    requirement_plan_schema_version: "requirement-plan-evidence-v1",
    requirement_plan_policy_version: "reviewed-requirement-plan-v1",
    requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1",
    opportunity_count: 2,
    opportunity_set_fingerprint: "4".repeat(64),
    evidence_set_fingerprint: "5".repeat(64),
    through_revision: 1,
    authority_head_count: 1,
    objective_result_count: 1,
    native_acceptance_count: 0,
    resolved_opportunity_count: 1,
    met_requirement_count: 1,
    ...R8_VERIFICATION_IDENTITY,
    binding_fingerprint: "a".repeat(64),
  });
}

function declaredProfileFixture(): DeclaredTaskProfile {
  return {
    profile_id: "1".repeat(64),
    provider: "codex",
    session_id: SESSION_ID,
    revision: 3,
    previous_profile_id: "3".repeat(64),
    constraint_kinds: ["privacy"],
    expected_outcome_count: 2,
    deliverable_slots: ["artifact"],
    profile_fingerprint: "2".repeat(64),
    confirmed_at: "2040-01-02T09:59:00Z",
    confirmation_authority: "authenticated_local_user",
    schema_version: "declared-task-profile-v1",
    policy_version: "authenticated-local-user-v1",
    local_only: true,
    content_persisted: false,
  };
}

const LIVE_TERMINAL_MODEL_SPECS = [
  {
    modelKey: "mdeberta_xnli",
    repositoryId: "example-org/mdeberta-xnli",
    device: "cpu" as const,
    quantization: "none",
  },
  {
    modelKey: "multilingual_minilmv2_l6_nli",
    repositoryId: "example-org/multilingual-minilmv2-l6-nli",
    device: "cpu" as const,
    quantization: "none",
  },
  {
    modelKey: "multilingual_minilmv2_l12_nli",
    repositoryId: "example-org/multilingual-minilmv2-l12-nli",
    device: "cpu" as const,
    quantization: "none",
  },
  {
    modelKey: "qwen3_4b_rubric",
    repositoryId: "example-org/qwen3-4b-rubric",
    device: "cuda" as const,
    quantization: "bitsandbytes_nf4",
  },
] as const;

function fourStageTerminalRun(): ModelEnsembleRun {
  const run = structuredClone(runFixture());
  run.predictive_model_stages = LIVE_TERMINAL_MODEL_SPECS.map((spec, ordinal) => ({
    model_key: spec.modelKey,
    repository_id: spec.repositoryId,
    revision: (ordinal + 5).toString(16).repeat(40),
    status: "completed" as const,
    error_code: null,
    device: spec.device,
    quantization: spec.quantization,
    inference_latency_ms: 20 + ordinal,
    peak_accelerator_memory_mb: spec.device === "cuda" ? 3_840 : 0,
    process_rss_mb: spec.device === "cuda" ? 4_096 : 768,
    unloaded_after_stage: true,
  }));
  return run;
}

function fourTerminalAttemptStages(): ModelEnsembleCanonicalHead["stages"] {
  return LIVE_TERMINAL_MODEL_SPECS.map((spec, ordinal) => ({
    stage_ordinal: ordinal,
    stage_key: spec.modelKey,
    state: "completed" as const,
    model_key: spec.modelKey,
    repository_id: spec.repositoryId,
    revision: (ordinal + 5).toString(16).repeat(40),
    error_code: null,
    device: spec.device,
    quantization: spec.quantization,
    inference_latency_ms: 20 + ordinal,
    peak_accelerator_memory_mb: spec.device === "cuda" ? 3_840 : 0,
    process_rss_mb: spec.device === "cuda" ? 4_096 : 768,
    evaluated_case_count: 18,
    contributed_case_count: 12,
    unloaded_after_stage: true,
    completed_at: `2040-01-02T10:00:0${ordinal + 2}Z`,
  }));
}

function watchFixture(latestRun: ModelEnsembleRun | null = null): ModelEnsembleWatchSnapshot {
  return {
    watch: {
      watch_id: "d".repeat(64),
      provider: "codex",
      project_id: PROJECT_ID,
      session_id: SESSION_ID,
      max_messages: 100,
      state: "idle",
      generation: 2,
      progress_completed: 10,
      progress_total: 10,
      has_result: latestRun !== null,
      last_error_code: null,
      next_check_at: "2040-01-02T10:01:00Z",
      updated_at: "2040-01-02T10:00:00Z",
      serial_model_execution: true,
      process_isolated_model_release: true,
      cuda_resource_retry_on_cpu: true,
      content_persisted: false,
      calibrated_as_truth: false,
    },
    latest_run: latestRun,
  };
}

function trajectoryFixture(): ModelEnsembleTrajectoryPage {
  const run = runFixture();
  return {
    watch_id: "d".repeat(64),
    head_run_id: run.run_id,
    head_generation: 2,
    points: [{
      generation: 2,
      run_id: run.run_id,
      published_at: "2040-01-02T10:00:01Z",
      completed_at: run.completed_at,
      max_messages: 100,
      source_coverage_state: run.source_coverage_state,
      chunk_count: run.chunk_count,
      comparable_to_head: true,
      metrics: run.metrics,
      metric_projection_version: run.metric_projection_version,
      metric_projection_completed_at: run.metric_projection_completed_at,
      typed_metrics: run.typed_metrics,
      metric_states_v2: [],
      predictive_projection_version: run.predictive_projection_version,
      predictive_metrics: run.predictive_metrics,
    }],
    next_before_generation: null,
    content_persisted: false,
    calibrated_as_truth: false,
  };
}

function canonicalHeadFixture(
  run = runFixture(),
  sessionId = SESSION_ID,
  state: "running" | "cancelled" = "running",
): ModelEnsembleCanonicalHead {
  const watch = watchFixture(run).watch;
  watch.session_id = sessionId;
  watch.state = state === "running" ? "running" : "idle";
  return {
    schema_version: "analysis-snapshot-v2",
    watch,
    head_run_id: run.run_id,
    head_generation: 2,
    latest_attempt: {
      attempt_id: "e".repeat(64),
      watch_id: watch.watch_id,
      generation: watch.generation,
      state,
      prior_head_run_id: run.run_id,
      published_run_id: null,
      progress_completed: 1,
      progress_total: 6,
      stage_count: state === "cancelled" ? 1 : 0,
      warning_count: state === "cancelled" ? 1 : 0,
      error_code: state === "cancelled" ? "analysis_cancelled" : null,
      requested_at: "2040-01-02T10:00:00Z",
      started_at: "2040-01-02T10:00:00Z",
      completed_at: state === "cancelled" ? "2040-01-02T10:00:02Z" : null,
      content_persisted: false,
    },
    stages: state === "running" ? [] : [{
      stage_ordinal: 0,
      stage_key: "foreign_stage",
      state: "cancelled",
      model_key: "foreign_stage",
      repository_id: "example-org/foreign-stage",
      revision: "f".repeat(40),
      error_code: "analysis_cancelled",
      device: "cpu",
      quantization: "none",
      inference_latency_ms: 40,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 256,
      evaluated_case_count: 20,
      contributed_case_count: 10,
      unloaded_after_stage: true,
      completed_at: "2040-01-02T10:00:01Z",
    }],
    content_persisted: false,
  };
}

function emptyCanonicalHeadFixture(): ModelEnsembleCanonicalHead {
  const head = canonicalHeadFixture();
  head.watch.state = "idle";
  head.watch.has_result = false;
  head.watch.progress_completed = 0;
  head.head_run_id = null;
  head.head_generation = null;
  head.latest_attempt = null;
  head.stages = [];
  return head;
}

function predictiveDetailFixture(metricKey = "prompt.task_definition_coverage"): ModelPredictiveMetricDetail {
  const metric = runFixture().predictive_metrics.find((item) => item.metric_key === metricKey)!;
  return {
    run_id: "b".repeat(64),
    projection_version: "local-probabilistic-radar-v1",
    projected_at: "2040-01-02T10:00:02Z",
    metric,
    density_bins: Array.from({ length: 20 }, () => 0.05),
    factors: [{
      factor_key: "action",
      scale: "binary",
      weight: 1,
      applicability_probability: 0.9,
      present_probability: 0.7,
      neutral_probability: 0.2,
      absent_probability: 0.1,
      expert_count: 3,
      critical: true,
    }],
    experimental_label: "Experimental model range",
    local_only: true,
    content_persisted: false,
    universal_trust_percentage_available: false,
  };
}

function renderPanel(
  transport: PromptEnhancerTransport,
  overrides: Partial<ComponentProps<typeof ModelEnsemblePanel>> = {},
) {
  return render(
    <ModelEnsemblePanel
      analysisCapability={CAPABILITY}
      category="prompt-quality"
      providerCompatibility={EXACT}
      projectId={PROJECT_ID}
      sessionId={SESSION_ID}
      transport={transport}
      {...overrides}
    />,
  );
}

describe("model ensemble response contract", () => {
  it("explains quarantined cleanup without promising a completed result or automatic retry", async () => {
    const snapshot = watchFixture();
    snapshot.watch.state = "failed";
    snapshot.watch.quarantined = true;
    snapshot.watch.quarantine_reason_code = "model_ensemble_cleanup_unconfirmed";
    snapshot.watch.last_error_code = "model_ensemble_cleanup_unconfirmed";
    const disableModelEnsembleWatch = vi.fn(async () => ({ ...snapshot, watch: { ...snapshot.watch, state: "disabled" as const } }));
    renderPanel({
      ...createSyntheticTransport(),
      getActiveModelEnsembleWatch: async () => snapshot,
      disableModelEnsembleWatch,
    });
    expect(await screen.findByRole("status")).toHaveTextContent(/Model process cleanup was not confirmed/);
    expect(screen.getByRole("status")).toHaveTextContent(/Automatic retries are paused/);
    expect(screen.getByRole("status")).toHaveTextContent(/restart the app before retrying/);
    expect(screen.getByText(/No completed snapshot is available here/)).toBeVisible();
    expect(screen.queryByText(/Start one explicit run/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop continuous updates" }));
    await waitFor(() => expect(disableModelEnsembleWatch).toHaveBeenCalledTimes(1));
    await screen.findByRole("button", { name: "Watch this session" });
    expect(screen.getByRole("status")).toHaveTextContent(/Model process cleanup was not confirmed/);
    expect(screen.queryByText(/Start one explicit run/)).not.toBeInTheDocument();
  });

  it("keeps the fixed cleanup recovery message on direct model-run errors", async () => {
    const startModelEnsemble = vi.fn().mockRejectedValue(new TransportError("unavailable", 503, "model_ensemble_cleanup_unconfirmed"));
    renderPanel({ ...createSyntheticTransport(), startModelEnsemble });
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Model process cleanup was not confirmed.*Automatic retries are paused/);
    expect(screen.queryByText(/Start one explicit run/)).not.toBeInTheDocument();
    expect(startModelEnsemble).toHaveBeenCalledTimes(1);
  });

  it("strictly parses the minimized declared-profile binding and classifies future identities", () => {
    const binding = {
      profile_source: "declared_task_profile",
      profile_id: "1".repeat(64),
      profile_revision: 3,
      profile_fingerprint: "2".repeat(64),
      profile_schema_version: "declared-task-profile-v1",
      profile_policy_version: "authenticated-local-user-v1",
      local_only: true,
      content_persisted: false,
    };
    expect(parseModelMetricProfileBinding(structuredClone(binding))).toEqual(binding);

    const extra = { ...binding, session_id: SESSION_ID };
    expect(() => parseModelMetricProfileBinding(extra)).toThrow(ModelEnsemblePayloadError);
    const crossed = { ...binding, profile_policy_version: "server-preset-v1" };
    expect(() => parseModelMetricProfileBinding(crossed)).toThrow(ModelEnsemblePayloadError);
    const future = { ...binding, profile_schema_version: "declared-task-profile-v2" };
    let caught: unknown;
    try { parseModelMetricProfileBinding(future); } catch (error) { caught = error; }
    expect(caught).toBeInstanceOf(MetricDefinitionsOutOfDateError);
    expect((caught as MetricDefinitionsOutOfDateError).mismatch).toBe("metric_profile_binding");
  });

  it("accepts only the exact content-free unconfigured preset identity", () => {
    const binding = {
      profile_source: "coaching_profile_v1_unconfigured",
      profile_id: null,
      profile_revision: null,
      profile_fingerprint: "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71",
      profile_schema_version: "coaching-profile-v1-unconfigured",
      profile_policy_version: "server-preset-v1",
      local_only: true,
      content_persisted: false,
    };
    const parsedBinding = parseModelMetricProfileBinding(structuredClone(binding));
    expect(parsedBinding).toEqual(binding);
    const r5 = r5RunFixture(parsedBinding);
    expect(parseModelEnsembleRun(structuredClone(r5))).toEqual(r5);
    r5.metric_profile_binding = null;
    expect(() => parseModelEnsembleRun(r5)).toThrow(ModelEnsemblePayloadError);
    const legacy = runFixture();
    legacy.metric_profile_binding = parsedBinding;
    expect(() => parseModelEnsembleRun(legacy)).toThrow(ModelEnsemblePayloadError);
    expect(() => parseModelMetricProfileBinding({
      ...binding,
      profile_fingerprint: "0".repeat(64),
    })).toThrow(ModelEnsemblePayloadError);
  });

  it("strictly binds every r6 decomposition state to its minimized requirement-plan authority", () => {
    const unavailable = parseModelRequirementPlanEvidenceBinding({
      evidence_source: "unavailable",
      confirmation_id: null,
      proposal_id: null,
      evidence_fingerprint: "30f6b309825c563a881ed1b7587072222e3cb33ca70f7bff274ba968cb067641",
      evidence_schema_version: "requirement-plan-unavailable-v1",
      evidence_policy_version: "reviewed-requirement-plan-v1",
      local_only: true,
      content_persisted: false,
    });
    const absent = r6RunFixture(unavailable);
    expect(parseModelEnsembleRun(structuredClone(absent))).toEqual(absent);

    const awaiting = parseModelRequirementPlanEvidenceBinding({
      evidence_source: "awaiting_review",
      confirmation_id: null,
      proposal_id: null,
      evidence_fingerprint: "843a2a5154affde7f7cddc19137dfcdfa8253d9f541c98b6e2cdabd930401ff2",
      evidence_schema_version: "requirement-plan-awaiting-review-v1",
      evidence_policy_version: "reviewed-requirement-plan-v1",
      local_only: true,
      content_persisted: false,
    });
    const awaitingRun = r6RunFixture(awaiting);
    const awaitingIndex = awaitingRun.metric_publication_v2!.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const confirmationRequired = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "unknown",
      capability_available: true,
      source_complete: true,
      explanation_code: "requirement_plan_evidence_confirmation_required",
    });
    confirmationRequired.state.projection_version = "metric-contract-v2-projection-6";
    awaitingRun.metric_publication_v2!.metrics[awaitingIndex] = confirmationRequired as NonNullable<
      typeof awaitingRun.metric_publication_v2
    >["metrics"][number];
    expect(parseModelEnsembleRun(structuredClone(awaitingRun))).toEqual(awaitingRun);
    expect(() => parseModelRequirementPlanEvidenceBinding({
      ...awaiting,
      evidence_fingerprint: "0".repeat(64),
    })).toThrow(ModelEnsemblePayloadError);
    const awaitingWrongReceipt = structuredClone(awaitingRun);
    awaitingWrongReceipt.metric_publication_v2!.metrics[awaitingIndex].state.statistics
      .capability_available = false;
    expect(() => parseModelEnsembleRun(awaitingWrongReceipt)).toThrow(ModelEnsemblePayloadError);

    const missing = structuredClone(absent);
    missing.requirement_plan_evidence_binding = null;
    expect(() => parseModelEnsembleRun(missing)).toThrow(ModelEnsemblePayloadError);
    const falseNumber = structuredClone(absent);
    const absentState = falseNumber.metric_publication_v2!.metrics.find(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    )!.state;
    absentState.statistics.capability_available = true;
    expect(() => parseModelEnsembleRun(falseNumber)).toThrow(ModelEnsemblePayloadError);

    expect(() => parseModelRequirementPlanEvidenceBinding({
      ...unavailable,
      evidence_fingerprint: "0".repeat(64),
    })).toThrow(ModelEnsemblePayloadError);
    let future: unknown;
    try {
      parseModelRequirementPlanEvidenceBinding({
        ...unavailable,
        evidence_schema_version: "requirement-plan-evidence-v2",
      });
    } catch (error) { future = error; }
    expect(future).toBeInstanceOf(MetricDefinitionsOutOfDateError);
    expect((future as MetricDefinitionsOutOfDateError).mismatch).toBe(
      "requirement_plan_evidence_binding",
    );

    const reviewed = parseModelRequirementPlanEvidenceBinding({
      evidence_source: "reviewed_requirement_plan",
      confirmation_id: "8".repeat(64),
      proposal_id: "9".repeat(64),
      evidence_fingerprint: "7".repeat(64),
      evidence_schema_version: "requirement-plan-evidence-v1",
      evidence_policy_version: "reviewed-requirement-plan-v1",
      local_only: true,
      content_persisted: false,
    });
    const measured = r6RunFixture(reviewed);
    const publication = measured.metric_publication_v2!;
    const index = publication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const state = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "known",
      numerator: 1,
      denominator: 2,
      explanation_code: "reviewed_requirement_plan_links",
    });
    state.state.projection_version = "metric-contract-v2-projection-6";
    publication.metrics[index] = state as typeof publication.metrics[number];
    publication.unknown_count -= 1;
    publication.known_count += 1;
    expect(parseModelEnsembleRun(structuredClone(measured))).toEqual(measured);

    const pendingPlanRun = r6RunFixture(reviewed);
    const pendingPlanPublication = pendingPlanRun.metric_publication_v2!;
    const pendingPlanIndex = pendingPlanPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const pendingPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "pending", capability_available: true, source_complete: true,
      eligible: 2, numerator: 1, pending: 1,
      explanation_code: "opportunity_right_censored",
    });
    pendingPlan.state.projection_version = "metric-contract-v2-projection-6";
    pendingPlanPublication.metrics[pendingPlanIndex] = pendingPlan as typeof pendingPlanPublication.metrics[number];
    pendingPlanPublication.unknown_count -= 1;
    pendingPlanPublication.pending_count += 1;
    expect(parseModelEnsembleRun(structuredClone(pendingPlanRun))).toEqual(pendingPlanRun);

    const emptyPlanRun = r6RunFixture(reviewed);
    const emptyPlanPublication = emptyPlanRun.metric_publication_v2!;
    const emptyPlanIndex = emptyPlanPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const emptyPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "not_applicable", capability_available: true, source_complete: true,
      eligible: 0, explanation_code: "no_opportunity_observed",
    });
    emptyPlan.state.projection_version = "metric-contract-v2-projection-6";
    emptyPlanPublication.metrics[emptyPlanIndex] = emptyPlan as typeof emptyPlanPublication.metrics[number];
    emptyPlanPublication.unknown_count -= 1;
    emptyPlanPublication.not_applicable_count += 1;
    expect(parseModelEnsembleRun(structuredClone(emptyPlanRun))).toEqual(emptyPlanRun);

    const invalidCoordinates = r6RunFixture(reviewed);
    const invalidPublication = invalidCoordinates.metric_publication_v2!;
    const invalidIndex = invalidPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const invalid = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "unknown",
      capability_available: true,
      source_complete: false,
      explanation_code: "requirement_plan_evidence_invalid",
    });
    invalid.state.projection_version = "metric-contract-v2-projection-6";
    invalidPublication.metrics[invalidIndex] = invalid as typeof invalidPublication.metrics[number];
    expect(parseModelEnsembleRun(structuredClone(invalidCoordinates))).toEqual(invalidCoordinates);

    const legacy = r5RunFixture(measured.metric_profile_binding!);
    legacy.requirement_plan_evidence_binding = reviewed;
    expect(() => parseModelEnsembleRun(legacy)).toThrow(ModelEnsemblePayloadError);
  });

  it("strictly correlates every r7 requirement-action marker and reviewed authority to its sealed state", () => {
    const marker = (
      source: "unavailable" | "awaiting_review" | "candidate_manifest_overflow" | "candidate_source_incomplete" | "binding_invalid",
      evidenceFingerprint: string,
      schema: NonNullable<ModelEnsembleRun["requirement_action_evidence_binding"]>["evidence_schema_version"],
    ) => parseModelRequirementActionEvidenceBinding({
      evidence_source: source,
      source_run_id: null,
      requirement_plan_confirmation_id: null,
      requirement_plan_evidence_fingerprint: null,
      candidate_manifest_fingerprint: null,
      confirmation_id: null,
      proposal_id: null,
      reviewed_descriptor_set_fingerprint: null,
      evidence_fingerprint: evidenceFingerprint,
      evidence_schema_version: schema,
      evidence_policy_version: "reviewed-requirement-action-v1",
      local_only: true,
      content_persisted: false,
    });
    const markers = [
      marker("unavailable", "9059e785839871abf94e1fea1c86c48e737621047a526cd3c9e94099a5b5e07f", "requirement-action-unavailable-v1"),
      marker("awaiting_review", "0ca65041b98be25e41cbbba908641f116f0e81b45416f89fd7ddf177489add4a", "requirement-action-awaiting-review-v1"),
      marker("candidate_manifest_overflow", "528224b052ffbec5c2b404b8970ab2ced61b84bc39cc20d70fd77320a059875f", "requirement-action-candidate-manifest-overflow-v1"),
      marker("candidate_source_incomplete", "d44bd4fa494e3123c7cb6f23ada45473204a55736c8a0ae9e5305ba30d91c699", "requirement-action-candidate-source-incomplete-v1"),
      marker("binding_invalid", "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da", "requirement-action-binding-invalid-v1"),
    ];
    for (const binding of markers) {
      const run = r7RunFixture(binding);
      expect(
        () => parseModelEnsembleRun(structuredClone(run)),
        `r7 ${binding.evidence_source} binding must match its exact unknown state`,
      ).not.toThrow();
      expect(parseModelEnsembleRun(structuredClone(run))).toEqual(run);

      const mismatched = r7RunFixture(binding);
      const actionIndex = mismatched.metric_publication_v2!.metrics.findIndex(
        (item) => item.state.metric_key === "logic.requirement_action_traceability",
      );
      const mismatchScenario = binding.evidence_source === "unavailable"
        ? { capability_available: false, source_complete: true,
          explanation_code: "requirement_action_evidence_unavailable" }
        : binding.evidence_source === "awaiting_review"
          ? { capability_available: true, source_complete: true,
            explanation_code: "requirement_action_evidence_confirmation_required" }
          : binding.evidence_source === "candidate_manifest_overflow"
            ? { capability_available: true, source_complete: true,
              explanation_code: "requirement_action_evidence_overflow" }
            : binding.evidence_source === "candidate_source_incomplete"
              ? { capability_available: true, source_complete: false,
                explanation_code: "requirement_action_candidate_source_incomplete" }
              : { capability_available: true, source_complete: false,
                explanation_code: "requirement_action_evidence_invalid" };
      const mismatchedAction = syntheticPublishedMetricV2(
        "logic.requirement_action_traceability",
        { value_state: "unknown", eligible: 1, unknown: 1, ...mismatchScenario },
      );
      mismatchedAction.state.projection_version = "metric-contract-v2-projection-7";
      mismatched.metric_publication_v2!.metrics[actionIndex] = mismatchedAction as NonNullable<
        ModelEnsembleRun["metric_publication_v2"]
      >["metrics"][number];
      expect(() => parseModelEnsembleRun(mismatched)).toThrow(ModelEnsemblePayloadError);

      const pendingPlanMarker = r7RunFixture(binding);
      const pendingPublication = pendingPlanMarker.metric_publication_v2!;
      const pendingPlanIndex = pendingPublication.metrics.findIndex(
        (item) => item.state.metric_key === "logic.decomposition_coverage",
      );
      const pendingReviewedPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
        value_state: "pending", capability_available: true, source_complete: true,
        eligible: 2, numerator: 1, pending: 1,
        explanation_code: "opportunity_right_censored",
      });
      pendingReviewedPlan.state.projection_version = "metric-contract-v2-projection-7";
      pendingPublication.metrics[pendingPlanIndex] = pendingReviewedPlan as typeof pendingPublication.metrics[number];
      pendingPublication.known_count -= 1;
      pendingPublication.pending_count += 1;
      expect(parseModelEnsembleRun(structuredClone(pendingPlanMarker))).toEqual(pendingPlanMarker);
    }

    const overflowBinding = markers.find(
      (binding) => binding.evidence_source === "candidate_manifest_overflow",
    )!;
    const mismatchedNonemptyOverflow = r7RunFixture(overflowBinding);
    const nonemptyActionIndex = mismatchedNonemptyOverflow.metric_publication_v2!.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const zeroActionOverflow = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_overflow",
      },
    );
    zeroActionOverflow.state.projection_version = "metric-contract-v2-projection-7";
    mismatchedNonemptyOverflow.metric_publication_v2!.metrics[nonemptyActionIndex] =
      zeroActionOverflow as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    expect(() => parseModelEnsembleRun(mismatchedNonemptyOverflow))
      .toThrow(ModelEnsemblePayloadError);

    const emptyOverflow = r7RunFixture(overflowBinding);
    const emptyPublication = emptyOverflow.metric_publication_v2!;
    const emptyPlanIndex = emptyPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const emptyActionIndex = emptyPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const emptyPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "not_applicable", capability_available: true, source_complete: true,
      eligible: 0, explanation_code: "no_opportunity_observed",
    });
    emptyPlan.state.projection_version = "metric-contract-v2-projection-7";
    emptyPublication.metrics[emptyPlanIndex] = emptyPlan as typeof emptyPublication.metrics[number];
    emptyPublication.metrics[emptyActionIndex] = zeroActionOverflow as typeof emptyPublication.metrics[number];
    emptyPublication.known_count -= 1;
    emptyPublication.not_applicable_count += 1;
    expect(parseModelEnsembleRun(structuredClone(emptyOverflow))).toEqual(emptyOverflow);

    const overflowBeforePlanAuthorityCases = [
      {
        binding: parseModelRequirementPlanEvidenceBinding({
          evidence_source: "unavailable",
          confirmation_id: null,
          proposal_id: null,
          evidence_fingerprint: "30f6b309825c563a881ed1b7587072222e3cb33ca70f7bff274ba968cb067641",
          evidence_schema_version: "requirement-plan-unavailable-v1",
          evidence_policy_version: "reviewed-requirement-plan-v1",
          local_only: true,
          content_persisted: false,
        }),
        plan: {
          value_state: "unknown" as const, capability_available: false, source_complete: true,
          eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_unavailable",
        },
      },
      {
        binding: parseModelRequirementPlanEvidenceBinding({
          evidence_source: "awaiting_review",
          confirmation_id: null,
          proposal_id: null,
          evidence_fingerprint: "843a2a5154affde7f7cddc19137dfcdfa8253d9f541c98b6e2cdabd930401ff2",
          evidence_schema_version: "requirement-plan-awaiting-review-v1",
          evidence_policy_version: "reviewed-requirement-plan-v1",
          local_only: true,
          content_persisted: false,
        }),
        plan: {
          value_state: "unknown" as const, capability_available: true, source_complete: true,
          eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_confirmation_required",
        },
      },
      {
        binding: parseModelRequirementPlanEvidenceBinding({
          evidence_source: "reviewed_requirement_plan",
          confirmation_id: "8".repeat(64),
          proposal_id: "9".repeat(64),
          evidence_fingerprint: "7".repeat(64),
          evidence_schema_version: "requirement-plan-evidence-v1",
          evidence_policy_version: "reviewed-requirement-plan-v1",
          local_only: true,
          content_persisted: false,
        }),
        plan: {
          value_state: "unknown" as const, capability_available: true, source_complete: false,
          eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
        },
      },
    ];
    for (const { binding, plan } of overflowBeforePlanAuthorityCases) {
      const run = r7RunFixture(overflowBinding);
      const publication = run.metric_publication_v2!;
      const planIndex = publication.metrics.findIndex(
        (item) => item.state.metric_key === "logic.decomposition_coverage",
      );
      const actionIndex = publication.metrics.findIndex(
        (item) => item.state.metric_key === "logic.requirement_action_traceability",
      );
      const unresolvedPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", plan);
      unresolvedPlan.state.projection_version = "metric-contract-v2-projection-7";
      publication.metrics[planIndex] = unresolvedPlan as typeof publication.metrics[number];
      publication.metrics[actionIndex] = zeroActionOverflow as typeof publication.metrics[number];
      publication.known_count -= 1;
      publication.unknown_count += 1;
      run.requirement_plan_evidence_binding = binding;
      expect(parseModelEnsembleRun(structuredClone(run))).toEqual(run);
    }

    const mismatchedEmptyOverflow = structuredClone(emptyOverflow);
    const oneActionOverflow = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 1, unknown: 1, explanation_code: "requirement_action_evidence_overflow",
      },
    );
    oneActionOverflow.state.projection_version = "metric-contract-v2-projection-7";
    mismatchedEmptyOverflow.metric_publication_v2!.metrics[emptyActionIndex] =
      oneActionOverflow as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    expect(() => parseModelEnsembleRun(mismatchedEmptyOverflow))
      .toThrow(ModelEnsemblePayloadError);

    const invalidPlan = r7RunFixture(markers.find(
      (binding) => binding.evidence_source === "binding_invalid",
    )!);
    const invalidPlanPublication = invalidPlan.metric_publication_v2!;
    const invalidPlanIndex = invalidPlanPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const invalidPlanActionIndex = invalidPlanPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const sealedInvalidPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "unknown", capability_available: true, source_complete: false,
      eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
    });
    sealedInvalidPlan.state.projection_version = "metric-contract-v2-projection-7";
    const zeroInvalidAction = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 0, unknown: 0, explanation_code: "requirement_action_evidence_invalid",
      },
    );
    zeroInvalidAction.state.projection_version = "metric-contract-v2-projection-7";
    invalidPlanPublication.metrics[invalidPlanIndex] = sealedInvalidPlan as typeof invalidPlanPublication.metrics[number];
    invalidPlanPublication.metrics[invalidPlanActionIndex] = zeroInvalidAction as typeof invalidPlanPublication.metrics[number];
    invalidPlanPublication.known_count -= 1;
    invalidPlanPublication.unknown_count += 1;
    expect(parseModelEnsembleRun(structuredClone(invalidPlan))).toEqual(invalidPlan);

    const invalidPlanWithInventedDenominator = structuredClone(invalidPlan);
    const inventedAction = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      {
        value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 1, unknown: 1, explanation_code: "requirement_action_evidence_invalid",
      },
    );
    inventedAction.state.projection_version = "metric-contract-v2-projection-7";
    invalidPlanWithInventedDenominator.metric_publication_v2!.metrics[invalidPlanActionIndex] =
      inventedAction as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    expect(() => parseModelEnsembleRun(invalidPlanWithInventedDenominator))
      .toThrow(ModelEnsemblePayloadError);

    const reviewed = parseModelRequirementActionEvidenceBinding({
      evidence_source: "reviewed_requirement_action",
      // The reviewed authority targets the predecessor source run used to
      // create the proposal, not the newly sealed analysis run.
      source_run_id: "d".repeat(64),
      requirement_plan_confirmation_id: "8".repeat(64),
      requirement_plan_evidence_fingerprint: "7".repeat(64),
      candidate_manifest_fingerprint: "4".repeat(64),
      confirmation_id: "5".repeat(64),
      proposal_id: "6".repeat(64),
      reviewed_descriptor_set_fingerprint: "a".repeat(64),
      evidence_fingerprint: "c".repeat(64),
      evidence_schema_version: "requirement-action-evidence-v1",
      evidence_policy_version: "reviewed-requirement-action-v1",
      local_only: true,
      content_persisted: false,
    });
    const reviewedRun = r7RunFixture(reviewed);
    expect(parseModelEnsembleRun(structuredClone(reviewedRun))).toEqual(reviewedRun);

    const reviewedPending = r7RunFixture(reviewed);
    const reviewedPendingPublication = reviewedPending.metric_publication_v2!;
    const reviewedPendingActionIndex = reviewedPendingPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const pendingAction = syntheticPublishedMetricV2("logic.requirement_action_traceability", {
      value_state: "pending", capability_available: true, source_complete: true,
      eligible: 2, numerator: 1, pending: 1,
      explanation_code: "opportunity_right_censored",
    });
    pendingAction.state.projection_version = "metric-contract-v2-projection-7";
    reviewedPendingPublication.metrics[reviewedPendingActionIndex] =
      pendingAction as typeof reviewedPendingPublication.metrics[number];
    reviewedPendingPublication.known_count -= 1;
    reviewedPendingPublication.pending_count += 1;
    reviewedPendingPublication.objective_measured_count -= 1;
    expect(parseModelEnsembleRun(structuredClone(reviewedPending))).toEqual(reviewedPending);

    const pendingWrongReason = structuredClone(reviewedPending);
    const pendingWrongRow = pendingWrongReason.metric_publication_v2!.metrics[reviewedPendingActionIndex];
    pendingWrongRow.state.explanation_code = "reviewed_requirement_action_links";
    pendingWrongRow.guidance.reason_code = "reviewed_requirement_action_links";
    expect(() => parseModelEnsembleRun(pendingWrongReason)).toThrow(ModelEnsemblePayloadError);

    const reviewedEmpty = r7RunFixture(reviewed);
    const reviewedEmptyPublication = reviewedEmpty.metric_publication_v2!;
    const reviewedEmptyPlanIndex = reviewedEmptyPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    );
    const reviewedEmptyActionIndex = reviewedEmptyPublication.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const emptyReviewedPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "not_applicable", capability_available: true, source_complete: true,
      eligible: 0, explanation_code: "no_opportunity_observed",
    });
    emptyReviewedPlan.state.projection_version = "metric-contract-v2-projection-7";
    const emptyReviewedAction = syntheticPublishedMetricV2("logic.requirement_action_traceability", {
      value_state: "not_applicable", capability_available: true, source_complete: true,
      eligible: 0, explanation_code: "no_opportunity_observed",
    });
    emptyReviewedAction.state.projection_version = "metric-contract-v2-projection-7";
    reviewedEmptyPublication.metrics[reviewedEmptyPlanIndex] =
      emptyReviewedPlan as typeof reviewedEmptyPublication.metrics[number];
    reviewedEmptyPublication.metrics[reviewedEmptyActionIndex] =
      emptyReviewedAction as typeof reviewedEmptyPublication.metrics[number];
    reviewedEmptyPublication.known_count -= 2;
    reviewedEmptyPublication.not_applicable_count += 2;
    reviewedEmptyPublication.objective_measured_count -= 1;
    expect(parseModelEnsembleRun(structuredClone(reviewedEmpty))).toEqual(reviewedEmpty);

    const emptyWrongReason = structuredClone(reviewedEmpty);
    const emptyWrongRow = emptyWrongReason.metric_publication_v2!.metrics[reviewedEmptyActionIndex];
    emptyWrongRow.state.explanation_code = "reviewed_requirement_action_links";
    emptyWrongRow.guidance.reason_code = "reviewed_requirement_action_links";
    expect(() => parseModelEnsembleRun(emptyWrongReason)).toThrow(ModelEnsemblePayloadError);

    const reviewedEmptyWithInvalidPlan = structuredClone(reviewedEmpty);
    const invalidEmptyPlan = syntheticPublishedMetricV2("logic.decomposition_coverage", {
      value_state: "unknown", capability_available: true, source_complete: false,
      eligible: 0, unknown: 0, explanation_code: "requirement_plan_evidence_invalid",
    });
    invalidEmptyPlan.state.projection_version = "metric-contract-v2-projection-7";
    reviewedEmptyWithInvalidPlan.metric_publication_v2!.metrics[reviewedEmptyPlanIndex] =
      invalidEmptyPlan as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    reviewedEmptyWithInvalidPlan.metric_publication_v2!.not_applicable_count -= 1;
    reviewedEmptyWithInvalidPlan.metric_publication_v2!.unknown_count += 1;
    expect(() => parseModelEnsembleRun(reviewedEmptyWithInvalidPlan))
      .toThrow(ModelEnsemblePayloadError);

    const reviewedDenominatorDrift = r7RunFixture(reviewed);
    const reviewedActionIndex = reviewedDenominatorDrift.metric_publication_v2!.metrics.findIndex(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    );
    const oneRequirementReviewed = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      { value_state: "known", numerator: 1, denominator: 1,
        explanation_code: "reviewed_requirement_action_links" },
    );
    oneRequirementReviewed.state.projection_version = "metric-contract-v2-projection-7";
    reviewedDenominatorDrift.metric_publication_v2!.metrics[reviewedActionIndex] =
      oneRequirementReviewed as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    expect(() => parseModelEnsembleRun(reviewedDenominatorDrift))
      .toThrow(ModelEnsemblePayloadError);

    const reviewedAsInvalid = r7RunFixture(reviewed);
    const invalidAction = syntheticPublishedMetricV2(
      "logic.requirement_action_traceability",
      { value_state: "unknown", capability_available: true, source_complete: false,
        eligible: 2, unknown: 2, explanation_code: "requirement_action_evidence_invalid" },
    );
    invalidAction.state.projection_version = "metric-contract-v2-projection-7";
    reviewedAsInvalid.metric_publication_v2!.metrics[reviewedActionIndex] =
      invalidAction as NonNullable<ModelEnsembleRun["metric_publication_v2"]>["metrics"][number];
    reviewedAsInvalid.metric_publication_v2!.known_count -= 1;
    reviewedAsInvalid.metric_publication_v2!.unknown_count += 1;
    reviewedAsInvalid.metric_publication_v2!.objective_measured_count -= 1;
    expect(() => parseModelEnsembleRun(reviewedAsInvalid)).toThrow(ModelEnsemblePayloadError);

    for (const mutate of [
      (run: ModelEnsembleRun) => { run.requirement_action_evidence_binding!.requirement_plan_confirmation_id = "d".repeat(64); },
      (run: ModelEnsembleRun) => { run.requirement_action_evidence_binding!.requirement_plan_evidence_fingerprint = "d".repeat(64); },
      (run: ModelEnsembleRun) => { run.metric_publication_v2!.metrics.find((item) => item.state.metric_key === "logic.requirement_action_traceability")!.state.explanation_code = "requirement_action_evidence_confirmation_required"; },
    ]) {
      const crossed = structuredClone(reviewedRun);
      mutate(crossed);
      expect(() => parseModelEnsembleRun(crossed)).toThrow(ModelEnsemblePayloadError);
    }
  });

  it("parses exact backend r8 missing, invalid, overflow, and censored verification states", () => {
    type Scenario = NonNullable<Parameters<typeof syntheticPublishedMetricV2>[1]>;
    const actionMarker = (
      evidenceSource: "unavailable" | "binding_invalid",
      evidenceFingerprint: string,
      evidenceSchemaVersion: "requirement-action-unavailable-v1" | "requirement-action-binding-invalid-v1",
    ) => parseModelRequirementActionEvidenceBinding({
      evidence_source: evidenceSource,
      source_run_id: null,
      requirement_plan_confirmation_id: null,
      requirement_plan_evidence_fingerprint: null,
      candidate_manifest_fingerprint: null,
      confirmation_id: null,
      proposal_id: null,
      reviewed_descriptor_set_fingerprint: null,
      evidence_fingerprint: evidenceFingerprint,
      evidence_schema_version: evidenceSchemaVersion,
      evidence_policy_version: "reviewed-requirement-action-v1",
      local_only: true,
      content_persisted: false,
    });
    const reviewedAction = parseModelRequirementActionEvidenceBinding({
      evidence_source: "reviewed_requirement_action",
      source_run_id: "d".repeat(64),
      requirement_plan_confirmation_id: "8".repeat(64),
      requirement_plan_evidence_fingerprint: "7".repeat(64),
      candidate_manifest_fingerprint: "4".repeat(64),
      confirmation_id: "5".repeat(64),
      proposal_id: "6".repeat(64),
      reviewed_descriptor_set_fingerprint: "a".repeat(64),
      evidence_fingerprint: "c".repeat(64),
      evidence_schema_version: "requirement-action-evidence-v1",
      evidence_policy_version: "reviewed-requirement-action-v1",
      local_only: true,
      content_persisted: false,
    });
    const replaceMetric = (
      run: ModelEnsembleRun,
      metricKey: Parameters<typeof syntheticPublishedMetricV2>[0],
      scenario: Scenario,
      distinctOwnerCount?: number,
      metCount?: number,
      notMetCount?: number,
    ) => {
      const publication = run.metric_publication_v2!;
      const index = publication.metrics.findIndex(
        (item) => item.state.metric_key === metricKey,
      );
      const item = syntheticPublishedMetricV2(metricKey, scenario);
      item.state.projection_version = "metric-contract-v2-projection-8";
      if (distinctOwnerCount !== undefined) {
        item.state.statistics.distinct_owner_count = distinctOwnerCount;
      }
      if (metCount !== undefined && notMetCount !== undefined) {
        item.state.statistics.met_count = metCount;
        item.state.statistics.not_met_count = notMetCount;
        item.guidance.met_count = metCount;
        item.guidance.not_met_count = notMetCount;
      }
      publication.metrics[index] = item as typeof publication.metrics[number];
    };
    const upgrade = (
      run: ModelEnsembleRun,
      binding: NonNullable<ModelEnsembleRun["requirement_verification_evidence_binding"]>,
      scenario: Scenario,
      distinctOwnerCount = 0,
      metCount?: number,
      notMetCount?: number,
    ) => {
      const publication = run.metric_publication_v2!;
      publication.projection_version = "metric-contract-v2-projection-8";
      for (const item of publication.metrics) {
        item.state.projection_version = "metric-contract-v2-projection-8";
      }
      replaceMetric(
        run,
        "outcome.verified_requirement_coverage",
        scenario,
        distinctOwnerCount,
        metCount,
        notMetCount,
      );
      const verified = publication.metrics.find(
        (item) => item.state.metric_key === "outcome.verified_requirement_coverage",
      )!.state;
      const typedVerification = run.typed_metrics.find(
        (item) => item.metric_key === "outcome.verified_requirement_coverage",
      )!;
      const resolved = verified.statistics.met_count + verified.statistics.not_met_count;
      Object.assign(typedVerification, {
        value_state: verified.value_state,
        numerator: verified.numerator,
        denominator: verified.denominator,
        numeric_value: verified.numeric_value,
        observed_message_count: resolved,
        eligible_message_count: verified.statistics.eligible_count,
        coverage: verified.statistics.eligible_count === 0
          ? 0
          : resolved / verified.statistics.eligible_count,
        explanation_code: verified.explanation_code,
        error_code: null,
        engine_version: "reviewed-requirement-verification-objective-projection-v1",
        algorithm_id: "reviewed-requirement-verification-authority",
        algorithm_version: "4",
        rubric_version: "objective-evidence-no-rubric-v4",
      });
      run.requirement_verification_evidence_binding = binding;
      return run;
    };

    const missing = r7RunFixture(actionMarker(
      "unavailable",
      "9059e785839871abf94e1fea1c86c48e737621047a526cd3c9e94099a5b5e07f",
      "requirement-action-unavailable-v1",
    ));
    missing.requirement_plan_evidence_binding = parseModelRequirementPlanEvidenceBinding({
      evidence_source: "unavailable",
      confirmation_id: null,
      proposal_id: null,
      evidence_fingerprint: "30f6b309825c563a881ed1b7587072222e3cb33ca70f7bff274ba968cb067641",
      evidence_schema_version: "requirement-plan-unavailable-v1",
      evidence_policy_version: "reviewed-requirement-plan-v1",
      local_only: true,
      content_persisted: false,
    });
    replaceMetric(missing, "logic.decomposition_coverage", {
      value_state: "unknown", capability_available: false, source_complete: true,
      explanation_code: "requirement_plan_evidence_unavailable",
    });
    replaceMetric(missing, "logic.requirement_action_traceability", {
      value_state: "unknown", capability_available: false, source_complete: true,
      explanation_code: "requirement_action_evidence_unavailable",
    });
    missing.metric_publication_v2!.known_count -= 1;
    missing.metric_publication_v2!.unknown_count += 1;
    upgrade(missing, r8UnavailableVerificationBinding(), {
      value_state: "unknown", capability_available: false, source_complete: true,
      explanation_code: "reviewed_requirement_authority_unavailable",
    });

    const invalid = r7RunFixture(actionMarker(
      "binding_invalid",
      "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da",
      "requirement-action-binding-invalid-v1",
    ));
    replaceMetric(invalid, "logic.decomposition_coverage", {
      value_state: "unknown", capability_available: true, source_complete: false,
      explanation_code: "requirement_plan_evidence_invalid",
    });
    replaceMetric(invalid, "logic.requirement_action_traceability", {
      value_state: "unknown", capability_available: true, source_complete: false,
      explanation_code: "requirement_action_evidence_invalid",
    });
    invalid.metric_publication_v2!.known_count -= 1;
    invalid.metric_publication_v2!.unknown_count += 1;
    upgrade(invalid, r8UnavailableVerificationBinding(), {
      value_state: "unknown", capability_available: true, source_complete: false,
      explanation_code: "reviewed_requirement_authority_invalid",
    });

    const overflow = r7RunFixture(reviewedAction);
    replaceMetric(overflow, "logic.decomposition_coverage", {
      value_state: "known", numerator: 1, denominator: 101,
      explanation_code: "reviewed_requirement_plan_links",
    });
    replaceMetric(overflow, "logic.requirement_action_traceability", {
      value_state: "known", numerator: 1, denominator: 101,
      explanation_code: "reviewed_requirement_action_links",
    });
    upgrade(overflow, r8OverflowVerificationBinding(), {
      value_state: "unknown", capability_available: true, source_complete: true,
      explanation_code: "typed_objective_opportunity_count_exceeds_receipt_bound",
    });

    const unavailableReader = upgrade(
      r7RunFixture(reviewedAction),
      r8UnavailableVerificationBinding(),
      {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 2, unknown: 2, censoring_lower_bound: 0, censoring_upper_bound: 1,
        explanation_code: "requirement_verification_evidence_unavailable",
      },
      2,
    );
    const awaiting = upgrade(
      r7RunFixture(reviewedAction),
      r8AwaitingVerificationBinding(),
      {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 2, unknown: 2, censoring_lower_bound: 0, censoring_upper_bound: 1,
        explanation_code: "requirement_verification_evidence_unavailable",
      },
      2,
    );
    const persisted = upgrade(
      r7RunFixture(reviewedAction),
      r8PersistedVerificationBinding(),
      {
        value_state: "unknown", capability_available: true, source_complete: true,
        eligible: 2, unknown: 1, censoring_lower_bound: 0.5, censoring_upper_bound: 1,
        explanation_code: "app_issued_requirement_verification_pending",
      },
      2,
      1,
      0,
    );

    expect(overflow.metric_publication_v2!.known_count).toBe(
      overflow.metric_publication_v2!.metrics.filter(
        (item) => item.state.value_state === "known",
      ).length,
    );
    expect(overflow.metric_publication_v2!.objective_measured_count).toBe(
      overflow.metric_publication_v2!.metrics.filter(
        (item) => item.state.value_state === "known"
          && item.state.evidence_authority === "objective_receipt",
      ).length,
    );
    overflow.metric_publication_v2!.metrics.forEach((item) => {
      expect(
        () => parseMetricV2State(structuredClone(item.state), item.state.metric_key),
        `backend r8 overflow ${item.state.metric_key} state`,
      ).not.toThrow();
    });

    for (const [label, run] of [
      ["missing", missing],
      ["invalid", invalid],
      ["overflow", overflow],
      ["unavailable reader", unavailableReader],
      ["awaiting", awaiting],
      ["persisted", persisted],
    ] as const) {
      expect(
        () => parseModelEnsembleRun(structuredClone(run)),
        `backend r8 ${label} DTO shape`,
      ).not.toThrow();
      expect(parseModelEnsembleRun(structuredClone(run))).toEqual(run);
    }

    const wrongMissingFlags = structuredClone(missing);
    const wrongMissingState = wrongMissingFlags.metric_publication_v2!.metrics.find(
      (item) => item.state.metric_key === "outcome.verified_requirement_coverage",
    )!.state;
    wrongMissingState.statistics.source_complete = false;
    expect(() => parseModelEnsembleRun(wrongMissingFlags)).toThrow(ModelEnsemblePayloadError);

    const wrongOverflowFlags = structuredClone(overflow);
    const wrongOverflowState = wrongOverflowFlags.metric_publication_v2!.metrics.find(
      (item) => item.state.metric_key === "outcome.verified_requirement_coverage",
    )!.state;
    wrongOverflowState.statistics.capability_available = false;
    expect(() => parseModelEnsembleRun(wrongOverflowFlags)).toThrow(ModelEnsemblePayloadError);

    for (const mutate of [
      (state: typeof wrongOverflowState) => { state.statistics.superseded_excluded_count = 1; },
      (state: typeof wrongOverflowState) => { state.statistics.distinct_owner_count += 1; },
    ]) {
      const crossed = structuredClone(awaiting);
      const state = crossed.metric_publication_v2!.metrics.find(
        (item) => item.state.metric_key === "outcome.verified_requirement_coverage",
      )!.state;
      mutate(state);
      expect(() => parseModelEnsembleRun(crossed)).toThrow(ModelEnsemblePayloadError);
    }

    const forgedTypedAuthority = structuredClone(persisted);
    forgedTypedAuthority.typed_metrics.find(
      (item) => item.metric_key === "outcome.verified_requirement_coverage",
    )!.algorithm_id = "typed-objective-evidence";
    expect(() => parseModelEnsembleRun(forgedTypedAuthority)).toThrow(ModelEnsemblePayloadError);

    for (const source of [unavailableReader, awaiting, persisted]) {
      const wrongBounds = structuredClone(source);
      const item = wrongBounds.metric_publication_v2!.metrics.find(
        (candidate) => candidate.state.metric_key === "outcome.verified_requirement_coverage",
      )!;
      item.state.censoring_lower_bound = null;
      item.state.censoring_upper_bound = null;
      item.guidance.censoring_lower_bound = null;
      item.guidance.censoring_upper_bound = null;
      expect(() => parseModelEnsembleRun(wrongBounds)).toThrow(ModelEnsemblePayloadError);
    }
  });

  it("keeps unconfigured declared-profile metrics entirely nonnumeric and count-free", () => {
    const unconfiguredBinding = parseModelMetricProfileBinding({
      profile_source: "coaching_profile_v1_unconfigured",
      profile_id: null,
      profile_revision: null,
      profile_fingerprint: "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71",
      profile_schema_version: "coaching-profile-v1-unconfigured",
      profile_policy_version: "server-preset-v1",
      local_only: true,
      content_persisted: false,
    });
    const valid = r5RunFixture(unconfiguredBinding);
    expect(parseModelEnsembleRun(structuredClone(valid))).toEqual(valid);

    const known = structuredClone(valid);
    const knownIndex = known.metric_publication_v2!.metrics.findIndex(
      (item) => item.state.metric_key === "prompt.constraint_precision",
    );
    const knownMetric = syntheticPublishedMetricV2("prompt.constraint_precision", {
      value_state: "known",
      numerator: 1,
      denominator: 1,
    });
    knownMetric.state.projection_version = "metric-contract-v2-projection-5";
    known.metric_publication_v2!.metrics[knownIndex] = knownMetric as NonNullable<
      ModelEnsembleRun["metric_publication_v2"]
    >["metrics"][number];
    known.metric_publication_v2!.known_count += 1;
    known.metric_publication_v2!.unknown_count -= 1;
    expect(() => parseModelEnsembleRun(known)).toThrow(ModelEnsemblePayloadError);

    const countedUnknown = structuredClone(valid);
    const countedIndex = countedUnknown.metric_publication_v2!.metrics.findIndex(
      (item) => item.state.metric_key === "prompt.acceptance_testability",
    );
    const countedMetric = syntheticPublishedMetricV2("prompt.acceptance_testability", {
      value_state: "unknown",
      eligible: 1,
      unknown: 1,
      capability_available: true,
    });
    countedMetric.state.projection_version = "metric-contract-v2-projection-5";
    countedUnknown.metric_publication_v2!.metrics[countedIndex] = countedMetric as NonNullable<
      ModelEnsembleRun["metric_publication_v2"]
    >["metrics"][number];
    expect(() => parseModelEnsembleRun(countedUnknown)).toThrow(ModelEnsemblePayloadError);

    const boundedUnknown = structuredClone(valid);
    const boundedItem = boundedUnknown.metric_publication_v2!.metrics.find(
      (item) => item.state.metric_key === "prompt.deliverable_contract",
    )!;
    boundedItem.state.censoring_lower_bound = 0;
    boundedItem.state.censoring_upper_bound = 0;
    boundedItem.guidance.censoring_lower_bound = 0;
    boundedItem.guidance.censoring_upper_bound = 0;
    expect(() => parseModelEnsembleRun(boundedUnknown)).toThrow(ModelEnsemblePayloadError);

    const declared = structuredClone(known);
    declared.metric_profile_binding = parseModelMetricProfileBinding({
      profile_source: "declared_task_profile",
      profile_id: "1".repeat(64),
      profile_revision: 3,
      profile_fingerprint: "2".repeat(64),
      profile_schema_version: "declared-task-profile-v1",
      profile_policy_version: "authenticated-local-user-v1",
      local_only: true,
      content_persisted: false,
    });
    expect(parseModelEnsembleRun(declared)).toEqual(declared);
  });

  it("accepts the complete fixed committee and rejects missing votes", () => {
    const valid = runFixture();
    expect(parseModelEnsembleRun(structuredClone(valid))).toEqual(valid);
    expect(parseModelEnsembleOutcome({ run: structuredClone(valid), applied: true })).toEqual({
      run: valid,
      applied: true,
    });
    const invalid = structuredClone(valid);
    invalid.votes.pop();
    expect(() => parseModelEnsembleRun(invalid)).toThrow(ModelEnsemblePayloadError);
  });

  it("preserves a zero-opportunity typed metric as nonnumeric", () => {
    const valid = structuredClone(runFixture());
    valid.typed_metrics[0] = {
      ...valid.typed_metrics[0],
      value_state: "unknown",
      numerator: null,
      denominator: null,
      numeric_value: null,
      observed_message_count: 0,
      eligible_message_count: 0,
      coverage: 0,
      explanation_code: "typed_opportunity_unavailable",
    };

    expect(parseModelEnsembleRun(valid)).toEqual(valid);

    const boundedSuffix = structuredClone(runFixture());
    boundedSuffix.typed_metrics[0] = {
      ...boundedSuffix.typed_metrics[0],
      observed_message_count: 100,
      eligible_message_count: 324,
      coverage: 100 / 324,
    };
    expect(parseModelEnsembleRun(boundedSuffix)).toEqual(boundedSuffix);
  });

  it("rejects false unload claims, impossible dates, and aggregate tampering", () => {
    const unload = structuredClone(runFixture());
    unload.experts[0].unloaded_after_stage = false as true;
    expect(() => parseModelEnsembleRun(unload)).toThrow(ModelEnsemblePayloadError);

    const calendar = structuredClone(runFixture());
    calendar.completed_at = "2040-02-31T10:00:00Z";
    expect(() => parseModelEnsembleRun(calendar)).toThrow(ModelEnsemblePayloadError);

    const aggregate = structuredClone(runFixture());
    aggregate.metrics[0].numeric_value = 0.5;
    expect(() => parseModelEnsembleRun(aggregate)).toThrow(ModelEnsemblePayloadError);
  });

  it("uses exact private loopback routes and rejects cacheable model receipts", async () => {
    const auth = new Response(
      JSON.stringify({ csrf_token: "example-csrf", expires_in_seconds: 300 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    const privateResponse = (body: unknown) => new Response(JSON.stringify(body), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
      },
    });
    const fetch = vi.fn()
      .mockResolvedValueOnce(auth)
      .mockResolvedValueOnce(privateResponse(runFixture()))
      .mockResolvedValueOnce(privateResponse({ run: runFixture(), applied: true }));
    const transport = createHttpTransport({ fetch, origin: "http://127.0.0.1:8765" });

    await transport.getLatestModelEnsemble(SESSION_ID);
    await transport.startModelEnsemble(
      SESSION_ID,
      { confirmation: "run_local_metric_cascade_on_selected_redacted_text" },
      "example-model-ensemble-key-0001",
    );

    const calls = fetch.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls[1][0]).toBe(`/v1/sessions/${SESSION_ID}/model-ensemble-runs/latest`);
    expect(calls[2][0]).toBe(`/v1/sessions/${SESSION_ID}/model-ensemble-runs`);
    expect(calls[2][1].cache).toBe("no-store");
    expect((calls[2][1].headers as Record<string, string>)["Idempotency-Key"]).toBe("example-model-ensemble-key-0001");

    const unsafeFetch = vi.fn()
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ csrf_token: "example-csrf", expires_in_seconds: 300 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(JSON.stringify(runFixture()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    await expect(
      createHttpTransport({ fetch: unsafeFetch, origin: "http://127.0.0.1:8765" })
        .getLatestModelEnsemble(SESSION_ID),
    ).rejects.toThrow("Private local response was not cache-safe");
  });

  it("validates continuous-watch identity, truth flags, timestamps, and result coherence", () => {
    const valid = watchFixture(runFixture());
    expect(parseModelEnsembleWatchSnapshot(structuredClone(valid))).toEqual(valid);

    const extra = structuredClone(valid) as unknown as Record<string, unknown>;
    extra.private_text = "SYNTHETIC_PRIVATE_CANARY";
    expect(() => parseModelEnsembleWatchSnapshot(extra)).toThrow(ModelEnsembleWatchPayloadError);

    const invalidDate = structuredClone(valid);
    invalidDate.watch.updated_at = "2040-02-31T10:00:00Z";
    expect(() => parseModelEnsembleWatchSnapshot(invalidDate)).toThrow(ModelEnsembleWatchPayloadError);

    const missing = structuredClone(valid);
    missing.latest_run = null;
    expect(() => parseModelEnsembleWatchSnapshot(missing)).toThrow(ModelEnsembleWatchPayloadError);

    const falseRelease = structuredClone(valid);
    falseRelease.watch.process_isolated_model_release = false as true;
    expect(() => parseModelEnsembleWatchSnapshot(falseRelease)).toThrow(ModelEnsembleWatchPayloadError);

    const invalidWindow = structuredClone(valid);
    invalidWindow.watch.max_messages = 101;
    expect(() => parseModelEnsembleWatchSnapshot(invalidWindow)).toThrow(ModelEnsembleWatchPayloadError);
  });

  it("validates the slim trajectory graph and rejects forged chronology or metric counts", () => {
    const valid = trajectoryFixture();
    expect(parseModelEnsembleTrajectoryPage(structuredClone(valid))).toEqual(valid);

    const ownedObservation = structuredClone(valid);
    ownedObservation.points[0].chunk_count = 2;
    expect(parseModelEnsembleTrajectoryPage(ownedObservation)).toEqual(ownedObservation);

    const extra = structuredClone(valid) as unknown as Record<string, unknown>;
    extra.private_text = "SYNTHETIC_PRIVATE_CANARY";
    expect(() => parseModelEnsembleTrajectoryPage(extra)).toThrow(ModelEnsembleTrajectoryPayloadError);

    const chronology = structuredClone(valid);
    chronology.points[0].published_at = "2040-01-02T09:59:59Z";
    expect(() => parseModelEnsembleTrajectoryPage(chronology)).toThrow(ModelEnsembleTrajectoryPayloadError);

    const calendar = structuredClone(valid);
    calendar.points[0].completed_at = "2040-02-31T10:00:00Z";
    expect(() => parseModelEnsembleTrajectoryPage(calendar)).toThrow(ModelEnsembleTrajectoryPayloadError);

    const counts = structuredClone(valid);
    counts.points[0].metrics[0].known_chunk_count = 0;
    expect(() => parseModelEnsembleTrajectoryPage(counts)).toThrow(ModelEnsembleTrajectoryPayloadError);

    const wrongHead = structuredClone(valid);
    wrongHead.head_generation = 1;
    expect(() => parseModelEnsembleTrajectoryPage(wrongHead)).toThrow(ModelEnsembleTrajectoryPayloadError);
  });

  it("validates a fixed-bin predictive detail without accepting source text", () => {
    const valid = predictiveDetailFixture();
    expect(parseModelPredictiveMetricDetail(structuredClone(valid))).toEqual(valid);
    const forged = structuredClone(valid) as unknown as Record<string, unknown>;
    forged.private_text = "SYNTHETIC_PRIVATE_CANARY";
    expect(() => parseModelPredictiveMetricDetail(forged)).toThrow();
    const badDensity = structuredClone(valid);
    badDensity.density_bins[0] = 0.5;
    expect(() => parseModelPredictiveMetricDetail(badDensity)).toThrow();
  });

  it("uses exact private watch routes and cache-safe transport", async () => {
    const auth = new Response(
      JSON.stringify({ csrf_token: "example-csrf", expires_in_seconds: 300 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    const response = () => new Response(JSON.stringify(watchFixture()), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
      },
    });
    const fetch = vi.fn()
      .mockResolvedValueOnce(auth)
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(new Response(JSON.stringify(trajectoryFixture()), {
        status: 200,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "no-store, private",
          Pragma: "no-cache",
        },
      }));
    const transport = createHttpTransport({ fetch, origin: "http://127.0.0.1:8765" });

    await transport.getActiveModelEnsembleWatch!();
    await transport.enableModelEnsembleWatch!(SESSION_ID, {
      project_id: PROJECT_ID,
      max_messages: 25,
      confirmation: "continuously_analyze_selected_redacted_session",
    });
    await transport.disableModelEnsembleWatch!("d".repeat(64));
    await transport.getModelEnsembleTrajectory!("d".repeat(64), 24, 8);

    const calls = fetch.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls[1][0]).toBe("/v1/model-ensemble-watch/active");
    expect(calls[2][0]).toBe(`/v1/sessions/${SESSION_ID}/model-ensemble-watch`);
    expect(calls[2][1].method).toBe("PUT");
    expect(calls[2][1].cache).toBe("no-store");
    expect(calls[3][0]).toBe(`/v1/model-ensemble-watches/${"d".repeat(64)}`);
    expect(calls[3][1].method).toBe("DELETE");
    expect(calls[4][0]).toBe(`/v1/model-ensemble-watches/${"d".repeat(64)}/trajectory?limit=24&before_generation=8`);
    expect(calls[4][1].method).toBe("GET");
    expect(calls[4][1].cache).toBe("no-store");
  });

  it("uses the exact canonical-head, immutable-snapshot, enqueue, and cancellation routes", async () => {
    const run = runFixture();
    const head = canonicalHeadFixture(run);
    const auth = new Response(
      JSON.stringify({ csrf_token: "example-csrf", expires_in_seconds: 300 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
    const privateResponse = (body: unknown) => new Response(JSON.stringify(body), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, private",
        Pragma: "no-cache",
      },
    });
    const fetch = vi.fn()
      .mockResolvedValueOnce(auth)
      .mockResolvedValueOnce(privateResponse(head))
      .mockResolvedValueOnce(privateResponse(head))
      .mockResolvedValueOnce(privateResponse(run))
      .mockResolvedValueOnce(privateResponse(head))
      .mockResolvedValueOnce(privateResponse(canonicalHeadFixture(run, SESSION_ID, "cancelled")));
    const transport = createHttpTransport({ fetch, origin: "http://127.0.0.1:8765" });

    await transport.getActiveModelEnsembleCanonicalHead!();
    await transport.getSessionModelEnsembleCanonicalHead!(SESSION_ID);
    await transport.getModelEnsembleSnapshot!(run.run_id);
    await transport.enqueueModelEnsembleAnalysis!(head.watch.watch_id);
    await transport.cancelModelEnsembleAnalysis!(head.watch.watch_id);

    const calls = fetch.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls[1][0]).toBe("/v2/model-ensemble-watch/active/head");
    expect(calls[1][1].method).toBe("GET");
    expect(calls[2][0]).toBe(`/v2/sessions/${SESSION_ID}/model-ensemble-head`);
    expect(calls[2][1].method).toBe("GET");
    expect(calls[3][0]).toBe(`/v2/model-ensemble-snapshots/${run.run_id}`);
    expect(calls[3][1].method).toBe("GET");
    expect(calls[4][0]).toBe(`/v2/model-ensemble-watches/${head.watch.watch_id}/analysis`);
    expect(calls[4][1].method).toBe("POST");
    expect(calls[5][0]).toBe(`/v2/model-ensemble-watches/${head.watch.watch_id}/attempts/active`);
    expect(calls[5][1].method).toBe("DELETE");
  });
});

describe("ModelEnsemblePanel", () => {
  it("keeps full and compact workspaces on the exact same sealed snapshot contract", () => {
    const run = runFixture();
    const transport = createSyntheticTransport();
    const view = render(
      <>
        <MetricWorkspace
          lensId="task-framing"
          mode="full"
          onLensChange={vi.fn()}
          run={run}
          runId={run.run_id}
          snapshotLabel="Sealed source window"
          stageRun={run}
          transport={transport}
        />
        <MetricWorkspace
          lensId="task-framing"
          mode="compact"
          onLensChange={vi.fn()}
          run={run}
          runId={run.run_id}
          snapshotLabel="Sealed source window"
          stageRun={run}
          transport={transport}
        />
      </>,
    );

    const workspaces = [...view.container.querySelectorAll(".metric-workspace")];
    expect(workspaces).toHaveLength(2);
    expect(workspaces.map((node) => node.getAttribute("data-run-id"))).toEqual([run.run_id, run.run_id]);
    expect(screen.getAllByRole("heading", {
      level: 3,
      name: `Metric workspace · Snapshot ${run.run_id.slice(0, 8)}…${run.run_id.slice(-4)}`,
    })).toHaveLength(2);
    expect(screen.getAllByRole("group", { name: "Metric workspace view" })).toHaveLength(2);
    expect(screen.getAllByText("History")).toHaveLength(2);
    expect(screen.getAllByText("Scope not exposed")).toHaveLength(2);
  });

  it("keeps the reviewed agent-evidence workflow available for current r5 snapshots", () => {
    const run = runFixture();
    run.metric_publication_v2 = syntheticMetricPublicationV2();
    run.metric_publication_v2.projection_version = "metric-contract-v2-projection-5";
    expect(run.metric_publication_v2?.projection_version).toBe(
      "metric-contract-v2-projection-5",
    );
    const props = {
      evidenceEnabled: true,
      evidenceSessionId: SESSION_ID,
      lensId: "collaboration-flow" as const,
      mode: "full" as const,
      onLensChange: vi.fn(),
      run,
      runId: run.run_id,
      snapshotLabel: "Sealed source window",
      stageRun: run,
      transport: createSyntheticTransport(),
    };
    const view = render(<MetricWorkspace {...props} />);

    expect(screen.getByRole("region", { name: "Import agent metric evidence" })).toBeVisible();

    const historical = structuredClone(run);
    if (historical.metric_publication_v2 === null) {
      throw new Error("synthetic run is missing its publication");
    }
    historical.metric_publication_v2.projection_version = "metric-contract-v2-projection-3";
    view.rerender(<MetricWorkspace {...props} run={historical} />);

    expect(screen.queryByRole("region", { name: "Import agent metric evidence" })).not.toBeInTheDocument();
  });

  it("routes the strict requirement-plan workflow for an exact selected r7 snapshot", () => {
    const actionBinding = parseModelRequirementActionEvidenceBinding({
      evidence_source: "awaiting_review",
      source_run_id: null,
      requirement_plan_confirmation_id: null,
      requirement_plan_evidence_fingerprint: null,
      candidate_manifest_fingerprint: null,
      confirmation_id: null,
      proposal_id: null,
      reviewed_descriptor_set_fingerprint: null,
      evidence_fingerprint: "0ca65041b98be25e41cbbba908641f116f0e81b45416f89fd7ddf177489add4a",
      evidence_schema_version: "requirement-action-awaiting-review-v1",
      evidence_policy_version: "reviewed-requirement-action-v1",
      local_only: true,
      content_persisted: false,
    });
    const run = r7RunFixture(actionBinding);
    const props = {
      evidenceEnabled: true,
      evidenceSessionId: SESSION_ID,
      lensId: "collaboration-flow" as const,
      mode: "full" as const,
      onLensChange: vi.fn(),
      run,
      runId: run.run_id,
      snapshotLabel: "Sealed r7 source window",
      stageRun: run,
      transport: createSyntheticTransport(),
    };
    const view = render(<MetricWorkspace {...props} />);

    expect(screen.getByRole("region", { name: "Review requirement-to-plan evidence" })).toBeVisible();
    expect(screen.getByText(/does not expose the complete reviewed requirement-plan boundary/i)).toBeVisible();

    const unsupported = structuredClone(run);
    unsupported.metric_publication_v2!.projection_version = "metric-contract-v2-projection-4";
    view.rerender(<MetricWorkspace {...props} run={unsupported} />);
    expect(screen.queryByRole("region", { name: "Review requirement-to-plan evidence" })).not.toBeInTheDocument();
  });

  it("renders the dynamic three-small plus Qwen terminal constellation without counting Qwen as a small expert", () => {
    const run = fourStageTerminalRun();
    const attemptStages = fourTerminalAttemptStages();
    expect(run.predictive_model_stages.map((stage) => stage.model_key)).toEqual(
      LIVE_TERMINAL_MODEL_SPECS.map((stage) => stage.modelKey),
    );
    expect(modelEnsembleCompletedSmallExperts(run)).toBe(3);

    render(
      <MetricWorkspace
        attemptStages={attemptStages}
        lensId="task-framing"
        mode="compact"
        onLensChange={vi.fn()}
        run={run}
        runId={run.run_id}
        snapshotLabel="Sealed source window"
        stageRun={run}
        transport={createSyntheticTransport()}
      />,
    );

    expect(screen.getByText("Models").parentElement).toHaveTextContent(
      "Latest attempt · 4/4 stages completed",
    );
    fireEvent.click(screen.getByText("Models"));
    const factorGroup = screen.getByText("Factor models").closest("section");
    const deepGroup = screen.getByText("Deep judge").closest("section");
    expect(factorGroup).not.toBeNull();
    expect(deepGroup).not.toBeNull();
    expect(within(factorGroup!).getAllByRole("button")).toHaveLength(3);
    expect(within(deepGroup!).getAllByRole("button")).toHaveLength(1);
    expect(within(deepGroup!).getByText("qwen3-4b-rubric")).toBeVisible();
    expect(screen.queryByText("Challengers")).not.toBeInTheDocument();

    const belowGate = structuredClone(run);
    belowGate.predictive_model_stages = belowGate.predictive_model_stages.map((stage, ordinal) => ({
      ...stage,
      status: ordinal === 0 || stage.model_key === "qwen3_4b_rubric"
        ? "completed" as const
        : "failed" as const,
      error_code: ordinal === 0 || stage.model_key === "qwen3_4b_rubric"
        ? null
        : "example_optional_stage_failure",
    }));
    expect(modelEnsembleCompletedSmallExperts(belowGate)).toBe(1);
    const gatedAxis = modelEnsembleRadarAxes(belowGate, "task-framing")[0];
    expect(gatedAxis.predictiveMedian).toBeNull();
    expect(gatedAxis.predictiveWithheldReason).toMatch(/fewer than two small experts/i);
  });

  it("labels the model drawer as sealed-snapshot provenance when an active attempt has no stage rows", () => {
    const run = runFixture();
    render(
      <MetricWorkspace
        attemptStages={[]}
        lensId="task-framing"
        mode="compact"
        onLensChange={vi.fn()}
        run={run}
        runId={run.run_id}
        snapshotLabel="Last complete snapshot during active analysis"
        stageRun={run}
        transport={createSyntheticTransport()}
      />,
    );

    expect(screen.getByText("Models").parentElement).toHaveTextContent(
      "Sealed snapshot · 3/3 stages completed",
    );
    expect(screen.getByText("Models").parentElement).not.toHaveTextContent("Latest attempt");
  });

  it("shows the typed radar with separate diagnostics and never describes it as a product score", async () => {
    const getDetail = vi.fn(async (_runId: string, metricKey: string) => predictiveDetailFixture(metricKey));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => structuredClone(runFixture()),
      getModelPredictiveMetricDetail: getDetail,
    };
    const view = renderPanel(transport);

    expect(await screen.findByRole("img", { name: /typed local metric radar/i })).toBeVisible();
    expect(screen.getByText(/solid measurements and model ranges stay separate/i)).toBeVisible();
    expect(screen.getByText(/axes and order stay fixed/i)).toBeVisible();
    expect(screen.getByText(/gaps are unknown, not zero/i)).toBeVisible();
    expect(screen.getByText(/coverage, not confidence/i)).toBeVisible();
    expect(screen.getByText("Models").parentElement).toHaveTextContent("3/3 stages completed");
    expect(screen.getByText("History").parentElement).toHaveTextContent("Not exposed for this receipt");
    expect(screen.getByText("Sealed source window")).toBeVisible();
    fireEvent.click(screen.getByText("Models"));
    expect(screen.getByText("Released").parentElement).toHaveTextContent("yes");
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByText(/content-free trajectory/i)).toBeVisible();
    expect(await screen.findByLabelText("Radar-quality predictive density")).toBeVisible();
    expect(document.querySelector(".model-ensemble__radar-band")).not.toBeInTheDocument();
    expect(document.querySelector(".model-ensemble__radar-predictive-segment")).not.toBeInTheDocument();
    expect(view.container.querySelector("svg [role='button']")).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: /metric axes/i })).getAllByRole("button").length).toBeGreaterThan(0);
    expect(getDetail).toHaveBeenCalledWith(
      "b".repeat(64),
      "prompt.task_definition_coverage",
      expect.any(AbortSignal),
    );
  });

  it("preserves the open Models and History drawers while safe receipts arrive", () => {
    const run = runFixture();
    const trajectory = trajectoryFixture();
    const baseProps = {
      lensId: "task-framing" as const,
      mode: "compact" as const,
      onLensChange: vi.fn(),
      run,
      runId: run.run_id,
      snapshotLabel: "Sealed source window",
      transport: createSyntheticTransport(),
    };
    const view = render(<MetricWorkspace {...baseProps} stageRun={null} />);
    const models = screen.getByText("Models").closest("details")!;
    const history = screen.getByText("History").closest("details")!;
    fireEvent.click(screen.getByText("Models"));
    fireEvent.click(screen.getByText("History"));
    expect(models).toHaveAttribute("open");
    expect(history).toHaveAttribute("open");

    view.rerender(
      <MetricWorkspace
        {...baseProps}
        history={{
          points: trajectory.points,
          headRunId: trajectory.head_run_id,
          selectedRunId: trajectory.head_run_id,
          onSelectRun: vi.fn(),
        }}
        stageRun={run}
      />,
    );

    expect(screen.getByText("Models").closest("details")).toBe(models);
    expect(screen.getByText("History").closest("details")).toBe(history);
    expect(models).toHaveAttribute("open");
    expect(history).toHaveAttribute("open");
    expect(screen.getByText("1 sealed snapshots")).toBeVisible();
  });

  it("does not request factor density for an intentionally unavailable estimate", async () => {
    const run = runFixture();
    run.predictive_metrics[0] = {
      ...run.predictive_metrics[0],
      state: "unavailable",
    };
    const getModelPredictiveMetricDetail = vi.fn();
    render(
      <MetricWorkspace
        lensId="task-framing"
        mode="full"
        onLensChange={vi.fn()}
        run={run}
        runId={run.run_id}
        snapshotLabel="Sealed source window"
        stageRun={run}
        transport={{ getModelPredictiveMetricDetail }}
      />,
    );

    expect(screen.getByText("No experimental estimate is available.")).toBeVisible();
    expect(getModelPredictiveMetricDetail).not.toHaveBeenCalled();
    expect(screen.queryByText(/Detailed factor distribution is temporarily unavailable/i)).not.toBeInTheDocument();
  });

  it("labels lower-is-better measured values, estimates, and density in one radar-quality direction", async () => {
    const run = runFixture();
    const metricKey = "collaboration.rework_candidate_rate";
    run.typed_metrics.push({
      ...run.typed_metrics[0],
      metric_key: metricKey,
      numerator: 2,
      denominator: 100,
      numeric_value: 0.02,
    });
    run.metrics.push({
      ...run.metrics[0],
      metric_key: metricKey,
      numerator: 2,
      denominator: 100,
      numeric_value: 0.02,
    });
    const estimate = {
      ...run.predictive_metrics[0],
      metric_key: metricKey,
      median: 0.02,
      mean: 0.02,
      q05: 0.01,
      q25: 0.015,
      q75: 0.03,
      q95: 0.04,
      applicability_probability: null,
    };
    run.predictive_metrics.push(estimate);
    const density = Array.from({ length: 20 }, (_, index) => index === 0 ? 1 : 0);
    const getModelPredictiveMetricDetail = vi.fn(async (): Promise<ModelPredictiveMetricDetail> => ({
      run_id: run.run_id,
      projection_version: "local-probabilistic-radar-v1",
      projected_at: "2040-01-02T10:00:02Z",
      metric: estimate,
      density_bins: density,
      factors: [{
        factor_key: "avoidable_correction",
        scale: "binary",
        weight: 1,
        applicability_probability: 0.9,
        present_probability: 0.2,
        neutral_probability: 0.1,
        absent_probability: 0.7,
        expert_count: 3,
        critical: true,
      }],
      experimental_label: "Experimental model range",
      local_only: true,
      content_persisted: false,
      universal_trust_percentage_available: false,
    }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getModelPredictiveMetricDetail,
    };
    render(
      <MetricWorkspace
        lensId="collaboration-flow"
        mode="full"
        onLensChange={vi.fn()}
        run={run}
        runId={run.run_id}
        snapshotLabel="Sealed source window"
        stageRun={run}
        transport={transport}
      />,
    );
    const axes = screen.getByRole("navigation", { name: "Collaboration flow metric axes" });
    fireEvent.click(within(axes).getByRole("button", { name: /Rework/i }));

    expect(screen.getAllByText("98% radar quality").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/raw lower-is-better rate 2%/i)).toBeVisible();
    expect(screen.getByText("2% measured raw rate")).toBeVisible();
    expect(screen.getAllByText(/raw rate 2%/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/radar-quality median 98%/i)).toBeVisible();
    expect(screen.getByText(/Raw modeled lower-is-better rate: median 2%/i)).toBeVisible();
    expect(screen.getByText(/applicability not estimable/i)).toBeVisible();
    expect(screen.queryByText(/applicability 0%/i)).not.toBeInTheDocument();
    expect(screen.getByText(/effective support not established/i)).toBeVisible();
    expect(screen.queryByText(/n=1/i)).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Radar-quality predictive density")).toBeVisible();
    expect(screen.getByText(/density uses the same radar-quality direction/i)).toBeVisible();
  });

  it("uses the durable v2 watch job for analyze and cancellation in first-party mode", async () => {
    const run = runFixture();
    const enabled = watchFixture(run);
    const runningHead = canonicalHeadFixture(run);
    const cancelledHead = canonicalHeadFixture(run, SESSION_ID, "cancelled");
    cancelledHead.stages[0] = {
      ...cancelledHead.stages[0],
      state: "cancelled",
      error_code: "analysis_cancelled",
    };
    const startModelEnsemble = vi.fn();
    const enableModelEnsembleWatch = vi.fn(async () => enabled);
    const enqueueModelEnsembleAnalysis = vi.fn(async () => runningHead);
    const cancelModelEnsembleAnalysis = vi.fn(async () => cancelledHead);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      startModelEnsemble,
      getLatestModelEnsemble: async () => structuredClone(run),
      getSessionModelEnsembleCanonicalHead: vi.fn().mockRejectedValue({ status: 404 }),
      getModelEnsembleSnapshot: vi.fn(async () => structuredClone(run)),
      enableModelEnsembleWatch,
      enqueueModelEnsembleAnalysis,
      cancelModelEnsembleAnalysis,
    };
    renderPanel(transport);

    fireEvent.click(await screen.findByRole("button", { name: "Analyze metric ranges" }));
    await waitFor(() => expect(enableModelEnsembleWatch).toHaveBeenCalledWith(
      SESSION_ID,
      {
        project_id: PROJECT_ID,
        max_messages: 100,
        confirmation: "continuously_analyze_selected_redacted_session",
      },
      expect.any(AbortSignal),
    ));
    expect(enqueueModelEnsembleAnalysis).toHaveBeenCalledWith("d".repeat(64), expect.any(AbortSignal));
    expect(startModelEnsemble).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel analysis" }));
    await waitFor(() => expect(cancelModelEnsembleAnalysis).toHaveBeenCalledWith(
      "d".repeat(64),
      expect.any(AbortSignal),
    ));
    expect(screen.getByText(/Local analysis was cancelled/i)).toBeVisible();
    fireEvent.click(screen.getByText("Models"));
    expect(document.querySelector('.model-constellation__nodes button[data-status="cancelled"]')).toBeInTheDocument();
    expect(screen.getAllByText("cancelled").length).toBeGreaterThanOrEqual(1);
  });

  it("does not admit a legacy latest run when the same-session canonical head intentionally has no snapshot", async () => {
    const getModelEnsembleSnapshot = vi.fn(async () => runFixture());
    const getLatestModelEnsemble = vi.fn(async () => structuredClone(runFixture()));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble,
      getSessionModelEnsembleCanonicalHead: vi.fn(async () => emptyCanonicalHeadFixture()),
      getModelEnsembleSnapshot,
    };
    renderPanel(transport);

    expect(await screen.findByText(/Start one explicit run to create typed metric receipts/i)).toBeVisible();
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
    expect(getLatestModelEnsemble).not.toHaveBeenCalled();
    expect(getModelEnsembleSnapshot).not.toHaveBeenCalled();
  });

  it("applies an empty enqueue head immediately instead of retaining a previously loaded run", async () => {
    const oldRun = runFixture();
    const enabled = watchFixture(oldRun);
    const getModelEnsembleSnapshot = vi.fn(async () => oldRun);
    const getLatestModelEnsemble = vi.fn(async () => structuredClone(oldRun));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble,
      getSessionModelEnsembleCanonicalHead: vi.fn().mockRejectedValue({ status: 404 }),
      getModelEnsembleSnapshot,
      enableModelEnsembleWatch: vi.fn(async () => enabled),
      enqueueModelEnsembleAnalysis: vi.fn(async () => emptyCanonicalHeadFixture()),
    };
    renderPanel(transport);

    expect(await screen.findByText(/Start one explicit run to create typed metric receipts/i)).toBeVisible();
    expect(screen.queryByText(/Loading stored content-free receipts/i)).not.toBeInTheDocument();
    expect(getLatestModelEnsemble).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
    expect(getModelEnsembleSnapshot).not.toHaveBeenCalled();
  });

  it("shows a queued canonical watch as queued and disables duplicate analysis", async () => {
    const run = runFixture();
    const queuedHead = canonicalHeadFixture(run);
    queuedHead.watch.state = "queued";
    queuedHead.latest_attempt = {
      ...queuedHead.latest_attempt!,
      state: "completed",
      published_run_id: run.run_id,
      completed_at: "2040-01-02T10:00:02Z",
    };
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => structuredClone(run),
      getSessionModelEnsembleCanonicalHead: vi.fn(async () => queuedHead),
      getModelEnsembleSnapshot: vi.fn(async () => structuredClone(run)),
    };
    renderPanel(transport);

    expect(await screen.findByText("Analysis queued")).not.toHaveAttribute("role", "button");
    expect(screen.queryByRole("button", { name: "Analysis queued" })).not.toBeInTheDocument();
    expect(screen.getByText(/queued for the serial local model lane/i)).toBeVisible();
    expect(screen.getByText(/queued · waiting for the local model lane/i)).toBeVisible();
  });

  it("never admits another session's canonical snapshot or attempt stages", async () => {
    const run = runFixture();
    const foreignHead = canonicalHeadFixture(run, "9".repeat(64));
    const getLatestModelEnsemble = vi.fn(async () => structuredClone(run));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble,
      getSessionModelEnsembleCanonicalHead: vi.fn(async () => foreignHead),
      getModelEnsembleSnapshot: vi.fn(async () => structuredClone(run)),
      getModelEnsembleTrajectory: vi.fn(async () => trajectoryFixture()),
    };
    renderPanel(transport);

    expect(await screen.findByRole("status")).toHaveTextContent(/Checking for stored content-free/i);
    expect(screen.queryByText(/Start one explicit run to create typed metric receipts/i)).not.toBeInTheDocument();
    expect(screen.queryByText(`Snapshot ${run.run_id.slice(0, 8)}…${run.run_id.slice(-4)}`)).not.toBeInTheDocument();
    expect(screen.queryByText("foreign-stage")).not.toBeInTheDocument();
    expect(getLatestModelEnsemble).not.toHaveBeenCalled();
  });

  it("uses the same content-free trajectory drawer as the compact workspace", async () => {
    const run = runFixture();
    const olderRun = { ...structuredClone(run), run_id: "c".repeat(64) };
    const trajectory = trajectoryFixture();
    trajectory.points.push({
      ...structuredClone(trajectory.points[0]),
      generation: 1,
      run_id: olderRun.run_id,
      published_at: "2040-01-02T09:00:01Z",
      completed_at: "2040-01-02T09:00:00Z",
    });
    const getModelEnsembleTrajectory = vi.fn(async () => trajectory);
    const getModelEnsembleSnapshot = vi.fn(async () => olderRun);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => structuredClone(run),
      getSessionModelEnsembleCanonicalHead: undefined,
      getActiveModelEnsembleWatch: vi.fn(async () => watchFixture(run)),
      getModelEnsembleSnapshot,
      getModelEnsembleTrajectory,
    };
    renderPanel(transport);

    await waitFor(() => expect(getModelEnsembleTrajectory).toHaveBeenCalledWith(
      "d".repeat(64),
      24,
      undefined,
      expect.any(AbortSignal),
    ));
    expect(screen.getByText("Window").parentElement).toHaveTextContent("Newest 100 messages");
    expect(screen.getByText("History").parentElement).toHaveTextContent("2 sealed snapshots");
    fireEvent.click(screen.getByText("History"));
    expect(screen.getByRole("img", { name: "Selected metric history" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open live snapshot" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open earlier snapshot 2" }));
    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(
      olderRun.run_id,
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText(/radar-quality median 70%/i)).toBeVisible();
  });

  it("binds profile status to the selected exact seal instead of relabelling the latest head as visible history", async () => {
    const profile = declaredProfileFixture();
    const binding = parseModelMetricProfileBinding({
      profile_source: "declared_task_profile",
      profile_id: profile.profile_id,
      profile_revision: profile.revision,
      profile_fingerprint: profile.profile_fingerprint,
      profile_schema_version: profile.schema_version,
      profile_policy_version: profile.policy_version,
      local_only: true,
      content_persisted: false,
    });
    const headRun = r5RunFixture(binding);
    const historicalRun = { ...structuredClone(runFixture()), run_id: "c".repeat(64) };
    const trajectory = trajectoryFixture();
    trajectory.points[0] = {
      ...trajectory.points[0],
      metrics: headRun.metrics,
      typed_metrics: headRun.typed_metrics,
      metric_states_v2: headRun.metric_publication_v2!.metrics.map((item) => item.state),
    };
    trajectory.points.push({
      ...structuredClone(trajectory.points[0]),
      generation: 1,
      run_id: historicalRun.run_id,
      published_at: "2040-01-02T09:00:01Z",
      completed_at: "2040-01-02T09:00:00Z",
      metric_states_v2: [],
    });
    const getModelEnsembleSnapshot = vi.fn(async (runId: string) => (
      runId === historicalRun.run_id ? historicalRun : headRun
    ));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(async () => structuredClone(headRun)),
      getSessionModelEnsembleCanonicalHead: undefined,
      getActiveModelEnsembleWatch: vi.fn(async () => watchFixture(headRun)),
      getModelEnsembleSnapshot,
      getModelEnsembleTrajectory: vi.fn(async () => trajectory),
      getDeclaredTaskProfile: vi.fn(async () => ({
        session_id: SESSION_ID,
        profile,
        confirmation_available: true,
      })),
      saveDeclaredTaskProfile: vi.fn(),
    };
    renderPanel(transport);

    const currentStatus = await screen.findByText(
      /exactly bound to latest sealed head bbbbbbbb…bbbb/i,
    );
    expect(currentStatus).toHaveAttribute("data-profile-publication-status", "verified_current");
    fireEvent.click(screen.getByText("History"));
    fireEvent.click(await screen.findByRole("button", { name: "Open earlier snapshot 2" }));

    await waitFor(() => expect(getModelEnsembleSnapshot).toHaveBeenCalledWith(
      historicalRun.run_id,
      expect.any(AbortSignal),
    ));
    const historicalStatus = await screen.findByText(
      /selected historical seal cccccccc…cccc has no exact reviewed-profile binding/i,
    );
    expect(historicalStatus).toHaveAttribute("data-profile-publication-status", "unverified");
    expect(screen.queryByText(/exactly bound to latest sealed head/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/visible sealed r5 snapshot/i)).not.toBeInTheDocument();
  });

  it("marks an incomplete source window without presenting it as complete-session evidence", async () => {
    const incomplete = structuredClone(runFixture());
    incomplete.source_coverage_state = "incomplete_source";
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => incomplete,
    };
    renderPanel(transport);

    expect(await screen.findByText("Incomplete source window")).toBeVisible();
    expect(screen.getByText(/retained content only/i)).toBeVisible();
    expect(screen.getByText(/not a complete-session judgment/i)).toBeVisible();
  });

  it("starts exactly one local analysis command with the explicit compatibility confirmation", async () => {
    const start = vi.fn(async () => ({ run: structuredClone(runFixture()), applied: true }));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => { throw new TransportError("not found", 404); },
      startModelEnsemble: start,
    };
    renderPanel(transport);
    fireEvent.click(await screen.findByRole("button", { name: "Analyze metric ranges" }));

    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    const calls = start.mock.calls as unknown as Array<[string, object, string]>;
    expect(calls[0][0]).toBe(SESSION_ID);
    expect(calls[0][1]).toEqual({
      confirmation: "run_local_metric_cascade_on_selected_redacted_text",
    });
    expect(calls[0][2]).toMatch(/^dashboard-model-ensemble-/);
    expect(await screen.findByText(/stored local analysis completed/i)).toBeVisible();
  });

  it("starts the one-session watch with an explicit standing confirmation", async () => {
    const enable = vi.fn(async () => watchFixture());
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => { throw new TransportError("not found", 404); },
      getActiveModelEnsembleWatch: async () => { throw new TransportError("not found", 404); },
      enableModelEnsembleWatch: enable,
    };
    renderPanel(transport);
    fireEvent.click(await screen.findByRole("button", { name: "Watch this session" }));

    await waitFor(() => expect(enable).toHaveBeenCalledTimes(1));
    expect(enable).toHaveBeenCalledWith(
      SESSION_ID,
      {
        project_id: PROJECT_ID,
        max_messages: 100,
        confirmation: "continuously_analyze_selected_redacted_session",
      },
      expect.any(AbortSignal),
    );
  });

  it("applies a null latest run from watch re-enable instead of retaining a stale receipt", async () => {
    const enable = vi.fn(async () => watchFixture(null));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: async () => structuredClone(runFixture()),
      getSessionModelEnsembleCanonicalHead: undefined,
      getModelEnsembleSnapshot: undefined,
      getActiveModelEnsembleWatch: async () => { throw new TransportError("not found", 404); },
      enableModelEnsembleWatch: enable,
    };
    renderPanel(transport);
    expect(await screen.findByText(/Snapshot [a-f0-9]/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Watch this session" }));
    expect(await screen.findByText(/Start one explicit run to create typed metric receipts/i)).toBeVisible();
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
  });

  it("keeps checking distinct from a verified empty receipt store", async () => {
    const latest = deferred<ModelEnsembleRun>();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(() => latest.promise),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
    };
    renderPanel(transport);

    const panel = screen.getByRole("region", { name: /Measure the analyzed window/i });
    expect(panel).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toHaveTextContent(/Checking for stored content-free/i);
    expect(screen.queryByText(/No measured \+ predictive analysis is stored/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Start one explicit run/i)).not.toBeInTheDocument();

    latest.resolve(runFixture());
    expect(await screen.findByText(/Snapshot [a-f0-9]/i)).toBeVisible();
    expect(panel).toHaveAttribute("aria-busy", "false");
  });

  it("reports a failed legacy receipt read as unknown and offers an exact retry", async () => {
    const getLatestModelEnsemble = vi.fn()
      .mockRejectedValueOnce(new TransportError("unavailable", 503))
      .mockResolvedValueOnce(runFixture());
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble,
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
    };
    renderPanel(transport);

    expect(await screen.findByText(/availability remains unknown/i)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/availability is unknown/i);
    expect(screen.queryByText(/Start one explicit run/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Snapshot [a-f0-9]/i)).toBeVisible();
    expect(getLatestModelEnsemble).toHaveBeenCalledTimes(2);
  });

  it("serializes a watch change against analysis and keeps policy-disabled actions discoverable", async () => {
    const enabled = deferred<ModelEnsembleWatchSnapshot>();
    const startModelEnsemble = vi.fn();
    const enableModelEnsembleWatch = vi.fn(() => enabled.promise);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn().mockRejectedValue(new TransportError("not found", 404)),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
      startModelEnsemble,
      enableModelEnsembleWatch,
    };
    renderPanel(transport);
    await screen.findByText(/Start one explicit run/i);

    fireEvent.click(screen.getByRole("button", { name: "Watch this session" }));
    const analyze = screen.getByRole("button", { name: "Analyze metric ranges" });
    expect(analyze).toBeDisabled();
    fireEvent.click(analyze);
    expect(startModelEnsemble).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled();

    enabled.resolve(watchFixture(null));
    expect(await screen.findByRole("button", { name: "Stop continuous updates" })).toBeEnabled();
  });

  it("serializes an analysis request against the watch control", async () => {
    const started = deferred<{ run: ModelEnsembleRun; applied: boolean }>();
    const enableModelEnsembleWatch = vi.fn();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn().mockRejectedValue(new TransportError("not found", 404)),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
      startModelEnsemble: vi.fn(() => started.promise),
      enableModelEnsembleWatch,
    };
    renderPanel(transport);
    await screen.findByText(/Start one explicit run/i);
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));

    const watchButton = screen.getByRole("button", { name: "Watch this session" });
    expect(watchButton).toBeDisabled();
    fireEvent.click(watchButton);
    expect(enableModelEnsembleWatch).not.toHaveBeenCalled();
    started.resolve({ run: runFixture(), applied: true });
    expect(await screen.findByText(/Snapshot [a-f0-9]/i)).toBeVisible();
  });

  it("allows an active watch to be stopped after analysis access is blocked", async () => {
    const active = watchFixture(runFixture());
    active.watch.state = "idle";
    const disabled = structuredClone(active);
    disabled.watch.state = "disabled";
    const disableModelEnsembleWatch = vi.fn(async () => disabled);
    const startModelEnsemble = vi.fn();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(async () => runFixture()),
      getActiveModelEnsembleWatch: vi.fn(async () => active),
      getSessionModelEnsembleCanonicalHead: undefined,
      disableModelEnsembleWatch,
      startModelEnsemble,
    };
    renderPanel(transport, {
      analysisCapability: {
        ...CAPABILITY,
        available: false,
        reason_code: "redacted_content_consent_required",
        data_tier: null,
      },
    });

    const analyze = await screen.findByRole("button", { name: "Analyze metric ranges" });
    expect(analyze).toHaveAttribute("aria-disabled", "true");
    expect(analyze).not.toBeDisabled();
    fireEvent.click(analyze);
    expect(startModelEnsemble).not.toHaveBeenCalled();

    const stop = screen.getByRole("button", { name: "Stop continuous updates" });
    expect(stop).toBeEnabled();
    fireEvent.click(stop);
    await waitFor(() => expect(disableModelEnsembleWatch).toHaveBeenCalledWith(
      active.watch.watch_id,
      expect.any(AbortSignal),
    ));
  });

  it("aborts and ignores an earlier session mutation after the panel context changes", async () => {
    const started = deferred<{ run: ModelEnsembleRun; applied: boolean }>();
    let startSignal: AbortSignal | undefined;
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn().mockRejectedValue(new TransportError("not found", 404)),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
      startModelEnsemble: vi.fn((_sessionId, _request, _key, signal) => {
        startSignal = signal;
        return started.promise;
      }),
    };
    const view = renderPanel(transport);
    await screen.findByText(/Start one explicit run/i);
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));

    const nextSession = "9".repeat(64);
    view.rerender(
      <ModelEnsemblePanel
        analysisCapability={CAPABILITY}
        category="prompt-quality"
        projectId={PROJECT_ID}
        providerCompatibility={EXACT}
        sessionId={nextSession}
        transport={transport}
      />,
    );
    expect(startSignal?.aborted).toBe(true);
    started.resolve({ run: runFixture(), applied: true });
    await screen.findByText(/Start one explicit run/i);
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
  });

  it("does not let a slower legacy latest read overwrite a newer watch snapshot", async () => {
    const oldLatest = deferred<ModelEnsembleRun>();
    const newer = structuredClone(runFixture());
    newer.run_id = "c".repeat(64);
    const currentWatch = watchFixture(newer);
    currentWatch.watch.state = "idle";
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(() => oldLatest.promise),
      getActiveModelEnsembleWatch: vi.fn(async () => currentWatch),
      getSessionModelEnsembleCanonicalHead: undefined,
    };
    renderPanel(transport);

    const newerHeading = `Metric workspace · Snapshot ${newer.run_id.slice(0, 8)}…${newer.run_id.slice(-4)}`;
    expect(await screen.findByRole("heading", { level: 3, name: newerHeading })).toBeVisible();
    oldLatest.resolve(runFixture());
    await Promise.resolve();
    expect(screen.getByRole("heading", { level: 3, name: newerHeading })).toBeVisible();
    expect(screen.queryByRole("heading", {
      level: 3,
      name: `Metric workspace · Snapshot ${runFixture().run_id.slice(0, 8)}…${runFixture().run_id.slice(-4)}`,
    })).not.toBeInTheDocument();
  });

  it("does not let a slower legacy latest read overwrite a newer analysis command", async () => {
    const oldLatest = deferred<ModelEnsembleRun>();
    const newer = structuredClone(runFixture());
    newer.run_id = "c".repeat(64);
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(() => oldLatest.promise),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
      startModelEnsemble: vi.fn(async () => ({ run: newer, applied: true })),
    };
    renderPanel(transport);
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));
    const newerHeading = `Metric workspace · Snapshot ${newer.run_id.slice(0, 8)}…${newer.run_id.slice(-4)}`;
    expect(await screen.findByRole("heading", { level: 3, name: newerHeading })).toBeVisible();

    oldLatest.resolve(runFixture());
    await Promise.resolve();
    expect(screen.getByRole("heading", { level: 3, name: newerHeading })).toBeVisible();
    expect(screen.queryByRole("heading", {
      level: 3,
      name: `Metric workspace · Snapshot ${runFixture().run_id.slice(0, 8)}…${runFixture().run_id.slice(-4)}`,
    })).not.toBeInTheDocument();
  });

  it("does not let a slower legacy latest read clear command-owned definitions refusal", async () => {
    const oldLatest = deferred<ModelEnsembleRun>();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(() => oldLatest.promise),
      getActiveModelEnsembleWatch: undefined,
      getSessionModelEnsembleCanonicalHead: undefined,
      startModelEnsemble: vi.fn().mockRejectedValue(new MetricDefinitionsOutOfDateError("registry_version")),
    };
    renderPanel(transport);
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));
    expect(await screen.findByRole("alert", { name: "Metric definitions out of date" })).toBeVisible();

    oldLatest.resolve(runFixture());
    await Promise.resolve();
    expect(screen.getByRole("alert", { name: "Metric definitions out of date" })).toBeVisible();
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
  });

  it("does not let a slower legacy latest read clear watch-owned definitions refusal", async () => {
    const oldLatest = deferred<ModelEnsembleRun>();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(() => oldLatest.promise),
      getActiveModelEnsembleWatch: vi.fn().mockRejectedValue(
        new MetricDefinitionsOutOfDateError("contract_set_fingerprint"),
      ),
      getSessionModelEnsembleCanonicalHead: undefined,
    };
    renderPanel(transport);
    expect(await screen.findByRole("alert", { name: "Metric definitions out of date" })).toBeVisible();

    oldLatest.resolve(runFixture());
    await Promise.resolve();
    expect(screen.getByRole("alert", { name: "Metric definitions out of date" })).toBeVisible();
    expect(screen.queryByText(/Snapshot [a-f0-9]/i)).not.toBeInTheDocument();
  });

  it("uses truthful local-wait copy without claiming a durable queue cancellation", async () => {
    const enqueue = deferred<ModelEnsembleCanonicalHead>();
    const cancelModelEnsembleAnalysis = vi.fn();
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getLatestModelEnsemble: vi.fn(async () => runFixture()),
      getSessionModelEnsembleCanonicalHead: vi.fn().mockRejectedValue({ status: 404 }),
      getModelEnsembleSnapshot: vi.fn(async () => runFixture()),
      enableModelEnsembleWatch: vi.fn(async () => watchFixture(runFixture())),
      enqueueModelEnsembleAnalysis: vi.fn(() => enqueue.promise),
      cancelModelEnsembleAnalysis,
    };
    renderPanel(transport);
    await screen.findByText(/Start one explicit run/i);
    fireEvent.click(screen.getByRole("button", { name: "Analyze metric ranges" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop waiting for queue response" }));

    expect(await screen.findByRole("status")).toHaveTextContent(/Durable work may already have started/i);
    expect(cancelModelEnsembleAnalysis).not.toHaveBeenCalled();
    expect(screen.queryByText(/queue request cancelled/i)).not.toBeInTheDocument();
  });

  it("surfaces sustained canonical disconnection without inferring an empty store", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const getSessionModelEnsembleCanonicalHead = vi.fn().mockRejectedValue(new TransportError("unavailable", 503));
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getSessionModelEnsembleCanonicalHead,
      getModelEnsembleSnapshot: vi.fn(),
    };
    renderPanel(transport);

    await vi.advanceTimersByTimeAsync(10_100);
    await waitFor(() => expect(getSessionModelEnsembleCanonicalHead.mock.calls.length).toBeGreaterThanOrEqual(3));
    expect(screen.getByRole("status")).toHaveTextContent(/availability is temporarily unknown/i);
    expect(screen.queryByText(/Start one explicit run/i)).not.toBeInTheDocument();
    expect(screen.getByText(/without treating missing data as zero or absence/i)).toBeVisible();
    vi.useRealTimers();
  });

  it("labels failed and partial terminal attempts without false completed-success copy", async () => {
    const failedHead = canonicalHeadFixture(runFixture());
    failedHead.latest_attempt = {
      ...failedHead.latest_attempt!,
      state: "failed",
      completed_at: "2040-01-02T10:00:02Z",
      error_code: "local_model_ensemble_execution_failed",
    };
    const transport: PromptEnhancerTransport = {
      ...createSyntheticTransport(),
      getSessionModelEnsembleCanonicalHead: vi.fn(async () => failedHead),
      getModelEnsembleSnapshot: vi.fn(async () => runFixture()),
    };
    const view = renderPanel(transport);
    expect(await screen.findByRole("status")).toHaveTextContent(/Local analysis failed/i);
    expect(screen.getByRole("button", { name: "Retry analysis" })).toBeVisible();
    expect(screen.getByRole("status")).not.toHaveTextContent(/Stored local analysis completed/i);

    const partialHead = structuredClone(failedHead);
    partialHead.latest_attempt!.state = "partial";
    partialHead.latest_attempt!.warning_count = 2;
   view.unmount();
   renderPanel({
     ...transport,
     getSessionModelEnsembleCanonicalHead: vi.fn(async () => partialHead),
   });
   expect(await screen.findByRole("status")).toHaveTextContent(/completed with 2 warnings/i);
 });

  it("keeps an explicit command error visible across later successful polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const getActiveModelEnsembleWatch = vi.fn(async () => watchFixture(null));
      const startModelEnsemble = vi.fn().mockRejectedValue(
        new TransportError("unavailable", 503, "provider_unavailable"),
      );
      const transport: PromptEnhancerTransport = {
        ...createSyntheticTransport(),
        getLatestModelEnsemble: vi.fn().mockRejectedValue(new TransportError("not found", 404)),
        getSessionModelEnsembleCanonicalHead: undefined,
        getActiveModelEnsembleWatch,
        startModelEnsemble,
      };
      renderPanel(transport);
      fireEvent.click(await screen.findByRole("button", { name: "Analyze metric ranges" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/timed out or became unavailable/i);
      const pollsBefore = getActiveModelEnsembleWatch.mock.calls.length;
      await vi.advanceTimersByTimeAsync(70_000);
      await waitFor(() =>
        expect(getActiveModelEnsembleWatch.mock.calls.length).toBeGreaterThan(pollsBefore));
      expect(screen.getByRole("alert")).toHaveTextContent(/timed out or became unavailable/i);
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries a transient trajectory read a bounded number of times, then offers manual history retry with no loaded page", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const run = runFixture();
      const trajectory = trajectoryFixture();
      const getModelEnsembleTrajectory = vi.fn()
        .mockRejectedValue(new TransportError("unavailable", 503));
      const transport: PromptEnhancerTransport = {
        ...createSyntheticTransport(),
        getLatestModelEnsemble: vi.fn(async () => structuredClone(run)),
        getSessionModelEnsembleCanonicalHead: undefined,
        getActiveModelEnsembleWatch: vi.fn(async () => watchFixture(run)),
        getModelEnsembleTrajectory,
      };
      renderPanel(transport);

      await waitFor(() => expect(getModelEnsembleTrajectory).toHaveBeenCalledTimes(1));
      await vi.advanceTimersByTimeAsync(TRAJECTORY_RETRY_MS * (TRAJECTORY_RETRY_LIMIT + 2));
      await waitFor(() =>
        expect(getModelEnsembleTrajectory).toHaveBeenCalledTimes(TRAJECTORY_RETRY_LIMIT));
      await vi.advanceTimersByTimeAsync(TRAJECTORY_RETRY_MS * 2);
      expect(getModelEnsembleTrajectory).toHaveBeenCalledTimes(TRAJECTORY_RETRY_LIMIT);

      fireEvent.click(screen.getByText("History"));
      expect(screen.getByText(/no previously loaded trajectory is available/i)).toBeVisible();
      getModelEnsembleTrajectory.mockResolvedValue(structuredClone(trajectory));
      fireEvent.click(screen.getByRole("button", { name: "Retry history" }));

      await waitFor(() =>
        expect(getModelEnsembleTrajectory).toHaveBeenCalledTimes(TRAJECTORY_RETRY_LIMIT + 1));
      expect(await screen.findByRole("button", { name: "Open live snapshot" })).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });
});
