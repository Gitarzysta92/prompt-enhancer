import type {
  RequirementActionCandidate,
  RequirementActionCandidateManifest,
  RequirementActionEvidenceContract,
  RequirementActionEvidencePreview,
  RequirementActionImport,
  RequirementActionProposal,
  RequirementActionProposalOutcome,
  RequirementActionProposalPage,
  RequirementActionProposalPageSnapshot,
  RequirementActionProposalReview,
  RequirementActionRequirement,
} from "./contracts";

export class RequirementActionEvidencePayloadError extends Error {
  constructor() {
    super("Requirement-action evidence response was invalid");
    this.name = "RequirementActionEvidencePayloadError";
  }
}

export const REQUIREMENT_ACTION_MEDIA_TYPE =
  "application/vnd.prompt-enhancer.requirement-action-evidence+json";
export const REQUIREMENT_ACTION_IMPORT_CONFIRMATION =
  "import_requirement_action_proposal_without_metric_authority" as const;
export const REQUIREMENT_ACTION_REVIEW_CONFIRMATION =
  "open_exact_local_requirement_action_review" as const;
export const REQUIREMENT_ACTION_DECISION_CONFIRMATION =
  "decide_exact_reviewed_requirement_action_proposal" as const;
export const MAX_REQUIREMENT_ACTION_FILE_BYTES = 64 * 1024;

const HEX_64 = /^[0-9a-f]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const UTC_MICROSECOND = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/;
export const REQUIREMENT_ACTION_FILE_SCHEMA_SHA256 =
  "e25e6c1902cc2c7c1f0bdf138c4ac383c0b858e5516cceb05d9be89b6e46c500";
const PSEUDONYM_SCHEMA_PATTERN = "^[a-f0-9]{64}$";

/** Exact canonical JSON Schema returned to local agents for the r7 proposal file. */
export const REQUIREMENT_ACTION_FILE_JSON_SCHEMA: Record<string, unknown> = {
  $defs: {
    RequirementActionLinkEntry: {
      additionalProperties: false,
      description: "File proposal for one exact requirement and zero or more actions.",
      properties: {
        action_candidate_indexes: {
          default: [],
          items: { type: "integer" },
          maxItems: 4_000,
          title: "Action Candidate Indexes",
          type: "array",
          uniqueItems: true,
        },
        requirement_index: {
          exclusiveMaximum: 1_000,
          minimum: 0,
          title: "Requirement Index",
          type: "integer",
        },
      },
      required: ["requirement_index"],
      title: "RequirementActionLinkEntry",
      type: "object",
    },
    RequirementPlanProducer: {
      additionalProperties: false,
      description: "Ephemeral, explicitly untrusted producer claim from the submitted file.",
      properties: {
        authority: { const: "untrusted_provenance_claim", title: "Authority", type: "string" },
        kind: { const: "local_coding_agent", title: "Kind", type: "string" },
        model_id: { title: "Model Id", type: "string" },
        producer_id: { title: "Producer Id", type: "string" },
        producer_version: { title: "Producer Version", type: "string" },
      },
      required: ["kind", "producer_id", "producer_version", "model_id", "authority"],
      title: "RequirementPlanProducer",
      type: "object",
    },
  },
  additionalProperties: false,
  description: "Portable untrusted proposal; it contains no action-state fields.",
  properties: {
    candidate_manifest_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN,
      title: "Candidate Manifest Fingerprint",
      type: "string",
    },
    complete_action_candidate_enumeration: {
      const: true,
      title: "Complete Action Candidate Enumeration",
      type: "boolean",
    },
    complete_requirement_enumeration: {
      const: true,
      title: "Complete Requirement Enumeration",
      type: "boolean",
    },
    complete_requirement_link_classification: {
      const: true,
      title: "Complete Requirement Link Classification",
      type: "boolean",
    },
    contains_action_state_claims: {
      const: false, title: "Contains Action State Claims", type: "boolean",
    },
    contains_metric_values: {
      const: false, title: "Contains Metric Values", type: "boolean",
    },
    contains_objective_proof_claims: {
      const: false, title: "Contains Objective Proof Claims", type: "boolean",
    },
    contains_paths: { const: false, title: "Contains Paths", type: "boolean" },
    contains_prose: { const: false, title: "Contains Prose", type: "boolean" },
    created_at: { format: "date-time", title: "Created At", type: "string" },
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
    links: {
      items: { $ref: "#/$defs/RequirementActionLinkEntry" },
      maxItems: 1_000,
      title: "Links",
      type: "array",
    },
    nonce: { pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Nonce", type: "string" },
    producer: { $ref: "#/$defs/RequirementPlanProducer" },
    requirement_plan_confirmation_id: {
      pattern: PSEUDONYM_SCHEMA_PATTERN,
      title: "Requirement Plan Confirmation Id",
      type: "string",
    },
    requirement_plan_evidence_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN,
      title: "Requirement Plan Evidence Fingerprint",
      type: "string",
    },
    schema_version: {
      const: "requirement-action-evidence-file-v1",
      title: "Schema Version",
      type: "string",
    },
    session_id: { pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Session Id", type: "string" },
    source_window_fingerprint: {
      pattern: PSEUDONYM_SCHEMA_PATTERN, title: "Source Window Fingerprint", type: "string",
    },
  },
  required: [
    "schema_version", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "requirement_plan_confirmation_id", "requirement_plan_evidence_fingerprint",
    "candidate_manifest_fingerprint", "nonce", "created_at", "expires_at", "producer",
    "complete_requirement_enumeration", "complete_action_candidate_enumeration",
    "complete_requirement_link_classification", "links", "contains_action_state_claims",
    "contains_objective_proof_claims", "contains_metric_values", "contains_prose",
    "contains_paths",
  ],
  title: "RequirementActionEvidenceFileV1",
  type: "object",
  "x-prompt-enhancer-canonicalization": "json-sort-keys-compact-ensure-ascii-v1",
  "x-prompt-enhancer-complete-graph-required": true,
  "x-prompt-enhancer-empty-indexes-mean-reviewed-no-link": true,
};
const EVENT_KINDS = ["tool_start", "tool_end", "artifact"] as const;
const TOOL_CATEGORIES = [
  "file_read", "file_write", "command", "search", "test", "build",
  "version_control", "network", "mcp", "subagent", "other", "unknown",
] as const;
const ACTION_FAMILIES = ["tool", "command", "file_change", "review", "other_documented"] as const;
const ACTION_STATES = ["started", "completed", "failed", "cancelled", "unknown"] as const;
const PROVIDERS = ["codex", "claude_code", "synthetic"] as const;
const STATUSES = ["proposed", "confirmed", "rejected"] as const;
const ACTION_DESCRIPTOR_ALGORITHM_VERSION =
  "provider-local-redacted-action-descriptor-v1" as const;
const CANDIDATE_METADATA_FINGERPRINT_VERSION =
  "requirement-action-candidate-metadata-v1" as const;
export const REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION =
  "requirement-action-review-visible-display-v1" as const;
const FORBIDDEN_REVIEW_DISPLAY = /[\p{Cc}\p{Cf}\p{Cs}\u2028\u2029]/u;

type Row = Record<string, unknown>;

function fail(): never { throw new RequirementActionEvidencePayloadError(); }

function record(value: unknown): Row {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Row;
}

function exact(value: Row, keys: readonly string[]): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail();
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
  fail();
}

function oneOf<T extends string>(value: unknown, values: readonly T[]): T {
  if (typeof value !== "string" || !values.includes(value as T)) fail();
  return value as T;
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

function visibleReviewText(value: unknown, maximum: number): value is string {
  return typeof value === "string"
    && value.length >= 1
    && [...value].length <= maximum
    && !FORBIDDEN_REVIEW_DISPLAY.test(value);
}

export function requirementActionUtcMicrosecondKey(value: string): string {
  const match = UTC_MICROSECOND.exec(value);
  if (match === null) fail();
  const parsed = new Date(value);
  if (
    Number.isNaN(parsed.getTime())
    || parsed.getUTCFullYear() !== Number(match[1])
    || parsed.getUTCMonth() + 1 !== Number(match[2])
    || parsed.getUTCDate() !== Number(match[3])
    || parsed.getUTCHours() !== Number(match[4])
    || parsed.getUTCMinutes() !== Number(match[5])
    || parsed.getUTCSeconds() !== Number(match[6])
  ) fail();
  return `${match[1]}${match[2]}${match[3]}${match[4]}${match[5]}${match[6]}`
    + (match[7] ?? "").padEnd(6, "0");
}

function utc(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try { requirementActionUtcMicrosecondKey(value); return true; } catch { return false; }
}

function coordinate(value: unknown): { message_sequence: number; clause_index: number } {
  const item = record(value);
  exact(item, ["message_sequence", "clause_index"]);
  if (!integer(item.message_sequence, 1_000_000_000) || !integer(item.clause_index, 127)) fail();
  return item as { message_sequence: number; clause_index: number };
}

function coordinateKey(value: { message_sequence: number; clause_index: number }): string {
  return `${value.message_sequence.toString().padStart(10, "0")}:${value.clause_index.toString().padStart(3, "0")}`;
}

function producer(value: unknown): Row {
  const item = record(value);
  exact(item, ["kind", "producer_id", "producer_version", "model_id", "authority"]);
  if (
    item.kind !== "local_coding_agent"
    || item.authority !== "untrusted_provenance_claim"
    || !safeCode(item.producer_id)
    || !safeCode(item.producer_version)
    || !safeCode(item.model_id)
  ) fail();
  return item;
}

function producerReceipt(value: unknown): Row {
  const item = record(value);
  exact(item, ["kind", "claim_fingerprint", "authority", "raw_claim_persisted"]);
  if (
    item.kind !== "local_coding_agent"
    || !safeId(item.claim_fingerprint)
    || item.authority !== "untrusted_provenance_claim_commitment"
    || item.raw_claim_persisted !== false
  ) fail();
  return item;
}

function provenance(value: unknown): Row {
  const item = record(value);
  exact(item, [
    "provider", "provider_version", "adapter_version", "decoder_key", "decoder_version",
    "source_schema_version", "evidence_schema_version", "extraction_complete",
  ]);
  oneOf(item.provider, PROVIDERS);
  if (
    !safeCode(item.provider_version)
    || !safeCode(item.adapter_version)
    || !safeCode(item.decoder_key)
    || !safeCode(item.decoder_version)
    || !safeCode(item.source_schema_version)
    || item.evidence_schema_version !== 2
    || typeof item.extraction_complete !== "boolean"
  ) fail();
  return item;
}

function candidate(value: unknown, expectedIndex?: number): RequirementActionCandidate {
  const item = record(value);
  exact(item, [
    "candidate_index", "action_id", "source_reference_id", "sequence", "event_kind",
    "tool_category", "occurred_at", "duration_ms", "family", "state",
  ]);
  if (
    !integer(item.candidate_index, 3_999)
    || (expectedIndex !== undefined && item.candidate_index !== expectedIndex)
    || !safeId(item.action_id)
    || !safeId(item.source_reference_id)
    || !integer(item.sequence, 4_000_000_000)
    || !utc(item.occurred_at)
    || !(item.duration_ms === null || integer(item.duration_ms, Number.MAX_SAFE_INTEGER))
  ) fail();
  oneOf(item.event_kind, EVENT_KINDS);
  if (item.tool_category !== null) oneOf(item.tool_category, TOOL_CATEGORIES);
  oneOf(item.family, ACTION_FAMILIES);
  oneOf(item.state, ACTION_STATES);
  return item as unknown as RequirementActionCandidate;
}

function candidateList(value: unknown): RequirementActionCandidate[] {
  if (!Array.isArray(value) || value.length > 4_000) fail();
  const result = value.map((item, index) => candidate(item, index));
  const ids = result.map((item) => item.action_id);
  const sequences = result.map((item) => item.sequence);
  if (
    new Set(ids).size !== ids.length
    || new Set(sequences).size !== sequences.length
    || sequences.some((sequence, index) => index > 0 && sequence <= sequences[index - 1])
  ) fail();
  return result;
}

function manifest(value: unknown, expected: {
  sessionId: string; sourceRunId: string; sourceWindowFingerprint: string;
}): RequirementActionCandidateManifest {
  const item = record(value);
  exact(item, [
    "session_id", "source_run_id", "source_window_fingerprint", "provenance",
    "extraction_complete", "enumeration_complete", "actions", "manifest_fingerprint",
    "schema_version", "local_only", "content_persisted",
  ]);
  const parsedProvenance = provenance(item.provenance);
  const actions = candidateList(item.actions);
  if (
    item.session_id !== expected.sessionId
    || item.source_run_id !== expected.sourceRunId
    || item.source_window_fingerprint !== expected.sourceWindowFingerprint
    || typeof item.extraction_complete !== "boolean"
    || typeof item.enumeration_complete !== "boolean"
    || (item.enumeration_complete === true && item.extraction_complete !== true)
    || item.extraction_complete !== parsedProvenance.extraction_complete
    || !safeId(item.manifest_fingerprint)
    || item.schema_version !== "requirement-action-candidate-manifest-v1"
    || item.local_only !== true
    || item.content_persisted !== false
  ) fail();
  return { ...item, provenance: parsedProvenance, actions } as unknown as RequirementActionCandidateManifest;
}

function requirement(value: unknown, expectedIndex?: number): RequirementActionRequirement {
  const item = record(value);
  exact(item, ["requirement_index", "requirement_id", "coordinate"]);
  if (
    !integer(item.requirement_index, 999)
    || (expectedIndex !== undefined && item.requirement_index !== expectedIndex)
    || !safeId(item.requirement_id)
  ) fail();
  return { ...item, coordinate: coordinate(item.coordinate) } as RequirementActionRequirement;
}

function requirementList(value: unknown): RequirementActionRequirement[] {
  if (!Array.isArray(value) || value.length > 1_000) fail();
  const result = value.map((item, index) => requirement(item, index));
  const ids = result.map((item) => item.requirement_id);
  const coordinates = result.map((item) => coordinateKey(item.coordinate));
  if (
    new Set(ids).size !== ids.length
    || ids.some((id, index) => index > 0 && id <= ids[index - 1])
    || new Set(coordinates).size !== coordinates.length
  ) fail();
  return result;
}

function actionLinks(value: unknown, requirements: RequirementActionRequirement[], candidates: RequirementActionCandidate[]) {
  if (!Array.isArray(value) || value.length !== requirements.length) fail();
  const candidateIds = new Set(candidates.map((item) => item.action_id));
  let linkCount = 0;
  return value.map((raw, index) => {
    const item = record(raw);
    exact(item, ["requirement_id", "action_ids"]);
    if (item.requirement_id !== requirements[index].requirement_id || !Array.isArray(item.action_ids)) fail();
    const actionIds = item.action_ids;
    if (
      actionIds.length > 4_000
      || actionIds.some((id) => !safeId(id) || !candidateIds.has(id))
      || actionIds.some((id, itemIndex) => itemIndex > 0 && id <= actionIds[itemIndex - 1])
    ) fail();
    linkCount += actionIds.length;
    if (linkCount > 8_000) fail();
    return { requirement_id: item.requirement_id, action_ids: actionIds };
  });
}

export function parseRequirementActionEvidenceContract(
  value: unknown,
  expectedSessionId: string,
): RequirementActionEvidenceContract {
  const item = record(value);
  exact(item, [
    "schema_version", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "source_projection_version", "requirement_plan_confirmation_id",
    "requirement_plan_evidence_fingerprint", "candidate_manifest", "requirements",
    "expected_predecessor_confirmation_id", "metric_key", "max_requirement_count",
    "max_candidate_count", "max_link_count", "max_file_bytes", "max_json_depth",
    "max_json_items", "max_lifetime_seconds", "canonicalization",
    "import_creates_unconfirmed_proposal_only", "native_confirmation_required_for_metric_authority",
    "action_descriptor_algorithm_version", "action_descriptor_content_persisted",
    "candidate_metadata_fingerprint_version",
    "all_linked_action_semantics_acknowledgement_required",
    "native_review_displays_every_redacted_invocation_and_effect", "review_rubric_version",
    "review_visible_display_algorithm_version", "review_visible_display_is_injective_one_pass",
    "review_visible_display_never_truncates",
    "every_requirement_requires_one_link_classification",
    "empty_action_links_are_explicit_reviewed_negative_links", "action_states_are_application_issued",
    "action_state_claims_allowed_in_file", "objective_proof_claims_allowed_in_file",
    "metric_values_allowed_in_file", "raw_payload_persisted", "raw_producer_claim_persisted",
    "durable_producer_claim_shape", "import_confirmation", "file_json_schema_sha256",
    "file_json_schema",
  ]);
  if (
    item.schema_version !== "requirement-action-evidence-file-v1"
    || item.session_id !== expectedSessionId
    || !safeId(item.expected_source_run_id)
    || !safeId(item.source_window_fingerprint)
    || ![
      "metric-contract-v2-projection-6",
      "metric-contract-v2-projection-7",
      "metric-contract-v2-projection-8",
    ].includes(item.source_projection_version as string)
    || !safeId(item.requirement_plan_confirmation_id)
    || !safeId(item.requirement_plan_evidence_fingerprint)
    || !optionalSafeId(item.expected_predecessor_confirmation_id)
    || item.metric_key !== "logic.requirement_action_traceability"
    || item.max_requirement_count !== 1_000
    || item.max_candidate_count !== 4_000
    || item.max_link_count !== 8_000
    || item.max_file_bytes !== 65_536
    || item.max_json_depth !== 8
    || item.max_json_items !== 8_000
    || item.max_lifetime_seconds !== 86_400
    || item.canonicalization !== "json-sort-keys-compact-ensure-ascii-v1"
    || item.import_creates_unconfirmed_proposal_only !== true
    || item.native_confirmation_required_for_metric_authority !== true
    || item.action_descriptor_algorithm_version !== ACTION_DESCRIPTOR_ALGORITHM_VERSION
    || item.action_descriptor_content_persisted !== false
    || item.candidate_metadata_fingerprint_version !== CANDIDATE_METADATA_FINGERPRINT_VERSION
    || item.all_linked_action_semantics_acknowledgement_required !== true
    || item.native_review_displays_every_redacted_invocation_and_effect !== true
    || item.review_rubric_version !== "requirement-action-review-rubric-v2"
    || item.review_visible_display_algorithm_version !== REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    || item.review_visible_display_is_injective_one_pass !== true
    || item.review_visible_display_never_truncates !== true
    || item.every_requirement_requires_one_link_classification !== true
    || item.empty_action_links_are_explicit_reviewed_negative_links !== true
    || item.action_states_are_application_issued !== true
    || item.action_state_claims_allowed_in_file !== false
    || item.objective_proof_claims_allowed_in_file !== false
    || item.metric_values_allowed_in_file !== false
    || item.raw_payload_persisted !== false
    || item.raw_producer_claim_persisted !== false
    || item.durable_producer_claim_shape !== "installation_keyed_opaque_commitment_only"
    || item.import_confirmation !== REQUIREMENT_ACTION_IMPORT_CONFIRMATION
    || item.file_json_schema_sha256 !== REQUIREMENT_ACTION_FILE_SCHEMA_SHA256
    || canonicalJson(item.file_json_schema) !== canonicalJson(REQUIREMENT_ACTION_FILE_JSON_SCHEMA)
  ) fail();
  const candidateManifest = manifest(item.candidate_manifest, {
    sessionId: expectedSessionId,
    sourceRunId: item.expected_source_run_id as string,
    sourceWindowFingerprint: item.source_window_fingerprint as string,
  });
  if (!candidateManifest.extraction_complete || !candidateManifest.enumeration_complete) fail();
  const requirements = requirementList(item.requirements);
  return { ...item, candidate_manifest: candidateManifest, requirements } as unknown as RequirementActionEvidenceContract;
}

export function parseRequirementActionEvidencePreview(
  value: unknown,
  expected: { sessionId: string; contract?: RequirementActionEvidenceContract },
): RequirementActionEvidencePreview {
  const item = record(value);
  exact(item, [
    "payload_sha256", "session_id", "expected_source_run_id", "source_window_fingerprint",
    "requirement_plan_confirmation_id", "requirement_plan_evidence_fingerprint",
    "candidate_manifest_fingerprint", "expected_predecessor_confirmation_id",
    "requirement_count", "candidate_count", "linked_requirement_count",
    "unlinked_requirement_count", "link_count", "expires_at", "producer",
    "creates_unconfirmed_proposal_only", "native_confirmation_required_for_metric_authority",
    "can_set_numeric_metric_on_import", "raw_payload_persisted", "raw_producer_claim_persisted",
  ]);
  const contract = expected.contract;
  if (
    !safeId(item.payload_sha256)
    || item.session_id !== expected.sessionId
    || !safeId(item.expected_source_run_id)
    || !safeId(item.source_window_fingerprint)
    || !safeId(item.requirement_plan_confirmation_id)
    || !safeId(item.requirement_plan_evidence_fingerprint)
    || !safeId(item.candidate_manifest_fingerprint)
    || !optionalSafeId(item.expected_predecessor_confirmation_id)
    || !integer(item.requirement_count, 1_000)
    || !integer(item.candidate_count, 4_000)
    || !integer(item.linked_requirement_count, 1_000)
    || !integer(item.unlinked_requirement_count, 1_000)
    || !integer(item.link_count, 8_000)
    || item.requirement_count !== (item.linked_requirement_count as number) + (item.unlinked_requirement_count as number)
    || (item.linked_requirement_count as number) > (item.link_count as number)
    || (item.candidate_count === 0 && item.link_count !== 0)
    || !utc(item.expires_at)
    || item.creates_unconfirmed_proposal_only !== true
    || item.native_confirmation_required_for_metric_authority !== true
    || item.can_set_numeric_metric_on_import !== false
    || item.raw_payload_persisted !== false
    || item.raw_producer_claim_persisted !== false
  ) fail();
  producer(item.producer);
  if (contract !== undefined && (
    item.expected_source_run_id !== contract.expected_source_run_id
    || item.source_window_fingerprint !== contract.source_window_fingerprint
    || item.requirement_plan_confirmation_id !== contract.requirement_plan_confirmation_id
    || item.requirement_plan_evidence_fingerprint !== contract.requirement_plan_evidence_fingerprint
    || item.candidate_manifest_fingerprint !== contract.candidate_manifest.manifest_fingerprint
    || item.expected_predecessor_confirmation_id !== contract.expected_predecessor_confirmation_id
    || item.requirement_count !== contract.requirements.length
    || item.candidate_count !== contract.candidate_manifest.actions.length
  )) fail();
  return item as unknown as RequirementActionEvidencePreview;
}

export function parseRequirementActionProposal(value: unknown): RequirementActionProposal {
  const item = record(value);
  exact(item, [
    "proposal_id", "session_id", "source_run_id", "source_window_fingerprint",
    "requirement_plan_confirmation_id", "requirement_plan_evidence_fingerprint",
    "candidate_manifest_fingerprint", "candidate_provenance", "candidate_extraction_complete",
    "candidate_enumeration_complete", "expected_predecessor_confirmation_id", "payload_sha256",
    "producer_receipt", "review_rubric_version", "requirements", "candidates", "links",
    "created_at", "schema_version", "policy_version", "status", "decision_id", "decision",
    "decided_at", "confirmation_authority", "local_only", "content_persisted",
  ]);
  const ids = [
    item.proposal_id, item.session_id, item.source_run_id, item.source_window_fingerprint,
    item.requirement_plan_confirmation_id, item.requirement_plan_evidence_fingerprint,
    item.candidate_manifest_fingerprint, item.payload_sha256,
  ];
  if (
    ids.some((id) => !safeId(id))
    || !optionalSafeId(item.expected_predecessor_confirmation_id)
    || typeof item.candidate_extraction_complete !== "boolean"
    || typeof item.candidate_enumeration_complete !== "boolean"
    || (item.candidate_enumeration_complete === true && item.candidate_extraction_complete !== true)
    || item.review_rubric_version !== "requirement-action-review-rubric-v2"
    || !utc(item.created_at)
    || item.schema_version !== "requirement-action-evidence-v1"
    || item.policy_version !== "reviewed-requirement-action-v1"
    || item.local_only !== true
    || item.content_persisted !== false
  ) fail();
  const parsedProvenance = provenance(item.candidate_provenance);
  if (parsedProvenance.extraction_complete !== item.candidate_extraction_complete) fail();
  producerReceipt(item.producer_receipt);
  const requirements = requirementList(item.requirements);
  const candidates = candidateList(item.candidates);
  const links = actionLinks(item.links, requirements, candidates);
  const status = oneOf(item.status, STATUSES);
  const decisionExpected = status === "proposed" ? null : status === "confirmed" ? "confirm" : "reject";
  if (
    (status === "proposed") !== (item.decision_id === null && item.decision === null
      && item.decided_at === null && item.confirmation_authority === null)
    || (status !== "proposed" && (!safeId(item.decision_id) || item.decision !== decisionExpected
      || !utc(item.decided_at) || item.confirmation_authority !== "owned_native_user_presence"))
  ) fail();
  return { ...item, candidate_provenance: parsedProvenance, requirements, candidates, links } as unknown as RequirementActionProposal;
}

/** Exact durable proposal-to-contract binding required before native review. */
export function requirementActionProposalMatchesContract(
  proposal: RequirementActionProposal,
  contract: RequirementActionEvidenceContract,
): boolean {
  try {
    return proposal.session_id === contract.session_id
      && proposal.source_run_id === contract.expected_source_run_id
      && proposal.source_window_fingerprint === contract.source_window_fingerprint
      && proposal.requirement_plan_confirmation_id === contract.requirement_plan_confirmation_id
      && proposal.requirement_plan_evidence_fingerprint === contract.requirement_plan_evidence_fingerprint
      && proposal.candidate_manifest_fingerprint === contract.candidate_manifest.manifest_fingerprint
      && proposal.expected_predecessor_confirmation_id === contract.expected_predecessor_confirmation_id
      && proposal.candidate_extraction_complete === contract.candidate_manifest.extraction_complete
      && proposal.candidate_enumeration_complete === contract.candidate_manifest.enumeration_complete
      && canonicalJson(proposal.candidate_provenance)
        === canonicalJson(contract.candidate_manifest.provenance)
      && canonicalJson(proposal.requirements) === canonicalJson(contract.requirements)
      && canonicalJson(proposal.candidates) === canonicalJson(contract.candidate_manifest.actions);
  } catch {
    return false;
  }
}

function snapshot(value: unknown): RequirementActionProposalPageSnapshot {
  const item = record(value);
  exact(item, ["snapshot_id", "total", "decision_count", "high_water_created_at", "high_water_proposal_id"]);
  if (
    !safeId(item.snapshot_id)
    || !integer(item.total, 1_000_000)
    || !integer(item.decision_count, 1_000_000)
    || (item.decision_count as number) > (item.total as number)
    || !(item.high_water_created_at === null || utc(item.high_water_created_at))
    || !optionalSafeId(item.high_water_proposal_id)
    || (item.high_water_created_at === null) !== (item.high_water_proposal_id === null)
    || (item.high_water_created_at !== null) !== ((item.total as number) > 0)
  ) fail();
  return item as unknown as RequirementActionProposalPageSnapshot;
}

export function parseRequirementActionProposalPage(
  value: unknown,
  expected: {
    sessionId: string;
    limit: number;
    offset: number;
    snapshot: RequirementActionProposalPageSnapshot | null;
  },
): RequirementActionProposalPage {
  const item = record(value);
  exact(item, ["session_id", "proposals", "limit", "offset", "total", "snapshot", "next_offset", "complete"]);
  if (
    item.session_id !== expected.sessionId
    || item.limit !== expected.limit
    || item.offset !== expected.offset
    || !integer(item.total, 1_000_000)
    || !Array.isArray(item.proposals)
    || item.proposals.length > expected.limit
    || typeof item.complete !== "boolean"
  ) fail();
  const parsedSnapshot = snapshot(item.snapshot);
  if (
    parsedSnapshot.total !== item.total
    || (expected.snapshot !== null && JSON.stringify(parsedSnapshot) !== JSON.stringify(expected.snapshot))
  ) fail();
  const proposals = item.proposals.map(parseRequirementActionProposal);
  const consumed = expected.offset + proposals.length;
  if (
    consumed > item.total
    || item.complete !== (consumed === item.total)
    || item.next_offset !== (consumed === item.total ? null : consumed)
    || proposals.some((proposal) => proposal.session_id !== expected.sessionId)
  ) fail();
  return { ...item, proposals, snapshot: parsedSnapshot } as unknown as RequirementActionProposalPage;
}

export function parseRequirementActionImport(
  value: unknown,
  expected: RequirementActionEvidencePreview,
): RequirementActionImport {
  const item = record(value);
  exact(item, [
    "payload_sha256", "proposal", "applied", "creates_unconfirmed_proposal_only",
    "native_confirmation_required_for_metric_authority", "raw_payload_persisted",
    "raw_producer_claim_persisted",
  ]);
  const proposal = parseRequirementActionProposal(item.proposal);
  if (
    item.payload_sha256 !== expected.payload_sha256
    || proposal.payload_sha256 !== expected.payload_sha256
    || proposal.session_id !== expected.session_id
    || proposal.source_run_id !== expected.expected_source_run_id
    || proposal.source_window_fingerprint !== expected.source_window_fingerprint
    || proposal.requirement_plan_confirmation_id !== expected.requirement_plan_confirmation_id
    || proposal.requirement_plan_evidence_fingerprint !== expected.requirement_plan_evidence_fingerprint
    || proposal.candidate_manifest_fingerprint !== expected.candidate_manifest_fingerprint
    || proposal.expected_predecessor_confirmation_id !== expected.expected_predecessor_confirmation_id
    || proposal.status !== "proposed"
    || typeof item.applied !== "boolean"
    || item.creates_unconfirmed_proposal_only !== true
    || item.native_confirmation_required_for_metric_authority !== true
    || item.raw_payload_persisted !== false
    || item.raw_producer_claim_persisted !== false
  ) fail();
  return { ...item, proposal } as RequirementActionImport;
}

export function parseRequirementActionProposalReview(
  value: unknown,
  expected: {
    sessionId: string;
    proposal: RequirementActionProposal;
    contract: RequirementActionEvidenceContract;
  },
): RequirementActionProposalReview {
  const item = record(value);
  exact(item, [
    "proposal_id", "session_id", "source_run_id", "source_window_fingerprint",
    "review_receipt_id", "payload_sha256", "requirement_plan_evidence_fingerprint",
    "candidate_manifest_fingerprint", "reviewed_graph_fingerprint",
    "reviewed_candidate_set_fingerprint", "reviewed_descriptor_set_fingerprint",
    "review_visible_display_algorithm_version", "requirements", "candidates",
    "candidate_memberships", "review_context_expires_at", "review_receipt_expires_at",
    "all_requirements_and_candidates_displayed", "raw_text_persisted", "local_only",
  ]);
  const proposal = expected.proposal;
  const contract = expected.contract;
  if (
    !requirementActionProposalMatchesContract(proposal, contract)
    || proposal.status !== "proposed"
    || item.proposal_id !== proposal.proposal_id
    || item.session_id !== expected.sessionId
    || item.source_run_id !== proposal.source_run_id
    || item.source_window_fingerprint !== proposal.source_window_fingerprint
    || !safeId(item.review_receipt_id)
    || item.payload_sha256 !== proposal.payload_sha256
    || item.requirement_plan_evidence_fingerprint !== proposal.requirement_plan_evidence_fingerprint
    || item.candidate_manifest_fingerprint !== proposal.candidate_manifest_fingerprint
    || !safeId(item.reviewed_graph_fingerprint)
    || !safeId(item.reviewed_candidate_set_fingerprint)
    || !safeId(item.reviewed_descriptor_set_fingerprint)
    || item.review_visible_display_algorithm_version !== REQUIREMENT_ACTION_REVIEW_VISIBLE_DISPLAY_VERSION
    || item.review_visible_display_algorithm_version !== contract.review_visible_display_algorithm_version
    || !utc(item.review_context_expires_at)
    || !utc(item.review_receipt_expires_at)
    || item.all_requirements_and_candidates_displayed !== true
    || item.raw_text_persisted !== false
    || item.local_only !== true
    || !Array.isArray(item.requirements)
    || !Array.isArray(item.candidates)
    || !Array.isArray(item.candidate_memberships)
  ) fail();
  const candidates = candidateList(item.candidates);
  if (canonicalJson(candidates) !== canonicalJson(proposal.candidates)
    || canonicalJson(candidates) !== canonicalJson(contract.candidate_manifest.actions)) fail();
  if (item.requirements.length !== proposal.requirements.length) fail();
  const reviewRequirements = item.requirements.map((raw, index) => {
    const value = record(raw);
    exact(value, ["requirement_id", "coordinate", "text", "linked_action_ids"]);
    const point = coordinate(value.coordinate);
    const proposalRequirement = proposal.requirements[index];
    const contractRequirement = contract.requirements[index];
    const proposalLink = proposal.links[index];
    if (
      value.requirement_id !== proposalRequirement.requirement_id
      || value.requirement_id !== contractRequirement.requirement_id
      || coordinateKey(point) !== coordinateKey(proposalRequirement.coordinate)
      || coordinateKey(point) !== coordinateKey(contractRequirement.coordinate)
      || !visibleReviewText(value.text, 32_000)
      || !Array.isArray(value.linked_action_ids)
      || JSON.stringify(value.linked_action_ids) !== JSON.stringify(proposalLink.action_ids)
    ) fail();
    return { ...value, coordinate: point };
  });
  if (item.candidate_memberships.length !== candidates.length) fail();
  const expectedMemberships = new Map(candidates.map((candidate) => [candidate.action_id, [] as string[]]));
  proposal.links.forEach((link) => link.action_ids.forEach((id) => expectedMemberships.get(id)!.push(link.requirement_id)));
  const memberships = item.candidate_memberships.map((raw, index) => {
    const value = record(raw);
    exact(value, [
      "candidate", "candidate_metadata_fingerprint_version", "candidate_metadata_fingerprint",
      "descriptor_algorithm_version", "tool_name", "invocation_preview",
      "result_or_effect_preview", "invocation_truncated", "result_or_effect_truncated",
      "redactor_version", "linked_requirement_ids",
    ]);
    const parsedCandidate = candidate(value.candidate, index);
    if (
      canonicalJson(parsedCandidate) !== canonicalJson(candidates[index])
      || value.candidate_metadata_fingerprint_version !== CANDIDATE_METADATA_FINGERPRINT_VERSION
      || value.candidate_metadata_fingerprint_version !== contract.candidate_metadata_fingerprint_version
      || !safeId(value.candidate_metadata_fingerprint)
      || value.descriptor_algorithm_version !== ACTION_DESCRIPTOR_ALGORITHM_VERSION
      || !visibleReviewText(value.tool_name, 120)
      || !visibleReviewText(value.invocation_preview, 4_096)
      || !(value.result_or_effect_preview === null
        || visibleReviewText(value.result_or_effect_preview, 4_096))
      || (parsedCandidate.event_kind !== "tool_start" && value.result_or_effect_preview === null)
      || value.invocation_truncated !== false
      || value.result_or_effect_truncated !== false
      || !safeCode(value.redactor_version)
      || !Array.isArray(value.linked_requirement_ids)
      || JSON.stringify(value.linked_requirement_ids) !== JSON.stringify(expectedMemberships.get(parsedCandidate.action_id))
    ) fail();
    return { ...value, candidate: parsedCandidate };
  });
  return {
    ...item,
    requirements: reviewRequirements,
    candidates,
    candidate_memberships: memberships,
  } as unknown as RequirementActionProposalReview;
}

export function parseRequirementActionProposalOutcome(
  value: unknown,
  expected: { sessionId: string; proposalId: string; sourceRunId: string; decision: "confirm" | "reject" },
): RequirementActionProposalOutcome {
  const item = record(value);
  exact(item, ["proposal", "applied"]);
  const proposal = parseRequirementActionProposal(item.proposal);
  if (
    typeof item.applied !== "boolean"
    || proposal.session_id !== expected.sessionId
    || proposal.proposal_id !== expected.proposalId
    || proposal.source_run_id !== expected.sourceRunId
    || proposal.decision !== expected.decision
    || proposal.status !== (expected.decision === "confirm" ? "confirmed" : "rejected")
  ) fail();
  return { proposal, applied: item.applied };
}
