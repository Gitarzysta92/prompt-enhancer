import type { ModelEnsembleRun } from "./contracts";

export class MetricPublicationV2PayloadError extends Error {
  constructor() {
    super("Canonical metric V2 publication was invalid");
    this.name = "MetricPublicationV2PayloadError";
  }
}

/**
 * The publication is well-formed for *some* registry, but not for the exact
 * registry version, contract-set fingerprint, or per-metric contract
 * fingerprint this client's presentation copy is bound to. Callers must treat
 * this as "definitions out of date" (update the client) rather than as a
 * transport failure, and must not keep rendering values or guidance from an
 * earlier publication beside it.
 */
export class MetricDefinitionsOutOfDateError extends MetricPublicationV2PayloadError {
  readonly code = "definitions_out_of_date" as const;
  constructor(readonly mismatch: MetricDefinitionMismatch) {
    super();
    this.name = "MetricDefinitionsOutOfDateError";
    this.message = "Canonical metric V2 definitions do not match this client";
  }
}

type Row = Record<string, unknown>;
export type MetricPublicationV2 = NonNullable<ModelEnsembleRun["metric_publication_v2"]>;

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_LABEL = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
export const METRIC_CONTRACT_V2_REGISTRY_VERSION = "all-20-factor-contracts-v2";
export const METRIC_CONTRACT_V2_SET_FINGERPRINT =
  "02eac63391eb48351f5c8c197d62897895234e2334d388a530d6e6812a18aa67";
export const METRIC_GUIDANCE_CONTRACT_VERSION = "metric-guidance-contract-v1";
export const METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION = "metric-guidance-templates-v1";
export const MAX_GUIDANCE_FOCUS_FACTOR_KEYS = 2;
export const METRIC_CONTRACT_V2_PROJECTION_VERSIONS = [
  "metric-contract-v2-projection-1",
  "metric-contract-v2-projection-2",
  "metric-contract-v2-projection-3",
  "metric-contract-v2-projection-4",
  "metric-contract-v2-projection-5",
  "metric-contract-v2-projection-6",
  "metric-contract-v2-projection-7",
  "metric-contract-v2-projection-8",
] as const;

export type MetricDefinitionMismatch =
  | "registry_version"
  | "contract_set_fingerprint"
  | "metric_contract_fingerprint"
  | "guidance_contract_version"
  | "guidance_template_catalog_version"
  | "guidance_template_identity"
  | "projection_version"
  | "metric_profile_binding"
  | "requirement_plan_evidence_binding"
  | "requirement_action_evidence_binding"
  | "requirement_verification_evidence_binding";

function requireReadableProjectionVersion(value: unknown): asserts value is typeof METRIC_CONTRACT_V2_PROJECTION_VERSIONS[number] {
  if (METRIC_CONTRACT_V2_PROJECTION_VERSIONS.includes(
    value as typeof METRIC_CONTRACT_V2_PROJECTION_VERSIONS[number],
  )) return;
  if (typeof value === "string" && /^metric-contract-v2-projection-[1-9][0-9]*$/.test(value)) {
    throw new MetricDefinitionsOutOfDateError("projection_version");
  }
  throw new MetricPublicationV2PayloadError();
}

export type MetricDefinitionCompatibility =
  | { state: "compatible"; registryVersion: typeof METRIC_CONTRACT_V2_REGISTRY_VERSION; contractSetFingerprint: typeof METRIC_CONTRACT_V2_SET_FINGERPRINT }
  | { state: "definitions_out_of_date"; mismatch: MetricDefinitionMismatch };

/**
 * Pure, reusable compatibility gate: binds every client-side V2 presentation
 * (help copy, guidance templates, contract identities) to one exact registry
 * version and contract-set fingerprint. It reads only identity fields that are
 * already present on a publication or on a compact trajectory state list, so it
 * never needs an extra fetch. Any surface that renders V2 values must consult it
 * and, on mismatch, block all twenty values and their guidance.
 */
export function metricDefinitionCompatibility(input: {
  registry_version?: unknown;
  contract_set_fingerprint?: unknown;
  guidance_contract_version?: unknown;
  guidance_template_catalog_version?: unknown;
  metric_contract_fingerprints?: ReadonlyArray<{ metric_key: unknown; contract_fingerprint: unknown }>;
}): MetricDefinitionCompatibility {
  if (input.registry_version !== undefined && input.registry_version !== METRIC_CONTRACT_V2_REGISTRY_VERSION) {
    return { state: "definitions_out_of_date", mismatch: "registry_version" };
  }
  if (input.contract_set_fingerprint !== undefined && input.contract_set_fingerprint !== METRIC_CONTRACT_V2_SET_FINGERPRINT) {
    return { state: "definitions_out_of_date", mismatch: "contract_set_fingerprint" };
  }
  if (input.guidance_contract_version !== undefined && input.guidance_contract_version !== METRIC_GUIDANCE_CONTRACT_VERSION) {
    return { state: "definitions_out_of_date", mismatch: "guidance_contract_version" };
  }
  if (
    input.guidance_template_catalog_version !== undefined
    && input.guidance_template_catalog_version !== METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION
  ) {
    return { state: "definitions_out_of_date", mismatch: "guidance_template_catalog_version" };
  }
  for (const item of input.metric_contract_fingerprints ?? []) {
    const identity = METRIC_V2_CONTRACT_IDENTITIES[item.metric_key as MetricKeyV2];
    if (identity === undefined || item.contract_fingerprint !== identity.fingerprint) {
      return { state: "definitions_out_of_date", mismatch: "metric_contract_fingerprint" };
    }
  }
  return {
    state: "compatible",
    registryVersion: METRIC_CONTRACT_V2_REGISTRY_VERSION,
    contractSetFingerprint: METRIC_CONTRACT_V2_SET_FINGERPRINT,
  };
}

export const METRIC_V2_KEYS = [
  "prompt.task_definition_coverage",
  "prompt.problem_evidence_quality",
  "prompt.context_sufficiency",
  "prompt.constraint_precision",
  "prompt.acceptance_testability",
  "prompt.deliverable_contract",
  "collaboration.ambiguity_resolution",
  "collaboration.clarification_yield",
  "collaboration.exploration_conversion",
  "collaboration.scope_change_discipline",
  "collaboration.rework_candidate_rate",
  "logic.decomposition_coverage",
  "logic.hypothesis_test_linkage",
  "logic.decision_rationale_coverage",
  "logic.requirement_action_traceability",
  "logic.open_loop_closure",
  "outcome.agent_claim_grounding",
  "outcome.verification_strategy_adequacy",
  "outcome.first_pass_verification",
  "outcome.verified_requirement_coverage",
] as const;

type MetricKeyV2 = typeof METRIC_V2_KEYS[number];
export type MetricGuidanceStateClassV2 =
  | "known_retain"
  | "known_improve"
  | "pending_closure"
  | "objective_evidence_missing"
  | "objective_evidence_unresolved"
  | "evidence_unresolved"
  | "no_opportunity"
  | "evidence_coverage_abstained"
  | "analysis_failed";

const GUIDANCE_GENERIC_TEMPLATE_FAMILIES: Readonly<Partial<Record<
  MetricGuidanceStateClassV2,
  readonly [action: string, verification: string]
>>> = {
  pending_closure: ["action.await_opportunity_closure", "verification.await_opportunity_closure"],
  objective_evidence_missing: ["action.collect_objective_receipt", "verification.objective_receipt_scope"],
  objective_evidence_unresolved: ["action.resolve_objective_evidence", "verification.objective_evidence_completeness"],
  evidence_unresolved: ["action.hold_state_unknown", "verification.review_opportunity_evidence"],
  no_opportunity: ["action.no_change_required", "verification.reassess_on_new_opportunity"],
  evidence_coverage_abstained: ["action.review_evidence_coverage", "verification.review_evidence_coverage"],
  analysis_failed: ["action.repair_local_analysis_stage", "verification.fresh_sealed_receipt"],
};

/** Exact identities from the catalog bound to this client; no fallback prose is allowed. */
export function expectedMetricGuidanceTemplateIdentities(
  metricKey: string,
  stateClass: MetricGuidanceStateClassV2,
): { diagnosis: string; action: string; verification: string } {
  const generic = GUIDANCE_GENERIC_TEMPLATE_FAMILIES[stateClass];
  const actionFamily = generic?.[0]
    ?? (stateClass === "known_retain" ? "action.retain" : "action.improve");
  const verificationFamily = generic?.[1] ?? "verification";
  return {
    diagnosis: `diagnosis.${metricKey}.v1`,
    action: generic === undefined ? `${actionFamily}.${metricKey}.v1` : `${actionFamily}.v1`,
    verification: generic === undefined ? `${verificationFamily}.${metricKey}.v1` : `${verificationFamily}.v1`,
  };
}

type ContractIdentity = {
  fingerprint: string;
  basis: typeof DENOMINATOR_BASES[number];
  unit: typeof UNIT_KINDS[number] | null;
  authority: "conversation" | "objective_receipt";
};

export const METRIC_V2_CONTRACT_IDENTITIES: Record<MetricKeyV2, ContractIdentity> = {
  "prompt.task_definition_coverage": { fingerprint: "176e2d092d19b1bffb719d7f3ce78673dd07fc14ed90415aa25454129042d7c2", basis: "rubric_factors", unit: "request_revision", authority: "conversation" },
  "prompt.problem_evidence_quality": { fingerprint: "c664f0e7941a944529cea65af5b9e6599d32ff7ad4362fd7dc93687b42e3d740", basis: "rubric_factors", unit: "request_revision", authority: "conversation" },
  "prompt.context_sufficiency": { fingerprint: "ac9d65a60a8c09c4dedf152510ea8c2b2e3e6c3764149331ea207b4e86197923", basis: "rubric_factors", unit: "request_revision", authority: "conversation" },
  "prompt.constraint_precision": { fingerprint: "c9665290720ebd1efbbd6eaeb760468b409525f4a4913cf600ca81269f23a79c", basis: "declared_profile_slots", unit: null, authority: "conversation" },
  "prompt.acceptance_testability": { fingerprint: "f7c05d2e7ab1637e63efe539f14bc1a287031b81eb0978f6935d7df8548871ce", basis: "declared_profile_slots", unit: null, authority: "conversation" },
  "prompt.deliverable_contract": { fingerprint: "2ed619d698730c3047b70c1fd572d6fb5dfc18b90fa5f6cec937d2fb8a5f8abd", basis: "declared_profile_slots", unit: null, authority: "conversation" },
  "collaboration.ambiguity_resolution": { fingerprint: "89a4c1bfb9efbc3a3b1f5d0c75e2d1e71a55e5df25bf46bf09c7bb5fd80dfb3b", basis: "semantic_unit_opportunities", unit: "ambiguity", authority: "conversation" },
  "collaboration.clarification_yield": { fingerprint: "c3bf3e69633063b5543489639d49966ac6eb0f509980a8d678ed6819db59f389", basis: "semantic_unit_opportunities", unit: "clarification", authority: "conversation" },
  "collaboration.exploration_conversion": { fingerprint: "3e4b9e79039694d1c79fa809d73e62674f32c1c19f7d9bd42ff97e57a554f560", basis: "semantic_unit_opportunities", unit: "hypothesis", authority: "conversation" },
  "collaboration.scope_change_discipline": { fingerprint: "308a3ee1a577a8f361627b9101021a50a12b63e05ca95865d5dadfa24ebd5326", basis: "semantic_unit_opportunities", unit: "scope_change", authority: "conversation" },
  "collaboration.rework_candidate_rate": { fingerprint: "3cfa3bbf472661329527e86b3248f5255bfe0307931d30042a87ec36cf1100a0", basis: "semantic_unit_opportunities", unit: "feedback", authority: "conversation" },
  "logic.decomposition_coverage": { fingerprint: "7a1941086fd7c37510ee04ccba28c4e35added3f0ca7bb933c0d8d066031c6af", basis: "semantic_unit_opportunities", unit: "requirement", authority: "conversation" },
  "logic.hypothesis_test_linkage": { fingerprint: "a21f8fd9431724967d264a9e34ba685c72339b1d9f81403a1ba23a3b5c09c1c0", basis: "objective_opportunities", unit: null, authority: "objective_receipt" },
  "logic.decision_rationale_coverage": { fingerprint: "12c8dfa3affe7e278b5e65af54b566a69b05ccc68dc27391384bb9dfca76aaaf", basis: "semantic_unit_opportunities", unit: "decision", authority: "conversation" },
  "logic.requirement_action_traceability": { fingerprint: "fdf6cf24b63e6c955099f1cd66ab989d3adc5aaef12b857e57dd54516bf80912", basis: "objective_opportunities", unit: null, authority: "objective_receipt" },
  "logic.open_loop_closure": { fingerprint: "1e0d49f883f23c5bc119d657190b2cb045d28e254eb2c6d7ba9217466a7495a6", basis: "semantic_unit_opportunities", unit: "open_loop", authority: "conversation" },
  "outcome.agent_claim_grounding": { fingerprint: "354c189507dadabe7418d3e404e5d2dd74ad9b13d567a93137daad84ef50e3d0", basis: "objective_opportunities", unit: null, authority: "objective_receipt" },
  "outcome.verification_strategy_adequacy": { fingerprint: "59ec9a0d1d65d1ea17b350e5e325e14eb0c1cd8a655ba6dbc1910f339ecb377e", basis: "semantic_unit_opportunities", unit: "request_revision", authority: "conversation" },
  "outcome.first_pass_verification": { fingerprint: "b17403508c53029c3c6a7dd9f9d17484f451a5e961a2ee18f0dd9a532b16b667", basis: "objective_opportunities", unit: null, authority: "objective_receipt" },
  "outcome.verified_requirement_coverage": { fingerprint: "4fcdd48c79e41c5e8e82e5de08c05dd4c4c6780550b2c27c78138d3ef2129be7", basis: "objective_opportunities", unit: null, authority: "objective_receipt" },
};

const VALUE_STATES = [
  "known", "pending", "unknown", "not_applicable", "abstained", "execution_error",
] as const;
const IMPLEMENTATION_STATES = [
  "live_measured", "compatibility_projected", "method_only_withheld",
  "objective_capability_missing", "objective_evidence_unresolved", "pending",
  "no_opportunity", "abstained", "error",
] as const;
const DENOMINATOR_BASES = [
  "rubric_factors", "semantic_unit_opportunities", "declared_profile_slots",
  "objective_opportunities",
] as const;
const UNIT_KINDS = [
  "request_revision", "requirement", "constraint", "deliverable", "ambiguity",
  "clarification", "scope_change", "feedback", "hypothesis", "decision",
  "open_loop", "action", "verification",
] as const;

function record(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new MetricPublicationV2PayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new MetricPublicationV2PayloadError();
  }
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new MetricPublicationV2PayloadError();
  }
  return value as number;
}

function finite(value: unknown, minimum = 0, maximum = 1): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new MetricPublicationV2PayloadError();
  }
  return value;
}

function optionalFinite(value: unknown): number | null {
  return value === null ? null : finite(value);
}

function safeLabel(value: unknown): string {
  if (typeof value !== "string" || !SAFE_LABEL.test(value)) {
    throw new MetricPublicationV2PayloadError();
  }
  return value;
}

function oneOf<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    throw new MetricPublicationV2PayloadError();
  }
  return value as T;
}

function parseStatistics(value: unknown, metricKey: string) {
  const statistics = record(value);
  exact(statistics, [
    "metric_key", "denominator_basis", "opportunity_unit_kind",
    "capability_available", "source_complete", "eligible_count", "met_count",
    "not_met_count", "pending_count", "unknown_count",
    "superseded_excluded_count", "distinct_owner_count",
  ]);
  if (statistics.metric_key !== metricKey) throw new MetricPublicationV2PayloadError();
  const denominatorBasis = oneOf(statistics.denominator_basis, DENOMINATOR_BASES);
  const unitKind = statistics.opportunity_unit_kind === null
    ? null
    : oneOf(statistics.opportunity_unit_kind, UNIT_KINDS);
  if (
    (["rubric_factors", "semantic_unit_opportunities"].includes(denominatorBasis))
      !== (unitKind !== null)
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  if (typeof statistics.capability_available !== "boolean" || typeof statistics.source_complete !== "boolean") {
    throw new MetricPublicationV2PayloadError();
  }
  const eligible = integer(statistics.eligible_count, 0, 1_000_000);
  const met = integer(statistics.met_count, 0, 1_000_000);
  const notMet = integer(statistics.not_met_count, 0, 1_000_000);
  const pending = integer(statistics.pending_count, 0, 1_000_000);
  const unknown = integer(statistics.unknown_count, 0, 1_000_000);
  integer(statistics.superseded_excluded_count, 0, 1_000_000);
  const owners = integer(statistics.distinct_owner_count, 0, 1_000_000);
  if (
    met + notMet + pending + unknown !== eligible
    || (denominatorBasis === "semantic_unit_opportunities" && owners !== eligible)
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  return { statistics, denominatorBasis, eligible, met, notMet, pending, unknown };
}

/**
 * Projection 8 gives verified-requirement coverage a closed state vocabulary.
 * This check is deliberately source-independent so compact trajectory rows are
 * safe on their own; the full-run parser additionally correlates the row with
 * its exact evidence binding.
 */
function validateR8VerifiedRequirementState(parsedState: {
  state: Row;
  valueState: typeof VALUE_STATES[number];
  lower: number | null;
  upper: number | null;
  numerator: number | null;
  denominator: number | null;
  parsed: ReturnType<typeof parseStatistics>;
}): void {
  const { state, valueState, lower, upper, numerator, denominator, parsed } = parsedState;
  if (
    state.projection_version !== "metric-contract-v2-projection-8"
    || state.metric_key !== "outcome.verified_requirement_coverage"
  ) return;

  const statistics = parsed.statistics;
  const nonnumeric = numerator === null && denominator === null && state.numeric_value === null;
  const nullBounds = lower === null && upper === null;
  const exactBounds = (expectedLower: number, expectedUpper: number) => (
    lower !== null
    && upper !== null
    && Math.abs(lower - expectedLower) <= 1e-9
    && Math.abs(upper - expectedUpper) <= 1e-9
  );
  const frozenOwnership = statistics.superseded_excluded_count === 0
    && statistics.distinct_owner_count === parsed.eligible;
  const zeroCounts = parsed.eligible === 0
    && parsed.met === 0
    && parsed.notMet === 0
    && parsed.pending === 0
    && parsed.unknown === 0;
  const unresolvedCounts = parsed.eligible > 0
    && parsed.met === 0
    && parsed.notMet === 0
    && parsed.pending === 0
    && parsed.unknown === parsed.eligible;

  if (!frozenOwnership) throw new MetricPublicationV2PayloadError();

  const legal = (
    valueState === "unknown"
    && state.explanation_code === "reviewed_requirement_authority_unavailable"
    && statistics.capability_available === false
    && statistics.source_complete === true
    && nonnumeric
    && nullBounds
    && zeroCounts
  ) || (
    valueState === "unknown"
    && state.explanation_code === "reviewed_requirement_authority_invalid"
    && statistics.capability_available === true
    && statistics.source_complete === false
    && nonnumeric
    && nullBounds
    && zeroCounts
  ) || (
    valueState === "unknown"
    && state.explanation_code === "typed_objective_opportunity_count_exceeds_receipt_bound"
    && statistics.capability_available === true
    && statistics.source_complete === true
    && nonnumeric
    && nullBounds
    && zeroCounts
  ) || (
    valueState === "not_applicable"
    && state.explanation_code === "reviewed_requirement_set_empty"
    && statistics.capability_available === true
    && statistics.source_complete === true
    && nonnumeric
    && nullBounds
    && zeroCounts
  ) || (
    valueState === "unknown"
    && state.explanation_code === "requirement_verification_evidence_unavailable"
    && statistics.capability_available === true
    && statistics.source_complete === true
    && nonnumeric
    && unresolvedCounts
    && exactBounds(0, 1)
  ) || (
    valueState === "unknown"
    && state.explanation_code === "requirement_verification_authority_invalid"
    && statistics.capability_available === true
    && statistics.source_complete === false
    && nonnumeric
    && unresolvedCounts
    && exactBounds(0, 1)
  ) || (
    valueState === "unknown"
    && state.explanation_code === "app_issued_requirement_verification_pending"
    && statistics.capability_available === true
    && statistics.source_complete === true
    && nonnumeric
    && parsed.eligible > 0
    && parsed.pending === 0
    && parsed.unknown > 0
    && exactBounds(
      parsed.met / parsed.eligible,
      (parsed.met + parsed.unknown) / parsed.eligible,
    )
  ) || (
    valueState === "known"
    && state.explanation_code === "app_issued_verified_requirement_coverage"
    && statistics.capability_available === true
    && statistics.source_complete === true
    && parsed.eligible > 0
    && parsed.pending === 0
    && parsed.unknown === 0
  );
  if (!legal) throw new MetricPublicationV2PayloadError();
}

function parseState(value: unknown, expectedMetricKey: string) {
  const state = record(value);
  const identity = METRIC_V2_CONTRACT_IDENTITIES[expectedMetricKey as MetricKeyV2];
  // Registry order is a shape rule; identity comes right after it and before any
  // other shape check, so a compact row published under another registry
  // version or contract fingerprint (even one whose shape also moved) reads as
  // "definitions out of date" rather than as a malformed page.
  if (identity === undefined || state.metric_key !== expectedMetricKey) {
    throw new MetricPublicationV2PayloadError();
  }
  const fingerprintCandidate = typeof state.contract_fingerprint === "string" && HEX_64.test(state.contract_fingerprint)
    ? state.contract_fingerprint
    : null;
  const compatibility = metricDefinitionCompatibility({
    registry_version: state.registry_version,
    metric_contract_fingerprints: fingerprintCandidate === null
      ? undefined
      : [{ metric_key: expectedMetricKey, contract_fingerprint: fingerprintCandidate }],
  });
  if (compatibility.state === "definitions_out_of_date") {
    throw new MetricDefinitionsOutOfDateError(compatibility.mismatch);
  }
  exact(state, [
    "metric_key", "registry_version", "contract_version", "contract_fingerprint",
    "evidence_authority", "value_state", "explanation_code", "numerator",
    "denominator", "numeric_value", "censoring_lower_bound",
    "censoring_upper_bound", "statistics", "projection_version",
    "product_metric_eligible",
  ]);
  requireReadableProjectionVersion(state.projection_version);
  if (
    fingerprintCandidate === null
    || state.contract_version !== "probabilistic-metric-contract-v2"
    || state.product_metric_eligible !== false
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  const authority = oneOf(state.evidence_authority, ["conversation", "objective_receipt"] as const);
  const valueState = oneOf(state.value_state, VALUE_STATES);
  safeLabel(state.explanation_code);
  const numerator = state.numerator === null ? null : integer(state.numerator, 0, 1_000_000);
  const denominator = state.denominator === null ? null : integer(state.denominator, 1, 1_000_000);
  const numericValue = optionalFinite(state.numeric_value);
  const lower = optionalFinite(state.censoring_lower_bound);
  const upper = optionalFinite(state.censoring_upper_bound);
  const parsed = parseStatistics(state.statistics, expectedMetricKey);
  const reviewedRequirementActionUnavailableException =
    ["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      state.projection_version,
    )
    && expectedMetricKey === "logic.requirement_action_traceability"
    && valueState === "unknown"
    && state.explanation_code === "requirement_action_evidence_unavailable"
    && parsed.statistics.capability_available === false
    && parsed.statistics.source_complete === true
    && parsed.met === 0
    && parsed.notMet === 0
    && parsed.pending === 0
    && parsed.unknown === parsed.eligible;
  if (
    authority !== identity.authority
    || parsed.denominatorBasis !== identity.basis
    || parsed.statistics.opportunity_unit_kind !== identity.unit
    || (lower === null) !== (upper === null)
    || (lower !== null && upper !== null && lower > upper)
    // A right-censored value always travels with its exact bounds: met/eligible
    // below, (met + pending)/eligible above. It is only authoritative when the
    // capability and source are complete; an unknown count is never pending.
    || (valueState === "pending" && (
      !parsed.statistics.capability_available
      || !parsed.statistics.source_complete
      || parsed.eligible === 0
      || parsed.pending === 0
      || lower === null || upper === null || parsed.unknown !== 0
      || Math.abs(lower - parsed.met / parsed.eligible) > 1e-9
      || Math.abs(upper - (parsed.met + parsed.pending) / parsed.eligible) > 1e-9
    ))
    || (valueState === "not_applicable" && parsed.eligible !== 0)
    || (!parsed.statistics.capability_available && parsed.eligible !== 0
      && !reviewedRequirementActionUnavailableException)
    || (authority === "objective_receipt" && valueState === "known"
      && parsed.denominatorBasis !== "objective_opportunities")
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  if (valueState === "known") {
    if (
      numerator === null || denominator === null || numerator > denominator || numericValue === null
      || Math.abs(numericValue - numerator / denominator) > 1e-9
      || lower !== numericValue || upper !== numericValue
      || !parsed.statistics.capability_available || !parsed.statistics.source_complete
      || denominator !== parsed.eligible || numerator !== parsed.met
      || parsed.pending !== 0 || parsed.unknown !== 0
      || parsed.notMet !== parsed.eligible - parsed.met
    ) {
      throw new MetricPublicationV2PayloadError();
    }
  } else if (numerator !== null || denominator !== null || numericValue !== null) {
    throw new MetricPublicationV2PayloadError();
  }
  const parsedState = { state, authority, valueState, lower, upper, numerator, denominator, parsed };
  validateR8VerifiedRequirementState(parsedState);
  return parsedState;
}

/** Strict parser for one compact V2 trajectory state in registry order. */
export function parseMetricV2State(
  value: unknown,
  expectedMetricKey: string,
): MetricPublicationV2["metrics"][number]["state"] {
  return parseState(value, expectedMetricKey).state as MetricPublicationV2["metrics"][number]["state"];
}

/** Exact reviewed-r6 denominator authority used by projection 7. */
function hasExactPendingCensoringBounds(
  state: MetricPublicationV2["metrics"][number]["state"],
): boolean {
  const lower = state.censoring_lower_bound;
  const upper = state.censoring_upper_bound;
  const statistics = state.statistics;
  return typeof lower === "number"
    && typeof upper === "number"
    && statistics.eligible_count > 0
    && Math.abs(lower - statistics.met_count / statistics.eligible_count) <= 1e-9
    && Math.abs(upper - (statistics.met_count + statistics.pending_count)
      / statistics.eligible_count) <= 1e-9;
}

export function isReviewedRequirementPlanState(
  state: MetricPublicationV2["metrics"][number]["state"],
): boolean {
  if (
    state.metric_key !== "logic.decomposition_coverage"
    || ![
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(
      state.projection_version,
    )
    || state.statistics.capability_available !== true
    || state.statistics.source_complete !== true
    || state.statistics.unknown_count !== 0
  ) return false;
  if (state.value_state === "known") {
    return state.explanation_code === "reviewed_requirement_plan_links";
  }
  if (state.value_state === "pending") {
    return state.explanation_code === "opportunity_right_censored"
      && state.statistics.eligible_count > 0
      && state.statistics.pending_count > 0
      && hasExactPendingCensoringBounds(state);
  }
  return state.value_state === "not_applicable"
    && state.explanation_code === "no_opportunity_observed"
    && state.statistics.eligible_count === 0
    && state.statistics.met_count === 0
    && state.statistics.not_met_count === 0
    && state.statistics.pending_count === 0;
}

/** Exact reviewed r7/r8 action authority after the shared state resolver runs. */
export function isReviewedRequirementActionState(
  state: MetricPublicationV2["metrics"][number]["state"],
): boolean {
  if (
    state.metric_key !== "logic.requirement_action_traceability"
    || !["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      state.projection_version,
    )
    || state.statistics.capability_available !== true
    || state.statistics.source_complete !== true
    || state.statistics.unknown_count !== 0
  ) return false;
  if (state.value_state === "known") {
    return state.explanation_code === "reviewed_requirement_action_links";
  }
  if (state.value_state === "pending") {
    return state.explanation_code === "opportunity_right_censored"
      && state.statistics.eligible_count > 0
      && state.statistics.pending_count > 0
      && hasExactPendingCensoringBounds(state);
  }
  return state.value_state === "not_applicable"
    && state.explanation_code === "no_opportunity_observed"
    && state.statistics.eligible_count === 0
    && state.statistics.met_count === 0
    && state.statistics.not_met_count === 0
    && state.statistics.pending_count === 0;
}

function parseGuidance(value: unknown, parsedState: ReturnType<typeof parseState>) {
  const guidance = record(value);
  // Identity before shape, as for the state row: a receipt for another guidance
  // contract or template catalog is a client-update condition even when its
  // field set also changed.
  const guidanceCompatibility = metricDefinitionCompatibility({
    registry_version: guidance.registry_version,
    guidance_contract_version: guidance.contract_version,
    guidance_template_catalog_version: guidance.template_catalog_version,
  });
  if (guidanceCompatibility.state === "definitions_out_of_date") {
    throw new MetricDefinitionsOutOfDateError(guidanceCompatibility.mismatch);
  }
  exact(guidance, [
    "schema_version", "contract_version", "template_catalog_version", "template_version",
    "metric_key", "metric_version", "registry_version", "metric_contract_version",
    "metric_contract_fingerprint", "evidence_authority", "denominator_basis",
    "contract_factor_count", "audience", "role", "value_state", "state_class",
    "basis", "value_origin", "factor_evidence", "focus_factor_keys", "reason_code",
    "diagnosis_template_id", "action_template_id", "verification_template_id",
    "numerator", "denominator", "censoring_lower_bound", "censoring_upper_bound",
    "eligible_count", "met_count", "not_met_count", "pending_count", "unknown_count",
    "product_metric_eligible",
  ]);
  if (
    guidance.schema_version !== 1
    || integer(guidance.template_version, 1, 1) !== 1
    || guidance.metric_key !== parsedState.state.metric_key
    || integer(guidance.metric_version, 1, 1_000_000) < 1
    || guidance.metric_contract_version !== parsedState.state.contract_version
    || guidance.metric_contract_fingerprint !== parsedState.state.contract_fingerprint
    || guidance.evidence_authority !== parsedState.authority
    || guidance.denominator_basis !== parsedState.parsed.denominatorBasis
    || guidance.value_state !== parsedState.valueState
    // The producer copies the state's explanation code as the guidance reason:
    // the two surfaces that quote them must never disagree.
    || guidance.reason_code !== parsedState.state.explanation_code
    || guidance.product_metric_eligible !== false
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  oneOf(guidance.audience, ["user", "agent", "workflow", "tooling"] as const);
  oneOf(guidance.role, [
    "specification_signal", "collaboration_signal", "traceability_signal",
    "outcome_evidence", "friction_signal",
  ] as const);
  const stateClass = oneOf(guidance.state_class, [
    "known_retain", "known_improve", "pending_closure", "objective_evidence_missing",
    "objective_evidence_unresolved", "evidence_unresolved", "no_opportunity",
    "evidence_coverage_abstained", "analysis_failed",
  ] as const);
  const basis = oneOf(guidance.basis, ["measured", "experimental", "readiness", "method-only"] as const);
  const valueOrigin = oneOf(guidance.value_origin, ["none", "deterministic_local", "typed_objective", "neural_uncalibrated"] as const);
  const factorEvidence = oneOf(guidance.factor_evidence, [
    "not_observed", "aggregate_only", "per_factor_measured",
  ] as const);
  const contractFactorCount = integer(guidance.contract_factor_count, 1, 8);
  // Focus factors may be named only when per-factor sufficient statistics were
  // measured, never from an aggregate count or an unobserved factor set, and
  // never more than two: a rubric numerator proves a count, not an identity.
  if (
    !Array.isArray(guidance.focus_factor_keys)
    || guidance.focus_factor_keys.length > MAX_GUIDANCE_FOCUS_FACTOR_KEYS
    || guidance.focus_factor_keys.length > contractFactorCount
    || (guidance.focus_factor_keys.length > 0 && factorEvidence !== "per_factor_measured")
    || new Set(guidance.focus_factor_keys).size !== guidance.focus_factor_keys.length
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  guidance.focus_factor_keys.forEach((key) => safeLabel(key));
  safeLabel(guidance.reason_code);
  safeLabel(guidance.diagnosis_template_id);
  safeLabel(guidance.action_template_id);
  safeLabel(guidance.verification_template_id);
  const expectedTemplates = expectedMetricGuidanceTemplateIdentities(
    parsedState.state.metric_key as string,
    stateClass,
  );
  if (
    guidance.diagnosis_template_id !== expectedTemplates.diagnosis
    || guidance.action_template_id !== expectedTemplates.action
    || guidance.verification_template_id !== expectedTemplates.verification
  ) {
    throw new MetricDefinitionsOutOfDateError("guidance_template_identity");
  }
  const optionalInteger = (candidate: unknown, minimum: number, maximum: number) => (
    candidate === null ? null : integer(candidate, minimum, maximum)
  );
  if (
    optionalInteger(guidance.numerator, 0, 1_000_000) !== parsedState.numerator
    || optionalInteger(guidance.denominator, 1, 1_000_000) !== parsedState.denominator
    || optionalFinite(guidance.censoring_lower_bound) !== parsedState.lower
    || optionalFinite(guidance.censoring_upper_bound) !== parsedState.upper
    || integer(guidance.eligible_count, 0, 1_000_000) !== parsedState.parsed.eligible
    || integer(guidance.met_count, 0, 1_000_000) !== parsedState.parsed.met
    || integer(guidance.not_met_count, 0, 1_000_000) !== parsedState.parsed.notMet
    || integer(guidance.pending_count, 0, 1_000_000) !== parsedState.parsed.pending
    || integer(guidance.unknown_count, 0, 1_000_000) !== parsedState.parsed.unknown
  ) {
    throw new MetricPublicationV2PayloadError();
  }

  // A canonical live publication consumes no model-stage output and persists
  // no per-factor receipts. Re-derive these labels rather than trusting a
  // structurally valid but semantically relabelled API response.
  const expectedStateClass = parsedState.valueState === "pending" ? "pending_closure"
    : parsedState.valueState === "not_applicable" ? "no_opportunity"
      : parsedState.valueState === "abstained" ? "evidence_coverage_abstained"
        : parsedState.valueState === "execution_error" ? "analysis_failed"
          : parsedState.valueState === "unknown"
            ? parsedState.authority === "objective_receipt"
              ? (parsedState.parsed.statistics.capability_available && parsedState.parsed.eligible > 0
                ? "objective_evidence_unresolved"
                : "objective_evidence_missing")
              : "evidence_unresolved"
            : null;
  // A known state keeps the producer's retain/improve decision as published: the
  // client renders that state class and never re-decides it from the value.
  // Aggregate-only factor evidence is method-level guidance (no measured basis).
  if (
    (parsedState.valueState === "known" && (
      !["known_retain", "known_improve"].includes(stateClass)
      || basis !== (factorEvidence === "aggregate_only" ? "method-only" : "measured")
      || valueOrigin !== (parsedState.authority === "objective_receipt" ? "typed_objective" : "deterministic_local")
    ))
    || (parsedState.valueState !== "known" && (
      factorEvidence !== "not_observed"
      || stateClass !== expectedStateClass
      || valueOrigin !== "none"
      || basis !== (parsedState.valueState === "execution_error" ? "method-only" : "readiness")
    ))
  ) {
    throw new MetricPublicationV2PayloadError();
  }
}

export function parseMetricPublicationV2(value: unknown): MetricPublicationV2 {
  const publication = record(value);
  // Identity first: a publication for another registry version or contract set
  // is "definitions out of date" even when its shape also differs.
  const compatibility = metricDefinitionCompatibility({
    registry_version: publication.registry_version,
    contract_set_fingerprint: publication.contract_set_fingerprint,
    guidance_contract_version: publication.guidance_contract_version,
    guidance_template_catalog_version: publication.guidance_template_catalog_version,
  });
  if (compatibility.state === "definitions_out_of_date") {
    throw new MetricDefinitionsOutOfDateError(compatibility.mismatch);
  }
  exact(publication, [
    "publication_key", "publication_version", "registry_version",
    "contract_set_fingerprint", "projection_version", "guidance_contract_version",
    "guidance_template_catalog_version", "source", "canonical_live_snapshot",
    "model_stage_consumed", "compatibility_preview", "metrics", "known_count",
    "pending_count", "unknown_count", "not_applicable_count", "abstained_count",
    "execution_error_count", "objective_measured_count", "product_metric_eligible",
  ]);
  requireReadableProjectionVersion(publication.projection_version);
  if (
    publication.publication_key !== "metric.contract-v2.publication"
    || publication.publication_version !== 2
    || publication.source !== "live_projection"
    || publication.canonical_live_snapshot !== true
    || publication.model_stage_consumed !== false
    || publication.compatibility_preview !== false
    || publication.product_metric_eligible !== false
    || !Array.isArray(publication.metrics)
    || publication.metrics.length !== METRIC_V2_KEYS.length
  ) {
    throw new MetricPublicationV2PayloadError();
  }
  const counts = new Map<string, number>();
  const parsedStates = new Map<string, ReturnType<typeof parseState>>();
  let objectiveMeasured = 0;
  publication.metrics.forEach((candidate, ordinal) => {
    const item = record(candidate);
    exact(item, ["state", "guidance", "implementation_state"]);
    const parsedState = parseState(item.state, METRIC_V2_KEYS[ordinal]);
    if (parsedState.state.projection_version !== publication.projection_version) {
      throw new MetricPublicationV2PayloadError();
    }
    parseGuidance(item.guidance, parsedState);
    const implementation = oneOf(item.implementation_state, IMPLEMENTATION_STATES);
    const expected = parsedState.valueState === "known" ? "live_measured"
      : parsedState.valueState === "pending" ? "pending"
        : parsedState.valueState === "not_applicable" ? "no_opportunity"
          : parsedState.valueState === "abstained" ? "abstained"
            : parsedState.valueState === "execution_error" ? "error" : null;
    if (expected !== null && implementation !== expected) {
      throw new MetricPublicationV2PayloadError();
    }
    const expectedUnknownImplementation = parsedState.authority === "objective_receipt"
      // Implementation state deliberately keys on capability alone: an eligible
      // count of zero is not itself a capability failure (the projection may
      // withhold cardinality). The guidance state class above keys on both.
      ? (parsedState.parsed.statistics.capability_available
        ? "objective_evidence_unresolved"
        : "objective_capability_missing")
      : "method_only_withheld";
    if (
      parsedState.valueState === "unknown"
      && implementation !== expectedUnknownImplementation
    ) {
      throw new MetricPublicationV2PayloadError();
    }
    parsedStates.set(parsedState.state.metric_key as string, parsedState);
    counts.set(parsedState.valueState, (counts.get(parsedState.valueState) ?? 0) + 1);
    if (parsedState.authority === "objective_receipt" && parsedState.valueState === "known") {
      objectiveMeasured += 1;
    }
  });
  if (["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
    publication.projection_version,
  )) {
    const requirementPlan = parsedStates.get("logic.decomposition_coverage");
    const requirementAction = parsedStates.get("logic.requirement_action_traceability");
    if (requirementPlan === undefined || requirementAction === undefined) {
      throw new MetricPublicationV2PayloadError();
    }
    const actionResolved = (["known", "pending", "not_applicable"] as const).includes(
      requirementAction.valueState as "known" | "pending" | "not_applicable",
    );
    const reviewedAction = isReviewedRequirementActionState(
      requirementAction.state as MetricPublicationV2["metrics"][number]["state"],
    );
    if (actionResolved && !reviewedAction) throw new MetricPublicationV2PayloadError();
    const reviewedPlan = isReviewedRequirementPlanState(
      requirementPlan.state as MetricPublicationV2["metrics"][number]["state"],
    );
    if (
      (reviewedPlan
        ? requirementAction.parsed.eligible !== requirementPlan.parsed.eligible
        : requirementAction.parsed.eligible !== 0)
      || (reviewedAction && !reviewedPlan)
    ) {
      throw new MetricPublicationV2PayloadError();
    }
  }
  if ([
    "metric-contract-v2-projection-6",
    "metric-contract-v2-projection-7",
    "metric-contract-v2-projection-8",
  ].includes(
    publication.projection_version as string,
  )) {
    const requirementPlan = parsedStates.get("logic.decomposition_coverage");
    if (
      requirementPlan !== undefined
      && (["known", "pending", "not_applicable"] as const).includes(
        requirementPlan.valueState as "known" | "pending" | "not_applicable",
      )
      && !isReviewedRequirementPlanState(
        requirementPlan.state as MetricPublicationV2["metrics"][number]["state"],
      )
    ) throw new MetricPublicationV2PayloadError();
  }
  const declared = [
    ["known", publication.known_count], ["pending", publication.pending_count],
    ["unknown", publication.unknown_count], ["not_applicable", publication.not_applicable_count],
    ["abstained", publication.abstained_count], ["execution_error", publication.execution_error_count],
  ] as const;
  let total = 0;
  for (const [state, candidate] of declared) {
    const count = integer(candidate, 0, 20);
    if (count !== (counts.get(state) ?? 0)) throw new MetricPublicationV2PayloadError();
    total += count;
  }
  if (total !== 20 || integer(publication.objective_measured_count, 0, 5) !== objectiveMeasured) {
    throw new MetricPublicationV2PayloadError();
  }
  return value as MetricPublicationV2;
}
