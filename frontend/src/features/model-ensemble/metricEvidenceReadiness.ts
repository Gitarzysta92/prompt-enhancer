import {
  METRIC_CONTRACT_V2_PROJECTION_VERSIONS,
  METRIC_CONTRACT_V2_REGISTRY_VERSION,
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_V2_KEYS,
  isReviewedRequirementActionState,
  isReviewedRequirementPlanState,
  type MetricPublicationV2,
} from "../../shared/api/metricPublicationV2Contract";
import type {
  CapabilityKey,
  MetricEvidenceAvailabilityState,
  MetricEvidenceContributor,
  MetricEvidenceReadinessProjectionV2,
  MetricEvidenceReadinessV2,
} from "../../shared/api/contracts";

export type { MetricEvidenceAvailabilityState, MetricEvidenceContributor };

/** Closed adapter authorities used by the five objective V2 contracts. */
export type MetricEvidenceAdapterCapability = Extract<CapabilityKey,
  | "tool_events"
  | "decision_events"
  | "verification_events"
  | "requirement_opportunities"
  | "hypothesis_opportunities"
  | "material_claim_opportunities"
  | "verification_task_opportunities"
  | "requirement_evidence_links"
  | "hypothesis_evidence_links"
  | "material_claim_evidence_links"
  | "verification_task_evidence_links">;

const OBJECTIVE_ADAPTER_CAPABILITIES: Readonly<Record<string, readonly MetricEvidenceAdapterCapability[]>> = {
  "logic.hypothesis_test_linkage": [
    "hypothesis_opportunities", "hypothesis_evidence_links", "tool_events",
    "decision_events", "verification_events",
  ],
  "logic.requirement_action_traceability": [
    "requirement_opportunities", "requirement_evidence_links", "tool_events",
  ],
  "outcome.agent_claim_grounding": [
    "material_claim_opportunities", "material_claim_evidence_links", "verification_events",
  ],
  "outcome.first_pass_verification": [
    "verification_task_opportunities", "verification_task_evidence_links", "verification_events",
  ],
  "outcome.verified_requirement_coverage": [
    "requirement_opportunities", "requirement_evidence_links", "verification_events",
  ],
};

const METRIC_EVIDENCE_CONTRIBUTORS: Readonly<Record<string, readonly MetricEvidenceContributor[]>> = {
  "prompt.task_definition_coverage": ["focus_owned_request_revision", "rubric_factor_calculator"],
  "prompt.problem_evidence_quality": ["focus_owned_request_revision", "rubric_factor_calculator"],
  "prompt.context_sufficiency": ["focus_owned_request_revision", "rubric_factor_calculator"],
  "prompt.constraint_precision": ["declared_task_profile", "canonical_request_text"],
  "prompt.acceptance_testability": ["declared_task_profile", "canonical_request_text"],
  "prompt.deliverable_contract": ["declared_task_profile", "canonical_request_text"],
  "collaboration.ambiguity_resolution": ["semantic_unit_heads", "agent_response_text"],
  "collaboration.clarification_yield": ["semantic_unit_heads", "agent_response_text"],
  "collaboration.exploration_conversion": ["semantic_unit_heads", "typed_action_evidence"],
  "collaboration.scope_change_discipline": ["semantic_unit_heads", "agent_response_text"],
  "collaboration.rework_candidate_rate": ["semantic_unit_heads", "feedback_classification"],
  "logic.decomposition_coverage": ["semantic_unit_heads", "agent_response_text"],
  "logic.hypothesis_test_linkage": [
    "declared_objective_opportunity_set", "typed_action_evidence",
    "typed_decision_evidence", "typed_verification_receipt",
  ],
  "logic.decision_rationale_coverage": ["semantic_unit_heads", "agent_response_text"],
  "logic.requirement_action_traceability": ["declared_objective_opportunity_set", "typed_action_evidence"],
  "logic.open_loop_closure": ["semantic_unit_heads", "agent_response_text"],
  "outcome.agent_claim_grounding": ["declared_objective_opportunity_set", "typed_verification_receipt"],
  "outcome.verification_strategy_adequacy": ["semantic_unit_heads", "agent_response_text"],
  "outcome.first_pass_verification": ["declared_objective_opportunity_set", "typed_verification_receipt"],
  "outcome.verified_requirement_coverage": ["declared_objective_opportunity_set", "typed_verification_receipt"],
};

const METRIC_EVIDENCE_CONTRIBUTORS_R3: Readonly<Record<string, readonly MetricEvidenceContributor[]>> = {
  "logic.open_loop_closure": ["documented_plan_message", "explicit_plan_supersession_link"],
};

const R4_LIFECYCLE_METRIC_KEYS = new Set([
  "collaboration.ambiguity_resolution",
  "collaboration.clarification_yield",
  "collaboration.exploration_conversion",
  "collaboration.scope_change_discipline",
  "collaboration.rework_candidate_rate",
]);

const R3_REQUIREMENT_PROJECTIONS = new Set<MetricPublicationV2["projection_version"]>([
  "metric-contract-v2-projection-3",
  "metric-contract-v2-projection-4",
  "metric-contract-v2-projection-5",
  "metric-contract-v2-projection-6",
  "metric-contract-v2-projection-7",
  "metric-contract-v2-projection-8",
]);
const R4_LIFECYCLE_PROJECTIONS = new Set<MetricPublicationV2["projection_version"]>([
  "metric-contract-v2-projection-4",
  "metric-contract-v2-projection-5",
  "metric-contract-v2-projection-6",
  "metric-contract-v2-projection-7",
  "metric-contract-v2-projection-8",
]);

const METRIC_EVIDENCE_CONTRIBUTORS_R4: Readonly<Record<string, readonly MetricEvidenceContributor[]>> =
  Object.fromEntries([...R4_LIFECYCLE_METRIC_KEYS].map((metricKey) => [metricKey, [
    "confirmed_lifecycle_enumeration",
    "confirmed_lifecycle_opportunity",
    "confirmed_lifecycle_outcome_link",
  ] as const]));

const METRIC_EVIDENCE_CONTRIBUTORS_R6: Readonly<Record<string, readonly MetricEvidenceContributor[]>> = {
  "logic.decomposition_coverage": [
    "reviewed_requirement_enumeration",
    "reviewed_requirement_plan_disposition",
  ],
};

const METRIC_EVIDENCE_CONTRIBUTORS_R7: Readonly<Record<string, readonly MetricEvidenceContributor[]>> = {
  "logic.requirement_action_traceability": [
    "reviewed_requirement_enumeration",
    "reviewed_requirement_action_link",
    "safe_action_candidate_enumeration",
  ],
};

const CAPABILITY_MISSING_REASONS = {
  "prompt.task_definition_coverage": "focus_owned_request_revision_required",
  "prompt.problem_evidence_quality": "focus_owned_request_revision_required",
  "prompt.context_sufficiency": "focus_owned_request_revision_required",
  "prompt.constraint_precision": "owned_canonical_request_text_required",
  "prompt.acceptance_testability": "owned_canonical_request_text_required",
  "prompt.deliverable_contract": "owned_canonical_request_text_required",
  "collaboration.ambiguity_resolution": "ambiguity_episode_extraction_required",
  "collaboration.clarification_yield": "clarification_episode_extraction_required",
  "collaboration.exploration_conversion": "hypothesis_episode_extraction_required",
  "collaboration.scope_change_discipline": "scope_change_episode_extraction_required",
  "collaboration.rework_candidate_rate": "feedback_unit_extraction_required",
  "logic.decomposition_coverage": "requirement_unit_extraction_required",
  "logic.hypothesis_test_linkage": "hypothesis_chain_adapter_capabilities_required",
  "logic.decision_rationale_coverage": "decision_unit_extraction_required",
  "logic.requirement_action_traceability": "requirement_action_adapter_capabilities_required",
  "logic.open_loop_closure": "open_loop_episode_extraction_required",
  "outcome.agent_claim_grounding": "material_claim_verification_adapter_capabilities_required",
  "outcome.verification_strategy_adequacy": "request_revision_unit_extraction_required",
  "outcome.first_pass_verification": "verification_task_outcome_adapter_capabilities_required",
  "outcome.verified_requirement_coverage": "requirement_verification_adapter_capabilities_required",
} as const satisfies Readonly<Record<
  typeof METRIC_V2_KEYS[number],
  MetricEvidenceReadinessV2["reason_code"]
>>;

export function metricEvidenceRequirementFor(
  metricKey: string,
  projectionVersion: MetricPublicationV2["projection_version"],
): {
  requiredContributors: readonly MetricEvidenceContributor[];
  requiredAdapterCapabilities: readonly MetricEvidenceAdapterCapability[];
  capabilityMissingReason: MetricEvidenceReadinessV2["reason_code"] | null;
} {
  const projectionContributors = [
    "metric-contract-v2-projection-7",
    "metric-contract-v2-projection-8",
  ].includes(projectionVersion)
    ? METRIC_EVIDENCE_CONTRIBUTORS_R7[metricKey]
      ?? METRIC_EVIDENCE_CONTRIBUTORS_R6[metricKey]
      ?? METRIC_EVIDENCE_CONTRIBUTORS_R4[metricKey]
      ?? METRIC_EVIDENCE_CONTRIBUTORS_R3[metricKey]
    : projectionVersion === "metric-contract-v2-projection-6"
    ? METRIC_EVIDENCE_CONTRIBUTORS_R6[metricKey]
      ?? METRIC_EVIDENCE_CONTRIBUTORS_R4[metricKey]
      ?? METRIC_EVIDENCE_CONTRIBUTORS_R3[metricKey]
    : R4_LIFECYCLE_PROJECTIONS.has(projectionVersion)
    ? METRIC_EVIDENCE_CONTRIBUTORS_R4[metricKey] ?? METRIC_EVIDENCE_CONTRIBUTORS_R3[metricKey]
    : R3_REQUIREMENT_PROJECTIONS.has(projectionVersion)
      ? METRIC_EVIDENCE_CONTRIBUTORS_R3[metricKey]
      : undefined;
  return {
    requiredContributors: projectionContributors ?? METRIC_EVIDENCE_CONTRIBUTORS[metricKey] ?? [],
    requiredAdapterCapabilities: OBJECTIVE_ADAPTER_CAPABILITIES[metricKey] ?? [],
    capabilityMissingReason: [
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(projectionVersion)
      && metricKey === "logic.requirement_action_traceability"
      ? "reviewed_requirement_action_service_required"
      : [
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(projectionVersion)
      && metricKey === "logic.decomposition_coverage"
      ? "reviewed_requirement_plan_service_required"
      : R4_LIFECYCLE_PROJECTIONS.has(projectionVersion)
      && R4_LIFECYCLE_METRIC_KEYS.has(metricKey)
      ? "confirmed_lifecycle_service_required"
      : R3_REQUIREMENT_PROJECTIONS.has(projectionVersion)
        && metricKey === "logic.open_loop_closure"
        ? "explicit_plan_episode_required"
        : CAPABILITY_MISSING_REASONS[metricKey as keyof typeof CAPABILITY_MISSING_REASONS] ?? null,
  };
}

export type MetricEvidenceReadinessRowV2 = MetricEvidenceReadinessV2;
export type { MetricEvidenceReadinessProjectionV2 };

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const CONTRIBUTORS: readonly MetricEvidenceContributor[] = [
  "focus_owned_request_revision", "canonical_request_text", "declared_task_profile",
  "rubric_factor_calculator", "semantic_unit_heads", "agent_response_text",
  "feedback_classification", "declared_objective_opportunity_set", "documented_plan_message",
  "explicit_plan_supersession_link", "confirmed_lifecycle_enumeration",
  "confirmed_lifecycle_opportunity", "confirmed_lifecycle_outcome_link", "typed_action_evidence",
  "reviewed_requirement_enumeration", "reviewed_requirement_plan_disposition",
  "reviewed_requirement_action_link", "safe_action_candidate_enumeration",
  "typed_decision_evidence", "typed_verification_receipt",
];
const AVAILABILITY: readonly MetricEvidenceAvailabilityState[] = [
  "measured", "pending_right_censored", "no_opportunity", "capability_missing",
  "source_incomplete", "evidence_unresolved", "abstained", "execution_error",
];
const PROJECTION_KEYS = [
  "projection_key", "projection_version", "catalog_version", "registry_version",
  "publication_key", "publication_version", "publication_source",
  "canonical_live_snapshot", "compatibility_preview", "contract_set_fingerprint",
  "publication_fingerprint", "metric_projection_version", "provider",
  "provider_version", "adapter_version", "source_schema_version", "metrics",
  "measured_count", "pending_count", "no_opportunity_count",
  "capability_missing_count", "source_incomplete_count", "evidence_unresolved_count",
  "abstained_count", "execution_error_count", "objective_metric_count",
  "objective_measurable_count", "objective_measured_count", "local_only",
  "content_persisted", "calibration_state", "product_metric_eligible",
] as const;
const READINESS_ROW_KEYS = [
  "metric_key", "contract_version", "contract_fingerprint", "evidence_authority",
  "denominator_basis", "opportunity_unit_kind", "value_state", "availability_state",
  "reason_code", "required_contributors", "observed_contributors",
  "missing_contributors", "required_adapter_capabilities", "capability_available",
  "source_complete", "eligible_count", "met_count", "not_met_count",
  "pending_count", "unknown_count", "resolved_count", "censoring_lower_bound",
  "censoring_upper_bound", "calibration_state", "product_metric_eligible",
] as const;

function row(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function contributorList(value: unknown): readonly MetricEvidenceContributor[] | null {
  return Array.isArray(value)
    && value.every((item) => typeof item === "string" && CONTRIBUTORS.includes(item as MetricEvidenceContributor))
    && new Set(value).size === value.length
    ? value as MetricEvidenceContributor[]
    : null;
}

function capabilityList(value: unknown): readonly MetricEvidenceAdapterCapability[] | null {
  return Array.isArray(value)
    && value.every((item) => typeof item === "string")
    && new Set(value).size === value.length
    ? value as MetricEvidenceAdapterCapability[]
    : null;
}

function sameOrderedValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length
    && actual.every((key, index) => key === sortedExpected[index]);
}

function expectedObservedContributors(
  sealed: MetricPublicationV2["metrics"][number]["state"],
  required: readonly MetricEvidenceContributor[],
): readonly MetricEvidenceContributor[] {
  const statistics = sealed.statistics;
  if (!statistics.capability_available) return [];
  const resolved = statistics.met_count + statistics.not_met_count;
  if (
    sealed.projection_version === "metric-contract-v2-projection-8"
    && sealed.metric_key === "outcome.verified_requirement_coverage"
  ) {
    return statistics.source_complete
      && (sealed.value_state === "not_applicable" || statistics.eligible_count > 0)
      ? ["declared_objective_opportunity_set"]
      : [];
  }
  if (
    ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      sealed.projection_version,
    )
    && sealed.metric_key === "logic.requirement_action_traceability"
  ) {
    return ["known", "pending", "not_applicable"].includes(sealed.value_state)
      && statistics.source_complete
      ? [
          "reviewed_requirement_enumeration",
          "reviewed_requirement_action_link",
          "safe_action_candidate_enumeration",
        ]
      : [];
  }
  if (
    [
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(sealed.projection_version)
    && sealed.metric_key === "logic.decomposition_coverage"
  ) {
    const observed: MetricEvidenceContributor[] = [];
    if (
      statistics.source_complete
      && (sealed.value_state === "not_applicable" || statistics.eligible_count > 0)
    ) observed.push("reviewed_requirement_enumeration");
    if (statistics.eligible_count > 0) observed.push("reviewed_requirement_plan_disposition");
    return observed;
  }
  if (
    R4_LIFECYCLE_PROJECTIONS.has(sealed.projection_version)
    && R4_LIFECYCLE_METRIC_KEYS.has(sealed.metric_key)
  ) {
    const observed: MetricEvidenceContributor[] = [];
    if (statistics.source_complete) observed.push("confirmed_lifecycle_enumeration");
    if (statistics.eligible_count > 0) observed.push("confirmed_lifecycle_opportunity");
    if (resolved > 0) observed.push("confirmed_lifecycle_outcome_link");
    return observed;
  }
  if (
    [
      "metric-contract-v2-projection-5",
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(
      sealed.projection_version,
    )
    && statistics.denominator_basis === "declared_profile_slots"
    && statistics.eligible_count === 0
  ) return [];
  const observed = resolved === 0 && !statistics.source_complete
    ? []
    : resolved === 0
      ? required.slice(0, 1)
      : [...required];
  return sealed.projection_version === "metric-contract-v2-projection-1"
    && statistics.denominator_basis === "rubric_factors"
    ? observed.filter((item) => item !== "focus_owned_request_revision")
    : observed;
}

function integer(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 1_000_000;
}

function optionalBound(value: unknown): value is number | null | undefined {
  return value === null || value === undefined
    || (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1);
}

interface ExpectedReadinessVerdict {
  availability: MetricEvidenceAvailabilityState;
  reason: MetricEvidenceReadinessV2["reason_code"];
}

/**
 * Mirror the backend's structural verdict derivation from the sealed state.
 * Producer-authored explanation/reason prose is deliberately ignored: for one
 * immutable state shape and projection there is exactly one legal readiness
 * reason, so a wire payload cannot redirect remediation while preserving all
 * of the measured facts.
 */
function expectedReadinessVerdict(
  sealed: MetricPublicationV2["metrics"][number]["state"],
  capabilityMissingReason: MetricEvidenceReadinessV2["reason_code"] | null,
): ExpectedReadinessVerdict | null {
  const statistics = sealed.statistics;
  if (sealed.value_state === "execution_error") {
    return { availability: "execution_error", reason: "execution_error_reported" };
  }
  if (sealed.value_state === "abstained") {
    return { availability: "abstained", reason: "calculator_abstained" };
  }
  if (
    ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      sealed.projection_version,
    )
    && sealed.metric_key === "logic.requirement_action_traceability"
    && sealed.value_state === "unknown"
  ) {
    const exact = {
      requirement_action_evidence_unavailable: {
        shape: !statistics.capability_available && statistics.source_complete
          && statistics.met_count === 0
          && statistics.not_met_count === 0
          && statistics.pending_count === 0
          && statistics.unknown_count === statistics.eligible_count,
        availability: "capability_missing" as const,
        reason: "reviewed_requirement_action_service_required" as const,
      },
      requirement_action_evidence_confirmation_required: {
        shape: statistics.capability_available && statistics.source_complete
          && statistics.unknown_count === statistics.eligible_count,
        availability: "evidence_unresolved" as const,
        reason: "reviewed_requirement_action_confirmation_required" as const,
      },
      requirement_action_evidence_invalid: {
        shape: statistics.capability_available && !statistics.source_complete
          && statistics.unknown_count === statistics.eligible_count,
        availability: "source_incomplete" as const,
        reason: "reviewed_requirement_action_binding_invalid" as const,
      },
      requirement_action_evidence_overflow: {
        shape: statistics.capability_available && statistics.source_complete
          && statistics.met_count === 0
          && statistics.not_met_count === 0
          && statistics.pending_count === 0
          && statistics.unknown_count === statistics.eligible_count,
        availability: "evidence_unresolved" as const,
        reason: "opportunity_set_exceeds_receipt_bound" as const,
      },
      requirement_action_candidate_source_incomplete: {
        shape: statistics.capability_available && !statistics.source_complete
          && statistics.unknown_count === statistics.eligible_count,
        availability: "source_incomplete" as const,
        reason: "requirement_action_adapter_capabilities_required" as const,
      },
    }[sealed.explanation_code];
    return exact?.shape ? { availability: exact.availability, reason: exact.reason } : null;
  }
  if (sealed.value_state === "known") {
    const supersededRubric = sealed.projection_version === "metric-contract-v2-projection-1"
      && statistics.denominator_basis === "rubric_factors";
    return {
      availability: "measured",
      reason: supersededRubric
        ? "measured_under_superseded_projection_identity"
        : "measured_from_owned_opportunities",
    };
  }
  if (sealed.value_state === "pending") {
    const lower = sealed.censoring_lower_bound;
    const upper = sealed.censoring_upper_bound;
    if (
      !statistics.capability_available
      || !statistics.source_complete
      || statistics.eligible_count <= 0
      || statistics.pending_count <= 0
      || statistics.unknown_count !== 0
      || typeof lower !== "number"
      || typeof upper !== "number"
      || Math.abs(lower
        - statistics.met_count / statistics.eligible_count) > 1e-9
      || Math.abs(upper
        - (statistics.met_count + statistics.pending_count) / statistics.eligible_count) > 1e-9
    ) return null;
    return { availability: "pending_right_censored", reason: "opportunity_right_censored" };
  }
  if (sealed.value_state === "not_applicable") {
    return { availability: "no_opportunity", reason: "no_eligible_opportunity_observed" };
  }
  if (
    R3_REQUIREMENT_PROJECTIONS.has(sealed.projection_version)
    && statistics.denominator_basis === "objective_opportunities"
    && statistics.capability_available
    && statistics.source_complete
    && statistics.eligible_count === 0
  ) {
    return {
      availability: "evidence_unresolved",
      reason: "opportunity_set_exceeds_receipt_bound",
    };
  }
  if (!statistics.capability_available) {
    return capabilityMissingReason === null
      ? null
      : { availability: "capability_missing", reason: capabilityMissingReason };
  }
  if (
    [
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(sealed.projection_version)
    && sealed.metric_key === "logic.decomposition_coverage"
    && !statistics.source_complete
  ) {
    return {
      availability: "source_incomplete",
      reason: "reviewed_requirement_plan_binding_invalid",
    };
  }
  if (
    [
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(sealed.projection_version)
    && sealed.metric_key === "logic.decomposition_coverage"
    && statistics.source_complete
    && statistics.eligible_count === 0
  ) {
    return {
      availability: "evidence_unresolved",
      reason: "reviewed_requirement_plan_confirmation_required",
    };
  }
  if (
    R4_LIFECYCLE_PROJECTIONS.has(sealed.projection_version)
    && R4_LIFECYCLE_METRIC_KEYS.has(sealed.metric_key)
    && !statistics.source_complete
  ) {
    return {
      availability: "source_incomplete",
      reason: "confirmed_lifecycle_enumeration_required",
    };
  }
  if (!statistics.source_complete) {
    return {
      availability: "source_incomplete",
      reason: "source_reconciliation_incomplete",
    };
  }
  if (statistics.eligible_count === 0) {
    return {
      availability: "evidence_unresolved",
      reason: statistics.denominator_basis === "declared_profile_slots"
        ? "declared_profile_slots_absent"
        : "opportunity_set_undetermined",
    };
  }
  return {
    availability: "evidence_unresolved",
    reason: "opportunity_classification_unresolved",
  };
}

/**
 * Presentation-side cross-binding for the additive readiness projection. The
 * API parser remains authoritative; this guard ensures contributor prose is
 * never shown unless all twenty rows describe the exact sealed publication.
 */
export function metricEvidenceReadinessForPublication(
  value: unknown,
  publication: MetricPublicationV2 | null | undefined,
): MetricEvidenceReadinessProjectionV2 | null {
  const candidate = row(value);
  if (candidate === null || publication === null || publication === undefined) return null;
  if (!hasExactKeys(candidate, PROJECTION_KEYS)) return null;
  const catalogIsReadable = candidate.catalog_version === "metric-evidence-readiness-v2-7"
    || (candidate.catalog_version === "metric-evidence-readiness-v2-6"
      && publication.projection_version !== "metric-contract-v2-projection-8")
    || (candidate.catalog_version === "metric-evidence-readiness-v2-5"
      && !["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
        publication.projection_version,
      ))
    || (candidate.catalog_version === "metric-evidence-readiness-v2-4"
      && ![
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(publication.projection_version))
    || (candidate.catalog_version === "metric-evidence-readiness-v2-3"
      && ![
        "metric-contract-v2-projection-5", "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7", "metric-contract-v2-projection-8",
      ].includes(publication.projection_version))
    || (candidate.catalog_version === "metric-evidence-readiness-v2-2"
      && !R4_LIFECYCLE_PROJECTIONS.has(publication.projection_version));
  if (
    candidate.projection_key !== "metric.contract-v2.evidence-readiness"
    || candidate.projection_version !== 1
    || !catalogIsReadable
    || candidate.registry_version !== METRIC_CONTRACT_V2_REGISTRY_VERSION
    || candidate.registry_version !== publication.registry_version
    || candidate.publication_key !== publication.publication_key
    || candidate.publication_version !== publication.publication_version
    || candidate.publication_source !== publication.source
    || candidate.canonical_live_snapshot !== publication.canonical_live_snapshot
    || candidate.compatibility_preview !== publication.compatibility_preview
    || candidate.contract_set_fingerprint !== METRIC_CONTRACT_V2_SET_FINGERPRINT
    || candidate.contract_set_fingerprint !== publication.contract_set_fingerprint
    || typeof candidate.publication_fingerprint !== "string"
    || !HEX_64.test(candidate.publication_fingerprint)
    || !METRIC_CONTRACT_V2_PROJECTION_VERSIONS.includes(candidate.metric_projection_version as typeof METRIC_CONTRACT_V2_PROJECTION_VERSIONS[number])
    || candidate.metric_projection_version !== publication.projection_version
    || candidate.local_only !== true || candidate.content_persisted !== false
    || candidate.calibration_state !== "not_assessed" || candidate.product_metric_eligible !== false
    || !Array.isArray(candidate.metrics) || candidate.metrics.length !== METRIC_V2_KEYS.length
  ) return null;
  for (const field of ["provider", "provider_version", "adapter_version", "source_schema_version"] as const) {
    if (typeof candidate[field] !== "string" || !SAFE_CODE.test(candidate[field])) return null;
  }
  if (["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
    publication.projection_version,
  )) {
    const requirementAction = publication.metrics.find(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    )?.state;
    const requirementPlan = publication.metrics.find(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    )?.state;
    const reviewedRequirementPlan = requirementPlan === undefined
      ? false
      : isReviewedRequirementPlanState(requirementPlan);
    if (
      requirementPlan !== undefined
      && ["known", "pending", "not_applicable"].includes(requirementPlan.value_state)
      && !reviewedRequirementPlan
    ) return null;
    if (
      requirementAction !== undefined
      && ["known", "pending", "not_applicable"].includes(requirementAction.value_state)
      && (!isReviewedRequirementActionState(requirementAction) || !reviewedRequirementPlan)
    ) return null;
    const reviewedRequirementCount = reviewedRequirementPlan && requirementPlan !== undefined
      ? requirementPlan.statistics.eligible_count
      : 0;
    if (
      requirementAction !== undefined
      && requirementAction.statistics.eligible_count !== reviewedRequirementCount
    ) return null;
  }
  const availabilityCounts = new Map<MetricEvidenceAvailabilityState, number>(AVAILABILITY.map((state) => [state, 0]));
  let objectiveMeasurableCount = 0;
  let objectiveMeasuredCount = 0;
  let objectiveMetricCount = 0;
  for (let index = 0; index < METRIC_V2_KEYS.length; index += 1) {
    const readiness = row(candidate.metrics[index]);
    const sealed = publication.metrics[index].state;
    if (readiness === null || !hasExactKeys(readiness, READINESS_ROW_KEYS)) return null;
    const required = contributorList(readiness.required_contributors);
    const observed = contributorList(readiness.observed_contributors);
    const missing = contributorList(readiness.missing_contributors);
    const adapterCapabilities = capabilityList(readiness.required_adapter_capabilities);
    const requirement = metricEvidenceRequirementFor(
      sealed.metric_key,
      publication.projection_version,
    );
    const expectedRequiredContributors = [
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(publication.projection_version)
      && sealed.metric_key === "logic.decomposition_coverage"
      && sealed.value_state === "not_applicable"
      ? ["reviewed_requirement_enumeration"] as const
      : R4_LIFECYCLE_PROJECTIONS.has(publication.projection_version)
      && R4_LIFECYCLE_METRIC_KEYS.has(sealed.metric_key)
      && sealed.value_state === "not_applicable"
      ? ["confirmed_lifecycle_enumeration"] as const
      : requirement.requiredContributors;
    const expectedObserved = expectedObservedContributors(
      sealed,
      expectedRequiredContributors,
    );
    const expectedVerdict = expectedReadinessVerdict(
      sealed,
      requirement.capabilityMissingReason,
    );
    if (expectedVerdict === null) return null;
    const expectedAvailability = expectedVerdict.availability;
    if (
      readiness.metric_key !== METRIC_V2_KEYS[index]
      || readiness.metric_key !== sealed.metric_key
      || readiness.contract_version !== sealed.contract_version
      || readiness.contract_fingerprint !== sealed.contract_fingerprint
      || readiness.evidence_authority !== sealed.evidence_authority
      || readiness.denominator_basis !== sealed.statistics.denominator_basis
      || readiness.opportunity_unit_kind !== sealed.statistics.opportunity_unit_kind
      || readiness.value_state !== sealed.value_state
      || typeof readiness.availability_state !== "string"
      || !AVAILABILITY.includes(readiness.availability_state as MetricEvidenceAvailabilityState)
      || readiness.availability_state !== expectedAvailability
      || typeof readiness.reason_code !== "string" || !SAFE_CODE.test(readiness.reason_code)
      || readiness.reason_code !== expectedVerdict.reason
      || required === null || required.length === 0 || observed === null || missing === null
      || !sameOrderedValues(required, expectedRequiredContributors)
      || !sameOrderedValues(observed, expectedObserved)
      || missing.length !== required.filter((item) => !observed.includes(item)).length
      || missing.some((item) => observed.includes(item) || !required.includes(item))
      || adapterCapabilities === null
      || !sameOrderedValues(adapterCapabilities, requirement.requiredAdapterCapabilities)
      || readiness.capability_available !== sealed.statistics.capability_available
      || readiness.source_complete !== sealed.statistics.source_complete
      || readiness.eligible_count !== sealed.statistics.eligible_count
      || readiness.met_count !== sealed.statistics.met_count
      || readiness.not_met_count !== sealed.statistics.not_met_count
      || readiness.pending_count !== sealed.statistics.pending_count
      || readiness.unknown_count !== sealed.statistics.unknown_count
      || readiness.resolved_count !== sealed.statistics.met_count + sealed.statistics.not_met_count
      || !optionalBound(readiness.censoring_lower_bound) || !optionalBound(readiness.censoring_upper_bound)
      || (readiness.censoring_lower_bound ?? null) !== (sealed.censoring_lower_bound ?? null)
      || (readiness.censoring_upper_bound ?? null) !== (sealed.censoring_upper_bound ?? null)
      || readiness.calibration_state !== "not_assessed" || readiness.product_metric_eligible !== false
    ) return null;
    const state = readiness.availability_state as MetricEvidenceAvailabilityState;
    availabilityCounts.set(state, (availabilityCounts.get(state) ?? 0) + 1);
    if (sealed.evidence_authority === "objective_receipt") {
      objectiveMetricCount += 1;
      if (readiness.capability_available === true) objectiveMeasurableCount += 1;
      if (state === "measured") objectiveMeasuredCount += 1;
    }
  }
  const summary: Readonly<Record<MetricEvidenceAvailabilityState, string>> = {
    measured: "measured_count",
    pending_right_censored: "pending_count",
    no_opportunity: "no_opportunity_count",
    capability_missing: "capability_missing_count",
    source_incomplete: "source_incomplete_count",
    evidence_unresolved: "evidence_unresolved_count",
    abstained: "abstained_count",
    execution_error: "execution_error_count",
  };
  for (const state of AVAILABILITY) {
    const field = summary[state];
    if (!integer(candidate[field]) || candidate[field] !== availabilityCounts.get(state)) return null;
  }
  if (
    candidate.objective_metric_count !== 5
    || objectiveMetricCount !== candidate.objective_metric_count
    || !integer(candidate.objective_measurable_count)
    || candidate.objective_measurable_count !== objectiveMeasurableCount
    || !integer(candidate.objective_measured_count)
    || candidate.objective_measured_count !== objectiveMeasuredCount
    || candidate.objective_measured_count !== publication.objective_measured_count
  ) return null;
  return candidate as unknown as MetricEvidenceReadinessProjectionV2;
}

export function readableEvidenceContributor(value: string): string {
  return value.replaceAll("_", " ");
}

export function readableEvidenceAvailability(value: string): string {
  return value.replaceAll("_", " ");
}

export function readableAdapterCapability(value: string): string {
  return value.replaceAll("_", " ");
}
