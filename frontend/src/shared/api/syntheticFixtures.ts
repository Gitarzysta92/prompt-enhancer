import type {
  AnalysisResult,
  AnalysisRun,
  CandidateListItem,
  CodexSession,
  ModelLinkExperiment,
  ModelLinkExperimentOutcome,
  MetricCoverageReport,
  ProviderCompatibilityStatus,
  ProviderCapabilityReport,
  MetricEvidenceCapability,
  SessionCoachingProjection,
  SessionAnalysisResult,
  SessionAnalysisRunResponse,
  SessionMetricReadinessReport,
  TaskDecision,
  TaskLifecycleSnapshot,
  TaskRevision,
} from "./contracts";

const pseudonym = (character: string): string => character.repeat(64);

export const SYNTHETIC_QUALITY_PROJECT_ID = pseudonym("4");
export const SYNTHETIC_QUALITY_SESSION_ID = pseudonym("5");

export const SYNTHETIC_MODEL_LINK_EXPERIMENT: ModelLinkExperiment = {
  run: {
    run_id: pseudonym("a"),
    experiment_key: "local.neural-link-comparison",
    experiment_version: 1,
    resolved_device: "cuda",
    qwen_model: {
      key: "qwen3_embedding_06b",
      repository_id: "Qwen/Qwen3-Embedding-0.6B",
      revision: "c".repeat(40),
      license_spdx: "Apache-2.0",
      tokenizer_id: `Qwen/Qwen3-Embedding-0.6B:${"c".repeat(40)}`,
      backend_key: "qwen3_embedding_last_token_v1",
    },
    bge_model: {
      key: "bge_reranker_v2_m3",
      repository_id: "BAAI/bge-reranker-v2-m3",
      revision: "d".repeat(40),
      license_spdx: "Apache-2.0",
      tokenizer_id: `BAAI/bge-reranker-v2-m3:${"d".repeat(40)}`,
      backend_key: "bge_reranker_sequence_classifier_v1",
    },
    query_count: 1,
    link_count: 2,
    agreement_count: 0,
    started_at: "2040-01-03T09:00:00Z",
    finished_at: "2040-01-03T09:00:07Z",
    local_only: true,
  },
  links: [
    {
      link_id: pseudonym("b"),
      candidate_kind: "response",
      qwen_score: 0.82,
      qwen_rank: 1,
      bge_score: 2.4,
      bge_rank: 2,
      recommended_by: "qwen",
    },
    {
      link_id: pseudonym("c"),
      candidate_kind: "plan",
      qwen_score: 0.71,
      qwen_rank: 2,
      bge_score: 4.8,
      bge_rank: 1,
      recommended_by: "bge",
    },
  ],
  annotations: [],
};

export const SYNTHETIC_MODEL_LINK_OUTCOME: ModelLinkExperimentOutcome = {
  experiment: SYNTHETIC_MODEL_LINK_EXPERIMENT,
  suggestions: [
    {
      link_id: pseudonym("b"),
      query_excerpt: "Add a fictional readiness summary to the local dashboard.",
      candidate_excerpt: "Implemented the fictional readiness summary with synthetic checks.",
    },
    {
      link_id: pseudonym("c"),
      query_excerpt: "Add a fictional readiness summary to the local dashboard.",
      candidate_excerpt: "Plan the fictional summary, empty state, and local-only verification.",
    },
  ],
  applied: true,
};

export const SYNTHETIC_PROVIDER_COMPATIBILITY: ProviderCompatibilityStatus = {
  provider: "synthetic",
  capability: "session_text_analysis",
  state: "exact",
  capability_state: "supported",
  provider_family: "synthetic_provider",
  provider_version: "preview-1",
  adapter_family: "synthetic_adapter",
  adapter_version: "preview-1",
  source_schema_family: "synthetic_session",
  source_schema_version: "preview-1",
  content_schema_family: "synthetic_content",
  content_schema_version: "preview-1",
  reason_code: "exact_match",
  checked_at: "2040-01-03T09:12:30Z",
  update_support: "supported",
  update_target: null,
};

export const SYNTHETIC_CODEX_SESSIONS: CodexSession[] = [
  {
    session_id: SYNTHETIC_QUALITY_SESSION_ID,
    installation_id: pseudonym("3"),
    project_id: SYNTHETIC_QUALITY_PROJECT_ID,
    project_display_name: "Synthetic Metric Lab",
    session_display_name: "Complete Coaching v1 evidence showcase",
    provider: "synthetic",
    project_display_name_origin: "provider",
    session_display_name_origin: "provider",
    project_manual_label_revision: 0,
    session_manual_label_revision: 0,
    provider_version: "synthetic-provider-1",
    adapter_version: "synthetic-adapter-1",
    source_schema_version: "synthetic-schema-1",
    started_at: "2040-01-03T09:00:00Z",
    ended_at: "2040-01-03T09:12:00Z",
    terminal_state: "completed",
    events_complete: true,
  },
];

export const SYNTHETIC_CANDIDATES: CandidateListItem[] = [
  {
    candidate: {
      candidate_id: pseudonym("a"),
      provider: "synthetic",
      installation_id: pseudonym("1"),
      project_id: pseudonym("2"),
      session_ids: [pseudonym("3"), pseudonym("4"), pseudonym("5")],
      signals: [
        {
          key: "project_continuity",
          version: 1,
          session_ids: [pseudonym("3"), pseudonym("4")],
          direction: "supports_link",
          confidence: 0.94,
          weight: 1,
          evidence_code: "same_project",
          observed_count: 2,
          eligible_count: 2,
          coverage: 1,
          numeric_evidence: null,
          evidence_unit: null,
        },
        {
          key: "time_gap",
          version: 1,
          session_ids: [pseudonym("4"), pseudonym("5")],
          direction: "supports_link",
          confidence: 0.76,
          weight: 0.8,
          evidence_code: "gap_within_window",
          observed_count: 2,
          eligible_count: 2,
          coverage: 1,
          numeric_evidence: 18,
          evidence_unit: "minutes",
        },
      ],
      confidence: 0.86,
      observed_count: 4,
      eligible_count: 4,
      coverage: 1,
      discovery_version: "synthetic.discovery.v1",
      input_fingerprint: pseudonym("6"),
      created_at: "2040-01-02T09:30:00Z",
    },
    decision_status: "undecided",
    decision_id: null,
    decision_action: null,
  },
  {
    candidate: {
      candidate_id: pseudonym("b"),
      provider: "synthetic",
      installation_id: pseudonym("1"),
      project_id: pseudonym("2"),
      session_ids: [pseudonym("7"), pseudonym("8")],
      signals: [
        {
          key: "time_gap",
          version: 1,
          session_ids: [pseudonym("7"), pseudonym("8")],
          direction: "unknown",
          confidence: null,
          weight: 0.8,
          evidence_code: "timestamp_unknown",
          observed_count: 0,
          eligible_count: 2,
          coverage: 0,
          numeric_evidence: null,
          evidence_unit: null,
        },
      ],
      confidence: null,
      observed_count: 0,
      eligible_count: 2,
      coverage: 0,
      discovery_version: "synthetic.discovery.v1",
      input_fingerprint: pseudonym("9"),
      created_at: "2040-01-02T10:15:00Z",
    },
    decision_status: "undecided",
    decision_id: null,
    decision_action: null,
  },
  {
    candidate: {
      candidate_id: pseudonym("c"),
      provider: "synthetic",
      installation_id: pseudonym("1"),
      project_id: pseudonym("2"),
      session_ids: [pseudonym("0"), pseudonym("f")],
      signals: [
        {
          key: "project_continuity",
          version: 1,
          session_ids: [pseudonym("0"), pseudonym("f")],
          direction: "supports_link",
          confidence: 0.9,
          weight: 1,
          evidence_code: "same_project",
          observed_count: 2,
          eligible_count: 2,
          coverage: 1,
          numeric_evidence: null,
          evidence_unit: null,
        },
      ],
      confidence: 0.9,
      observed_count: 2,
      eligible_count: 2,
      coverage: 1,
      discovery_version: "synthetic.discovery.v1",
      input_fingerprint: pseudonym("3"),
      created_at: "2040-01-01T14:00:00Z",
    },
    decision_status: "decided",
    decision_id: pseudonym("4"),
    decision_action: "accept",
  },
];

export const SYNTHETIC_TASKS: TaskRevision[] = [
  {
    task_id: pseudonym("d"),
    revision: 1,
    project_id: pseudonym("2"),
    task_type: "feature_implementation",
    lifecycle_state: "confirmed",
    session_ids: [pseudonym("0"), pseudonym("f")],
    input_fingerprint: pseudonym("3"),
    created_at: "2040-01-01T14:05:00Z",
  },
];

/** Content-free explicit-user lifecycle receipts for the fictional task. */
export const SYNTHETIC_TASK_LIFECYCLES: TaskLifecycleSnapshot[] = [
  {
    task_id: pseudonym("d"),
    task_revision: 1,
    current_task_revision: 1,
    is_current_revision: true,
    current_state: "in_progress",
    head_event_id: pseudonym("7"),
    event_count: 2,
    prior_revision_event_count: 0,
    events_limit: 100,
    events_offset: 0,
    events_complete: true,
    events: [
      {
        event_id: pseudonym("6"),
        task_id: pseudonym("d"),
        task_revision: 1,
        sequence: 1,
        event_kind: "transition",
        prior_state: null,
        resulting_state: "backlog",
        previous_event_id: null,
        supersedes_event_id: null,
        task_input_fingerprint: pseudonym("3"),
        command_schema_version: "task-lifecycle-command-v1",
        source: "explicit_local_user",
        actor_scope: "local_user",
        request_fingerprint: pseudonym("8"),
        created_at: "2040-01-01T14:05:10Z",
      },
      {
        event_id: pseudonym("7"),
        task_id: pseudonym("d"),
        task_revision: 1,
        sequence: 2,
        event_kind: "transition",
        prior_state: "backlog",
        resulting_state: "in_progress",
        previous_event_id: pseudonym("6"),
        supersedes_event_id: null,
        task_input_fingerprint: pseudonym("3"),
        command_schema_version: "task-lifecycle-command-v1",
        source: "explicit_local_user",
        actor_scope: "local_user",
        request_fingerprint: pseudonym("9"),
        created_at: "2040-01-01T14:05:20Z",
      },
    ],
  },
];

/** Immutable fictional review receipt that links the decided candidate to its task revision. */
export const SYNTHETIC_TASK_DECISIONS: Readonly<Record<string, readonly TaskDecision[]>> = {
  [pseudonym("c")]: [
    {
      decision_id: pseudonym("4"),
      action: "accept",
      candidate_ids: [pseudonym("c")],
      revision_links: [
        { task_id: pseudonym("d"), revision: 1, role: "output" },
      ],
      decision_schema_version: "synthetic.task-review.v1",
      decision_source: "person",
      decision_code: null,
      decided_at: "2040-01-01T14:05:00Z",
    },
  ],
};

export const SYNTHETIC_RUN: AnalysisRun = {
  run_id: pseudonym("e"),
  task_id: pseudonym("d"),
  task_revision: 1,
  metric_pack_key: "core.metadata.task",
  metric_pack_version: 3,
  data_tier: "metadata",
  input_fingerprint: pseudonym("3"),
  metric_engine_version: "task-deterministic-2",
  redactor_version: "not-applicable",
  schema_version: 6,
  started_at: "2040-01-01T14:06:00Z",
  status: "completed",
  finished_at: "2040-01-01T14:06:02Z",
  failure_code: null,
};

const SYNTHETIC_METRIC_DEFINITIONS: Record<
  string,
  { version: number; dimension: string; displayName: string; description: string }
> = {
  "task.workflow.session_count": {
    version: 2,
    dimension: "workflow",
    displayName: "Session count",
    description: "Number of reviewed sessions assigned to this task revision.",
  },
  "task.workflow.observed_event_count": {
    version: 2,
    dimension: "workflow",
    displayName: "Observed event count",
    description: "Events available for this task; coverage reports complete session streams.",
  },
  "task.efficiency.cycle_time_ms": {
    version: 2,
    dimension: "efficiency",
    displayName: "Task cycle time",
    description: "Elapsed time from the earliest session start to the latest session end.",
  },
  "task.verification.observed_count": {
    version: 2,
    dimension: "verification",
    displayName: "Observed verifications",
    description: "Verification events available for the reviewed task.",
  },
  "task.verification.pass_rate": {
    version: 2,
    dimension: "verification",
    displayName: "Verification pass rate",
    description: "Successful verification results divided by known results.",
  },
  "task.usage.input_tokens": {
    version: 2,
    dimension: "usage",
    displayName: "Input tokens",
    description: "Subtotal of additive input-token deltas across task sessions.",
  },
  "task.usage.output_tokens": {
    version: 2,
    dimension: "usage",
    displayName: "Output tokens",
    description: "Subtotal of additive output-token deltas across task sessions.",
  },
  "task.usage.total_tokens": {
    version: 2,
    dimension: "usage",
    displayName: "Total tokens",
    description: "Subtotal of additive total-token deltas across task sessions.",
  },
  "task.workflow.finalized_turn_count": {
    version: 1,
    dimension: "workflow",
    displayName: "Observed agent iterations",
    description: "Observed finalized-turn subtotal across reviewed task sessions.",
  },
  "task.data_quality.turn_usage_coverage": {
    version: 1,
    dimension: "data_quality",
    displayName: "Usable turn usage coverage",
    description: "Share of finalized turns paired with usable additive turn usage.",
  },
  "task.data_quality.turn_duration_coverage": {
    version: 1,
    dimension: "data_quality",
    displayName: "Turn duration coverage",
    description: "Share of finalized turns with a known duration.",
  },
  "task.data_quality.tool_result_coverage": {
    version: 1,
    dimension: "data_quality",
    displayName: "Tool result coverage",
    description: "Share of completed tool events with a known result.",
  },
  "task.data_quality.tool_duration_coverage": {
    version: 1,
    dimension: "data_quality",
    displayName: "Tool duration coverage",
    description: "Share of completed tool events with a known duration.",
  },
  "task.data_quality.unknown_event_kind_rate": {
    version: 1,
    dimension: "data_quality",
    displayName: "Unknown event kind rate",
    description: "Share of observed safe events whose event kind is unknown.",
  },
  "task.data_quality.direct_event_timestamp_rate": {
    version: 1,
    dimension: "data_quality",
    displayName: "Direct event timestamp rate",
    description: "Share of safe events with an event-specific provider timestamp.",
  },
};

function syntheticResult(input: {
  key: string;
  state: AnalysisResult["value_state"];
  numericValue: number | null;
  unit: string;
  source?: AnalysisResult["source"];
  observed: number;
  eligible: number;
  coverage: number;
  confidence: number | null;
  evidence?: string[];
}): AnalysisResult {
  const definition = SYNTHETIC_METRIC_DEFINITIONS[input.key];
  if (!definition) throw new Error("Synthetic metric definition is missing");
  return {
    key: input.key,
    version: definition.version,
    dimension: definition.dimension,
    display_name: definition.displayName,
    description: definition.description,
    value_state: input.state,
    numeric_value: input.numericValue,
    text_value: null,
    unit: input.unit,
    source: input.source ?? "deterministic",
    observed_count: input.observed,
    eligible_count: input.eligible,
    coverage: input.coverage,
    confidence: input.confidence,
    calculator_version: "task-deterministic-2",
    evidence_event_ids: input.evidence ?? [],
    model_id: null,
    model_revision: null,
    tokenizer_id: null,
    prompt_version: null,
    rubric_version: null,
    error_code: null,
    computed_at: "2040-01-01T14:06:01Z",
  };
}

const SYNTHETIC_EVENT_IDS = ["5", "6", "7", "8", "9", "a", "b", "c"].map(
  pseudonym,
);
const SYNTHETIC_TURN_END_IDS = SYNTHETIC_EVENT_IDS.slice(0, 2);
const SYNTHETIC_TOOL_END_IDS = SYNTHETIC_EVENT_IDS.slice(2, 4);
const SYNTHETIC_VERIFICATION_IDS = SYNTHETIC_EVENT_IDS.slice(4, 6);
const SYNTHETIC_USAGE_IDS = SYNTHETIC_EVENT_IDS.slice(6, 7);

export const SYNTHETIC_RESULTS: AnalysisResult[] = [
  syntheticResult({
    key: "task.workflow.session_count",
    state: "known",
    numericValue: 2,
    unit: "count",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
  }),
  syntheticResult({
    key: "task.workflow.observed_event_count",
    state: "known",
    numericValue: 8,
    unit: "count",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_EVENT_IDS,
  }),
  syntheticResult({
    key: "task.efficiency.cycle_time_ms",
    state: "known",
    numericValue: 1_800_000,
    unit: "milliseconds",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
  }),
  syntheticResult({
    key: "task.verification.observed_count",
    state: "known",
    numericValue: 2,
    unit: "count",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_VERIFICATION_IDS,
  }),
  syntheticResult({
    key: "task.verification.pass_rate",
    state: "known",
    numericValue: 0.5,
    unit: "ratio",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_VERIFICATION_IDS,
  }),
  syntheticResult({
    key: "task.usage.input_tokens",
    state: "known",
    numericValue: 10,
    unit: "tokens",
    source: "provider_reported",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: null,
    evidence: SYNTHETIC_USAGE_IDS,
  }),
  syntheticResult({
    key: "task.usage.output_tokens",
    state: "known",
    numericValue: 5,
    unit: "tokens",
    source: "provider_reported",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: null,
    evidence: SYNTHETIC_USAGE_IDS,
  }),
  syntheticResult({
    key: "task.usage.total_tokens",
    state: "unknown",
    numericValue: null,
    unit: "tokens",
    source: "provider_reported",
    observed: 0,
    eligible: 2,
    coverage: 0,
    confidence: null,
  }),
  syntheticResult({
    key: "task.workflow.finalized_turn_count",
    state: "known",
    numericValue: 2,
    unit: "count",
    observed: 2,
    eligible: 2,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_TURN_END_IDS,
  }),
  syntheticResult({
    key: "task.data_quality.turn_usage_coverage",
    state: "known",
    numericValue: 0.5,
    unit: "ratio",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: 1,
    evidence: SYNTHETIC_USAGE_IDS,
  }),
  syntheticResult({
    key: "task.data_quality.turn_duration_coverage",
    state: "known",
    numericValue: 0.5,
    unit: "ratio",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: 1,
    evidence: SYNTHETIC_TURN_END_IDS.slice(0, 1),
  }),
  syntheticResult({
    key: "task.data_quality.tool_result_coverage",
    state: "known",
    numericValue: 0.5,
    unit: "ratio",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: 1,
    evidence: SYNTHETIC_TOOL_END_IDS.slice(0, 1),
  }),
  syntheticResult({
    key: "task.data_quality.tool_duration_coverage",
    state: "known",
    numericValue: 0.5,
    unit: "ratio",
    observed: 1,
    eligible: 2,
    coverage: 0.5,
    confidence: 1,
    evidence: SYNTHETIC_TOOL_END_IDS.slice(0, 1),
  }),
  syntheticResult({
    key: "task.data_quality.unknown_event_kind_rate",
    state: "known",
    numericValue: 0.125,
    unit: "ratio",
    observed: 8,
    eligible: 8,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_EVENT_IDS,
  }),
  syntheticResult({
    key: "task.data_quality.direct_event_timestamp_rate",
    state: "known",
    numericValue: 0.75,
    unit: "ratio",
    observed: 8,
    eligible: 8,
    coverage: 1,
    confidence: 1,
    evidence: SYNTHETIC_EVENT_IDS,
  }),
];

const SYNTHETIC_QUALITY_DEFINITIONS = {
  "prompt.goal_definition": {
    dimension: "prompt",
    displayName: "Goal definition",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "prompt.constraint_resolution": {
    dimension: "prompt",
    displayName: "Constraint resolution",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "prompt.completion_evaluability": {
    dimension: "prompt",
    displayName: "Completion evaluability",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "prompt.deliverable_contract": {
    dimension: "prompt",
    displayName: "Deliverable contract",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "prompt.open_decision_load": {
    dimension: "prompt",
    displayName: "Open decision load",
    unit: "risk_ratio",
    direction: "lower_is_better",
  },
  "logic.requirement_action_traceability": {
    dimension: "logic",
    displayName: "Requirement-to-action traceability",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "logic.plan_state_accounting": {
    dimension: "logic",
    displayName: "Plan-state accounting",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "logic.decision_rationale_coverage": {
    dimension: "logic",
    displayName: "Decision-rationale coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  "logic.scoped_consistency_candidate_rate": {
    dimension: "logic",
    displayName: "Scoped consistency candidates",
    unit: "risk_ratio",
    direction: "lower_is_better",
  },
  "logic.conversation_loop_closure": {
    dimension: "logic",
    displayName: "Conversation-loop closure",
    unit: "ratio",
    direction: "higher_is_better",
  },
} as const;

type SyntheticQualityKey = keyof typeof SYNTHETIC_QUALITY_DEFINITIONS;

function syntheticQualityResult(input: {
  key: SyntheticQualityKey;
  valueState?: SessionAnalysisResult["value_state"];
  numerator?: number;
  denominator?: number;
  applicability?: SessionAnalysisResult["applicability"];
  observed?: number;
  eligible?: number;
  source?: SessionAnalysisResult["source"];
  explanationCode?: string;
  signals?: SessionAnalysisResult["signals"];
  model?: {
    id: string;
    revision: string;
    license: string;
    tokenizer: string;
  };
}): SessionAnalysisResult {
  const definition = SYNTHETIC_QUALITY_DEFINITIONS[input.key];
  const valueState = input.valueState ?? "known";
  const known = valueState === "known";
  const numerator = input.numerator ?? 1;
  const denominator = input.denominator ?? 1;
  const observed = input.observed ?? 8;
  const eligible = input.eligible ?? 10;
  return {
    key: input.key,
    version: 1,
    dimension: definition.dimension,
    display_name: definition.displayName,
    description: "Fictional, content-free synthetic metric definition.",
    metric_schema_version: 2,
    value_state: valueState,
    numeric_value: known ? numerator / denominator : null,
    unit: definition.unit,
    source: input.source ?? "deterministic",
    direction: definition.direction,
    applicability:
      input.applicability ??
      (valueState === "not_applicable" ? "not_applicable" : "applicable"),
    aggregation_method: "ratio_of_sums",
    fraction: known ? { numerator, denominator } : null,
    observed_count: observed,
    eligible_count: eligible,
    coverage: eligible === 0 ? 0 : observed / eligible,
    confidence: known ? 0.92 : null,
    evidence_data_tier: "redacted_content",
    evidence: known
      ? [{ message_id: pseudonym("b"), origin: "direct" }]
      : [],
    signals: input.signals ?? [],
    explanation_code:
      input.explanationCode ??
      (valueState === "known"
        ? "synthetic_fraction"
        : valueState === "not_applicable"
          ? "explicitly_not_applicable"
          : valueState === "abstained"
            ? "synthetic_abstention"
            : "synthetic_unknown"),
    error_code: null,
    algorithm_id: "synthetic.rules.en-pl",
    algorithm_version: "1",
    model_id: input.model?.id ?? null,
    model_revision: input.model?.revision ?? null,
    model_license: input.model?.license ?? null,
    tokenizer_id: input.model?.tokenizer ?? null,
    prompt_version: null,
    rubric_version: "synthetic-rubric-1",
    computed_at: "2040-01-03T09:13:00Z",
  };
}

const SYNTHETIC_EMBEDDING_MODEL = {
  id: "example-org/multilingual-embedding",
  revision: "example-pinned-1",
  license: "example-permissive-1",
  tokenizer: "example-org/multilingual-embedding",
};
const SYNTHETIC_NLI_MODEL = {
  id: "example-org/multilingual-nli",
  revision: "example-pinned-2",
  license: "example-permissive-1",
  tokenizer: "example-org/multilingual-nli",
};

export const SYNTHETIC_SESSION_QUALITY_RUN: SessionAnalysisRunResponse = {
  run: {
    run_id: pseudonym("6"),
    session_id: SYNTHETIC_QUALITY_SESSION_ID,
    request_fingerprint: pseudonym("7"),
    input_fingerprint: pseudonym("8"),
    analysis_profile_key: "standard_engineering",
    analysis_profile_version: 1,
    metric_pack_key: "core.redacted-text.prompt-logic",
    metric_pack_version: 1,
    metric_scope_state: "exact",
    selected_metric_keys: Object.keys(SYNTHETIC_QUALITY_DEFINITIONS).sort(),
    data_tier: "redacted_content",
    consent_purpose: "text_analysis",
    consent_policy_version: "synthetic-text-consent-1",
    provider: "synthetic",
    provider_version: "synthetic-provider-1",
    adapter_version: "synthetic-adapter-1",
    source_schema_version: "synthetic-schema-1",
    content_schema_version: "synthetic-redacted-window-1",
    metric_engine_version: "synthetic-quality-engine-1",
    redactor_version: "synthetic-redactor-1",
    model_plan_fingerprint: pseudonym("9"),
    schema_version: 9,
    local_only: true,
    started_at: "2040-01-03T09:12:58Z",
    status: "completed",
    finished_at: "2040-01-03T09:13:00Z",
    failure_code: null,
  },
  results: [
    syntheticQualityResult({
      key: "prompt.goal_definition",
      numerator: 3,
      denominator: 3,
      signals: [
        { code: "goal.action", status: "detected", count: 1 },
        { code: "goal.target", status: "detected", count: 1 },
        { code: "goal.outcome", status: "detected", count: 1 },
      ],
    }),
    syntheticQualityResult({
      key: "prompt.constraint_resolution",
      valueState: "abstained",
      explanationCode: "denominator_unknown",
      signals: [
        { code: "constraint.expected_categories", status: "unknown", count: null },
      ],
    }),
    syntheticQualityResult({
      key: "prompt.completion_evaluability",
      numerator: 1,
      denominator: 2,
      signals: [
        { code: "completion.requirements", status: "counted", count: 2 },
        { code: "completion.checkable", status: "counted", count: 1 },
      ],
    }),
    syntheticQualityResult({
      key: "prompt.deliverable_contract",
      valueState: "abstained",
      explanationCode: "denominator_unknown",
      signals: [
        { code: "deliverable.expected_slots", status: "unknown", count: null },
      ],
    }),
    syntheticQualityResult({
      key: "prompt.open_decision_load",
      numerator: 1,
      denominator: 5,
      signals: [
        { code: "choices.prompt_clauses", status: "counted", count: 5 },
        { code: "choices.marker_clauses", status: "counted", count: 1 },
      ],
    }),
    syntheticQualityResult({
      key: "logic.requirement_action_traceability",
      numerator: 4,
      denominator: 5,
      source: "estimated",
      model: SYNTHETIC_EMBEDDING_MODEL,
    }),
    syntheticQualityResult({
      key: "logic.plan_state_accounting",
      valueState: "unknown",
      explanationCode: "plan_items_unknown",
    }),
    syntheticQualityResult({
      key: "logic.decision_rationale_coverage",
      valueState: "unknown",
    }),
    syntheticQualityResult({
      key: "logic.scoped_consistency_candidate_rate",
      numerator: 1,
      denominator: 6,
      source: "estimated",
      model: SYNTHETIC_NLI_MODEL,
    }),
    syntheticQualityResult({
      key: "logic.conversation_loop_closure",
      valueState: "abstained",
    }),
  ],
};

export const SYNTHETIC_COACHING_METRIC_SPECS = [
  {
    key: "prompt.task_definition_coverage",
    version: 2,
    dimension: "prompt",
    displayName: "Task definition coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "prompt.problem_evidence_quality",
    version: 2,
    dimension: "prompt",
    displayName: "Problem evidence quality",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "prompt.context_sufficiency",
    version: 2,
    dimension: "prompt",
    displayName: "Context cue coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "prompt.constraint_precision",
    version: 2,
    dimension: "prompt",
    displayName: "Constraint precision candidates",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "prompt.acceptance_testability",
    version: 2,
    dimension: "prompt",
    displayName: "Acceptance testability cues",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "prompt.deliverable_contract",
    version: 3,
    dimension: "prompt",
    displayName: "Deliverable contract cues",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "collaboration.ambiguity_resolution",
    version: 2,
    dimension: "collaboration",
    displayName: "Ambiguity-resolution candidates",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "collaboration.clarification_yield",
    version: 2,
    dimension: "collaboration",
    displayName: "Clarification yield candidates",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "collaboration.exploration_conversion",
    version: 2,
    dimension: "collaboration",
    displayName: "Exploration-to-plan conversion",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "collaboration.scope_change_discipline",
    version: 2,
    dimension: "collaboration",
    displayName: "Scope-change acknowledgement",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "collaboration.rework_candidate_rate",
    version: 2,
    dimension: "collaboration",
    displayName: "Rework-candidate rate",
    unit: "risk_ratio",
    direction: "lower_is_better",
  },
  {
    key: "logic.decomposition_coverage",
    version: 2,
    dimension: "logic",
    displayName: "Requirement-to-plan coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "logic.hypothesis_test_linkage",
    version: 2,
    dimension: "logic",
    displayName: "Hypothesis-to-test linkage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "logic.decision_rationale_coverage",
    version: 3,
    dimension: "logic",
    displayName: "Decision-rationale coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "logic.requirement_action_traceability",
    version: 3,
    dimension: "logic",
    displayName: "Requirement-to-action traceability",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "logic.open_loop_closure",
    version: 2,
    dimension: "logic",
    displayName: "Open-loop closure candidates",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "outcome.agent_claim_grounding",
    version: 2,
    dimension: "outcome",
    displayName: "Agent claim grounding",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "outcome.verification_strategy_adequacy",
    version: 2,
    dimension: "outcome",
    displayName: "Verification-strategy coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "outcome.first_pass_verification",
    version: 2,
    dimension: "outcome",
    displayName: "First-pass verification",
    unit: "ratio",
    direction: "higher_is_better",
  },
  {
    key: "outcome.verified_requirement_coverage",
    version: 2,
    dimension: "outcome",
    displayName: "Verified requirement coverage",
    unit: "ratio",
    direction: "higher_is_better",
  },
] as const;

type SyntheticCoachingKey =
  (typeof SYNTHETIC_COACHING_METRIC_SPECS)[number]["key"];

const SYNTHETIC_COACHING_FRACTIONS: Readonly<
  Record<SyntheticCoachingKey, readonly [number, number]>
> = {
  "prompt.task_definition_coverage": [3, 3],
  "prompt.problem_evidence_quality": [4, 4],
  "prompt.context_sufficiency": [3, 3],
  "prompt.constraint_precision": [4, 5],
  "prompt.acceptance_testability": [4, 5],
  "prompt.deliverable_contract": [3, 4],
  "collaboration.ambiguity_resolution": [3, 4],
  "collaboration.clarification_yield": [3, 3],
  "collaboration.exploration_conversion": [2, 3],
  "collaboration.scope_change_discipline": [2, 2],
  "collaboration.rework_candidate_rate": [1, 5],
  "logic.decomposition_coverage": [4, 5],
  "logic.hypothesis_test_linkage": [2, 3],
  "logic.decision_rationale_coverage": [3, 4],
  "logic.requirement_action_traceability": [4, 5],
  "logic.open_loop_closure": [4, 5],
  "outcome.agent_claim_grounding": [4, 5],
  "outcome.verification_strategy_adequacy": [4, 5],
  "outcome.first_pass_verification": [1, 1],
  "outcome.verified_requirement_coverage": [4, 5],
};

function syntheticCoachingResult(
  definition: (typeof SYNTHETIC_COACHING_METRIC_SPECS)[number],
): SessionAnalysisResult {
  const [numerator, denominator] = SYNTHETIC_COACHING_FRACTIONS[definition.key];
  return {
    key: definition.key,
    version: definition.version,
    dimension: definition.dimension,
    display_name: definition.displayName,
    description:
      "Fictional current-pack observation with complete synthetic evidence.",
    metric_schema_version: 2,
    value_state: "known",
    numeric_value: numerator / denominator,
    unit: definition.unit,
    source: "deterministic",
    direction: definition.direction,
    applicability: "applicable",
    aggregation_method: "ratio_of_sums",
    fraction: { numerator, denominator },
    observed_count: 12,
    eligible_count: 12,
    coverage: 1,
    confidence: 1,
    evidence_data_tier: "redacted_content",
    evidence: [{ message_id: pseudonym("b"), origin: "direct" }],
    signals: [],
    explanation_code: "synthetic_complete_evidence",
    error_code: null,
    algorithm_id: "synthetic.rules.coaching",
    algorithm_version: "3",
    model_id: null,
    model_revision: null,
    model_license: null,
    tokenizer_id: null,
    prompt_version: null,
    rubric_version: "coaching-observables-rubric-2",
    computed_at: "2040-01-03T09:13:00Z",
  };
}

export const SYNTHETIC_CURRENT_SESSION_QUALITY_RUN: SessionAnalysisRunResponse = {
  run: {
    run_id: pseudonym("1"),
    session_id: SYNTHETIC_QUALITY_SESSION_ID,
    request_fingerprint: pseudonym("2"),
    input_fingerprint: pseudonym("3"),
    analysis_profile_key: "coaching_profile",
    analysis_profile_version: 1,
    metric_pack_key: "experimental.redacted-text.coaching",
    metric_pack_version: 3,
    metric_scope_state: "exact",
    selected_metric_keys: SYNTHETIC_COACHING_METRIC_SPECS
      .map((definition) => definition.key)
      .sort(),
    data_tier: "redacted_content",
    consent_purpose: "text_analysis",
    consent_policy_version: "synthetic-text-consent-1",
    provider: "synthetic",
    provider_version: "synthetic-provider-1",
    adapter_version: "synthetic-adapter-1",
    source_schema_version: "synthetic-schema-1",
    content_schema_version: "synthetic-redacted-window-1",
    metric_engine_version: "synthetic-coaching-engine-3",
    redactor_version: "synthetic-redactor-1",
    model_plan_fingerprint: pseudonym("4"),
    schema_version: 9,
    local_only: true,
    started_at: "2040-01-03T09:12:58Z",
    status: "completed",
    finished_at: "2040-01-03T09:13:00Z",
    failure_code: null,
  },
  results: SYNTHETIC_COACHING_METRIC_SPECS.map(syntheticCoachingResult),
};

const SYNTHETIC_EVIDENCE_CAPABILITIES: MetricEvidenceCapability[] = [
  "request_text",
  "response_text",
  "plan_text",
  "action_evidence",
  "decision_evidence",
  "feedback_text",
  "objective_verification",
];
const SYNTHETIC_REQUEST_OR_FEEDBACK: MetricEvidenceCapability[] = [
  "feedback_text",
  "request_text",
];
const SYNTHETIC_COACHING_CAPABILITY_GROUPS: Record<
  SyntheticCoachingKey,
  MetricEvidenceCapability[][]
> = {
  "prompt.task_definition_coverage": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "prompt.problem_evidence_quality": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "prompt.context_sufficiency": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "prompt.constraint_precision": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "prompt.acceptance_testability": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "prompt.deliverable_contract": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "collaboration.ambiguity_resolution": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "collaboration.clarification_yield": [
    ["response_text"],
    SYNTHETIC_REQUEST_OR_FEEDBACK,
  ],
  "collaboration.exploration_conversion": [
    ["plan_text", "request_text", "response_text"],
  ],
  "collaboration.scope_change_discipline": [SYNTHETIC_REQUEST_OR_FEEDBACK],
  "collaboration.rework_candidate_rate": [
    ["response_text"],
    ["feedback_text"],
  ],
  "logic.decomposition_coverage": [
    SYNTHETIC_REQUEST_OR_FEEDBACK,
    ["plan_text"],
  ],
  "logic.hypothesis_test_linkage": [["objective_verification"]],
  "logic.decision_rationale_coverage": [["decision_evidence"]],
  "logic.requirement_action_traceability": [
    SYNTHETIC_REQUEST_OR_FEEDBACK,
    ["action_evidence"],
  ],
  "logic.open_loop_closure": [
    ["feedback_text", "request_text", "response_text"],
  ],
  "outcome.agent_claim_grounding": [
    ["response_text"],
    ["objective_verification"],
  ],
  "outcome.verification_strategy_adequacy": [
    SYNTHETIC_REQUEST_OR_FEEDBACK,
    ["objective_verification", "plan_text", "response_text"],
  ],
  "outcome.first_pass_verification": [["objective_verification"]],
  "outcome.verified_requirement_coverage": [
    SYNTHETIC_REQUEST_OR_FEEDBACK,
    ["objective_verification"],
  ],
};

export const SYNTHETIC_PROVIDER_METRIC_CAPABILITIES: ProviderCapabilityReport = {
  provider: "synthetic",
  surface: "text_window",
  catalog_version: "coaching-evidence-capabilities-v1",
  compatibility_state: "exact",
  provider_version: "synthetic-provider-1",
  decoder_key: "synthetic.fixture.coaching",
  decoder_version: "1",
  checked_at: "2040-01-03T09:12:57Z",
  capabilities: SYNTHETIC_EVIDENCE_CAPABILITIES.map((capability) => ({
    capability,
    state: "supported",
    reason_code: "verified_by_compatible_decoder",
  })),
  structurally_attemptable_metric_count: SYNTHETIC_COACHING_METRIC_SPECS.length,
  structurally_unsupported_metric_count: 0,
  structurally_unknown_metric_count: 0,
};

export const SYNTHETIC_SESSION_METRIC_READINESS: SessionMetricReadinessReport = {
  session_id: SYNTHETIC_QUALITY_SESSION_ID,
  provider: "synthetic",
  preset_id: "coaching_profile_v1",
  analysis_profile_key: "coaching_profile",
  analysis_profile_version: 1,
  metric_pack_key: "experimental.redacted-text.coaching",
  metric_pack_version: 3,
  capability_report: SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
  metrics: SYNTHETIC_COACHING_METRIC_SPECS.map((definition) => ({
    metric_key: definition.key,
    metric_version: definition.version,
    dimension: definition.dimension,
    display_name: definition.displayName,
    unit: definition.unit,
    direction: definition.direction,
    radar_policy: definition.direction === "higher_is_better"
      ? "direct_bounded_ratio"
      : "exact_value_only_unnormalized_lower_is_better",
    evidence_tier: "redacted_content",
    state: "known",
    reason_code: "measured",
    next_actions: ["none"],
    capability_groups: SYNTHETIC_COACHING_CAPABILITY_GROUPS[definition.key],
    available_capabilities: [
      ...new Set(SYNTHETIC_COACHING_CAPABILITY_GROUPS[definition.key].flat()),
    ].sort(),
    missing_capabilities: [],
    latest_run_id: SYNTHETIC_CURRENT_SESSION_QUALITY_RUN.run.run_id,
  })),
};

export const SYNTHETIC_METRIC_COVERAGE: MetricCoverageReport = {
  contract_version: "metric-coverage-report-v1",
  scope: "provider_catalog",
  provider: "synthetic",
  generated_at: "2040-01-03T09:13:00Z",
  analysis_profile_key: "coaching_profile",
  analysis_profile_version: 1,
  metric_pack_key: "experimental.redacted-text.coaching",
  metric_pack_version: 3,
  metric_catalog_version: "coaching-evidence-capabilities-v1",
  indexed_project_count: 1,
  indexed_session_count: 1,
  latest_profile_runs: {
    completed: 1,
    running: 0,
    failed: 0,
    never_run: 0,
  },
  latest_completed_snapshot_count: 1,
  effective_automation_grant_count: 0,
  effective_automation_project_count: 0,
  unrecognized_result_record_count: 0,
  automation_scheduling_scope: "new_or_changed_newest_bounded",
  metrics: SYNTHETIC_COACHING_METRIC_SPECS.map((definition) => ({
    metric_key: definition.key,
    metric_version: definition.version,
    dimension: definition.dimension,
    display_name: definition.displayName,
    structural_support: "attemptable" as const,
    required_evidence: SYNTHETIC_COACHING_CAPABILITY_GROUPS[definition.key],
    latest_completed_run_count: 1,
    selected_run_count: 1,
    not_selected_run_count: 0,
    unknown_scope_run_count: 0,
    completed_selected_run_count: 1,
    contract_compatible_result_states: {
      known: 1,
      unknown: 0,
      not_applicable: 0,
      abstained: 0,
      execution_error: 0,
    },
    contract_incompatible_result_count: 0,
    expected_result_absent_count: 0,
    compatible_provenance_cohort_count: 1,
    effective_automation_selected_project_count: 0,
  })),
  capability_report: SYNTHETIC_PROVIDER_METRIC_CAPABILITIES,
  local_index_snapshot_exact: true,
  provider_history_completeness: "unknown",
  provider_snapshot_authority: "unavailable",
  stored_result_contract_validation_performed: true,
  provider_capability_snapshot_atomic: false,
  full_catalog_automation_coverage_guaranteed: false,
  metric_values_included: false,
  product_source_authority: false,
  population_completeness_verified: false,
  comparison_authority: false,
  snapshot_materialization_allowed: false,
  recommendation_authority: false,
};

const SYNTHETIC_COACHING_DECISION_COMMON = {
  algorithm_id: "rules.coaching-loop.summary",
  algorithm_version: "1",
  candidate_policy_version: 2,
  confidence: null,
  construct_version: 1,
  coverage: 1,
  decision_state: "candidate" as const,
  denominator: 5,
  denominator_kind: "event_count" as const,
  denominator_kind_priority_version: 1,
  evidence_lower_bound: 0.8,
  evidence_upper_bound: 1,
  evidence_basis: ["rule.factor_counts" as const],
  evidence_kind: "deterministic_candidate" as const,
  evidence_tier: "redacted_content" as const,
  pack_key: "coaching.loop",
  pack_version: 1,
  polarity_successes: 4,
  recommendation_policy_version: 1,
  rule_priority_version: 1,
  source_provenance: {
    algorithm_id: "synthetic.rules.coaching",
    algorithm_version: "3",
    pack_key: "experimental.redacted-text.coaching",
    pack_version: 3,
  },
  task_type: "implementation" as const,
  abstention_code: null,
};

const SYNTHETIC_REWORK_FRICTION = {
  ...SYNTHETIC_COACHING_DECISION_COMMON,
  code: "friction.rework_signal_high",
  evidence_lower_bound: 0,
  evidence_upper_bound: 0.2,
  polarity_successes: 1,
  evidence_basis: ["rule.correction_counts" as const],
  metric_basis: ["collaboration.rework_candidate_rate.v2"],
};

export const SYNTHETIC_COACHING_PROJECTION: SessionCoachingProjection = {
  projection_key: "coaching.loop.current",
  projection_version: 1,
  task_context_source: "reviewed_task",
  task_type: "implementation",
  summary: {
    outcome: {
      ...SYNTHETIC_COACHING_DECISION_COMMON,
      code: "outcome.verified",
      decision_state: "supported",
      denominator: 5,
      evidence_basis: ["objective.verification_results"],
      evidence_disagreement: false,
      evidence_kind: "objective_verification",
      evidence_lower_bound: 0.8,
      evidence_tier: "objective_event",
      evidence_upper_bound: 0.8,
      human_acceptance_status: "unknown",
      metric_basis: ["outcome.verified_requirement_coverage.v2"],
      polarity_successes: 4,
      status: "verified",
    },
    strength: {
      ...SYNTHETIC_COACHING_DECISION_COMMON,
      code: "strength.testable_acceptance",
      metric_basis: ["prompt.acceptance_testability.v2"],
    },
    friction: SYNTHETIC_REWORK_FRICTION,
    next_experiment: {
      ...SYNTHETIC_REWORK_FRICTION,
      code: "experiment.confirm_contract_before_execution",
    },
    prompt_template: {
      ...SYNTHETIC_REWORK_FRICTION,
      code: "prompt_template.preflight_contract",
      slot_codes: ["goal", "scope", "acceptance", "confirmation"],
      template_version: 1,
    },
  },
};
