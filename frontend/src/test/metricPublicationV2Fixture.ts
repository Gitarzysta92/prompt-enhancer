import {
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_V2_CONTRACT_IDENTITIES,
  METRIC_V2_KEYS,
  type MetricPublicationV2,
} from "../shared/api/metricPublicationV2Contract";
import type {
  MetricEvidenceAvailabilityState,
  MetricEvidenceReadinessProjectionV2,
  MetricEvidenceReadinessRowV2,
} from "../features/model-ensemble/metricEvidenceReadiness";
import { metricEvidenceRequirementFor } from "../features/model-ensemble/metricEvidenceReadiness";

/**
 * Synthetic canonical V2 publication builder for tests. Every value is a
 * reserved example: no transcript text, no identities, no paths. The builder
 * produces the exact wire shape the strict parser accepts, so tests exercise
 * the same parse → present path as the product.
 */
export type MetricKeyV2 = typeof METRIC_V2_KEYS[number];
export type MetricGuidanceStateClassFixture = MetricPublicationV2["metrics"][number]["guidance"]["state_class"];

export interface MetricScenarioV2 {
  /** Value state on the wire. */
  value_state?: "known" | "pending" | "unknown" | "not_applicable" | "abstained" | "execution_error";
  numerator?: number;
  denominator?: number;
  eligible?: number;
  met?: number;
  not_met?: number;
  pending?: number;
  unknown?: number;
  /** Producer decision; never re-decided by the client. */
  state_class?: MetricGuidanceStateClassFixture;
  factor_evidence?: "not_observed" | "aggregate_only" | "per_factor_measured";
  focus_factor_keys?: readonly string[];
  censoring_lower_bound?: number | null;
  censoring_upper_bound?: number | null;
  capability_available?: boolean;
  source_complete?: boolean;
  explanation_code?: string;
  contract_factor_count?: number;
  distinct_owner_count?: number;
}

const OBJECTIVE_KEYS = new Set<string>(
  METRIC_V2_KEYS.filter((key) => METRIC_V2_CONTRACT_IDENTITIES[key].authority === "objective_receipt"),
);

export function isObjectiveMetricKeyV2(metricKey: string): boolean {
  return OBJECTIVE_KEYS.has(metricKey);
}

function defaultStateClass(scenario: MetricScenarioV2, objective: boolean): MetricGuidanceStateClassFixture {
  switch (scenario.value_state ?? "unknown") {
    case "known": return scenario.state_class ?? "known_improve";
    case "pending": return "pending_closure";
    case "not_applicable": return "no_opportunity";
    case "abstained": return "evidence_coverage_abstained";
    case "execution_error": return "analysis_failed";
    default:
      return objective
        ? ((scenario.capability_available ?? false) && (scenario.eligible ?? 0) > 0
          ? "objective_evidence_unresolved"
          : "objective_evidence_missing")
        : "evidence_unresolved";
  }
}

function templateIds(metricKey: string, stateClass: MetricGuidanceStateClassFixture) {
  const generic: Partial<Record<MetricGuidanceStateClassFixture, [string, string]>> = {
    pending_closure: ["action.await_opportunity_closure", "verification.await_opportunity_closure"],
    objective_evidence_missing: ["action.collect_objective_receipt", "verification.objective_receipt_scope"],
    objective_evidence_unresolved: ["action.resolve_objective_evidence", "verification.objective_evidence_completeness"],
    evidence_unresolved: ["action.hold_state_unknown", "verification.review_opportunity_evidence"],
    no_opportunity: ["action.no_change_required", "verification.reassess_on_new_opportunity"],
    evidence_coverage_abstained: ["action.review_evidence_coverage", "verification.review_evidence_coverage"],
    analysis_failed: ["action.repair_local_analysis_stage", "verification.fresh_sealed_receipt"],
  };
  const pair = generic[stateClass];
  if (pair === undefined) {
    const prefix = stateClass === "known_retain" ? "action.retain" : "action.improve";
    return {
      diagnosis_template_id: `diagnosis.${metricKey}.v1`,
      action_template_id: `${prefix}.${metricKey}.v1`,
      verification_template_id: `verification.${metricKey}.v1`,
    };
  }
  return {
    diagnosis_template_id: `diagnosis.${metricKey}.v1`,
    action_template_id: `${pair[0]}.v1`,
    verification_template_id: `${pair[1]}.v1`,
  };
}

/** One published metric (state + guidance + implementation state) for a scenario. */
export function syntheticPublishedMetricV2(metricKey: MetricKeyV2, scenario: MetricScenarioV2 = {}) {
  const identity = METRIC_V2_CONTRACT_IDENTITIES[metricKey];
  const objective = identity.authority === "objective_receipt";
  const valueState = scenario.value_state ?? "unknown";
  const known = valueState === "known";
  const pending = valueState === "pending";
  const numerator = known ? (scenario.numerator ?? 1) : null;
  const denominator = known ? (scenario.denominator ?? 2) : null;
  const eligible = known ? denominator! : (scenario.eligible ?? (pending ? 4 : 0));
  const pendingCount = pending ? (scenario.pending ?? 2) : 0;
  const unknownCount = known || pending ? 0 : (scenario.unknown ?? 0);
  const met = known ? numerator! : pending
    ? (scenario.met ?? Math.max(0, Math.min(eligible - pendingCount, scenario.numerator ?? 1)))
    : (scenario.met ?? 0);
  const notMet = known
    ? eligible - met
    : (scenario.not_met ?? eligible - met - pendingCount - unknownCount);
  const capabilityAvailable = scenario.capability_available ?? (known || pending || eligible > 0);
  const numericValue = known ? numerator! / denominator! : null;
  const lower = known ? numericValue : pending
    ? (scenario.censoring_lower_bound === undefined ? met / eligible : scenario.censoring_lower_bound)
    : (scenario.censoring_lower_bound ?? null);
  const upper = known ? numericValue : pending
    ? (scenario.censoring_upper_bound === undefined ? (met + pendingCount) / eligible : scenario.censoring_upper_bound)
    : (scenario.censoring_upper_bound ?? null);
  const stateClass = defaultStateClass(scenario, objective);
  const factorEvidence = known ? (scenario.factor_evidence ?? "not_observed") : "not_observed";
  const explanationCode = scenario.explanation_code ?? (
    known ? "exact_fraction"
      : pending ? "episode_horizon_open"
        : valueState === "not_applicable" ? "no_eligible_opportunity"
          : valueState === "abstained" ? "evidence_coverage_insufficient"
            : valueState === "execution_error" ? "local_stage_failed"
              : objective ? (stateClass === "objective_evidence_unresolved" ? "typed_objective_evidence_unresolved" : "typed_objective_absent")
                : "opportunity_family_unobservable"
  );
  const statistics = {
    metric_key: metricKey,
    denominator_basis: identity.basis,
    opportunity_unit_kind: identity.unit,
    capability_available: capabilityAvailable,
    source_complete: scenario.source_complete ?? (known || pending),
    eligible_count: eligible,
    met_count: met,
    not_met_count: notMet,
    pending_count: pendingCount,
    unknown_count: unknownCount,
    superseded_excluded_count: 0,
    distinct_owner_count: scenario.distinct_owner_count
      ?? (identity.basis === "semantic_unit_opportunities" ? eligible : 0),
  };
  const state = {
    metric_key: metricKey,
    registry_version: "all-20-factor-contracts-v2",
    contract_version: "probabilistic-metric-contract-v2",
    contract_fingerprint: identity.fingerprint,
    evidence_authority: identity.authority,
    value_state: valueState,
    explanation_code: explanationCode,
    numerator,
    denominator,
    numeric_value: numericValue,
    censoring_lower_bound: lower,
    censoring_upper_bound: upper,
    statistics,
    projection_version: "metric-contract-v2-projection-1",
    product_metric_eligible: false,
  };
  const implementation = known ? "live_measured"
    : pending ? "pending"
      : valueState === "not_applicable" ? "no_opportunity"
        : valueState === "abstained" ? "abstained"
          : valueState === "execution_error" ? "error"
            : objective
              ? (capabilityAvailable ? "objective_evidence_unresolved" : "objective_capability_missing")
              : "method_only_withheld";
  const guidance = {
    schema_version: 1,
    contract_version: "metric-guidance-contract-v1",
    template_catalog_version: "metric-guidance-templates-v1",
    template_version: 1,
    metric_key: metricKey,
    metric_version: 2,
    registry_version: "all-20-factor-contracts-v2",
    metric_contract_version: "probabilistic-metric-contract-v2",
    metric_contract_fingerprint: identity.fingerprint,
    evidence_authority: identity.authority,
    denominator_basis: identity.basis,
    contract_factor_count: scenario.contract_factor_count ?? 3,
    audience: valueState === "execution_error" ? "tooling"
      : objective || metricKey.startsWith("outcome.") ? "tooling"
        : metricKey.startsWith("prompt.") ? "user"
          : metricKey.startsWith("collaboration.") ? "workflow" : "agent",
    role: metricKey === "collaboration.rework_candidate_rate" ? "friction_signal"
      : metricKey.startsWith("prompt.") ? "specification_signal"
        : metricKey.startsWith("collaboration.") ? "collaboration_signal"
          : metricKey.startsWith("logic.") ? "traceability_signal" : "outcome_evidence",
    value_state: valueState,
    state_class: stateClass,
    basis: known ? (factorEvidence === "aggregate_only" ? "method-only" : "measured")
      : valueState === "execution_error" ? "method-only" : "readiness",
    value_origin: known ? (objective ? "typed_objective" : "deterministic_local") : "none",
    factor_evidence: factorEvidence,
    focus_factor_keys: known && factorEvidence === "per_factor_measured" ? [...(scenario.focus_factor_keys ?? [])] : [],
    reason_code: explanationCode,
    ...templateIds(metricKey, stateClass),
    numerator,
    denominator,
    censoring_lower_bound: lower,
    censoring_upper_bound: upper,
    eligible_count: eligible,
    met_count: met,
    not_met_count: notMet,
    pending_count: pendingCount,
    unknown_count: unknownCount,
    product_metric_eligible: false,
  };
  return { state, guidance, implementation_state: implementation };
}

/** A complete twenty-metric publication; unspecified keys are objective-missing / method-withheld unknowns. */
export function syntheticMetricPublicationV2(
  scenarios: Partial<Record<MetricKeyV2, MetricScenarioV2>> = {},
): MetricPublicationV2 {
  const metrics = METRIC_V2_KEYS.map((metricKey) => syntheticPublishedMetricV2(metricKey, scenarios[metricKey] ?? {}));
  const count = (state: string) => metrics.filter((item) => item.state.value_state === state).length;
  return {
    publication_key: "metric.contract-v2.publication",
    publication_version: 2,
    registry_version: "all-20-factor-contracts-v2",
    contract_set_fingerprint: METRIC_CONTRACT_V2_SET_FINGERPRINT,
    projection_version: "metric-contract-v2-projection-1",
    guidance_contract_version: "metric-guidance-contract-v1",
    guidance_template_catalog_version: "metric-guidance-templates-v1",
    source: "live_projection",
    canonical_live_snapshot: true,
    model_stage_consumed: false,
    compatibility_preview: false,
    metrics,
    known_count: count("known"),
    pending_count: count("pending"),
    unknown_count: count("unknown"),
    not_applicable_count: count("not_applicable"),
    abstained_count: count("abstained"),
    execution_error_count: count("execution_error"),
    objective_measured_count: metrics.filter((item) => (
      item.state.evidence_authority === "objective_receipt" && item.state.value_state === "known"
    )).length,
    product_metric_eligible: false,
  } as unknown as MetricPublicationV2;
}

/** Content-free evidence-readiness projection cross-bound to one synthetic publication. */
export function syntheticMetricEvidenceReadinessV2(
  publication: MetricPublicationV2,
): MetricEvidenceReadinessProjectionV2 {
  const metrics = publication.metrics.map(({ state }) => {
    const requirement = metricEvidenceRequirementFor(
      state.metric_key,
      publication.projection_version,
    );
    const availability: MetricEvidenceAvailabilityState = state.value_state === "known" ? "measured"
      : state.value_state === "pending" ? "pending_right_censored"
        : state.value_state === "not_applicable" ? "no_opportunity"
          : state.value_state === "abstained" ? "abstained"
            : state.value_state === "execution_error" ? "execution_error"
              : !state.statistics.capability_available ? "capability_missing"
                : !state.statistics.source_complete ? "source_incomplete"
                  : "evidence_unresolved";
    const lifecycleProjection = publication.projection_version === "metric-contract-v2-projection-4"
      || publication.projection_version === "metric-contract-v2-projection-5"
      || publication.projection_version === "metric-contract-v2-projection-6"
      || publication.projection_version === "metric-contract-v2-projection-7"
      || publication.projection_version === "metric-contract-v2-projection-8";
    const lifecycleMetric = state.metric_key.startsWith("collaboration.");
    let reason: MetricEvidenceReadinessRowV2["reason_code"];
    if (availability === "execution_error") {
      reason = "execution_error_reported";
    } else if (availability === "abstained") {
      reason = "calculator_abstained";
    } else if (availability === "measured") {
      reason = publication.projection_version === "metric-contract-v2-projection-1"
        && state.statistics.denominator_basis === "rubric_factors"
        ? "measured_under_superseded_projection_identity"
        : "measured_from_owned_opportunities";
    } else if (availability === "pending_right_censored") {
      reason = "opportunity_right_censored";
    } else if (availability === "no_opportunity") {
      reason = "no_eligible_opportunity_observed";
    } else if (
      ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
        publication.projection_version,
      )
      && state.metric_key === "logic.requirement_action_traceability"
      && state.value_state === "unknown"
    ) {
      const exactReason = {
        requirement_action_evidence_unavailable: "reviewed_requirement_action_service_required",
        requirement_action_evidence_confirmation_required: "reviewed_requirement_action_confirmation_required",
        requirement_action_evidence_invalid: "reviewed_requirement_action_binding_invalid",
        requirement_action_evidence_overflow: "opportunity_set_exceeds_receipt_bound",
        requirement_action_candidate_source_incomplete: "requirement_action_adapter_capabilities_required",
      } as const;
      const resolvedReason = exactReason[state.explanation_code as keyof typeof exactReason];
      if (resolvedReason === undefined) {
        throw new Error("synthetic r7/r8 requirement-action fixture needs an exact structural explanation");
      }
      reason = resolvedReason;
    } else if (
      [
        "metric-contract-v2-projection-3",
        "metric-contract-v2-projection-4",
        "metric-contract-v2-projection-5",
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(publication.projection_version)
      && state.statistics.denominator_basis === "objective_opportunities"
      && state.statistics.capability_available
      && state.statistics.source_complete
      && state.statistics.eligible_count === 0
    ) {
      reason = "opportunity_set_exceeds_receipt_bound";
    } else if (availability === "capability_missing") {
      reason = requirement.capabilityMissingReason ?? "focus_owned_request_revision_required";
    } else if (
      availability === "source_incomplete"
      && [
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(
        publication.projection_version,
      )
      && state.metric_key === "logic.decomposition_coverage"
    ) {
      reason = "reviewed_requirement_plan_binding_invalid";
    } else if (availability === "source_incomplete" && lifecycleProjection && lifecycleMetric) {
      reason = "confirmed_lifecycle_enumeration_required";
    } else if (availability === "source_incomplete") {
      reason = "source_reconciliation_incomplete";
    } else if (
      [
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(
        publication.projection_version,
      )
      && state.metric_key === "logic.decomposition_coverage"
      && state.statistics.capability_available
      && state.statistics.source_complete
      && state.statistics.eligible_count === 0
    ) {
      reason = "reviewed_requirement_plan_confirmation_required";
    } else if (state.statistics.eligible_count === 0) {
      reason = state.statistics.denominator_basis === "declared_profile_slots"
        ? "declared_profile_slots_absent"
        : "opportunity_set_undetermined";
    } else {
      reason = "opportunity_classification_unresolved";
    }
    const r6Decomposition = [
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(
      publication.projection_version,
    )
      && state.metric_key === "logic.decomposition_coverage";
    const reviewedRequirementAction = [
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(publication.projection_version)
      && state.metric_key === "logic.requirement_action_traceability";
    const r8VerifiedRequirement = publication.projection_version
      === "metric-contract-v2-projection-8"
      && state.metric_key === "outcome.verified_requirement_coverage";
    const required = r6Decomposition
      && state.value_state === "not_applicable"
      ? ["reviewed_requirement_enumeration"] as const
      : lifecycleProjection
      && lifecycleMetric
      && state.value_state === "not_applicable"
      ? ["confirmed_lifecycle_enumeration"] as const
      : requirement.requiredContributors;
    const observed = !state.statistics.capability_available
      ? []
      : r8VerifiedRequirement
        ? (state.statistics.source_complete
          && (state.value_state === "not_applicable" || state.statistics.eligible_count > 0)
          ? ["declared_objective_opportunity_set" as const]
          : [])
      : reviewedRequirementAction
        ? (["known", "pending", "not_applicable"].includes(state.value_state)
          && state.statistics.source_complete
          ? [...required]
          : [])
      : r6Decomposition
        ? [
          ...(state.statistics.source_complete
            && (state.value_state === "not_applicable" || state.statistics.eligible_count > 0)
            ? ["reviewed_requirement_enumeration" as const]
            : []),
          ...(state.statistics.eligible_count > 0 ? ["reviewed_requirement_plan_disposition" as const] : []),
        ]
        : lifecycleProjection && lifecycleMetric
        ? [
          ...(state.statistics.source_complete ? ["confirmed_lifecycle_enumeration" as const] : []),
          ...(state.statistics.eligible_count > 0 ? ["confirmed_lifecycle_opportunity" as const] : []),
          ...(state.statistics.met_count + state.statistics.not_met_count > 0
            ? ["confirmed_lifecycle_outcome_link" as const]
            : []),
        ]
      : [
        "metric-contract-v2-projection-5",
        "metric-contract-v2-projection-6",
        "metric-contract-v2-projection-7",
        "metric-contract-v2-projection-8",
      ].includes(
        publication.projection_version,
      )
        && state.statistics.denominator_basis === "declared_profile_slots"
        && state.statistics.eligible_count === 0
        ? []
      : state.statistics.met_count + state.statistics.not_met_count === 0
        ? state.statistics.source_complete ? required.slice(0, 1) : []
        : publication.projection_version === "metric-contract-v2-projection-1"
          && state.statistics.denominator_basis === "rubric_factors"
          ? required.filter((contributor) => contributor !== "focus_owned_request_revision")
          : required;
    return {
      metric_key: state.metric_key,
      contract_version: state.contract_version,
      contract_fingerprint: state.contract_fingerprint,
      evidence_authority: state.evidence_authority,
      denominator_basis: state.statistics.denominator_basis,
      opportunity_unit_kind: state.statistics.opportunity_unit_kind ?? null,
      value_state: state.value_state,
      availability_state: availability,
      reason_code: reason,
      required_contributors: [...required],
      observed_contributors: [...observed],
      // Exact partition: missing is always required minus observed. A partial
      // observation (capability present but nothing resolved yet) must still
      // name the contributors it is missing, or the presentation guard rejects
      // the whole projection and the additive detail vanishes silently.
      missing_contributors: required.filter((contributor) => !observed.includes(contributor)),
      required_adapter_capabilities: [...requirement.requiredAdapterCapabilities],
      capability_available: state.statistics.capability_available,
      source_complete: state.statistics.source_complete,
      eligible_count: state.statistics.eligible_count,
      met_count: state.statistics.met_count,
      not_met_count: state.statistics.not_met_count,
      pending_count: state.statistics.pending_count,
      unknown_count: state.statistics.unknown_count,
      resolved_count: state.statistics.met_count + state.statistics.not_met_count,
      censoring_lower_bound: state.censoring_lower_bound ?? null,
      censoring_upper_bound: state.censoring_upper_bound ?? null,
      calibration_state: "not_assessed" as const,
      product_metric_eligible: false as const,
    };
  });
  const count = (state: MetricEvidenceAvailabilityState) => metrics.filter((metric) => metric.availability_state === state).length;
  return {
    projection_key: "metric.contract-v2.evidence-readiness",
    projection_version: 1,
    catalog_version: publication.projection_version === "metric-contract-v2-projection-8"
      ? "metric-evidence-readiness-v2-7"
      : publication.projection_version === "metric-contract-v2-projection-7"
        ? "metric-evidence-readiness-v2-6"
        : "metric-evidence-readiness-v2-5",
    registry_version: "all-20-factor-contracts-v2",
    publication_key: publication.publication_key,
    publication_version: publication.publication_version,
    publication_source: publication.source,
    canonical_live_snapshot: publication.canonical_live_snapshot,
    compatibility_preview: publication.compatibility_preview,
    contract_set_fingerprint: publication.contract_set_fingerprint,
    publication_fingerprint: "7a".repeat(32),
    metric_projection_version: publication.projection_version as MetricEvidenceReadinessProjectionV2["metric_projection_version"],
    provider: "codex",
    provider_version: "example-provider-v1",
    adapter_version: "example-adapter-v1",
    source_schema_version: "example-source-v1",
    metrics,
    measured_count: count("measured"),
    pending_count: count("pending_right_censored"),
    no_opportunity_count: count("no_opportunity"),
    capability_missing_count: count("capability_missing"),
    source_incomplete_count: count("source_incomplete"),
    evidence_unresolved_count: count("evidence_unresolved"),
    abstained_count: count("abstained"),
    execution_error_count: count("execution_error"),
    objective_metric_count: 5,
    objective_measurable_count: metrics.filter((metric) => (
      metric.evidence_authority === "objective_receipt" && metric.capability_available
    )).length,
    objective_measured_count: metrics.filter((metric) => (
      metric.evidence_authority === "objective_receipt" && metric.availability_state === "measured"
    )).length,
    local_only: true,
    content_persisted: false,
    calibration_state: "not_assessed",
    product_metric_eligible: false,
  };
}
