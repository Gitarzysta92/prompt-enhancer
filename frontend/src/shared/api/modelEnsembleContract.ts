import type {
  ModelEnsembleOutcome,
  ModelEnsembleRun,
} from "./contracts";
import {
  isReviewedRequirementActionState,
  isReviewedRequirementPlanState,
  MetricDefinitionsOutOfDateError,
  parseMetricPublicationV2,
} from "./metricPublicationV2Contract";

export class ModelEnsemblePayloadError extends Error {
  constructor() {
    super("Local model ensemble response was invalid");
    this.name = "ModelEnsemblePayloadError";
  }
}

type Row = Record<string, unknown>;
type EnsembleMetric = ModelEnsembleRun["metrics"][number];
type TypedMetric = ModelEnsembleRun["typed_metrics"][number];
type PredictiveMetric = ModelEnsembleRun["predictive_metrics"][number];
export type ModelMetricProfileBinding = NonNullable<ModelEnsembleRun["metric_profile_binding"]>;
export type ModelRequirementPlanEvidenceBinding = NonNullable<
  ModelEnsembleRun["requirement_plan_evidence_binding"]
>;
export type ModelRequirementActionEvidenceBinding = NonNullable<
  ModelEnsembleRun["requirement_action_evidence_binding"]
>;
export type ModelRequirementVerificationEvidenceBinding = NonNullable<
  ModelEnsembleRun["requirement_verification_evidence_binding"]
>;

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_LABEL = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const AWAITING_REVIEW_REQUIREMENT_PLAN_FINGERPRINT =
  "843a2a5154affde7f7cddc19137dfcdfa8253d9f541c98b6e2cdabd930401ff2";
const UNAVAILABLE_REQUIREMENT_ACTION_FINGERPRINT =
  "9059e785839871abf94e1fea1c86c48e737621047a526cd3c9e94099a5b5e07f";
const AWAITING_REVIEW_REQUIREMENT_ACTION_FINGERPRINT =
  "0ca65041b98be25e41cbbba908641f116f0e81b45416f89fd7ddf177489add4a";
const OVERFLOW_REQUIREMENT_ACTION_FINGERPRINT =
  "528224b052ffbec5c2b404b8970ab2ced61b84bc39cc20d70fd77320a059875f";
const SOURCE_INCOMPLETE_REQUIREMENT_ACTION_FINGERPRINT =
  "d44bd4fa494e3123c7cb6f23ada45473204a55736c8a0ae9e5305ba30d91c699";
const BINDING_INVALID_REQUIREMENT_ACTION_FINGERPRINT =
  "357ed7bbb833a8dfbd8f907e8309c363957460c6053d5b9d77d069bbbb7e55da";

function record(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ModelEnsemblePayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new ModelEnsemblePayloadError();
  }
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (!Number.isInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new ModelEnsemblePayloadError();
  }
  return value as number;
}

function finite(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new ModelEnsemblePayloadError();
  }
  return value;
}

function optionalFinite(value: unknown, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number | null {
  return value === null ? null : finite(value, minimum, maximum);
}

function label(value: unknown): string {
  if (typeof value !== "string" || !SAFE_LABEL.test(value)) {
    throw new ModelEnsemblePayloadError();
  }
  return value;
}

function oneOf<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    throw new ModelEnsemblePayloadError();
  }
  return value as T;
}

function utcTimestamp(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
  ) {
    throw new ModelEnsemblePayloadError();
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  const parsed = new Date(value);
  if (
    match === null ||
    Number.isNaN(parsed.getTime()) ||
    parsed.getUTCFullYear() !== Number(match[1]) ||
    parsed.getUTCMonth() + 1 !== Number(match[2]) ||
    parsed.getUTCDate() !== Number(match[3]) ||
    parsed.getUTCHours() !== Number(match[4]) ||
    parsed.getUTCMinutes() !== Number(match[5]) ||
    parsed.getUTCSeconds() !== Number(match[6])
  ) {
    throw new ModelEnsemblePayloadError();
  }
  return value;
}

const VOTE_STATES = ["present", "absent", "abstain", "unsupported", "failed"] as const;
const VALUE_STATES = ["known", "unknown", "not_applicable", "abstained", "execution_error"] as const;
const EXPERT_ROLES = ["retrieval", "reranking", "scope_nli", "structured_rubric"] as const;
const EXPERT_STATUSES = ["completed", "unavailable", "resource_exhausted", "failed"] as const;
const PREDICTIVE_STATES = [
  "unavailable", "experimental", "calibrated", "out_of_distribution", "execution_error",
] as const;
const UNCONFIGURED_PROFILE_FINGERPRINT =
  "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71";
const UNAVAILABLE_REQUIREMENT_PLAN_FINGERPRINT =
  "30f6b309825c563a881ed1b7587072222e3cb33ca70f7bff274ba968cb067641";

/**
 * Parse the deliberately minimized profile identity exposed by a sealed r5/r6
 * run. The full declaration and source-window identity stay behind the local
 * API boundary; this receipt is sufficient to bind the visible metric values
 * to the exact reviewed revision without exposing session content.
 */
export function parseModelMetricProfileBinding(value: unknown): ModelMetricProfileBinding {
  const binding = record(value);
  exact(binding, [
    "profile_source", "profile_id", "profile_revision", "profile_fingerprint",
    "profile_schema_version", "profile_policy_version", "local_only", "content_persisted",
  ]);
  const knownSources = ["coaching_profile_v1_unconfigured", "declared_task_profile"] as const;
  const knownSchemas = ["coaching-profile-v1-unconfigured", "declared-task-profile-v1"] as const;
  const knownPolicies = ["server-preset-v1", "authenticated-local-user-v1"] as const;
  for (const [candidate, known] of [
    [binding.profile_source, knownSources],
    [binding.profile_schema_version, knownSchemas],
    [binding.profile_policy_version, knownPolicies],
  ] as const) {
    if (typeof candidate === "string" && !known.includes(candidate as never)) {
      throw new MetricDefinitionsOutOfDateError("metric_profile_binding");
    }
  }
  const source = oneOf(binding.profile_source, knownSources);
  const schema = oneOf(binding.profile_schema_version, knownSchemas);
  const policy = oneOf(binding.profile_policy_version, knownPolicies);
  const profileId = binding.profile_id === null ? null : binding.profile_id;
  const revision = binding.profile_revision === null
    ? null
    : integer(binding.profile_revision, 1, 1_000_000);
  if (
    binding.local_only !== true
    || binding.content_persisted !== false
    || typeof binding.profile_fingerprint !== "string"
    || !HEX_64.test(binding.profile_fingerprint)
    || (profileId !== null && (typeof profileId !== "string" || !HEX_64.test(profileId)))
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (source === "declared_task_profile") {
    if (
      profileId === null
      || revision === null
      || schema !== "declared-task-profile-v1"
      || policy !== "authenticated-local-user-v1"
    ) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (
    profileId !== null
    || revision !== null
    || binding.profile_fingerprint !== UNCONFIGURED_PROFILE_FINGERPRINT
    || schema !== "coaching-profile-v1-unconfigured"
    || policy !== "server-preset-v1"
  ) {
    throw new ModelEnsemblePayloadError();
  }
  return value as ModelMetricProfileBinding;
}

/** Parse the minimized r6 requirement-plan authority bound to one sealed run. */
export function parseModelRequirementPlanEvidenceBinding(
  value: unknown,
): ModelRequirementPlanEvidenceBinding {
  const binding = record(value);
  exact(binding, [
    "evidence_source", "confirmation_id", "proposal_id", "evidence_fingerprint",
    "evidence_schema_version", "evidence_policy_version", "local_only",
    "content_persisted",
  ]);
  const knownSources = ["unavailable", "awaiting_review", "reviewed_requirement_plan"] as const;
  const knownSchemas = [
    "requirement-plan-unavailable-v1", "requirement-plan-awaiting-review-v1",
    "requirement-plan-evidence-v1",
  ] as const;
  if (
    (typeof binding.evidence_source === "string"
      && !knownSources.includes(binding.evidence_source as never))
    || (typeof binding.evidence_schema_version === "string"
      && !knownSchemas.includes(binding.evidence_schema_version as never))
    || (typeof binding.evidence_policy_version === "string"
      && binding.evidence_policy_version !== "reviewed-requirement-plan-v1")
  ) {
    throw new MetricDefinitionsOutOfDateError("requirement_plan_evidence_binding");
  }
  const source = oneOf(binding.evidence_source, knownSources);
  const schema = oneOf(binding.evidence_schema_version, knownSchemas);
  const confirmationId = binding.confirmation_id === null ? null : binding.confirmation_id;
  const proposalId = binding.proposal_id === null ? null : binding.proposal_id;
  if (
    binding.evidence_policy_version !== "reviewed-requirement-plan-v1"
    || binding.local_only !== true
    || binding.content_persisted !== false
    || typeof binding.evidence_fingerprint !== "string"
    || !HEX_64.test(binding.evidence_fingerprint)
    || (confirmationId !== null
      && (typeof confirmationId !== "string" || !HEX_64.test(confirmationId)))
    || (proposalId !== null
      && (typeof proposalId !== "string" || !HEX_64.test(proposalId)))
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (source === "reviewed_requirement_plan") {
    if (
      confirmationId === null
      || proposalId === null
      || schema !== "requirement-plan-evidence-v1"
      || binding.evidence_fingerprint === UNAVAILABLE_REQUIREMENT_PLAN_FINGERPRINT
      || binding.evidence_fingerprint === AWAITING_REVIEW_REQUIREMENT_PLAN_FINGERPRINT
    ) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (source === "awaiting_review") {
    if (
      confirmationId !== null
      || proposalId !== null
      || schema !== "requirement-plan-awaiting-review-v1"
      || binding.evidence_fingerprint !== AWAITING_REVIEW_REQUIREMENT_PLAN_FINGERPRINT
    ) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (
    confirmationId !== null
    || proposalId !== null
    || schema !== "requirement-plan-unavailable-v1"
    || binding.evidence_fingerprint !== UNAVAILABLE_REQUIREMENT_PLAN_FINGERPRINT
  ) {
    throw new ModelEnsemblePayloadError();
  }
  return value as ModelRequirementPlanEvidenceBinding;
}

/** Parse the minimized r7/r8 requirement-action authority bound to one sealed run. */
export function parseModelRequirementActionEvidenceBinding(
  value: unknown,
): ModelRequirementActionEvidenceBinding {
  const binding = record(value);
  exact(binding, [
    "evidence_source", "source_run_id", "requirement_plan_confirmation_id",
    "requirement_plan_evidence_fingerprint", "candidate_manifest_fingerprint",
    "confirmation_id", "proposal_id", "reviewed_descriptor_set_fingerprint",
    "evidence_fingerprint",
    "evidence_schema_version", "evidence_policy_version", "local_only",
    "content_persisted",
  ]);
  const knownSources = [
    "unavailable", "awaiting_review", "candidate_manifest_overflow",
    "candidate_source_incomplete", "binding_invalid", "reviewed_requirement_action",
  ] as const;
  const knownSchemas = [
    "requirement-action-unavailable-v1", "requirement-action-awaiting-review-v1",
    "requirement-action-candidate-manifest-overflow-v1",
    "requirement-action-candidate-source-incomplete-v1",
    "requirement-action-binding-invalid-v1",
    "requirement-action-evidence-v1",
  ] as const;
  if (
    (typeof binding.evidence_source === "string"
      && !knownSources.includes(binding.evidence_source as never))
    || (typeof binding.evidence_schema_version === "string"
      && !knownSchemas.includes(binding.evidence_schema_version as never))
    || (typeof binding.evidence_policy_version === "string"
      && binding.evidence_policy_version !== "reviewed-requirement-action-v1")
  ) {
    throw new MetricDefinitionsOutOfDateError("requirement_action_evidence_binding");
  }
  const source = oneOf(binding.evidence_source, knownSources);
  const schema = oneOf(binding.evidence_schema_version, knownSchemas);
  const authorityFields = [
    binding.source_run_id,
    binding.requirement_plan_confirmation_id,
    binding.requirement_plan_evidence_fingerprint,
    binding.candidate_manifest_fingerprint,
    binding.confirmation_id,
    binding.proposal_id,
    binding.reviewed_descriptor_set_fingerprint,
  ];
  if (
    binding.evidence_policy_version !== "reviewed-requirement-action-v1"
    || binding.local_only !== true
    || binding.content_persisted !== false
    || typeof binding.evidence_fingerprint !== "string"
    || !HEX_64.test(binding.evidence_fingerprint)
    || authorityFields.some((candidate) => candidate !== null
      && (typeof candidate !== "string" || !HEX_64.test(candidate)))
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (source === "reviewed_requirement_action") {
    if (
      authorityFields.some((candidate) => candidate === null)
      || schema !== "requirement-action-evidence-v1"
      || binding.evidence_fingerprint === UNAVAILABLE_REQUIREMENT_ACTION_FINGERPRINT
      || binding.evidence_fingerprint === AWAITING_REVIEW_REQUIREMENT_ACTION_FINGERPRINT
      || binding.evidence_fingerprint === OVERFLOW_REQUIREMENT_ACTION_FINGERPRINT
      || binding.evidence_fingerprint === SOURCE_INCOMPLETE_REQUIREMENT_ACTION_FINGERPRINT
      || binding.evidence_fingerprint === BINDING_INVALID_REQUIREMENT_ACTION_FINGERPRINT
    ) throw new ModelEnsemblePayloadError();
  } else if (source === "awaiting_review") {
    if (
      authorityFields.some((candidate) => candidate !== null)
      || schema !== "requirement-action-awaiting-review-v1"
      || binding.evidence_fingerprint !== AWAITING_REVIEW_REQUIREMENT_ACTION_FINGERPRINT
    ) throw new ModelEnsemblePayloadError();
  } else if (source === "candidate_manifest_overflow") {
    if (
      authorityFields.some((candidate) => candidate !== null)
      || schema !== "requirement-action-candidate-manifest-overflow-v1"
      || binding.evidence_fingerprint !== OVERFLOW_REQUIREMENT_ACTION_FINGERPRINT
    ) throw new ModelEnsemblePayloadError();
  } else if (source === "candidate_source_incomplete") {
    if (
      authorityFields.some((candidate) => candidate !== null)
      || schema !== "requirement-action-candidate-source-incomplete-v1"
      || binding.evidence_fingerprint !== SOURCE_INCOMPLETE_REQUIREMENT_ACTION_FINGERPRINT
    ) throw new ModelEnsemblePayloadError();
  } else if (source === "binding_invalid") {
    if (
      authorityFields.some((candidate) => candidate !== null)
      || schema !== "requirement-action-binding-invalid-v1"
      || binding.evidence_fingerprint !== BINDING_INVALID_REQUIREMENT_ACTION_FINGERPRINT
    ) throw new ModelEnsemblePayloadError();
  } else if (
    authorityFields.some((candidate) => candidate !== null)
    || schema !== "requirement-action-unavailable-v1"
    || binding.evidence_fingerprint !== UNAVAILABLE_REQUIREMENT_ACTION_FINGERPRINT
  ) {
    throw new ModelEnsemblePayloadError();
  }
  return value as ModelRequirementActionEvidenceBinding;
}

/** Parse the minimized, content-free verification authority bound to one r8 run. */
export function parseModelRequirementVerificationEvidenceBinding(
  value: unknown,
): ModelRequirementVerificationEvidenceBinding {
  const binding = record(value);
  exact(binding, [
    "evidence_source",
    "requirement_plan_confirmation_id", "requirement_plan_proposal_id",
    "requirement_plan_evidence_fingerprint", "requirement_plan_schema_version",
    "requirement_plan_policy_version", "requirement_plan_review_rubric_version",
    "opportunity_count", "opportunity_set_fingerprint", "evidence_set_fingerprint",
    "through_revision", "authority_head_count", "objective_result_count",
    "native_acceptance_count", "resolved_opportunity_count", "met_requirement_count",
    "opportunity_issuer_version", "result_issuer_version", "acceptance_issuer_version",
    "evidence_schema_version", "evidence_policy_version", "persistence_schema_version",
    "evidence_projection_version", "objective_projection_version", "binding_schema_version",
    "binding_fingerprint",
    "local_only", "content_persisted",
  ]);
  const knownSources = [
    "unavailable", "opportunity_bound_exceeded", "awaiting_evidence", "persisted_evidence",
  ] as const;
  const expectedVersions = {
    requirement_plan_schema_version: "requirement-plan-evidence-v1",
    requirement_plan_policy_version: "reviewed-requirement-plan-v1",
    requirement_plan_review_rubric_version: "active-requirement-plan-review-rubric-v1",
    opportunity_issuer_version: "reviewed-r6-requirement-opportunity-issuer-v1",
    result_issuer_version: "local-objective-verification-result-issuer-v1",
    acceptance_issuer_version: "native-explicit-requirement-acceptance-issuer-v1",
    evidence_schema_version: "requirement-verification-evidence-v1",
    evidence_policy_version: "app-issued-reviewed-requirement-verification-v1",
    persistence_schema_version: "requirement-verification-persistence-v1",
    evidence_projection_version: "reviewed-requirement-verification-objective-projection-v1",
    objective_projection_version: "reviewed-requirement-verification-objective-projection-v1",
    binding_schema_version: "session-requirement-verification-evidence-binding-v1",
  } as const;
  if (
    (typeof binding.evidence_source === "string"
      && !knownSources.includes(binding.evidence_source as never))
    || Object.entries(expectedVersions).some(([field, expected]) => {
      const candidate = binding[field];
      return candidate !== null && typeof candidate === "string" && candidate !== expected;
    })
  ) {
    throw new MetricDefinitionsOutOfDateError("requirement_verification_evidence_binding");
  }
  const source = oneOf(binding.evidence_source, knownSources);
  for (const [field, expected] of Object.entries(expectedVersions)) {
    const candidate = binding[field];
    const nullablePlanVersion = field.startsWith("requirement_plan_");
    if (candidate !== expected && !(nullablePlanVersion && candidate === null)) {
      throw new ModelEnsemblePayloadError();
    }
  }
  if (binding.local_only !== true || binding.content_persisted !== false) {
    throw new ModelEnsemblePayloadError();
  }
  const pseudonymFields = [
    "requirement_plan_confirmation_id", "requirement_plan_proposal_id",
    "requirement_plan_evidence_fingerprint", "opportunity_set_fingerprint",
    "evidence_set_fingerprint", "binding_fingerprint",
  ] as const;
  if (pseudonymFields.some((field) => (
    binding[field] !== null
    && (typeof binding[field] !== "string" || !HEX_64.test(binding[field] as string))
  ))) throw new ModelEnsemblePayloadError();
  const optionalInteger = (field: string, maximum: number): number | null => (
    binding[field] === null ? null : integer(binding[field], 0, maximum)
  );
  const opportunityCount = optionalInteger("opportunity_count", 1_000);
  const throughRevision = optionalInteger("through_revision", 32_000);
  const authorityHeadCount = optionalInteger("authority_head_count", 1_000);
  const objectiveResultCount = optionalInteger("objective_result_count", 1_000);
  const nativeAcceptanceCount = optionalInteger("native_acceptance_count", 1_000);
  const resolvedOpportunityCount = optionalInteger("resolved_opportunity_count", 1_000);
  const metRequirementCount = optionalInteger("met_requirement_count", 1_000);
  const planFields = [
    binding.requirement_plan_confirmation_id, binding.requirement_plan_proposal_id,
    binding.requirement_plan_evidence_fingerprint, binding.requirement_plan_schema_version,
    binding.requirement_plan_policy_version, binding.requirement_plan_review_rubric_version,
  ];
  const opportunityFields = [opportunityCount, binding.opportunity_set_fingerprint];
  const evidenceIdentityFields = [binding.evidence_set_fingerprint, throughRevision];
  const evidenceCounts = [
    authorityHeadCount, objectiveResultCount, nativeAcceptanceCount,
    resolvedOpportunityCount, metRequirementCount,
  ];
  if (source === "unavailable") {
    if ([...planFields, ...opportunityFields, ...evidenceIdentityFields, ...evidenceCounts]
      .some((candidate) => candidate !== null)) throw new ModelEnsemblePayloadError();
  } else {
    if ([...planFields, ...opportunityFields].some((candidate) => candidate === null)) {
      throw new ModelEnsemblePayloadError();
    }
    if (source === "opportunity_bound_exceeded") {
      if (
        opportunityCount === null || opportunityCount <= 100
        || [...evidenceIdentityFields, ...evidenceCounts].some((candidate) => candidate !== null)
      ) throw new ModelEnsemblePayloadError();
    } else if (source === "awaiting_evidence") {
      if (
        opportunityCount === null || opportunityCount > 100
        || evidenceIdentityFields.some((candidate) => candidate !== null)
        || evidenceCounts.some((candidate) => candidate !== 0)
      ) throw new ModelEnsemblePayloadError();
    } else if (
      opportunityCount === null || opportunityCount > 100
      || [...evidenceIdentityFields, ...evidenceCounts].some((candidate) => candidate === null)
      || authorityHeadCount !== objectiveResultCount! + nativeAcceptanceCount!
      || resolvedOpportunityCount! > authorityHeadCount!
      || metRequirementCount! > resolvedOpportunityCount!
      || authorityHeadCount! > opportunityCount
      || throughRevision! < authorityHeadCount!
    ) {
      throw new ModelEnsemblePayloadError();
    }
  }
  return value as ModelRequirementVerificationEvidenceBinding;
}

/**
 * Validate one content-free aggregate metric against its enclosing chunk bound.
 * Structural graph cells do not count as eligible metric observations, so the
 * receipt total may be smaller than the physical chunk count.
 * Kept public so the slim trajectory boundary can reuse the exact same trust
 * rules without accepting the much larger run graph.
 */
export function parseModelEnsembleMetricReceipt(
  value: unknown,
  chunkCount: number,
): EnsembleMetric {
  const metric = record(value);
  exact(metric, [
    "metric_key", "value_state", "numerator", "denominator", "numeric_value",
    "known_chunk_count", "abstained_chunk_count", "unsupported_chunk_count",
    "failed_chunk_count", "total_chunk_count", "explanation_code",
    "calibration_state", "product_metric_eligible",
  ]);
  const state = oneOf(metric.value_state, VALUE_STATES);
  const known = integer(metric.known_chunk_count, 0, chunkCount);
  const abstained = integer(metric.abstained_chunk_count, 0, chunkCount);
  const unsupported = integer(metric.unsupported_chunk_count, 0, chunkCount);
  const failed = integer(metric.failed_chunk_count, 0, chunkCount);
  const total = integer(metric.total_chunk_count, 1, chunkCount);
  if (known + abstained + unsupported + failed !== total) {
    throw new ModelEnsemblePayloadError();
  }
  label(metric.metric_key);
  label(metric.explanation_code);
  if (metric.calibration_state !== "not_assessed" || metric.product_metric_eligible !== false) {
    throw new ModelEnsemblePayloadError();
  }
  const numerator = metric.numerator === null ? null : integer(metric.numerator, 0, total);
  const denominator = metric.denominator === null ? null : integer(metric.denominator, 1, total);
  const numeric = optionalFinite(metric.numeric_value, 0, 1);
  if (state === "known") {
    if (denominator !== known || numerator === null || numeric === null || Math.abs(numeric - numerator / denominator) > 1e-12) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (numerator !== null || denominator !== null || numeric !== null) {
    throw new ModelEnsemblePayloadError();
  }
  return value as EnsembleMetric;
}

export function parseModelEnsembleTypedMetricReceipt(value: unknown): TypedMetric {
  const metric = record(value);
  exact(metric, [
    "metric_key", "metric_version", "value_state", "numerator", "denominator",
    "numeric_value", "observed_message_count", "eligible_message_count", "coverage",
    "explanation_code", "error_code", "projection_source", "metric_schema_version",
    "engine_version", "algorithm_id", "algorithm_version", "rubric_version",
    "calibration_state", "product_metric_eligible",
  ]);
  label(metric.metric_key);
  integer(metric.metric_version, 1, 1_000_000);
  const state = oneOf(metric.value_state, VALUE_STATES);
  const observed = integer(metric.observed_message_count, 0, 100);
  const eligible = integer(metric.eligible_message_count, 0, 10_000_000);
  const coverage = finite(metric.coverage, 0, 1);
  const expectedCoverage = eligible === 0 ? 0 : observed / eligible;
  if (observed > eligible || Math.abs(coverage - expectedCoverage) > 1e-12) {
    throw new ModelEnsemblePayloadError();
  }
  const numerator = metric.numerator === null
    ? null
    : integer(metric.numerator, 0, 1_000_000);
  const denominator = metric.denominator === null
    ? null
    : integer(metric.denominator, 1, 1_000_000);
  const numeric = optionalFinite(metric.numeric_value, 0, 1);
  const errorCode = metric.error_code === null ? null : label(metric.error_code);
  if (state === "known") {
    if (
      numerator === null || denominator === null || numerator > denominator
      || numeric === null || errorCode !== null
      || Math.abs(numeric - numerator / denominator) > 1e-12
    ) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (
    numerator !== null || denominator !== null || numeric !== null
    || ((state === "execution_error") !== (errorCode !== null))
  ) {
    throw new ModelEnsemblePayloadError();
  }
  label(metric.explanation_code);
  if (
    metric.projection_source !== "deterministic_typed_contract"
    || metric.calibration_state !== "not_assessed"
    || metric.product_metric_eligible !== false
  ) {
    throw new ModelEnsemblePayloadError();
  }
  integer(metric.metric_schema_version, 1, 1_000_000);
  label(metric.engine_version);
  label(metric.algorithm_id);
  label(metric.algorithm_version);
  label(metric.rubric_version);
  return value as TypedMetric;
}

export function parseModelPredictiveMetricSummary(value: unknown): PredictiveMetric {
  const metric = record(value);
  exact(metric, [
    "metric_key", "target", "state", "mean", "median", "q05", "q25", "q75", "q95",
    "applicability_probability", "pending_probability", "model_disagreement",
    "effective_observation_count", "model_set_version", "calibration_version",
    "contract_version", "contract_fingerprint", "product_metric_eligible",
  ]);
  label(metric.metric_key);
  oneOf(metric.target, ["metric_value", "outcome_forecast"] as const);
  const state = oneOf(metric.state, PREDICTIVE_STATES);
  const mean = optionalFinite(metric.mean, 0, 1);
  const median = optionalFinite(metric.median, 0, 1);
  const q05 = optionalFinite(metric.q05, 0, 1);
  const q25 = optionalFinite(metric.q25, 0, 1);
  const q75 = optionalFinite(metric.q75, 0, 1);
  const q95 = optionalFinite(metric.q95, 0, 1);
  const applicability = optionalFinite(metric.applicability_probability, 0, 1);
  const pending = optionalFinite(metric.pending_probability, 0, 1);
  optionalFinite(metric.model_disagreement, 0, 1);
  const observations = integer(metric.effective_observation_count, 0, 10_000_000);
  label(metric.model_set_version);
  label(metric.calibration_version);
  label(metric.contract_version);
  if (typeof metric.contract_fingerprint !== "string" || !HEX_64.test(metric.contract_fingerprint)) {
    throw new ModelEnsemblePayloadError();
  }
  if (metric.product_metric_eligible !== false) throw new ModelEnsemblePayloadError();
  const hasDistribution = ["experimental", "calibrated", "out_of_distribution"].includes(state);
  if (hasDistribution) {
    if (
      mean === null || median === null || q05 === null || q25 === null || q75 === null || q95 === null
      || applicability === null || pending === null || observations < 1
      || !(q05 <= q25 && q25 <= median && median <= q75 && q75 <= q95)
      || (state === "experimental" && metric.calibration_version !== "not-calibrated-v1")
    ) {
      throw new ModelEnsemblePayloadError();
    }
  } else if (
    mean !== null || median !== null || q05 !== null || q25 !== null || q75 !== null || q95 !== null
    || applicability !== null || pending !== null || metric.model_disagreement !== null
    || observations !== 0
  ) {
    throw new ModelEnsemblePayloadError();
  }
  return value as PredictiveMetric;
}

export function parseModelEnsembleRun(value: unknown): ModelEnsembleRun {
  const run = record(value);
  exact(run, [
    "run_id", "plan_version", "plan_fingerprint", "source_coverage_state",
    "chunk_count", "model_count", "chunks", "experts", "votes", "chunk_metrics",
    "metrics", "metric_projection_version", "metric_projection_completed_at",
    "typed_metrics", "metric_publication_v2", "metric_profile_binding",
    "requirement_plan_evidence_binding", "metric_evidence_readiness_v2",
    "requirement_action_evidence_binding",
    "requirement_verification_evidence_binding",
    "predictive_projection_version", "predictive_projected_at",
    "predictive_metrics", "predictive_model_stages", "completed_at", "local_only", "content_persisted",
    "calibration_state", "product_metric_eligible",
  ]);
  if (
    typeof run.run_id !== "string" || !HEX_64.test(run.run_id) ||
    run.plan_version !== "local-shadow-ensemble-v1" ||
    typeof run.plan_fingerprint !== "string" || !HEX_64.test(run.plan_fingerprint) ||
    !["complete_window", "incomplete_source"].includes(String(run.source_coverage_state)) ||
    run.model_count !== 10 || run.local_only !== true || run.content_persisted !== false ||
    run.calibration_state !== "not_assessed" || run.product_metric_eligible !== false
  ) {
    throw new ModelEnsemblePayloadError();
  }
  const chunkCount = integer(run.chunk_count, 1, 8);
  utcTimestamp(run.completed_at);

  if (!Array.isArray(run.chunks) || run.chunks.length !== chunkCount) {
    throw new ModelEnsemblePayloadError();
  }
  run.chunks.forEach((candidate, ordinal) => {
    const chunk = record(candidate);
    exact(chunk, ["ordinal", "source_message_count", "fragment_count", "character_count"]);
    if (integer(chunk.ordinal, 0, 7) !== ordinal) throw new ModelEnsemblePayloadError();
    integer(chunk.source_message_count, 1, 100);
    integer(chunk.fragment_count, 1, 128);
    integer(chunk.character_count, 1, 100_000);
  });

  if (!Array.isArray(run.experts) || run.experts.length !== 10) {
    throw new ModelEnsemblePayloadError();
  }
  const expertRoles = new Map<string, string>();
  const roleCounts = new Map<string, number>();
  run.experts.forEach((candidate, ordinal) => {
    const expert = record(candidate);
    exact(expert, [
      "ordinal", "model_key", "role", "repository_id", "revision", "license_spdx",
      "contributes_to_decision", "status", "error_code", "device",
      "inference_latency_ms", "peak_accelerator_memory_mb", "process_rss_mb",
      "unloaded_after_stage",
    ]);
    if (integer(expert.ordinal, 0, 9) !== ordinal || expert.unloaded_after_stage !== true) {
      throw new ModelEnsemblePayloadError();
    }
    const modelKey = label(expert.model_key);
    const role = oneOf(expert.role, EXPERT_ROLES);
    if (expertRoles.has(modelKey)) throw new ModelEnsemblePayloadError();
    expertRoles.set(modelKey, role);
    roleCounts.set(role, (roleCounts.get(role) ?? 0) + 1);
    if (typeof expert.repository_id !== "string" || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(expert.repository_id)) {
      throw new ModelEnsemblePayloadError();
    }
    if (typeof expert.revision !== "string" || !/^[0-9a-f]{40}$/.test(expert.revision)) {
      throw new ModelEnsemblePayloadError();
    }
    oneOf(expert.license_spdx, ["MIT", "Apache-2.0"] as const);
    if (typeof expert.contributes_to_decision !== "boolean") throw new ModelEnsemblePayloadError();
    const status = oneOf(expert.status, EXPERT_STATUSES);
    const errorCode = expert.error_code === null ? null : label(expert.error_code);
    const device = expert.device === null ? null : oneOf(expert.device, ["cpu", "cuda", "mps"] as const);
    optionalFinite(expert.inference_latency_ms);
    optionalFinite(expert.peak_accelerator_memory_mb);
    optionalFinite(expert.process_rss_mb);
    if ((status === "completed") !== (errorCode === null && device !== null)) {
      throw new ModelEnsemblePayloadError();
    }
  });
  if (
    roleCounts.get("retrieval") !== 4 || roleCounts.get("reranking") !== 2 ||
    roleCounts.get("scope_nli") !== 3 || roleCounts.get("structured_rubric") !== 1
  ) {
    throw new ModelEnsemblePayloadError();
  }

  if (!Array.isArray(run.metrics) || run.metrics.length < 1 || run.metrics.length > 20) {
    throw new ModelEnsemblePayloadError();
  }
  const metricKeys = new Set<string>();
  run.metrics.forEach((candidate) => {
    const metric = parseModelEnsembleMetricReceipt(candidate, chunkCount);
    const key = metric.metric_key;
    if (metricKeys.has(key)) throw new ModelEnsemblePayloadError();
    metricKeys.add(key);
  });
  const projectionVersion = run.metric_projection_version;
  const projectionCompletedAt = run.metric_projection_completed_at;
  if (!Array.isArray(run.typed_metrics) || run.typed_metrics.length > 20) {
    throw new ModelEnsemblePayloadError();
  }
  if (
    (projectionVersion === null) !== (projectionCompletedAt === null)
    || (projectionVersion === null) !== (run.typed_metrics.length === 0)
    || (projectionVersion !== null && projectionVersion !== "coaching-typed-projection-v1")
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (projectionCompletedAt !== null) utcTimestamp(projectionCompletedAt);
  const typedKeys = new Set<string>();
  run.typed_metrics.forEach((candidate) => {
    const metric = parseModelEnsembleTypedMetricReceipt(candidate);
    if (!metricKeys.has(metric.metric_key) || typedKeys.has(metric.metric_key)) {
      throw new ModelEnsemblePayloadError();
    }
    typedKeys.add(metric.metric_key);
  });
  if (run.typed_metrics.length > 0 && typedKeys.size !== metricKeys.size) {
    throw new ModelEnsemblePayloadError();
  }
  let publication: ReturnType<typeof parseMetricPublicationV2> | null = null;
  if (run.metric_publication_v2 !== null) {
    try {
      publication = parseMetricPublicationV2(run.metric_publication_v2);
    } catch (error) {
      // Definitions out of date is a distinct client-update condition, not a
      // malformed run: surfaces show the update alert instead of "reconnecting".
      if (error instanceof MetricDefinitionsOutOfDateError) throw error;
      throw new ModelEnsemblePayloadError();
    }
    const publishedKeys = new Set(publication.metrics.map((item) => item.state.metric_key));
    if (
      publishedKeys.size !== metricKeys.size
      || [...metricKeys].some((metricKey) => !publishedKeys.has(metricKey))
    ) {
      throw new ModelEnsemblePayloadError();
    }
  }
  const profileBinding = run.metric_profile_binding === null
    ? null
    : parseModelMetricProfileBinding(run.metric_profile_binding);
  const currentProfileProjection = publication !== null && [
    "metric-contract-v2-projection-5",
    "metric-contract-v2-projection-6",
    "metric-contract-v2-projection-7",
    "metric-contract-v2-projection-8",
  ].includes(publication.projection_version);
  if (
    (publication === null && profileBinding !== null)
    || (currentProfileProjection && profileBinding === null)
    || (publication !== null && !currentProfileProjection && profileBinding !== null)
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (profileBinding?.profile_source === "coaching_profile_v1_unconfigured") {
    const profileMetricStates = publication?.metrics.filter(
      (item) => item.state.statistics.denominator_basis === "declared_profile_slots",
    ) ?? [];
    if (
      profileMetricStates.length !== 3
      || profileMetricStates.some(({ state }) => (
        state.value_state !== "unknown"
        || state.numerator !== null
        || state.denominator !== null
        || state.numeric_value !== null
        || state.censoring_lower_bound !== null
        || state.censoring_upper_bound !== null
        || state.statistics.eligible_count !== 0
        || state.statistics.met_count !== 0
        || state.statistics.not_met_count !== 0
        || state.statistics.pending_count !== 0
        || state.statistics.unknown_count !== 0
      ))
    ) {
      throw new ModelEnsemblePayloadError();
    }
  }
  const requirementPlanBinding = run.requirement_plan_evidence_binding === null
    ? null
    : parseModelRequirementPlanEvidenceBinding(run.requirement_plan_evidence_binding);
  if (
    ([
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(
      publication?.projection_version ?? "",
    ))
      !== (requirementPlanBinding !== null)
  ) {
    throw new ModelEnsemblePayloadError();
  }
  const requirementActionBinding = run.requirement_action_evidence_binding === null
    ? null
    : parseModelRequirementActionEvidenceBinding(run.requirement_action_evidence_binding);
  if (
    (["metric-contract-v2-projection-7", "metric-contract-v2-projection-8"].includes(
      publication?.projection_version ?? "",
    ))
      !== (requirementActionBinding !== null)
  ) throw new ModelEnsemblePayloadError();
  if (
    requirementActionBinding?.evidence_source === "reviewed_requirement_action"
    && (
      requirementPlanBinding?.evidence_source !== "reviewed_requirement_plan"
      || requirementActionBinding.requirement_plan_confirmation_id
        !== requirementPlanBinding.confirmation_id
      || requirementActionBinding.requirement_plan_evidence_fingerprint
        !== requirementPlanBinding.evidence_fingerprint
    )
  ) throw new ModelEnsemblePayloadError();
  if (requirementActionBinding !== null && publication !== null) {
    const state = publication.metrics.find(
      (item) => item.state.metric_key === "logic.requirement_action_traceability",
    )?.state;
    const requirementPlanState = publication.metrics.find(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    )?.state;
    if (state === undefined || requirementPlanState === undefined) throw new ModelEnsemblePayloadError();
    const statistics = state.statistics;
    const unknownShape = state.value_state === "unknown"
      && state.numerator === null
      && state.denominator === null
      && state.numeric_value === null
      && state.censoring_lower_bound === null
      && state.censoring_upper_bound === null;
    const unresolvedShape = statistics.met_count === 0
      && statistics.not_met_count === 0
      && statistics.pending_count === 0
      && statistics.unknown_count === statistics.eligible_count;
    const reviewedRequirementPlan = isReviewedRequirementPlanState(requirementPlanState);
    if (
      reviewedRequirementPlan
        ? statistics.eligible_count !== requirementPlanState.statistics.eligible_count
        : statistics.eligible_count !== 0
    ) throw new ModelEnsemblePayloadError();
    if (requirementActionBinding.evidence_source === "unavailable") {
      if (
        !unknownShape
        || state.explanation_code !== "requirement_action_evidence_unavailable"
        || statistics.capability_available !== false
        || statistics.source_complete !== true
        || !unresolvedShape
      ) throw new ModelEnsemblePayloadError();
    } else if (requirementActionBinding.evidence_source === "awaiting_review") {
      if (
        !unknownShape
        || state.explanation_code !== "requirement_action_evidence_confirmation_required"
        || statistics.capability_available !== true
        || statistics.source_complete !== true
        || !unresolvedShape
      ) throw new ModelEnsemblePayloadError();
    } else if (requirementActionBinding.evidence_source === "candidate_manifest_overflow") {
      if (
        !unknownShape
        || state.explanation_code !== "requirement_action_evidence_overflow"
        || statistics.capability_available !== true
        || statistics.source_complete !== true
        || !unresolvedShape
      ) throw new ModelEnsemblePayloadError();
    } else if (requirementActionBinding.evidence_source === "candidate_source_incomplete") {
      if (
        !unknownShape
        || state.explanation_code !== "requirement_action_candidate_source_incomplete"
        || statistics.capability_available !== true
        || statistics.source_complete !== false
        || !unresolvedShape
      ) throw new ModelEnsemblePayloadError();
    } else if (requirementActionBinding.evidence_source === "binding_invalid") {
      if (
        !unknownShape
        || state.explanation_code !== "requirement_action_evidence_invalid"
        || statistics.capability_available !== true
        || statistics.source_complete !== false
        || !unresolvedShape
      ) throw new ModelEnsemblePayloadError();
    } else {
      const reviewed = reviewedRequirementPlan && isReviewedRequirementActionState(state);
      if (!reviewed) throw new ModelEnsemblePayloadError();
    }
  }
  const requirementVerificationBinding = run.requirement_verification_evidence_binding === null
    ? null
    : parseModelRequirementVerificationEvidenceBinding(
      run.requirement_verification_evidence_binding,
    );
  if (
    (publication?.projection_version === "metric-contract-v2-projection-8")
      !== (requirementVerificationBinding !== null)
  ) throw new ModelEnsemblePayloadError();
  if (
    requirementVerificationBinding !== null
    && requirementVerificationBinding.evidence_source !== "unavailable"
    && (
      requirementPlanBinding?.evidence_source !== "reviewed_requirement_plan"
      || requirementVerificationBinding.requirement_plan_confirmation_id
        !== requirementPlanBinding.confirmation_id
      || requirementVerificationBinding.requirement_plan_evidence_fingerprint
        !== requirementPlanBinding.evidence_fingerprint
    )
  ) throw new ModelEnsemblePayloadError();
  if (requirementVerificationBinding !== null && publication !== null) {
    const verified = publication.metrics.find(
      (item) => item.state.metric_key === "outcome.verified_requirement_coverage",
    )?.state;
    if (verified === undefined) throw new ModelEnsemblePayloadError();
    const statistics = verified.statistics;
    const typedVerification = run.typed_metrics.find(
      (item) => item.metric_key === "outcome.verified_requirement_coverage",
    );
    const resolvedStatistics = statistics.met_count + statistics.not_met_count;
    const expectedCoverage = statistics.eligible_count === 0
      ? 0
      : resolvedStatistics / statistics.eligible_count;
    if (
      typedVerification === undefined
      || typedVerification.value_state !== verified.value_state
      || typedVerification.numerator !== verified.numerator
      || typedVerification.denominator !== verified.denominator
      || typedVerification.numeric_value !== verified.numeric_value
      || typedVerification.observed_message_count !== resolvedStatistics
      || typedVerification.eligible_message_count !== statistics.eligible_count
      || Math.abs(typedVerification.coverage - expectedCoverage) > 1e-9
      || typedVerification.explanation_code !== verified.explanation_code
      || typedVerification.error_code !== null
      || typedVerification.engine_version
        !== "reviewed-requirement-verification-objective-projection-v1"
      || typedVerification.algorithm_id
        !== "reviewed-requirement-verification-authority"
      || typedVerification.algorithm_version !== "4"
      || typedVerification.rubric_version !== "objective-evidence-no-rubric-v4"
    ) throw new ModelEnsemblePayloadError();
    const source = requirementVerificationBinding.evidence_source;
    const opportunityCount = requirementVerificationBinding.opportunity_count;
    const resolvedCount = requirementVerificationBinding.resolved_opportunity_count;
    const metCount = requirementVerificationBinding.met_requirement_count;
    const nonnumericValueShape = verified.numerator === null
      && verified.denominator === null
      && verified.numeric_value === null;
    const nullBounds = verified.censoring_lower_bound === null
      && verified.censoring_upper_bound === null;
    const exactBounds = (lower: number, upper: number) => (
      typeof verified.censoring_lower_bound === "number"
      && typeof verified.censoring_upper_bound === "number"
      && Math.abs(verified.censoring_lower_bound - lower) <= 1e-9
      && Math.abs(verified.censoring_upper_bound - upper) <= 1e-9
    );
    const zeroStatistics = statistics.eligible_count === 0
      && statistics.met_count === 0
      && statistics.not_met_count === 0
      && statistics.pending_count === 0
      && statistics.unknown_count === 0
      && statistics.distinct_owner_count === 0;
    const exactFrozenOwnership = statistics.superseded_excluded_count === 0
      && statistics.distinct_owner_count === statistics.eligible_count;
    const unavailableWithoutReviewedAuthority = source === "unavailable"
      && verified.value_state === "unknown"
      && (
        (
          verified.explanation_code === "reviewed_requirement_authority_unavailable"
          && statistics.capability_available === false
          && statistics.source_complete === true
        )
        || (
          verified.explanation_code === "reviewed_requirement_authority_invalid"
          && statistics.capability_available === true
          && statistics.source_complete === false
        )
      )
      && nonnumericValueShape
      && nullBounds
      && zeroStatistics;
    const unavailableWithReviewedAuthority = source === "unavailable"
      && verified.value_state === "unknown"
      && verified.explanation_code === "requirement_verification_evidence_unavailable"
      && statistics.capability_available === true
      && statistics.source_complete === true
      && statistics.eligible_count > 0
      && statistics.met_count === 0
      && statistics.not_met_count === 0
      && statistics.pending_count === 0
      && statistics.unknown_count === statistics.eligible_count
      && statistics.distinct_owner_count === statistics.eligible_count
      && nonnumericValueShape
      && exactBounds(0, 1);
    const bounded = source === "opportunity_bound_exceeded"
      && verified.value_state === "unknown"
      && verified.explanation_code === "typed_objective_opportunity_count_exceeds_receipt_bound"
      && statistics.capability_available === true
      && statistics.source_complete === true
      && nonnumericValueShape
      && nullBounds
      && zeroStatistics;
    const empty = opportunityCount === 0
      && verified.value_state === "not_applicable"
      && verified.explanation_code === "reviewed_requirement_set_empty"
      && statistics.capability_available === true
      && statistics.source_complete === true
      && nonnumericValueShape
      && nullBounds
      && zeroStatistics;
    const awaiting = source === "awaiting_evidence"
      && opportunityCount !== null
      && opportunityCount > 0
      && verified.value_state === "unknown"
      && verified.explanation_code === "requirement_verification_evidence_unavailable"
      && statistics.capability_available === true
      && statistics.source_complete === true
      && statistics.eligible_count === opportunityCount
      && statistics.met_count === 0
      && statistics.not_met_count === 0
      && statistics.pending_count === 0
      && statistics.unknown_count === opportunityCount
      && statistics.distinct_owner_count === opportunityCount
      && nonnumericValueShape
      && exactBounds(0, 1);
    let persisted = false;
    if (
      source === "persisted_evidence"
      && opportunityCount !== null
      && resolvedCount !== null
      && metCount !== null
      && opportunityCount > 0
      && statistics.capability_available === true
      && statistics.source_complete === true
      && statistics.eligible_count === opportunityCount
      && statistics.met_count === metCount
      && statistics.not_met_count === resolvedCount - metCount
      && statistics.pending_count === 0
      && statistics.unknown_count === opportunityCount - resolvedCount
      && statistics.distinct_owner_count === opportunityCount
    ) {
      if (resolvedCount < opportunityCount) {
        const expectedLower = metCount / opportunityCount;
        const expectedUpper = (metCount + opportunityCount - resolvedCount) / opportunityCount;
        persisted = verified.value_state === "unknown"
          && verified.explanation_code === "app_issued_requirement_verification_pending"
          && nonnumericValueShape
          && exactBounds(expectedLower, expectedUpper);
      } else {
        const expected = metCount / opportunityCount;
        persisted = verified.value_state === "known"
          && verified.explanation_code === "app_issued_verified_requirement_coverage"
          && verified.numerator === metCount
          && verified.denominator === opportunityCount
          && typeof verified.numeric_value === "number"
          && typeof verified.censoring_lower_bound === "number"
          && typeof verified.censoring_upper_bound === "number"
          && Math.abs(verified.numeric_value - expected) <= 1e-9
          && Math.abs(verified.censoring_lower_bound - expected) <= 1e-9
          && Math.abs(verified.censoring_upper_bound - expected) <= 1e-9;
      }
    }
    if (
      !exactFrozenOwnership
      || !(unavailableWithoutReviewedAuthority || unavailableWithReviewedAuthority
        || bounded || awaiting || persisted
        || (empty && (source === "awaiting_evidence" || source === "persisted_evidence")))
    ) throw new ModelEnsemblePayloadError();
    if (
      source !== "unavailable"
      && opportunityCount !== null
      && requirementPlanBinding?.evidence_source === "reviewed_requirement_plan"
    ) {
      const decomposition = publication.metrics.find(
        (item) => item.state.metric_key === "logic.decomposition_coverage",
      )?.state;
      if (decomposition?.statistics.eligible_count !== opportunityCount) {
        throw new ModelEnsemblePayloadError();
      }
    }
    if (unavailableWithReviewedAuthority) {
      const decomposition = publication.metrics.find(
        (item) => item.state.metric_key === "logic.decomposition_coverage",
      )?.state;
      if (
        requirementPlanBinding?.evidence_source !== "reviewed_requirement_plan"
        || decomposition?.statistics.eligible_count !== statistics.eligible_count
      ) throw new ModelEnsemblePayloadError();
    }
  }
  if (requirementPlanBinding !== null && publication !== null) {
    const decomposition = publication.metrics.find(
      (item) => item.state.metric_key === "logic.decomposition_coverage",
    )?.state;
    if (decomposition === undefined) throw new ModelEnsemblePayloadError();
    const statistics = decomposition.statistics;
    const empty = statistics.eligible_count === 0
      && statistics.met_count === 0
      && statistics.not_met_count === 0
      && statistics.pending_count === 0
      && statistics.unknown_count === 0;
    if (requirementPlanBinding.evidence_source === "unavailable") {
      if (
        decomposition.value_state !== "unknown"
        || decomposition.explanation_code !== "requirement_plan_evidence_unavailable"
        || decomposition.numerator !== null
        || decomposition.denominator !== null
        || decomposition.numeric_value !== null
        || decomposition.censoring_lower_bound !== null
        || decomposition.censoring_upper_bound !== null
        || statistics.capability_available !== false
        || statistics.source_complete !== true
        || !empty
      ) throw new ModelEnsemblePayloadError();
    } else if (requirementPlanBinding.evidence_source === "awaiting_review") {
      if (
        decomposition.value_state !== "unknown"
        || decomposition.explanation_code !== "requirement_plan_evidence_confirmation_required"
        || decomposition.numerator !== null
        || decomposition.denominator !== null
        || decomposition.numeric_value !== null
        || decomposition.censoring_lower_bound !== null
        || decomposition.censoring_upper_bound !== null
        || statistics.capability_available !== true
        || statistics.source_complete !== true
        || !empty
      ) throw new ModelEnsemblePayloadError();
    } else {
      const invalid = decomposition.value_state === "unknown"
        && decomposition.explanation_code === "requirement_plan_evidence_invalid"
        && statistics.capability_available === true
        && statistics.source_complete === false
        && empty;
      const reviewed = isReviewedRequirementPlanState(decomposition);
      if (!invalid && !reviewed) throw new ModelEnsemblePayloadError();
    }
  }
  if (
    run.metric_evidence_readiness_v2 !== null
    && (
      typeof run.metric_evidence_readiness_v2 !== "object"
      || Array.isArray(run.metric_evidence_readiness_v2)
    )
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (run.metric_publication_v2 === null && run.metric_evidence_readiness_v2 !== null) {
    throw new ModelEnsemblePayloadError();
  }

  const predictiveVersion = run.predictive_projection_version;
  const predictiveProjectedAt = run.predictive_projected_at;
  if (!Array.isArray(run.predictive_metrics) || run.predictive_metrics.length > 20) {
    throw new ModelEnsemblePayloadError();
  }
  if (!Array.isArray(run.predictive_model_stages) || run.predictive_model_stages.length > 8) {
    throw new ModelEnsemblePayloadError();
  }
  if (
    (predictiveVersion === null) !== (predictiveProjectedAt === null)
    || (predictiveVersion === null) !== (run.predictive_metrics.length === 0)
    || (predictiveVersion === null) !== (run.predictive_model_stages.length === 0)
    || (predictiveVersion !== null && predictiveVersion !== "local-probabilistic-radar-v1")
  ) {
    throw new ModelEnsemblePayloadError();
  }
  if (predictiveProjectedAt !== null) utcTimestamp(predictiveProjectedAt);
  const predictiveKeys = new Set<string>();
  run.predictive_metrics.forEach((candidate) => {
    const metric = parseModelPredictiveMetricSummary(candidate);
    if (!metricKeys.has(metric.metric_key) || predictiveKeys.has(metric.metric_key)) {
      throw new ModelEnsemblePayloadError();
    }
    predictiveKeys.add(metric.metric_key);
  });
  if (run.predictive_metrics.length > 0 && predictiveKeys.size !== metricKeys.size) {
    throw new ModelEnsemblePayloadError();
  }
  const predictiveModels = new Set<string>();
  run.predictive_model_stages.forEach((candidate) => {
    const stage = record(candidate);
    exact(stage, [
      "model_key", "repository_id", "revision", "status", "error_code", "device",
      "quantization", "inference_latency_ms", "peak_accelerator_memory_mb", "process_rss_mb",
      "unloaded_after_stage",
    ]);
    const modelKey = label(stage.model_key);
    if (predictiveModels.has(modelKey) || stage.unloaded_after_stage !== true) {
      throw new ModelEnsemblePayloadError();
    }
    predictiveModels.add(modelKey);
    if (typeof stage.repository_id !== "string" || !/^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/.test(stage.repository_id)) {
      throw new ModelEnsemblePayloadError();
    }
    if (typeof stage.revision !== "string" || !/^[0-9a-f]{40}$/.test(stage.revision)) {
      throw new ModelEnsemblePayloadError();
    }
    const status = oneOf(stage.status, EXPERT_STATUSES);
    const errorCode = stage.error_code === null ? null : label(stage.error_code);
    const device = stage.device === null ? null : oneOf(stage.device, ["cpu", "cuda", "mps"] as const);
    oneOf(stage.quantization, ["none", "bitsandbytes_nf4"] as const);
    optionalFinite(stage.inference_latency_ms);
    optionalFinite(stage.peak_accelerator_memory_mb, 0, 6_144);
    optionalFinite(stage.process_rss_mb, 0, 8_192);
    if ((status === "completed") !== (errorCode === null && device !== null)) {
      throw new ModelEnsemblePayloadError();
    }
  });

  const expectedPairs = new Set<string>();
  for (let chunk = 0; chunk < chunkCount; chunk += 1) {
    for (const metric of metricKeys) expectedPairs.add(`${chunk}\u0000${metric}`);
  }
  if (!Array.isArray(run.chunk_metrics) || run.chunk_metrics.length !== expectedPairs.size) {
    throw new ModelEnsemblePayloadError();
  }
  const chunkPairs = new Set<string>();
  run.chunk_metrics.forEach((candidate) => {
    const metric = record(candidate);
    exact(metric, [
      "chunk_ordinal", "metric_key", "value_state", "numerator", "denominator",
      "rubric_vote", "contributing_nli_votes", "diagnostic_nli_votes", "reason_code",
    ]);
    const pair = `${integer(metric.chunk_ordinal, 0, chunkCount - 1)}\u0000${label(metric.metric_key)}`;
    if (!expectedPairs.has(pair) || chunkPairs.has(pair)) throw new ModelEnsemblePayloadError();
    chunkPairs.add(pair);
    const state = oneOf(metric.value_state, VALUE_STATES);
    const numerator = metric.numerator === null ? null : integer(metric.numerator, 0, 1);
    const denominator = metric.denominator === null ? null : integer(metric.denominator, 1, 1);
    oneOf(metric.rubric_vote, VOTE_STATES);
    integer(metric.contributing_nli_votes, 0, 2);
    integer(metric.diagnostic_nli_votes, 0, 1);
    label(metric.reason_code);
    if ((state === "known") !== (numerator !== null && denominator === 1)) {
      throw new ModelEnsemblePayloadError();
    }
  });

  if (!Array.isArray(run.votes) || run.votes.length !== expectedPairs.size * 4) {
    throw new ModelEnsemblePayloadError();
  }
  const votesByPair = new Map<string, Set<string>>();
  const voteRoleCounts = new Map<string, { nli: number; rubric: number }>();
  run.votes.forEach((candidate) => {
    const vote = record(candidate);
    exact(vote, [
      "chunk_ordinal", "metric_key", "model_key", "role", "state", "raw_score",
      "evidence_fragment_count", "reason_code",
    ]);
    const pair = `${integer(vote.chunk_ordinal, 0, chunkCount - 1)}\u0000${label(vote.metric_key)}`;
    const modelKey = label(vote.model_key);
    const role = oneOf(vote.role, ["scope_nli", "structured_rubric"] as const);
    if (!expectedPairs.has(pair) || expertRoles.get(modelKey) !== role) throw new ModelEnsemblePayloadError();
    const identities = votesByPair.get(pair) ?? new Set<string>();
    if (identities.has(modelKey)) throw new ModelEnsemblePayloadError();
    identities.add(modelKey);
    votesByPair.set(pair, identities);
    const counts = voteRoleCounts.get(pair) ?? { nli: 0, rubric: 0 };
    if (role === "scope_nli") {
      counts.nli += 1;
    } else {
      counts.rubric += 1;
    }
    voteRoleCounts.set(pair, counts);
    const state = oneOf(vote.state, VOTE_STATES);
    const raw = optionalFinite(vote.raw_score, 0, 1);
    if ((state === "present" || state === "absent") !== (raw !== null)) throw new ModelEnsemblePayloadError();
    integer(vote.evidence_fragment_count, 0, 8);
    label(vote.reason_code);
  });
  for (const pair of expectedPairs) {
    const counts = voteRoleCounts.get(pair);
    if (votesByPair.get(pair)?.size !== 4 || counts?.nli !== 3 || counts.rubric !== 1) {
      throw new ModelEnsemblePayloadError();
    }
  }
  return value as ModelEnsembleRun;
}

export function parseModelEnsembleOutcome(value: unknown): ModelEnsembleOutcome {
  const outcome = record(value);
  exact(outcome, ["run", "applied"]);
  if (typeof outcome.applied !== "boolean") throw new ModelEnsemblePayloadError();
  parseModelEnsembleRun(outcome.run);
  return value as ModelEnsembleOutcome;
}
