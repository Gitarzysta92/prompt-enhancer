import { describe, expect, it } from "vitest";
import {
  AgentMetricEvidencePayloadError,
  parseAgentMetricEvidenceImport,
  parseAgentMetricEvidencePreview,
  parseMetricLifecycleProposalList,
  parseMetricLifecycleProposalPage,
} from "./agentMetricEvidenceContract";

const proposal = {
  proposal_id: "1".repeat(64),
  session_id: "2".repeat(64),
  source_run_id: "3".repeat(64),
  proposal_revision: 1,
  proposal_kind: "opportunity",
  family: "collaboration.ambiguity_resolution",
  opportunity_kind: "ambiguity",
  opportunity_id: "4".repeat(64),
  link_kind: null,
  outcome_kind: null,
  enumerated_opportunity_ids: [],
  status: "proposed",
  decision_id: null,
  decision: null,
  created_at: "2042-01-01T00:00:00+00:00",
  decided_at: null,
  schema_version: "metric-lifecycle-evidence-v1",
  policy_version: "explicit-local-confirmation-v1",
  local_only: true,
  content_persisted: false,
} as const;

const preview = {
  schema_version: "agent-metric-evidence-file-v1",
  payload_sha256: "5".repeat(64),
  session_id: proposal.session_id,
  expected_source_run_id: proposal.source_run_id,
  source_window_fingerprint: "6".repeat(64),
  metric_key: proposal.family,
  proposal_kind: proposal.proposal_kind,
  expires_at: "2042-01-01T01:00:00+00:00",
  producer: {
    kind: "local_coding_agent",
    producer_id: "example-agent",
    producer_version: "example-agent-v1",
    model_id: "example-model-v1",
    authority: "untrusted_provenance_claim",
  },
  creates_unconfirmed_proposal_only: true,
  requires_authenticated_local_user_confirmation: true,
  can_set_numeric_metric: false,
  objective_receipt_claims_accepted: false,
  raw_payload_persisted: false,
} as const;

describe("agent metric evidence response contract", () => {
  it("accepts exact preview, import, and proposal-list shapes", () => {
    expect(parseAgentMetricEvidencePreview(structuredClone(preview))).toEqual(preview);
    expect(parseAgentMetricEvidencePreview({
      ...structuredClone(preview),
      schema_version: "agent-metric-evidence-file-v2",
    }).schema_version).toBe("agent-metric-evidence-file-v2");
    expect(parseAgentMetricEvidenceImport({
      payload_sha256: preview.payload_sha256,
      proposal,
      applied: true,
      producer_claim_persisted: false,
      raw_payload_persisted: false,
      requires_authenticated_local_user_confirmation: true,
    }).proposal).toEqual(proposal);
    expect(parseMetricLifecycleProposalList({
      session_id: proposal.session_id,
      proposals: [proposal],
    }, proposal.session_id).proposals).toEqual([proposal]);
    expect(parseMetricLifecycleProposalPage({
      session_id: proposal.session_id,
      proposals: [proposal],
      limit: 200,
      offset: 0,
      total: 1,
      next_offset: null,
      complete: true,
    }, proposal.session_id, 200, 0).complete).toBe(true);
  });

  it("rejects score-like extras, cross-session rows, authority drift, and inconsistent decisions", () => {
    const cases: Array<() => unknown> = [
      () => parseAgentMetricEvidencePreview({ ...preview, score: 1 }),
      () => parseAgentMetricEvidencePreview({
        ...preview,
        schema_version: "agent-metric-evidence-file-v3",
      }),
      () => parseAgentMetricEvidencePreview({ ...preview, can_set_numeric_metric: true }),
      () => parseAgentMetricEvidencePreview({
        ...preview,
        producer: { ...preview.producer, authority: "metric_authority" },
      }),
      () => parseMetricLifecycleProposalList({
        session_id: proposal.session_id,
        proposals: [{ ...proposal, session_id: "9".repeat(64) }],
      }, proposal.session_id),
      () => parseAgentMetricEvidenceImport({
        payload_sha256: preview.payload_sha256,
        proposal: { ...proposal, status: "confirmed" },
        applied: true,
        producer_claim_persisted: false,
        raw_payload_persisted: false,
        requires_authenticated_local_user_confirmation: true,
      }),
      () => parseMetricLifecycleProposalPage({
        session_id: proposal.session_id,
        proposals: [proposal],
        limit: 200,
        offset: 0,
        total: 2,
        next_offset: null,
        complete: true,
      }, proposal.session_id, 200, 0),
    ];
    for (const run of cases) expect(run).toThrow(AgentMetricEvidencePayloadError);
  });
});
