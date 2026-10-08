import type { SessionCoachingProjection } from "../../shared/api/contracts";
import type {
  CoachingLoopViewModel,
  CoachingSignalCategory,
  CoachingUnavailableReasonCode,
  ImprovedPromptTemplateCode,
} from "./coachingLoopModel";

type JsonRecord = Record<string, unknown>;

const SAFE_CODE = /^[a-z0-9][a-z0-9._-]{0,127}$/;
const TASK_TYPES = new Set([
  "implementation",
  "diagnosis",
  "research",
  "review",
  "planning",
  "unknown",
]);
const CONTEXT_SOURCES = new Set(["reviewed_task", "not_reviewed", "ambiguous"]);
const DECISION_STATES = new Set(["candidate", "supported", "abstained"]);
const EVIDENCE_KINDS = new Set([
  "objective_verification",
  "deterministic_candidate",
  "human_review",
  "assistant_claim",
]);
const EVIDENCE_TIERS = new Set([
  "metadata",
  "redacted_content",
  "objective_event",
  "human_review",
]);
const EVIDENCE_BASES = new Set([
  "objective.verification_results",
  "human.acceptance_decision",
  "rule.factor_counts",
  "rule.link_counts",
  "rule.correction_counts",
  "assistant.completion_claim",
]);
const HUMAN_ACCEPTANCE = new Set(["accepted", "rejected", "unknown"]);
const OUTCOME_STATUSES = new Set(["verified", "failed", "mixed", "unknown"]);
const DENOMINATOR_KINDS = new Set(["rubric_factor", "event_count"]);

const COMMON_KEYS = [
  "abstention_code",
  "algorithm_id",
  "algorithm_version",
  "candidate_policy_version",
  "code",
  "confidence",
  "construct_version",
  "coverage",
  "decision_state",
  "denominator",
  "denominator_kind",
  "denominator_kind_priority_version",
  "evidence_lower_bound",
  "evidence_upper_bound",
  "evidence_basis",
  "evidence_kind",
  "evidence_tier",
  "metric_basis",
  "pack_key",
  "pack_version",
  "polarity_successes",
  "recommendation_policy_version",
  "rule_priority_version",
  "source_provenance",
  "task_type",
] as const;

const ABSTENTION_REASONS: Record<string, CoachingUnavailableReasonCode> = {
  objective_evidence_missing: "evidence-missing",
  outcome_authority_incomplete: "insufficient-coverage",
  task_type_unknown: "unsupported-task",
  mixed_source_provenance: "method-abstained",
  supported_strength_missing: "not-observed",
  supported_friction_missing: "not-observed",
  evidence_backed_friction_missing: "not-observed",
};

const STRENGTH_CATEGORIES: Record<string, CoachingSignalCategory> = {
  "strength.testable_acceptance": "acceptance-criteria",
  "strength.task_contract": "task-framing",
  "strength.operating_context": "task-framing",
  "strength.precise_constraints": "task-framing",
  "strength.deliverable_contract": "task-framing",
  "strength.requirement_plan_trace": "exploration-to-plan",
  "strength.hypothesis_test_loop": "verification",
  "strength.scope_change_control": "scope-control",
  "strength.productive_clarification": "clarification",
  "strength.low_rework_signal": "rework",
};

const FRICTION_CATEGORIES: Record<string, CoachingSignalCategory> = {
  "friction.acceptance_before_implementation_unclear": "acceptance-criteria",
  "friction.task_contract_incomplete": "task-framing",
  "friction.operating_context_missing": "task-framing",
  "friction.constraints_not_operational": "task-framing",
  "friction.deliverable_contract_missing": "task-framing",
  "friction.requirements_not_traced_to_plan": "exploration-to-plan",
  "friction.hypotheses_not_linked_to_tests": "verification",
  "friction.scope_changes_not_replanned": "scope-control",
  "friction.clarification_not_converging": "clarification",
  "friction.rework_signal_high": "rework",
};

const EXPERIMENT_CATEGORIES: Record<string, CoachingSignalCategory> = {
  "experiment.define_acceptance_before_implementation": "acceptance-criteria",
  "experiment.state_goal_target_and_end_state": "task-framing",
  "experiment.add_minimum_operating_context": "task-framing",
  "experiment.convert_constraint_to_boundary": "task-framing",
  "experiment.define_deliverable_contract": "task-framing",
  "experiment.map_requirements_to_plan_items": "exploration-to-plan",
  "experiment.pair_each_hypothesis_with_test": "verification",
  "experiment.restate_scope_after_change": "scope-control",
  "experiment.answer_clarification_with_decision": "clarification",
  "experiment.confirm_contract_before_execution": "rework",
};

const TEMPLATE_CODES: Record<string, ImprovedPromptTemplateCode> = {
  "prompt_template.acceptance_first": "acceptance-first",
  "prompt_template.task_contract": "task-contract",
  "prompt_template.context_anchor": "context-anchor",
  "prompt_template.bounded_task": "scope-boundary",
  "prompt_template.deliverable_contract": "deliverable-contract",
  "prompt_template.requirement_plan_map": "requirement-plan-map",
  "prompt_template.hypothesis_test_loop": "hypothesis-test-loop",
  "prompt_template.scope_change": "scope-boundary",
  "prompt_template.clarification_decision": "clarify-first",
  "prompt_template.preflight_contract": "preflight-contract",
};

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: JsonRecord, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isSafeCode(value: unknown): value is string {
  return typeof value === "string" && SAFE_CODE.test(value);
}

function isSafeCodeArray(value: unknown, max = 8): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= max &&
    value.every(isSafeCode) &&
    new Set(value).size === value.length
  );
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNullableSafeCode(value: unknown): value is string | null {
  return value === null || isSafeCode(value);
}

function validProvenance(value: unknown): value is JsonRecord {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["algorithm_id", "algorithm_version", "pack_key", "pack_version"]) &&
    isSafeCode(value.algorithm_id) &&
    isSafeCode(value.algorithm_version) &&
    isSafeCode(value.pack_key) &&
    Number.isSafeInteger(value.pack_version) &&
    (value.pack_version as number) >= 1
  );
}

function commonDecisionValid(value: unknown, taskType: string): value is JsonRecord {
  if (!isRecord(value)) return false;
  if (
    !isSafeCode(value.code) ||
    !DECISION_STATES.has(String(value.decision_state)) ||
    !isSafeCodeArray(value.metric_basis) ||
    !isSafeCodeArray(value.evidence_basis) ||
    !(value.evidence_basis as string[]).every((basis) => EVIDENCE_BASES.has(basis)) ||
    !isNullableSafeCode(value.evidence_kind) ||
    (value.evidence_kind !== null && !EVIDENCE_KINDS.has(value.evidence_kind)) ||
    !isNullableSafeCode(value.evidence_tier) ||
    (value.evidence_tier !== null && !EVIDENCE_TIERS.has(value.evidence_tier)) ||
    !isNullableNumber(value.construct_version) ||
    !isNullableNumber(value.denominator) ||
    !isNullableSafeCode(value.denominator_kind) ||
    (value.denominator_kind !== null && !DENOMINATOR_KINDS.has(value.denominator_kind)) ||
    !isNullableNumber(value.polarity_successes) ||
    !isNullableNumber(value.evidence_lower_bound) ||
    !isNullableNumber(value.evidence_upper_bound) ||
    !isNullableNumber(value.confidence) ||
    (typeof value.confidence === "number" && (value.confidence < 0 || value.confidence > 1)) ||
    !isNullableNumber(value.coverage) ||
    !isNullableSafeCode(value.abstention_code) ||
    value.task_type !== taskType ||
    value.pack_key !== "coaching.loop" ||
    value.pack_version !== 1 ||
    value.algorithm_id !== "rules.coaching-loop.summary" ||
    value.algorithm_version !== "1" ||
    value.recommendation_policy_version !== 1 ||
    value.candidate_policy_version !== 2 ||
    value.denominator_kind_priority_version !== 1 ||
    value.rule_priority_version !== 1
  ) {
    return false;
  }
  if (value.decision_state === "abstained") {
    return (
      value.abstention_code !== null &&
      (value.metric_basis as string[]).length === 0 &&
      (value.evidence_basis as string[]).length === 0 &&
      value.evidence_kind === null &&
      value.evidence_tier === null &&
      value.construct_version === null &&
      value.denominator === null &&
      value.denominator_kind === null &&
      value.polarity_successes === null &&
      value.evidence_lower_bound === null &&
      value.evidence_upper_bound === null &&
      value.confidence === null &&
      value.coverage === null &&
      value.source_provenance === null
    );
  }
  return (
    value.abstention_code === null &&
    (value.metric_basis as string[]).length === 1 &&
    (value.evidence_basis as string[]).length >= 1 &&
    Number.isSafeInteger(value.construct_version) &&
    (value.construct_version as number) >= 1 &&
    Number.isSafeInteger(value.denominator) &&
    (value.denominator as number) >= 1 &&
    DENOMINATOR_KINDS.has(String(value.denominator_kind)) &&
    Number.isSafeInteger(value.polarity_successes) &&
    (value.polarity_successes as number) >= 0 &&
    (value.polarity_successes as number) <= (value.denominator as number) &&
    typeof value.evidence_lower_bound === "number" &&
    value.evidence_lower_bound >= 0 &&
    value.evidence_lower_bound <= 1 &&
    typeof value.evidence_upper_bound === "number" &&
    value.evidence_upper_bound >= value.evidence_lower_bound &&
    value.evidence_upper_bound <= 1 &&
    typeof value.coverage === "number" &&
    value.coverage >= 0 &&
    value.coverage <= 1 &&
    validProvenance(value.source_provenance)
  );
}

function validBasis(value: unknown, taskType: string, extraKeys: readonly string[] = []): value is JsonRecord {
  return (
    isRecord(value) &&
    hasExactKeys(value, [...COMMON_KEYS, ...extraKeys]) &&
    commonDecisionValid(value, taskType)
  );
}

function unavailableReason(value: JsonRecord): CoachingUnavailableReasonCode | null {
  return typeof value.abstention_code === "string"
    ? ABSTENTION_REASONS[value.abstention_code] ?? null
    : null;
}

function sameCandidateBasis(left: JsonRecord, right: JsonRecord): boolean {
  return JSON.stringify({
    metric_basis: left.metric_basis,
    evidence_basis: left.evidence_basis,
    denominator: left.denominator,
    denominator_kind: left.denominator_kind,
    polarity_successes: left.polarity_successes,
    evidence_lower_bound: left.evidence_lower_bound,
    evidence_upper_bound: left.evidence_upper_bound,
    coverage: left.coverage,
    source_provenance: left.source_provenance,
  }) === JSON.stringify({
    metric_basis: right.metric_basis,
    evidence_basis: right.evidence_basis,
    denominator: right.denominator,
    denominator_kind: right.denominator_kind,
    polarity_successes: right.polarity_successes,
    evidence_lower_bound: right.evidence_lower_bound,
    evidence_upper_bound: right.evidence_upper_bound,
    coverage: right.coverage,
    source_provenance: right.source_provenance,
  });
}

function candidateDecisionValid(
  value: JsonRecord,
  boundary?: "strength" | "friction",
): boolean {
  const clearsBoundary =
    boundary === "strength"
      ? Number(value.evidence_lower_bound) >= 0.75
      : boundary === "friction"
        ? Number(value.evidence_upper_bound) <= 0.25
        : true;
  return (
    value.decision_state === "candidate" &&
    value.confidence === null &&
    value.evidence_kind === "deterministic_candidate" &&
    value.evidence_tier === "redacted_content" &&
    (value.evidence_basis as string[]).every((basis) => basis.startsWith("rule.")) &&
    clearsBoundary
  );
}

function toReasonedState(value: JsonRecord) {
  const reasonCode = unavailableReason(value);
  return reasonCode
    ? ({ state: "abstained", category: null, reasonCode } as const)
    : null;
}

/**
 * Fail-closed adapter from the content-free API receipt to a closed UI model.
 * No backend prose, identifiers, evidence references, or transcript-derived
 * strings can cross this boundary.
 */
export function createCoachingLoopViewModel(
  input: unknown,
): CoachingLoopViewModel | null {
  if (
    !isRecord(input) ||
    !hasExactKeys(input, [
      "projection_key",
      "projection_version",
      "summary",
      "task_context_source",
      "task_type",
    ]) ||
    input.projection_key !== "coaching.loop.current" ||
    input.projection_version !== 1 ||
    !TASK_TYPES.has(String(input.task_type)) ||
    !CONTEXT_SOURCES.has(String(input.task_context_source)) ||
    !isRecord(input.summary)
  ) {
    return null;
  }
  const taskType = String(input.task_type);
  if (
    (input.task_context_source === "reviewed_task" && taskType === "unknown") ||
    (input.task_context_source !== "reviewed_task" && taskType !== "unknown") ||
    !hasExactKeys(input.summary, [
      "friction",
      "next_experiment",
      "outcome",
      "prompt_template",
      "strength",
    ])
  ) {
    return null;
  }
  const { strength, friction, next_experiment: experiment, prompt_template: template, outcome } = input.summary;
  if (
    !validBasis(strength, taskType) ||
    !validBasis(friction, taskType) ||
    !validBasis(experiment, taskType) ||
    !validBasis(template, taskType, ["slot_codes", "template_version"]) ||
    !validBasis(outcome, taskType, [
      "evidence_disagreement",
      "human_acceptance_status",
      "status",
    ]) ||
    !OUTCOME_STATUSES.has(String(outcome.status)) ||
    !HUMAN_ACCEPTANCE.has(String(outcome.human_acceptance_status)) ||
    typeof outcome.evidence_disagreement !== "boolean" ||
    !isSafeCodeArray(template.slot_codes) ||
    !isNullableNumber(template.template_version)
  ) {
    return null;
  }

  const strengthCategory = STRENGTH_CATEGORIES[String(strength.code)];
  const frictionCategory = FRICTION_CATEGORIES[String(friction.code)];
  const experimentCategory = EXPERIMENT_CATEGORIES[String(experiment.code)];
  const templateCode = TEMPLATE_CODES[String(template.code)];

  const strengthModel = strength.decision_state === "abstained"
    ? toReasonedState(strength)
    : strengthCategory && candidateDecisionValid(strength, "strength")
      ? ({ state: "available", category: strengthCategory, basis: "observed-text" } as const)
      : null;
  const frictionModel = friction.decision_state === "abstained"
    ? toReasonedState(friction)
    : frictionCategory && candidateDecisionValid(friction, "friction")
      ? ({ state: "available", category: frictionCategory, basis: "observed-text" } as const)
      : null;
  const experimentModel = experiment.decision_state === "abstained"
    ? toReasonedState(experiment)
    : experimentCategory && candidateDecisionValid(experiment) && sameCandidateBasis(friction, experiment)
      ? ({ state: "available", category: experimentCategory } as const)
      : null;
  const templateModel = template.decision_state === "abstained"
    ? (() => {
        const state = toReasonedState(template);
        return state ? { state: state.state, reasonCode: state.reasonCode } as const : null;
      })()
    : templateCode && candidateDecisionValid(template) && sameCandidateBasis(friction, template) && template.template_version === 1
      ? ({ state: "available", templateCode } as const)
      : null;
  if (!strengthModel || !frictionModel || !experimentModel || !templateModel) return null;

  let outcomeModel: CoachingLoopViewModel["outcome"];
  if (outcome.status === "unknown") {
    const reasonCode = unavailableReason(outcome);
    if (
      outcome.decision_state !== "abstained" ||
      outcome.code !== "outcome.unknown" ||
      outcome.evidence_disagreement !== false ||
      reasonCode === null
    ) {
      return null;
    }
    outcomeModel = { status: "unknown", basis: "none", reasonCode };
  } else {
    const expectedDisagreement =
      (outcome.status === "verified" && outcome.human_acceptance_status === "rejected") ||
      (outcome.status === "failed" && outcome.human_acceptance_status === "accepted");
    if (
      outcome.decision_state !== "supported" ||
      outcome.code !== `outcome.${String(outcome.status)}` ||
      outcome.evidence_kind !== "objective_verification" ||
      outcome.evidence_tier !== "objective_event" ||
      JSON.stringify(outcome.evidence_basis) !== JSON.stringify(["objective.verification_results"]) ||
      outcome.evidence_disagreement !== expectedDisagreement
    ) {
      return null;
    }
    outcomeModel = {
      status: outcome.status as "verified" | "failed" | "mixed",
      basis: "objective",
      evidenceCode: "automated-checks",
    };
  }

  const selectedCandidates = [strength, friction].filter(
    (decision) => decision.decision_state === "candidate",
  );
  const coverages = selectedCandidates.map((decision) => Number(decision.coverage));
  const evidence: CoachingLoopViewModel["evidence"] = coverages.length > 0
    ? {
        state: coverages.every((value) => value === 1) ? "complete" : "partial",
        minimumRatio: Math.min(...coverages),
        candidateCount: coverages.length,
      }
    : {
        state: taskType === "unknown" ? "abstained" : "unknown",
        reasonCode: taskType === "unknown" ? "unsupported-task" : "evidence-missing",
      };

  const uiTaskType = taskType === "unknown" ? "other" : taskType;
  const mixedProvenance = [strength, friction, experiment, template].some(
    (decision) => decision.abstention_code === "mixed_source_provenance",
  );
  return {
    assessment: {
      calibration: "candidate-unvalidated",
      taskType: uiTaskType as CoachingLoopViewModel["assessment"]["taskType"],
      evidenceTier: outcome.status === "unknown"
        ? coverages.length > 0
          ? "text-only"
          : "abstained"
        : "objective",
      methodCode: "deterministic-candidates-v1",
    },
    outcome: outcomeModel,
    strength: strengthModel,
    friction: frictionModel,
    nextExperiment: experimentModel,
    improvedPrompt: templateModel,
    evidence,
    details: {
      limitationCode: "human-review-required",
      provenanceCode: "local-versioned-run",
    },
    sharing: {
      status: "blocked",
      reasonCode: mixedProvenance ? "incoherent-evidence" : "uncalibrated",
    },
  };
}

export type { SessionCoachingProjection };
