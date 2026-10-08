import type {
  AnalysisRun,
  ApplicationUpdateStatus,
  CandidateListItem,
  CandidateStatusFilter,
  ContentFreeListPage,
  ModelCompatibilityCatalog,
  ModelEvaluationJob,
  ModelRuntimeInventory,
  ProjectSessionQualityAggregate,
  ReviewCommand,
  SessionQualityAggregate,
  TaskDecision,
  TaskLifecycleMutationResponse,
  TaskLifecycleSnapshot,
  TaskLifecycleState,
  TaskAnalysisResponse,
  TaskRevision,
  TaskReviewResponse,
} from "./contracts";
import type { SyntheticRuntimeTransport } from "../platform/runtimeMode";
import {
  SYNTHETIC_CANDIDATES,
  SYNTHETIC_COACHING_METRIC_SPECS,
  SYNTHETIC_COACHING_PROJECTION,
  SYNTHETIC_CODEX_SESSIONS,
  SYNTHETIC_CURRENT_SESSION_QUALITY_RUN,
  SYNTHETIC_RESULTS,
  SYNTHETIC_RUN,
  SYNTHETIC_QUALITY_PROJECT_ID,
  SYNTHETIC_TASKS,
  SYNTHETIC_TASK_LIFECYCLES,
  SYNTHETIC_QUALITY_SESSION_ID,
  SYNTHETIC_PROVIDER_COMPATIBILITY,
  SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
  SYNTHETIC_SESSION_METRIC_READINESS,
  SYNTHETIC_TASK_DECISIONS,
  SYNTHETIC_MODEL_LINK_EXPERIMENT,
  SYNTHETIC_MODEL_LINK_OUTCOME,
  SYNTHETIC_METRIC_COVERAGE,
} from "./syntheticFixtures";
import { TransportError } from "./httpTransport";
import {
  deriveModelCompatibilityDisposition,
  FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS,
} from "./modelCompatibilityContract";
import { SYNTHETIC_TEXT_ANALYSIS_RESEARCH } from "./syntheticResearchFixture";
import { SYNTHETIC_MODEL_LAB_INVENTORY } from "./syntheticModelLabFixture";
import { createSyntheticMetricOperabilityCatalog } from "./metricOperabilityContract";

function copy<T>(value: T): T {
  return structuredClone(value);
}

function syntheticPage<T>(
  values: readonly T[],
  page: ContentFreeListPage | undefined,
): { values: T[]; limit: number; offset: number } {
  const limit = page?.limit ?? 100;
  const offset = page?.offset ?? 0;
  return {
    values: copy(values.slice(offset, offset + limit)),
    limit,
    offset,
  };
}

function safeId(sequence: number): string {
  return sequence.toString(16).padStart(64, "0");
}

function syntheticApplicationUpdateStatus(): ApplicationUpdateStatus {
  return {
    contract_version: "application-update-status.v3",
    instance_id: "0".repeat(32),
    revision: 0,
    contains_private_data: false,
    installed_version: "0.1.0",
    channel: "stable",
    state: "unconfigured",
    available_version: null,
    artifact_size_bytes: null,
    downloaded_bytes: null,
    last_checked_at: null,
    reason_code: "release_feed_unconfigured",
    verification_code: null,
    can_check: false,
    can_stage: false,
    can_cancel: false,
    can_retry: false,
    can_apply: false,
    can_verify: false,
    package_review: { state: "not_configured", reason_code: null, checked_at: null },
  };
}

function lifecyclePage(
  snapshot: TaskLifecycleSnapshot,
  eventLimit = 100,
  eventOffset = 0,
): TaskLifecycleSnapshot {
  const events = snapshot.events.slice(eventOffset, eventOffset + eventLimit);
  return copy({
    ...snapshot,
    events,
    events_limit: eventLimit,
    events_offset: eventOffset,
    events_complete: eventOffset + events.length >= snapshot.event_count,
  });
}

const SYNTHETIC_MODEL_RUNTIME_INVENTORY: ModelRuntimeInventory = {
  preferred_device: "cuda",
  cuda_state: "available",
  cuda_available: true,
  mps_available: false,
  cpu_available: true,
  cpu_architecture_bucket: "x86_64",
  logical_core_bucket: "9_to_16",
  system_ram_bucket: "16_gib_class",
  cuda_vram_bucket: "16_gib_class",
  cuda_capability_bucket: "8_x",
  model_cache_free_disk_bucket: "10240_to_51199_mib",
  discovery_reason_codes: [],
  inventory_version: "bucketed-sensitive-hardware-inventory-v3",
  one_model_at_a_time: true,
  subprocess_isolation: true,
  raw_session_data_accepted: false,
  model_child_gpu_allocation_ceiling_mib: 6_144,
  model_child_rss_ceiling_mib: 8_192,
  model_downloads_started: false,
  model_activation_allowed: false,
  sensitivity: "sensitive_derived",
  local_only: true,
  persisted: false,
  synced: false,
};

const SYNTHETIC_MODEL_COMPATIBILITY: ModelCompatibilityCatalog = {
  catalog_version: "reviewed-model-resource-fit-v3",
  measurement_version: "reviewed-runtime-configurations-2026-08-v3",
  catalog_policy: "exploratory_resource_fit_only",
  content_free: true,
  session_data_read: false,
  cache_contents_read: false,
  downloads_started: false,
  activation_allowed: false,
  local_only: true,
  persisted: false,
  synced: false,
  inventory: SYNTHETIC_MODEL_RUNTIME_INVENTORY,
  models: FROZEN_MODEL_COMPATIBILITY_CONFIGURATIONS.map((configuration) => ({
    ...configuration,
    ...deriveModelCompatibilityDisposition(
      SYNTHETIC_MODEL_RUNTIME_INVENTORY,
      configuration,
    ),
  })),
};

function syntheticCoachingProjectAggregate(
  selectedSessionCount: number,
): ProjectSessionQualityAggregate {
  const missingRunCount = Math.max(0, selectedSessionCount - 1);
  return {
    analysis_profile_key: "coaching_profile",
    analysis_profile_version: 1,
    metric_pack_key: "experimental.redacted-text.coaching",
    metric_pack_version: 3,
    metric_schema_version: 2,
    selected_session_count: selectedSessionCount,
    completed_run_count: 1,
    missing_run_count: missingRunCount,
    integrity_state: "valid",
    unexpected_result_record_count: 0,
    duplicate_result_record_count: 0,
    metrics: SYNTHETIC_COACHING_METRIC_SPECS.map(
      (definition, index) => {
        const metricKey = definition.key;
        const metricVersion = definition.version;
        const metricUnit = definition.unit;
        const metricDirection = definition.direction;
        const abstained = false;
        const stateCounts = {
          known: abstained ? 0 : 1,
          unknown: 0,
          not_applicable: 0,
          abstained: abstained ? 1 : 0,
          execution_error: 0,
        };
        const numerator = abstained ? null : 2 + (index % 3);
        const denominator = abstained ? null : 4;
        const numericValue =
          numerator === null || denominator === null
            ? null
            : numerator / denominator;
        const cohort = {
          compatibility_fingerprint: safeId(800 + index),
          result_count: 1,
          state_counts: stateCounts,
          fraction_numerator: numerator,
          fraction_denominator: denominator,
          numeric_value: numericValue,
          analyzable_observed_count: 4,
          analyzable_eligible_count: 4,
          analyzable_coverage: 1,
        };
        return {
          metric_key: metricKey,
          metric_version: metricVersion,
          metric_unit: metricUnit,
          metric_direction: metricDirection,
          aggregation_method: "ratio_of_sums" as const,
          compatibility_state: "compatible" as const,
          aggregate_state: abstained ? ("abstained" as const) : ("known" as const),
          blocked_reason_codes: [],
          selected_session_count: selectedSessionCount,
          completed_run_count: 1,
          missing_run_count: missingRunCount,
          not_selected_run_count: 0,
          unknown_scope_run_count: 0,
          present_result_count: 1,
          missing_result_count: 0,
          invalid_result_session_count: 0,
          invalid_result_record_count: 0,
          state_counts: stateCounts,
          compatibility_cohorts: [cohort],
          fraction_numerator: numerator,
          fraction_denominator: denominator,
          numeric_value: numericValue,
          analyzable_observed_count: 4,
          analyzable_eligible_count: 4,
          analyzable_coverage: 1,
        };
      },
    ),
  };
}

function syntheticQualityAggregate(
  sessionIds: readonly string[],
): SessionQualityAggregate {
  const selected = new Set(sessionIds);
  if (
    sessionIds.length < 1 ||
    sessionIds.length > 100 ||
    selected.size !== sessionIds.length ||
    sessionIds.some((value) => !/^[a-f0-9]{64}$/.test(value))
  ) {
    throw new TransportError("Synthetic quality selection is invalid", 422);
  }
  const hasRun = selected.has(SYNTHETIC_QUALITY_SESSION_ID);
  const completed = hasRun ? 1 : 0;
  const missing = sessionIds.length - completed;
  const run = SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run;
  const stateCounts = (state: string) => ({
    known: state === "known" ? 1 : 0,
    unknown: state === "unknown" ? 1 : 0,
    not_applicable: state === "not_applicable" ? 1 : 0,
    abstained: state === "abstained" ? 1 : 0,
    execution_error: state === "execution_error" ? 1 : 0,
  });
  return {
    analysis_profile_key: run.analysis_profile_key,
    analysis_profile_version: run.analysis_profile_version,
    metric_pack_key: run.metric_pack_key,
    metric_pack_version: run.metric_pack_version,
    metric_schema_version: 2,
    selected_session_count: sessionIds.length,
    completed_run_count: completed,
    missing_run_count: missing,
    integrity_state: "valid",
    unexpected_result_record_count: 0,
    duplicate_result_record_count: 0,
    metrics: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.results.map((result) => {
      if (!hasRun) {
        return {
          metric_key: result.key,
          metric_version: result.version,
          metric_unit: result.unit!,
          metric_direction: result.direction,
          aggregation_method: result.aggregation_method,
          compatibility_state: "no_results",
          aggregate_state: "unknown",
          blocked_reason_codes: [],
          selected_session_count: sessionIds.length,
          completed_run_count: 0,
          missing_run_count: sessionIds.length,
          not_selected_run_count: 0,
          unknown_scope_run_count: 0,
          present_result_count: 0,
          missing_result_count: 0,
          invalid_result_session_count: 0,
          invalid_result_record_count: 0,
          state_counts: stateCounts("missing"),
          compatibility_cohorts: [],
          fraction_numerator: null,
          fraction_denominator: null,
          numeric_value: null,
          analyzable_observed_count: null,
          analyzable_eligible_count: null,
          analyzable_coverage: null,
        };
      }
      const counts = stateCounts(result.value_state);
      const cohort = {
        key: {
          metric_pack_key: run.metric_pack_key,
          metric_pack_version: run.metric_pack_version,
          metric_scope_state: run.metric_scope_state,
          analysis_profile_key: run.analysis_profile_key,
          analysis_profile_version: run.analysis_profile_version,
          data_tier: run.data_tier,
          consent_policy_version: run.consent_policy_version,
          provider: run.provider,
          provider_version: run.provider_version,
          adapter_version: run.adapter_version,
          source_schema_version: run.source_schema_version,
          content_schema_version: run.content_schema_version,
          metric_engine_version: run.metric_engine_version,
          redactor_version: run.redactor_version,
          local_only: run.local_only,
          metric_key: result.key,
          metric_version: result.version,
          metric_unit: result.unit!,
          metric_source: result.source,
          metric_direction: result.direction,
          aggregation_method: result.aggregation_method,
          metric_schema_version: result.metric_schema_version,
          algorithm_id: result.algorithm_id,
          algorithm_version: result.algorithm_version,
          model_id: result.model_id,
          model_revision: result.model_revision,
          model_license: result.model_license,
          tokenizer_id: result.tokenizer_id,
          prompt_version: result.prompt_version,
          rubric_version: result.rubric_version,
        },
        result_count: 1,
        state_counts: counts,
        fraction_numerator: result.fraction?.numerator ?? null,
        fraction_denominator: result.fraction?.denominator ?? null,
        numeric_value: result.numeric_value,
        analyzable_observed_count: result.observed_count,
        analyzable_eligible_count: result.eligible_count,
        analyzable_coverage: result.coverage,
      };
      return {
        metric_key: result.key,
        metric_version: result.version,
        metric_unit: result.unit!,
        metric_direction: result.direction,
        aggregation_method: result.aggregation_method,
        compatibility_state: "compatible",
        aggregate_state: result.value_state,
        blocked_reason_codes: [],
        selected_session_count: sessionIds.length,
        completed_run_count: 1,
        missing_run_count: missing,
        not_selected_run_count: 0,
        unknown_scope_run_count: 0,
        present_result_count: 1,
        missing_result_count: 0,
        invalid_result_session_count: 0,
        invalid_result_record_count: 0,
        state_counts: counts,
        compatibility_cohorts: [cohort],
        fraction_numerator: result.fraction?.numerator ?? null,
        fraction_denominator: result.fraction?.denominator ?? null,
        numeric_value: result.numeric_value,
        analyzable_observed_count: result.observed_count,
        analyzable_eligible_count: result.eligible_count,
        analyzable_coverage: result.coverage,
      };
    }),
  };
}

function candidateIds(command: ReviewCommand): string[] {
  if (command.action === "merge") return command.request.candidate_ids;
  return [command.request.candidate_id];
}

export function createSyntheticTransport(): SyntheticRuntimeTransport {
  let candidates = copy(SYNTHETIC_CANDIDATES);
  const tasks = copy(SYNTHETIC_TASKS);
  const lifecycles = copy(SYNTHETIC_TASK_LIFECYCLES);
  const decisions = new Map<string, TaskReviewResponse>();
  const auditDecisions = new Map<string, TaskDecision[]>(
    Object.entries(SYNTHETIC_TASK_DECISIONS).map(([candidateId, values]) => [
      candidateId,
      copy(values) as TaskDecision[],
    ]),
  );
  const analyses = new Map<string, TaskAnalysisResponse>();
  const lifecycleCommands = new Map<string, {
    fingerprint: string;
    response: TaskLifecycleMutationResponse;
  }>();
  const runs: AnalysisRun[] = [copy(SYNTHETIC_RUN)];
  const resultsByRun = new Map([
    [SYNTHETIC_RUN.run_id, copy(SYNTHETIC_RESULTS)],
  ]);
  let sequence = 32;
  let modelLinkExperiment = copy(SYNTHETIC_MODEL_LINK_EXPERIMENT);
  let modelEvaluationJob: ModelEvaluationJob = {
    job_id: "a".repeat(32),
    status: "completed" as const,
    candidate: {
      candidate: "all" as const,
      device: "auto" as const,
      mode: "full" as const,
      allow_download: false,
    },
    created_at: "2040-01-03T09:00:00Z",
    started_at: "2040-01-03T09:00:01Z",
    completed_at: "2040-01-03T09:00:08Z",
    resolved_device: "cuda" as const,
    error_code: null,
    outcomes: [
      {
        key: "qwen3_embedding_06b" as const,
        status: "evaluated" as const,
        error_code: null,
        primary_metric: "top1_accuracy",
        primary_value: 0.75,
        secondary_metric: "mean_reciprocal_rank",
        secondary_value: 0.861111,
        critical_metric: null,
        critical_value: null,
        inference_latency_ms: 613.202,
        peak_accelerator_memory_mb: 1197.371,
      },
      {
        key: "bge_m3" as const,
        status: "evaluated" as const,
        error_code: null,
        primary_metric: "top1_accuracy",
        primary_value: 0.666667,
        secondary_metric: "mean_reciprocal_rank",
        secondary_value: 0.819444,
        critical_metric: null,
        critical_value: null,
        inference_latency_ms: 432.376,
        peak_accelerator_memory_mb: 2179.602,
      },
    ],
  };

  const findCandidates = (command: ReviewCommand): CandidateListItem[] => {
    const found = candidateIds(command).map((id) =>
      candidates.find((item) => item.candidate.candidate_id === id),
    );
    if (found.some((item) => item === undefined)) {
      throw new TransportError("Synthetic candidate was not found", 404);
    }
    return found as CandidateListItem[];
  };

  const assertVersions = (command: ReviewCommand, items: CandidateListItem[]) => {
    if (
      items.some(
        (item) =>
          item.candidate.discovery_version !== command.request.expected_discovery_version,
      )
    ) {
      throw new TransportError("Synthetic candidate version is stale", 409);
    }
  };

  return {
    runtimeKind: "synthetic_fixture",
    async getApplicationUpdateStatus() {
      return copy(syntheticApplicationUpdateStatus());
    },
    async checkApplicationUpdate() {
      return copy(syntheticApplicationUpdateStatus());
    },
    async verifyApplicationUpdate() {
      return copy(syntheticApplicationUpdateStatus());
    },
    async getUserPresenceCapability() {
      return {
        contract_version: "native-user-presence-capability-v1",
        confirmation_available: false,
        mode: "unavailable",
      };
    },
    async getControlPlaneReadiness() {
      throw new TransportError(
        "The loopback control-plane readiness route is unavailable in synthetic preview",
        404,
      );
    },
    async getTextAnalysisResearch() {
      return copy(SYNTHETIC_TEXT_ANALYSIS_RESEARCH);
    },
    async getMetricOperabilityCatalog() {
      return copy(createSyntheticMetricOperabilityCatalog());
    },
    async getTextModelRuntime() {
      return copy(SYNTHETIC_MODEL_RUNTIME_INVENTORY);
    },
    async getTextModelCompatibility() {
      return copy(SYNTHETIC_MODEL_COMPATIBILITY);
    },
    async getModelLabInventory() {
      return copy(SYNTHETIC_MODEL_LAB_INVENTORY);
    },
    async startTextModelEvaluation(request) {
      modelEvaluationJob = {
        ...modelEvaluationJob,
        candidate: {
          candidate: request.candidate ?? "all",
          device: request.device ?? "auto",
          mode: request.mode ?? "smoke",
          allow_download: request.allow_download ?? false,
        },
      };
      return copy(modelEvaluationJob);
    },
    async getTextModelEvaluation(jobId) {
      if (jobId !== modelEvaluationJob.job_id) {
        throw new TransportError("Synthetic model evaluation was not found", 404);
      }
      return copy(modelEvaluationJob);
    },
    async getSessionTextAnalysisCapability() {
      return {
        available: true,
        reason_code: "available",
        data_tier: "redacted_content",
        content_persistence: false,
        network_inference: false,
        raw_transcripts: false,
      } as const;
    },
    async getProviderCompatibility() {
      return copy(SYNTHETIC_PROVIDER_COMPATIBILITY);
    },
    async getProviderMetricCapabilities(provider) {
      if (provider !== "synthetic") {
        throw new TransportError("Synthetic provider capabilities were not found", 404);
      }
      return copy(SYNTHETIC_PROVIDER_METRIC_CAPABILITIES);
    },
    async getMetricCoverage(provider) {
      if (provider !== "synthetic") {
        throw new TransportError("Synthetic metric coverage was not found", 404);
      }
      const report = copy(SYNTHETIC_METRIC_COVERAGE);
      return report;
    },
    async getProjectMetricCoverage(projectId, provider) {
      if (projectId !== SYNTHETIC_QUALITY_PROJECT_ID || provider !== "synthetic") {
        throw new TransportError("Synthetic project coverage was not found", 404);
      }
      const report = copy(SYNTHETIC_METRIC_COVERAGE);
      report.scope = "one_project";
      return report;
    },
    async getSessionMetricReadiness(
      sessionId,
      presetId = "coaching_profile_v1",
    ) {
      if (
        sessionId !== SYNTHETIC_QUALITY_SESSION_ID ||
        presetId !== "coaching_profile_v1"
      ) {
        throw new TransportError("Synthetic metric readiness was not found", 404);
      }
      return copy(SYNTHETIC_SESSION_METRIC_READINESS);
    },
    async checkProviderCompatibility() {
      return copy(SYNTHETIC_PROVIDER_COMPATIBILITY);
    },
    async getCodexLocalSourceStatus() {
      return {
        consent_active: true,
        indexed_sessions: SYNTHETIC_CODEX_SESSIONS.length,
        indexed_projects: 1,
        verification_capability: {
          state: "validation_only" as const,
          live_classification_enabled: false,
          supported_kinds: ["test" as const, "build" as const, "type_check" as const],
          reason_code: "synthetic_validation_only",
          candidate_schema_version: "synthetic-verification-1",
          classifier_version: "synthetic-classifier-1",
          normalizer_version: "synthetic-normalizer-1",
        },
      };
    },
    async getOnboardingStatus() {
      throw new TransportError("Onboarding is unavailable in synthetic preview", 404);
    },
    async acceptOnboarding() {
      throw new TransportError("Onboarding is unavailable in synthetic preview", 404);
    },
    async judgeSessionWithModel() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async startModelJudgeSweep() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async getModelJudgeSweep() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async checkPrompt() {
      throw new TransportError("Prompt checks are unavailable in synthetic preview", 404);
    },
    async getPromptCheckHistory() {
      throw new TransportError("Prompt checks are unavailable in synthetic preview", 404);
    },
    async getPromptCheck() {
      throw new TransportError("Prompt checks are unavailable in synthetic preview", 404);
    },
    async getAgentOrchestration() { throw new TransportError("Agent controller API is unavailable in synthetic preview", 404); },
    async getAgentHardening() { throw new TransportError("Agent health diagnostics are unavailable in synthetic preview", 404); },
    async beginAgentNativeAcceptance() { throw new TransportError("Native Agent acceptance is unavailable in synthetic preview", 404); },
    async listAgentProjects() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async createAgentProject() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentProject() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async updateAgentProject() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async deleteAgentProject() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async listAgentCatalogSessions() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async searchAgentSavedMessages() { throw new TransportError("Saved-message search is unavailable in synthetic preview", 404); },
    async getAgentCatalogSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async updateAgentCatalogSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async deleteAgentCatalogSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentPersistedEvents() { throw new TransportError("Retained agent history is unavailable in synthetic preview", 404); },
    async forkAgentSession() { throw new TransportError("Agent session branching is unavailable in synthetic preview", 404); },
    async resumeAgentSession() { throw new TransportError("Retained agent history is unavailable in synthetic preview", 404); },
    async exportAgentHistory() { throw new TransportError("Retained agent history is unavailable in synthetic preview", 404); },
    async listAgentArtifacts() { throw new TransportError("Agent artifacts are unavailable in synthetic preview", 404); },
    async previewAgentArtifactCapture() { throw new TransportError("Agent artifacts are unavailable in synthetic preview", 404); },
    async getAgentArtifact() { throw new TransportError("Agent artifacts are unavailable in synthetic preview", 404); },
    async exportAgentArtifact() { throw new TransportError("Agent artifact export is unavailable in synthetic preview", 404); },
    async updateAgentArtifact() { throw new TransportError("Agent artifact lifecycle is unavailable in synthetic preview", 404); },
    async removeAgentArtifact() { throw new TransportError("Agent artifact lifecycle is unavailable in synthetic preview", 404); },
    async captureAgentArtifact() { throw new TransportError("Agent artifacts are unavailable in synthetic preview", 404); },
    async getAgentArtifactDocumentPreview() { throw new TransportError("Agent document previews are unavailable in synthetic preview", 404); },
    async getAgentArtifactContent() { throw new TransportError("Agent artifacts are unavailable in synthetic preview", 404); },
    async listAgentSessions() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async createAgentSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentSessionContext() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async switchAgentSessionModel() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async revalidateAgentAuthority() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async deleteAgentSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async listAgentAttachments() { throw new TransportError("Agent attachments are unavailable in synthetic preview", 404); },
    async stageAgentAttachment() { throw new TransportError("Agent attachments are unavailable in synthetic preview", 404); },
    async deleteAgentAttachment() { throw new TransportError("Agent attachments are unavailable in synthetic preview", 404); },
    async getAgentAttachmentContent() { throw new TransportError("Agent attachments are unavailable in synthetic preview", 404); },
    async getAgentAttachmentDocumentPreview() { throw new TransportError("Agent document previews are unavailable in synthetic preview", 404); },
    async sendAgentMessage() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentChangeSet() { throw new TransportError("Local agent changes are unavailable in synthetic preview", 404); },
    async getAgentChangeDiff() { throw new TransportError("Local agent changes are unavailable in synthetic preview", 404); },
    async previewAgentChangeRestore() { throw new TransportError("Local agent change recovery is unavailable in synthetic preview", 404); },
    async applyAgentChangeRestore() { throw new TransportError("Local agent change recovery is unavailable in synthetic preview", 404); },
    async getAgentEvents() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async streamAgentEvents() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async decideAgentApproval() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async stopAgentSession() { throw new TransportError("Local agent is unavailable in synthetic preview", 404); },
    async getAgentWorkspaceDiscovery() { throw new TransportError("Local agent workspace discovery is unavailable in synthetic preview", 404); },
    async getAgentWorkspaceTree() { throw new TransportError("Local agent workspace is unavailable in synthetic preview", 404); },
    async getAgentWorkspaceSearch() { throw new TransportError("Local agent workspace search is unavailable in synthetic preview", 404); },
    async getAgentWorkspaceFile() { throw new TransportError("Local agent workspace is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceEdit() { throw new TransportError("Local agent workspace is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceEdit() { throw new TransportError("Local agent workspace is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceCreate() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceCreate() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceDirectoryCreate() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceDirectoryCreate() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceDirectoryMove() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceDirectoryMove() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceMove() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceMove() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceFileTrash() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceFileTrash() { throw new TransportError("Local agent workspace lifecycle is unavailable in synthetic preview", 404); },
    async previewAgentWorkspaceTransaction() { throw new TransportError("Local agent workspace transactions are unavailable in synthetic preview", 404); },
    async applyAgentWorkspaceTransaction() { throw new TransportError("Local agent workspace transactions are unavailable in synthetic preview", 404); },
    async interpretSessionWithModel() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async getModelJudgments() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async getModelJudgeAgreement() {
      throw new TransportError("Model judge is unavailable in synthetic preview", 404);
    },
    async getAnnotationAllowance() {
      throw new TransportError("Annotation is unavailable in synthetic preview", 404);
    },
    async setAnnotationAllowance() {
      throw new TransportError("Annotation is unavailable in synthetic preview", 404);
    },
    async getAnnotationMetaprompt() {
      throw new TransportError("Annotation is unavailable in synthetic preview", 404);
    },
    async getRemoteAnnotationDisclosure() {
      throw new TransportError("Remote annotation disclosure is unavailable in synthetic preview", 404);
    },
    async annotateRemotely() {
      throw new TransportError("Annotation is unavailable in synthetic preview", 404);
    },
    async shareFolder() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async listSharedFolders() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async revokeSharedFolder() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async joinSharedFolder() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async listPeerLinks() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async leavePeerLink() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async pullPeerLink() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async pushPeerLink() {
      throw new TransportError("Shared folders are unavailable in synthetic preview", 404);
    },
    async getLocalModels() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async getLocalModelPlacement() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async addLocalModel() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async activateLocalModel() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async deactivateLocalModel() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async getLocalRuntime() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async switchLocalRuntime() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async stopLocalRuntime() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async removeLocalModel() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async getLocalModelRemoteFiles() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async startLocalModelDownload() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async pauseLocalModelDownload() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async resumeLocalModelDownload() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async retryLocalModelDownload() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async cancelLocalModelDownload() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async scanLocalModelFolder() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async streamLocalModelChat() {
      throw new TransportError("Local models are unavailable in synthetic preview", 404);
    },
    async getProjectTimeline() {
      throw new TransportError("Timeline is unavailable in synthetic preview", 404);
    },
    async getSessionTimeline() {
      throw new TransportError("Timeline is unavailable in synthetic preview", 404);
    },
    async getCalibrationSample() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async reviewCalibrationCase() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async submitCalibrationRatings() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async getCalibrationRatings() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async getCalibrationProgress() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async getCalibrationExport() {
      throw new TransportError("Calibration is unavailable in synthetic preview", 404);
    },
    async getSessionTranscript() {
      throw new TransportError("Session reading is unavailable in synthetic preview", 404);
    },
    async getClaudeLocalSourceStatus() {
      return {
        consent_active: false,
        captured_sessions: 0,
        captured_events: 0,
        captured_requests: 0,
        telemetry_sessions: 0,
        indexed_sessions: 0,
        indexed_projects: 0,
        verification_capability: {
          state: "validation_only" as const,
          live_classification_enabled: false,
          supported_kinds: ["test" as const, "build" as const, "type_check" as const],
          reason_code: "synthetic_validation_only",
          candidate_schema_version: "synthetic-verification-1",
          classifier_version: "synthetic-classifier-1",
          normalizer_version: "synthetic-normalizer-1",
        },
        capture_channel: "claude_code_hooks",
        telemetry_channel: "claude_code_otlp",
        reads_transcripts: false,
        persists_content: false,
      };
    },
    async grantClaudeLocalHistoryConsent() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async revokeClaudeLocalHistoryConsent() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async indexClaudeLocalSessions() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async grantCodexLocalHistoryConsent() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async revokeCodexLocalHistoryConsent() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async indexCodexLocalSessions() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async analyzeCodexLocalSessions() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async enrichCodexDisplayLabels() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async setManualDisplayLabel() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async clearManualDisplayLabel() {
      throw new TransportError("Data sources are unavailable in synthetic preview", 404);
    },
    async listCodexSessions(limit = 100, offset = 0) {
      return {
        sessions: copy(SYNTHETIC_CODEX_SESSIONS.slice(offset, offset + limit)),
        limit,
        offset,
      };
    },
    async listProjectSessions(projectId, limit = 100, offset = 0) {
      const matching = SYNTHETIC_CODEX_SESSIONS.filter(
        (session) => session.project_id === projectId,
      );
      const sessions = matching.slice(offset, offset + limit);
      return {
        sessions: copy(sessions),
        limit,
        offset,
        total: matching.length,
        has_more: offset + sessions.length < matching.length,
      };
    },
    async getSessionMetrics(sessionId: string) {
      if (!SYNTHETIC_CODEX_SESSIONS.some((session) => session.session_id === sessionId)) {
        throw new TransportError("Synthetic session was not found", 404);
      }
      return { session_id: sessionId, metrics: [] };
    },
    async listAnalysisJobs() {
      throw new TransportError(
        "Durable jobs are unavailable in synthetic demo mode",
        501,
      );
    },
    async getAnalysisJob() {
      throw new TransportError(
        "Durable jobs are unavailable in synthetic demo mode",
        501,
      );
    },
    async getLatestSessionAnalysisJob() {
      throw new TransportError(
        "Durable jobs are unavailable in synthetic demo mode",
        501,
      );
    },
    async cancelAnalysisJob() {
      throw new TransportError(
        "Durable jobs are unavailable in synthetic demo mode",
        501,
      );
    },
    async listAutomationGrants() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async getAutomationGrant() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async createAutomationGrant() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async renewAutomationGrant() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async revokeAutomationGrant() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async pollAutomationGrants() {
      throw new TransportError(
        "Automation grants are unavailable in synthetic demo mode",
        501,
      );
    },
    async getLatestSessionQualityAnalysis(sessionId: string) {
      if (sessionId !== SYNTHETIC_QUALITY_SESSION_ID) {
        throw new TransportError("Synthetic quality analysis run was not found", 404);
      }
      return copy(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN);
    },
    async getSessionQualityAnalysisRun(runId: string) {
      if (runId !== SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id) {
        throw new TransportError("Synthetic quality analysis run was not found", 404);
      }
      return copy(SYNTHETIC_CURRENT_SESSION_QUALITY_RUN);
    },
    async getSessionCoachingSummary(runId) {
      if (runId !== SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id) {
        throw new TransportError("Synthetic coaching summary was not found", 404);
      }
      return copy(SYNTHETIC_COACHING_PROJECTION);
    },
    async startSessionQualityAnalysis(sessionId, request) {
      if (sessionId !== SYNTHETIC_QUALITY_SESSION_ID) {
        throw new TransportError("Synthetic session was not found", 404);
      }
      if (
        request.confirmation !== "analyze_selected_redacted_text" ||
        request.preset_id !== "coaching_profile_v1"
      ) {
        throw new TransportError("Synthetic quality request is invalid", 422);
      }
      return copy({
        analysis_profile_key: "coaching_profile",
        analysis_profile_version: 1,
        applied: false,
        result_count: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.results.length,
        run_id: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id,
        status: "completed" as const,
      });
    },
    async prepareSessionQualityAnalysisPreview(sessionId, request) {
      if (sessionId !== SYNTHETIC_QUALITY_SESSION_ID) {
        throw new TransportError("Synthetic session was not found", 404);
      }
      if (request.preset_id !== "coaching_profile_v1") {
        throw new TransportError("Synthetic preview request is invalid", 422);
      }
      throw new TransportError(
        "Private previews are unavailable in synthetic demo mode",
        501,
      );
    },
    async approveSessionQualityAnalysisPreview() {
      throw new TransportError(
        "Private preview approvals are unavailable in synthetic demo mode",
        501,
      );
    },
    async aggregateSessionQuality(request) {
      return copy(syntheticQualityAggregate(request.session_ids));
    },
    async aggregateProjectQuality(request) {
      const projectIds = request.project_ids;
      if (
        request.selection_mode !== "all_analyzed_work" ||
        projectIds.length < 1 ||
        projectIds.length > 25 ||
        new Set(projectIds).size !== projectIds.length ||
        projectIds.some((value) => !/^[a-f0-9]{64}$/.test(value))
      ) {
        throw new TransportError("Synthetic project quality selection is invalid", 422);
      }
      if (projectIds.some((projectId) => projectId !== SYNTHETIC_QUALITY_PROJECT_ID)) {
        throw new TransportError("Synthetic project quality selection is incomplete", 409);
      }
      const sessionIds = SYNTHETIC_CODEX_SESSIONS.filter((session) =>
        projectIds.includes(session.project_id),
      ).map((session) => session.session_id);
      return copy({
        aggregation_method: "ratio_of_sums" as const,
        estimand: "per_eligible_opportunity" as const,
        selected_project_count: projectIds.length,
        selection_mode: "all_analyzed_work" as const,
        session_quality: syntheticCoachingProjectAggregate(sessionIds.length),
      });
    },
    async getLatestModelLinkExperiment(sessionId) {
      if (sessionId !== SYNTHETIC_QUALITY_SESSION_ID) {
        throw new TransportError("Synthetic model-link experiment was not found", 404);
      }
      return copy(modelLinkExperiment);
    },
    async startModelLinkExperiment(sessionId) {
      if (sessionId !== SYNTHETIC_QUALITY_SESSION_ID) {
        throw new TransportError("Synthetic session was not found", 404);
      }
      modelLinkExperiment = copy(SYNTHETIC_MODEL_LINK_EXPERIMENT);
      return copy({
        ...SYNTHETIC_MODEL_LINK_OUTCOME,
        experiment: modelLinkExperiment,
      });
    },
    async annotateModelLink(runId, linkId, request) {
      if (
        runId !== modelLinkExperiment.run.run_id ||
        !modelLinkExperiment.links.some((link) => link.link_id === linkId)
      ) {
        throw new TransportError("Synthetic model link was not found", 404);
      }
      const current = modelLinkExperiment.annotations.find(
        (annotation) => annotation.link_id === linkId,
      );
      const revision = current?.revision ?? 0;
      if (revision !== request.expected_revision) {
        throw new TransportError("Synthetic annotation revision changed", 409);
      }
      const annotation = {
        link_id: linkId,
        revision: revision + 1,
        label: request.label,
        annotated_at: "2040-01-03T09:01:00Z",
      };
      modelLinkExperiment = {
        ...modelLinkExperiment,
        annotations: [
          ...modelLinkExperiment.annotations.filter(
            (item) => item.link_id !== linkId,
          ),
          annotation,
        ],
      };
      return copy(annotation);
    },
    async getLatestModelEnsemble() {
      throw new TransportError(
        "Local model ensembles are unavailable in synthetic demo mode",
        404,
      );
    },
    async getActiveModelEnsembleWatch() {
      throw new TransportError(
        "No local model-ensemble watch exists in synthetic demo mode",
        404,
      );
    },
    async startModelEnsemble() {
      throw new TransportError(
        "Local model ensembles require the integrated local runtime",
        501,
      );
    },
    async listCandidates(status: CandidateStatusFilter = "all", _signal, page) {
      const filtered =
        status === "all"
          ? candidates
          : candidates.filter((item) => item.decision_status === status);
      const result = syntheticPage(filtered, page);
      return { candidates: result.values, limit: result.limit, offset: result.offset };
    },
    async listTaskRevisions(taskId?: string, _signal?: AbortSignal, page?: ContentFreeListPage) {
      const filtered = taskId ? tasks.filter((task) => task.task_id === taskId) : tasks;
      const result = syntheticPage(filtered, page);
      return { tasks: result.values, limit: result.limit, offset: result.offset };
    },
    async getCandidateDecisions(candidateId: string) {
      if (!candidates.some((item) => item.candidate.candidate_id === candidateId)) {
        throw new TransportError("Synthetic candidate was not found", 404);
      }
      return {
        candidate_id: candidateId,
        decisions: copy(auditDecisions.get(candidateId) ?? []),
      };
    },
    async getTaskRevision(taskId: string, revision: number) {
      const task = tasks.find(
        (item) => item.task_id === taskId && item.revision === revision,
      );
      if (!task) throw new TransportError("Synthetic task revision was not found", 404);
      return { task: copy(task) };
    },
    async listTaskLifecycles(_signal, page, eventLimit = 100) {
      const result = syntheticPage(lifecycles, page);
      return {
        lifecycles: result.values.map((item) => lifecyclePage(item, eventLimit, 0)),
        limit: result.limit,
        offset: result.offset,
      };
    },
    async getTaskLifecycle(taskId, revision, eventLimit = 100, eventOffset = 0) {
      const snapshot = lifecycles.find(
        (item) => item.task_id === taskId && item.task_revision === revision,
      );
      if (!snapshot) throw new TransportError("Synthetic lifecycle was not found", 404);
      return lifecyclePage(snapshot, eventLimit, eventOffset);
    },
    async transitionTaskLifecycle(
      taskId,
      revision,
      expectedHeadEventId,
      state: TaskLifecycleState,
      idempotencyKey,
    ) {
      const fingerprint = [
        "transition", taskId, String(revision), expectedHeadEventId ?? "none", state,
      ].join(":");
      const cached = lifecycleCommands.get(idempotencyKey);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          throw new TransportError("Synthetic lifecycle idempotency conflict", 409);
        }
        return copy(cached.response);
      }
      const snapshotIndex = lifecycles.findIndex(
        (item) => item.task_id === taskId && item.task_revision === revision,
      );
      const snapshot = lifecycles[snapshotIndex];
      const task = tasks.find((item) => item.task_id === taskId && item.revision === revision);
      if (!snapshot || !task) throw new TransportError("Synthetic lifecycle was not found", 404);
      if (snapshot.current_task_revision !== revision || !snapshot.is_current_revision) {
        throw new TransportError("Synthetic lifecycle revision changed", 409);
      }
      if (snapshot.head_event_id !== expectedHeadEventId) {
        throw new TransportError("Synthetic lifecycle head changed", 409);
      }
      const allowed: Readonly<Record<string, TaskLifecycleState>> = {
        unknown: "backlog",
        backlog: "in_progress",
        in_progress: "done",
      };
      if (allowed[snapshot.current_state ?? "unknown"] !== state) {
        throw new TransportError("Synthetic lifecycle transition was invalid", 422);
      }
      const eventId = safeId(sequence++);
      const event = {
        event_id: eventId,
        task_id: taskId,
        task_revision: revision,
        sequence: snapshot.event_count + 1,
        event_kind: "transition" as const,
        prior_state: snapshot.current_state,
        resulting_state: state,
        previous_event_id: snapshot.head_event_id,
        supersedes_event_id: null,
        task_input_fingerprint: task.input_fingerprint,
        command_schema_version: "task-lifecycle-command-v1" as const,
        source: "explicit_local_user" as const,
        actor_scope: "local_user" as const,
        request_fingerprint: safeId(sequence++),
        created_at: new Date(Date.UTC(2040, 0, 2, 12, 0, sequence)).toISOString(),
      };
      lifecycles[snapshotIndex] = {
        ...snapshot,
        current_state: state,
        head_event_id: eventId,
        event_count: snapshot.event_count + 1,
        events: [...snapshot.events, event],
        events_complete: true,
      };
      const response: TaskLifecycleMutationResponse = {
        event,
        state,
        head_event_id: eventId,
      };
      lifecycleCommands.set(idempotencyKey, { fingerprint, response: copy(response) });
      return copy(response);
    },
    async correctTaskLifecycle(
      taskId,
      revision,
      expectedHeadEventId,
      expectedPriorState,
      expectedResultingState,
      idempotencyKey,
    ) {
      const fingerprint = [
        "correction", taskId, String(revision), expectedHeadEventId,
        expectedPriorState, expectedResultingState ?? "unknown",
      ].join(":");
      const cached = lifecycleCommands.get(idempotencyKey);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          throw new TransportError("Synthetic lifecycle idempotency conflict", 409);
        }
        return copy(cached.response);
      }
      const snapshotIndex = lifecycles.findIndex(
        (item) => item.task_id === taskId && item.task_revision === revision,
      );
      const snapshot = lifecycles[snapshotIndex];
      const task = tasks.find((item) => item.task_id === taskId && item.revision === revision);
      if (!snapshot || !task) throw new TransportError("Synthetic lifecycle was not found", 404);
      if (snapshot.current_task_revision !== revision || !snapshot.is_current_revision) {
        throw new TransportError("Synthetic lifecycle revision changed", 409);
      }
      if (snapshot.head_event_id !== expectedHeadEventId) {
        throw new TransportError("Synthetic lifecycle head changed", 409);
      }
      const head = snapshot.events.at(-1);
      if (!head || head.event_id !== expectedHeadEventId) {
        throw new TransportError("Synthetic lifecycle audit was incomplete", 409);
      }
      if (snapshot.current_state !== expectedPriorState || head.prior_state !== expectedResultingState) {
        throw new TransportError("Synthetic lifecycle correction context changed", 409);
      }
      const eventId = safeId(sequence++);
      const event = {
        event_id: eventId,
        task_id: taskId,
        task_revision: revision,
        sequence: snapshot.event_count + 1,
        event_kind: "correction" as const,
        prior_state: snapshot.current_state,
        resulting_state: head.prior_state,
        previous_event_id: snapshot.head_event_id,
        supersedes_event_id: snapshot.head_event_id,
        task_input_fingerprint: task.input_fingerprint,
        command_schema_version: "task-lifecycle-command-v1" as const,
        source: "explicit_local_user" as const,
        actor_scope: "local_user" as const,
        request_fingerprint: safeId(sequence++),
        created_at: new Date(Date.UTC(2040, 0, 2, 12, 0, sequence)).toISOString(),
      };
      lifecycles[snapshotIndex] = {
        ...snapshot,
        current_state: head.prior_state,
        head_event_id: eventId,
        event_count: snapshot.event_count + 1,
        events: [...snapshot.events, event],
        events_complete: true,
      };
      const response: TaskLifecycleMutationResponse = {
        event,
        state: head.prior_state,
        head_event_id: eventId,
      };
      lifecycleCommands.set(idempotencyKey, { fingerprint, response: copy(response) });
      return copy(response);
    },
    async listAnalysisRuns(taskId?: string, _signal?: AbortSignal, page?: ContentFreeListPage) {
      const filtered = taskId ? runs.filter((run) => run.task_id === taskId) : runs;
      const result = syntheticPage(filtered, page);
      return { runs: result.values, limit: result.limit, offset: result.offset };
    },
    async getAnalysisRun(runId: string) {
      const run = runs.find((item) => item.run_id === runId);
      const results = resultsByRun.get(runId);
      if (!run || !results) {
        throw new TransportError("Synthetic analysis run was not found", 404);
      }
      return { run: copy(run), results: copy(results) };
    },
    async review(command, idempotencyKey) {
      const cached = decisions.get(idempotencyKey);
      if (cached) return copy({ ...cached, applied: false });

      const items = findCandidates(command);
      assertVersions(command, items);
      if (items.some((item) => item.decision_status === "decided")) {
        throw new TransportError("Synthetic candidate was already decided", 409);
      }

      const decisionId = safeId(sequence++);
      const outputRevisions: { task_id: string; revision: number }[] = [];
      const createdTasks: TaskRevision[] = [];

      if (command.action === "accept" || command.action === "merge") {
        const taskId = safeId(sequence++);
        const sessions = items.flatMap((item) => item.candidate.session_ids);
        createdTasks.push({
          task_id: taskId,
          revision: 1,
          project_id: items[0].candidate.project_id,
          task_type: command.request.task_category,
          lifecycle_state: "confirmed",
          session_ids: sessions,
          input_fingerprint: safeId(sequence++),
          created_at: "2040-01-02T12:00:00Z",
        });
        outputRevisions.push({ task_id: taskId, revision: 1 });
      }

      if (command.action === "split") {
        command.request.partitions.forEach((sessions, index) => {
          const taskId = safeId(sequence++);
          createdTasks.push({
            task_id: taskId,
            revision: 1,
            project_id: items[0].candidate.project_id,
            task_type: command.request.task_categories[index] ?? "unknown",
            lifecycle_state: "confirmed",
            session_ids: [...sessions],
            input_fingerprint: safeId(sequence++),
            created_at: "2040-01-02T12:00:00Z",
          });
          outputRevisions.push({ task_id: taskId, revision: 1 });
        });
      }

      tasks.unshift(...createdTasks);
      lifecycles.unshift(...createdTasks.map((task): TaskLifecycleSnapshot => ({
        task_id: task.task_id,
        task_revision: task.revision,
        current_task_revision: task.revision,
        is_current_revision: true,
        current_state: null,
        head_event_id: null,
        event_count: 0,
        prior_revision_event_count: 0,
        events: [],
        events_limit: 100,
        events_offset: 0,
        events_complete: true,
      })));
      const reviewedIds = new Set(items.map((item) => item.candidate.candidate_id));
      candidates = candidates.map((item) =>
        reviewedIds.has(item.candidate.candidate_id)
          ? {
              ...item,
              decision_status: "decided",
              decision_id: decisionId,
              decision_action: command.action,
            }
          : item,
      );

      const result: TaskReviewResponse = {
        decision_id: decisionId,
        action: command.action,
        output_revisions: outputRevisions,
        applied: true,
      };
      const audit: TaskDecision = {
        decision_id: decisionId,
        action: command.action,
        candidate_ids: [...reviewedIds],
        revision_links: outputRevisions.map((link) => ({ ...link, role: "output" })),
        decision_schema_version: "synthetic.task-review.v1",
        decision_code: command.action === "reject" ? command.request.reason : null,
        decided_at: "2040-01-02T12:00:00Z",
        decision_source: "person",
      };
      reviewedIds.forEach((candidateId) => auditDecisions.set(candidateId, [copy(audit)]));
      decisions.set(idempotencyKey, result);
      return copy(result);
    },
    async startAnalysis(taskId, revision, idempotencyKey) {
      const cached = analyses.get(idempotencyKey);
      if (cached) return copy({ ...cached, applied: false });
      const task = tasks.find(
        (item) => item.task_id === taskId && item.revision === revision,
      );
      if (!task) {
        throw new TransportError("Synthetic task revision was not found", 404);
      }

      const runId = safeId(sequence++);
      const run: AnalysisRun = {
        ...SYNTHETIC_RUN,
        run_id: runId,
        task_id: taskId,
        task_revision: revision,
        input_fingerprint: task.input_fingerprint,
        started_at: "2040-01-02T12:01:00Z",
        finished_at: "2040-01-02T12:01:02Z",
      };
      const results = SYNTHETIC_RESULTS.map((result) => {
        const sessionCount = result.key === "task.workflow.session_count";
        const sessionScoped =
          result.key.startsWith("task.workflow.") ||
          result.key.startsWith("task.efficiency.") ||
          result.key === "task.verification.observed_count";
        return {
          ...result,
          value_state: sessionCount ? "known" as const : "unknown" as const,
          numeric_value: sessionCount ? task.session_ids.length : null,
          observed_count: sessionCount ? task.session_ids.length : 0,
          eligible_count: sessionCount
            ? task.session_ids.length
            : sessionScoped
              ? task.session_ids.length
              : 0,
          coverage: sessionCount ? 1 : 0,
          confidence: sessionCount ? 1 : null,
          evidence_event_ids: [],
          computed_at: "2040-01-02T12:01:01Z",
        };
      });
      runs.unshift(run);
      resultsByRun.set(runId, results);

      const outcome: TaskAnalysisResponse = {
        run_id: runId,
        status: "completed",
        result_count: results.length,
        applied: true,
      };
      analyses.set(idempotencyKey, outcome);
      return copy(outcome);
    },
  };
}
