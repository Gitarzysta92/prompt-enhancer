export interface MetricDecisionGuidance {
  role:
    | "Specification signal"
    | "Collaboration signal"
    | "Traceability signal"
    | "Outcome evidence"
    | "Friction signal";
  whyItMatters: string;
  reviewNext: string;
  tryNext: string;
  confirmWith: string;
}

export type MetricGuidanceAudience = "user" | "agent" | "tooling" | "workflow";
export type MetricGuidanceBasis = "measured" | "experimental" | "readiness" | "method-only";

export interface SessionMetricGuidance {
  audience: MetricGuidanceAudience;
  action: string;
  verification: string;
  basis: MetricGuidanceBasis;
  factorKeys: readonly string[];
}

export interface SessionMetricGuidanceInput {
  state: "known" | "unknown" | "not_applicable" | "abstained" | "execution_error" | "pending" | "missing";
  numericValue: number | null;
  direction: "higher_is_better" | "lower_is_better";
  explanationCode?: string | null;
  factorKeys?: readonly string[];
  experimentalOnly?: boolean;
}

type MetricReviewGuidance = Pick<
  MetricDecisionGuidance,
  "role" | "whyItMatters" | "reviewNext"
>;

const DEFAULT_GUIDANCE: MetricDecisionGuidance = {
  role: "Traceability signal",
  whyItMatters:
    "This observation can focus a review, but it has not been calibrated as a universal quality measure.",
  reviewNext:
    "Inspect the raw numerator, denominator, coverage, and evidence boundary before changing the workflow.",
  tryNext:
    "Choose one reversible change for the next comparable task instead of optimizing every cue at once.",
  confirmWith:
    "Compare objective evidence and the same versioned metric on a later task with similar scope.",
};

/**
 * Decision guidance is deliberately separate from metric math. It explains a
 * useful review action without changing the persisted value or implying that a
 * lexical candidate causes task success.
 */
const METRIC_GUIDANCE = {
  "prompt.task_definition_coverage": {
    role: "Specification signal",
    whyItMatters:
      "A visible action, target, and intended outcome make the requested change easier to bound and verify.",
    reviewNext:
      "Check which of action, target, or intended outcome was not observable in the focus request.",
  },
  "prompt.problem_evidence_quality": {
    role: "Specification signal",
    whyItMatters:
      "Diagnosis is more reproducible when observed behavior, expected behavior, reproduction, and environment are explicit.",
    reviewNext:
      "Add only the missing diagnostic evidence that is available; do not invent an environment or reproduction step.",
  },
  "prompt.context_sufficiency": {
    role: "Specification signal",
    whyItMatters:
      "Current state, environment, and scope boundaries reduce avoidable discovery work and unsafe assumptions.",
    reviewNext:
      "Identify whether current state, environment or version, or the relevant boundary is genuinely missing.",
  },
  "prompt.constraint_precision": {
    role: "Specification signal",
    whyItMatters:
      "Concrete limits and prohibitions make trade-offs visible and acceptance checks less ambiguous.",
    reviewNext:
      "Replace vague constraint wording with the smallest truthful boundary, platform, version, or threshold.",
  },
  "prompt.acceptance_testability": {
    role: "Specification signal",
    whyItMatters:
      "Observable pass conditions let objective verification outrank an assistant's completion claim.",
    reviewNext:
      "For each active requirement, name the check or artifact that would demonstrate completion.",
  },
  "prompt.deliverable_contract": {
    role: "Specification signal",
    whyItMatters:
      "Explicit output form, location, audience, or compatibility prevents a correct idea from arriving in the wrong shape.",
    reviewNext:
      "Confirm the required format or interface only where the task actually constrains it.",
  },
  "collaboration.ambiguity_resolution": {
    role: "Collaboration signal",
    whyItMatters:
      "Closing material ambiguity before execution reduces branching work and incompatible interpretations.",
    reviewNext:
      "Review unresolved ambiguity candidates and decide whether each needs a question, assumption, or explicit deferral.",
  },
  "collaboration.clarification_yield": {
    role: "Collaboration signal",
    whyItMatters:
      "A clarification is useful when it obtains information that changes or confirms the execution path.",
    reviewNext:
      "Check whether unanswered questions were necessary and whether answers were incorporated into the plan.",
  },
  "collaboration.exploration_conversion": {
    role: "Collaboration signal",
    whyItMatters:
      "Exploration creates value when a hypothesis becomes a decision, action, or verification step.",
    reviewNext:
      "Link each still-relevant hypothesis to a next test, decision, or explicit stop condition.",
  },
  "collaboration.scope_change_discipline": {
    role: "Collaboration signal",
    whyItMatters:
      "Acknowledged scope changes keep the plan and acceptance boundary synchronized with the user's latest intent.",
    reviewNext:
      "Confirm that each material scope change updated the active plan, deliverable, or verification target.",
  },
  "collaboration.rework_candidate_rate": {
    role: "Friction signal",
    whyItMatters:
      "Correction markers can reveal avoidable misunderstanding, but they can also reflect healthy iteration or a changed request.",
    reviewNext:
      "Inspect the candidate corrections individually and separate misunderstanding from new information or preference changes.",
  },
  "logic.decomposition_coverage": {
    role: "Traceability signal",
    whyItMatters:
      "Requirement-to-plan links make omitted work and unsupported plan items easier to spot before implementation.",
    reviewNext:
      "Review active requirements without a plan link and decide whether they are missing, deferred, or not applicable.",
  },
  "logic.hypothesis_test_linkage": {
    role: "Traceability signal",
    whyItMatters:
      "A hypothesis linked to a discriminating check supports diagnosis instead of unbounded trial and error.",
    reviewNext:
      "For each active hypothesis, identify the evidence that would support or reject it.",
  },
  "logic.decision_rationale_coverage": {
    role: "Traceability signal",
    whyItMatters:
      "Visible rationale preserves the constraint or evidence behind a choice without exposing hidden chain-of-thought.",
    reviewNext:
      "Record the decisive constraint, evidence, or trade-off for choices that future work may need to revisit.",
  },
  "logic.requirement_action_traceability": {
    role: "Traceability signal",
    whyItMatters:
      "Requirement-to-action links show whether execution addressed the requested work rather than adjacent activity.",
    reviewNext:
      "Inspect requirements without an action link and actions without a requirement or justified maintenance purpose.",
  },
  "logic.open_loop_closure": {
    role: "Traceability signal",
    whyItMatters:
      "Closed questions and decisions reduce hidden blockers and repeated clarification in later turns.",
    reviewNext:
      "Review open questions and mark each answered, explicitly deferred, superseded, or still blocking.",
  },
  "outcome.agent_claim_grounding": {
    role: "Outcome evidence",
    whyItMatters:
      "Material completion claims are more trustworthy when they point to an objective check, source, or inspectable artifact.",
    reviewNext:
      "Find ungrounded material claims and attach evidence or restate them as unverified.",
  },
  "outcome.verification_strategy_adequacy": {
    role: "Outcome evidence",
    whyItMatters:
      "A requirement-specific verification strategy reduces the chance that a green but irrelevant check is mistaken for success.",
    reviewNext:
      "Map each active requirement to the check family that can actually falsify an incorrect implementation.",
  },
  "outcome.first_pass_verification": {
    role: "Outcome evidence",
    whyItMatters:
      "First meaningful verification is a useful flow signal when task mix and objective evidence are comparable.",
    reviewNext:
      "If the first check failed, inspect whether the cause was implementation, environment, flaky infrastructure, or an unsuitable check.",
  },
  "outcome.verified_requirement_coverage": {
    role: "Outcome evidence",
    whyItMatters:
      "Passing evidence linked to active requirements is the strongest available basis for a completion claim.",
    reviewNext:
      "Review uncovered requirements and add evidence, record an explicit acceptance decision, or keep completion unknown.",
  },
} satisfies Readonly<Record<string, MetricReviewGuidance>>;

type MetricActionGuidance = Pick<
  MetricDecisionGuidance,
  "tryNext" | "confirmWith"
>;

const METRIC_ACTION_GUIDANCE = {
  "prompt.task_definition_coverage": {
    tryNext:
      "State the action, target, and observable end state in one compact task-contract sentence before execution.",
    confirmWith:
      "Check whether the first plan and final evidence point back to the same action, target, and end state.",
  },
  "prompt.problem_evidence_quality": {
    tryNext:
      "Record the smallest available observed/expected contrast, reproduction step, and environment detail before diagnosis.",
    confirmWith:
      "Confirm that the reproduction exhibits the issue and that the same check distinguishes the repaired state.",
  },
  "prompt.context_sufficiency": {
    tryNext:
      "Add one current-state fact, one environment or version fact, and the relevant boundary only when each changes the execution path.",
    confirmWith:
      "Check whether the agent can identify the correct artifact and boundary without an avoidable discovery or correction loop.",
  },
  "prompt.constraint_precision": {
    tryNext:
      "Convert the highest-impact vague constraint into one concrete limit, prohibition, platform, version, or threshold.",
    confirmWith:
      "Verify that the plan, implementation, and final check all preserve that exact boundary.",
  },
  "prompt.acceptance_testability": {
    tryNext:
      "Give each active requirement one falsifiable pass condition before implementation starts.",
    confirmWith:
      "Require a requirement-to-check link and the observed result; a green unrelated check does not count.",
  },
  "prompt.deliverable_contract": {
    tryNext:
      "Name the required artifact and only the format, location, audience, interface, or compatibility constraints that actually matter.",
    confirmWith:
      "Inspect the delivered artifact against those named slots rather than relying on a completion claim.",
  },
  "collaboration.ambiguity_resolution": {
    tryNext:
      "Resolve the one uncertainty most likely to change scope, architecture, safety, or acceptance; explicitly defer the rest.",
    confirmWith:
      "Check that the resulting decision appears in the revised plan and is not reopened without new evidence.",
  },
  "collaboration.clarification_yield": {
    tryNext:
      "Ask one decision-shaped question whose answer selects between materially different execution paths.",
    confirmWith:
      "Confirm that the answer changes or validates a plan item, constraint, assumption, or verification step.",
  },
  "collaboration.exploration_conversion": {
    tryNext:
      "End a bounded exploration with one selected hypothesis, the deciding evidence, and the next observable test.",
    confirmWith:
      "Look for a later plan, action, or verification item that names the same hypothesis and test.",
  },
  "collaboration.scope_change_discipline": {
    tryNext:
      "After a material scope change, restate the new in-scope work, exclusions, affected deliverable, and revised check.",
    confirmWith:
      "Verify that subsequent actions follow the latest boundary and that intentionally deferred work stays visible.",
  },
  "collaboration.rework_candidate_rate": {
    tryNext:
      "Turn one confirmed misunderstanding into an explicit task constraint before the next revision.",
    confirmWith:
      "Check whether the same correction category recurs, while separating new scope and preference changes from rework.",
  },
  "logic.decomposition_coverage": {
    tryNext:
      "Map each active requirement to one owned plan item and mark deferred or not-applicable requirements explicitly.",
    confirmWith:
      "Review requirements without a plan link and plan items without a requirement or justified support purpose.",
  },
  "logic.hypothesis_test_linkage": {
    tryNext:
      "Pair each active hypothesis with a discriminating check and a result that would support or reject it.",
    confirmWith:
      "Confirm that the selected check can distinguish competing explanations instead of merely collecting more activity.",
  },
  "logic.decision_rationale_coverage": {
    tryNext:
      "Record the decisive constraint, evidence, or trade-off for choices that are costly, uncertain, or likely to be revisited.",
    confirmWith:
      "Check whether a later reviewer can understand and safely reverse the choice without hidden reasoning.",
  },
  "logic.requirement_action_traceability": {
    tryNext:
      "Tag each material action with the requirement, verification need, or justified maintenance purpose it serves.",
    confirmWith:
      "Inspect unmatched requirements and unmatched actions before declaring the task complete.",
  },
  "logic.open_loop_closure": {
    tryNext:
      "Maintain a short list of open questions and mark each answered, superseded, deferred, or blocking.",
    confirmWith:
      "Check that no blocking question disappears from the final handoff without a resolution state.",
  },
  "outcome.agent_claim_grounding": {
    tryNext:
      "Attach every material completion or correctness claim to an observed check, source, or inspectable artifact.",
    confirmWith:
      "Sample the claims and verify that each cited item supports the same scope and does not merely show activity.",
  },
  "outcome.verification_strategy_adequacy": {
    tryNext:
      "Choose the check family that could falsify each requirement before implementation, including one relevant failure path.",
    confirmWith:
      "Verify requirement-to-check coverage and preserve unevaluable requirements as unknown.",
  },
  "outcome.first_pass_verification": {
    tryNext:
      "Run the smallest meaningful requirement-relevant check as soon as a coherent implementation slice exists.",
    confirmWith:
      "Classify a first failure as implementation, environment, flaky infrastructure, or unsuitable check before changing the workflow.",
  },
  "outcome.verified_requirement_coverage": {
    tryNext:
      "Close one uncovered requirement with objective evidence, explicit human acceptance, or an honest unresolved state.",
    confirmWith:
      "Recompute coverage from active requirements only and retain the exact evidence authority for every covered item.",
  },
} satisfies Readonly<
  Record<keyof typeof METRIC_GUIDANCE, MetricActionGuidance>
>;

export function metricDecisionGuidance(
  metricKey: string,
): MetricDecisionGuidance {
  const reviewGuidance = (
    METRIC_GUIDANCE as Readonly<Record<string, MetricReviewGuidance>>
  )[metricKey];
  const actionGuidance = (
    METRIC_ACTION_GUIDANCE as Readonly<Record<string, MetricActionGuidance>>
  )[metricKey];
  return {
    ...(reviewGuidance ?? DEFAULT_GUIDANCE),
    ...(actionGuidance ?? {
      tryNext: DEFAULT_GUIDANCE.tryNext,
      confirmWith: DEFAULT_GUIDANCE.confirmWith,
    }),
  };
}

function audienceFor(metricKey: string, explanationCode?: string | null): MetricGuidanceAudience {
  if (
    metricKey.startsWith("outcome.")
    || metricKey === "logic.hypothesis_test_linkage"
    || metricKey === "logic.requirement_action_traceability"
    || explanationCode?.includes("objective_")
    || explanationCode === "message_kind_unavailable"
  ) return "tooling";
  if (metricKey.startsWith("prompt.")) return "user";
  if (metricKey.startsWith("collaboration.")) return "workflow";
  return "agent";
}

function readableFactor(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

/**
 * Produce content-free, reviewed advice from the typed state and factor keys.
 * This never changes the metric and never fabricates a transcript-specific explanation.
 */
export function sessionMetricGuidance(
  metricKey: string,
  input: SessionMetricGuidanceInput,
): SessionMetricGuidance {
  const base = metricDecisionGuidance(metricKey);
  const factorKeys = [...new Set(input.factorKeys ?? [])].slice(0, 2);
  const audience = audienceFor(metricKey, input.explanationCode);
  if (input.state === "not_applicable") {
    return {
      audience,
      action: "No change is required for this metric because no eligible opportunity was observed in the selected scope.",
      verification: "Reassess only when a later request creates an eligible opportunity.",
      basis: "readiness",
      factorKeys,
    };
  }
  if (input.state === "execution_error") {
    return {
      audience: "tooling",
      action: "Keep the last valid value and repair or retry the failed local analysis stage.",
      verification: "Confirm that a fresh sealed receipt completes before comparing this metric.",
      basis: "method-only",
      factorKeys,
    };
  }
  if (input.state === "pending" || (input.state !== "known" && input.explanationCode === "episode_horizon_open")) {
    return {
      audience,
      action: "Nothing to change yet: the newest exchange is still open, so this metric is pending rather than measured or zero.",
      verification: "Re-measure once the follow-up message arrives and the episode closes; the value is only then decidable.",
      basis: "readiness",
      factorKeys,
    };
  }
  if (input.experimentalOnly) {
    return {
      audience,
      action: `If the experimental signal persists, ${base.tryNext.charAt(0).toLowerCase()}${base.tryNext.slice(1)}`,
      verification: base.confirmWith,
      basis: "experimental",
      factorKeys,
    };
  }
  if (input.state === "unknown" || input.state === "abstained" || input.state === "missing") {
    const objective = audience === "tooling";
    return {
      audience,
      action: objective
        ? "Connect the required local tool, test, artifact, action, or acceptance receipt; prose alone cannot establish this value."
        : "Keep this metric unknown until its required opportunity and evidence are observable.",
      verification: objective
        ? "Verify that the receipt is fresh, scoped to the active requirement, and produced by a supported local adapter."
        : base.confirmWith,
      basis: "readiness",
      factorKeys,
    };
  }
  if (input.numericValue === null) {
    return {
      audience,
      action: `If the experimental signal persists, ${base.tryNext.charAt(0).toLowerCase()}${base.tryNext.slice(1)}`,
      verification: base.confirmWith,
      basis: "experimental",
      factorKeys,
    };
  }
  const oriented = input.direction === "lower_is_better"
    ? 1 - input.numericValue
    : input.numericValue;
  // Reinforce only an exact, fully met observed fraction.  This is a receipt
  // fact, unlike an arbitrary quality threshold on an uncalibrated metric.
  if (oriented === 1) {
    return {
      audience,
      action: `Keep the observed practice: ${base.whyItMatters.charAt(0).toLowerCase()}${base.whyItMatters.slice(1)}`,
      verification: base.confirmWith,
      basis: "measured",
      factorKeys,
    };
  }
  const focus = factorKeys.length === 0
    ? ""
    : `Focus on ${factorKeys.map(readableFactor).join(" and ")}: `;
  return {
    audience,
    action: `${focus}${base.tryNext}`,
    verification: base.confirmWith,
    basis: "measured",
    factorKeys,
  };
}
