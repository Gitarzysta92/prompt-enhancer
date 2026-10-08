import type { QualityMetricObservation } from "./qualityProfile";

export type QualityLensDimension =
  | "prompt"
  | "collaboration"
  | "logic"
  | "outcome";

export type QualityLensId =
  | "task-framing"
  | "collaboration-flow"
  | "reasoning-trace"
  | "outcome-evidence"
  | "legacy-task-contract"
  | "legacy-reasoning-trace";

export interface QualityLensDefinition {
  id: QualityLensId;
  version: 1;
  dimension: QualityLensDimension;
  label: string;
  shortLabel: string;
  question: string;
  boundary: string;
  expectedMetricCount: number;
  metrics: readonly {
    key: string;
    version: QualityMetricObservation["definition"]["version"];
  }[];
}

export interface ResolvedQualityLens {
  definition: QualityLensDefinition;
  metrics: readonly QualityMetricObservation[];
}

/**
 * Lens versions stabilize construct, axis order, and interpretation. Metric
 * values keep their persisted direction; a lens never silently inverts them.
 */
export const QUALITY_LENSES: readonly QualityLensDefinition[] = [
  {
    id: "task-framing",
    version: 1,
    dimension: "prompt",
    label: "Task framing",
    shortLabel: "Framing",
    question: "How completely was the observable request framed for the agent?",
    boundary:
      "Request and specification candidates only; not correctness, value, or developer skill.",
    expectedMetricCount: 6,
    metrics: [
      { key: "prompt.task_definition_coverage", version: 2 },
      { key: "prompt.problem_evidence_quality", version: 2 },
      { key: "prompt.context_sufficiency", version: 2 },
      { key: "prompt.constraint_precision", version: 2 },
      { key: "prompt.acceptance_testability", version: 2 },
      { key: "prompt.deliverable_contract", version: 3 },
    ],
  },
  {
    id: "collaboration-flow",
    version: 1,
    dimension: "collaboration",
    label: "Collaboration flow",
    shortLabel: "Collaboration",
    question: "Did observable clarification, repair, and scope changes converge?",
    boundary:
      "Conversation repair candidates only; not personality, aptitude, or blame.",
    expectedMetricCount: 5,
    metrics: [
      { key: "collaboration.ambiguity_resolution", version: 2 },
      { key: "collaboration.clarification_yield", version: 2 },
      { key: "collaboration.exploration_conversion", version: 2 },
      { key: "collaboration.scope_change_discipline", version: 2 },
      { key: "collaboration.rework_candidate_rate", version: 2 },
    ],
  },
  {
    id: "reasoning-trace",
    version: 1,
    dimension: "logic",
    label: "Reasoning trace",
    shortLabel: "Trace",
    question: "How well did observable requirements, plans, decisions, and actions connect?",
    boundary:
      "Observable work traces only; hidden chain-of-thought is never accessed or inferred.",
    expectedMetricCount: 4,
    metrics: [
      { key: "logic.decomposition_coverage", version: 2 },
      { key: "logic.decision_rationale_coverage", version: 3 },
      { key: "logic.open_loop_closure", version: 2 },
      { key: "outcome.verification_strategy_adequacy", version: 2 },
    ],
  },
  {
    id: "outcome-evidence",
    version: 1,
    dimension: "outcome",
    label: "Evidence lane",
    shortLabel: "Evidence",
    question: "Which observable actions and objective receipts support the work?",
    boundary:
      "Verification evidence only; an assistant completion claim never proves success.",
    expectedMetricCount: 5,
    metrics: [
      { key: "logic.hypothesis_test_linkage", version: 2 },
      { key: "logic.requirement_action_traceability", version: 3 },
      { key: "outcome.agent_claim_grounding", version: 2 },
      { key: "outcome.first_pass_verification", version: 2 },
      { key: "outcome.verified_requirement_coverage", version: 2 },
    ],
  },
  {
    id: "legacy-task-contract",
    version: 1,
    dimension: "prompt",
    label: "Prompt contract",
    shortLabel: "Prompt",
    question: "Which fixed prompt-contract cues were observable in this legacy analysis?",
    boundary:
      "Legacy deterministic cue candidates only; not prompt correctness, task value, or developer skill.",
    expectedMetricCount: 5,
    metrics: [
      { key: "prompt.goal_definition", version: 1 },
      { key: "prompt.constraint_resolution", version: 1 },
      { key: "prompt.completion_evaluability", version: 1 },
      { key: "prompt.deliverable_contract", version: 1 },
      { key: "prompt.open_decision_load", version: 1 },
    ],
  },
  {
    id: "legacy-reasoning-trace",
    version: 1,
    dimension: "logic",
    label: "Observable logic trace",
    shortLabel: "Logic",
    question: "How did the legacy analysis connect observable requirements, plans, decisions, and loops?",
    boundary:
      "Legacy observable trace candidates only; hidden chain-of-thought is never accessed or inferred.",
    expectedMetricCount: 5,
    metrics: [
      { key: "logic.requirement_action_traceability", version: 1 },
      { key: "logic.plan_state_accounting", version: 1 },
      { key: "logic.decision_rationale_coverage", version: 1 },
      { key: "logic.scoped_consistency_candidate_rate", version: 1 },
      { key: "logic.conversation_loop_closure", version: 1 },
    ],
  },
] as const;

function orderedLensMetrics(
  definition: QualityLensDefinition,
  metrics: readonly QualityMetricObservation[],
): readonly QualityMetricObservation[] {
  const rank = new Map(
    definition.metrics.map(({ key, version }, index) => [
      `${key}@${version}`,
      index,
    ]),
  );
  const dimensionMetrics = metrics
    .map((metric, sourceIndex) => ({ metric, sourceIndex }))
    .filter(
      ({ metric }) =>
        rank.has(`${metric.definition.key}@${metric.definition.version}`),
    );
  const identities = dimensionMetrics.map(
    ({ metric }) => `${metric.definition.key}@${metric.definition.version}`,
  );
  if (new Set(identities).size !== identities.length) return [];
  return dimensionMetrics
    .sort((left, right) => {
      const leftRank = rank.get(
        `${left.metric.definition.key}@${left.metric.definition.version}`,
      );
      const rightRank = rank.get(
        `${right.metric.definition.key}@${right.metric.definition.version}`,
      );
      if (leftRank !== undefined && rightRank !== undefined) {
        return leftRank - rightRank;
      }
      if (leftRank !== undefined) return -1;
      if (rightRank !== undefined) return 1;
      return left.sourceIndex - right.sourceIndex;
    })
    .map(({ metric }) => metric);
}

/** Return only lenses represented by the supplied, already-bounded profile. */
export function qualityLensesFor(
  metrics: readonly QualityMetricObservation[],
): readonly ResolvedQualityLens[] {
  return QUALITY_LENSES.flatMap((definition) => {
    const lensMetrics = orderedLensMetrics(definition, metrics);
    return lensMetrics.length > 0 ? [{ definition, metrics: lensMetrics }] : [];
  });
}
