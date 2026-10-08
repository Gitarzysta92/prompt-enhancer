import type {
  ProjectQualityMetricAggregate,
  ProjectSessionQualityAggregate,
  SessionAnalysisResult,
  SessionAnalysisRun,
  SessionAnalysisRunResponse,
  SessionQualityAggregate,
  SessionQualityCompatibilityKey,
  SessionQualityMetricAggregate,
} from "../../shared/api/contracts";
import type { MetricCategory } from "../../shared/platform/platform";

export type QualityProfileKind = "prompt" | "logic";
export type QualitySnapshotKind = "initial" | "latest";
export type QualitySnapshotLabel =
  | "Initial request"
  | "Latest analysis window"
  | "First observed state"
  | "Current observed state";
export type QualitySnapshotIntegrity =
  | "coherent"
  | "unavailable"
  | "stale-pack"
  | "mixed-provenance"
  | "invalid-contract";
export type QualityMetricPolarity = "capability" | "review-load";
export type QualityMetricState =
  | "observed"
  | "partial"
  | "not-selected"
  | "incompatible"
  | "unavailable"
  | "abstained"
  | "not-applicable"
  | "execution-error";
export type QualityMetricErrorCode =
  | "metric-not-implemented"
  | "metric-not-selected"
  | "metric-scope-unknown"
  | "incompatible-provenance"
  | "insufficient-evidence"
  | "analysis-abstained"
  | "calculation-failed"
  | "invalid-contract";

export interface QualityMetricDefinition {
  key: string;
  version: 1 | 2 | 3;
  kind: QualityProfileKind;
  dimension: "prompt" | "collaboration" | "logic" | "outcome";
  unit: "ratio" | "risk_ratio";
  direction: "higher_is_better" | "lower_is_better";
  shortLabel: string;
  label: string;
  question: string;
  method: string;
  limitation: string;
  polarity: QualityMetricPolarity;
}

export interface QualityMetricObservation {
  definition: QualityMetricDefinition;
  state: QualityMetricState;
  ratio: number | null;
  fractionNumerator: number | null;
  fractionDenominator: number | null;
  observed: number;
  eligible: number;
  /** Completed runs that explicitly omitted this metric from their exact scope. */
  notSelectedRuns: number;
  /** Completed legacy runs whose selected metric scope cannot be recovered. */
  unknownScopeRuns: number;
  coverage: number;
  confidence: number | null;
  signals: readonly QualityMetricSignal[];
  metricSchemaVersion: number | null;
  explanationCode: string | null;
  algorithmId: string | null;
  algorithmVersion: string | null;
  modelId: string | null;
  errorCode: QualityMetricErrorCode | null;
  definitionVersion: number | null;
  computedAt: string | null;
}

export interface QualityMetricSignal {
  code: string;
  status: "detected" | "missing" | "counted" | "unknown";
  count: number | null;
}

export interface QualityProfileSnapshot {
  kind: QualitySnapshotKind;
  metrics: readonly QualityMetricObservation[];
  integrity: QualitySnapshotIntegrity;
  metricPackVersion: number | null;
  scope: {
    selectedSessions: number;
    completedRuns: number;
    missingRuns: number;
  } | null;
}

export interface QualityMetricProfile {
  kind: QualityProfileKind;
  title: string;
  eyebrow: string;
  question: string;
  summary: string;
  initialLabel: QualitySnapshotLabel;
  latestLabel: QualitySnapshotLabel;
  initial: QualityProfileSnapshot;
  latest: QualityProfileSnapshot;
  analysisProfile:
    | { state: "standard"; label: "Standard engineering v1" }
    | { state: "coaching"; label: "Coaching profile v1" }
    | { state: "legacy-or-unknown"; label: "Legacy / unknown analysis profile" }
    | null;
}

const LEGACY_PROMPT_DEFINITIONS: readonly QualityMetricDefinition[] = [
  {
    key: "prompt.goal_definition",
    version: 1,
    kind: "prompt",
    dimension: "prompt",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Goal cues",
    label: "Goal cue coverage",
    question: "Were action, possible target, and purpose cues detected in the user-text window?",
    method: "Detected action, target-after-action, and purpose-connector cues divided by three fixed slots.",
    limitation: "Cue presence is not proof that the goal is clear, coherent, correct, or valuable.",
    polarity: "capability",
  },
  {
    key: "prompt.constraint_resolution",
    version: 1,
    kind: "prompt",
    dimension: "prompt",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Constraints",
    label: "Expected constraint cues",
    question: "Could the preset establish which constraint categories should be checked?",
    method: "Detected expected constraint-category cues divided by task-profile categories.",
    limitation: "Standard engineering v1 has no task-specific constraint denominator, so this is normally not measurable.",
    polarity: "capability",
  },
  {
    key: "prompt.completion_evaluability",
    version: 1,
    kind: "prompt",
    dimension: "prompt",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Done",
    label: "Checkability cue coverage",
    question: "How many detected requirement clauses contain an observable-check cue?",
    method: "Requirement clauses with test, threshold, comparison, visibility, or verification markers divided by detected requirement clauses.",
    limitation: "A check word is not proof of a complete or correct acceptance criterion.",
    polarity: "capability",
  },
  {
    key: "prompt.deliverable_contract",
    version: 1,
    kind: "prompt",
    dimension: "prompt",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Output cues",
    label: "Expected output-detail cues",
    question: "Could the preset establish which output details should be checked?",
    method: "Detected expected output-detail cues divided by task-profile slots.",
    limitation: "Standard engineering v1 has no task-specific output denominator, so this is normally not measurable.",
    polarity: "capability",
  },
  {
    key: "prompt.open_decision_load",
    version: 1,
    kind: "prompt",
    dimension: "prompt",
    unit: "risk_ratio",
    direction: "lower_is_better",
    shortLabel: "Choice cues",
    label: "Choice-marker density",
    question: "What share of user clauses contains a recognized unresolved-choice marker?",
    method: "Clauses with choose, which, whether, maybe, or similar EN/PL markers divided by all analyzed user clauses; narrow deliberate-delegation phrases are excluded.",
    limitation: "This lexical baseline does not establish materiality or whether a choice was resolved later. Lower is better only as a review cue.",
    polarity: "review-load",
  },
] as const;

const LEGACY_LOGIC_DEFINITIONS: readonly QualityMetricDefinition[] = [
  {
    key: "logic.requirement_action_traceability",
    version: 1,
    kind: "logic",
    dimension: "logic",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Trace",
    label: "Requirement-to-action traceability",
    question: "Did every active requirement lead to observable work?",
    method: "Active requirements linked to actions divided by eligible requirements.",
    limitation: "A semantic link does not prove correct implementation.",
    polarity: "capability",
  },
  {
    key: "logic.plan_state_accounting",
    version: 1,
    kind: "logic",
    dimension: "logic",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Plan",
    label: "Plan-state accounting",
    question: "Did explicit plan items become action-linked, revised, blocked, or deferred?",
    method: "State-accounted plan items divided by eligible explicit plan items.",
    limitation: "No explicit plan for a simple task should be not applicable, not zero.",
    polarity: "capability",
  },
  {
    key: "logic.decision_rationale_coverage",
    version: 1,
    kind: "logic",
    dimension: "logic",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Decisions",
    label: "Decision-rationale coverage",
    question: "Are material decisions linked to constraints, alternatives, or evidence?",
    method: "Material decisions with observable rationale divided by eligible decisions.",
    limitation: "This evaluates recorded rationale, never hidden chain-of-thought.",
    polarity: "capability",
  },
  {
    key: "logic.scoped_consistency_candidate_rate",
    version: 1,
    kind: "logic",
    dimension: "logic",
    unit: "risk_ratio",
    direction: "lower_is_better",
    shortLabel: "Conflicts",
    label: "Scoped consistency candidates",
    question: "What share of comparable claims needs contradiction review?",
    method: "Typed contradiction candidates divided by comparable claims.",
    limitation: "Candidates require review; they are not confirmed defects.",
    polarity: "review-load",
  },
  {
    key: "logic.conversation_loop_closure",
    version: 1,
    kind: "logic",
    dimension: "logic",
    unit: "ratio",
    direction: "higher_is_better",
    shortLabel: "Closure",
    label: "Conversation-loop closure",
    question: "Were actionable questions and clarification requests closed?",
    method: "Closed actionable loops divided by eligible conversation loops.",
    limitation: "A linked answer is not evidence that the answer was correct.",
    polarity: "capability",
  },
] as const;

const LEGACY_QUALITY_ANALYSIS_DEFINITIONS = [
  ...LEGACY_PROMPT_DEFINITIONS,
  ...LEGACY_LOGIC_DEFINITIONS,
] as const;

const COACHING_PROMPT_DEFINITIONS: readonly QualityMetricDefinition[] = [
  {
    key: "prompt.task_definition_coverage", version: 2, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Task", label: "Task definition coverage",
    question: "Did the focus request contain separate action, target, and intended-outcome cues?",
    method: "Three non-overlapping EN/PL cue checks on the focus request only: action, target, and intended outcome.",
    limitation: "Cue presence does not prove that the task is correct, wise, or unambiguous.", polarity: "capability",
  },
  {
    key: "prompt.problem_evidence_quality", version: 2, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Evidence", label: "Problem evidence quality",
    question: "For a diagnosis task, were observed behavior, expected behavior, reproduction, and environment described?",
    method: "Four cue checks, produced only when a bug or diagnosis candidate is detected.",
    limitation: "Lexical evidence cues do not establish that the diagnosis is accurate.", polarity: "capability",
  },
  {
    key: "prompt.context_sufficiency", version: 2, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Context", label: "Context cue checks",
    question: "Did the focus request identify current state, environment or version, and an important boundary?",
    method: "Three non-overlapping context-cue checks on the focus request only.",
    limitation: "Lexical cue presence is not proof that the supplied context is sufficient or correct.", polarity: "capability",
  },
  {
    key: "prompt.constraint_precision", version: 2, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Constraints", label: "Constraint precision candidates",
    question: "How many detected constraints contain a concrete boundary, value, platform, version, or prohibition?",
    method: "Concrete constraint candidates divided by detected constraint clauses.",
    limitation: "Unknown task-specific constraints stay Unknown; absent constraints are never scored as zero.", polarity: "capability",
  },
  {
    key: "prompt.acceptance_testability", version: 2, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Checkability", label: "Acceptance testability cues",
    question: "How many detected requirements include an observable pass condition?",
    method: "Requirements with check, threshold, comparison, or explicit pass cues divided by detected requirements.",
    limitation: "A test word is not proof of a complete or correct acceptance criterion.", polarity: "capability",
  },
  {
    key: "prompt.deliverable_contract", version: 3, kind: "prompt", dimension: "prompt",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Deliverable", label: "Deliverable contract cues",
    question: "How many requested deliverables include a format, interface, location, audience, or compatibility detail?",
    method: "Detailed deliverable clauses divided by detected deliverable clauses.",
    limitation: "The v3 candidate avoids inventing a universal output-slot denominator.", polarity: "capability",
  },
  {
    key: "collaboration.ambiguity_resolution", version: 2, kind: "prompt", dimension: "collaboration",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Ambiguity", label: "Ambiguity-resolution candidates",
    question: "Were detected vague or unresolved references followed by a related clarification?",
    method: "Related clarification or explicit replacement candidates divided by ambiguity-marker clauses.",
    limitation: "Markers are review candidates; the rule does not judge semantic materiality.", polarity: "capability",
  },
  {
    key: "collaboration.clarification_yield", version: 2, kind: "prompt", dimension: "collaboration",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Clarify", label: "Clarification yield candidates",
    question: "Did agent questions produce a related, substantive user answer?",
    method: "Agent questions with a later related answer containing concrete task information divided by agent questions.",
    limitation: "Question frequency alone is not quality; this is an uncalibrated linkage candidate.", polarity: "capability",
  },
  {
    key: "collaboration.exploration_conversion", version: 2, kind: "prompt", dimension: "collaboration",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Explore", label: "Exploration-to-plan conversion",
    question: "Did observable hypotheses or theorizing converge into a related plan or evidence step?",
    method: "Hypothesis-marker clauses with a later related plan, decision, action, or verification item divided by hypotheses.",
    limitation: "There is no universal ideal amount of exploration; research tasks need task-type context.", polarity: "capability",
  },
  {
    key: "collaboration.scope_change_discipline", version: 2, kind: "prompt", dimension: "collaboration",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Scope", label: "Scope-change acknowledgement",
    question: "Were explicit scope changes acknowledged in a related response or revised plan?",
    method: "Acknowledged change candidates divided by explicit user scope-change clauses.",
    limitation: "Intentional iteration is not failure; absence of a change yields Unknown.", polarity: "capability",
  },
  {
    key: "collaboration.rework_candidate_rate", version: 2, kind: "prompt", dimension: "collaboration",
    unit: "risk_ratio", direction: "lower_is_better", shortLabel: "Rework", label: "Rework-candidate rate",
    question: "What share of user feedback contains correction or misunderstanding markers?",
    method: "Correction-marker feedback clauses divided by user feedback clauses following an agent response.",
    limitation: "New information and healthy iteration can look like rework; treat every hit as a review candidate.", polarity: "review-load",
  },
] as const;

const COACHING_LOGIC_DEFINITIONS: readonly QualityMetricDefinition[] = [
  {
    key: "logic.decomposition_coverage", version: 2, kind: "logic", dimension: "logic",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Decompose", label: "Requirement-to-plan coverage",
    question: "Could each detected requirement be linked to an explicit plan item?",
    method: "Requirements with conservative lexical plan links divided by detected requirements.",
    limitation: "A lexical link is a candidate and does not prove that the plan is adequate.", polarity: "capability",
  },
  {
    key: "logic.hypothesis_test_linkage", version: 2, kind: "logic", dimension: "logic",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Hypothesis", label: "Hypothesis-to-test linkage",
    question: "Was each technical hypothesis followed by a discriminating structured check?",
    method: "Requires typed verification evidence; text alone deliberately abstains.",
    limitation: "Chronological proximity and an agent saying it tested something are not proof.", polarity: "capability",
  },
  {
    key: "logic.decision_rationale_coverage", version: 3, kind: "logic", dimension: "logic",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Decisions", label: "Decision-rationale coverage",
    question: "Were observable decisions connected to a rationale, alternative, constraint, or evidence?",
    method: "Rationale-bearing structured decision items divided by structured decisions.",
    limitation: "The Codex text projection does not currently expose decision items, so it normally abstains.", polarity: "capability",
  },
  {
    key: "logic.requirement_action_traceability", version: 3, kind: "logic", dimension: "logic",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Trace", label: "Requirement-to-action traceability",
    question: "Could every active requirement be linked to structured implementation work?",
    method: "Requirements with structured action links divided by detected requirements.",
    limitation: "Generic agent response text is never reclassified as an action.", polarity: "capability",
  },
  {
    key: "logic.open_loop_closure", version: 2, kind: "logic", dimension: "logic",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Closure", label: "Open-loop closure candidates",
    question: "Were detected questions followed by a related opposite-role response and not reopened?",
    method: "Closed question-response candidates divided by detected questions.",
    limitation: "A linked response does not establish that the answer is correct.", polarity: "capability",
  },
  {
    key: "outcome.agent_claim_grounding", version: 2, kind: "logic", dimension: "outcome",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Grounding", label: "Agent claim grounding",
    question: "Are material completion claims backed by objective evidence?",
    method: "Requires typed tool, test, source, or artifact evidence; response prose alone abstains.",
    limitation: "An assistant completion claim is never proof of delivery.", polarity: "capability",
  },
  {
    key: "outcome.verification_strategy_adequacy", version: 2, kind: "logic", dimension: "outcome",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Strategy", label: "Verification-strategy coverage",
    question: "Did each detected requirement receive a related planned check?",
    method: "Requirements linked to a later plan or response containing a check cue divided by requirements.",
    limitation: "This measures stated verification strategy, not whether checks ran or passed.", polarity: "capability",
  },
  {
    key: "outcome.first_pass_verification", version: 2, kind: "logic", dimension: "outcome",
    unit: "ratio", direction: "higher_is_better", shortLabel: "First pass", label: "First-pass verification",
    question: "Did the first meaningful executable verification episode pass?",
    method: "Requires ordered structured verification outcomes and task eligibility; text analysis abstains.",
    limitation: "Retries cannot improve this metric, and missing checks never become failure.", polarity: "capability",
  },
  {
    key: "outcome.verified_requirement_coverage", version: 2, kind: "logic", dimension: "outcome",
    unit: "ratio", direction: "higher_is_better", shortLabel: "Verified", label: "Verified requirement coverage",
    question: "How many active requirements have objective passing evidence or explicit acceptance?",
    method: "Requires typed requirement-to-verification or acceptance links; text analysis abstains.",
    limitation: "It remains Unknown until objective evidence is available and linked.", polarity: "capability",
  },
] as const;

export const QUALITY_ANALYSIS_DEFINITIONS = [
  ...COACHING_PROMPT_DEFINITIONS,
  ...COACHING_LOGIC_DEFINITIONS,
] as const;

export const QUALITY_ANALYSIS_METRIC_KEYS = QUALITY_ANALYSIS_DEFINITIONS.map(
  (definition) => definition.key,
);

const DEFINITIONS_BY_KEY = new Map(
  QUALITY_ANALYSIS_DEFINITIONS.map((definition) => [definition.key, definition]),
);
const PSEUDONYM = /^[a-f0-9]{64}$/;
const SAFE_VERSION = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const SAFE_LABEL = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const EPSILON = 1e-9;
const COACHING_PACK_KEY = "experimental.redacted-text.coaching";
const COACHING_PACK_VERSION = 3;
const LEGACY_PACK_KEY = "core.redacted-text.prompt-logic";
const LEGACY_PACK_VERSION = 1;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRequiredSafeVersion(value: unknown): value is string {
  return typeof value === "string" && SAFE_VERSION.test(value);
}

function isNullableSafeVersion(value: unknown): value is string | null {
  return value === null || isRequiredSafeVersion(value);
}

function isRequiredSafeLabel(value: unknown): value is string {
  return typeof value === "string" && SAFE_LABEL.test(value);
}

function isRequiredDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    !Number.isNaN(new Date(value).valueOf())
  );
}

function profileKind(category: MetricCategory): QualityProfileKind | null {
  if (category === "prompt-quality") return "prompt";
  if (category === "reasoning") return "logic";
  return null;
}

function definitionsFor(kind: QualityProfileKind): readonly QualityMetricDefinition[] {
  return kind === "prompt"
    ? COACHING_PROMPT_DEFINITIONS
    : COACHING_LOGIC_DEFINITIONS;
}

function definitionsForRun(
  kind: QualityProfileKind,
  response: SessionAnalysisRunResponse | null,
): readonly QualityMetricDefinition[] {
  if (
    response?.run?.metric_pack_key === LEGACY_PACK_KEY &&
    response.run.metric_pack_version === LEGACY_PACK_VERSION
  ) {
    return kind === "prompt"
      ? LEGACY_PROMPT_DEFINITIONS
      : LEGACY_LOGIC_DEFINITIONS;
  }
  return definitionsFor(kind);
}

function definitionsForAggregate(
  kind: QualityProfileKind,
  aggregate: SessionQualityAggregate | ProjectSessionQualityAggregate | null,
): readonly QualityMetricDefinition[] {
  if (!aggregate || !Array.isArray(aggregate.metrics)) {
    return definitionsFor(kind);
  }
  if (
    aggregate.analysis_profile_key === "standard_engineering" &&
    aggregate.analysis_profile_version === 1 &&
    aggregate.metric_pack_key === LEGACY_PACK_KEY &&
    aggregate.metric_pack_version === LEGACY_PACK_VERSION
  ) {
    return kind === "prompt"
      ? LEGACY_PROMPT_DEFINITIONS
      : LEGACY_LOGIC_DEFINITIONS;
  }
  return definitionsFor(kind);
}

function unavailableObservation(
  definition: QualityMetricDefinition,
): QualityMetricObservation {
  return {
    definition,
    state: "unavailable",
    ratio: null,
    fractionNumerator: null,
    fractionDenominator: null,
    observed: 0,
    eligible: 0,
    notSelectedRuns: 0,
    unknownScopeRuns: 0,
    coverage: 0,
    confidence: null,
    signals: [],
    metricSchemaVersion: null,
    explanationCode: null,
    algorithmId: null,
    algorithmVersion: null,
    modelId: null,
    errorCode: "metric-not-implemented",
    definitionVersion: null,
    computedAt: null,
  };
}

function notSelectedObservation(
  definition: QualityMetricDefinition,
  notSelectedRuns = 1,
): QualityMetricObservation {
  return {
    ...unavailableObservation(definition),
    state: "not-selected",
    notSelectedRuns,
    errorCode: "metric-not-selected",
  };
}

function scopeUnknownObservation(
  definition: QualityMetricDefinition,
  unknownScopeRuns = 1,
): QualityMetricObservation {
  return {
    ...unavailableObservation(definition),
    unknownScopeRuns,
    errorCode: "metric-scope-unknown",
  };
}

function invalidObservation(
  definition: QualityMetricDefinition,
): QualityMetricObservation {
  return {
    ...unavailableObservation(definition),
    state: "execution-error",
    errorCode: "invalid-contract",
  };
}

function incompatibleObservation(
  definition: QualityMetricDefinition,
  notSelectedRuns: number,
): QualityMetricObservation {
  return {
    ...unavailableObservation(definition),
    state: "incompatible",
    notSelectedRuns,
    errorCode: "incompatible-provenance",
    definitionVersion: definition.version,
  };
}

function isCompletedRun(
  run: SessionAnalysisRun,
  metricPackKey: string,
  metricPackVersion: number,
  expectedSessionId?: string,
): boolean {
  const positiveInteger = (value: number) =>
    Number.isSafeInteger(value) && value > 0;
  const metricScopeValid = (() => {
    if (
      !Array.isArray(run.selected_metric_keys) ||
      run.selected_metric_keys.length > 100 ||
      run.selected_metric_keys.some((key) => !isRequiredSafeVersion(key))
    ) {
      return false;
    }
    const canonical = [...run.selected_metric_keys].sort();
    if (
      new Set(run.selected_metric_keys).size !== run.selected_metric_keys.length ||
      canonical.some((key, index) => key !== run.selected_metric_keys[index])
    ) {
      return false;
    }
    return run.metric_scope_state === "exact"
      ? run.selected_metric_keys.length > 0
      : run.metric_scope_state === "legacy_unknown" &&
          run.selected_metric_keys.length === 0;
  })();
  return (
    PSEUDONYM.test(run.run_id) &&
    PSEUDONYM.test(run.session_id) &&
    (expectedSessionId === undefined || run.session_id === expectedSessionId) &&
    PSEUDONYM.test(run.request_fingerprint) &&
    PSEUDONYM.test(run.input_fingerprint) &&
    PSEUDONYM.test(run.model_plan_fingerprint) &&
    run.metric_pack_key === metricPackKey &&
    run.metric_pack_version === metricPackVersion &&
    run.data_tier === "redacted_content" &&
    run.consent_purpose === "text_analysis" &&
    run.local_only === true &&
    run.status === "completed" &&
    ["codex", "claude_code", "synthetic"].includes(run.provider) &&
    run.failure_code === null &&
    metricScopeValid &&
    isRequiredDate(run.started_at) &&
    isRequiredDate(run.finished_at) &&
    positiveInteger(run.schema_version) &&
    [
      run.consent_policy_version,
      run.provider_version,
      run.adapter_version,
      run.source_schema_version,
      run.content_schema_version,
      run.metric_engine_version,
      run.redactor_version,
    ].every(isRequiredSafeVersion)
  );
}

function validModelTuple(result: SessionAnalysisResult): boolean {
  const fields = [
    result.model_id,
    result.model_revision,
    result.model_license,
    result.tokenizer_id,
  ];
  const present = fields.filter((value) => value !== null).length;
  return (
    (present === 0 || present === fields.length) &&
    fields.every(isNullableSafeVersion) &&
    isNullableSafeVersion(result.prompt_version) &&
    isNullableSafeVersion(result.rubric_version)
  );
}

function validObservationCoverage(result: SessionAnalysisResult): boolean {
  const countsValid =
    Number.isSafeInteger(result.observed_count) &&
    Number.isSafeInteger(result.eligible_count) &&
    result.observed_count >= 0 &&
    result.eligible_count >= 0 &&
    result.observed_count <= result.eligible_count;
  if (!countsValid || !Number.isFinite(result.coverage)) return false;
  const expected =
    result.eligible_count === 0
      ? 0
      : result.observed_count / result.eligible_count;
  return (
    result.coverage >= 0 &&
    result.coverage <= 1 &&
    Math.abs(result.coverage - expected) <= EPSILON
  );
}

function validEvidence(result: SessionAnalysisResult): boolean {
  if (
    result.evidence_data_tier !== "redacted_content" ||
    !Array.isArray(result.evidence)
  ) {
    return false;
  }
  const identities = new Set<string>();
  for (const item of result.evidence) {
    if (
      typeof item !== "object" ||
      item === null ||
      typeof item.message_id !== "string" ||
      !PSEUDONYM.test(item.message_id) ||
      identities.has(item.message_id)
    ) {
      return false;
    }
    if (item.origin !== "direct" && item.origin !== "inherited") return false;
    identities.add(item.message_id);
  }
  return true;
}

function validSignals(result: SessionAnalysisResult): boolean {
  if (!Array.isArray(result.signals) || result.signals.length > 32) return false;
  const codes = new Set<string>();
  for (const item of result.signals) {
    if (
      !isRecord(item) ||
      Object.keys(item).sort().join(",") !== "code,count,status" ||
      !isRequiredSafeLabel(item.code) ||
      codes.has(item.code as string) ||
      !["detected", "missing", "counted", "unknown"].includes(
        item.status as string,
      )
    ) {
      return false;
    }
    const count = item.count;
    if (
      (item.status === "detected" && count !== 1) ||
      (item.status === "missing" && count !== 0) ||
      (item.status === "counted" &&
        (!Number.isSafeInteger(count) ||
          (count as number) < 0 ||
          (count as number) > 10_000_000)) ||
      (item.status === "unknown" && count !== null)
    ) {
      return false;
    }
    codes.add(item.code as string);
  }
  return true;
}

function validPromptSignalReceipt(
  definition: QualityMetricDefinition,
  result: SessionAnalysisResult,
): boolean {
  void definition;
  if (result.value_state !== "known") return true;
  const numerator = result.fraction?.numerator;
  const denominator = result.fraction?.denominator;
  if (numerator === undefined || denominator === undefined) {
    return false;
  }
  // Legacy v1 logic results predate content-free score receipts. They remain
  // readable through their immutable pack identity; current coaching results
  // always include receipts and are validated when present.
  if (result.signals.length === 0) return true;
  if (
    result.signals.every(
      (signal) => signal.status === "detected" || signal.status === "missing",
    )
  ) {
    return (
      result.signals.length === denominator &&
      result.signals.filter((signal) => signal.status === "detected").length ===
        numerator
    );
  }
  const counted = result.signals.filter((signal) => signal.status === "counted");
  return (
    counted.length === result.signals.length &&
    counted.length === 2 &&
    counted.some((signal) => signal.count === denominator) &&
    counted.some((signal) => signal.count === numerator)
  );
}

function validValueContract(
  definition: QualityMetricDefinition,
  result: SessionAnalysisResult,
): boolean {
  const confidence = result.confidence ?? null;
  if (
    confidence !== null &&
    (!Number.isFinite(confidence) || confidence < 0 || confidence > 1)
  ) {
    return false;
  }
  if (
    result.key !== definition.key ||
    result.version !== definition.version ||
    result.metric_schema_version !== 2 ||
    result.dimension !== definition.dimension ||
    result.unit !== definition.unit ||
    result.direction !== definition.direction ||
    result.aggregation_method !== "ratio_of_sums" ||
    !["provider_reported", "deterministic", "human_label", "estimated"].includes(
      result.source,
    ) ||
    !["applicable", "not_applicable", "unknown"].includes(result.applicability) ||
    ![
      "known",
      "unknown",
      "not_applicable",
      "abstained",
      "execution_error",
    ].includes(result.value_state) ||
    !isRequiredSafeVersion(result.algorithm_id) ||
    !isRequiredSafeVersion(result.algorithm_version) ||
    !isRequiredSafeLabel(result.explanation_code) ||
    !isRequiredDate(result.computed_at) ||
    !validModelTuple(result) ||
    !validObservationCoverage(result) ||
    !validEvidence(result) ||
    !validSignals(result) ||
    !validPromptSignalReceipt(definition, result)
  ) {
    return false;
  }

  if (
    (result.applicability === "unknown" && result.value_state !== "unknown") ||
    (result.applicability === "not_applicable" &&
      result.value_state !== "not_applicable") ||
    (result.applicability === "applicable" &&
      result.value_state === "not_applicable")
  ) {
    return false;
  }

  if (result.value_state === "known") {
    const fraction = result.fraction;
    if (
      result.applicability !== "applicable" ||
      result.error_code !== null ||
      !isRecord(fraction) ||
      result.numeric_value === null ||
      !Number.isSafeInteger(fraction.numerator) ||
      !Number.isSafeInteger(fraction.denominator) ||
      (fraction.numerator as number) < 0 ||
      (fraction.denominator as number) <= 0 ||
      (fraction.numerator as number) > (fraction.denominator as number) ||
      !Number.isFinite(result.numeric_value) ||
      result.numeric_value < 0 ||
      result.numeric_value > 1
    ) {
      return false;
    }
    return (
      Math.abs(
        result.numeric_value -
          (fraction.numerator as number) / (fraction.denominator as number),
      ) <= EPSILON
    );
  }

  if (result.numeric_value !== null || result.fraction !== null) return false;
  if (result.value_state === "execution_error") {
    return isRequiredSafeLabel(result.error_code);
  }
  return result.error_code === null;
}

function stateFor(result: SessionAnalysisResult): QualityMetricState {
  if (result.value_state === "not_applicable") return "not-applicable";
  if (result.value_state === "abstained") return "abstained";
  if (result.value_state === "execution_error") return "execution-error";
  if (result.value_state === "unknown") return "unavailable";
  return result.coverage < 1 ? "partial" : "observed";
}

function errorFor(result: SessionAnalysisResult): QualityMetricErrorCode | null {
  if (result.value_state === "known" || result.value_state === "not_applicable") {
    return null;
  }
  if (result.value_state === "abstained") return "analysis-abstained";
  if (result.value_state === "execution_error") return "calculation-failed";
  return "insufficient-evidence";
}

function observationFromResult(
  definition: QualityMetricDefinition,
  result: SessionAnalysisResult,
): QualityMetricObservation {
  return {
    definition,
    state: stateFor(result),
    ratio: result.numeric_value,
    fractionNumerator: result.fraction?.numerator ?? null,
    fractionDenominator: result.fraction?.denominator ?? null,
    observed: result.observed_count,
    eligible: result.eligible_count,
    notSelectedRuns: 0,
    unknownScopeRuns: 0,
    coverage: result.coverage,
    confidence: result.confidence ?? null,
    signals: result.signals.map((signal) => ({
      code: signal.code,
      status: signal.status as QualityMetricSignal["status"],
      count: signal.count,
    })),
    metricSchemaVersion: result.metric_schema_version,
    explanationCode: result.explanation_code,
    algorithmId: result.algorithm_id,
    algorithmVersion: result.algorithm_version,
    modelId: result.model_id,
    errorCode: errorFor(result),
    definitionVersion: result.version,
    computedAt: result.computed_at,
  };
}

function snapshot(
  kind: QualitySnapshotKind,
  definitions: readonly QualityMetricDefinition[],
  response: SessionAnalysisRunResponse | null,
  expectedSessionId?: string,
): QualityProfileSnapshot {
  if (response === null) {
    return {
      kind,
      integrity: "unavailable",
      metricPackVersion: null,
      scope: null,
      metrics: definitions.map(unavailableObservation),
    };
  }

  if (
    typeof response !== "object" ||
    response === null ||
    typeof response.run !== "object" ||
    response.run === null ||
    !Array.isArray(response.results) ||
    response.results.some(
      (result) => typeof result !== "object" || result === null,
    )
  ) {
    return {
      kind,
      integrity: "invalid-contract",
      metricPackVersion: null,
      scope: null,
      metrics: definitions.map(invalidObservation),
    };
  }

  const staleCoachingPack =
    response.run.metric_pack_key === COACHING_PACK_KEY &&
    Number.isSafeInteger(response.run.metric_pack_version) &&
    response.run.metric_pack_version > 0 &&
    response.run.metric_pack_version < COACHING_PACK_VERSION;
  if (
    staleCoachingPack &&
    isCompletedRun(
      response.run,
      COACHING_PACK_KEY,
      response.run.metric_pack_version,
      expectedSessionId,
    )
  ) {
    return {
      kind,
      integrity: "stale-pack",
      metricPackVersion: response.run.metric_pack_version,
      scope: null,
      metrics: definitions.map(unavailableObservation),
    };
  }

  const packContract =
    response.run.metric_pack_key === COACHING_PACK_KEY &&
    response.run.metric_pack_version === COACHING_PACK_VERSION
      ? {
          key: COACHING_PACK_KEY,
          version: COACHING_PACK_VERSION,
          definitions: QUALITY_ANALYSIS_DEFINITIONS,
        }
      : response.run.metric_pack_key === LEGACY_PACK_KEY &&
          response.run.metric_pack_version === LEGACY_PACK_VERSION
        ? {
            key: LEGACY_PACK_KEY,
            version: LEGACY_PACK_VERSION,
            definitions: LEGACY_QUALITY_ANALYSIS_DEFINITIONS,
          }
        : null;
  if (packContract === null) {
    return {
      kind,
      integrity: "invalid-contract",
      metricPackVersion: null,
      scope: null,
      metrics: definitions.map(invalidObservation),
    };
  }

  const allKeys = new Set(packContract.definitions.map((definition) => definition.key));
  const resultKeys = response.results.map((result) => result.key);
  const uniqueKeys = new Set(resultKeys);
  const returnedSubsetValid =
    response.results.length <= 100 &&
    uniqueKeys.size === response.results.length &&
    resultKeys.every((key) => allKeys.has(key));
  const resultsByKey = new Map(
    response.results.map((result) => [result.key, result]),
  );
  const resultsValid = response.results.every((result) => {
    const definition = packContract.definitions.find(
      (candidate) => candidate.key === result.key,
    );
    return definition !== undefined && validValueContract(definition, result);
  });
  const selectedKeys = response.run.selected_metric_keys;
  const exactScopeMatchesResults =
    response.run.metric_scope_state !== "exact" ||
    (selectedKeys.length === resultKeys.length &&
      selectedKeys.every((key) => uniqueKeys.has(key)));
  const coherent =
    returnedSubsetValid &&
    isCompletedRun(
      response.run,
      packContract.key,
      packContract.version,
      expectedSessionId,
    ) &&
    exactScopeMatchesResults &&
    resultsValid;
  if (!coherent) {
    return {
      kind,
      integrity: "invalid-contract",
      metricPackVersion: null,
      scope: null,
      metrics: definitions.map(invalidObservation),
    };
  }

  return {
    kind,
    integrity: "coherent",
    metricPackVersion: response.run.metric_pack_version,
    scope: null,
    metrics: definitions.map((definition) => {
      const result = resultsByKey.get(definition.key);
      if (result !== undefined) return observationFromResult(definition, result);
      return response.run.metric_scope_state === "exact"
        ? notSelectedObservation(definition)
        : scopeUnknownObservation(definition);
    }),
  };
}

function safeCount(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0;
}

const STATE_COUNT_KEYS = [
  "known",
  "unknown",
  "not_applicable",
  "abstained",
  "execution_error",
] as const;

function hasRequiredAndOnlyKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  const actual = Object.keys(value);
  return required.every((key) => actual.includes(key)) &&
    actual.every((key) => allowed.has(key));
}

const PROJECT_AGGREGATE_KEYS = [
  "analysis_profile_key",
  "analysis_profile_version",
  "completed_run_count",
  "duplicate_result_record_count",
  "integrity_state",
  "metric_pack_key",
  "metric_pack_version",
  "metric_schema_version",
  "metrics",
  "missing_run_count",
  "selected_session_count",
  "unexpected_result_record_count",
] as const;

const PROJECT_METRIC_REQUIRED_KEYS = [
  "aggregate_state",
  "aggregation_method",
  "blocked_reason_codes",
  "compatibility_cohorts",
  "compatibility_state",
  "completed_run_count",
  "invalid_result_record_count",
  "invalid_result_session_count",
  "metric_direction",
  "metric_key",
  "metric_unit",
  "metric_version",
  "missing_result_count",
  "missing_run_count",
  "not_selected_run_count",
  "present_result_count",
  "selected_session_count",
  "state_counts",
  "unknown_scope_run_count",
] as const;

const PROJECT_METRIC_OPTIONAL_KEYS = [
  "analyzable_coverage",
  "analyzable_eligible_count",
  "analyzable_observed_count",
  "fraction_denominator",
  "fraction_numerator",
  "numeric_value",
] as const;

const PROJECT_COHORT_REQUIRED_KEYS = [
  "analyzable_coverage",
  "analyzable_eligible_count",
  "analyzable_observed_count",
  "compatibility_fingerprint",
  "result_count",
  "state_counts",
] as const;

const PROJECT_COHORT_OPTIONAL_KEYS = [
  "fraction_denominator",
  "fraction_numerator",
  "numeric_value",
] as const;

const COMPATIBILITY_FINGERPRINT = /^[0-9a-f]{64}$/;

function hasStateCounts(value: unknown): boolean {
  return (
    isRecord(value) &&
    Object.keys(value).length === STATE_COUNT_KEYS.length &&
    STATE_COUNT_KEYS.every((key) => safeCount(value[key] as number))
  );
}

function sameStateCounts(
  left: SessionQualityMetricAggregate["state_counts"],
  right: SessionQualityMetricAggregate["state_counts"],
): boolean {
  return STATE_COUNT_KEYS.every((key) => left[key] === right[key]);
}

function validAggregateCohortProjection(
  cohort:
    | SessionQualityMetricAggregate["compatibility_cohorts"][number]
    | ProjectQualityMetricAggregate["compatibility_cohorts"][number],
): boolean {
  const stateTotal = Object.values(cohort.state_counts).reduce(
    (total, count) => total + count,
    0,
  );
  const numerator = cohort.fraction_numerator ?? null;
  const denominator = cohort.fraction_denominator ?? null;
  const value = cohort.numeric_value ?? null;
  const hasKnown = cohort.state_counts.known > 0;
  return (
    safeCount(cohort.result_count) &&
    cohort.result_count > 0 &&
    cohort.result_count === stateTotal &&
    safeCount(cohort.analyzable_observed_count) &&
    safeCount(cohort.analyzable_eligible_count) &&
    cohort.analyzable_observed_count <= cohort.analyzable_eligible_count &&
    Number.isFinite(cohort.analyzable_coverage) &&
    Math.abs(
      cohort.analyzable_coverage -
        (cohort.analyzable_eligible_count === 0
          ? 0
          : cohort.analyzable_observed_count / cohort.analyzable_eligible_count)
    ) <= EPSILON &&
    (hasKnown
      ? numerator !== null &&
        denominator !== null &&
        value !== null &&
        safeCount(numerator) &&
        Number.isSafeInteger(denominator) &&
        denominator > 0 &&
        numerator <= denominator &&
        Number.isFinite(value) &&
        Math.abs(value - numerator / denominator) <= EPSILON
      : numerator === null && denominator === null && value === null)
  );
}

function hasAggregateMetricStructure(
  value: unknown,
): value is SessionQualityMetricAggregate {
  if (
    !isRecord(value) ||
    !hasStateCounts(value.state_counts) ||
    !safeCount(value.not_selected_run_count as number) ||
    !safeCount(value.unknown_scope_run_count as number) ||
    !Array.isArray(value.blocked_reason_codes) ||
    !value.blocked_reason_codes.every(isRequiredSafeLabel) ||
    !Array.isArray(value.compatibility_cohorts)
  ) {
    return false;
  }
  return value.compatibility_cohorts.every(
    (cohort) =>
      isRecord(cohort) &&
      isRecord(cohort.key) &&
      hasStateCounts(cohort.state_counts),
  );
}

function hasAggregateEnvelope(value: unknown): value is SessionQualityAggregate {
  return (
    isRecord(value) &&
    isRequiredSafeVersion(value.analysis_profile_key) &&
    Number.isSafeInteger(value.analysis_profile_version) &&
    (value.analysis_profile_version as number) > 0 &&
    isRequiredSafeVersion(value.metric_pack_key) &&
    Number.isSafeInteger(value.metric_pack_version) &&
    (value.metric_pack_version as number) > 0 &&
    Number.isSafeInteger(value.metric_schema_version) &&
    (value.metric_schema_version as number) > 0 &&
    Array.isArray(value.metrics) &&
    value.metrics.every(hasAggregateMetricStructure)
  );
}

function hasProjectAggregateCohort(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasRequiredAndOnlyKeys(
      value,
      PROJECT_COHORT_REQUIRED_KEYS,
      PROJECT_COHORT_OPTIONAL_KEYS,
    ) &&
    typeof value.compatibility_fingerprint === "string" &&
    COMPATIBILITY_FINGERPRINT.test(value.compatibility_fingerprint) &&
    safeCount(value.result_count as number) &&
    safeCount(value.analyzable_observed_count as number) &&
    safeCount(value.analyzable_eligible_count as number) &&
    (value.analyzable_observed_count as number) <=
      (value.analyzable_eligible_count as number) &&
    typeof value.analyzable_coverage === "number" &&
    Number.isFinite(value.analyzable_coverage) &&
    hasStateCounts(value.state_counts)
  );
}

function hasProjectAggregateMetric(value: unknown): boolean {
  return (
    isRecord(value) &&
    hasRequiredAndOnlyKeys(
      value,
      PROJECT_METRIC_REQUIRED_KEYS,
      PROJECT_METRIC_OPTIONAL_KEYS,
    ) &&
    hasStateCounts(value.state_counts) &&
    Array.isArray(value.blocked_reason_codes) &&
    value.blocked_reason_codes.every(isRequiredSafeLabel) &&
    Array.isArray(value.compatibility_cohorts) &&
    value.compatibility_cohorts.every(hasProjectAggregateCohort)
  );
}

function hasProjectAggregateEnvelope(
  value: unknown,
): value is ProjectSessionQualityAggregate {
  return (
    isRecord(value) &&
    hasRequiredAndOnlyKeys(value, PROJECT_AGGREGATE_KEYS) &&
    isRequiredSafeVersion(value.analysis_profile_key) &&
    Number.isSafeInteger(value.analysis_profile_version) &&
    (value.analysis_profile_version as number) > 0 &&
    isRequiredSafeVersion(value.metric_pack_key) &&
    Number.isSafeInteger(value.metric_pack_version) &&
    (value.metric_pack_version as number) > 0 &&
    Number.isSafeInteger(value.metric_schema_version) &&
    (value.metric_schema_version as number) > 0 &&
    Array.isArray(value.metrics) &&
    value.metrics.every(hasProjectAggregateMetric)
  );
}

function aggregateAnalysisProfile(
  aggregate: SessionQualityAggregate | ProjectSessionQualityAggregate,
): QualityMetricProfile["analysisProfile"] {
  if (
    aggregate.analysis_profile_key === "coaching_profile" &&
    aggregate.analysis_profile_version === 1
  ) {
    return { state: "coaching", label: "Coaching profile v1" };
  }
  if (
    aggregate.analysis_profile_key === "standard_engineering" &&
    aggregate.analysis_profile_version === 1
  ) {
    return { state: "standard", label: "Standard engineering v1" };
  }
  return {
    state: "legacy-or-unknown",
    label: "Legacy / unknown analysis profile",
  };
}

function compatibilityBaseIdentity(
  metric: SessionQualityMetricAggregate,
  key: SessionQualityCompatibilityKey,
): string | null {
  const modelFields = [
    key.model_id,
    key.model_revision,
    key.model_license,
    key.tokenizer_id,
  ];
  const modelFieldCount = modelFields.filter((value) => value != null).length;
  if (
    key.metric_key !== metric.metric_key ||
    key.metric_version !== metric.metric_version ||
    key.metric_unit !== metric.metric_unit ||
    key.metric_direction !== metric.metric_direction ||
    key.aggregation_method !== metric.aggregation_method ||
    key.data_tier !== "redacted_content" ||
    key.local_only !== true ||
    !isRequiredSafeVersion(key.analysis_profile_key) ||
    !Number.isSafeInteger(key.analysis_profile_version) ||
    key.analysis_profile_version < 1 ||
    !(
      (key.metric_pack_key === COACHING_PACK_KEY &&
        key.metric_pack_version === COACHING_PACK_VERSION) ||
      (key.metric_pack_key === LEGACY_PACK_KEY &&
        key.metric_pack_version === LEGACY_PACK_VERSION)
    ) ||
    key.metric_schema_version !== 2 ||
    !["exact", "legacy_unknown"].includes(key.metric_scope_state) ||
    !["codex", "claude_code", "synthetic"].includes(key.provider) ||
    !["provider_reported", "deterministic", "human_label", "estimated"].includes(
      key.metric_source,
    ) ||
    (modelFieldCount !== 0 && modelFieldCount !== modelFields.length) ||
    ![
      ...modelFields,
      key.prompt_version,
      key.rubric_version,
    ].every(isNullableSafeVersion) ||
    !isRequiredSafeVersion(key.algorithm_id) ||
    !isRequiredSafeVersion(key.algorithm_version) ||
    !Number.isSafeInteger(key.metric_pack_version) ||
    key.metric_pack_version < 1 ||
    !Number.isSafeInteger(key.metric_schema_version) ||
    key.metric_schema_version < 1 ||
    ![
      key.metric_pack_key,
      key.consent_policy_version,
      key.provider_version,
      key.adapter_version,
      key.source_schema_version,
      key.content_schema_version,
      key.metric_engine_version,
      key.redactor_version,
    ].every(isRequiredSafeVersion)
  ) {
    return "invalid";
  }
  return JSON.stringify({
    analysisProfileKey: key.analysis_profile_key,
    analysisProfileVersion: key.analysis_profile_version,
    metricPackKey: key.metric_pack_key,
    metricPackVersion: key.metric_pack_version,
    metricScopeState: key.metric_scope_state,
    dataTier: key.data_tier,
    consentPolicyVersion: key.consent_policy_version,
    provider: key.provider,
    providerVersion: key.provider_version,
    adapterVersion: key.adapter_version,
    sourceSchemaVersion: key.source_schema_version,
    contentSchemaVersion: key.content_schema_version,
    metricEngineVersion: key.metric_engine_version,
    redactorVersion: key.redactor_version,
    localOnly: key.local_only,
  });
}

function aggregateBaseIdentity(
  metric: SessionQualityMetricAggregate,
): string | null {
  if (metric.compatibility_cohorts.length === 0) return null;
  const identities = new Set(
    metric.compatibility_cohorts.map((cohort) =>
      compatibilityBaseIdentity(metric, cohort.key),
    ),
  );
  if (identities.has("invalid") || identities.has(null) || identities.size !== 1) {
    return "invalid";
  }
  return [...identities][0];
}

function aggregateObservation(
  definition: QualityMetricDefinition,
  metric: SessionQualityMetricAggregate | ProjectQualityMetricAggregate,
): QualityMetricObservation | null {
  const stateTotal = Object.values(metric.state_counts).reduce(
    (total, count) => total + count,
    0,
  );
  if (
    metric.metric_key !== definition.key ||
    metric.metric_version !== definition.version ||
    metric.metric_unit !== definition.unit ||
    metric.metric_direction !== definition.direction ||
    metric.aggregation_method !== "ratio_of_sums" ||
    !["compatible", "incompatible", "no_results"].includes(
      metric.compatibility_state,
    ) ||
    ![
      "known",
      "unknown",
      "not_applicable",
      "abstained",
      "execution_error",
      "incompatible",
    ].includes(metric.aggregate_state) ||
    metric.selected_session_count !==
      metric.completed_run_count + metric.missing_run_count ||
    metric.completed_run_count !==
      metric.present_result_count +
        metric.not_selected_run_count +
        metric.missing_result_count +
        metric.invalid_result_session_count ||
    metric.present_result_count !== stateTotal ||
    metric.invalid_result_session_count !== 0 ||
    metric.invalid_result_record_count !== 0 ||
    metric.unknown_scope_run_count > metric.completed_run_count ||
    ![
      metric.selected_session_count,
      metric.completed_run_count,
      metric.missing_run_count,
      metric.present_result_count,
      metric.missing_result_count,
      metric.not_selected_run_count,
      metric.unknown_scope_run_count,
      metric.invalid_result_session_count,
      metric.invalid_result_record_count,
      ...Object.values(metric.state_counts),
    ].every(safeCount)
  ) {
    return null;
  }

  if (metric.compatibility_state === "incompatible") {
    const cohortResultCount = metric.compatibility_cohorts.reduce(
      (total, cohort) => total + cohort.result_count,
      0,
    );
    if (
      metric.aggregate_state !== "incompatible" ||
      metric.blocked_reason_codes.length === 0 ||
      cohortResultCount !== metric.present_result_count ||
      !metric.compatibility_cohorts.every(validAggregateCohortProjection) ||
      !metric.compatibility_cohorts.every(
        (cohort) =>
          !("key" in cohort) ||
          compatibilityBaseIdentity(
            metric as SessionQualityMetricAggregate,
            cohort.key,
          ) !== "invalid",
      ) ||
      metric.numeric_value != null ||
      metric.fraction_numerator != null ||
      metric.fraction_denominator != null ||
      metric.analyzable_observed_count != null ||
      metric.analyzable_eligible_count != null ||
      metric.analyzable_coverage != null
    ) {
      return null;
    }
    const scopeReason = metric.blocked_reason_codes.includes("metric_scope_unknown");
    if (scopeReason !== (metric.unknown_scope_run_count > 0)) return null;
    if (scopeReason) {
      return {
        ...scopeUnknownObservation(definition, metric.unknown_scope_run_count),
        notSelectedRuns: metric.not_selected_run_count,
        definitionVersion: metric.metric_version,
      };
    }
    return incompatibleObservation(
      definition,
      metric.not_selected_run_count,
    );
  }

  if (metric.compatibility_state === "no_results") {
    if (
      metric.present_result_count !== 0 ||
      metric.compatibility_cohorts.length !== 0 ||
      metric.blocked_reason_codes.length !== 0 ||
      metric.unknown_scope_run_count !== 0 ||
      metric.aggregate_state !== "unknown" ||
      metric.numeric_value != null ||
      metric.fraction_numerator != null ||
      metric.fraction_denominator != null ||
      metric.analyzable_observed_count != null ||
      metric.analyzable_eligible_count != null ||
      metric.analyzable_coverage != null
    ) {
      return null;
    }
    if (
      metric.not_selected_run_count > 0 &&
      metric.not_selected_run_count === metric.selected_session_count &&
      metric.missing_run_count === 0 &&
      metric.missing_result_count === 0
    ) {
      return notSelectedObservation(definition, metric.not_selected_run_count);
    }
    const unavailable = unavailableObservation(definition);
    return {
      ...unavailable,
      errorCode:
        metric.missing_result_count > 0
          ? "insufficient-evidence"
          : unavailable.errorCode,
      notSelectedRuns: metric.not_selected_run_count,
      unknownScopeRuns: metric.unknown_scope_run_count,
    };
  }

  if (
    metric.compatibility_state !== "compatible" ||
    metric.unknown_scope_run_count !== 0 ||
    metric.blocked_reason_codes.length !== 0 ||
    metric.compatibility_cohorts.length !== 1
  ) {
    return null;
  }
  const cohort = metric.compatibility_cohorts[0];
  const cohortStateTotal = Object.values(cohort.state_counts).reduce(
    (total, count) => total + count,
    0,
  );
  const observed = metric.analyzable_observed_count;
  const eligible = metric.analyzable_eligible_count;
  const coverage = metric.analyzable_coverage;
  if (
    cohort.result_count !== metric.present_result_count ||
    cohortStateTotal !== cohort.result_count ||
    !sameStateCounts(cohort.state_counts, metric.state_counts) ||
    observed == null ||
    eligible == null ||
    coverage == null ||
    !safeCount(observed) ||
    !safeCount(eligible) ||
    observed > eligible ||
    !Number.isFinite(coverage) ||
    Math.abs(coverage - (eligible === 0 ? 0 : observed / eligible)) > EPSILON ||
    cohort.analyzable_observed_count !== observed ||
    cohort.analyzable_eligible_count !== eligible ||
    !Number.isFinite(cohort.analyzable_coverage) ||
    Math.abs(cohort.analyzable_coverage - coverage) > EPSILON
  ) {
    return null;
  }

  if (metric.aggregate_state === "known") {
    const numerator = metric.fraction_numerator;
    const denominator = metric.fraction_denominator;
    const value = metric.numeric_value;
    if (
      numerator == null ||
      denominator == null ||
      value == null ||
      !safeCount(numerator) ||
      !Number.isSafeInteger(denominator) ||
      denominator <= 0 ||
      numerator > denominator ||
      !Number.isFinite(value) ||
      Math.abs(value - numerator / denominator) > EPSILON ||
      cohort.fraction_numerator !== numerator ||
      cohort.fraction_denominator !== denominator ||
      cohort.numeric_value == null ||
      !Number.isFinite(cohort.numeric_value) ||
      Math.abs(cohort.numeric_value - value) > EPSILON ||
      metric.state_counts.known === 0
    ) {
      return null;
    }
    const partial =
      metric.missing_run_count > 0 ||
      metric.missing_result_count > 0 ||
      metric.not_selected_run_count > 0 ||
      stateTotal !== metric.state_counts.known ||
      coverage < 1;
    return {
      definition,
      state: partial ? "partial" : "observed",
      ratio: value,
      fractionNumerator: numerator,
      fractionDenominator: denominator,
      observed,
      eligible,
      notSelectedRuns: metric.not_selected_run_count,
      unknownScopeRuns: metric.unknown_scope_run_count,
      coverage,
      confidence: null,
      signals: [],
      metricSchemaVersion: null,
      explanationCode: null,
      algorithmId: null,
      algorithmVersion: null,
      modelId: null,
      errorCode: null,
      definitionVersion: metric.metric_version,
      computedAt: null,
    };
  }

  if (
    metric.numeric_value != null ||
    metric.fraction_numerator != null ||
    metric.fraction_denominator != null ||
    cohort.numeric_value != null ||
    cohort.fraction_numerator != null ||
    cohort.fraction_denominator != null
  ) {
    return null;
  }
  const state: QualityMetricState =
    metric.aggregate_state === "not_applicable"
      ? "not-applicable"
      : metric.aggregate_state === "abstained"
        ? "abstained"
        : metric.aggregate_state === "execution_error"
          ? "execution-error"
          : metric.aggregate_state === "unknown"
            ? "unavailable"
            : "execution-error";
  if (metric.aggregate_state === "incompatible") return null;
  return {
    definition,
    state,
    ratio: null,
    fractionNumerator: null,
    fractionDenominator: null,
    observed,
    eligible,
    notSelectedRuns: metric.not_selected_run_count,
    unknownScopeRuns: metric.unknown_scope_run_count,
    coverage,
    confidence: null,
    signals: [],
    metricSchemaVersion: null,
    explanationCode: null,
    algorithmId: null,
    algorithmVersion: null,
    modelId: null,
    errorCode:
      state === "abstained"
        ? "analysis-abstained"
        : state === "execution-error"
          ? "calculation-failed"
          : state === "unavailable"
            ? "insufficient-evidence"
            : null,
    definitionVersion: metric.metric_version,
    computedAt: null,
  };
}

function profileCopy(kind: QualityProfileKind): Pick<
  QualityMetricProfile,
  "title" | "eyebrow" | "question" | "summary" | "initialLabel" | "latestLabel"
> {
  return kind === "prompt"
    ? {
        title: "Prompt & collaboration coaching",
        eyebrow: "11 observable coaching metrics",
        question: "How clearly was the work framed, clarified, constrained, and adapted?",
        summary:
          "Independent experimental signals—not a cognitive-skill rating, person score, or task-success claim.",
        initialLabel: "Initial request",
        latestLabel: "Latest analysis window",
      }
    : {
        title: "Logic & outcome evidence",
        eyebrow: "9 observable workflow metrics",
        question: "How well did requirements, plans, checks, claims, and evidence stay connected?",
        summary:
          "Observable traceability and conversation structure only; hidden reasoning is neither accessed nor inferred.",
        initialLabel: "First observed state",
        latestLabel: "Current observed state",
      };
}

export function createQualityMetricProfile(
  category: MetricCategory,
  latestRun: SessionAnalysisRunResponse | null,
  expectedSessionId?: string,
): QualityMetricProfile | null {
  const kind = profileKind(category);
  if (!kind) return null;
  const definitions = definitionsForRun(kind, latestRun);
  return {
    kind,
    ...profileCopy(kind),
    analysisProfile:
      latestRun === null
        ? null
        : latestRun.run?.analysis_profile_key === "coaching_profile" &&
            latestRun.run?.analysis_profile_version === 1
          ? { state: "coaching", label: "Coaching profile v1" }
          : latestRun.run?.analysis_profile_key === "standard_engineering" &&
            latestRun.run?.analysis_profile_version === 1
          ? { state: "standard", label: "Standard engineering v1" }
          : {
              state: "legacy-or-unknown",
              label: "Legacy / unknown analysis profile",
            },
    initial: snapshot("initial", definitions, null),
    latest: snapshot("latest", definitions, latestRun, expectedSessionId),
  };
}

export function createAggregateQualityMetricProfile(
  category: MetricCategory,
  aggregate: SessionQualityAggregate | null,
): QualityMetricProfile | null {
  const kind = profileKind(category);
  if (!kind) return null;
  const definitions = definitionsForAggregate(kind, aggregate);
  const unavailable = {
    kind: "latest" as const,
    integrity: "unavailable" as const,
    metricPackVersion: null,
    scope:
      aggregate === null
        ? null
        : {
            selectedSessions: aggregate.selected_session_count,
            completedRuns: aggregate.completed_run_count,
            missingRuns: aggregate.missing_run_count,
          },
    metrics: definitions.map(unavailableObservation),
  };
  if (aggregate === null) {
    return {
      kind,
      ...profileCopy(kind),
      analysisProfile: null,
      initial: snapshot("initial", definitions, null),
      latest: unavailable,
    };
  }

  if (!hasAggregateEnvelope(aggregate)) {
    return {
      kind,
      ...profileCopy(kind),
      analysisProfile: null,
      initial: snapshot("initial", definitions, null),
      latest: {
        kind: "latest",
        integrity: "invalid-contract",
        metricPackVersion: null,
        scope: null,
        metrics: definitions.map(invalidObservation),
      },
    };
  }

  const topCountsValid =
    safeCount(aggregate.selected_session_count) &&
    aggregate.selected_session_count >= 1 &&
    aggregate.selected_session_count <= 100 &&
    safeCount(aggregate.completed_run_count) &&
    safeCount(aggregate.missing_run_count) &&
    aggregate.selected_session_count ===
      aggregate.completed_run_count + aggregate.missing_run_count &&
    aggregate.unexpected_result_record_count === 0 &&
    aggregate.duplicate_result_record_count === 0 &&
    aggregate.metrics.every(
      (metric) =>
        metric.selected_session_count === aggregate.selected_session_count &&
        metric.completed_run_count === aggregate.completed_run_count &&
        metric.missing_run_count === aggregate.missing_run_count,
    );
  const aggregatePlanValid =
    aggregate.metric_schema_version === 2 &&
    aggregate.metrics.every((metric) =>
      metric.compatibility_cohorts.every(
        (cohort) =>
          cohort.key.analysis_profile_key === aggregate.analysis_profile_key &&
          cohort.key.analysis_profile_version === aggregate.analysis_profile_version &&
          cohort.key.metric_pack_key === aggregate.metric_pack_key &&
          cohort.key.metric_pack_version === aggregate.metric_pack_version &&
          cohort.key.metric_schema_version === aggregate.metric_schema_version,
      ),
    );
  const resultsByKey = new Map(
    aggregate.metrics.map((metric) => [metric.metric_key, metric]),
  );
  const aggregatePackDefinitions =
    definitions === LEGACY_PROMPT_DEFINITIONS ||
    definitions === LEGACY_LOGIC_DEFINITIONS
      ? LEGACY_QUALITY_ANALYSIS_DEFINITIONS
      : QUALITY_ANALYSIS_DEFINITIONS;
  const exactPack =
    aggregate.metrics.length === aggregatePackDefinitions.length &&
    resultsByKey.size === aggregatePackDefinitions.length &&
    aggregatePackDefinitions.every((definition) =>
      resultsByKey.has(definition.key),
    );
  const observations = definitions.map((definition) => {
    const metric = resultsByKey.get(definition.key);
    return metric ? aggregateObservation(definition, metric) : null;
  });
  const validMixedObservations = observations.every(
    (observation) => observation !== null,
  );
  const baseIdentities = new Set(
    aggregate.metrics
      .map(aggregateBaseIdentity)
      .filter((value): value is string => value !== null),
  );
  const hasInvalidIdentity = baseIdentities.has("invalid");
  const coherentBase = !hasInvalidIdentity && baseIdentities.size <= 1;
  const scope = {
    selectedSessions: aggregate.selected_session_count,
    completedRuns: aggregate.completed_run_count,
    missingRuns: aggregate.missing_run_count,
  };

  let latest: QualityProfileSnapshot;
  if (
    aggregate.integrity_state === "incompatible" &&
    topCountsValid &&
    exactPack &&
    aggregatePlanValid
  ) {
    latest = {
      kind: "latest",
      integrity: "mixed-provenance",
      metricPackVersion: validMixedObservations
        ? aggregate.metric_pack_version
        : null,
      scope,
      metrics: validMixedObservations
        ? observations as QualityMetricObservation[]
        : definitions.map(invalidObservation),
    };
  } else if (
    !topCountsValid ||
    !aggregatePlanValid ||
    !exactPack ||
    aggregate.integrity_state !== "valid" ||
    observations.some((item) => item === null) ||
    !coherentBase
  ) {
    latest = {
      kind: "latest",
      integrity: "invalid-contract",
      metricPackVersion: null,
      scope,
      metrics: definitions.map(invalidObservation),
    };
  } else if (baseIdentities.size === 0) {
    latest = {
      kind: "latest",
      integrity: "coherent",
      metricPackVersion: aggregate.metric_pack_version,
      scope,
      metrics: observations as QualityMetricObservation[],
    };
  } else {
    const firstCohort = aggregate.metrics.find(
      (metric) => metric.compatibility_cohorts.length === 1,
    )!.compatibility_cohorts[0];
    latest = {
      kind: "latest",
      integrity: "coherent",
      metricPackVersion: firstCohort.key.metric_pack_version,
      scope,
      metrics: observations as QualityMetricObservation[],
    };
  }

  return {
    kind,
    ...profileCopy(kind),
    analysisProfile: aggregateAnalysisProfile(aggregate),
    initial: snapshot("initial", definitions, null),
    latest,
  };
}

/**
 * Build the same presentation model from the identifier-free project endpoint.
 * That endpoint intentionally replaces raw compatibility provenance with one
 * content-free fingerprint per cohort, so this adapter validates the public
 * projection rather than reconstructing the private compatibility key.
 */
export function createProjectAggregateQualityMetricProfile(
  category: MetricCategory,
  aggregate: ProjectSessionQualityAggregate | null,
): QualityMetricProfile | null {
  const kind = profileKind(category);
  if (!kind) return null;
  const definitions = definitionsForAggregate(kind, aggregate);
  const scope =
    aggregate === null
      ? null
      : {
          selectedSessions: aggregate.selected_session_count,
          completedRuns: aggregate.completed_run_count,
          missingRuns: aggregate.missing_run_count,
        };
  const unavailable: QualityProfileSnapshot = {
    kind: "latest",
    integrity: "unavailable",
    metricPackVersion: null,
    scope,
    metrics: definitions.map(unavailableObservation),
  };
  if (aggregate === null) {
    return {
      kind,
      ...profileCopy(kind),
      analysisProfile: null,
      initial: snapshot("initial", definitions, null),
      latest: unavailable,
    };
  }
  if (!hasProjectAggregateEnvelope(aggregate)) {
    return {
      kind,
      ...profileCopy(kind),
      analysisProfile: null,
      initial: snapshot("initial", definitions, null),
      latest: {
        kind: "latest",
        integrity: "invalid-contract",
        metricPackVersion: null,
        scope: null,
        metrics: definitions.map(invalidObservation),
      },
    };
  }

  const topCountsValid =
    safeCount(aggregate.selected_session_count) &&
    aggregate.selected_session_count >= 1 &&
    aggregate.selected_session_count <= 100 &&
    safeCount(aggregate.completed_run_count) &&
    safeCount(aggregate.missing_run_count) &&
    aggregate.selected_session_count ===
      aggregate.completed_run_count + aggregate.missing_run_count &&
    aggregate.unexpected_result_record_count === 0 &&
    aggregate.duplicate_result_record_count === 0 &&
    aggregate.metrics.every(
      (metric) =>
        metric.selected_session_count === aggregate.selected_session_count &&
        metric.completed_run_count === aggregate.completed_run_count &&
        metric.missing_run_count === aggregate.missing_run_count &&
        metric.aggregation_method === "ratio_of_sums",
    );
  const aggregatePlanValid =
    aggregate.metric_schema_version === 2 &&
    ((aggregate.metric_pack_key === COACHING_PACK_KEY &&
      aggregate.metric_pack_version === COACHING_PACK_VERSION) ||
      (aggregate.metric_pack_key === LEGACY_PACK_KEY &&
        aggregate.metric_pack_version === LEGACY_PACK_VERSION));
  const resultsByKey = new Map(
    aggregate.metrics.map((metric) => [metric.metric_key, metric]),
  );
  const aggregatePackDefinitions =
    definitions === LEGACY_PROMPT_DEFINITIONS ||
    definitions === LEGACY_LOGIC_DEFINITIONS
      ? LEGACY_QUALITY_ANALYSIS_DEFINITIONS
      : QUALITY_ANALYSIS_DEFINITIONS;
  const exactPack =
    aggregate.metrics.length === aggregatePackDefinitions.length &&
    resultsByKey.size === aggregatePackDefinitions.length &&
    aggregatePackDefinitions.every((definition) =>
      resultsByKey.has(definition.key),
    );
  const observations = definitions.map((definition) => {
    const metric = resultsByKey.get(definition.key);
    return metric ? aggregateObservation(definition, metric) : null;
  });
  const validMixedObservations = observations.every(
    (observation) => observation !== null,
  );
  const hasAnyCohort = aggregate.metrics.some(
    (metric) => metric.compatibility_cohorts.length === 1,
  );

  let latest: QualityProfileSnapshot;
  if (
    aggregate.integrity_state === "incompatible" &&
    topCountsValid &&
    exactPack &&
    aggregatePlanValid
  ) {
    latest = {
      kind: "latest",
      integrity: "mixed-provenance",
      metricPackVersion: validMixedObservations
        ? aggregate.metric_pack_version
        : null,
      scope: scope!,
      metrics: validMixedObservations
        ? observations as QualityMetricObservation[]
        : definitions.map(invalidObservation),
    };
  } else if (
    !topCountsValid ||
    !aggregatePlanValid ||
    !exactPack ||
    aggregate.integrity_state !== "valid" ||
    observations.some((item) => item === null)
  ) {
    latest = {
      kind: "latest",
      integrity: "invalid-contract",
      metricPackVersion: null,
      scope: scope!,
      metrics: definitions.map(invalidObservation),
    };
  } else if (!hasAnyCohort) {
    latest = {
      kind: "latest",
      integrity: "coherent",
      metricPackVersion: aggregate.metric_pack_version,
      scope: scope!,
      metrics: observations as QualityMetricObservation[],
    };
  } else {
    latest = {
      kind: "latest",
      integrity: "coherent",
      metricPackVersion: aggregate.metric_pack_version,
      scope: scope!,
      metrics: observations as QualityMetricObservation[],
    };
  }

  return {
    kind,
    ...profileCopy(kind),
    analysisProfile: aggregateAnalysisProfile(aggregate),
    initial: snapshot("initial", definitions, null),
    latest,
  };
}

export function isQualityProfileCategory(
  category: MetricCategory | null,
): category is "prompt-quality" | "reasoning" {
  return category === "prompt-quality" || category === "reasoning";
}
