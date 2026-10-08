import type {
  RequirementPlanEvidenceContract,
  RequirementPlanEvidencePreview,
  RequirementPlanImport,
  RequirementPlanProposal,
  RequirementPlanProposalOutcome,
  RequirementPlanProposalPage,
  RequirementPlanProposalPageSnapshot,
  RequirementPlanProposalReview,
} from "./contracts";
import {
  METRIC_CONTRACT_V2_REGISTRY_VERSION,
  METRIC_CONTRACT_V2_SET_FINGERPRINT,
  METRIC_V2_CONTRACT_IDENTITIES,
} from "./metricPublicationV2Contract";

export class RequirementPlanEvidencePayloadError extends Error {
  constructor() {
    super("Requirement-plan evidence response was invalid");
    this.name = "RequirementPlanEvidencePayloadError";
  }
}

export const REQUIREMENT_PLAN_MEDIA_TYPE =
  "application/vnd.prompt-enhancer.requirement-plan-evidence+json";
export const REQUIREMENT_PLAN_IMPORT_CONFIRMATION =
  "import_requirement_plan_evidence_as_unconfirmed_proposal" as const;
export const REQUIREMENT_PLAN_DECISION_CONFIRMATION =
  "apply_local_user_requirement_plan_evidence_decision" as const;
export const MAX_REQUIREMENT_PLAN_FILE_BYTES = 64 * 1024;

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const PROJECTIONS = [
  "metric-contract-v2-projection-5",
  "metric-contract-v2-projection-6",
  "metric-contract-v2-projection-7",
  "metric-contract-v2-projection-8",
] as const;
const DISPOSITIONS = ["linked", "not_linked", "pending"] as const;
const USER_CLASSIFICATIONS = [
  "active_requirement", "excluded_from_active_requirement_denominator",
] as const;
const EXCLUSION_REASONS = [
  "not_requirement", "superseded", "withdrawn", "duplicate", "out_of_scope",
  "already_satisfied_or_closed",
] as const;
const TEXT_ROLES = ["user", "agent"] as const;
const TEXT_KINDS = [
  "request", "response", "plan", "action", "verification", "decision", "feedback", "summary",
] as const;
export const REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC = {
  algorithm: "message-clause-coordinates-en-pl-v1",
  split_regex: "(?:\\r?\\n)+|(?<=[.!?;])\\s+",
  split_regex_flags: "unicode",
  implementation_semantics: "python-3.12-re-unicode",
  trim_each_part: true,
  whitespace_regex: "\\s+",
  nul_replacement: "ascii_space",
  whitespace_replacement: "ascii_space",
  operation_order: [
    "replace_nul", "split", "normalize_whitespace", "trim", "omit_empty", "overflow_check",
  ],
  omit_empty_parts: true,
  clause_indexes_are_zero_based: true,
  max_clauses_per_message: 128,
  overflow_policy: "fail_closed_above_128_normalized_clauses",
} as const;
export const REQUIREMENT_PLAN_REVIEW_RUBRIC = {
  version: "active-requirement-plan-review-rubric-v1",
  active_requirement_rule: "current_in_scope_user_owned_work_at_the_sealed_window",
  not_requirement_rule: "clause_does_not_express_work_to_be_performed",
  superseded_rule: "later_user_clause_explicitly_replaces_this_work",
  withdrawn_rule: "later_user_clause_explicitly_cancels_this_work",
  duplicate_rule: "same_active_work_is_owned_by_another_reviewed_clause",
  out_of_scope_rule: "person_explicitly_excludes_this_work_from_the_current_scope",
  already_satisfied_or_closed_rule:
    "work_was_already_satisfied_or_explicitly_closed_before_this_snapshot",
  uncertain_policy: "reject_or_leave_proposal_unconfirmed",
  exclusion_basis_policy:
    "superseded_and_withdrawn_point_to_a_later_user_clause_duplicate_points_to_its_active_owner",
  linked_rule: "one_or_more_reviewed_concrete_plan_clauses_address_the_active_requirement",
  not_linked_rule:
    "no_reviewed_plan_clause_addresses_the_requirement_and_the_person_confirms_the_planning_horizon_closed",
  pending_rule:
    "no_reviewed_plan_clause_yet_addresses_the_requirement_and_the_planning_horizon_is_not_confirmed_closed",
} as const;
export const REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES = [
  "identifiers_match_current_contract",
  "producer_codes_match_safe_version_pattern",
  "expires_at_is_utc_after_validation_and_within_86400_seconds",
  "requirement_coordinates_are_sorted_unique",
  "plan_coordinates_are_sorted_unique",
  "plan_indexes_are_sorted_unique_non_negative",
  "linked_requires_nonempty_plan_indexes",
  "nonlinked_and_pending_require_empty_plan_indexes",
  "plan_indexes_reference_existing_plan_items",
  "total_plan_indexes_lte_4000",
  "requirement_coordinates_reference_user_request_or_feedback_clauses",
  "excluded_user_clause_coordinates_are_sorted_unique",
  "excluded_user_clause_reasons_use_closed_rubric",
  "exclusion_basis_coordinates_follow_reason_rules",
  "user_clauses_exactly_classified_as_active_or_excluded",
  "active_and_excluded_user_clause_coordinates_are_disjoint",
  "source_messages_fail_closed_above_128_normalized_clauses",
  "plan_coordinates_reference_agent_plan_clauses",
  "linked_plan_sequence_gte_requirement_sequence",
] as const;
export const REQUIREMENT_PLAN_FILE_SCHEMA_SHA256 =
  "a00004d5e8d29e32e34740216c5facd7271a1fa5e468ee27df4365ced4e6afff";
const PSEUDONYM_SCHEMA_PATTERN = "^[a-f0-9]{64}$";
const SAFE_CODE_SCHEMA_PATTERN = "^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$";

function coordinateFileSchema(title: string) {
  return {
    additionalProperties: false,
    properties: {
      clause_index: {
        exclusiveMaximum: 128, minimum: 0, title: "Clause Index", type: "integer",
      },
      message_sequence: {
        maximum: 1_000_000_000, minimum: 0, title: "Message Sequence", type: "integer",
      },
    },
    required: ["message_sequence", "clause_index"],
    title,
    type: "object",
  };
}

/** Exact JSON Schema supplied to local coding agents for the r5-r8 content-free file. */
export const REQUIREMENT_PLAN_FILE_JSON_SCHEMA = {
  $defs: {
    ExcludedRequirementClause: {
      additionalProperties: false,
      properties: {
        basis_coordinate: {
          anyOf: [
            { $ref: "#/$defs/RequirementCoordinate" },
            { type: "null" },
          ],
          default: null,
        },
        coordinate: { $ref: "#/$defs/RequirementCoordinate" },
        reason: { $ref: "#/$defs/RequirementPlanExclusionReason" },
      },
      required: ["coordinate", "reason"],
      title: "ExcludedRequirementClause",
      type: "object",
    },
    PlanCoordinate: coordinateFileSchema("PlanCoordinate"),
    RequirementCoordinate: coordinateFileSchema("RequirementCoordinate"),
    RequirementDisposition: {
      enum: [...DISPOSITIONS], title: "RequirementDisposition", type: "string",
    },
    RequirementPlanExclusionReason: {
      enum: [...EXCLUSION_REASONS], title: "RequirementPlanExclusionReason", type: "string",
    },
    RequirementEvidenceEntry: {
      additionalProperties: false,
      properties: {
        coordinate: { $ref: "#/$defs/RequirementCoordinate" },
        disposition: { $ref: "#/$defs/RequirementDisposition" },
        plan_indexes: {
          default: [],
          items: { minimum: 0, type: "integer" },
          maxItems: 1_000,
          title: "Plan Indexes",
          type: "array",
          uniqueItems: true,
        },
      },
      required: ["coordinate", "disposition"],
      title: "RequirementEvidenceEntry",
      type: "object",
    },
    RequirementPlanProducer: {
      additionalProperties: false,
      description: "Ephemeral, explicitly untrusted producer claim from the submitted file.",
      properties: {
        authority: { const: "untrusted_provenance_claim", title: "Authority", type: "string" },
        kind: { const: "local_coding_agent", title: "Kind", type: "string" },
        model_id: { pattern: SAFE_CODE_SCHEMA_PATTERN, title: "Model Id", type: "string" },
        producer_id: { pattern: SAFE_CODE_SCHEMA_PATTERN, title: "Producer Id", type: "string" },
        producer_version: {
          pattern: SAFE_CODE_SCHEMA_PATTERN, title: "Producer Version", type: "string",
        },
      },
      required: ["kind", "producer_id", "producer_version", "model_id", "authority"],
      title: "RequirementPlanProducer",
      type: "object",
    },
  },
  additionalProperties: false,
  properties: {
    clause_algorithm: {
      const: "message-clause-coordinates-en-pl-v1", title: "Clause Algorithm", type: "string",
    },
    complete_user_clause_classification: {
      const: true, title: "Complete User Clause Classification", type: "boolean",
    },
    contains_authoritative_model_judgment_claims: {
      const: false, title: "Contains Authoritative Model Judgment Claims", type: "boolean",
    },
    contains_objective_receipt_claims: {
      const: false, title: "Contains Objective Receipt Claims", type: "boolean",
    },
    contains_prose: { const: false, title: "Contains Prose", type: "boolean" },
    contains_scores: { const: false, title: "Contains Scores", type: "boolean" },
    contains_untrusted_structured_proposals: {
      const: true, title: "Contains Untrusted Structured Proposals", type: "boolean",
    },
    contract_set_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Contract Set Fingerprint", type: "string",
    },
    expected_predecessor_confirmation_id: {
      anyOf: [
        { pattern: PSEUDONYM_SCHEMA_PATTERN, type: "string" },
        { type: "null" },
      ],
      default: null,
      title: "Expected Predecessor Confirmation Id",
    },
    expected_source_run_id: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Expected Source Run Id", type: "string",
    },
    expires_at: { format: "date-time", title: "Expires At", type: "string" },
    excluded_user_clauses: {
      items: { $ref: "#/$defs/ExcludedRequirementClause" },
      maxItems: 1_000,
      title: "Excluded User Clauses",
      type: "array",
      uniqueItems: true,
    },
    metric_contract_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Metric Contract Fingerprint", type: "string",
    },
    metric_key: {
      const: "logic.decomposition_coverage", title: "Metric Key", type: "string",
    },
    nonce: { pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Nonce", type: "string" },
    plan_items: {
      items: { $ref: "#/$defs/PlanCoordinate" },
      maxItems: 1_000,
      title: "Plan Items",
      type: "array",
    },
    producer: { $ref: "#/$defs/RequirementPlanProducer" },
    registry_version: {
      const: "all-20-factor-contracts-v2", title: "Registry Version", type: "string",
    },
    requirements: {
      items: { $ref: "#/$defs/RequirementEvidenceEntry" },
      maxItems: 1_000,
      title: "Requirements",
      type: "array",
    },
    review_rubric_version: {
      const: "active-requirement-plan-review-rubric-v1",
      title: "Review Rubric Version",
      type: "string",
    },
    schema_version: {
      const: "requirement-plan-evidence-file-v1", title: "Schema Version", type: "string",
    },
    session_id: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Session Id", type: "string",
    },
    source_projection_version: {
      enum: [...PROJECTIONS], title: "Source Projection Version", type: "string",
    },
    source_window_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Source Window Fingerprint", type: "string",
    },
  },
  required: [
    "schema_version", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "registry_version", "contract_set_fingerprint", "metric_key",
    "metric_contract_fingerprint", "source_projection_version", "clause_algorithm",
    "review_rubric_version", "nonce", "expires_at", "producer", "contains_prose",
    "contains_scores", "contains_authoritative_model_judgment_claims",
    "contains_untrusted_structured_proposals", "contains_objective_receipt_claims",
    "complete_user_clause_classification", "requirements", "excluded_user_clauses", "plan_items",
  ],
  title: "RequirementPlanEvidenceFileV1",
  type: "object",
  "x-prompt-enhancer-constraint-contract": "requirement-plan-file-constraints-v1",
  "x-prompt-enhancer-constraints": REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES.map((code) => ({
    code,
    required: true,
  })),
} as const;

type Row = Record<string, unknown>;

function record(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new RequirementPlanEvidencePayloadError();
  }
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new RequirementPlanEvidencePayloadError();
  }
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    const item = value as Row;
    return `{${Object.keys(item).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(item[key])}`
    )).join(",")}}`;
  }
  throw new RequirementPlanEvidencePayloadError();
}

function safeId(value: unknown): value is string {
  return typeof value === "string" && HEX_64.test(value);
}

function optionalSafeId(value: unknown): value is string | null {
  return value === null || safeId(value);
}

function safeCode(value: unknown): value is string {
  return typeof value === "string" && SAFE_CODE.test(value);
}

function integer(value: unknown, maximum: number): value is number {
  return Number.isInteger(value) && (value as number) >= 0 && (value as number) <= maximum;
}

function utcTimestamp(value: unknown): value is string {
  if (
    typeof value !== "string"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)
  ) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(value);
  const parsed = new Date(value);
  return match !== null
    && !Number.isNaN(parsed.getTime())
    && parsed.getUTCFullYear() === Number(match[1])
    && parsed.getUTCMonth() + 1 === Number(match[2])
    && parsed.getUTCDate() === Number(match[3])
    && parsed.getUTCHours() === Number(match[4])
    && parsed.getUTCMinutes() === Number(match[5])
    && parsed.getUTCSeconds() === Number(match[6]);
}

function normalizedClauseText(value: unknown): value is string {
  return typeof value === "string"
    && value.length > 0
    && value === value.trim()
    && !value.includes("\u0000")
    && !value.includes("  ")
    && !/[^\S ]/u.test(value);
}

function coordinate(value: unknown): { message_sequence: number; clause_index: number } {
  const item = record(value);
  exact(item, ["message_sequence", "clause_index"]);
  if (!integer(item.message_sequence, 1_000_000_000) || !integer(item.clause_index, 127)) {
    throw new RequirementPlanEvidencePayloadError();
  }
  return item as { message_sequence: number; clause_index: number };
}

function coordinateKey(value: { message_sequence: number; clause_index: number }): string {
  return `${value.message_sequence.toString().padStart(10, "0")}:${value.clause_index.toString().padStart(3, "0")}`;
}

function producer(value: unknown) {
  const item = record(value);
  exact(item, ["kind", "producer_id", "producer_version", "model_id", "authority"]);
  if (
    item.kind !== "local_coding_agent"
    || item.authority !== "untrusted_provenance_claim"
    || !safeCode(item.producer_id)
    || !safeCode(item.producer_version)
    || !safeCode(item.model_id)
  ) throw new RequirementPlanEvidencePayloadError();
  return item;
}

function producerReceipt(value: unknown) {
  const item = record(value);
  exact(item, ["kind", "claim_fingerprint", "authority", "raw_claim_persisted"]);
  if (
    item.kind !== "local_coding_agent"
    || !safeId(item.claim_fingerprint)
    || item.authority !== "untrusted_provenance_claim_commitment"
    || item.raw_claim_persisted !== false
  ) throw new RequirementPlanEvidencePayloadError();
  return item;
}

function excludedClause(value: unknown) {
  const item = record(value);
  exact(item, ["coordinate", "reason", "basis_coordinate"]);
  const point = coordinate(item.coordinate);
  const basis = item.basis_coordinate === null ? null : coordinate(item.basis_coordinate);
  const requiresBasis = item.reason === "superseded"
    || item.reason === "withdrawn"
    || item.reason === "duplicate";
  if (
    !EXCLUSION_REASONS.includes(item.reason as typeof EXCLUSION_REASONS[number])
    || requiresBasis !== (basis !== null)
    || (basis !== null && coordinateKey(basis) === coordinateKey(point))
  ) throw new RequirementPlanEvidencePayloadError();
  return { coordinate: point, reason: item.reason, basis_coordinate: basis };
}

function clauseAlgorithmSpec(value: unknown) {
  const item = record(value);
  exact(item, Object.keys(REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC));
  if (canonicalJson(item) !== canonicalJson(REQUIREMENT_PLAN_CLAUSE_ALGORITHM_SPEC)) {
    throw new RequirementPlanEvidencePayloadError();
  }
  return item;
}

function reviewRubric(value: unknown) {
  const item = record(value);
  exact(item, Object.keys(REQUIREMENT_PLAN_REVIEW_RUBRIC));
  if (canonicalJson(item) !== canonicalJson(REQUIREMENT_PLAN_REVIEW_RUBRIC)) {
    throw new RequirementPlanEvidencePayloadError();
  }
  return item;
}

function sourceManifest(
  value: unknown,
  expected: { sessionId: string; sourceRunId: string; sourceWindowFingerprint: string },
) {
  const manifest = record(value);
  exact(manifest, [
    "session_id", "source_run_id", "source_window_fingerprint", "schema_version",
    "clause_algorithm", "clause_algorithm_spec", "review_rubric_version",
    "review_rubric", "messages", "message_count",
    "candidate_clause_count", "manifest_fingerprint", "review_context_expires_at",
    "contains_text", "local_only", "content_persisted",
  ]);
  if (
    manifest.session_id !== expected.sessionId
    || manifest.source_run_id !== expected.sourceRunId
    || manifest.source_window_fingerprint !== expected.sourceWindowFingerprint
    || manifest.schema_version !== "requirement-plan-source-manifest-v1"
    || manifest.clause_algorithm !== "message-clause-coordinates-en-pl-v1"
    || manifest.review_rubric_version !== "active-requirement-plan-review-rubric-v1"
    || !Array.isArray(manifest.messages)
    || manifest.messages.length < 1
    || manifest.messages.length > 100
    || manifest.message_count !== manifest.messages.length
    || !integer(manifest.candidate_clause_count, 12_800)
    || !safeId(manifest.manifest_fingerprint)
    || !utcTimestamp(manifest.review_context_expires_at)
    || manifest.contains_text !== false
    || manifest.local_only !== true
    || manifest.content_persisted !== false
  ) throw new RequirementPlanEvidencePayloadError();
  clauseAlgorithmSpec(manifest.clause_algorithm_spec);
  reviewRubric(manifest.review_rubric);
  let candidateCount = 0;
  let previousSequence = -1;
  for (const rawMessage of manifest.messages) {
    const message = record(rawMessage);
    exact(message, ["message_sequence", "role", "kind", "clause_count"]);
    if (
      !integer(message.message_sequence, 1_000_000_000)
      || (message.message_sequence as number) <= previousSequence
      || !TEXT_ROLES.includes(message.role as typeof TEXT_ROLES[number])
      || !TEXT_KINDS.includes(message.kind as typeof TEXT_KINDS[number])
      || !integer(message.clause_count, 128)
    ) throw new RequirementPlanEvidencePayloadError();
    previousSequence = message.message_sequence as number;
    if (
      (message.role === "user" && (message.kind === "request" || message.kind === "feedback"))
      || (message.role === "agent" && message.kind === "plan")
    ) candidateCount += message.clause_count as number;
  }
  if (manifest.candidate_clause_count !== candidateCount) {
    throw new RequirementPlanEvidencePayloadError();
  }
  return manifest;
}

export function parseRequirementPlanEvidenceContract(
  value: unknown,
  expectedSessionId: string,
): RequirementPlanEvidenceContract {
  const contract = record(value);
  exact(contract, [
    "schema_version", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "expected_predecessor_confirmation_id", "registry_version", "contract_set_fingerprint",
    "metric_key", "metric_contract_fingerprint", "source_projection_version",
    "clause_algorithm", "clause_algorithm_spec", "review_rubric_version", "review_rubric",
    "allowed_dispositions", "allowed_user_clause_classifications", "allowed_exclusion_reasons",
    "max_reviewed_user_clause_count", "max_active_requirement_count",
    "max_excluded_user_clause_count", "max_plan_item_count", "max_link_count",
    "max_file_bytes", "max_json_depth",
    "max_json_items", "max_clauses_per_message", "max_lifetime_seconds",
    "canonical_json_required", "canonicalization", "payload_digest",
    "utf8_without_bom_required", "duplicate_keys_allowed",
    "floating_point_values_allowed", "candidate_unit", "opportunity_unit",
    "complete_user_clause_classification_required", "compound_clause_coarsening_disclosed",
    "one_active_requirement_coordinate_is_one_opportunity",
    "excluded_user_clauses_are_excluded_from_metric", "uncertain_classification_policy",
    "import_creates_unconfirmed_proposal_only",
    "native_confirmation_required_for_metric_authority", "raw_payload_persisted",
    "prose_allowed", "scores_allowed", "untrusted_structured_classification_proposals_allowed",
    "authoritative_model_judgment_claims_allowed", "raw_producer_claim_persisted",
    "durable_producer_claim_shape",
    "objective_receipt_claims_allowed", "import_confirmation",
    "file_json_schema_sha256", "file_json_schema", "source_manifest",
    "file_constraint_contract_version",
    "file_constraint_codes",
  ]);
  if (
    contract.schema_version !== "requirement-plan-evidence-file-v1"
    || contract.session_id !== expectedSessionId
    || !safeId(expectedSessionId)
    || !safeId(contract.expected_source_run_id)
    || !safeId(contract.source_window_fingerprint)
    || !optionalSafeId(contract.expected_predecessor_confirmation_id)
    || contract.registry_version !== METRIC_CONTRACT_V2_REGISTRY_VERSION
    || contract.contract_set_fingerprint !== METRIC_CONTRACT_V2_SET_FINGERPRINT
    || contract.metric_key !== "logic.decomposition_coverage"
    || contract.metric_contract_fingerprint
      !== METRIC_V2_CONTRACT_IDENTITIES["logic.decomposition_coverage"].fingerprint
    || !PROJECTIONS.includes(contract.source_projection_version as typeof PROJECTIONS[number])
    || contract.clause_algorithm !== "message-clause-coordinates-en-pl-v1"
    || contract.review_rubric_version !== "active-requirement-plan-review-rubric-v1"
    || !Array.isArray(contract.allowed_dispositions)
    || contract.allowed_dispositions.length !== DISPOSITIONS.length
    || contract.allowed_dispositions.some((item, index) => item !== DISPOSITIONS[index])
    || !Array.isArray(contract.allowed_user_clause_classifications)
    || contract.allowed_user_clause_classifications.length !== USER_CLASSIFICATIONS.length
    || contract.allowed_user_clause_classifications.some(
      (item, index) => item !== USER_CLASSIFICATIONS[index],
    )
    || !Array.isArray(contract.allowed_exclusion_reasons)
    || contract.allowed_exclusion_reasons.length !== EXCLUSION_REASONS.length
    || contract.allowed_exclusion_reasons.some((item, index) => item !== EXCLUSION_REASONS[index])
    || contract.max_reviewed_user_clause_count !== 1_000
    || contract.max_active_requirement_count !== 1_000
    || contract.max_excluded_user_clause_count !== 1_000
    || contract.max_plan_item_count !== 1_000
    || contract.max_link_count !== 4_000
    || contract.max_file_bytes !== MAX_REQUIREMENT_PLAN_FILE_BYTES
    || contract.max_json_depth !== 8
    || contract.max_json_items !== 6_000
    || contract.max_clauses_per_message !== 128
    || contract.max_lifetime_seconds !== 86_400
    || contract.canonical_json_required !== true
    || contract.canonicalization !== "json-sort-keys-compact-ensure-ascii-v1"
    || contract.payload_digest !== "sha256"
    || contract.utf8_without_bom_required !== true
    || contract.duplicate_keys_allowed !== false
    || contract.floating_point_values_allowed !== false
    || contract.candidate_unit !== "reviewable_user_request_or_feedback_clause"
    || contract.opportunity_unit !== "reviewed_active_requirement_clause"
    || contract.complete_user_clause_classification_required !== true
    || contract.compound_clause_coarsening_disclosed !== true
    || contract.one_active_requirement_coordinate_is_one_opportunity !== true
    || contract.excluded_user_clauses_are_excluded_from_metric !== true
    || contract.uncertain_classification_policy !== "reject_or_leave_proposal_unconfirmed"
    || contract.import_creates_unconfirmed_proposal_only !== true
    || contract.native_confirmation_required_for_metric_authority !== true
    || contract.raw_payload_persisted !== false
    || contract.prose_allowed !== false
    || contract.scores_allowed !== false
    || contract.untrusted_structured_classification_proposals_allowed !== true
    || contract.authoritative_model_judgment_claims_allowed !== false
    || contract.raw_producer_claim_persisted !== false
    || contract.durable_producer_claim_shape !== "installation_keyed_opaque_commitment_only"
    || contract.objective_receipt_claims_allowed !== false
    || contract.import_confirmation !== REQUIREMENT_PLAN_IMPORT_CONFIRMATION
    || contract.file_json_schema_sha256 !== REQUIREMENT_PLAN_FILE_SCHEMA_SHA256
    || canonicalJson(contract.file_json_schema)
      !== canonicalJson(REQUIREMENT_PLAN_FILE_JSON_SCHEMA)
    || contract.file_constraint_contract_version !== "requirement-plan-file-constraints-v1"
    || !Array.isArray(contract.file_constraint_codes)
    || contract.file_constraint_codes.length !== REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES.length
    || contract.file_constraint_codes.some(
      (item, index) => item !== REQUIREMENT_PLAN_FILE_CONSTRAINT_CODES[index],
    )
  ) throw new RequirementPlanEvidencePayloadError();
  clauseAlgorithmSpec(contract.clause_algorithm_spec);
  reviewRubric(contract.review_rubric);
  sourceManifest(contract.source_manifest, {
    sessionId: expectedSessionId,
    sourceRunId: contract.expected_source_run_id as string,
    sourceWindowFingerprint: contract.source_window_fingerprint as string,
  });
  return contract as unknown as RequirementPlanEvidenceContract;
}

export function parseRequirementPlanEvidencePreview(
  value: unknown,
  expectedSessionId: string,
): RequirementPlanEvidencePreview {
  const preview = record(value);
  exact(preview, [
    "payload_sha256", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "expected_predecessor_confirmation_id", "reviewed_user_clause_count",
    "active_requirement_count", "excluded_user_clause_count", "plan_item_count",
    "linked_active_requirement_count", "not_linked_active_requirement_count",
    "pending_active_requirement_count", "link_count", "expires_at", "producer",
    "creates_unconfirmed_proposal_only", "native_confirmation_required_for_metric_authority",
    "can_set_numeric_metric_on_import", "raw_payload_persisted", "raw_producer_claim_persisted",
  ]);
  const counts = [
    preview.reviewed_user_clause_count,
    preview.active_requirement_count,
    preview.excluded_user_clause_count,
    preview.plan_item_count,
    preview.linked_active_requirement_count,
    preview.not_linked_active_requirement_count,
    preview.pending_active_requirement_count,
  ];
  if (
    !safeId(preview.payload_sha256)
    || preview.session_id !== expectedSessionId
    || !safeId(expectedSessionId)
    || !safeId(preview.expected_source_run_id)
    || !safeId(preview.source_window_fingerprint)
    || !optionalSafeId(preview.expected_predecessor_confirmation_id)
    || counts.some((item) => !integer(item, 1_000))
    || !integer(preview.link_count, 4_000)
    || preview.reviewed_user_clause_count !== (
      (preview.active_requirement_count as number)
      + (preview.excluded_user_clause_count as number)
    )
    || preview.active_requirement_count !== (
      (preview.linked_active_requirement_count as number)
      + (preview.not_linked_active_requirement_count as number)
      + (preview.pending_active_requirement_count as number)
    )
    || (preview.linked_active_requirement_count as number) > (preview.link_count as number)
    || ((preview.plan_item_count as number) === 0 && (preview.link_count as number) !== 0)
    || !utcTimestamp(preview.expires_at)
    || preview.creates_unconfirmed_proposal_only !== true
    || preview.native_confirmation_required_for_metric_authority !== true
    || preview.can_set_numeric_metric_on_import !== false
    || preview.raw_payload_persisted !== false
    || preview.raw_producer_claim_persisted !== false
  ) throw new RequirementPlanEvidencePayloadError();
  producer(preview.producer);
  return preview as unknown as RequirementPlanEvidencePreview;
}

export function parseRequirementPlanProposal(value: unknown): RequirementPlanProposal {
  const proposal = record(value);
  exact(proposal, [
    "proposal_id", "session_id", "source_run_id", "source_window_fingerprint",
    "expected_predecessor_confirmation_id", "payload_sha256", "producer_receipt",
    "review_rubric_version", "requirements", "excluded_user_clauses", "plan_items",
    "created_at", "schema_version", "policy_version", "status",
    "decision_id", "decision", "decided_at", "confirmation_authority",
    "local_only", "content_persisted",
  ]);
  if (
    !safeId(proposal.proposal_id)
    || !safeId(proposal.session_id)
    || !safeId(proposal.source_run_id)
    || !safeId(proposal.source_window_fingerprint)
    || !optionalSafeId(proposal.expected_predecessor_confirmation_id)
    || !safeId(proposal.payload_sha256)
    || proposal.review_rubric_version !== "active-requirement-plan-review-rubric-v1"
    || !Array.isArray(proposal.requirements) || proposal.requirements.length > 1_000
    || !Array.isArray(proposal.excluded_user_clauses)
    || proposal.excluded_user_clauses.length > 1_000
    || proposal.requirements.length + proposal.excluded_user_clauses.length > 1_000
    || !Array.isArray(proposal.plan_items) || proposal.plan_items.length > 1_000
    || !utcTimestamp(proposal.created_at)
    || proposal.schema_version !== "requirement-plan-evidence-v1"
    || proposal.policy_version !== "reviewed-requirement-plan-v1"
    || !["proposed", "confirmed", "rejected"].includes(String(proposal.status))
    || !optionalSafeId(proposal.decision_id)
    || !(proposal.decision === null || ["confirm", "reject"].includes(String(proposal.decision)))
    || !(proposal.decided_at === null || utcTimestamp(proposal.decided_at))
    || !(proposal.confirmation_authority === null
      || proposal.confirmation_authority === "owned_native_user_presence")
    || proposal.local_only !== true
    || proposal.content_persisted !== false
  ) throw new RequirementPlanEvidencePayloadError();
  producerReceipt(proposal.producer_receipt);

  const plans = proposal.plan_items.map(coordinate);
  const planKeys = plans.map(coordinateKey);
  if (
    new Set(planKeys).size !== planKeys.length
    || planKeys.some((item, index) => index > 0 && item <= planKeys[index - 1])
  ) throw new RequirementPlanEvidencePayloadError();

  const requirementKeys: string[] = [];
  let linkCount = 0;
  for (const candidate of proposal.requirements) {
    const requirement = record(candidate);
    exact(requirement, ["coordinate", "disposition", "plan_indexes"]);
    const point = coordinate(requirement.coordinate);
    const planIndexes = Array.isArray(requirement.plan_indexes)
      ? requirement.plan_indexes
      : null;
    requirementKeys.push(coordinateKey(point));
    if (
      !DISPOSITIONS.includes(requirement.disposition as typeof DISPOSITIONS[number])
      || planIndexes === null
      || planIndexes.length > 1_000
      || planIndexes.some((item) => (
        !integer(item, 999) || (item as number) >= plans.length
      ))
      || new Set(planIndexes).size !== planIndexes.length
      || planIndexes.some((item, index) => index > 0 && item <= planIndexes[index - 1])
      || planIndexes.some((item) => (
        plans[item as number].message_sequence < point.message_sequence
      ))
      || ((requirement.disposition === "linked") !== (planIndexes.length > 0))
    ) throw new RequirementPlanEvidencePayloadError();
    linkCount += planIndexes.length;
  }
  if (
    linkCount > 4_000
    || new Set(requirementKeys).size !== requirementKeys.length
    || requirementKeys.some((item, index) => index > 0 && item <= requirementKeys[index - 1])
  ) throw new RequirementPlanEvidencePayloadError();

  const excluded = proposal.excluded_user_clauses.map(excludedClause);
  const excludedKeys = excluded.map((item) => coordinateKey(item.coordinate));
  const activeKeySet = new Set(requirementKeys);
  if (
    new Set(excludedKeys).size !== excludedKeys.length
    || excludedKeys.some((item, index) => index > 0 && item <= excludedKeys[index - 1])
    || excludedKeys.some((item) => activeKeySet.has(item))
    || excluded.some((item) => (
      (item.reason === "superseded" || item.reason === "withdrawn")
      && item.basis_coordinate !== null
      && coordinateKey(item.basis_coordinate) <= coordinateKey(item.coordinate)
    ))
    || excluded.some((item) => (
      item.reason === "duplicate"
      && item.basis_coordinate !== null
      && !activeKeySet.has(coordinateKey(item.basis_coordinate))
    ))
  ) throw new RequirementPlanEvidencePayloadError();

  const proposed = proposal.status === "proposed";
  const confirmed = proposal.status === "confirmed";
  if (
    proposed !== (
      proposal.decision_id === null
      && proposal.decision === null
      && proposal.decided_at === null
      && proposal.confirmation_authority === null
    )
    || (!proposed && (
      proposal.decision_id === null
      || proposal.decided_at === null
      || proposal.confirmation_authority !== "owned_native_user_presence"
      || (confirmed ? proposal.decision !== "confirm" : proposal.decision !== "reject")
    ))
  ) throw new RequirementPlanEvidencePayloadError();
  return { ...proposal, excluded_user_clauses: excluded } as unknown as RequirementPlanProposal;
}

export function parseRequirementPlanImport(
  value: unknown,
  expected: RequirementPlanEvidencePreview,
): RequirementPlanImport {
  const imported = record(value);
  exact(imported, [
    "payload_sha256", "proposal", "applied", "creates_unconfirmed_proposal_only",
    "native_confirmation_required_for_metric_authority", "raw_payload_persisted",
  ]);
  const proposal = parseRequirementPlanProposal(imported.proposal);
  if (
    imported.payload_sha256 !== expected.payload_sha256
    || proposal.payload_sha256 !== expected.payload_sha256
    || proposal.session_id !== expected.session_id
    || proposal.source_run_id !== expected.expected_source_run_id
    || proposal.source_window_fingerprint !== expected.source_window_fingerprint
    || proposal.expected_predecessor_confirmation_id
      !== expected.expected_predecessor_confirmation_id
    || proposal.status !== "proposed"
    || typeof imported.applied !== "boolean"
    || imported.creates_unconfirmed_proposal_only !== true
    || imported.native_confirmation_required_for_metric_authority !== true
    || imported.raw_payload_persisted !== false
  ) throw new RequirementPlanEvidencePayloadError();
  return { ...imported, proposal } as RequirementPlanImport;
}

export function parseRequirementPlanProposalPage(
  value: unknown,
  expectedSessionId: string,
  expectedLimit: number,
  expectedOffset: number,
  expectedSnapshot: RequirementPlanProposalPageSnapshot | null = null,
): RequirementPlanProposalPage {
  const page = record(value);
  exact(page, [
    "session_id", "proposals", "limit", "offset", "total", "snapshot", "next_offset", "complete",
  ]);
  if (
    page.session_id !== expectedSessionId
    || !safeId(expectedSessionId)
    || page.limit !== expectedLimit
    || page.offset !== expectedOffset
    || !integer(page.total, 1_000_000)
    || !Array.isArray(page.proposals)
    || page.proposals.length > expectedLimit
    || typeof page.complete !== "boolean"
    || !(page.next_offset === null
      || (integer(page.next_offset, 1_000_000) && page.next_offset > expectedOffset))
  ) throw new RequirementPlanEvidencePayloadError();
  const snapshot = parseRequirementPlanProposalPageSnapshot(page.snapshot);
  if (
    snapshot.total !== page.total
    || (expectedSnapshot !== null
      && canonicalJson(snapshot) !== canonicalJson(expectedSnapshot))
  ) throw new RequirementPlanEvidencePayloadError();
  const proposals = page.proposals.map(parseRequirementPlanProposal);
  if (proposals.some((item) => item.session_id !== expectedSessionId)) {
    throw new RequirementPlanEvidencePayloadError();
  }
  const consumed = expectedOffset + proposals.length;
  if (
    (page.complete && (page.next_offset !== null || consumed < (page.total as number)))
    || (!page.complete && (page.next_offset !== consumed || consumed >= (page.total as number)))
  ) throw new RequirementPlanEvidencePayloadError();
  return { ...page, proposals, snapshot } as RequirementPlanProposalPage;
}

export function parseRequirementPlanProposalPageSnapshot(
  value: unknown,
): RequirementPlanProposalPageSnapshot {
  const snapshot = record(value);
  exact(snapshot, [
    "snapshot_id", "total", "decision_count", "high_water_created_at",
    "high_water_proposal_id",
  ]);
  const hasBoundary = snapshot.high_water_created_at !== null
    && snapshot.high_water_proposal_id !== null;
  if (
    !safeId(snapshot.snapshot_id)
    || !integer(snapshot.total, 1_000_000)
    || !integer(snapshot.decision_count, 1_000_000)
    || (snapshot.decision_count as number) > (snapshot.total as number)
    || !(snapshot.high_water_created_at === null || utcTimestamp(snapshot.high_water_created_at))
    || !optionalSafeId(snapshot.high_water_proposal_id)
    || hasBoundary !== ((snapshot.total as number) > 0)
    || ((snapshot.high_water_created_at === null) !== (snapshot.high_water_proposal_id === null))
  ) throw new RequirementPlanEvidencePayloadError();
  return snapshot as unknown as RequirementPlanProposalPageSnapshot;
}

export function parseRequirementPlanProposalReview(
  value: unknown,
  expected: {
    sessionId: string;
    proposal: RequirementPlanProposal;
    contract: RequirementPlanEvidenceContract;
  },
): RequirementPlanProposalReview {
  const review = record(value);
  exact(review, [
    "proposal_id", "session_id", "source_run_id", "source_window_fingerprint",
    "review_receipt_id", "payload_sha256", "manifest_fingerprint",
    "reviewed_graph_fingerprint", "reviewed_candidate_set_fingerprint",
    "candidate_clauses", "review_context_expires_at", "review_receipt_expires_at",
    "all_coordinates_structurally_valid", "raw_text_persisted", "local_only",
  ]);
  const { contract, proposal, sessionId } = expected;
  if (
    review.proposal_id !== proposal.proposal_id
    || review.session_id !== sessionId
    || review.session_id !== proposal.session_id
    || review.source_run_id !== proposal.source_run_id
    || review.source_run_id !== contract.expected_source_run_id
    || review.source_window_fingerprint !== proposal.source_window_fingerprint
    || review.source_window_fingerprint !== contract.source_window_fingerprint
    || review.payload_sha256 !== proposal.payload_sha256
    || proposal.expected_predecessor_confirmation_id
      !== contract.expected_predecessor_confirmation_id
    || review.manifest_fingerprint !== contract.source_manifest.manifest_fingerprint
    || !safeId(review.review_receipt_id)
    || !safeId(review.reviewed_graph_fingerprint)
    || !safeId(review.reviewed_candidate_set_fingerprint)
    || !utcTimestamp(review.review_context_expires_at)
    || review.review_context_expires_at !== contract.source_manifest.review_context_expires_at
    || !utcTimestamp(review.review_receipt_expires_at)
    || Date.parse(review.review_receipt_expires_at as string)
      > Date.parse(review.review_context_expires_at as string)
    || !Array.isArray(review.candidate_clauses)
    || review.candidate_clauses.length !== contract.source_manifest.candidate_clause_count
    || review.all_coordinates_structurally_valid !== true
    || review.raw_text_persisted !== false
    || review.local_only !== true
  ) throw new RequirementPlanEvidencePayloadError();

  const messageBySequence = new Map(
    contract.source_manifest.messages.map((message) => [message.message_sequence, message]),
  );
  const expectedCandidates = contract.source_manifest.messages.flatMap((message) => {
    const eligible = (
      message.role === "user" && (message.kind === "request" || message.kind === "feedback")
    ) || (message.role === "agent" && message.kind === "plan");
    return eligible
      ? Array.from({ length: message.clause_count }, (_, clauseIndex) => ({
        message_sequence: message.message_sequence,
        clause_index: clauseIndex,
      }))
      : [];
  });
  const requirementByCoordinate = new Map(
    proposal.requirements.map((item) => [coordinateKey(item.coordinate), item]),
  );
  const excludedByCoordinate = new Map(
    proposal.excluded_user_clauses.map((item) => [coordinateKey(item.coordinate), item]),
  );
  const planByCoordinate = new Map(
    proposal.plan_items.map((item, index) => [coordinateKey(item), index]),
  );
  const expectedUserKeys = new Set(contract.source_manifest.messages.flatMap((message) => (
    message.role === "user" && (message.kind === "request" || message.kind === "feedback")
      ? Array.from({ length: message.clause_count }, (_, clauseIndex) => (
        coordinateKey({ message_sequence: message.message_sequence, clause_index: clauseIndex })
      ))
      : []
  )));
  const expectedPlanKeys = new Set(contract.source_manifest.messages.flatMap((message) => (
    message.role === "agent" && message.kind === "plan"
      ? Array.from({ length: message.clause_count }, (_, clauseIndex) => (
        coordinateKey({ message_sequence: message.message_sequence, clause_index: clauseIndex })
      ))
      : []
  )));
  const proposedUserKeys = new Set([
    ...proposal.requirements.map((item) => coordinateKey(item.coordinate)),
    ...proposal.excluded_user_clauses.map((item) => coordinateKey(item.coordinate)),
  ]);
  if (
    proposedUserKeys.size !== expectedUserKeys.size
    || [...proposedUserKeys].some((key) => !expectedUserKeys.has(key))
    || [...expectedUserKeys].some((key) => !proposedUserKeys.has(key))
    || [...planByCoordinate.keys()].some((key) => !expectedPlanKeys.has(key))
    || proposal.excluded_user_clauses.some((item) => (
      item.basis_coordinate !== null
      && !expectedUserKeys.has(coordinateKey(item.basis_coordinate))
    ))
  ) throw new RequirementPlanEvidencePayloadError();

  const parsedClauses = review.candidate_clauses.map((rawClause, index) => {
    const clause = record(rawClause);
    exact(clause, [
      "message_sequence", "clause_index", "role", "kind", "text", "candidate_kind",
      "included_in_proposal", "classification", "exclusion_reason", "basis_coordinate",
      "disposition", "linked_plan_coordinates",
    ]);
    const point = coordinate({
      message_sequence: clause.message_sequence,
      clause_index: clause.clause_index,
    });
    const expectedPoint = expectedCandidates[index];
    const message = messageBySequence.get(point.message_sequence);
    if (
      expectedPoint === undefined
      || coordinateKey(point) !== coordinateKey(expectedPoint)
      || message === undefined
      || clause.role !== message.role
      || clause.kind !== message.kind
      || !normalizedClauseText(clause.text)
      || typeof clause.included_in_proposal !== "boolean"
      || !Array.isArray(clause.linked_plan_coordinates)
      || clause.linked_plan_coordinates.length > 1_000
    ) throw new RequirementPlanEvidencePayloadError();
    const links = clause.linked_plan_coordinates.map(coordinate);
    const basis = clause.basis_coordinate === null ? null : coordinate(clause.basis_coordinate);
    const linkKeys = links.map(coordinateKey);
    if (
      new Set(linkKeys).size !== linkKeys.length
      || linkKeys.some((item, linkIndex) => linkIndex > 0 && item <= linkKeys[linkIndex - 1])
    ) throw new RequirementPlanEvidencePayloadError();

    const key = coordinateKey(point);
    if (message.role === "user") {
      const requirement = requirementByCoordinate.get(key);
      const excluded = excludedByCoordinate.get(key);
      const expectedLinks = requirement?.plan_indexes.map((planIndex) => (
        proposal.plan_items[planIndex]
      ));
      const activeShape = requirement !== undefined
        && excluded === undefined
        && clause.classification === "active_requirement"
        && clause.exclusion_reason === null
        && basis === null
        && clause.disposition === requirement.disposition
        && expectedLinks !== undefined
        && !expectedLinks.some((item) => item === undefined)
        && canonicalJson(links) === canonicalJson(expectedLinks);
      const excludedShape = requirement === undefined
        && excluded !== undefined
        && clause.classification === "excluded_from_active_requirement_denominator"
        && clause.exclusion_reason === excluded.reason
        && canonicalJson(basis) === canonicalJson(excluded.basis_coordinate)
        && clause.disposition === null
        && links.length === 0;
      if (
        clause.candidate_kind !== "user_clause"
        || clause.included_in_proposal !== true
        || (!activeShape && !excludedShape)
      ) throw new RequirementPlanEvidencePayloadError();
    } else if (
      clause.candidate_kind !== "plan"
      || clause.included_in_proposal !== planByCoordinate.has(key)
      || clause.classification !== null
      || clause.exclusion_reason !== null
      || basis !== null
      || clause.disposition !== null
      || links.length !== 0
    ) throw new RequirementPlanEvidencePayloadError();
    return { ...clause, basis_coordinate: basis, linked_plan_coordinates: links };
  });
  return { ...review, candidate_clauses: parsedClauses } as unknown as RequirementPlanProposalReview;
}

export function parseRequirementPlanProposalOutcome(
  value: unknown,
  expected: { sessionId: string; proposalId: string; sourceRunId: string; decision: "confirm" | "reject" },
): RequirementPlanProposalOutcome {
  const outcome = record(value);
  exact(outcome, ["proposal", "applied"]);
  const proposal = parseRequirementPlanProposal(outcome.proposal);
  if (
    proposal.session_id !== expected.sessionId
    || proposal.proposal_id !== expected.proposalId
    || proposal.source_run_id !== expected.sourceRunId
    || proposal.decision !== expected.decision
    || proposal.status !== (expected.decision === "confirm" ? "confirmed" : "rejected")
    || typeof outcome.applied !== "boolean"
  ) throw new RequirementPlanEvidencePayloadError();
  return { proposal, applied: outcome.applied };
}
