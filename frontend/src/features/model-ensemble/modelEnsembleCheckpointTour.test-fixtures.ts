import type {
  AgentMetricEvidencePreview,
  MetricLifecycleProposal,
  ModelEnsembleAttemptStage,
  ModelEnsembleCanonicalHead,
  ModelEnsembleRun,
  ModelEnsembleTrajectoryPage,
  PromptEnhancerTransport,
  ProviderCompatibilityStatus,
} from "../../shared/api/contracts";
import { createSyntheticTransport } from "../../shared/api/syntheticTransport";
import { syntheticMetricPublicationV2 } from "../../test/metricPublicationV2Fixture";
import { vi } from "vitest";

export const CHECKPOINT_PROJECT_ID = "1".repeat(64);
export const CHECKPOINT_SESSION_A = "2".repeat(64);
export const CHECKPOINT_SESSION_B = "3".repeat(64);
export const CHECKPOINT_RUN_A = "a".repeat(64);
export const CHECKPOINT_RUN_B = "b".repeat(64);

export const CHECKPOINT_CAPABILITY = {
  available: true,
  reason_code: "available",
  data_tier: "redacted_content",
  content_persistence: false,
  network_inference: false,
  raw_transcripts: false,
} as const;

export const CHECKPOINT_COMPATIBILITY: ProviderCompatibilityStatus = {
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

function checkpointPublication() {
  const publication = syntheticMetricPublicationV2({
    "prompt.task_definition_coverage": {
      value_state: "known",
      numerator: 1,
      denominator: 4,
      eligible: 4,
      state_class: "known_improve",
      factor_evidence: "per_factor_measured",
      source_complete: true,
    },
    "prompt.context_sufficiency": {
      value_state: "pending",
      eligible: 3,
      pending: 1,
      censoring_lower_bound: 0.25,
      censoring_upper_bound: 0.75,
      source_complete: true,
    },
    "prompt.acceptance_testability": {
      value_state: "unknown",
      eligible: 1,
      unknown: 1,
      source_complete: false,
    },
  });
  publication.projection_version = "metric-contract-v2-projection-4";
  for (const metric of publication.metrics) {
    metric.state.projection_version = "metric-contract-v2-projection-4";
  }
  return publication;
}

export function checkpointStages(
  suffix: "a" | "b",
): ModelEnsembleAttemptStage[] {
  return [
    {
      stage_ordinal: 0,
      stage_key: `example_factor_${suffix}`,
      state: "completed",
      model_key: `example_factor_${suffix}`,
      repository_id: `example-org/factor-${suffix}`,
      revision: suffix.repeat(40),
      error_code: null,
      device: "cpu",
      quantization: "none",
      inference_latency_ms: suffix === "a" ? 12 : 14,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 256,
      evaluated_case_count: 4,
      contributed_case_count: 3,
      unloaded_after_stage: null,
      completed_at: "2040-01-02T10:00:02Z",
    },
    {
      stage_ordinal: 1,
      stage_key: `example_judge_${suffix}`,
      state: "completed",
      model_key: `example_judge_${suffix}`,
      repository_id: `example-org/judge-${suffix}`,
      revision: suffix === "a" ? "c".repeat(40) : "d".repeat(40),
      error_code: null,
      device: "cpu",
      quantization: "none",
      inference_latency_ms: suffix === "a" ? 20 : 22,
      peak_accelerator_memory_mb: 0,
      process_rss_mb: 384,
      evaluated_case_count: 4,
      contributed_case_count: 4,
      unloaded_after_stage: false,
      completed_at: "2040-01-02T10:00:03Z",
    },
  ];
}

export function checkpointRun(
  runId: string,
  suffix: "a" | "b",
): ModelEnsembleRun {
  const stages = checkpointStages(suffix);
  return {
    run_id: runId,
    plan_version: "local-shadow-ensemble-v1",
    plan_fingerprint: suffix === "a" ? "4".repeat(64) : "5".repeat(64),
    source_coverage_state: "complete_window",
    chunk_count: 0,
    model_count: 10,
    chunks: [],
    experts: [],
    votes: [],
    chunk_metrics: [],
    metrics: [],
    metric_projection_version: "coaching-typed-projection-v1",
    metric_projection_completed_at: "2040-01-02T10:00:01Z",
    metric_publication_v2: checkpointPublication(),
    metric_profile_binding: null,
    requirement_plan_evidence_binding: null,
    requirement_action_evidence_binding: null,
    requirement_verification_evidence_binding: null,
    metric_evidence_readiness_v2: null,
    typed_metrics: [],
    predictive_projection_version: "local-probabilistic-radar-v1",
    predictive_projected_at: "2040-01-02T10:00:01Z",
    predictive_metrics: [],
    predictive_model_stages: stages.map((stage) => ({
      model_key: stage.model_key!,
      repository_id: stage.repository_id!,
      revision: stage.revision!,
      status: "completed" as const,
      error_code: null,
      device: "cpu" as const,
      quantization: "none",
      inference_latency_ms: stage.inference_latency_ms,
      peak_accelerator_memory_mb: stage.peak_accelerator_memory_mb,
      process_rss_mb: stage.process_rss_mb,
      unloaded_after_stage: true,
    })),
    completed_at: "2040-01-02T10:00:04Z",
    local_only: true,
    content_persisted: false,
    calibration_state: "not_assessed",
    product_metric_eligible: false,
  };
}

export function checkpointHead(
  run: ModelEnsembleRun,
  sessionId: string,
  suffix: "a" | "b",
): ModelEnsembleCanonicalHead {
  const stages = checkpointStages(suffix);
  const watchId = suffix === "a" ? "6".repeat(64) : "7".repeat(64);
  return {
    schema_version: "analysis-snapshot-v2",
    watch: {
      watch_id: watchId,
      provider: "codex",
      project_id: CHECKPOINT_PROJECT_ID,
      session_id: sessionId,
      max_messages: 100,
      state: "idle",
      generation: 2,
      progress_completed: 10,
      progress_total: 10,
      has_result: true,
      last_error_code: null,
      next_check_at: "2040-01-02T10:05:00Z",
      updated_at: "2040-01-02T10:00:04Z",
      serial_model_execution: true,
      process_isolated_model_release: true,
      cuda_resource_retry_on_cpu: true,
      content_persisted: false,
      calibrated_as_truth: false,
    },
    head_run_id: run.run_id,
    head_generation: 2,
    latest_attempt: {
      attempt_id: suffix === "a" ? "8".repeat(64) : "9".repeat(64),
      watch_id: watchId,
      generation: 2,
      state: "completed",
      prior_head_run_id: run.run_id,
      published_run_id: run.run_id,
      progress_completed: 2,
      progress_total: 2,
      stage_count: stages.length,
      warning_count: 0,
      error_code: null,
      requested_at: "2040-01-02T10:00:00Z",
      started_at: "2040-01-02T10:00:01Z",
      completed_at: "2040-01-02T10:00:04Z",
      content_persisted: false,
    },
    stages,
    content_persisted: false,
  };
}

export function checkpointTrajectory(
  run: ModelEnsembleRun,
  watchId: string,
  earlierRunId: string,
): ModelEnsembleTrajectoryPage {
  const point = (
    runId: string,
    generation: number,
    current: boolean,
  ): ModelEnsembleTrajectoryPage["points"][number] => ({
    generation,
    run_id: runId,
    published_at: current ? "2040-01-02T10:00:05Z" : "2040-01-01T10:00:05Z",
    completed_at: current ? run.completed_at : "2040-01-01T10:00:04Z",
    max_messages: 100,
    source_coverage_state: "complete_window",
    chunk_count: 0,
    comparable_to_head: true,
    metrics: [],
    metric_projection_version: "coaching-typed-projection-v1",
    metric_projection_completed_at: current
      ? "2040-01-02T10:00:01Z"
      : "2040-01-01T10:00:01Z",
    typed_metrics: [],
    metric_states_v2: current
      ? run.metric_publication_v2!.metrics.map((metric) => structuredClone(metric.state))
      : [],
    predictive_projection_version: "local-probabilistic-radar-v1",
    predictive_metrics: [],
  });
  return {
    watch_id: watchId,
    head_run_id: run.run_id,
    head_generation: 2,
    points: [point(run.run_id, 2, true), point(earlierRunId, 1, false)],
    next_before_generation: null,
    content_persisted: false,
    calibrated_as_truth: false,
  };
}

export function checkpointProposal(
  sessionId: string,
  runId: string,
  proposalId: string,
): MetricLifecycleProposal {
  return {
    proposal_id: proposalId,
    session_id: sessionId,
    source_run_id: runId,
    proposal_revision: 1,
    proposal_kind: "opportunity",
    family: "collaboration.ambiguity_resolution",
    opportunity_kind: "ambiguity",
    opportunity_id: proposalId.slice(0, 32).padEnd(64, "0"),
    link_kind: null,
    outcome_kind: null,
    enumerated_opportunity_ids: [],
    status: "proposed",
    decision_id: null,
    decision: null,
    created_at: "2041-01-01T00:00:00+00:00",
    decided_at: null,
    schema_version: "metric-lifecycle-evidence-v1",
    policy_version: "explicit-local-confirmation-v1",
    local_only: true,
    content_persisted: false,
  };
}

export function checkpointPreview(
  sessionId: string,
  runId: string,
  suffix: "a" | "b",
): AgentMetricEvidencePreview {
  return {
    schema_version: "agent-metric-evidence-file-v2",
    payload_sha256: suffix === "a" ? "d".repeat(64) : "e".repeat(64),
    session_id: sessionId,
    expected_source_run_id: runId,
    source_window_fingerprint: suffix === "a" ? "f".repeat(64) : "0".repeat(64),
    metric_key: "collaboration.ambiguity_resolution",
    proposal_kind: "opportunity",
    expires_at: "2042-01-01T01:00:00+00:00",
    producer: {
      kind: "local_coding_agent",
      producer_id: `example-agent-${suffix}`,
      producer_version: "example-agent-v1",
      model_id: `example-model-${suffix}`,
      authority: "untrusted_provenance_claim",
    },
    creates_unconfirmed_proposal_only: true,
    requires_authenticated_local_user_confirmation: true,
    can_set_numeric_metric: false,
    objective_receipt_claims_accepted: false,
    raw_payload_persisted: false,
  };
}

export interface CheckpointTransportLane {
  transport: PromptEnhancerTransport;
  getHead: ReturnType<typeof vi.fn>;
  getSnapshot: ReturnType<typeof vi.fn>;
  getTrajectory: ReturnType<typeof vi.fn>;
  listProposals: ReturnType<typeof vi.fn>;
  previewEvidence: ReturnType<typeof vi.fn>;
  importEvidence: ReturnType<typeof vi.fn>;
  decideProposal: ReturnType<typeof vi.fn>;
}

export function checkpointTransport({
  run,
  head,
  trajectory,
  sessionId,
  suffix,
  confirmationAvailable = true,
  proposalCount = 1,
}: {
  run: ModelEnsembleRun;
  head: ModelEnsembleCanonicalHead;
  trajectory: ModelEnsembleTrajectoryPage;
  sessionId: string;
  suffix: "a" | "b";
  confirmationAvailable?: boolean;
  proposalCount?: number;
}): CheckpointTransportLane {
  const proposalSeed = suffix === "a" ? "1" : "2";
  const proposals = Array.from({ length: proposalCount }, (_, index) => (
    checkpointProposal(sessionId, run.run_id, `${proposalSeed}${index}`.padEnd(64, proposalSeed))
  ));
  const importedProposal = checkpointProposal(
    sessionId,
    run.run_id,
    (suffix === "a" ? "3" : "4").repeat(64),
  );
  const preview = checkpointPreview(sessionId, run.run_id, suffix);
  const getHead = vi.fn(async () => structuredClone(head));
  const getSnapshot = vi.fn(async () => structuredClone(run));
  const getTrajectory = vi.fn(async () => structuredClone(trajectory));
  const listProposals = vi.fn(async () => ({
    session_id: sessionId,
    proposals: structuredClone(proposals),
    total: proposals.length,
    complete: true,
  }));
  const previewEvidence = vi.fn(async () => structuredClone(preview));
  const importEvidence = vi.fn(async () => ({
    payload_sha256: preview.payload_sha256,
    proposal: structuredClone(importedProposal),
    applied: true,
    producer_claim_persisted: false,
    raw_payload_persisted: false,
    requires_authenticated_local_user_confirmation: true,
  }));
  const decideProposal = vi.fn(async (
    _sessionId: string,
    proposalId: string,
    request: { decision: "confirm" | "reject" },
  ) => {
    const proposal = [...proposals, importedProposal].find((item) => item.proposal_id === proposalId)
      ?? importedProposal;
    return {
      proposal: {
        ...structuredClone(proposal),
        status: request.decision === "confirm" ? "confirmed" as const : "rejected" as const,
        decision_id: (suffix === "a" ? "5" : "6").repeat(64),
        decision: request.decision,
        decided_at: "2041-01-01T00:01:00+00:00",
      },
      applied: true,
    };
  });
  const transport: PromptEnhancerTransport = {
    ...createSyntheticTransport(),
    getUserPresenceCapability: vi.fn(async () => ({
      contract_version: "native-user-presence-capability-v1" as const,
      confirmation_available: confirmationAvailable,
      mode: confirmationAvailable ? "native_bridge_bound_token" as const : "unavailable" as const,
    })),
    getSessionModelEnsembleCanonicalHead: getHead,
    getModelEnsembleSnapshot: getSnapshot,
    getModelEnsembleTrajectory: getTrajectory,
    listMetricLifecycleProposals: listProposals,
    previewAgentMetricEvidence: previewEvidence,
    importAgentMetricEvidence: importEvidence,
    decideMetricLifecycleProposal: decideProposal,
  };
  return {
    transport,
    getHead,
    getSnapshot,
    getTrajectory,
    listProposals,
    previewEvidence,
    importEvidence,
    decideProposal,
  };
}

export function checkpointFile(suffix: "a" | "b"): File {
  const content = `{"fixture":"checkpoint-${suffix}"}`;
  const file = new File([content], `example-checkpoint-${suffix}.json`, {
    type: "application/json",
  });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(content).buffer,
  });
  return file;
}
