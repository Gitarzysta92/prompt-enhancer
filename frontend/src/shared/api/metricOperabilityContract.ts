import type {
  MetricOperabilityCatalog,
  MetricOperabilityEntry,
} from "./contracts";
import {
  METRIC_CONTRACT_V2_REGISTRY_VERSION,
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_V2_CONTRACT_IDENTITIES,
  METRIC_V2_KEYS,
} from "./metricPublicationV2Contract";

type Row = Record<string, unknown>;
type MetricKey = (typeof METRIC_V2_KEYS)[number];
type ExpectedOperability = Pick<
  MetricOperabilityEntry,
  "measured_path" | "shipped_path_state" | "next_step_code" | "experimental_model_path"
>;

const CATALOG_KEYS = [
  "catalog_version",
  "registry_version",
  "contract_set_fingerprint",
  "projection_version",
  "readiness_catalog_version",
  "total_metric_count",
  "shipped_path_count",
  "task_profile_configuration_gap_count",
  "provider_adapter_gap_count",
  "experimental_model_path_count",
  "model_authoritative_metric_count",
  "entries",
  "local_only",
  "content_persisted",
] as const;

const ENTRY_KEYS = [
  "metric_key",
  "contract_version",
  "contract_fingerprint",
  "evidence_authority",
  "denominator_basis",
  "measured_path",
  "shipped_path_state",
  "next_step_code",
  "experimental_model_path",
  "measured_value_may_use_model_output",
] as const;

const FOCUS_RUBRIC_KEYS = new Set<MetricKey>([
  "prompt.task_definition_coverage",
  "prompt.problem_evidence_quality",
  "prompt.context_sufficiency",
]);
const TASK_PROFILE_KEYS = new Set<MetricKey>([
  "prompt.constraint_precision",
  "prompt.acceptance_testability",
  "prompt.deliverable_contract",
]);
const LIFECYCLE_KEYS = new Set<MetricKey>([
  "collaboration.ambiguity_resolution",
  "collaboration.clarification_yield",
  "collaboration.exploration_conversion",
  "collaboration.scope_change_discipline",
  "collaboration.rework_candidate_rate",
]);
const TYPED_OBJECTIVE_GAP_KEYS = new Set<MetricKey>([
  "logic.hypothesis_test_linkage",
  "outcome.agent_claim_grounding",
  "outcome.verified_requirement_coverage",
]);
const DOCUMENTED_UNIT_KEYS = new Set<MetricKey>([
  "logic.decision_rationale_coverage",
  "outcome.verification_strategy_adequacy",
]);
export class MetricOperabilityPayloadError extends Error {
  constructor() {
    super("Metric operability catalog was invalid");
    this.name = "MetricOperabilityPayloadError";
  }
}

export class MetricOperabilityDefinitionsOutOfDateError extends MetricOperabilityPayloadError {
  constructor() {
    super();
    this.name = "MetricOperabilityDefinitionsOutOfDateError";
    this.message = "Metric operability definitions do not match this client";
  }
}

function record(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new MetricOperabilityPayloadError();
  }
  return value as Row;
}

function exactKeys(value: Row, expected: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  if (
    actual.length !== sortedExpected.length
    || actual.some((key, index) => key !== sortedExpected[index])
  ) {
    throw new MetricOperabilityPayloadError();
  }
}

function expectedOperability(metricKey: MetricKey): ExpectedOperability {
  if (FOCUS_RUBRIC_KEYS.has(metricKey)) {
    return {
      measured_path: "focus_rubric",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "analyze_focus_request",
      experimental_model_path: true,
    };
  }
  if (TASK_PROFILE_KEYS.has(metricKey)) {
    return {
      measured_path: "declared_task_profile",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "declare_task_profile",
      experimental_model_path: true,
    };
  }
  if (LIFECYCLE_KEYS.has(metricKey)) {
    return {
      measured_path: "confirmed_lifecycle",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "confirm_lifecycle_evidence",
      experimental_model_path: false,
    };
  }
  if (metricKey === "logic.decomposition_coverage") {
    return {
      measured_path: "reviewed_requirement_plan",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "confirm_requirement_plan_evidence",
      experimental_model_path: true,
    };
  }
  if (metricKey === "logic.requirement_action_traceability") {
    return {
      measured_path: "reviewed_requirement_action",
      shipped_path_state: "provider_adapter_required",
      next_step_code: "compose_requirement_action_evidence",
      experimental_model_path: false,
    };
  }
  if (TYPED_OBJECTIVE_GAP_KEYS.has(metricKey)) {
    return {
      measured_path: "typed_objective",
      shipped_path_state: "provider_adapter_required",
      next_step_code: "add_objective_opportunity_link_adapter",
      experimental_model_path: false,
    };
  }
  if (DOCUMENTED_UNIT_KEYS.has(metricKey)) {
    return {
      measured_path: "documented_semantic_unit",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "record_documented_decision",
      experimental_model_path: metricKey === "logic.decision_rationale_coverage",
    };
  }
  if (metricKey === "logic.open_loop_closure") {
    return {
      measured_path: "explicit_plan_link",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "link_plan_supersession",
      experimental_model_path: false,
    };
  }
  if (metricKey === "outcome.first_pass_verification") {
    return {
      measured_path: "task_scoped_verification",
      shipped_path_state: "available_when_evidence_exists",
      next_step_code: "record_task_scoped_verification",
      experimental_model_path: false,
    };
  }
  throw new MetricOperabilityPayloadError();
}

/**
 * Current provider-adapter gaps in the canonical coaching contract.
 *
 * Derived from the same strict expected-operability table that parses the
 * server catalog, so presentation cannot drift from the release gate. These
 * identities remain in an exact analysis receipt, but text-derived output has
 * no authority to fill them while the adapter is unavailable.
 */
export const METRIC_V2_PROVIDER_ADAPTER_GAP_KEYS = METRIC_V2_KEYS.filter(
  (metricKey) => (
    expectedOperability(metricKey).shipped_path_state === "provider_adapter_required"
  ),
);

function parseEntry(value: unknown, metricKey: MetricKey): MetricOperabilityEntry {
  const entry = record(value);
  exactKeys(entry, ENTRY_KEYS);
  const identity = METRIC_V2_CONTRACT_IDENTITIES[metricKey];
  const expected = expectedOperability(metricKey);
  if (
    entry.metric_key !== metricKey
    || entry.contract_version !== "probabilistic-metric-contract-v2"
    || entry.contract_fingerprint !== identity.fingerprint
    || entry.evidence_authority !== identity.authority
    || entry.denominator_basis !== identity.basis
    || entry.measured_path !== expected.measured_path
    || entry.shipped_path_state !== expected.shipped_path_state
    || entry.next_step_code !== expected.next_step_code
    || entry.experimental_model_path !== expected.experimental_model_path
    || entry.measured_value_may_use_model_output !== false
  ) {
    throw new MetricOperabilityDefinitionsOutOfDateError();
  }
  return entry as unknown as MetricOperabilityEntry;
}

export function parseMetricOperabilityCatalog(value: unknown): MetricOperabilityCatalog {
  const catalog = record(value);
  const rawEntries = catalog.entries;
  exactKeys(catalog, CATALOG_KEYS);
  if (
    catalog.catalog_version !== "metric-operability-v4"
    || catalog.registry_version !== METRIC_CONTRACT_V2_REGISTRY_VERSION
    || catalog.contract_set_fingerprint !== METRIC_CONTRACT_V2_SET_FINGERPRINT
    || catalog.projection_version !== "metric-contract-v2-projection-8"
    || catalog.readiness_catalog_version !== "metric-evidence-readiness-v2-7"
  ) {
    throw new MetricOperabilityDefinitionsOutOfDateError();
  }
  if (
    catalog.total_metric_count !== 20
    || catalog.shipped_path_count !== 16
    || catalog.task_profile_configuration_gap_count !== 0
    || catalog.provider_adapter_gap_count !== 4
    || catalog.experimental_model_path_count !== 8
    || catalog.model_authoritative_metric_count !== 0
    || catalog.local_only !== true
    || catalog.content_persisted !== false
    || !Array.isArray(rawEntries)
    || rawEntries.length !== METRIC_V2_KEYS.length
  ) {
    throw new MetricOperabilityPayloadError();
  }
  const entries = METRIC_V2_KEYS.map((metricKey, index) =>
    parseEntry(rawEntries[index], metricKey));
  return { ...catalog, entries } as unknown as MetricOperabilityCatalog;
}

/** Exact fictional transport fixture; it contains no session or project data. */
export function createSyntheticMetricOperabilityCatalog(): MetricOperabilityCatalog {
  const entries = METRIC_V2_KEYS.map((metricKey) => {
    const identity = METRIC_V2_CONTRACT_IDENTITIES[metricKey];
    return {
      metric_key: metricKey,
      contract_version: "probabilistic-metric-contract-v2",
      contract_fingerprint: identity.fingerprint,
      evidence_authority: identity.authority,
      denominator_basis: identity.basis,
      ...expectedOperability(metricKey),
      measured_value_may_use_model_output: false,
    } satisfies MetricOperabilityEntry;
  });
  return {
    catalog_version: "metric-operability-v4",
    registry_version: METRIC_CONTRACT_V2_REGISTRY_VERSION,
    contract_set_fingerprint: METRIC_CONTRACT_V2_SET_FINGERPRINT,
    projection_version: "metric-contract-v2-projection-8",
    readiness_catalog_version: "metric-evidence-readiness-v2-7",
    total_metric_count: 20,
    shipped_path_count: 16,
    task_profile_configuration_gap_count: 0,
    provider_adapter_gap_count: 4,
    experimental_model_path_count: 8,
    model_authoritative_metric_count: 0,
    entries,
    local_only: true,
    content_persisted: false,
  } satisfies MetricOperabilityCatalog;
}
