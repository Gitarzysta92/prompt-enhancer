export const METRIC_OPPORTUNITY_CATALOG_VERSION = 1 as const;

export type MetricOpportunityPriority = "P0" | "P1";
export type MetricOpportunityStatus =
  | "partial-foundation"
  | "not-measured"
  | "private-opt-in";
export type OpportunityMetricDirection =
  | "higher"
  | "lower"
  | "contextual";

export interface OpportunityMetricDefinition {
  key: string;
  label: string;
  direction: OpportunityMetricDirection;
}

export interface MetricOpportunityFamily {
  id: string;
  priority: MetricOpportunityPriority;
  status: MetricOpportunityStatus;
  title: string;
  question: string;
  whyItMatters: string;
  candidateMetrics: readonly OpportunityMetricDefinition[];
  evidenceToAdd: string;
  recommendedAction: string;
  validationGate: string;
  guardrail: string;
}

/**
 * Versioned specifications for high-value analysis that Coaching v1 does not
 * yet produce. These entries never create placeholder values. They make the
 * evidence and validation work visible so later post-processing can implement
 * one metric at a time without turning the roadmap into an overall score.
 */
export const METRIC_OPPORTUNITY_FAMILIES: readonly MetricOpportunityFamily[] = [
  {
    id: "user-value",
    priority: "P0",
    status: "partial-foundation",
    title: "Goal attainment & user value",
    question: "Did the verified output actually solve the user's intended problem?",
    whyItMatters:
      "A passing check can still miss the user's goal, while explicit acceptance can be incomplete or later reopened.",
    candidateMetrics: [
      {
        key: "value.accepted_requirement_coverage",
        label: "Accepted requirement coverage",
        direction: "higher",
      },
      {
        key: "value.explicit_goal_attainment",
        label: "Explicit goal attainment",
        direction: "higher",
      },
      {
        key: "value.user_usefulness_rating",
        label: "Optional usefulness rating",
        direction: "contextual",
      },
    ],
    evidenceToAdd:
      "Local requirement-level accept, partial-accept, reject, and reopen decisions plus an optional private usefulness response.",
    recommendedAction:
      "Let the user mark which requirements were useful and which remain open after reviewing objective evidence.",
    validationGate:
      "Report human acceptance beside objective verification; measure agreement and disagreement instead of merging them.",
    guardrail:
      "A positive rating never overrides a failing safety or verification check, and missing feedback remains unknown.",
  },
  {
    id: "quality-adjusted-delivery",
    priority: "P0",
    status: "not-measured",
    title: "Quality-adjusted delivery",
    question: "How much time, cost, and model usage produced each verified outcome?",
    whyItMatters:
      "Raw speed and token counts can reward incomplete work; efficiency becomes meaningful only after outcome quality is held constant.",
    candidateMetrics: [
      {
        key: "efficiency.time_to_first_verified_outcome",
        label: "Time to first verified outcome",
        direction: "lower",
      },
      {
        key: "efficiency.cost_per_verified_requirement",
        label: "Cost per verified requirement",
        direction: "lower",
      },
      {
        key: "efficiency.verified_outcomes_per_million_tokens",
        label: "Verified outcomes per 1M tokens",
        direction: "higher",
      },
    ],
    evidenceToAdd:
      "Complete timestamps, provider-reported usage or explicitly labeled estimates, price-table provenance, requirements, and objective checks.",
    recommendedAction:
      "Compare only within stable task, complexity, provider, and evidence-completeness strata, then show a quality-versus-cost/time Pareto view.",
    validationGate:
      "Require complete denominators and uncertainty intervals; independently validate token, price, and timing semantics for every provider cohort.",
    guardrail:
      "Never optimize cost or latency by accepting lower verified coverage, and do not call resource efficiency financial ROI without user-supplied value.",
  },
  {
    id: "oversight-autonomy",
    priority: "P0",
    status: "not-measured",
    title: "Oversight & autonomy calibration",
    question: "Did the agent ask for human attention when it mattered, without creating avoidable review load?",
    whyItMatters:
      "Human attention is finite. Too little escalation can hide risk; too much escalation can erase the benefit of delegation.",
    candidateMetrics: [
      {
        key: "oversight.appropriate_escalation_recall",
        label: "Appropriate escalation recall",
        direction: "higher",
      },
      {
        key: "oversight.unnecessary_escalation_rate",
        label: "Unnecessary escalation rate",
        direction: "lower",
      },
      {
        key: "oversight.recovery_after_intervention",
        label: "Verified recovery after intervention",
        direction: "higher",
      },
      {
        key: "oversight.planning_delegation_share",
        label: "Planning-decision delegation share",
        direction: "contextual",
      },
    ],
    evidenceToAdd:
      "Versioned task-risk classes, approval and intervention events, decision attribution, reversibility, and the later verified result.",
    recommendedAction:
      "Choose an explicit oversight tier per task and review false-negative and false-positive escalations separately.",
    validationGate:
      "Calibrate against multiple human reviewers using asymmetric error costs and report risk-coverage curves by task risk.",
    guardrail:
      "Delegation share is a work-style descriptor, not a quality or skill score; more or less autonomy is not universally better.",
  },
  {
    id: "downstream-durability",
    priority: "P0",
    status: "not-measured",
    title: "Downstream durability",
    question: "Did the accepted result remain correct and useful after the session ended?",
    whyItMatters:
      "Immediate verification misses later reopens, reversions, incidents, and defects that reveal fragile delivery.",
    candidateMetrics: [
      {
        key: "durability.reopen_rate",
        label: "Reopen rate",
        direction: "lower",
      },
      {
        key: "durability.revert_rate",
        label: "Revert rate",
        direction: "lower",
      },
      {
        key: "durability.escaped_defect_rate",
        label: "Linked escaped-defect rate",
        direction: "lower",
      },
    ],
    evidenceToAdd:
      "A declared follow-up window and local links from accepted work to later reopen, revert, failing-check, or incident events.",
    recommendedAction:
      "Attach a follow-up window to accepted work and distinguish changed requirements from regressions before calculating a rate.",
    validationGate:
      "Human-audit linkage precision and recall on a time-separated holdout, with censoring and incomplete follow-up reported.",
    guardrail:
      "A revert or reopen is not automatically agent failure; requirement changes and external incidents need separate reason codes.",
  },
  {
    id: "artifact-quality",
    priority: "P1",
    status: "not-measured",
    title: "Artifact quality profile",
    question: "Which task-relevant product qualities were objectively checked?",
    whyItMatters:
      "Functional correctness alone does not establish reliability, security, maintainability, compatibility, usability, performance, flexibility, or safety.",
    candidateMetrics: [
      {
        key: "artifact.quality_characteristic_coverage",
        label: "Applicable quality-characteristic coverage",
        direction: "higher",
      },
      {
        key: "artifact.quality_gate_pass_fraction",
        label: "Applicable quality-gate pass fraction",
        direction: "higher",
      },
      {
        key: "artifact.change_surface_proportionality",
        label: "Change-surface proportionality",
        direction: "contextual",
      },
    ],
    evidenceToAdd:
      "A task-selected quality profile and objective artifact checks such as tests, analyzers, performance probes, accessibility checks, or security scans.",
    recommendedAction:
      "Select only relevant product-quality characteristics at task start and map each one to an inspectable gate.",
    validationGate:
      "Validate every adapter and gate against the artifact type; preserve not-applicable and unknown instead of using a universal checklist.",
    guardrail:
      "Do not reward checklist volume, style conformity, or larger diffs; task relevance and objective evidence remain primary.",
  },
  {
    id: "measurement-trust",
    priority: "P0",
    status: "partial-foundation",
    title: "Measurement trust",
    question: "How reliable, calibrated, stable, and in-distribution is each estimate?",
    whyItMatters:
      "A precise-looking ratio can be wrong, unstable, or applied outside the population on which its method was validated.",
    candidateMetrics: [
      {
        key: "measurement.model_human_agreement",
        label: "Model-human agreement",
        direction: "higher",
      },
      {
        key: "measurement.selective_risk",
        label: "Selective risk at stated coverage",
        direction: "lower",
      },
      {
        key: "measurement.repeatability_disagreement_rate",
        label: "Repeated-run disagreement rate",
        direction: "lower",
      },
      {
        key: "measurement.task_mix_shift",
        label: "Task-mix shift",
        direction: "contextual",
      },
    ],
    evidenceToAdd:
      "Independent human labels, repeated runs, counterfactual variants, cohort features, model revisions, and time-separated deployment samples.",
    recommendedAction:
      "Display coverage, uncertainty, calibration, stability, and drift beside every inferred result and withhold unsupported cohorts.",
    validationGate:
      "Pre-register human-human and model-human agreement, calibration, selective-risk, and drift thresholds by language and task type.",
    guardrail:
      "Confidence is not correctness, repeated agreement is not validity, and a synthetic benchmark never activates a private estimator.",
  },
  {
    id: "safety-governance",
    priority: "P0",
    status: "partial-foundation",
    title: "Safety, privacy & user control",
    question: "Did the workflow stay within its authority, data, and recovery boundaries?",
    whyItMatters:
      "A useful result can still create unacceptable risk through unsafe actions, excessive data exposure, or missing user control.",
    candidateMetrics: [
      {
        key: "safety.policy_conformance",
        label: "Policy-conforming action coverage",
        direction: "higher",
      },
      {
        key: "safety.remote_approval_coverage",
        label: "Remote approval coverage",
        direction: "higher",
      },
      {
        key: "safety.privacy_canary_leakage",
        label: "Privacy canary leakage",
        direction: "lower",
      },
      {
        key: "safety.user_control_recovery",
        label: "User-control and recovery coverage",
        direction: "higher",
      },
    ],
    evidenceToAdd:
      "Versioned policies, action risk classes, approvals, redaction tests, remote-exposure receipts, user overrides, rollback, and deletion tests.",
    recommendedAction:
      "Treat safety and privacy checks as release gates and show the exact failed boundary rather than blending them into quality.",
    validationGate:
      "Adversarial, privacy-canary, fail-safe, rollback, and user-control tests must pass for every supported provider and action class.",
    guardrail:
      "Safety is not a tradeable radar spoke; a serious failing gate blocks the action regardless of strengths elsewhere.",
  },
  {
    id: "recommendation-effect",
    priority: "P0",
    status: "not-measured",
    title: "Recommendation effectiveness",
    question: "Was the recommendation applicable, tried faithfully, and beneficial on a later comparable task?",
    whyItMatters:
      "A plausible recommendation creates no user value until its adoption, cost, outcome effect, and possible downside are observed.",
    candidateMetrics: [
      {
        key: "recommendation.adoption_rate",
        label: "Recommendation adoption rate",
        direction: "contextual",
      },
      {
        key: "recommendation.execution_fidelity",
        label: "Experiment execution fidelity",
        direction: "higher",
      },
      {
        key: "recommendation.verified_uplift",
        label: "Matched verified-outcome uplift",
        direction: "contextual",
      },
      {
        key: "recommendation.adverse_effect_rate",
        label: "Recommendation adverse-effect rate",
        direction: "lower",
      },
    ],
    evidenceToAdd:
      "A versioned recommendation offer, explicit try/decline state, observable implementation receipt, comparable baseline, outcome, and effort cost.",
    recommendedAction:
      "Offer one reversible experiment with a success check and guardrail, then compare a later matched task without pressuring adoption.",
    validationGate:
      "Use randomized or matched within-stratum comparisons with confidence intervals; separate adoption selection from treatment effect.",
    guardrail:
      "Do not infer that non-adoption is resistance or that a time-series correlation proves the recommendation caused improvement.",
  },
  {
    id: "ease-sustainable-use",
    priority: "P1",
    status: "private-opt-in",
    title: "Ease & sustainable use",
    question: "Did the workflow reduce friction without increasing overload or weakening understanding?",
    whyItMatters:
      "Speed can coexist with exhausting oversight, interruptions, or reduced comprehension; telemetry alone cannot establish the user's experience.",
    candidateMetrics: [
      {
        key: "experience.workflow_ease_self_report",
        label: "Optional workflow-ease response",
        direction: "contextual",
      },
      {
        key: "experience.oversight_time_share",
        label: "Oversight time share",
        direction: "contextual",
      },
      {
        key: "experience.interruption_recovery_time",
        label: "Interruption recovery time",
        direction: "lower",
      },
      {
        key: "experience.explanation_request_coverage",
        label: "Explanation-request coverage",
        direction: "contextual",
      },
    ],
    evidenceToAdd:
      "Optional private self-report, explicit interruption/resumption events, active review intervals, and user-requested explanation events.",
    recommendedAction:
      "Ask one optional local question about ease and pair it with workflow telemetry; let the user disable or delete it independently.",
    validationGate:
      "Use validated short-form self-report items and longitudinal within-person analysis; never infer wellbeing or comprehension from prose.",
    guardrail:
      "These signals stay private and must never be exported for ranking, performance review, or cognitive assessment.",
  },
] as const;
