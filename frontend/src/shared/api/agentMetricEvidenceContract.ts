import type {
  AgentMetricEvidenceImport,
  AgentMetricEvidencePreview,
  MetricLifecycleProposal,
  MetricLifecycleProposalList,
  MetricLifecycleProposalPage,
  MetricLifecycleProposalOutcome,
} from "./contracts";

export class AgentMetricEvidencePayloadError extends Error {
  constructor() {
    super("Agent metric evidence response was invalid");
    this.name = "AgentMetricEvidencePayloadError";
  }
}

const HEX_64 = /^[a-f0-9]{64}$/;
const SAFE_CODE = /^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$/;
const FAMILIES = [
  "collaboration.ambiguity_resolution",
  "collaboration.clarification_yield",
  "collaboration.exploration_conversion",
  "collaboration.scope_change_discipline",
  "collaboration.rework_candidate_rate",
] as const;
const PROPOSAL_KINDS = ["opportunity", "outcome", "enumeration"] as const;
const OPPORTUNITY_KINDS = ["ambiguity", "clarification", "exploration", "scope_change", "rework"] as const;
const STATUSES = ["proposed", "confirmed", "rejected"] as const;
const DECISIONS = ["confirm", "reject"] as const;
const EVIDENCE_FILE_SCHEMAS = [
  "agent-metric-evidence-file-v1",
  "agent-metric-evidence-file-v2",
] as const;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentMetricEvidencePayloadError();
  }
  return value as Record<string, unknown>;
}

function exact(value: Record<string, unknown>, keys: readonly string[]) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new AgentMetricEvidencePayloadError();
  }
}

function safeId(value: unknown): value is string {
  return typeof value === "string" && HEX_64.test(value);
}

function safeCode(value: unknown): value is string {
  return typeof value === "string" && SAFE_CODE.test(value);
}

function isoUtc(value: unknown): value is string {
  return typeof value === "string"
    && (value.endsWith("Z") || value.endsWith("+00:00"))
    && Number.isFinite(Date.parse(value));
}

function optionalSafeId(value: unknown): value is string | null {
  return value === null || safeId(value);
}

export function parseMetricLifecycleProposal(value: unknown): MetricLifecycleProposal {
  const proposal = record(value);
  exact(proposal, [
    "proposal_id", "session_id", "source_run_id", "proposal_revision",
    "proposal_kind", "family", "opportunity_kind", "opportunity_id", "link_kind",
    "outcome_kind", "enumerated_opportunity_ids", "status", "decision_id", "decision",
    "created_at", "decided_at", "schema_version", "policy_version", "local_only",
    "content_persisted",
  ]);
  const enumeration = Array.isArray(proposal.enumerated_opportunity_ids)
    ? proposal.enumerated_opportunity_ids
    : null;
  if (
    !safeId(proposal.proposal_id) || !safeId(proposal.session_id) || !safeId(proposal.source_run_id)
    || proposal.proposal_revision !== 1
    || !PROPOSAL_KINDS.includes(proposal.proposal_kind as typeof PROPOSAL_KINDS[number])
    || !FAMILIES.includes(proposal.family as typeof FAMILIES[number])
    || !OPPORTUNITY_KINDS.includes(proposal.opportunity_kind as typeof OPPORTUNITY_KINDS[number])
    || !optionalSafeId(proposal.opportunity_id) || !optionalSafeId(proposal.decision_id)
    || enumeration === null || !enumeration.every(safeId)
    || new Set(enumeration).size !== enumeration.length
    || [...enumeration].sort().some((item, index) => item !== enumeration[index])
    || !STATUSES.includes(proposal.status as typeof STATUSES[number])
    || !(proposal.decision === null || DECISIONS.includes(proposal.decision as typeof DECISIONS[number]))
    || !isoUtc(proposal.created_at) || !(proposal.decided_at === null || isoUtc(proposal.decided_at))
    || !safeCode(proposal.schema_version) || !safeCode(proposal.policy_version)
    || proposal.local_only !== true || proposal.content_persisted !== false
    || !(proposal.link_kind === null || safeCode(proposal.link_kind))
    || !(proposal.outcome_kind === null || safeCode(proposal.outcome_kind))
    || (proposal.status === "proposed" && (proposal.decision_id !== null || proposal.decision !== null || proposal.decided_at !== null))
    || (proposal.status !== "proposed" && (proposal.decision_id === null || proposal.decision === null || proposal.decided_at === null))
  ) throw new AgentMetricEvidencePayloadError();
  return proposal as unknown as MetricLifecycleProposal;
}

export function parseAgentMetricEvidencePreview(value: unknown): AgentMetricEvidencePreview {
  const preview = record(value);
  exact(preview, [
    "schema_version", "payload_sha256", "session_id", "expected_source_run_id",
    "source_window_fingerprint", "metric_key", "proposal_kind", "expires_at", "producer",
    "creates_unconfirmed_proposal_only", "requires_authenticated_local_user_confirmation",
    "can_set_numeric_metric", "objective_receipt_claims_accepted", "raw_payload_persisted",
  ]);
  const producer = record(preview.producer);
  exact(producer, ["kind", "producer_id", "producer_version", "model_id", "authority"]);
  if (
    !EVIDENCE_FILE_SCHEMAS.includes(
      preview.schema_version as typeof EVIDENCE_FILE_SCHEMAS[number],
    )
    || !safeId(preview.payload_sha256) || !safeId(preview.session_id)
    || !safeId(preview.expected_source_run_id) || !safeId(preview.source_window_fingerprint)
    || !FAMILIES.includes(preview.metric_key as typeof FAMILIES[number])
    || !PROPOSAL_KINDS.includes(preview.proposal_kind as typeof PROPOSAL_KINDS[number])
    || !isoUtc(preview.expires_at)
    || producer.kind !== "local_coding_agent" || producer.authority !== "untrusted_provenance_claim"
    || !safeCode(producer.producer_id) || !safeCode(producer.producer_version) || !safeCode(producer.model_id)
    || preview.creates_unconfirmed_proposal_only !== true
    || preview.requires_authenticated_local_user_confirmation !== true
    || preview.can_set_numeric_metric !== false
    || preview.objective_receipt_claims_accepted !== false
    || preview.raw_payload_persisted !== false
  ) throw new AgentMetricEvidencePayloadError();
  return preview as unknown as AgentMetricEvidencePreview;
}

export function parseAgentMetricEvidenceImport(value: unknown): AgentMetricEvidenceImport {
  const imported = record(value);
  exact(imported, [
    "payload_sha256", "proposal", "applied", "producer_claim_persisted",
    "raw_payload_persisted", "requires_authenticated_local_user_confirmation",
  ]);
  if (
    !safeId(imported.payload_sha256) || typeof imported.applied !== "boolean"
    || imported.producer_claim_persisted !== false || imported.raw_payload_persisted !== false
    || imported.requires_authenticated_local_user_confirmation !== true
  ) throw new AgentMetricEvidencePayloadError();
  return { ...imported, proposal: parseMetricLifecycleProposal(imported.proposal) } as AgentMetricEvidenceImport;
}

export function parseMetricLifecycleProposalList(value: unknown, sessionId: string): MetricLifecycleProposalList {
  const page = record(value);
  exact(page, ["session_id", "proposals"]);
  if (page.session_id !== sessionId || !safeId(page.session_id) || !Array.isArray(page.proposals) || page.proposals.length > 1_000) {
    throw new AgentMetricEvidencePayloadError();
  }
  const proposals = page.proposals.map(parseMetricLifecycleProposal);
  if (proposals.some((item) => item.session_id !== sessionId)) throw new AgentMetricEvidencePayloadError();
  return { session_id: sessionId, proposals };
}

export function parseMetricLifecycleProposalPage(
  value: unknown,
  sessionId: string,
  expectedLimit: number,
  expectedOffset: number,
): MetricLifecycleProposalPage {
  const page = record(value);
  exact(page, ["session_id", "proposals", "limit", "offset", "total", "next_offset", "complete"]);
  if (
    page.session_id !== sessionId || !safeId(page.session_id)
    || page.limit !== expectedLimit || page.offset !== expectedOffset
    || !Number.isInteger(page.total) || (page.total as number) < 0 || (page.total as number) > 1_000_000
    || !Array.isArray(page.proposals) || page.proposals.length > expectedLimit
    || typeof page.complete !== "boolean"
    || !(page.next_offset === null || (Number.isInteger(page.next_offset) && (page.next_offset as number) > expectedOffset))
  ) throw new AgentMetricEvidencePayloadError();
  const proposals = page.proposals.map(parseMetricLifecycleProposal);
  if (proposals.some((item) => item.session_id !== sessionId)) throw new AgentMetricEvidencePayloadError();
  const consumed = expectedOffset + proposals.length;
  if (
    (page.complete && (page.next_offset !== null || consumed < (page.total as number)))
    || (!page.complete && (page.next_offset !== consumed || consumed >= (page.total as number)))
  ) throw new AgentMetricEvidencePayloadError();
  return { ...page, proposals } as MetricLifecycleProposalPage;
}

export function parseMetricLifecycleProposalOutcome(value: unknown): MetricLifecycleProposalOutcome {
  const outcome = record(value);
  exact(outcome, ["proposal", "applied"]);
  if (typeof outcome.applied !== "boolean") throw new AgentMetricEvidencePayloadError();
  return { proposal: parseMetricLifecycleProposal(outcome.proposal), applied: outcome.applied };
}
